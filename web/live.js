// Gemini 3.8 Live: sees (camera or a video file), hears (mic or the video's own audio track), talks back,
// can be interrupted, and calls tools: plan_quest, replan, past_hackathons, plus Google Search.
// Camera and file share one path, so a recorded video replays through exactly the live pipeline.
// The browser only ever holds a single-use ephemeral token minted by /api/live-token.
import { GoogleGenAI, Modality, Behavior, FunctionResponseScheduling } from "https://cdn.jsdelivr.net/npm/@google/genai@2.29.1/+esm";

const $ = (id) => document.getElementById(id);
const FPS = 1;
let session = null, ctxIn = null, ctxOut = null, micStream = null, camStream = null, node = null, frameTimer = null;
let playHead = 0, playing = new Set();
let app = null, hud = null, runSource = null;
let userText = "", turnStart = null, modelText = "";

const TOOLS = [
  { googleSearch: {} },
  {
    functionDeclarations: [
      {
        name: "plan_quest", behavior: Behavior.NON_BLOCKING,
        description: "Build a brand new quest around where the person is, from what they want and how many minutes they have.",
        parameters: { type: "object", properties: {
          minutes: { type: "integer", description: "Minutes available. Assume 30 if not said." },
          wants: { type: "string", description: "What they want, in their words, e.g. 'a coffee and a croissant'." },
          area: { type: "string", description: "Where: a street, landmark or neighborhood they named or the camera clearly shows, with the city. Leave out to use their phone's location." } }, required: ["minutes", "wants"] },
      },
      {
        name: "replan", behavior: Behavior.NON_BLOCKING,
        description: "Change the current quest. Pass only what changed.",
        parameters: { type: "object", properties: {
          minutes: { type: "integer" }, wants: { type: "string" },
          drop: { type: "string", description: "A stop or kind of stop to remove." },
          area: { type: "string", description: "Only if the place changed." } } },
      },
      {
        name: "ask_city", behavior: Behavior.NON_BLOCKING,
        description: "Ask the City Memory: gemini-4-argon holding thousands of live Google Places with their reviews in one context. Use for questions like 'best croissant in the city' or 'quietest coffee near here'.",
        parameters: { type: "object", properties: { question: { type: "string" } }, required: ["question"] },
      },
      {
        name: "past_hackathons", behavior: Behavior.NON_BLOCKING,
        description: "Winners and projects of the previous Google I/O Hackathon (Cerebral Valley gallery snapshot).",
        parameters: { type: "object", properties: { query: { type: "string", description: "Optional topic to search projects for." } } },
      },
    ],
  },
];

function caption(text) {
  const el = $("caption");
  if (!text) { el.classList.add("hidden"); return; }
  el.textContent = text;
  el.classList.remove("hidden");
}

const b64 = (buf) => { let s = ""; const b = new Uint8Array(buf); for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode(...b.subarray(i, i + 0x8000)); return btoa(s); };

function playPcm(base64) {
  const bin = atob(base64);
  const pcm = new Int16Array(bin.length / 2);
  for (let i = 0; i < pcm.length; i++) pcm[i] = (bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8)) << 16 >> 16;
  const buf = ctxOut.createBuffer(1, pcm.length, 24000);
  const ch = buf.getChannelData(0);
  for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 32768;
  const src = ctxOut.createBufferSource();
  src.buffer = buf;
  src.connect(ctxOut.destination);
  playHead = Math.max(playHead, ctxOut.currentTime + 0.03);
  src.start(playHead);
  playHead += buf.duration;
  playing.add(src);
  src.onended = () => playing.delete(src);
}

function stopPlayback() {
  for (const s of playing) { try { s.stop(); } catch {} }
  playing.clear();
  playHead = 0;
}

function respond(fc, response) {
  session?.sendToolResponse({ functionResponses: [{ id: fc.id, name: fc.name, response, scheduling: FunctionResponseScheduling.INTERRUPT }] });
}

