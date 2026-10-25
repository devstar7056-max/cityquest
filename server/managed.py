"""Managed-agent verifier: antigravity-preview-09-2026 (model gemini-4-argon) in a Google sandbox.

The quest, the candidate list and verifier/verify_quest.py are preloaded as inline
environment sources. The Maps key is a Credentials API secret that the egress proxy
injects as x-goog-api-key for places/routes.googleapis.com only, so it never enters
the sandbox or the model context. Every command the agent runs streams to the HUD
from the API's own code_execution_call / code_execution_result steps.
"""
import asyncio
import json
import os
import pathlib
import re
import threading
import time

from . import director
from .events import emit

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = (ROOT / "verifier" / "verify_quest.py").read_text()
PROMPT = (ROOT / "prompts" / "verifier_agent.md").read_text().split("---", 1)[-1].strip()
AGENT = "antigravity-preview-09-2026"
CREDENTIAL_ID = "cityquest-maps-server"
_cred_lock = threading.Lock()
_cred_ready = False


def ensure_credential():
    """Register MAPS_SERVER_KEY with the Credentials API once per process."""
    global _cred_ready
    with _cred_lock:
        if _cred_ready:
            return
        key = os.environ.get("MAPS_SERVER_KEY")
        if not key:
            raise RuntimeError("MAPS_SERVER_KEY is not set")
        c = director.client()
        try:
            c.credentials.delete(id=CREDENTIAL_ID)
        except Exception:
            pass
        c.credentials.create(id=CREDENTIAL_ID, type="bearer_token", token=key,
                             header_name="x-goog-api-key", prefix="")
        _cred_ready = True


def _candidates(quest, area):
    places = area["places"]
    used = {s["place_id"] for s in quest["stops"]} | set(quest.get("_failed_place_ids", []))
    keep = ("place_id", "name", "category", "what", "lat", "lng", "open_now", "distance_m")
    return [{k: p.get(k) for k in keep} for pid, p in places.items() if pid not in used]


def _public(quest):
    return {k: v for k, v in quest.items() if not k.startswith("_") and k not in ("route", "verification")}


def _short(result):
    out = result.replace("[STDOUT]", "").replace("[STDERR]", "").strip()
    try:
        j = json.loads(out[out.index("{"):out.rindex("}") + 1])
        if "failing_stop_ids" in j:
            return f"status {j['status']}, failing {j['failing_stop_ids'] or 'none'}, {j.get('total_min')} min"
        if "place_id" in j:
            return f"{j.get('name')}: {j.get('status')}, {j.get('detail')}"
        if j.get("status") == "error":
            return f"error: {j.get('error', '')[:140]}"
    except (ValueError, json.JSONDecodeError):
        pass
    return re.sub(r"\s+", " ", out)[:160]


def _run_stream(quest, now_iso, run_id, loop, done, area):
    """Blocking: stream the agent interaction, emitting each real command to the HUD."""
    t0 = time.perf_counter()
    ensure_credential()
    text = PROMPT.replace("{now_iso}", now_iso)
    text = re.sub(r"\nQUEST: .*?\nCANDIDATES: .*?\nSCRIPT: .*$", "\nQUEST, CANDIDATES and SCRIPT: already in /workspace "
                  "as quest.json, candidates.json and verify_quest.py. Work in /workspace.", text, flags=re.S)
    env = {"type": "remote",
           "sources": [
               {"type": "inline", "target": "/workspace/verify_quest.py", "content": SCRIPT},
               {"type": "inline", "target": "/workspace/quest.json", "content": json.dumps(_public(quest), indent=1)},
               {"type": "inline", "target": "/workspace/candidates.json", "content": json.dumps(_candidates(quest, area), indent=1)},
           ],
           "network": {"allowlist": [{"domain": "places.googleapis.com", "credential": CREDENTIAL_ID},
                                     {"domain": "routes.googleapis.com", "credential": CREDENTIAL_ID}]}}
    calls, log, final_text = {}, [], []

    def push(*a, **kw):
        loop.call_soon_threadsafe(lambda: emit(run_id, *a, **kw))

    push("agent", "start", None, f"{AGENT} (gemini-4-argon) sandbox starting")
    stream = director.client().interactions.create(
        agent=AGENT, agent_config={"type": "antigravity", "model": "gemini-4-argon"},
        input=text, environment=env, stream=True)
    for ev in stream:
        et = getattr(ev, "event_type", "")
        step = getattr(ev, "step", None)
        if et == "step.start" and step is not None:
            st = getattr(step, "type", None)
            if st == "code_execution_call":
                code = (getattr(step, "arguments", None) or {}).get("code", "") if isinstance(getattr(step, "arguments", None), dict) \
                    else getattr(step.arguments, "code", "")
                calls[step.id] = (code, time.perf_counter())
                push("agent", "info", None, f"$ {code[:200]}")
            elif st == "code_execution_result":
                code, ts = calls.get(step.call_id, ("?", time.perf_counter()))
                res = step.result or ""
                m = re.search(r"exit(?:[ _]?code)?[:= ]+(\d)", res, re.I)
                summary = _short(res)
                failed = bool(step.is_error) or "status fail" in summary or "closed" in summary
                log.append({"cmd": code[:300], "exit": int(m.group(1)) if m else (1 if step.is_error else None),
                            "result": summary})
                push("agent", "fail" if failed else "pass", round((time.perf_counter() - ts) * 1000), summary)
            elif st not in ("thought", "model_output", None):
                # Filesystem and other tool steps (e.g. the agent editing quest.json): show what it touched.
                if st.endswith("_result"):
                    continue
                d = step.model_dump(exclude_none=True) if hasattr(step, "model_dump") else {}
                args = d.get("arguments") or {}
                args = args if isinstance(args, dict) else {}
                target = args.get("path") or args.get("file_path") or args.get("target") or args.get("filename") or ""
                name = d.get("name") or st.replace("_call", "")
                push("agent", "info", None, f"{name} {target}".strip()[:200])
        elif et == "step.delta":
            d = getattr(ev, "delta", None)
            if d is not None and getattr(d, "type", None) == "text":
                final_text.append(d.text or "")
    text_out = "".join(final_text)
    qm = re.search(r"===QUEST_JSON===\s*(.*?)\s*===END===", text_out, re.S)
    verdict = None
    if qm:
        try:
            verdict = json.loads(qm.group(1)).get("verification", {})
        except json.JSONDecodeError:
            verdict = None
    ms = round((time.perf_counter() - t0) * 1000)
    status = (verdict or {}).get("status", "unknown")
    swaps = (verdict or {}).get("swaps") or []
    swap_text = "; ".join(f"{s.get('removed')} -> {s.get('added')}" for s in swaps)
    detail = (f"managed agent verdict {status.upper()} in {ms / 1000:.1f} s, {len(log)} sandbox commands"
              + (f", swaps: {swap_text}" if swaps else ""))
    push("agent", status if status in ("pass", "fixed", "fail", "error") else "info", ms, detail,
         agent={"status": status, "log": log, "swaps": swaps, "ms": ms})
    done["result"] = {"status": status, "log": log, "swaps": swaps, "ms": ms}


async def audit(quest, run_id, now_iso, area):
    """Run the managed agent on the Director's quest in parallel with the local path."""
    loop = asyncio.get_running_loop()
    done = {}
    try:
        await asyncio.to_thread(_run_stream, quest, now_iso, run_id, loop, done, area)
    except Exception as e:
        emit(run_id, "agent", "error", None, f"managed agent: {type(e).__name__}: {str(e)[:240]}")
        done["result"] = {"status": "error", "error": str(e)[:240]}
    return done.get("result")
