#!/usr/bin/env python3
"""CityQuest verifier: checks a quest against live Google data.

For every stop:
  business_status    the place is OPERATIONAL (Places API New)
  open_during_visit  open from arrival until arrival + dwell, using today's
                     currentOpeningHours periods (Places API New)
For the whole quest:
  time_budget        walking (Routes API, WALK) + dwell fits deadline_min

Usage:
  python3 verify_quest.py quest.json [--now ISO8601] [--out result.json] [--mock mock.json]
  python3 verify_quest.py --check-place PLACE_ID [--at ISO8601] [--dwell 8] [--mock mock.json]

Prints the result JSON to stdout. Exit codes: 0 pass, 1 fail, 2 error.

Auth: sends X-Goog-Api-Key from MAPS_SERVER_KEY when it is set. In the
Antigravity sandbox the Credentials API proxy injects the key instead, so the
variable can be absent there. The key is never printed or written.
Standard library only, so it runs unchanged in the managed-agent sandbox.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

PLACES_URL = "https://places.googleapis.com/v1/places/{pid}"
PLACES_FIELDS = "id,displayName,businessStatus,currentOpeningHours,utcOffsetMinutes"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
ROUTES_FIELDS = ("routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline,"
                 "routes.legs.duration,routes.legs.distanceMeters")
TIMEOUT_S = 10
PDT = timezone(timedelta(hours=-7), "PDT")


class ApiError(Exception):
    pass


def _request(url, field_mask, body=None):
    headers = {"X-Goog-FieldMask": field_mask}
    key = os.environ.get("MAPS_SERVER_KEY")
    if key:
        headers["X-Goog-Api-Key"] = key
    data, method = None, "GET"
    if body is not None:
        data, method = json.dumps(body).encode(), "POST"
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise ApiError(f"{url} HTTP {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise ApiError(f"{url} unreachable: {e.reason}") from None


class Source:
    """Live Google APIs, or a mock file with {"places": {id: details}, "routes": response}."""

    def __init__(self, mock=None):
        self.mock = mock

    def place(self, pid):
        if self.mock is not None:
            if pid not in self.mock.get("places", {}):
                raise ApiError(f"mock has no place {pid}")
            return self.mock["places"][pid]
        return _request(PLACES_URL.format(pid=pid), PLACES_FIELDS)

    def route(self, body):
        if self.mock is not None:
            return self.mock["routes"]
        return _request(ROUTES_URL, ROUTES_FIELDS, body)


def now_local():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Los_Angeles"))
    except Exception:
        return datetime.now(PDT)


def parse_iso(s):
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=PDT)


def fmt(dt):
    return dt.strftime("%I:%M %p").lstrip("0")


def ms_since(t):
    return round((time.perf_counter() - t) * 1000)


def secs(d):
    if d is None:
        return 0.0
    if isinstance(d, (int, float)):
        return float(d)
    return float(str(d).rstrip("s") or 0)


def waypoint(p):
    if p.get("place_id"):
        return {"placeId": p["place_id"]}
    if p.get("lat") is not None and p.get("lng") is not None:
        return {"location": {"latLng": {"latitude": p["lat"], "longitude": p["lng"]}}}
    raise ApiError(f"{p.get('name', '?')} has no place_id or lat/lng")


# ---------- opening hours ----------

def _point_dt(pt, tz, ref):
    """A Places open/close point as an aware datetime (dated periods first)."""
    hour, minute = pt.get("hour", 0), pt.get("minute", 0)
    extra = timedelta(0)
    if hour == 24:
        hour, extra = 0, timedelta(days=1)
    d = pt.get("date")
    if d:
        base = datetime(d["year"], d["month"], d["day"], hour, minute, tzinfo=tz)
    else:
        ref_local = ref.astimezone(tz)
        ref_day = (ref_local.weekday() + 1) % 7  # Places days: 0 = Sunday
        day = (ref_local + timedelta(days=pt.get("day", ref_day) - ref_day)).date()
        base = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
    return base + extra


def open_window(details, start, end, fallback_tz):
    """(status, detail) for being open from start to end. status: open | closed | no_hours."""
    hours = details.get("currentOpeningHours")
    if not hours:
        return "no_hours", "no opening hours listed (public space or unlisted)"
    off = details.get("utcOffsetMinutes")
    tz = timezone(timedelta(minutes=off)) if off is not None else fallback_tz
    periods = hours.get("periods") or []
    if not periods:
        return ("open", "open now (no periods listed)") if hours.get("openNow") \
            else ("closed", "closed now, no periods listed")
    local_start = start.astimezone(tz)
    closes_early = opens_later = None
    for p in periods:
        o, c = p.get("open"), p.get("close")
        if o is None:
            continue
        if c is None:
            return "open", "open 24 hours"
        windows = []
        os_, cs_ = _point_dt(o, tz, start), _point_dt(c, tz, start)
        if o.get("date"):
            if cs_ <= os_:
                cs_ += timedelta(days=1)
            windows.append((os_, cs_))
        else:
            if cs_ <= os_:
                cs_ += timedelta(days=7)
            windows += [(os_, cs_), (os_ - timedelta(days=7), cs_ - timedelta(days=7))]
        for ws, we in windows:
            if ws <= start and end <= we:
                return "open", f"open until {fmt(we.astimezone(tz))}"
            if ws <= start < we < end:
                closes_early = we
            if start < ws and ws.astimezone(tz).date() == local_start.date():
                opens_later = ws if opens_later is None else min(opens_later, ws)
    if closes_early:
        return "closed", f"closes {fmt(closes_early.astimezone(tz))}, before the visit ends"
    if opens_later:
        return "closed", f"opens at {fmt(opens_later.astimezone(tz))}"
    return "closed", "closed for the rest of today"


# ---------- verification ----------

def _fetch(src, stop):
    t = time.perf_counter()
    if not stop.get("place_id"):
        return None, "stop has no place_id", 0
    try:
        return src.place(stop["place_id"]), None, ms_since(t)
    except ApiError as e:
        return None, str(e), ms_since(t)


def verify(quest, now, src):
    t0 = time.perf_counter()
    stops = quest.get("stops") or []
    if not stops:
        raise ApiError("quest has no stops")
    start = quest.get("start") or {}
    end = quest.get("end") or start
    budget = quest.get("deadline_min")
    if not isinstance(budget, (int, float)):
        raise ApiError("quest has no deadline_min")

    body = {"origin": waypoint(start), "destination": waypoint(end),
            "intermediates": [waypoint(s) for s in stops], "travelMode": "WALK"}
    tr = time.perf_counter()
    rr = src.route(body)
    routes_ms = ms_since(tr)
    routes = rr.get("routes") or []
    if not routes:
        raise ApiError("Routes API returned no walking route")
    r0 = routes[0]
    legs = r0.get("legs") or []
    leg_secs = [secs(leg.get("duration")) for leg in legs]
    if len(leg_secs) != len(stops) + 1:
        raise ApiError(f"expected {len(stops) + 1} route legs, got {len(leg_secs)}")

    tp = time.perf_counter()
    with ThreadPoolExecutor(max_workers=min(8, len(stops))) as ex:
        fetched = list(ex.map(lambda s: _fetch(src, s), stops))
    places_ms = ms_since(tp)

    checks, failing, timeline = [], [], []
    t = now
    for i, s in enumerate(stops):
        sid = s.get("id", f"s{i + 1}")
        name = s.get("name", "?")
        dwell = int(s.get("dwell_min", 5))
        t += timedelta(seconds=leg_secs[i])
        arrive, leave = t, t + timedelta(minutes=dwell)
        timeline.append({"stop_id": sid, "name": name, "arrive": arrive.isoformat(),
                         "leave": leave.isoformat()})
        details, err, pms = fetched[i]
        if err:
            checks.append({"stop_id": sid, "name": name, "check": "places_lookup",
                           "result": "error", "detail": err, "latency_ms": pms})
            failing.append(sid)
        else:
            status = details.get("businessStatus", "OPERATIONAL")
            if status != "OPERATIONAL":
                checks.append({"stop_id": sid, "name": name, "check": "business_status",
                               "result": "fail", "detail": status.lower().replace("_", " "),
                               "latency_ms": pms})
                failing.append(sid)
            else:
                st, det = open_window(details, arrive, leave, now.tzinfo)
                ok = st in ("open", "no_hours")
                checks.append({"stop_id": sid, "name": name, "check": "open_during_visit",
                               "result": "pass" if ok else "fail",
                               "detail": f"arrive {fmt(arrive)}, stay {dwell} min: {det}",
                               "latency_ms": pms})
                if not ok:
                    failing.append(sid)
        t = leave
    t += timedelta(seconds=leg_secs[-1])

    total_min = (t - now).total_seconds() / 60
    walk_min = sum(leg_secs) / 60
    dwell_total = sum(int(s.get("dwell_min", 5)) for s in stops)
    over = total_min > budget
    checks.append({"stop_id": None, "name": None, "check": "time_budget",
                   "result": "fail" if over else "pass",
                   "detail": (f"{walk_min:.0f} min walking + {dwell_total} min at stops = "
                              f"{total_min:.0f} of {budget} min, back by {fmt(t)}"),
                   "latency_ms": routes_ms})

    names = [start.get("name", "start")] + [s.get("name", "?") for s in stops] + [end.get("name", "end")]
    return {
        "status": "fail" if (failing or over) else "pass",
        "checked_at": now.isoformat(),
        "deadline_min": budget,
        "total_min": round(total_min, 1),
        "walk_min": round(walk_min, 1),
        "dwell_min": dwell_total,
        "back_by": t.isoformat(),
        "over_budget": over,
        "failing_stop_ids": failing,
        "timeline": timeline,
        "checks": checks,
        "route": {
            "encoded_polyline": (r0.get("polyline") or {}).get("encodedPolyline"),
            "distance_m": r0.get("distanceMeters"),
            "walk_min_total": round(walk_min, 1),
            "legs": [{"from": names[i], "to": names[i + 1], "walk_min": round(leg_secs[i] / 60, 1),
                      "distance_m": legs[i].get("distanceMeters")} for i in range(len(legs))],
        },
        "timings_ms": {"routes": routes_ms, "places": places_ms, "total": ms_since(t0)},
    }


def check_place(pid, at, dwell, src):
    t = time.perf_counter()
    d = src.place(pid)
    status = d.get("businessStatus", "OPERATIONAL")
    if status != "OPERATIONAL":
        st, det = "closed", status.lower().replace("_", " ")
    else:
        st, det = open_window(d, at, at + timedelta(minutes=dwell), at.tzinfo)
    return {"place_id": pid, "name": (d.get("displayName") or {}).get("text"),
            "status": st, "detail": det, "latency_ms": ms_since(t)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Verify a CityQuest quest against live Google data.")
    ap.add_argument("quest", nargs="?", help="quest.json")
    ap.add_argument("--now", help="ISO 8601 time to plan from (default: now in San Francisco)")
    ap.add_argument("--out", help="also write the result JSON here")
    ap.add_argument("--mock", help="mock responses file (offline tests)")
    ap.add_argument("--check-place", help="check one place_id instead of a quest")
    ap.add_argument("--at", help="arrival time for --check-place (default: --now)")
    ap.add_argument("--dwell", type=int, default=8, help="minutes at the place for --check-place")
    a = ap.parse_args(argv)
    try:
        src = Source(json.load(open(a.mock)) if a.mock else None)
        now = parse_iso(a.now) if a.now else now_local()
        if a.check_place:
            at = parse_iso(a.at) if a.at else now
            result = check_place(a.check_place, at, a.dwell, src)
            code = 0 if result["status"] in ("open", "no_hours") else 1
        else:
            if not a.quest:
                ap.error("give quest.json or --check-place")
            result = verify(json.load(open(a.quest)), now, src)
            code = 0 if result["status"] == "pass" else 1
    except (ApiError, OSError, ValueError, KeyError) as e:
        result, code = {"status": "error", "error": str(e)}, 2
    out = json.dumps(result, indent=2)
    print(out)
    if a.out:
        with open(a.out, "w") as f:
            f.write(out)
    return code


if __name__ == "__main__":
    sys.exit(main())