async function handleToolCall(fc) {
  const args = fc.args || {};
  hud.log({ step: "live", status: "info", detail: `tool ${fc.name}(${JSON.stringify(args)})` });
  if (fc.name === "ask_city") {
    const r = await fetch("/api/ask-city", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: args.question || "", run_id: app.liveRunId() }) });
    respond(fc, r.ok ? await r.json() : { error: `city memory unavailable (${r.status})` });
    return;
  }
  if (fc.name === "past_hackathons") {
    const r = await fetch(`/api/past-hackathons?run_id=${encodeURIComponent(app.liveRunId())}${args.query ? `&q=${encodeURIComponent(args.query)}` : ""}`);
    respond(fc, r.ok ? await r.json() : { error: `gallery unavailable (${r.status})` });
    return;
  }
  const words = userText.trim() || args.wants || "";
  const transcriptMs = turnStart ? Math.round(performance.now() - turnStart) : null;
  if (fc.name === "plan_quest") app.newQuest();
  if (args.area) hud.log({ step: "vision", status: "pass", detail: `Live area: ${args.area}` });
  const q = await app.plan({ request: words || `${args.minutes} minutes, ${args.wants}`, minutes: args.minutes ?? null,
    wants: args.wants ?? null, transcriptMs, area: args.area ?? null });
  userText = ""; turnStart = null;
  const v = q.verification || {};
  respond(fc, q.error ? { error: q.error } : {
    title: q.title, status: v.status, stops: q.stops.map((s) => s.name), first_stop: q.stops[0]?.name,
    total_min: v.total_min, deadline_min: q.deadline_min, back_by: v.back_by,
    estimated_cost: q.cost && q.cost.low != null ? `$${q.cost.low} to $${q.cost.high} (Google price ranges)` : "price not listed",
    swaps: (v.swaps || []).map((s) => ({ removed: s.removed, added: s.added, reason: s.reason })), change_note: q.change_note,
  });
}

function onMessage(msg) {
  const sc = msg.serverContent;
  if (sc?.interrupted) stopPlayback();
  if (sc?.inputTranscription?.text) {
    if (!turnStart) turnStart = performance.now();
    userText += sc.inputTranscription.text;
    caption(`You: ${userText}`);
  }
  if (sc?.outputTranscription?.text) {
    modelText += sc.outputTranscription.text;
    caption(`Guide: ${modelText}`);
  }
  if (sc?.turnComplete) {
    if (modelText.trim()) hud.log({ step: "guide", status: "info", detail: modelText.trim().slice(0, 240) });
    modelText = "";
  }
  const gm = sc?.groundingMetadata;
  if (gm?.webSearchQueries?.length || gm?.groundingChunks?.length) {
    const sources = (gm.groundingChunks || []).map((c) => c.web?.title || c.web?.uri).filter(Boolean).slice(0, 3);
    hud.log({ step: "search", status: "pass", detail: `Google Search: ${(gm.webSearchQueries || []).join(" | ")}${sources.length ? ` -> ${sources.join(", ")}` : ""}` });
  }
  for (const part of sc?.modelTurn?.parts || []) {
    if (part.inlineData?.data) playPcm(part.inlineData.data);
    if (part.executableCode?.code) hud.log({ step: "live", status: "info", detail: `code: ${part.executableCode.code.slice(0, 160)}` });
  }
  for (const fc of msg.toolCall?.functionCalls || []) handleToolCall(fc);
}

const WORKLET = `class Pcm extends AudioWorkletProcessor {
  process(inputs) { const ch = inputs[0][0]; if (ch) { const o = new Int16Array(ch.length);
    for (let i = 0; i < ch.length; i++) { const s = Math.max(-1, Math.min(1, ch[i])); o[i] = s < 0 ? s * 0x8000 : s * 0x7fff; }
    this.port.postMessage(o.buffer, [o.buffer]); } return true; } }
registerProcessor("pcm", Pcm);`;

function startFrames(videoEl) {
  const canvas = document.createElement("canvas");
  const g = canvas.getContext("2d");
  let sent = 0;
  frameTimer = setInterval(() => {
    if (!session || !videoEl.videoWidth || videoEl.paused && runSource === "file") return;
    const w = 768, h = Math.round((videoEl.videoHeight / videoEl.videoWidth) * w);
    canvas.width = w; canvas.height = h;
    g.drawImage(videoEl, 0, 0, w, h);
    const data = canvas.toDataURL("image/jpeg", 0.7).split(",")[1];
    session.sendRealtimeInput({ video: { data, mimeType: "image/jpeg" } });
    if (++sent === 1) hud.log({ step: "vision", status: "pass", detail: `streaming ${runSource} frames to gemini-3.8-live at ${FPS} fps` });
  }, 1000 / FPS);
}

