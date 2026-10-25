"""CityQuest server: FastAPI serves web/ and /api. Keys come only from the environment."""
import asyncio
import copy
import json
import os
import pathlib
import secrets
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import area, citymem, director, events, managed, scan, verify
from .events import emit

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
SF = ZoneInfo("America/Los_Angeles")
QUESTS: dict[str, dict] = {}

app = FastAPI(title="CityQuest")
citymem.load()


class PlanIn(BaseModel):
    request: str
    minutes: int | None = None
    wants: str | None = None
    run_id: str | None = None
    transcript_ms: int | None = None
    area: str | None = None   # a street, landmark or neighborhood named by the person or seen by Live
    lat: float | None = None   # device GPS, when the browser shares it
    lng: float | None = None


class ReplanIn(PlanIn):
    quest_id: str
    drop: str | None = None


def _ms(t):
    return round((time.perf_counter() - t) * 1000)


def _public(q):
    return {k: v for k, v in q.items() if not k.startswith("_")}


async def _memory_notes(quest, run_id):
    """gemini-4-argon with the whole City Memory in context reviews the verified quest, in parallel."""
    cm = citymem.state["meta"] or {}
    emit(run_id, "memory", "start", None, f"gemini-4-argon City Memory: {cm.get('places')} places, "
         f"{(cm.get('input_tokens') or 0):,} tokens in one context, reviewing the quest")
    try:
        out, u, ms = await citymem.notes(quest)
    except Exception as e:
        emit(run_id, "memory", "error", None, f"City Memory: {type(e).__name__}: {str(e)[:160]}")
        return
    cached = u.get("total_cached_tokens")
    for s in out.get("stops", []):
        emit(run_id, "memory", "pass", None, f"{s['name']}: reviewers say {s['reviewers_say']}"
             + (f"; higher rated nearby: {s['better_nearby']}" if s.get("better_nearby") else ""))
    emit(run_id, "memory", "info", ms, f"City Memory turn: {(u.get('total_input_tokens') or 0):,} input tokens"
         + (f", {cached:,} served from cache" if cached else ""))


class CityQ(BaseModel):
    question: str
    run_id: str | None = None


@app.post("/api/ask-city")
async def ask_city(body: CityQ):
    if not citymem.state["interaction_id"]:
        raise HTTPException(503, "City Memory not built: run scripts/build_city_memory.py")
    run_id = body.run_id or "r-" + secrets.token_hex(3)
    cm = citymem.state["meta"] or {}
    emit(run_id, "memory", "start", None, f"asking the City Memory ({cm.get('places')} places, {(cm.get('input_tokens') or 0):,} tokens): {body.question!r}")
    answer, u, ms = await citymem.ask(body.question)
    emit(run_id, "memory", "pass", ms, answer[:300])
    return {"answer": answer, "ms": ms, "context_tokens": u.get("total_input_tokens"), "places": cm.get("places")}


def _attach_agent(qid, task):
    """Store the managed agent's audit on the quest once it finishes (it runs in parallel)."""
    if task.cancelled() or task.exception() or qid not in QUESTS:
        return
    QUESTS[qid].setdefault("verification", {})["agent"] = task.result()


