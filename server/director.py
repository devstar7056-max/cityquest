"""World Director: gemini-4-argon turns a request into quest JSON (schema-checked).

The model only chooses stops and writes copy. The places come from a live area (server/area.py:
Places Nearby Search around wherever the person is). Everything factual about a stop (category,
lat, lng) is copied from that live list by place_id, and any other place_id is rejected.
"""
import asyncio
import copy
import json
import pathlib
import secrets
import time
from datetime import datetime

import jsonschema
from google import genai

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "schema" / "quest.schema.json").read_text())
SYSTEM = (ROOT / "prompts" / "director.md").read_text()
MODEL = "gemini-4-argon"

_client = None


def client():
    global _client
    if _client is None:
        _client = genai.Client()
    return _client


class DirectorError(Exception):
    pass


def load_places(area):
    """The live area's start point and places (from server/area.py). Returns (start, places_by_id)."""
    if not area or not area.get("places"):
        raise DirectorError("no live area: say where you are, or allow location")
    return area["start"], area["places"]


def _inline(node, defs):
    if isinstance(node, dict):
        if "$ref" in node:
            return _inline(defs[node["$ref"].split("/")[-1]], defs)
        return {k: _inline(v, defs) for k, v in node.items()}
    if isinstance(node, list):
        return [_inline(v, defs) for v in node]
    return node


def response_schema():
    """The Director's part of the quest schema: $refs inlined, no route or verification."""
    s = copy.deepcopy(SCHEMA)
    defs = s.pop("$defs")
    for k in ("$schema", "$id", "title", "description"):
        s.pop(k, None)
    for k in ("route", "verification"):
        s["properties"].pop(k)
    return _inline(s, defs)


RESPONSE_SCHEMA = response_schema()


def _point(p):
    return {"name": p["name"], "place_id": p.get("place_id"), "lat": p.get("lat"), "lng": p.get("lng")}


LIVE_KEYS = ("open_now", "serves_coffee", "serves_breakfast", "serves_dessert", "price_low", "price_high", "price_level")


def _places_block(places, exclude=(), live=None):
    rows = []
    for p in sorted(places.values(), key=lambda p: p.get("distance_m") or 0):
        if p["place_id"] in exclude:
            continue
        row = {k: p.get(k) for k in ("place_id", "name", "category", "what", "distance_m", "rating")}
        row["live"] = {k: p.get(k) for k in LIVE_KEYS if p.get(k) is not None}
        rows.append(row)
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)


def _prompt(request, minutes, wants, now, start, places, previous=None, exclude=(), live=None):
    lines = [
        f"NOW: {now.isoformat()} ({now.strftime('%A')})",
        f"START: {json.dumps(_point(start))}",
        f"END: {json.dumps(_point(start))}",
        f"REQUEST: {json.dumps(request)}",
        f"MINUTES: {minutes if minutes else 'not given (assume 30)'}",
        f"WANTS: {wants or 'not given'}",
    ]
    if previous is not None:
        prev = {k: previous.get(k) for k in ("quest_id", "title", "theme", "deadline_min", "stops")}
        ver = previous.get("verification") or {}
        lines += [f"PREVIOUS_QUEST: {json.dumps(prev, ensure_ascii=False)}",
                  f"VERIFIER_RESULT: {json.dumps({k: ver.get(k) for k in ('status', 'checks', 'swaps', 'total_min')}, ensure_ascii=False)}"]
    if exclude:
        lines.append(f"NEVER USE these place_ids (they failed verification today): {json.dumps(sorted(exclude))}")
    lines.append("PLACES (one JSON object per line, nearest first, the only places you may use; found live with Google "
                 "Places seconds ago; `live` keys missing means unknown):")
    lines.append(_places_block(places, exclude, live))
    return "\n".join(lines)


def _strip_fence(text):
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    return t.strip()


def _finish(raw, request, minutes, now, start, places, parent_id):
    """Parse, fill server-owned fields, copy facts from the live area, validate."""
    try:
        q = json.loads(_strip_fence(raw))
    except json.JSONDecodeError as e:
        raise DirectorError(f"Director returned invalid JSON: {e}") from None
    q["quest_id"] = "q-" + secrets.token_hex(3)
    q["generated_at"] = now.isoformat()
    q["request"] = request
    if minutes:
        q["deadline_min"] = int(minutes)
    q["start"] = _point(start)
    q["end"] = _point(start)
    if parent_id:
        q["parent_quest_id"] = parent_id
    unknown = [s.get("place_id") for s in q.get("stops", []) if s.get("place_id") not in places]
    if unknown:
        raise DirectorError(f"Director used place_ids that are not in the live area: {unknown}")
    for i, s in enumerate(q.get("stops", [])):
        p = places[s["place_id"]]
        s["id"] = f"s{i + 1}"
        s["name"] = p["name"]
        for k in ("unit", "category", "lat", "lng"):
            s[k] = p.get(k)
        s["source"] = "director"
    jsonschema.validate(q, SCHEMA)
    n = len(q["stops"])
    if not 2 <= n <= 4:
        raise DirectorError(f"Director returned {n} stops; need 2 to 4")
    return q


