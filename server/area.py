"""Live areas: any street, landmark or GPS position becomes a playable area, discovered from Google Places.

resolve() turns a name or a lat/lng into a center (and a focus place with its viewport when a name was given).
discover() runs Places Nearby Search around the center (food and drink plus sights, in parallel) with the
live fields the planner needs (open now, what it serves, price range, editorial summary). Nothing is
precomputed: the same code serves the Ferry Building, Valencia Street or wherever the judge is standing.
"""
import asyncio
import math
import os
import time

import httpx

from .events import emit

NEARBY = "https://places.googleapis.com/v1/places:searchNearby"
TEXT = "https://places.googleapis.com/v1/places:searchText"
FIELDS = ("places.id,places.displayName,places.location,places.primaryType,places.primaryTypeDisplayName,"
          "places.businessStatus,places.currentOpeningHours.openNow,places.servesCoffee,places.servesBreakfast,"
          "places.servesDessert,places.priceRange,places.priceLevel,places.editorialSummary,places.rating,"
          "places.userRatingCount,places.formattedAddress")
GROUPS = {
    "food": ["cafe", "coffee_shop", "bakery", "ice_cream_shop", "dessert_shop", "restaurant", "bar", "tea_house",
             "juice_shop", "sandwich_shop", "chocolate_shop", "confectionery"],
    "sights": ["tourist_attraction", "park", "museum", "art_gallery", "book_store", "gift_shop", "market",
               "historical_landmark", "plaza", "observation_deck"],
}
LEVELS = {"PRICE_LEVEL_FREE": "free", "PRICE_LEVEL_INEXPENSIVE": "$", "PRICE_LEVEL_MODERATE": "$$",
          "PRICE_LEVEL_EXPENSIVE": "$$$", "PRICE_LEVEL_VERY_EXPENSIVE": "$$$$"}
TTL_S = 90
_cache: dict[str, dict] = {}
current: dict | None = None  # last area used, so follow-up requests stay where the person is


def _key():
    return os.environ.get("MAPS_SERVER_KEY", "")


def meters(a_lat, a_lng, b_lat, b_lng):
    r = 6371000
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    h = math.sin(math.radians(b_lat - a_lat) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b_lng - a_lng) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


async def resolve(http, query=None, lat=None, lng=None, near=None):
    """A name (geocoded with Places Text Search) or a GPS fix. Returns the area center and focus place."""
    if query:
        body = {"textQuery": query, "maxResultCount": 1}
        bias = near or ({"lat": lat, "lng": lng} if lat is not None else None)
        if bias:
            body["locationBias"] = {"circle": {"center": {"latitude": bias["lat"], "longitude": bias["lng"]}, "radius": 20000.0}}
        r = await http.post(TEXT, json=body, headers={
            "X-Goog-Api-Key": _key(), "X-Goog-FieldMask": "places.id,places.displayName,places.location,places.viewport,places.formattedAddress"})
        r.raise_for_status()
        places = r.json().get("places") or []
        if not places:
            raise ValueError(f"Google Places found nothing for {query!r}")
        p = places[0]
        vp = p.get("viewport")
        return {"name": p["displayName"]["text"], "query": query, "lat": p["location"]["latitude"],
                "lng": p["location"]["longitude"], "address": p.get("formattedAddress"),
                "focus": {"place_id": p["id"], "name": p["displayName"]["text"],
                          "viewport": vp and {"low": vp["low"], "high": vp["high"]}}}
    if lat is not None and lng is not None:
        return {"name": "your location", "query": None, "lat": lat, "lng": lng, "address": None, "focus": None}
    raise ValueError("no area: give a place name or a location")