async def _run(body: PlanIn, previous=None):
    run_id = body.run_id or "r-" + secrets.token_hex(3)
    t0 = time.perf_counter()
    now = datetime.now(SF)
    if body.transcript_ms is not None:
        emit(run_id, "transcript", "pass", body.transcript_ms, body.request)
    ts = time.perf_counter()
    try:
        # Where: a named place wins, then the device GPS, then the area this conversation is already in.
        if body.area:
            here = await area.get(run_id, query=body.area, lat=body.lat, lng=body.lng)
        elif previous is not None and previous.get("_area"):
            here = await area.get(run_id, query=previous["_area"].get("query"), lat=previous["_area"]["lat"] if not previous["_area"].get("query") else None,
                                  lng=previous["_area"]["lng"] if not previous["_area"].get("query") else None)
        else:
            here = await area.get(run_id, lat=body.lat, lng=body.lng)
    except Exception as e:
        emit(run_id, "area", "error", _ms(ts), f"{type(e).__name__}: {str(e)[:200]}")
        raise HTTPException(400, f"Where are you? {e}")
    scan_ms = _ms(ts)
    ctx = None
    if previous is None and os.environ.get("CQ_CITY_MEMORY_PLAN", "0") == "1" and citymem.state["interaction_id"]:
        ctx = citymem.state["interaction_id"]  # optional: plan inside the city memory (slower, 17 to 44 s measured)
    emit(run_id, "director", "start", None, f"gemini-4-argon planning: {body.request!r}")
    td = time.perf_counter()
    request = body.request
    if previous is not None and getattr(body, "drop", None):
        request = f"{request} (drop: {body.drop})"
    try:
        quest, iid, ms = await director.plan(request, body.minutes, body.wants, now=now, previous=previous, area=here, context_iid=ctx)
    except Exception as e:
        emit(run_id, "director", "error", _ms(td), f"{type(e).__name__}: {str(e)[:300]}")
        raise HTTPException(502, f"Director failed: {e}")
    emit(run_id, "director", "pass", ms,
         f"{quest['title']}: " + ", ".join(s["name"] for s in quest["stops"]), quest=_public(quest))
    qid = quest["quest_id"]
    if os.environ.get("MAPS_SERVER_KEY") and os.environ.get("CQ_AGENT", "1") == "1":
        agent_task = asyncio.create_task(managed.audit(copy.deepcopy(quest), run_id, now.isoformat(), here))
        agent_task.add_done_callback(lambda t: _attach_agent(qid, t))
    tv = time.perf_counter()
    try:
        quest = await verify.verify_local(quest, run_id, now.isoformat(), here)
    except Exception as e:
        emit(run_id, "verify", "error", _ms(tv), f"{type(e).__name__}: {str(e)[:300]}")
        raise HTTPException(502, f"Verifier failed: {e}")
    v = quest["verification"]
    quest["_interaction_id"] = iid
    quest["cost"] = scan.cost(quest, here["places"])
    quest["_area"] = {k: here.get(k) for k in ("name", "query", "lat", "lng")}
    quest["area"] = {k: here.get(k) for k in ("name", "lat", "lng", "focus", "start")}
    c = quest["cost"]
    if c["low"] is not None:
        emit(run_id, "cost", "info", None, f"estimated ${c['low']} to ${c['high']} from Google price ranges"
             + (f"; not listed: {', '.join(c['unlisted'])}" if c["unlisted"] else ""))
    quest["timings_ms"] = {"transcript": body.transcript_ms, "scan": scan_ms, "director": ms, "places": v["timings_ms"].get("places"),
                           "routes": v["timings_ms"].get("routes"), "verify": _ms(tv), "total": _ms(t0)}
    QUESTS[quest["quest_id"]] = quest
    if citymem.state["interaction_id"] and os.environ.get("CQ_CITY_MEMORY", "1") == "1":
        asyncio.create_task(_memory_notes(copy.deepcopy(_public(quest)), run_id))
    path = "managed agent" if v["path"] == "managed_agent" else "local verifier, live Places + Routes"
    emit(run_id, "done", v["status"], _ms(t0), f"{v['status'].upper()} via {path}", quest=_public(quest))
    return _public(quest)


@app.post("/api/plan")
async def plan(body: PlanIn):
    return await _run(body)


@app.post("/api/replan")
async def replan(body: ReplanIn):
    prev = QUESTS.get(body.quest_id)
    if prev is None:
        raise HTTPException(404, f"unknown quest_id {body.quest_id}")
    return await _run(body, previous=prev)


class AskIn(BaseModel):
    text: str
    quest_id: str | None = None
    run_id: str | None = None
    lat: float | None = None
    lng: float | None = None


@app.post("/api/ask")
async def ask(body: AskIn):
    """Typed box: gemini-3.5-flash-lite routes to a new quest, a replan, or a short reply."""
    run_id = body.run_id or "r-" + secrets.token_hex(3)
    has_quest = bool(body.quest_id and body.quest_id in QUESTS)
    try:
        r, ms = await director.route(body.text, has_quest)
    except Exception as e:
        emit(run_id, "route", "error", None, f"flash-lite: {type(e).__name__}: {str(e)[:200]}")
        r, ms = {"intent": "replan" if has_quest else "new_quest"}, None
    emit(run_id, "route", "pass", ms, f"gemini-3.5-flash-lite: {r.get('intent')}, minutes={r.get('minutes')}, wants={r.get('wants')!r}, place={r.get('place')!r}")
    if r["intent"] == "chit_chat":
        return {"intent": "chit_chat"}
    if r["intent"] == "replan":
        return await _run(ReplanIn(request=body.text, minutes=r.get("minutes"), wants=r.get("wants"), area=r.get("place"), lat=body.lat, lng=body.lng,
                                   drop=r.get("drop"), run_id=run_id, quest_id=body.quest_id),
                          previous=QUESTS[body.quest_id])
    return await _run(PlanIn(request=body.text, minutes=r.get("minutes"), wants=r.get("wants"), area=r.get("place"),
                             lat=body.lat, lng=body.lng, run_id=run_id))


