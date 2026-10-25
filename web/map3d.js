// Photorealistic 3D map (Map3DElement) with a 2D google.maps.Map fallback.
// Markers: one numbered pin per stop with its sprite; red while failing, green when swapped in.
export const EMOJI = {
  coffee: "☕", tea: "🍵", icecream: "🍦", chocolate: "🍫", pastry: "🥐", bread: "🍞", oyster: "🦪",
  book: "📖", ceramics: "🏺", clocktower: "🕰️", pier: "🌉", ferry: "⛴️", wine: "🍷", beer: "🍺", star: "⭐",
};
const COLORS = { pending: "#4da3ff", pass: "#2ecc71", fail: "#ff4d4d", swap: "#2ecc71", start: "#f4ede1" };

let mode = null; // "3d" | "2d"
let map, lib = {}, markers = new Map(), route = null, startMarker = null, pulseTimer = null;
const spriteOk = new Map();

function loadMapsApi(key) {
  // Google's dynamic library loader (bootstrap), key injected by the server at request time.
  ((g) => { var h, a, k, p = "The Google Maps JavaScript API", c = "google", l = "importLibrary", q = "__ib__", m = document, b = window; b = b[c] || (b[c] = {}); var d = b.maps || (b.maps = {}), r = new Set(), e = new URLSearchParams(), u = () => h || (h = new Promise(async (f, n) => { await (a = m.createElement("script")); e.set("libraries", [...r] + ""); for (k in g) e.set(k.replace(/[A-Z]/g, (t) => "_" + t[0].toLowerCase()), g[k]); e.set("callback", c + ".maps." + q); a.src = `https://maps.${c}apis.com/maps/api/js?` + e; d[q] = f; a.onerror = () => (h = n(Error(p + " could not load."))); a.nonce = m.querySelector("script[nonce]")?.nonce || ""; m.head.append(a); })); d[l] ? console.warn(p + " only loads once. Ignoring:", g) : (d[l] = (f, ...n) => r.add(f) && u().then(() => d[l](f, ...n))); })({ key, v: "weekly" });
}

async function spriteUrl(name) {
  const url = `/web/sprites/${name}.png`;
  if (!spriteOk.has(name)) {
    spriteOk.set(name, fetch(url, { method: "HEAD" }).then((r) => r.ok).catch(() => false));
  }
  return (await spriteOk.get(name)) ? url : null;
}

export async function initMap(key, center, onError = () => {}, startName = "You") {
  if (!key) {
    onError("MAPS_BROWSER_KEY is not set on the server, so the map cannot load");
    return null;
  }
  loadMapsApi(key);
  lib.geometry = await google.maps.importLibrary("geometry");
  lib.marker = await google.maps.importLibrary("marker");
  try {
    lib.maps3d = await google.maps.importLibrary("maps3d");
    map = new lib.maps3d.Map3DElement({
      center: { lat: center.lat, lng: center.lng, altitude: 0 },
      range: 800, tilt: 60, heading: 70, mode: "SATELLITE",
    });
    document.getElementById("map").append(map);
    mode = "3d";
  } catch (e) {
    console.warn("3D map failed, using 2D", e);
    onError(`3D map failed (${e.message}); using 2D`);
    const { Map } = await google.maps.importLibrary("maps");
    map = new Map(document.getElementById("map"), {
      center, zoom: 17, mapId: "DEMO_MAP_ID", tilt: 45, heading: 70, disableDefaultUI: true,
    });
    mode = "2d";
  }
  startMarker = await addPin({ lat: center.lat, lng: center.lng }, "S", startName, "start", null);
  return mode;
}

export function ready() { return !!map; }

