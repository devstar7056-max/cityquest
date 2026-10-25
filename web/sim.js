// CityQuest Sim: Google Photorealistic 3D Tiles in Three.js, driven by the same live SSE stream as the app.
// Any area "opens up": every place found live rises out of the map as a floating beacon (green open,
// red closed, grey unknown), the quest's stops become numbered gold beacons, and the verified walking
// route becomes a glowing path the camera flies along. Headset mode renders a stereo pair.
import * as THREE from "three";
import { TilesRenderer } from "3d-tiles-renderer";
import { GoogleCloudAuthPlugin, GLTFExtensionsPlugin, ReorientationPlugin, TilesFadePlugin, TileCompressionPlugin } from "3d-tiles-renderer/plugins";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";
import { VRButton } from "three/addons/webxr/VRButton.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

// Stall asset (Higgsfield: GPT Image 2.5 reference, Hunyuan3D image-to-3D), placed at each real place position
// inside the breakdown. Illustrative model, real positions; falls back to boxes if the GLB is missing.
let stallModel = null;
new GLTFLoader().load("/web/assets/stall.glb", (g) => {
  const obj = g.scene;
  const box = new THREE.Box3().setFromObject(obj);
  const size = box.getSize(new THREE.Vector3());
  obj.scale.setScalar(7 / Math.max(size.x, size.z, 0.001));
  box.setFromObject(obj);
  const c = box.getCenter(new THREE.Vector3());
  obj.position.set(-c.x, -box.min.y, -c.z);
  stallModel = new THREE.Group();
  stallModel.add(obj);
}, undefined, () => {});

const cfg = window.CQ_CONFIG || {};
const $ = (id) => document.getElementById(id);
const D2R = Math.PI / 180;
// Origin: the live area (server's current area), else this device's location, else the first area event.
// Ground height starts as an estimate and is then measured by raycasting the real tiles.
let groundH = -29; // starting estimate (typical San Francisco geoid offset); refined by measureGround()
let areaInfo = null;
async function findOrigin() {
  try { const r = await fetch("/api/area"); if (r.ok) { areaInfo = await r.json(); return { lat: areaInfo.lat, lng: areaInfo.lng }; } } catch {}
  const g = await new Promise((res) => {
    if (!navigator.geolocation) return res(null);
    navigator.geolocation.getCurrentPosition((p) => res({ lat: p.coords.latitude, lng: p.coords.longitude }), () => res(null), { timeout: 4000 });
    setTimeout(() => res(null), 4500);
  });
  if (g) return g;
  document.getElementById("boot").textContent = "Waiting for a location: start a quest on the phone or name a place";
  return new Promise((res) => {
    const es0 = new EventSource("/api/events");
    es0.onmessage = (m) => { const ev = JSON.parse(m.data); if (ev.step === "area" && ev.area?.lat != null) { es0.close(); areaInfo = ev.area; res({ lat: ev.area.lat, lng: ev.area.lng }); } };
  });
}
let origin = await findOrigin();
const COLORS = { open: 0x2ecc71, closed: 0xff4d4d, unknown: 0x8892a6, stop: 0xffc233, swap: 0x2ecc71, fail: 0xff4d4d };

// ---------- renderer, scene, tiles ----------
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.xr.enabled = true;
document.body.prepend(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x9cc6f2);
// Google tiles are unlit; these lights are for our lit assets (the stall models).
scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.6));
const sun = new THREE.DirectionalLight(0xffffff, 1.4);
sun.position.set(300, 600, 200);
scene.add(sun);
const camera = new THREE.PerspectiveCamera(60, innerWidth / innerHeight, 1, 40000);
camera.position.set(-500, 260, 450);

const tiles = new TilesRenderer();
tiles.registerPlugin(new GoogleCloudAuthPlugin({ apiToken: cfg.mapsKey, autoRefreshToken: true }));
tiles.registerPlugin(new GLTFExtensionsPlugin({ dracoLoader: new DRACOLoader().setDecoderPath("https://www.gstatic.com/draco/versioned/decoders/1.5.7/") }));
tiles.registerPlugin(new TileCompressionPlugin());
tiles.registerPlugin(new TilesFadePlugin());
const reorient = new ReorientationPlugin({ lat: origin.lat * D2R, lon: origin.lng * D2R, height: groundH, up: "+y", recenter: true });
tiles.registerPlugin(reorient);
tiles.setCamera(camera);
tiles.setResolutionFromRenderer(camera, renderer);
scene.add(tiles.group);

