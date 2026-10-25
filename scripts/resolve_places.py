#!/usr/bin/env python3
"""Resolve data/merchants.seed.json into data/merchants.json with real Google place IDs.

Places API (New) Text Search, biased to the Ferry Building. Needs MAPS_SERVER_KEY.
Prints one line per place. "check" means Google returned a different name or a
place too far away: fix that entry's "query" in the seed file and rerun.
Never prints the key. Standard library only.
"""
import json
import math
import os
import pathlib
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

URL = "https://places.googleapis.com/v1/places:searchText"
FIELDS = ("places.id,places.displayName,places.formattedAddress,places.location,"
          "places.primaryType,places.businessStatus")
ROOT = pathlib.Path(__file__).resolve().parent.parent
SEED = ROOT / "data" / "merchants.seed.json"
OUT = ROOT / "data" / "merchants.json"
IGNORE = {"the", "and", "company", "co", "ferry", "building", "san", "francisco", "unit", "suite"}


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]", " ", s)


def meters(a_lat, a_lng, b_lat, b_lng):
    r = 6371000
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = math.radians(b_lat - a_lat), math.radians(b_lng - a_lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def search(query, center, key):
    body = {"textQuery": query,
            "locationBias": {"circle": {"center": {"latitude": center["lat"], "longitude": center["lng"]},
                                        "radius": 800.0}}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST", headers={
        "Content-Type": "application/json", "X-Goog-Api-Key": key, "X-Goog-FieldMask": FIELDS})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode()).get("places", [])


def resolve(entry, center, key):
    out = dict(entry)
    try:
        places = search(entry["query"], center, key)
    except urllib.error.HTTPError as e:
        out.update(resolve_status="error", resolve_detail=f"HTTP {e.code}: {e.read().decode(errors='replace')[:200]}")
        return out
    except Exception as e:  # network, timeout
        out.update(resolve_status="error", resolve_detail=str(e)[:200])
        return out
    if not places:
        out.update(resolve_status="error", resolve_detail="no result")
        return out
    p = places[0]
    loc = p.get("location") or {}
    gname = (p.get("displayName") or {}).get("text", "")
    out.update(place_id=p.get("id"), lat=loc.get("latitude"), lng=loc.get("longitude"),
               google_name=gname, address=p.get("formattedAddress"),
               primary_type=p.get("primaryType"), business_status=p.get("businessStatus"))
    words = [w for w in norm(entry["name"]).split() if len(w) > 2 and w not in IGNORE]
    name_ok = not words or any(w in norm(gname) for w in words)
    dist = meters(center["lat"], center["lng"], out["lat"], out["lng"]) if out["lat"] is not None else 1e9
    out["distance_m"] = round(dist)
    far = dist > entry.get("max_m", 400)
    out["resolve_status"] = "ok" if name_ok and not far else "check"
    if out["resolve_status"] == "check":
        out["resolve_detail"] = ("name mismatch; " if not name_ok else "") + (f"{round(dist)} m away" if far else "")
    return out


def main():
    key = os.environ.get("MAPS_SERVER_KEY")
    if not key:
        print("MAPS_SERVER_KEY is not set. Export it in this terminal (SETUP.md step 2).")
        return 1
    seed = json.loads(SEED.read_text())
    center = seed["center"]
    with ThreadPoolExecutor(max_workers=8) as ex:
        resolved = list(ex.map(lambda e: resolve(e, center, key), seed["places"]))
    counts = {"ok": 0, "check": 0, "error": 0}
    for r in resolved:
        counts[r["resolve_status"]] += 1
        print(f"{r['resolve_status']:<6} {r['name']:<38} -> {r.get('google_name', '-')!s:<38} "
              f"{r.get('distance_m', '-')!s:>5} m  {r.get('resolve_detail', '')}")
    OUT.write_text(json.dumps({"source": seed["source"], "center": center, "places": resolved}, indent=2))
    print(f"\n{counts['ok']} ok, {counts['check']} check, {counts['error']} error. Wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
