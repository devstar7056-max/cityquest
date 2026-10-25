"""Verify a quest against live Google data, fix failures, rerun.

Two paths, same script (verifier/verify_quest.py):
  managed_agent   antigravity-preview-09-2026 runs it in a remote sandbox (managed.py)
  local_fallback  this process runs it via subprocess; Argon (low) ranks swaps
Every log line comes from a real command and its real output.
"""
import asyncio
import json
import os
import pathlib
import sys
import tempfile
import time

from . import director
from .events import emit

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "verifier" / "verify_quest.py"
MAX_ROUNDS = 2


def _ms(t):
    return round((time.perf_counter() - t) * 1000)


async def _run(args):
    """Run verify_quest.py; returns (exit_code, parsed_json, ms)."""
    t = time.perf_counter()
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(SCRIPT), *args, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env={**os.environ})
    out, err = await proc.communicate()
    try:
        data = json.loads(out.decode() or "{}")
    except json.JSONDecodeError:
        data = {"status": "error", "error": (err.decode() or out.decode())[:300]}
    return proc.returncode, data, _ms(t)


def _cmd(args):
    return "python3 verify_quest.py " + " ".join(a if " " not in a else f'"{a}"' for a in args)


def emit_checks(run_id, result):
    """One HUD line per real check, using the verifier's own words."""
    for c in result.get("checks", []):
        if c["check"] == "time_budget":
            emit(run_id, "routes", c["result"], c.get("latency_ms"),
                 f"WALK {len(result.get('timeline', []))} stops: {c['detail']}")
        else:
            emit(run_id, "places", c["result"], c.get("latency_ms"), f"{c['name']}: {c['detail']}",
                 stop_id=c.get("stop_id"))


def _public(quest):
    return {k: v for k, v in quest.items() if not k.startswith("_") and k not in ("route", "verification")}


async def verify_local(quest, run_id, now_iso, area):
    """Local fallback: verify, swap failing stops from merchants.json, rerun (max 2 rounds)."""
    t0 = time.perf_counter()
    log, swaps = [], []
    failed_ids = set(quest.get("_failed_place_ids", []))
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="cq-"))
    qf = tmp / "quest.json"
    result = {}
    for rnd in range(MAX_ROUNDS + 1):
        qf.write_text(json.dumps(_public(quest)))
        args = [str(qf), "--now", now_iso]
        code, result, ms = await _run(args)
        line = (f"pass, {result.get('total_min')} of {quest['deadline_min']} min" if code == 0 else
                f"fail: {', '.join(result.get('failing_stop_ids', [])) or 'over budget'}" if code == 1 else
                f"error: {result.get('error', '')[:120]}")
        log.append({"cmd": _cmd(["quest.json", "--now", now_iso]), "exit": code, "result": line})
        emit(run_id, "verify", "pass" if code == 0 else "fail" if code == 1 else "error", ms,
             f"round {rnd + 1}: {line}", cmd=log[-1]["cmd"], exit=code)
        if code == 2:
            break
        emit_checks(run_id, result)
        if code == 0 or rnd == MAX_ROUNDS:
            break
        changed = False
        timeline = {t["stop_id"]: t for t in result.get("timeline", [])}
        details = {c["stop_id"]: c["detail"] for c in result.get("checks", []) if c.get("stop_id")}
        failing = [next(s for s in quest["stops"] if s["id"] == sid) for sid in result.get("failing_stop_ids", [])]
        failed_ids |= {s["place_id"] for s in failing}
        ts = time.perf_counter()
        rankings = await asyncio.gather(*(director.pick_swaps(
            quest, s, details.get(s["id"], "failed a live check"), failed_ids, area) for s in failing))
        if failing:
            emit(run_id, "swap", "info", _ms(ts),
                 f"gemini-3.8-flash ranked candidates for {len(failing)} stop(s) in parallel")
        for stop, ranked in zip(failing, rankings):
            sid = stop["id"]
            reason = details.get(sid, "failed a live check")
            arrive = timeline.get(sid, {}).get("arrive", now_iso)
            replacement = None
            for pid in ranked:
                cargs = ["--check-place", pid, "--at", arrive, "--dwell", str(stop["dwell_min"]), "--now", now_iso]
                ccode, cres, cms = await _run(cargs)
                log.append({"cmd": _cmd(cargs), "exit": ccode,
                            "result": f"{cres.get('name')}: {cres.get('status')}, {cres.get('detail')}"})
                emit(run_id, "places", "pass" if ccode == 0 else "fail", cms,
                     f"candidate {cres.get('name')}: {cres.get('detail') or cres.get('error')}",
                     cmd=log[-1]["cmd"], exit=ccode)
                if ccode == 0:
                    replacement = pid
                    break
                failed_ids.add(pid)
            if replacement:
                p = area["places"][replacement]
                old = stop["name"]
                stop.update(place_id=replacement, name=p["name"], unit=p.get("unit"),
                            category=p.get("category"), lat=p.get("lat"), lng=p.get("lng"), source="swap")
                swaps.append({"removed": old, "added": p["name"], "reason": reason})
                emit(run_id, "swap", "fixed", None, f"{old} -> {p['name']}", stop_id=sid,
                     removed=old, added=p["name"], reason=reason)
                changed = True
            elif len(quest["stops"]) > 2:
                quest["stops"] = [s for s in quest["stops"] if s["id"] != sid]
                swaps.append({"removed": stop["name"], "added": None, "reason": reason})
                emit(run_id, "swap", "fixed", None, f"dropped {stop['name']} (no open candidate)", stop_id=sid)
                changed = True
        if result.get("over_budget") and len(quest["stops"]) > 1:
            low = min(quest["stops"], key=lambda s: s["reward"]["points"])
            quest["stops"] = [s for s in quest["stops"] if s is not low]
            swaps.append({"removed": low["name"], "added": None, "reason": "over the time budget"})
            emit(run_id, "swap", "fixed", None, f"dropped {low['name']} to fit {quest['deadline_min']} min",
                 stop_id=low["id"])
            changed = True
        if not changed:
            break
    status = result.get("status")
    final = "error" if status == "error" else "pass" if status == "pass" and not swaps else \
        "fixed" if status == "pass" else "fail"
    quest["route"] = result.get("route")
    quest["verification"] = {
        "status": final, "path": "local_fallback", "checked_at": result.get("checked_at", now_iso),
        "total_min": result.get("total_min"), "back_by": result.get("back_by"),
        "timeline": result.get("timeline", []), "checks": result.get("checks", []),
        "swaps": swaps, "log": log, "error": result.get("error"),
        "timings_ms": {**(result.get("timings_ms") or {}), "verify_total": _ms(t0)},
    }
    quest["_failed_place_ids"] = sorted(failed_ids)
    return quest
