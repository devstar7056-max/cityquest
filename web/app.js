// CityQuest app: typed or spoken request -> /api/plan or /api/replan -> SSE steps -> map + HUD.
import * as hud from "./hud.js";
import * as map3d from "./map3d.js";

const cfg = window.CQ_CONFIG || {};
const $ = (id) => document.getElementById(id);
const myRuns = new Set();
let current = null; // last verified quest
let geo = null;     // device location, when the browser shares it (phone GPS or laptop Wi-Fi)
let mapStarted = false;
let busy = false;
let stopStates = {};

const newRunId = () => "r-" + Math.random().toString(16).slice(2, 8);
const fmtTime = (iso) => (iso ? new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }) : "");

function renderCard(q) {
  $("card").classList.remove("hidden");
  $("q-title").textContent = q.title;
  const v = q.verification || {};
  const back = v.back_by ? `, back by ${fmtTime(v.back_by)}` : "";
  const total = v.total_min != null ? `${Math.round(v.total_min)} of ${q.deadline_min} min` : `${q.deadline_min} min`;
  $("q-meta").textContent = `${q.stops.length} stops, ${total}${back}`;
  $("q-points").textContent = `${q.stops.reduce((a, s) => a + (s.reward?.points || 0), 0)} pts`;
  const costEl = $("q-cost");
  const c = q.cost;
  if (c && c.low != null) {
    costEl.innerHTML = `Est. $${c.low} to $${c.high}<small>Google Places price ranges per stop, not menu prices${c.unlisted?.length ? `; not listed: ${c.unlisted.join(", ")}` : ""}</small>`;
    costEl.classList.remove("hidden");
  } else if (c) {
    costEl.innerHTML = `Price not listed<small>Google has no price range for these stops</small>`;
    costEl.classList.remove("hidden");
  } else costEl.classList.add("hidden");
  const change = $("q-change");
  if (q.change_note) { change.textContent = q.change_note; change.classList.remove("hidden"); }
  else change.classList.add("hidden");
  const times = Object.fromEntries((v.timeline || []).map((t) => [t.stop_id, t]));
  const ol = $("q-stops");
  ol.innerHTML = "";
  q.stops.forEach((s, i) => {
    const li = document.createElement("li");
    li.dataset.stop = s.id;
    const st = stopStates[s.id] || (s.source === "swap" ? "swap" : "");
    if (st) li.classList.add(st);
    const icon = document.createElement("img");
    icon.alt = s.reward?.sprite || "";
    icon.src = `/web/sprites/${s.reward?.sprite}.png`;
    icon.onerror = () => {
      const span = document.createElement("span");
      span.className = "emoji";
      span.textContent = map3d.EMOJI[s.reward?.sprite] || "⭐";
      icon.replaceWith(span);
    };
    const mid = document.createElement("div");
    mid.innerHTML = `<div class="name"></div><div class="obj"></div>`;
    mid.querySelector(".name").textContent = `${i + 1}. ${s.name}${s.unit ? ` (${s.unit})` : ""}`;
    mid.querySelector(".obj").textContent = s.objective;
    const when = document.createElement("div");
    when.className = "when";
    const t = times[s.id];
    when.textContent = t ? `${fmtTime(t.arrive)}\n${s.dwell_min} min` : `${s.dwell_min} min`;
    when.style.whiteSpace = "pre";
    li.append(icon, mid, when);
    ol.append(li);
  });
}

function markStop(stopId, state) {
  stopStates[stopId] = state;
  document.querySelector(`#q-stops li[data-stop="${stopId}"]`)?.classList.remove("fail", "swap");
  document.querySelector(`#q-stops li[data-stop="${stopId}"]`)?.classList.add(state);
  map3d.setStopState(stopId, state);
}

async function onEvent(ev) {
  if (!myRuns.has(ev.run_id) && !cfg.questId) return;
  hud.log(ev);
  if (ev.ms != null && ["transcript", "director"].includes(ev.step) && ev.status === "pass") hud.timing(ev.step, ev.ms);
  if (ev.step === "area" && ev.area?.lat != null) {
    const c = { lat: ev.area.lat, lng: ev.area.lng };
    if (!mapStarted) startMap(c, ev.area.start?.name || ev.area.name); else map3d.recenter(c, ev.area.name);
  }
  if (ev.step === "director" && ev.status === "pass" && ev.quest) {
    stopStates = {};
    renderCard(ev.quest);
    await map3d.drawStops(ev.quest);
    map3d.flyTo(ev.quest.stops[0]);
    hud.badge("working", "VERIFYING");
  }
  if (ev.step === "places" && ev.stop_id && ev.status === "fail") markStop(ev.stop_id, "fail");
  if (ev.step === "swap" && ev.status === "fixed" && ev.stop_id) markStop(ev.stop_id, "swap");
  if (ev.step === "done" && ev.quest) await showFinal(ev.quest);
  if (ev.step === "agent" && ev.agent) {
    hud.path(`verifier: local ${(current?.verification?.status || "-").toUpperCase()} | managed agent sandbox: ${ev.agent.status.toUpperCase()} in ${(ev.agent.ms / 1000).toFixed(1)} s`);
  }
}

