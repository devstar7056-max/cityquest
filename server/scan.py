"""Live building scan: Places details for every shop in parallel (open now, what it serves, price range).

Missing fields stay None (unknown), never False. Prices are Google's per-place price ranges only.
Results are cached for 60 s so replans do not pay for the scan again.
"""
import asyncio
import os
import time

import httpx

from . import director
from .events import emit

FIELDS = ("id,displayName,businessStatus,currentOpeningHours.openNow,servesCoffee,servesBreakfast,"
          "servesDessert,servesLunch,priceRange,priceLevel,primaryType")
TTL_S = 60
LEVELS = {"PRICE_LEVEL_FREE": "free", "PRICE_LEVEL_INEXPENSIVE": "$", "PRICE_LEVEL_MODERATE": "$$",
          "PRICE_LEVEL_EXPENSIVE": "$$$", "PRICE_LEVEL_VERY_EXPENSIVE": "$$$$"}
_cache = {"t": 0.0, "data": None}


def _money(p):
    return int(p.get("units", 0)) if p else None


def _row(place, d, ms):
    pr = d.get("priceRange") or {}
    lo, hi = _money(pr.get("startPrice")), _money(pr.get("endPrice"))
    return {
        "place_id": place["place_id"], "name": place["name"], "kind": place.get("kind"),
        "category": place.get("category"), "unit": place.get("unit"), "lat": place.get("lat"), "lng": place.get("lng"),
        "open_now": (d.get("currentOpeningHours") or {}).get("openNow"),
        "business_status": d.get("businessStatus"),
        "serves_coffee": d.get("servesCoffee"), "serves_breakfast": d.get("servesBreakfast"),
        "serves_dessert": d.get("servesDessert"), "serves_lunch": d.get("servesLunch"),
        "price_low": lo, "price_high": hi, "currency": (pr.get("startPrice") or {}).get("currencyCode"),
        "price_level": LEVELS.get(d.get("priceLevel")), "primary_type": d.get("primaryType"), "ms": ms,
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
    return ", ".join(bits)


async def scan(run_id, force=False):
    """Returns {place_id: row}. Emits one `scan` event per shop with the live result."""
    if not force and _cache["data"] and time.time() - _cache["t"] < TTL_S:
        emit(run_id, "scan", "info", 0, f"{len(_cache['data'])} shops, cached {time.time() - _cache['t']:.0f} s ago",
             scan=list(_cache["data"].values()))
        return _cache["data"]
    _, places = director.load_places()
    key = os.environ.get("MAPS_SERVER_KEY", "")
    t0 = time.perf_counter()
    emit(run_id, "scan", "start", None, f"Places live scan of {len(places)} Ferry Building places")
    out = {}
    async with httpx.AsyncClient(timeout=10) as http:
        async def one(p):
            t = time.perf_counter()
            try:
                r = await http.get(f"https://places.googleapis.com/v1/places/{p['place_id']}",
                                   headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": FIELDS})
                r.raise_for_status()
                row = _row(p, r.json(), round((time.perf_counter() - t) * 1000))
            except Exception as e:
                row = _row(p, {}, round((time.perf_counter() - t) * 1000))
                row["error"] = str(e)[:120]
            out[p["place_id"]] = row
            status = "pass" if row["open_now"] else "fail" if row["open_now"] is False else "info"
            emit(run_id, "scan", status, row["ms"], f"{p['name']}: {describe(row)}", place_id=p["place_id"],
                 shop={k: row[k] for k in ("name", "lat", "lng", "open_now", "kind", "category", "price_low", "price_high")})
        await asyncio.gather(*(one(p) for p in places.values()))
    ms = round((time.perf_counter() - t0) * 1000)
    n_open = sum(1 for r in out.values() if r["open_now"])
    emit(run_id, "scan", "pass", ms, f"{len(out)} places scanned in parallel, {n_open} open now",
         scan=list(out.values()))
    _cache.update(t=time.time(), data=out)
    return out


def cost(quest, rows):
    """Estimated total from Google price ranges for the quest's stops. Never invents a price."""
    per, low, high, unlisted = [], 0, 0, []
    for s in quest["stops"]:
        r = rows.get(s["place_id"]) or {}
        if r.get("price_low") is not None:
            lo = r["price_low"]
            hi = r["price_high"] if r.get("price_high") is not None else lo
            low, high = low + lo, high + hi
            per.append({"name": s["name"], "low": lo, "high": hi, "level": r.get("price_level")})
        else:
            unlisted.append(s["name"])
            per.append({"name": s["name"], "low": None, "high": None, "level": r.get("price_level")})
    listed = len(per) - len(unlisted)
    return {"low": low if listed else None, "high": high if listed else None, "currency": "USD",
            "stops": per, "unlisted": unlisted, "source": "Google Places priceRange per place (a range, not menu prices)"}