def _call(text, thinking, previous_interaction_id):
    kw = dict(model=MODEL, input=text, system_instruction=SYSTEM,
              generation_config={"thinking_level": thinking},
              response_format={"type": "text", "mime_type": "application/json", "schema": RESPONSE_SCHEMA})
    if previous_interaction_id:
        kw["previous_interaction_id"] = previous_interaction_id
    it = client().interactions.create(**kw)
    return it.id, it.output_text


async def plan(request, minutes=None, wants=None, now=None, previous=None, exclude=(), thinking="low", area=None,
               context_iid=None):
    """Returns (quest, interaction_id, ms). Retries once with the validation error appended."""
    start, places = load_places(area)
    now = now or datetime.now().astimezone()
    # Replans chain from the previous quest; a new quest chains from City Memory when it is primed.
    prev_iid = (previous or {}).get("_interaction_id") or context_iid
    parent_id = (previous or {}).get("quest_id")
    exclude = set(exclude) | set((previous or {}).get("_failed_place_ids", []))
    text = _prompt(request, minutes, wants, now, start, places, previous, exclude)
    t0 = time.perf_counter()
    err = None
    for attempt in range(2):
        body = text if err is None else f"{text}\n\nYour last answer was rejected: {err}\nFix it and answer again."
        iid, raw = await asyncio.to_thread(_call, body, thinking, prev_iid)
        try:
            q = _finish(raw, request, minutes, now, start, places, parent_id)
            if exclude & {s["place_id"] for s in q["stops"]}:
                raise DirectorError("Director reused a place that failed verification")
            q["_interaction_id"] = iid
            return q, iid, round((time.perf_counter() - t0) * 1000)
        except (DirectorError, jsonschema.ValidationError) as e:
            err = str(e).split("\n")[0][:400]
    raise DirectorError(f"Director failed twice: {err}")


FLASH = "gemini-3.8-flash"
FLASH_LITE = "gemini-3.5-flash-lite"


def _pick_call(text):
    it = client().interactions.create(
        model=FLASH, input=text,
        response_format={"type": "text", "mime_type": "application/json", "schema": {
            "type": "object", "required": ["place_ids"],
            "properties": {"place_ids": {"type": "array", "items": {"type": "string"}}}}})
    return json.loads(_strip_fence(it.output_text)).get("place_ids", [])


ROUTE_SCHEMA = {
    "type": "object", "required": ["intent"],
    "properties": {
        "intent": {"enum": ["new_quest", "replan", "chit_chat"]},
        "minutes": {"type": ["integer", "null"]},
        "wants": {"type": ["string", "null"]},
        "drop": {"type": ["string", "null"]},
        "place": {"type": ["string", "null"]},
    }}


def _route_call(text, has_quest):
    it = client().interactions.create(
        model=FLASH_LITE,
        input=(f"Classify one message to a city quest app. A quest is {'already' if has_quest else 'not yet'} on screen.\n"
               "new_quest: they describe time or wants from scratch, or say start over / new quest.\n"
               "replan: they change the current quest (less time, different craving, skip a stop).\n"
               "chit_chat: anything else.\nAlso extract minutes (integer or null), wants (short, their words), "
               f"drop (a stop to remove, or null) and place (a street, landmark, neighborhood or city they name as where they are or want to go, or null).\nMESSAGE: {json.dumps(text)}"),
        response_format={"type": "text", "mime_type": "application/json", "schema": ROUTE_SCHEMA})
    return json.loads(_strip_fence(it.output_text))


async def route(text, has_quest):
    """gemini-3.5-flash-lite: intent routing plus minutes/wants extraction. Returns (dict, ms)."""
    t = time.perf_counter()
    r = await asyncio.to_thread(_route_call, text, has_quest)
    if r.get("intent") == "replan" and not has_quest:
        r["intent"] = "new_quest"
    return r, round((time.perf_counter() - t) * 1000)


async def pick_swaps(quest, stop, reason, exclude, area):
    """gemini-3.8-flash ranks up to 3 replacement place_ids for one failing stop (run in parallel per stop)."""
    _, places = load_places(area)
    used = {s["place_id"] for s in quest["stops"]} | set(exclude)
    text = (f"A CityQuest stop failed a live check. Quest theme: {quest.get('theme')!r}. "
            f"Request: {quest.get('request')!r}.\nFailed stop: {stop['name']} ({stop.get('category')}). "
            f"Reason: {reason}\nPick up to 3 replacements from CANDIDATES that fit the theme and the "
            f"failed stop's role, best first. Prefer places close to the failed stop. Return only place_ids "
            f"from CANDIDATES.\nCANDIDATES:\n{_places_block(places, used)}")
    ids = await asyncio.to_thread(_pick_call, text)
    return [i for i in ids if i in places and i not in used][:3]
