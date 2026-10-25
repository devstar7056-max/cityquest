#!/usr/bin/env python3
"""Offline tests for verify_quest.py. No network, no keys. Run: python3 verifier/test_verify_quest.py"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import verify_quest as vq  # noqa: E402

PDT = timezone(timedelta(hours=-7))
NOW = datetime(2026, 10, 25, 15, 45, tzinfo=PDT)  # Sunday 3:45 PM
TODAY = {"year": 2026, "month": 10, "day": 25}


def dated(day, oh, ch, date=TODAY, cm=0):
    return {"open": {"day": day, "hour": oh, "minute": 0, "date": date},
            "close": {"day": day, "hour": ch, "minute": cm, "date": date}}


PLACES = {
    "p_open": {"displayName": {"text": "Blue Bottle Coffee"}, "businessStatus": "OPERATIONAL",
               "utcOffsetMinutes": -420,
               "currentOpeningHours": {"openNow": True, "periods": [dated(0, 7, 19)]}},
    "p_closed_today": {"displayName": {"text": "Farmers Market"}, "businessStatus": "OPERATIONAL",
                       "utcOffsetMinutes": -420,
                       "currentOpeningHours": {"openNow": False, "periods": [
                           dated(2, 10, 14, {"year": 2026, "month": 10, "day": 27}),
                           dated(4, 10, 14, {"year": 2026, "month": 10, "day": 29}),
                           dated(6, 8, 14, {"year": 2026, "month": 10, "day": 31})]}},
    "p_closes_4": {"displayName": {"text": "Early Closer"}, "businessStatus": "OPERATIONAL",
                   "utcOffsetMinutes": -420,
                   "currentOpeningHours": {"openNow": True, "periods": [dated(0, 10, 16)]}},
    "p_24h": {"displayName": {"text": "Always Open"}, "businessStatus": "OPERATIONAL",
              "utcOffsetMinutes": -420,
              "currentOpeningHours": {"openNow": True, "periods": [
                  {"open": {"day": 0, "hour": 0, "minute": 0}}]}},
    "p_landmark": {"displayName": {"text": "Pier 14"}},
    "p_undated": {"displayName": {"text": "Undated Hours"}, "businessStatus": "OPERATIONAL",
                  "utcOffsetMinutes": -420,
                  "currentOpeningHours": {"openNow": True, "periods": [
                      {"open": {"day": 0, "hour": 10, "minute": 0},
                       "close": {"day": 0, "hour": 17, "minute": 0}}]}},
    "p_shut": {"displayName": {"text": "Gone"}, "businessStatus": "CLOSED_PERMANENTLY"},
}


def routes(*leg_secs):
    return {"routes": [{"duration": f"{sum(leg_secs)}s", "distanceMeters": 900,
                        "polyline": {"encodedPolyline": "abc"},
                        "legs": [{"duration": f"{s}s", "distanceMeters": 100} for s in leg_secs]}]}


def quest(stop_ids, deadline, dwell=(8, 5)):
    return {"quest_id": "q-test", "deadline_min": deadline,
            "start": {"name": "SHACK15", "place_id": "p_start"},
            "end": {"name": "SHACK15", "place_id": "p_start"},
            "stops": [{"id": f"s{i + 1}", "place_id": pid, "name": pid, "dwell_min": dwell[i]}
                      for i, pid in enumerate(stop_ids)]}


def run(stop_ids, deadline, legs, dwell=(8, 5)):
    src = vq.Source({"places": PLACES, "routes": routes(*legs)})
    return vq.verify(quest(stop_ids, deadline, dwell), NOW, src)


class VerifyTests(unittest.TestCase):
    def test_pass(self):
        r = run(["p_open", "p_24h"], 45, (120, 60, 300))
        self.assertEqual(r["status"], "pass", r)
        self.assertEqual(r["walk_min"], 8.0)
        self.assertEqual(r["total_min"], 21.0)

    def test_closed_today_fails_that_stop(self):
        r = run(["p_open", "p_closed_today"], 45, (120, 60, 300))
        self.assertEqual(r["status"], "fail")
        self.assertEqual(r["failing_stop_ids"], ["s2"])

    def test_over_budget(self):
        r = run(["p_open", "p_24h"], 15, (120, 60, 300))
        self.assertEqual(r["status"], "fail")
        self.assertTrue(r["over_budget"])
        self.assertEqual(r["failing_stop_ids"], [])

    def test_closes_before_visit_ends(self):
        r = run(["p_closes_4", "p_24h"], 60, (120, 60, 300), dwell=(15, 5))
        self.assertEqual(r["failing_stop_ids"], ["s1"])
        self.assertIn("closes 4:00 PM", r["checks"][0]["detail"])

    def test_landmark_without_hours_passes(self):
        r = run(["p_landmark", "p_open"], 45, (120, 60, 300))
        self.assertEqual(r["status"], "pass", r)

    def test_undated_periods(self):
        r = run(["p_undated", "p_open"], 45, (120, 60, 300))
        self.assertEqual(r["status"], "pass", r)

    def test_permanently_closed(self):
        r = run(["p_shut", "p_open"], 45, (120, 60, 300))
        self.assertEqual(r["failing_stop_ids"], ["s1"])
        self.assertEqual(r["checks"][0]["check"], "business_status")

    def test_timeline_and_route(self):
        r = run(["p_open", "p_24h"], 45, (120, 60, 300))
        self.assertEqual(len(r["timeline"]), 2)
        self.assertEqual(r["route"]["encoded_polyline"], "abc")
        self.assertEqual(len(r["route"]["legs"]), 3)

    def test_check_place(self):
        src = vq.Source({"places": PLACES, "routes": routes(1)})
        self.assertEqual(vq.check_place("p_closed_today", NOW, 8, src)["status"], "closed")
        self.assertEqual(vq.check_place("p_open", NOW, 8, src)["status"], "open")

    def test_cli_exit_codes(self):
        def write(path, obj):
            with open(path, "w") as f:
                json.dump(obj, f)

        with tempfile.TemporaryDirectory() as d:
            mock = os.path.join(d, "mock.json")
            qf = os.path.join(d, "quest.json")
            write(mock, {"places": PLACES, "routes": routes(120, 60, 300)})
            script = os.path.join(HERE, "verify_quest.py")
            write(qf, quest(["p_open", "p_24h"], 45))
            ok = subprocess.run([sys.executable, script, qf, "--now", NOW.isoformat(), "--mock", mock],
                                capture_output=True, text=True)
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
            write(qf, quest(["p_open", "p_closed_today"], 45))
            bad = subprocess.run([sys.executable, script, qf, "--now", NOW.isoformat(), "--mock", mock],
                                 capture_output=True, text=True)
            self.assertEqual(bad.returncode, 1, bad.stdout + bad.stderr)
            self.assertEqual(json.loads(bad.stdout)["failing_stop_ids"], ["s2"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