// Headset view: the WebGL canvas renders the left lens at half width, and a 2D canvas mirrors each frame
// into the right lens. (Per-eye viewports split one wide image across the lenses with this tiles renderer;
// at city scale, stereo depth from a 6 cm eye gap is negligible anyway.)
const mirror = document.createElement("canvas");
mirror.id = "mirror";
Object.assign(mirror.style, { position: "fixed", top: "0", left: "50%", width: "50%", height: "100%", display: "none" });
document.body.prepend(mirror);
const mirrorCtx = mirror.getContext("2d");
function layout() {
  const w = headset ? Math.floor(innerWidth / 2) : innerWidth, h = innerHeight;
  renderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  tiles.setResolutionFromRenderer(camera, renderer);
  mirror.width = renderer.domElement.width;
  mirror.height = renderer.domElement.height;
  mirror.style.display = headset ? "block" : "none";
}
let tilesReady = false;
tiles.addEventListener("load-tile-set", () => {
  tilesReady = true;
  $("boot").remove();
  tiles.group.updateMatrixWorld(true);
  scheduleGround();
  for (const s of pendingShops.splice(0)) addShop(s);
  if (pendingQuest) showQuest(pendingQuest);
});
tiles.addEventListener("load-error", (e) => log({ step: "tiles", status: "error", detail: String(e.error?.message || e.error || "tile load error") }));

// ---------- building breakdown: cutaway shader on the Google tiles ----------
// Fragments inside the focus building's footprint (its Google viewport, or the cluster of places around you)
// and above uY are discarded, so the roof peels away and our floor plan (each place at its real Places
// position) shows inside.
// The tiles are a surface mesh with no interior; the floor plan is ours, drawn from live data.
const CUT = {
  uCutOn: { value: 0 }, uCutY: { value: 60 }, uCutCenter: { value: new THREE.Vector2() },
  uCutAxis: { value: new THREE.Vector2(1, 0) }, uCutHalf: { value: new THREE.Vector2(1, 1) },
  uTower: { value: new THREE.Vector3(0, 0, -1) },
};
function patchMaterial(m) {
  if (!m || m.userData.cut) return;
  m.userData.cut = true;
  m.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, CUT);
    sh.vertexShader = sh.vertexShader
      .replace("void main() {", "varying vec3 vCutPos;\nvoid main() {")
      .replace("#include <project_vertex>", "#include <project_vertex>\nvCutPos = (modelMatrix * vec4(transformed, 1.0)).xyz;");
    sh.fragmentShader = sh.fragmentShader.replace("void main() {", `varying vec3 vCutPos;
uniform float uCutOn; uniform float uCutY; uniform vec2 uCutCenter; uniform vec2 uCutAxis; uniform vec2 uCutHalf; uniform vec3 uTower;
void main() {
  if (uCutOn > 0.5) {
    vec2 d = vCutPos.xz - uCutCenter;
    float a = dot(d, uCutAxis), b = dot(d, vec2(-uCutAxis.y, uCutAxis.x));
    bool inside = abs(a) < uCutHalf.x && abs(b) < uCutHalf.y;
    bool tower = uTower.z > 0.0 && distance(vCutPos.xz, uTower.xy) < uTower.z;
    if (inside && !tower && vCutPos.y > uCutY) discard;
  }`);
  };
  m.customProgramCacheKey = () => "cq-cut";
  m.needsUpdate = true;
}
tiles.addEventListener("load-content", () => {
  tiles.group.traverse((o) => { if (o.isMesh) (Array.isArray(o.material) ? o.material : [o.material]).forEach(patchMaterial); });
});