// Move to a new live area: fly there and move the start pin. Old quest pins are cleared.
export async function recenter(center, name = "You") {
  if (!map || center?.lat == null) return;
  clearQuest();
  removeMarker(startMarker);
  startMarker = await addPin({ lat: center.lat, lng: center.lng }, "S", name, "start", null);
  if (mode === "3d") {
    map.flyCameraTo({ endCamera: { center: { lat: center.lat, lng: center.lng, altitude: 0 }, range: 800, tilt: 60, heading: map.heading ?? 0 }, durationMillis: 2500 });
  } else {
    map.panTo(center);
  }
}

async function addPin(pos, glyphText, title, state, sprite) {
  // Numbered glyphs: image glyphs render as black squares on 3D pins (see AGENTS.md); sprites live in the quest card.
  const { PinElement } = lib.marker;
  const pin = new PinElement({
    background: COLORS[state] || COLORS.pending,
    borderColor: "#0d1420",
    glyphColor: "#0d1420",
    glyphText,
    scale: 1.5,
  });
  let m;
  if (mode === "3d") {
    m = new lib.maps3d.Marker3DElement({
      position: { lat: pos.lat, lng: pos.lng, altitude: 25 }, altitudeMode: "RELATIVE_TO_GROUND",
      extruded: true, label: title,
    });
    m.append(pin);
    map.append(m);
  } else {
    m = new lib.marker.AdvancedMarkerElement({ map, position: pos, title, content: pin });
  }
  m._pin = pin;
  return m;
}

function removeMarker(m) {
  if (!m) return;
  if (mode === "3d") m.remove();
  else m.map = null;
}

export function clearQuest() {
  for (const m of markers.values()) removeMarker(m);
  markers.clear();
  if (route) { if (mode === "3d") route.remove(); else route.setMap(null); route = null; }
}

export async function drawStops(quest, states = {}) {
  if (!map) return;
  clearQuest();
  for (const [i, s] of quest.stops.entries()) {
    if (s.lat == null || s.lng == null) continue;
    const st = states[s.id] || (s.source === "swap" ? "swap" : "pending");
    markers.set(s.id, await addPin({ lat: s.lat, lng: s.lng }, String(i + 1), `${i + 1}. ${s.name}`, st, s.reward?.sprite));
  }
}

export function setStopState(stopId, state) {
  const m = markers.get(stopId);
  if (!m?._pin) return;
  m._pin.background = COLORS[state] || COLORS.pending;
  if (state === "fail") {
    clearInterval(pulseTimer);
    let on = true;
    pulseTimer = setInterval(() => {
      for (const mk of markers.values()) {
        if (mk._failing) mk._pin.background = on ? COLORS.fail : "#7a1010";
      }
      on = !on;
    }, 450);
  }
  m._failing = state === "fail";
}

export function drawRoute(encoded) {
  if (!map || !encoded) return;
  const pts = lib.geometry.encoding.decodePath(encoded).map((p) => ({ lat: p.lat(), lng: p.lng() }));
  if (route) { if (mode === "3d") route.remove(); else route.setMap(null); }
  if (mode === "3d") {
    route = new lib.maps3d.Polyline3DElement({
      strokeColor: "#ffb020", outerColor: "#0d1420", strokeWidth: 12, outerWidth: 0.35,
      altitudeMode: "CLAMP_TO_GROUND", drawsOccludedSegments: true,
    });
    route.path = pts;
    if (!route.path?.length) route.coordinates = pts;
    map.append(route);
  } else {
    route = new google.maps.Polyline({ path: pts, strokeColor: "#ffb020", strokeWeight: 6, map });
  }
}

export function flyTo(stop) {
  if (!map || stop?.lat == null) return;
  if (mode === "3d") {
    map.flyCameraTo({
      // Look from over the bay toward the city so the Embarcadero towers sit behind the stops, not in front.
      endCamera: { center: { lat: stop.lat, lng: stop.lng, altitude: 0 }, range: 650, tilt: 60, heading: 250 },
      durationMillis: 3000,
    });
  } else {
    map.panTo({ lat: stop.lat, lng: stop.lng });
  }
}