def _row(p, center):
    loc = p.get("location") or {}
    pr = p.get("priceRange") or {}
    lo = int((pr.get("startPrice") or {}).get("units", 0)) if pr.get("startPrice") else None
    hi = int((pr.get("endPrice") or {}).get("units", 0)) if pr.get("endPrice") else None
    return {
        "place_id": p["id"], "name": (p.get("displayName") or {}).get("text"), "lat": loc.get("latitude"),
        "lng": loc.get("longitude"), "kind": p.get("primaryType"),
        "category": (p.get("primaryTypeDisplayName") or {}).get("text") or p.get("primaryType"),
        "what": (p.get("editorialSummary") or {}).get("text"), "address": p.get("formattedAddress"),
        "business_status": p.get("businessStatus"), "open_now": (p.get("currentOpeningHours") or {}).get("openNow"),
        "serves_coffee": p.get("servesCoffee"), "serves_breakfast": p.get("servesBreakfast"),
        "serves_dessert": p.get("servesDessert"), "price_low": lo, "price_high": hi,
        "price_level": LEVELS.get(p.get("priceLevel")), "rating": p.get("rating"), "ratings": p.get("userRatingCount"),
        "distance_m": round(meters(center["lat"], center["lng"], loc.get("latitude", 0), loc.get("longitude", 0))),
    }


def describe(r):
    bits = ["open now" if r["open_now"] else "closed now" if r["open_now"] is False else "hours unknown"]
    serves = [k for k in ("coffee", "breakfast", "dessert") if r.get(f"serves_{k}")]
    if serves:
        bits.append("serves " + ", ".join(serves))
    if r["price_low"] is not None:
        bits.append(f"${r['price_low']}" + (f" to ${r['price_high']}" if r["price_high"] is not None else "+"))
    elif r["price_level"]:
        bits.append(r["price_level"])
    bits.append(f"{r['distance_m']} m")
    return ", ".join(bits)


async def get(run_id, query=None, lat=None, lng=None, radius=450.0):
    """Resolve and discover an area live (cached briefly). Emits `area` and one `scan` event per place."""
    global current
    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=10) as http:
        if query is None and lat is None and current is not None:
            a = current
        else:
            a = await resolve(http, query, lat, lng, near=current and {"lat": current["lat"], "lng": current["lng"]})
        ck = f"{a['lat']:.4f},{a['lng']:.4f}"
        cached = _cache.get(ck)
        if cached and time.time() - cached["t"] < TTL_S:
            current = cached["area"]
            emit(run_id, "area", "pass", 0, f"{current['name']}: {len(current['places'])} places, cached {time.time() - cached['t']:.0f} s ago",
                 area={k: current[k] for k in ("name", "lat", "lng", "focus", "start")}, scan=list(current["places"].values()))
            return current
        emit(run_id, "area", "start", None, f"{a['name']} ({a['lat']:.5f}, {a['lng']:.5f}): Places Nearby Search, {int(radius)} m",
             area={k: a[k] for k in ("name", "lat", "lng", "focus")})

        async def nearby(types):
            t = time.perf_counter()
            r = await http.post(NEARBY, json={
                "includedTypes": types, "maxResultCount": 20, "rankPreference": "POPULARITY",
                "locationRestriction": {"circle": {"center": {"latitude": a["lat"], "longitude": a["lng"]}, "radius": radius}}},
                headers={"X-Goog-Api-Key": _key(), "X-Goog-FieldMask": FIELDS})
            r.raise_for_status()
            return r.json().get("places") or [], round((time.perf_counter() - t) * 1000)

        results = await asyncio.gather(*(nearby(t) for t in GROUPS.values()))
    rows = {}
    for places, ms in results:
        for p in places:
            row = _row(p, a)
            if row["business_status"] not in (None, "OPERATIONAL") or row["place_id"] in rows:
                continue
            rows[row["place_id"]] = row
            status = "pass" if row["open_now"] else "fail" if row["open_now"] is False else "info"
            emit(run_id, "scan", status, ms, f"{row['name']}: {describe(row)}", place_id=row["place_id"],
                 shop={k: row[k] for k in ("name", "lat", "lng", "open_now", "kind", "category", "price_low", "price_high")})
    a["places"] = rows
    a["start"] = {"name": a["name"] if a["query"] else "your location", "place_id": None, "lat": a["lat"], "lng": a["lng"]}
    ms = round((time.perf_counter() - t0) * 1000)
    n_open = sum(1 for r in rows.values() if r["open_now"])
    emit(run_id, "scan", "pass", ms, f"{len(rows)} places near {a['name']} found live, {n_open} open now",
         scan=list(rows.values()), area={k: a[k] for k in ("name", "lat", "lng", "focus", "start")})
    _cache[ck] = {"t": time.time(), "area": a}
    current = a
    return a