let floor = null, stalls = new Map(), cutTarget = 60;
function buildFootprint() {
  let c, u, L, W;
  const vp = areaInfo?.focus?.viewport;
  // Google viewports are padded; when places sit inside it, fit the box to those places instead.
  const inVp = vp ? [...shops.values()].filter((s) => s.data.lat >= vp.low.latitude && s.data.lat <= vp.high.latitude &&
    s.data.lng >= vp.low.longitude && s.data.lng <= vp.high.longitude).map((s) => s.group.position) : [];
  if (inVp.length >= 3) {
    c = inVp.reduce((a, p) => a.add(new THREE.Vector2(p.x, p.z)), new THREE.Vector2()).divideScalar(inVp.length);
    let sxx = 0, szz = 0, sxz = 0;
    for (const p of inVp) { const dx = p.x - c.x, dz = p.z - c.y; sxx += dx * dx; szz += dz * dz; sxz += dx * dz; }
    const ang = 0.5 * Math.atan2(2 * sxz, sxx - szz);
    u = new THREE.Vector2(Math.cos(ang), Math.sin(ang));
    L = 0; W = 0;
    for (const p of inVp) { const d = new THREE.Vector2(p.x - c.x, p.z - c.y); L = Math.max(L, Math.abs(d.dot(u))); W = Math.max(W, Math.abs(d.x * -u.y + d.y * u.x)); }
    L = Math.min(L + 10, 120); W = Math.min(W + 8, 45);
  } else if (vp) {
    // The focus place's own Google viewport is its real bounding box.
    const sw = toScene(vp.low.latitude, vp.low.longitude), se = toScene(vp.low.latitude, vp.high.longitude), nw = toScene(vp.high.latitude, vp.low.longitude);
    const ex = new THREE.Vector2(se.x - sw.x, se.z - sw.z), ny = new THREE.Vector2(nw.x - sw.x, nw.z - sw.z);
    c = new THREE.Vector2(sw.x + (ex.x + ny.x) / 2, sw.z + (ex.y + ny.y) / 2);
    u = ex.clone().normalize();
    L = ex.length() / 2; W = ny.length() / 2;
  } else {
    // GPS only: the cluster of places within 150 m of where you stand, oriented by its main axis.
    const pts = [...shops.values()].map((s) => s.group.position).filter((p) => Math.hypot(p.x, p.z) < 150);
    if (pts.length < 3) return false;
    c = pts.reduce((a, p) => a.add(new THREE.Vector2(p.x, p.z)), new THREE.Vector2()).divideScalar(pts.length);
    let sxx = 0, szz = 0, sxz = 0;
    for (const p of pts) { const dx = p.x - c.x, dz = p.z - c.y; sxx += dx * dx; szz += dz * dz; sxz += dx * dz; }
    const ang = 0.5 * Math.atan2(2 * sxz, sxx - szz);
    u = new THREE.Vector2(Math.cos(ang), Math.sin(ang));
    L = 0; W = 0;
    for (const p of pts) { const d = new THREE.Vector2(p.x - c.x, p.z - c.y); L = Math.max(L, Math.abs(d.dot(u))); W = Math.max(W, Math.abs(d.x * -u.y + d.y * u.x)); }
    L += 12; W += 12;
  }
  L = THREE.MathUtils.clamp(L, 15, 160); W = THREE.MathUtils.clamp(W, 12, 160);
  CUT.uCutCenter.value.copy(c); CUT.uCutAxis.value.copy(u); CUT.uCutHalf.value.set(L, W);
  if (floor) scene.remove(floor);
  floor = new THREE.Group();
  const slab = new THREE.Mesh(new THREE.PlaneGeometry(2 * L, 2 * W), new THREE.MeshBasicMaterial({ color: 0x0d1420, transparent: true, opacity: 0.78, depthWrite: false }));
  slab.rotation.x = -Math.PI / 2;
  const grid = new THREE.GridHelper(2 * L, Math.max(4, Math.round(L / 5)), 0x4da3ff, 0x24405f);
  grid.scale.z = W / L;
  grid.material.transparent = true; grid.material.opacity = 0.5;
  floor.add(slab, grid);
  floor.position.set(c.x, 1.2, c.y);
  floor.rotation.y = -Math.atan2(u.y, u.x);
  scene.add(floor);
  return true;
}

function insideCut(p) {
  const d = new THREE.Vector2(p.x, p.z).sub(CUT.uCutCenter.value), u = CUT.uCutAxis.value;
  return Math.abs(d.dot(u)) < CUT.uCutHalf.value.x && Math.abs(d.x * -u.y + d.y * u.x) < CUT.uCutHalf.value.y;
}

