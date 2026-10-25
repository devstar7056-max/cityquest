// HUD: wall clock, quest age, step timings, real call log, PASS / FIXED / FAIL badge.
// Everything shown here comes from server events or the browser's own clock.
const $ = (id) => document.getElementById(id);
let generatedAt = null;

const hms = (d) => d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" });
const hms24 = (d) => d.toLocaleTimeString("en-GB", { hour12: false });
const fmtMs = (ms) => (ms == null ? "-" : ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`);

export function startClock() {
  const tick = () => {
    const now = new Date();
    $("clock").textContent = hms(now);
    if (generatedAt) {
      const s = Math.max(0, Math.round((now - generatedAt) / 1000));
      $("generated").textContent = `Quest generated ${hms(generatedAt)}, ${s} s ago`;
    }
  };
  tick();
  setInterval(tick, 250);
}

export function setGenerated(iso) {
  generatedAt = iso ? new Date(iso) : null;
}

export function badge(status, label) {
  const el = $("badge");
  el.className = `badge ${status}`;
  el.textContent = label || status.toUpperCase();
}

export function path(text) {
  $("path").textContent = text || "";
}

export function timing(key, ms) {
  const cell = document.querySelector(`#timings [data-k="${key}"]`);
  if (cell) cell.textContent = fmtMs(ms);
}

export function resetTimings() {
  document.querySelectorAll("#timings [data-k]").forEach((c) => (c.textContent = "-"));
}

export function log(ev) {
  const li = document.createElement("li");
  li.className = ev.status;
  const t = ev.t ? new Date(ev.t) : new Date();
  const ms = ev.ms != null ? ` (${fmtMs(ev.ms)})` : "";
  li.innerHTML = `<span class="ts"></span><span class="step"></span><span class="st"></span><span class="d"></span>`;
  li.querySelector(".ts").textContent = hms24(t);
  li.querySelector(".step").textContent = ev.step;
  li.querySelector(".st").textContent = ["pass", "fail", "error", "fixed"].includes(ev.status) ? `${ev.status} ` : "";
  li.querySelector(".d").textContent = `${ev.detail ?? ""}${ms}`;
  const ol = $("log");
  ol.appendChild(li);
  while (ol.children.length > 200) ol.removeChild(ol.firstChild);
  ol.scrollTop = ol.scrollHeight;
}