async function showFinal(q) {
  const t0 = performance.now();
  current = q;
  const v = q.verification || {};
  for (const sw of v.swaps || []) {
    const s = q.stops.find((x) => x.name === sw.added);
    if (s) stopStates[s.id] = "swap";
  }
  renderCard(q);
  await map3d.drawStops(q, stopStates);
  map3d.drawRoute(q.route?.encoded_polyline);
  const tm = q.timings_ms || {};
  for (const k of ["scan", "director", "places", "routes", "verify", "total"]) hud.timing(k, tm[k]);
  hud.setGenerated(q.generated_at);
  hud.badge(v.status || "error", (v.status || "error").toUpperCase());
  hud.path(`verifier: ${v.path === "managed_agent" ? "Antigravity managed agent (sandbox)" : "local, live Places + Routes"}${v.error ? `, ${v.error}` : ""} | managed agent: running in sandbox`);
  requestAnimationFrame(() => hud.timing("render", Math.round(performance.now() - t0)));
}

export async function plan({ request, minutes, wants, transcriptMs, typed, area } = {}) {
  if (busy) return { error: "busy" };
  busy = true;
  $("go").disabled = true;
  const runId = newRunId();
  myRuns.add(runId);
  hud.resetTimings();
  hud.badge("working", current ? "REPLANNING" : "PLANNING");
  const isReplan = !!current;
  const body = { request, minutes: minutes ?? null, wants: wants ?? null, run_id: runId, transcript_ms: transcriptMs ?? null,
    area: area ?? null, lat: geo?.lat ?? null, lng: geo?.lng ?? null };
  const [url, payload] = typed
    ? ["/api/ask", { text: request, quest_id: current?.quest_id ?? null, run_id: runId, lat: geo?.lat ?? null, lng: geo?.lng ?? null }]
    : [isReplan ? "/api/replan" : "/api/plan", isReplan ? { ...body, quest_id: current.quest_id } : body];
  try {
    const res = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || res.statusText);
    if (data.intent === "chit_chat") {
      hud.badge(current?.verification?.status || "idle", (current?.verification?.status || "ready").toUpperCase());
      return data;
    }
    await showFinal(data);
    return data;
  } catch (e) {
    hud.badge("error", "ERROR");
    hud.log({ step: "client", status: "error", detail: e.message });
    return { error: e.message };
  } finally {
    busy = false;
    $("go").disabled = false;
  }
}

export function newQuest() { current = null; }

// Run id for Live tool calls that are not quests (e.g. past_hackathons), so their HUD lines show up here.
let liveRun = null;
export function liveRunId() {
  if (!liveRun) { liveRun = newRunId(); myRuns.add(liveRun); }
  return liveRun;
}

window.cityquest = { plan, newQuest, get current() { return current; } };

function startMap(center, name) {
  if (mapStarted) return;
  mapStarted = true;
  map3d.initMap(cfg.mapsKey, center, (msg) => hud.log({ step: "map", status: "error", detail: msg }), name)
    .then((mode) => mode && hud.log({ step: "map", status: "pass", detail: `${mode === "3d" ? "Photorealistic 3D" : "2D"} map loaded at ${name}` }))
    .catch((e) => hud.log({ step: "map", status: "error", detail: e.message }));
}

async function main() {
  hud.startClock();
  const es = new EventSource("/api/events");
  es.onmessage = (m) => onEvent(JSON.parse(m.data));
  es.onerror = () => hud.path("event stream reconnecting");

  // Where are we? Device location first (asks permission), else the server's current live area,
  // else wait for the first `area` event from a request. Nothing is pinned to one place.
  const here = await new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    const done = (v) => resolve(v);
    navigator.geolocation.getCurrentPosition((p) => done({ lat: p.coords.latitude, lng: p.coords.longitude }), () => done(null),
      { enableHighAccuracy: true, timeout: 4000, maximumAge: 30000 });
    setTimeout(() => done(null), 4500);
  });
  if (here) {
    geo = here;
    hud.log({ step: "gps", status: "pass", detail: `device location ${here.lat.toFixed(5)}, ${here.lng.toFixed(5)}` });
    navigator.geolocation.watchPosition((p) => { geo = { lat: p.coords.latitude, lng: p.coords.longitude }; }, () => {}, { enableHighAccuracy: true, maximumAge: 10000 });
    startMap(here, "You");
  } else {
    hud.log({ step: "gps", status: "info", detail: "no device location; name a place, e.g. 'I'm on Valencia Street'" });
    const r = await fetch("/api/area").catch(() => null);
    if (r?.ok) { const a = await r.json(); startMap({ lat: a.lat, lng: a.lng }, a.name); }
  }

  if (cfg.questId) {
    const r = await fetch(`/api/quest/${cfg.questId}`);
    if (r.ok) await showFinal(await r.json());
  }

  $("ask").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("prompt").value.trim();
    if (!text) return;
    if (/^(new|start over|reset)\b/i.test(text)) current = null;
    plan({ request: text, typed: true });
  });

  import("./live.js").then((live) => live.init?.({ plan, newQuest, liveRunId, hud })).catch((e) => console.warn("live.js not loaded", e));
}

main();