async function connect() {
  const t0 = performance.now();
  const r = await fetch("/api/live-token", { method: "POST" });
  const tok = await r.json();
  if (!r.ok) throw new Error(tok.detail || "token failed");
  const ai = new GoogleGenAI({ apiKey: tok.token, httpOptions: { apiVersion: "v1alpha" } });
  ctxOut = new AudioContext({ sampleRate: 24000 });
  session = await ai.live.connect({
    model: tok.model,
    config: { responseModalities: [Modality.AUDIO], systemInstruction: tok.system, tools: TOOLS,
      inputAudioTranscription: {}, outputAudioTranscription: {} },
    callbacks: {
      onmessage: onMessage,
      onerror: (e) => hud.log({ step: "live", status: "error", detail: e.message || "socket error" }),
      onclose: (e) => { hud.log({ step: "live", status: "info", detail: `session closed ${e.reason || ""}` }); stop(true); },
    },
  });
  hud.log({ step: "live", status: "pass", ms: Math.round(performance.now() - t0), detail: `${tok.model} connected (ephemeral token, ${runSource} input)` });
}

async function audioPipe(sourceNodeFactory) {
  ctxIn = new AudioContext({ sampleRate: 16000 });
  await ctxIn.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" })));
  node = new AudioWorkletNode(ctxIn, "pcm");
  node.port.onmessage = (e) => session?.sendRealtimeInput({ audio: { data: b64(e.data), mimeType: "audio/pcm;rate=16000" } });
  const src = sourceNodeFactory(ctxIn);
  src.connect(node);
  return src;
}

// Live camera + mic (phone demo).
async function startCamera() {
  runSource = "camera";
  const preview = $("preview");
  try {
    camStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 } } });
    preview.srcObject = camStream;
    preview.muted = true;
    await preview.play();
    $("preview-wrap").classList.remove("hidden");
  } catch (e) {
    hud.log({ step: "vision", status: "error", detail: `camera unavailable (${e.name}); voice only` });
  }
  await connect();
  micStream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
  await audioPipe((ctx) => ctx.createMediaStreamSource(micStream));
  if (camStream) startFrames(preview);
}

// Recorded video: its frames and its own audio track (your voice) drive the same Live session.
async function startFile(url) {
  runSource = "file";
  const preview = $("preview");
  preview.srcObject = null;
  preview.src = url;
  preview.muted = false;
  preview.crossOrigin = "anonymous";
  $("preview-wrap").classList.remove("hidden");
  await connect();
  const src = await audioPipe((ctx) => ctx.createMediaElementSource(preview));
  src.connect(ctxIn.destination); // keep the recorded voice audible for the screen recording
  startFrames(preview);
  // Optional typed request for recordings with no spoken request (?say=...&say_at=seconds). It is typed into
  // the same Live session and labeled as typed in the HUD, never passed off as speech.
  const qs = new URLSearchParams(location.search);
  const say = qs.get("say");
  if (say) {
    const at = Number(qs.get("say_at") || 8);
    setTimeout(() => {
      if (!session) return;
      hud.log({ step: "typed", status: "info", detail: `typed into the Live session: "${say}"` });
      caption(`Typed: ${say}`);
      session.sendRealtimeInput({ text: say });
    }, at * 1000);
  }
  preview.onended = () => {
    hud.log({ step: "vision", status: "info", detail: "video ended; session stays open for replies" });
    session?.sendRealtimeInput({ audioStreamEnd: true });
  };
  await preview.play();
  hud.log({ step: "vision", status: "pass", detail: `replaying ${url.split("/").pop()} (frames + its audio track)` });
}

function stop(fromClose = false) {
  clearInterval(frameTimer);
  try { node?.disconnect(); } catch {}
  micStream?.getTracks().forEach((t) => t.stop());
  camStream?.getTracks().forEach((t) => t.stop());
  ctxIn?.close().catch(() => {});
  if (!fromClose) session?.close();
  stopPlayback();
  const p = $("preview");
  p.pause?.();
  session = null; micStream = null; camStream = null; node = null; ctxIn = null; frameTimer = null;
  $("mic").classList.remove("on");
  $("preview-wrap").classList.add("hidden");
  caption("");
}

export function init(deps) {
  app = deps; hud = deps.hud;
  $("mic").addEventListener("click", async () => {
    if (session) { stop(); return; }
    $("mic").classList.add("on");
    try { await startCamera(); } catch (e) { hud.log({ step: "live", status: "error", detail: e.message }); stop(); }
  });
  $("file").addEventListener("change", async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (session) stop();
    $("mic").classList.add("on");
    try { await startFile(URL.createObjectURL(f)); } catch (err) { hud.log({ step: "live", status: "error", detail: err.message }); stop(); }
  });
  const replay = new URLSearchParams(location.search).get("replay");
  if (replay) {
    $("replay").classList.remove("hidden");
    $("replay").addEventListener("click", async () => {
      $("replay").classList.add("hidden");
      $("mic").classList.add("on");
      try { await startFile(replay); } catch (err) { hud.log({ step: "live", status: "error", detail: err.message }); stop(); }
    });
  }
}
