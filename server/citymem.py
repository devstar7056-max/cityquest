"""City Memory: a whole slice of a city, live from Google Places, held in one gemini-4-argon context.

build() sweeps a grid of Places Nearby Searches around a center (food and drink plus sights), keeps each
place's live facts, Google's summary and up to four review snippets, and writes one line per place.
prime() sends that snapshot to gemini-4-argon once (stored interaction). Quests then chain from it with
previous_interaction_id, so the Director plans with the entire city in context while each request's
live area scan keeps opening hours fresh. Token counts come from the API's own usage report.
"""
import asyncio
import json
import math
import os
import pathlib
import time

import httpx

from . import area as area_mod
from . import director

ROOT = pathlib.Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "data" / "city_memory.jsonl"
META = ROOT / "data" / "city_memory.json"
FIELDS = area_mod.FIELDS + ",places.reviews"
SYSTEM = ("You are the CityQuest World Director's city memory. The input is a live Google Places snapshot of a city "
          "slice: one JSON object per place with its id, name, category, position, rating, Google's summary and "
          "review snippets. Keep all of it in mind. Later turns give you a person's request plus a fresh live scan "
          "of the places around them; use this memory for what places are like and what people say about them, "
          "and the fresh scan for what is open right now.")
state = {"interaction_id": None, "meta": None}


def load():
    if META.exists():
        state["meta"] = json.loads(META.read_text())
        state["interaction_id"] = state["meta"].get("interaction_id")
    return state


def _compact(p):
    reviews = []
    for r in (p.get("reviews") or [])[:4]:
        t = ((r.get("text") or {}).get("text") or "").replace("\n", " ").strip()
        if t:
            reviews.append(f"{r.get('rating', '?')}/5 {t[:260]}")
    loc = p.get("location") or {}
    return {"id": p["id"], "name": (p.get("displayName") or {}).get("text"),
            "cat": (p.get("primaryTypeDisplayName") or {}).get("text") or p.get("primaryType"),
            "lat": round(loc.get("latitude", 0), 5), "lng": round(loc.get("longitude", 0), 5),
            "rating": p.get("rating"), "n": p.get("userRatingCount"),
            "price": area_mod.LEVELS.get(p.get("priceLevel")),
            "summary": (p.get("editorialSummary") or {}).get("text"), "reviews": reviews}