function addStall(s) {
  if (stalls.has(s.place_id) || !insideCut(s.group.position)) return;
  const color = shopColor(s.data);
  let box;
  if (stallModel) {
    box = new THREE.Group();
    box.add(stallModel.clone(true));
    const ring = new THREE.Mesh(new THREE.RingGeometry(4.6, 5.6, 32), new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide, transparent: true, opacity: 0.9 }));
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.15;
    box.add(ring);
    box.position.set(s.group.position.x, 1.3, s.group.position.z);
  } else {
    box = new THREE.Mesh(new THREE.BoxGeometry(7, 4, 7), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.85 }));
    box.add(new THREE.LineSegments(new THREE.EdgesGeometry(box.geometry), new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.6 })));
    box.position.set(s.group.position.x, 3.2, s.group.position.z);
  }
  box.scale.y = 0.01;
  box.userData.born = performance.now();
  scene.add(box);
  stalls.set(s.place_id, box);
}

function breakdown(on) {
  if (on && !buildFootprint()) return;
  CUT.uCutOn.value = on ? 1 : 0;
  cutTarget = on ? 7 : 60;
  if (on) { CUT.uCutY.value = 45; for (const s of shops.values()) addStall(s); }
  if (floor) floor.visible = on;
  for (const b of stalls.values()) b.visible = on;
  $("mode").textContent = on ? "BREAKDOWN" : $("mode").textContent;
}

// ---------- live areas: recenter and measure the ground ----------
const raycaster = new THREE.Raycaster();
// Lowest of 9 downward rays within 40 m of the origin. Accepted only when two consecutive readings agree within
// 3 m and the shift is plausible (coarse tiles load first and can read far off).
let lastReading = null;
function measureGround() {
  const ys = [];
  for (const [dx, dz] of [[0, 0], [40, 0], [-40, 0], [0, 40], [0, -40], [28, 28], [-28, 28], [28, -28], [-28, -28]]) {
    raycaster.set(new THREE.Vector3(dx, 3000, dz), new THREE.Vector3(0, -1, 0));
    const hit = raycaster.intersectObject(tiles.group, true)[0];
    if (hit) ys.push(hit.point.y);
  }
  if (ys.length < 3) return false;
  ys.sort((a, b) => a - b);
  const dy = ys[0]; // lowest surface around the origin is street (or water), not a roof
  if (Math.abs(dy) > 150) { lastReading = null; return false; }
  if (lastReading === null || Math.abs(dy - lastReading) > 3) { lastReading = dy; return false; }
  lastReading = null;
  if (Math.abs(dy) < 0.5) return true;
  groundH += dy;
  reorient.transformLatLonHeightToOrigin(origin.lat * D2R, origin.lng * D2R, groundH);
  tiles.group.updateMatrixWorld(true);
  relayout();
  log({ step: "sim", status: "pass", detail: `ground measured from the 3D tiles: ${groundH.toFixed(1)} m ellipsoid height` });
  return true;
}
function scheduleGround() {
  let tries = 0;
  lastReading = null;
  const t = setInterval(() => { if (measureGround() || ++tries > 40) clearInterval(t); }, 800);
}
function relayout() {
  for (const s of shops.values()) s.group.position.copy(toScene(s.data.lat, s.data.lng, 0));
  for (const [pid, b] of stalls) { const s = shops.get(pid); if (s) b.position.set(s.group.position.x, b.isMesh ? 3.2 : 1.3, s.group.position.z); }
  if (lastQuest) showQuest(lastQuest);
}
function clearArea() {
  for (const s of shops.values()) scene.remove(s.group);
  shops.clear(); shopIndex = 0;
  for (const b of stalls.values()) scene.remove(b);
  stalls.clear();
  if (floor) { scene.remove(floor); floor = null; }
  CUT.uCutOn.value = 0;
  clearQuest(); lastQuest = null;
  $("quest").hidden = true;
}
function recenter(a) {
  areaInfo = a;
  if (Math.hypot(a.lat - origin.lat, a.lng - origin.lng) < 0.0003) return; // same area (about 30 m)
  origin = { lat: a.lat, lng: a.lng };
  clearArea();
  reorient.transformLatLonHeightToOrigin(origin.lat * D2R, origin.lng * D2R, groundH);
  tiles.group.updateMatrixWorld(true);
  mode = "scan";
  log({ step: "sim", status: "info", detail: `recentered on ${a.name}` });
  scheduleGround();
}