@app.get("/api/events")
async def sse():
    return StreamingResponse(events.stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


LIVE_MODEL = "gemini-3.8-live"
LIVE_SYSTEM = (ROOT / "prompts" / "live_guide.md").read_text().split("\n", 1)[1].strip()


@app.post("/api/live-token")
async def live_token():
    """Single-use ephemeral token for Gemini Live in the browser. Never the API key."""
    from datetime import timedelta, timezone as tz
    from google import genai

    def mint():
        now = datetime.now(tz.utc)
        c = genai.Client(http_options={"api_version": "v1alpha"})
        return c.auth_tokens.create(config={
            "uses": 1, "expire_time": now + timedelta(minutes=30),
            "new_session_expire_time": now + timedelta(minutes=2),
            "http_options": {"api_version": "v1alpha"}})

    t = time.perf_counter()
    try:
        tok = await asyncio.to_thread(mint)
    except Exception as e:
        raise HTTPException(502, f"could not mint a Live token: {type(e).__name__}: {str(e)[:200]}")
    return {"token": tok.name, "model": LIVE_MODEL, "system": LIVE_SYSTEM, "ms": _ms(t)}


_gallery = {"t": 0.0, "data": None}


@app.get("/api/past-hackathons")
async def past_hackathons(q: str | None = None, run_id: str | None = None):
    """Google I/O Hackathon gallery (Cerebral Valley), fetched live and cached 10 min."""
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import fetch_gallery
    if not _gallery["data"] or time.time() - _gallery["t"] > 600:
        try:
            _gallery["data"] = await asyncio.to_thread(fetch_gallery.snapshot)
            _gallery["t"] = time.time()
        except Exception as e:
            if not _gallery["data"]:
                raise HTTPException(502, f"gallery fetch failed: {e}")
    g = _gallery["data"]
    out = {"source": g["source"], "fetched_at": g["fetched_at"], "project_count": g["project_count"],
           "winners": [{k: w[k] for k in ("award", "name", "team", "description", "url")} for w in g["winners"]]}
    if q:
        ql = q.lower()
        out["matches"] = [{k: p[k] for k in ("award", "name", "team", "description", "url")} for p in g["projects"]
                          if ql in (p["name"] + " " + (p["description"] or "")).lower()][:8]
    if run_id:
        emit(run_id, "gallery", "pass", None, f"fetched live: {g['project_count']} projects; "
             + "; ".join(f"{w['award']} {w['name']}" for w in g["winners"][:3]) + f" ({g['source']})")
    return out


@app.get("/api/area")
async def get_area(q: str | None = None, lat: float | None = None, lng: float | None = None, run_id: str | None = None):
    """Resolve and discover an area live (for the map and sim to center before a quest)."""
    try:
        a = await area.get(run_id or "r-area", query=q, lat=lat, lng=lng)
    except Exception as e:
        raise HTTPException(400, str(e))
    return {k: a.get(k) for k in ("name", "lat", "lng", "focus", "start")} | {"places": list(a["places"].values())}


@app.get("/api/quest/{quest_id}")
async def get_quest(quest_id: str):
    q = QUESTS.get(quest_id)
    if q is None:
        raise HTTPException(404, "unknown quest")
    return _public(q)


@app.get("/api/health")
async def health():
    return {"ok": True, "keys": {v: bool(os.environ.get(v)) for v in ("GEMINI_API_KEY", "MAPS_SERVER_KEY", "MAPS_BROWSER_KEY")},
            "area": area.current and area.current["name"], "quests": len(QUESTS),
            "city_memory": {k: (citymem.state["meta"] or {}).get(k) for k in ("places", "input_tokens", "center", "built_at")}}


from fastapi import Request


@app.post("/api/recording")
async def recording(req: Request):
    """Local-only: save a sim canvas recording for the submission video (CQ_ALLOW_RECORDING=1)."""
    if os.environ.get("CQ_ALLOW_RECORDING") != "1":
        raise HTTPException(403, "recording uploads are disabled on this server")
    data = await req.body()
    if len(data) > 300_000_000:
        raise HTTPException(413, "too large")
    out = ROOT / "media" / "work" / f"sim_rec_{time.strftime('%H%M%S')}.webm"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return {"file": out.name, "bytes": len(data)}


@app.get("/sim", response_class=HTMLResponse)
async def sim():
    """Three.js headset view: Google Photorealistic 3D Tiles + the same live event stream."""
    html = (WEB / "sim.html").read_text()
    cfg = {"mapsKey": os.environ.get("MAPS_BROWSER_KEY", "")}
    return html.replace("/*__CONFIG__*/", f"window.CQ_CONFIG = {json.dumps(cfg)};")


@app.get("/", response_class=HTMLResponse)
@app.get("/q/{quest_id}", response_class=HTMLResponse)
async def index(quest_id: str | None = None):
    html = (WEB / "index.html").read_text()
    cfg = {"mapsKey": os.environ.get("MAPS_BROWSER_KEY", ""), "questId": quest_id}
    return html.replace("/*__CONFIG__*/", f"window.CQ_CONFIG = {json.dumps(cfg)};")


app.mount("/web", StaticFiles(directory=WEB), name="web")