async def build(center_query, half_km=2.5, cell_m=550, concurrency=24, log=print):
    """Grid-sweep Places around the named center. Returns (rows, stats)."""
    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=15) as http:
        c = await area_mod.resolve(http, query=center_query)
        dlat = cell_m / 111_320
        dlng = cell_m / (111_320 * math.cos(math.radians(c["lat"])))
        n = int(half_km * 1000 // cell_m)
        cells = [(c["lat"] + i * dlat, c["lng"] + j * dlng) for i in range(-n, n + 1) for j in range(-n, n + 1)]
        sem = asyncio.Semaphore(concurrency)
        rows, calls, errors = {}, 0, 0

        async def one(lat, lng, types):
            nonlocal calls, errors
            async with sem:
                try:
                    r = await http.post(area_mod.NEARBY, json={
                        "includedTypes": types, "maxResultCount": 20, "rankPreference": "POPULARITY",
                        "locationRestriction": {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": cell_m * 0.75}}},
                        headers={"X-Goog-Api-Key": os.environ["MAPS_SERVER_KEY"], "X-Goog-FieldMask": FIELDS})
                    calls += 1
                    r.raise_for_status()
                    for p in r.json().get("places") or []:
                        if p.get("businessStatus") in (None, "OPERATIONAL"):
                            rows.setdefault(p["id"], _compact(p))
                except Exception:
                    errors += 1

        await asyncio.gather(*(one(lat, lng, t) for lat, lng in cells for t in area_mod.GROUPS.values()))
    stats = {"center": c["name"], "lat": c["lat"], "lng": c["lng"], "cells": len(cells), "calls": calls, "errors": errors,
             "places": len(rows), "build_s": round(time.perf_counter() - t0, 1), "half_km": half_km}
    log(f"city sweep: {stats}")
    return list(rows.values()), stats


def _prime_call(text):
    c = director.client()
    it = c.interactions.create(model=director.MODEL, system_instruction=SYSTEM, input=text,
                               generation_config={"thinking_level": "low", "max_output_tokens": 400})
    return it


async def prime(rows, stats, log=print):
    """One stored gemini-4-argon interaction holding the whole snapshot. Saves its id and real token usage."""
    lines = "\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in rows)
    SNAPSHOT.write_text(lines)
    text = (f"CITY SNAPSHOT: {stats['places']} places within {stats['half_km']} km of {stats['center']}, "
            f"fetched live from Google Places at {time.strftime('%Y-%m-%d %H:%M %Z')}.\n{lines}\n\n"
            "Reply in one short paragraph: how many places you hold, the neighborhoods they span, and three "
            "places whose reviews stand out for coffee or pastries, with their ids.")
    t = time.perf_counter()
    it = await asyncio.to_thread(_prime_call, text)
    usage = getattr(it, "usage", None)
    u = usage.model_dump(exclude_none=True) if hasattr(usage, "model_dump") else {}
    meta = {**stats, "interaction_id": it.id, "prime_s": round(time.perf_counter() - t, 1),
            "input_tokens": u.get("total_input_tokens"), "usage": u, "ack": (it.output_text or "")[:800],
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "snapshot_bytes": len(text.encode())}
    META.write_text(json.dumps(meta, indent=1))
    state.update(interaction_id=it.id, meta=meta)
    log(f"primed: {meta['input_tokens']} input tokens in {meta['prime_s']} s, id {it.id[:16]}...")
    return meta


NOTES_SCHEMA = {"type": "object", "required": ["stops"], "properties": {"stops": {"type": "array", "items": {
    "type": "object", "required": ["name", "reviewers_say"], "properties": {
        "name": {"type": "string"}, "reviewers_say": {"type": "string"},
        "better_nearby": {"type": ["string", "null"]}}}}}}


def _chain(text, schema=None):
    kw = dict(model=director.MODEL, input=text, previous_interaction_id=state["interaction_id"],
              generation_config={"thinking_level": "low", "max_output_tokens": 1200})
    if schema:
        kw["response_format"] = {"type": "text", "mime_type": "application/json", "schema": schema}
    it = director.client().interactions.create(**kw)
    u = getattr(it, "usage", None)
    u = u.model_dump(exclude_none=True) if hasattr(u, "model_dump") else {}
    return it.output_text or "", u


async def notes(quest):
    """With the whole city in context: what reviewers say about each stop, and any better-rated place nearby."""
    stops = [{"name": s["name"], "place_id": s["place_id"], "category": s.get("category")} for s in quest["stops"]]
    text = ("A live quest was just verified. STOPS: " + json.dumps(stops) + "\nFor each stop, using only your city "
            "memory: what reviewers say (paraphrase, at most 15 words), and better_nearby: one higher-rated place of the "
            "same kind within about 400 m from your memory as 'Name (rating)', or null. Never invent; null if unsure.")
    t = time.perf_counter()
    raw, u = await asyncio.to_thread(_chain, text, NOTES_SCHEMA)
    return json.loads(director._strip_fence(raw)), u, round((time.perf_counter() - t) * 1000)


async def ask(question):
    """A free question answered from the whole city memory (e.g. 'best croissant in the city?')."""
    t = time.perf_counter()
    raw, u = await asyncio.to_thread(_chain, "Answer from your city memory only, in at most three short sentences, "
                                     "naming places and what reviewers say. Question: " + question)
    return raw.strip(), u, round((time.perf_counter() - t) * 1000)