function toScene(lat, lng, alt = 0) {
  const v = new THREE.Vector3();
  tiles.ellipsoid.getCartographicToPosition(lat * D2R, lng * D2R, groundH + alt, v);
  return v.applyMatrix4(tiles.group.matrixWorld);
}

// ---------- labels and beacons ----------
function label(text, color = "#f4ede1", scale = 1) {
  const c = document.createElement("canvas");
  const g = c.getContext("2d");
  g.font = "700 44px -apple-system, Segoe UI, sans-serif";
  const w = Math.ceil(g.measureText(text).width) + 36;
  c.width = w; c.height = 72;
  g.font = "700 44px -apple-system, Segoe UI, sans-serif";
  g.fillStyle = "rgba(8,12,20,0.82)";
  g.beginPath(); g.roundRect(0, 0, w, 72, 18); g.fill();
  g.fillStyle = color; g.textBaseline = "middle"; g.fillText(text, 18, 38);
  // Screen-space size (sizeAttenuation off) so labels stay readable whether the camera is near or far.
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), depthTest: false, transparent: true, sizeAttenuation: false }));
  sp.scale.set((w / 72) * 0.04 * scale, 0.04 * scale, 1);
  sp.renderOrder = 20;
  return sp;
}

function beacon(color, radius) {
  const grp = new THREE.Group();
  const orb = new THREE.Mesh(new THREE.SphereGeometry(radius, 20, 14), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.95, depthTest: false }));
  orb.renderOrder = 10;
  const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, 1, 6), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.55, depthTest: false }));
  stem.renderOrder = 9;
  grp.add(orb, stem);
  grp.userData = { orb, stem };
  return grp;
}

function setBeaconHeight(b, h) {
  b.userData.orb.position.y = h;
  b.userData.stem.scale.y = Math.max(h, 0.01);
  b.userData.stem.position.y = h / 2;
}

const shops = new Map(); // place_id -> {group, target, born, data}
const pendingShops = [];
let shopIndex = 0;

function shopColor(s) { return s.open_now === true ? COLORS.open : s.open_now === false ? COLORS.closed : COLORS.unknown; }

function addShop(s) {
  if (!tilesReady) { pendingShops.push(s); return; }
  if (shops.has(s.place_id) || s.lat == null) return;
  const b = beacon(shopColor(s), 3.2);
  b.position.copy(toScene(s.lat, s.lng, 0));
  const lab = label(s.name, s.open_now ? "#bff5d2" : s.open_now === false ? "#ffc4c4" : "#d5dbe6", 0.6);
  b.add(lab);
  scene.add(b);
  const target = 30 + (shopIndex++ % 7) * 8;
  shops.set(s.place_id, { group: b, lab, target, born: performance.now(), data: s });
  setBeaconHeight(b, 0.01);
}

function dimShops(keep) {
  for (const [pid, s] of shops) {
    const on = keep.has(pid);
    s.group.userData.orb.material.opacity = on ? 0.95 : 0.22;
    s.group.userData.stem.material.opacity = on ? 0.55 : 0.12;
    s.lab.visible = on;
  }
}

// ---------- quest: stops, route, flythrough ----------
let questObjs = [], route = null, curve = null, flyStart = 0, pendingQuest = null, lastQuest = null;
const stopBeacons = new Map();

function decodePolyline(str) {
  let i = 0, lat = 0, lng = 0; const out = [];
  while (i < str.length) {
    for (const k of [0, 1]) {
      let shift = 0, result = 0, b;
      do { b = str.charCodeAt(i++) - 63; result |= (b & 0x1f) << shift; shift += 5; } while (b >= 0x20);
      const d = result & 1 ? ~(result >> 1) : result >> 1;
      if (k === 0) lat += d; else lng += d;
    }
    out.push([lat / 1e5, lng / 1e5]);
  }
  return out;
}

function clearQuest() {
  for (const o of questObjs) scene.remove(o);
  questObjs = []; stopBeacons.clear();
  if (route) { scene.remove(route); route = null; }
  curve = null;
}

function showQuest(q) {
  if (!tilesReady) { pendingQuest = q; return; }
  pendingQuest = null;
  lastQuest = q;
  clearQuest();
  q.stops.forEach((s, i) => {
    if (s.lat == null) return;
    const color = s.source === "swap" ? COLORS.swap : COLORS.stop;
    const b = beacon(color, 4.5);
    b.position.copy(toScene(s.lat, s.lng, 0));
    setBeaconHeight(b, 72);
    const lab = label(`${i + 1}. ${s.name}`, "#ffe08a", 1.1);
    lab.position.y = 84;
    b.add(lab);
    scene.add(b);
    questObjs.push(b);
    stopBeacons.set(s.id, b);
  });
  dimShops(new Set(q.stops.map((s) => s.place_id)));
  const enc = q.route?.encoded_polyline;
  if (enc) {
    const pts = decodePolyline(enc).map(([la, ln]) => toScene(la, ln, 3));
    if (pts.length > 1) {
      curve = new THREE.CatmullRomCurve3(pts, false, "centripetal", 0.2);
      route = new THREE.Mesh(new THREE.TubeGeometry(curve, Math.min(600, pts.length * 6), 2.2, 8, false),
        new THREE.MeshBasicMaterial({ color: 0xffb020, transparent: true, opacity: 0.9, depthTest: false }));
      route.renderOrder = 8;
      scene.add(route);
      flyStart = performance.now();
      mode = "fly";
    }
  }
  $("quest").hidden = false;
  $("q-title").textContent = q.title;
  const v = q.verification || {};
  $("q-meta").textContent = `${(v.status || "").toUpperCase()} · ${Math.round(v.total_min ?? 0)} of ${q.deadline_min} min`;
  $("q-cost").textContent = q.cost?.low != null ? `Est. $${q.cost.low} to $${q.cost.high} (Google price ranges)` : "";
  $("q-stops").innerHTML = "";
  q.stops.forEach((s) => { const li = document.createElement("li"); li.textContent = s.name; $("q-stops").append(li); });
}

function markStop(stopId, color) {
  const b = stopBeacons.get(stopId);
  if (!b) return;
  b.userData.orb.material.color.setHex(color);
  b.userData.stem.material.color.setHex(color);
}

// ---------- camera ----------
let mode = "orbit"; // orbit | scan | fly
const look = new THREE.Vector3(0, 30, 0);
const camTarget = new THREE.Vector3();
const lookTarget = new THREE.Vector3();

function updateCamera(t) {
  if (mode === "fly" && curve) {
    const u = Math.min(1, (performance.now() - flyStart) / 14000);
    const p = curve.getPointAt(u);
    const ahead = curve.getPointAt(Math.min(1, u + 0.06));
    const dir = ahead.clone().sub(p).setY(0).normalize();
    camTarget.copy(p).addScaledVector(dir, -230).add(new THREE.Vector3(0, 150, 0));
    lookTarget.copy(ahead).add(new THREE.Vector3(0, 10, 0));
    if (u >= 1) mode = "orbit";
  } else {
    const r = mode === "scan" ? 300 : 520, h = mode === "scan" ? 150 : 240, speed = mode === "scan" ? 0.00006 : 0.00003;
    camTarget.set(Math.cos(t * speed) * r, h, Math.sin(t * speed) * r);
    lookTarget.set(0, 30, 0);
  }
  camera.position.lerp(camTarget, 0.035);
  look.lerp(lookTarget, 0.05);
  camera.lookAt(look);
}

// ---------- HUD ----------
function log(ev) {
  const div = document.createElement("div");
  div.className = ev.status || "";
  const t = ev.t ? new Date(ev.t) : new Date();
  div.textContent = `${t.toLocaleTimeString("en-GB", { hour12: false })} ${ev.step} ${ev.detail ?? ""}${ev.ms != null ? ` (${ev.ms} ms)` : ""}`;
  const el = $("log");
  el.append(div);
  while (el.children.length > 12) el.firstChild.remove();
}
setInterval(() => {
  $("clock").textContent = new Date().toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" });
  const a = [];
  tiles.getAttributions(a);
  $("attrib").textContent = a.filter((x) => x.type === "string").map((x) => x.value).join(" · ") || "Google";
}, 500);

// ---------- live events ----------
const es = new EventSource("/api/events");
es.onmessage = (m) => {
  const ev = JSON.parse(m.data);
  log(ev);
  if (ev.step === "area" && ev.area?.lat != null) recenter(ev.area);
  if (ev.step === "scan" && ev.status === "start") { mode = "scan"; $("mode").textContent = "SCANNING"; }
  if (ev.step === "scan" && ev.shop && ev.place_id) addShop({ place_id: ev.place_id, ...ev.shop });
  if (ev.step === "scan" && Array.isArray(ev.scan)) { ev.scan.forEach(addShop); setTimeout(() => breakdown(true), 300); }
  if (ev.step === "director" && ev.status === "pass" && ev.quest) { $("mode").textContent = "VERIFYING"; showQuest(ev.quest); }
  if (ev.step === "places" && ev.stop_id && ev.status === "fail") markStop(ev.stop_id, COLORS.fail);
  if (ev.step === "swap" && ev.status === "fixed" && ev.stop_id) markStop(ev.stop_id, COLORS.swap);
  if (ev.step === "done" && ev.quest) { $("mode").textContent = (ev.status || "").toUpperCase(); showQuest(ev.quest); }
};

// ---------- controls ----------
let headset = false;
$("headset").onclick = () => { headset = !headset; document.body.classList.toggle("headset", headset); layout(); };
$("orbit").onclick = () => { mode = "orbit"; };
$("cut").onclick = async () => {
  if (CUT.uCutOn.value > 0.5) { breakdown(false); return; }
  if (shops.size < 5) { // no scan yet: place shops from the resolved merchant list (positions only, no live status)
    const r = await fetch("/api/area");
    if (r.ok) { areaInfo = await r.json(); areaInfo.places.forEach(addShop); }
  }
  breakdown(true);
};
if (navigator.xr) navigator.xr.isSessionSupported?.("immersive-vr").then((ok) => ok && document.body.append(VRButton.createButton(renderer)));
addEventListener("resize", layout);



// ---------- recorder (local only): /sim?rec=SECONDS records the WebGL canvas and uploads it ----------
const recSec = Number(new URLSearchParams(location.search).get("rec") || 0);
if (recSec > 0) {
  const startRec = () => {
    const chunks = [];
    const rec = new MediaRecorder(renderer.domElement.captureStream(30), { mimeType: "video/webm;codecs=vp9", videoBitsPerSecond: 8_000_000 });
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    rec.onstop = async () => {
      const r = await fetch("/api/recording", { method: "POST", body: new Blob(chunks, { type: "video/webm" }) });
      log({ step: "rec", status: r.ok ? "pass" : "error", detail: r.ok ? `recording saved (${(await r.json()).file})` : `upload failed ${r.status}` });
    };
    rec.start(1000);
    log({ step: "rec", status: "info", detail: `recording the sim canvas for ${recSec} s` });
    setTimeout(() => rec.stop(), recSec * 1000);
  };
  setTimeout(startRec, 1500);
}

// ---------- loop ----------
renderer.setAnimationLoop((t) => {
  updateCamera(t);
  const now = performance.now();
  for (const s of shops.values()) {
    const k = Math.min(1, (now - s.born) / 1400);
    const ease = 1 - Math.pow(1 - k, 3);
    setBeaconHeight(s.group, s.target * ease + 0.01);
    s.lab.position.y = s.target * ease + 8;
  }
  for (const b of stopBeacons.values()) b.userData.orb.scale.setScalar(1 + 0.12 * Math.sin(now / 250));
  CUT.uCutY.value += (cutTarget - CUT.uCutY.value) * 0.02; // roof peels down smoothly
  for (const b of stalls.values()) b.scale.y = Math.min(1, (now - b.userData.born) / 900) + 0.01;
  camera.updateMatrixWorld();
  tiles.update();
  renderer.render(scene, camera);
  if (headset) mirrorCtx.drawImage(renderer.domElement, 0, 0); // same frame, before the buffer is cleared
});
