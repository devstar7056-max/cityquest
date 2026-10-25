<p align="center">
  <img src="docs/images/title-card.jpg" alt="CityQuest: live, verified quests on the street you are standing on" width="100%">
</p>

<p align="center">
  <b>Maps tell you where to go. CityQuest proves where you can go, right now.</b><br>
  Point your phone at the street, say how much time you have and what you want. CityQuest sees where you are,<br>
  checks every place around you live, plans a quest with Gemini 4 Argon, and proves it before you take a step.
</p>

<p align="center">
  <a href="https://cityquest-247490230415.us-west1.run.app"><b>Live app</b></a> ·
  <a href="https://cityquest-247490230415.us-west1.run.app/sim"><b>3D headset sim</b></a> ·
  <a href="https://cityquest-247490230415.us-west1.run.app/web/architecture.html"><b>Interactive architecture</b></a> ·
  Built in one day at the <b>Gemini 4 Argon SF Hackathon</b> (Oct 25, 2026)
</p>

---

## The person and the problem

**Me, an hour before judging.** I was jogging to the Ferry Building with 20 minutes between sessions. I wanted a coffee and a croissant, and I had no idea what was actually open, how long the walk was, or whether I would make it back on time.

Maps show you pins. They do not promise you will be back on time. **CityQuest turns your next block of time into a short game whose every stop is a real place that is open right now, and it proves the plan against live Google data before you start.**

It works on any street, not just the Ferry Building: give it your phone's location, point the camera at a landmark, or name a street, and it builds the world from live data in under a second.

## The vision

| | |
|---|---|
| <img src="docs/images/vision-sf-diorama.jpg" alt="isometric San Francisco waterfront diorama with a glowing quest path"> | <img src="docs/images/vision-quest-runner.jpg" alt="runner on a glowing path toward a clock tower with coffee and croissant tokens"> |
| **Your next hour becomes a game level:** a glowing route through the real streets around you. | **Every collectible is a real place** that is open right now, checked against live data. |
| <img src="docs/images/vision-building-breakdown.jpg" alt="cut-open market hall with green and red rings on stalls"> | <img src="docs/images/vision-game-city.jpg" alt="stylized sunset San Francisco game world"> |
| **Break the building open:** see what is inside and which places are open (green) or closed (red). The sim does this live with Google 3D Tiles. | **Any neighborhood becomes playable**, because the world is built from live data, not from a map we drew. |
| <img src="docs/images/vision-conference-gap.jpg" alt="conference floor with a person following a phone route out to a cafe"> | <img src="docs/images/vision-accessible-street.jpg" alt="accessible street with tactile paving, a wheelchair user and open cafes"> |
| **Who it is for first:** the 20-minute gap at a conference or a hackathon. | **Where it goes next:** routes that respect access needs, where a verified time budget matters most. |

<sub>Vision art generated with Gemini Nano Banana 2.1 (`scripts/gen_vision_images.py`). Every screenshot below is the real app.</sub>

## What happens in one request

| | |
|---|---|
| <img src="docs/images/pov-headset-lens.jpg" alt="first person headset lens view of the jog to the Ferry Building"> | **1. Real input.** The phone camera (about 1 frame a second), your voice and GPS stream into **Gemini 3.8 Live** with a single-use ephemeral token. It sees what you point at and calls `plan_quest` with the area it recognized. A recorded video replays through exactly the same path (its frames and its own audio track). |
| <img src="docs/images/sim-scan-shops-rise.jpg" alt="every place around the Ferry Building rises out of the 3D city as a green or red beacon"> | **2. The live world.** Google Places finds every place around you (about 40 in about 0.5 s) with open now, serves coffee / breakfast / dessert, price range and Google's own summary. In the Three.js sim each one rises out of the city as a beacon: green open, red closed. |
| <img src="docs/images/sim-ferry-breakdown-route.jpg" alt="the Ferry Building opened up with a cutaway, the verified walking route glowing"> | **3. Plan and prove.** **gemini-4-argon** plans 2 to 4 stops as schema-checked JSON. The verifier checks each stop's real opening hours for the exact visit window and the real walking time from Routes against your budget. If a check fails, **gemini-3.8-flash** ranks replacements, each is re-checked, and the quest reruns. The building opens up (cutaway) with a stall at each real place position, and the verified route glows. |
| <img src="docs/images/sim-valencia-live.jpg" alt="the sim re-centered on Valencia Street, planning live"> | **4. Any street, live.** "Let's do Valencia Street instead": the sim flies across the city, scans, plans and verifies there. Nothing is precomputed. |

In parallel, an **Antigravity managed agent** re-runs the same verifier in a Google-hosted sandbox and reports its own verdict, and **City Memory** (gemini-4-argon holding 2,088 places with their reviews, 565,115 tokens in one context) reviews the quest against the whole city. Both stream into the HUD as they finish; nobody waits on them.

## Architecture

<p align="center"><img src="docs/architecture.svg" alt="CityQuest architecture: real inputs, understand, plan and prove, experience" width="100%"></p>

## Every model has one job

| Job in the app | Model or agent | What it does in CityQuest |
|---|---|---|
| Lead brain: plan and replan | `gemini-4-argon` (Interactions API) | World Director. Plans only from the live places, structured output validated against `schema/quest.schema.json`, replans as a delta with `previous_interaction_id` |
| Whole-city reasoning | `gemini-4-argon`, City Memory | 2,088 live places with Google reviews in one stored context (565,115 input tokens, API-reported). Reviews every quest; answers `ask_city` ("best croissant in the whole city") |
| Autonomous sandbox verification | `antigravity-preview-09-2026` with `gemini-4-argon` | Runs `verify_quest.py` against live Places and Routes in a Google sandbox, swaps from candidates, reruns. The Maps key is a Credentials API secret injected by the egress proxy, never in the sandbox or the prompt |
| Voice and vision | `gemini-3.8-live` | Camera + mic (or a video's frames + audio), barge-in, non-blocking tools `plan_quest`, `replan`, `ask_city`, `past_hackathons`, plus Google Search |
| Fast parallel leaf work | `gemini-3.8-flash` | Ranks replacement places for every failing stop at once |
| Routing and extraction | `gemini-3.5-flash-lite` | Typed input: new quest, replan or chit chat; pulls out minutes, wants and the place |
| Collectible sprites | `gemini-nano-banana-2.1` | 15 reward sprites, generated once |
| Soundtrack | `lyria-3-clip-preview` | One 30 s loop, generated once |
| Cited research | `deep-research-preview-04-2026` | Cited notes on the Ferry Building merchants (one 704 s background run) |
| 3D world | Maps JavaScript API (Photorealistic 3D) and Map Tiles API in Three.js | Phone map with route and pins; the headset sim with the building breakdown |
| Live place facts | Places API (New) | Text Search, Nearby Search, Place Details: open now, serves, price range, summary, viewport |
| Walking time and route | Routes API `computeRoutes` (WALK) | Leg times and the encoded route line |
| Hosting | Cloud Run | HTTPS so phone camera and mic work |
| Video and assets | Higgsfield (GPT Image 2.5, Hunyuan3D, Seedance 2.5) | Stall model (image to 3D GLB), title card, sim-style redo of the real jog for the submission video |

## The verification loop (real, not staged)

`verifier/verify_quest.py` is deterministic, standard library only, and covered by 10 offline tests.

1. **Opening hours for the exact visit window**: arrival time comes from the real walking legs, the stay from the plan's dwell time, checked against today's `currentOpeningHours` periods.
2. **Business status**: permanently or temporarily closed places fail.
3. **Time budget**: walking (Routes, WALK) plus dwell must fit the person's minutes, including the walk back.
4. **On failure**: `gemini-3.8-flash` ranks replacements from the live places; each candidate is checked with `--check-place` for its arrival window; the quest reruns (at most 2 rounds). Over budget drops the lowest-value stop.
5. **Independent proof**: the managed agent runs the same script in its sandbox and reaches its own verdict.

Failures caught live today, each from a real API response:

| Request | What the verifier found | Fix |
|---|---|---|
| 45 min, coffee, uniquely SF | 4 stops: 19 min walking + 27 min at stops = 46 of 45 min | dropped Pier 14, rerun passed at 27 of 45 |
| 30 min, something sweet and a bay view | 33 of 30 min | dropped a stop, passed at 27 of 30 |
| Ferry Building, 20 min, coffee and a croissant | 23 of 20 min | dropped a stop, passed at 11 of 20 |
| Managed agent on the first quest | same over-budget failure in its sandbox | its own verdict: FIXED in 86.9 s, 2 sandbox commands |

## City Memory: using Argon's long context for real

A grid sweep of Places Nearby Search (225 cells, 450 calls, 8.8 s) collects 2,088 places within 4 km of the Ferry Building with Google's summary and up to four review snippets each. That snapshot is sent to `gemini-4-argon` once and stored (primed in 30 s). The API reports **565,115 input tokens** for that context.

* After every verified quest, a City Memory turn chained from that context adds what reviewers say about each stop and flags a higher-rated alternative nearby, for example: *"Blue Bottle Coffee: famous for New Orleans-style iced coffee, no indoor seating; higher rated nearby: Philz Coffee (4.4)"*.
* `ask_city` answers city-wide questions from the same context, for example "best croissant in the whole city" named Arsicault Bakery, Neighbor Bakehouse and Juniper with what reviewers say (29 s).
* We measured planning inside the memory at 17 to 44 s, too slow for a live turn, so planning uses the fresh area scan and City Memory runs in parallel. That is the honest trade: more than half of the 1M window holds the city; the live path stays under 15 s.

## No hard-coding: any street, live

* **Where** comes from the person: a named place (geocoded with Places Text Search), the device GPS, what Gemini Live recognizes in the camera, or the area the conversation is already in.
* **What** comes from Places Nearby Search around that center, every request (cached 90 s).
* The Three.js sim re-centers Google's 3D tiles on the new area and **measures the ground height by raycasting the real tiles**. The building breakdown fits its cutaway to the places inside the focus place's Google viewport.
* The past-hackathon answers are fetched live from the Cerebral Valley gallery (cached 10 min).

## Measured today

| Step | Time |
|---|---|
| Live area scan (Places) | 0.45 to 0.54 s for 39 to 40 places |
| Director (`gemini-4-argon`, thinking low) | 8.2 to 11.8 s |
| Verifier, local (Places + Routes) | 0.5 to 1.9 s |
| Typed request to verified quest | 10.5 to 14.9 s |
| Replan ("only 15 minutes, something sweet") | 11.0 s |
| Live token mint | 0.6 s; Live session connect 1.2 s |
| Managed agent full verify, fix, rerun | 86.9 s (in parallel) |
| City Memory turn | 29 to 35 s (in parallel), 565K tokens in context |

## How this maps to the judging criteria

**Working live demo (50%).** It runs on real inputs during judging: phone GPS, camera and voice, or any street a judge names. Gemini 4 Argon plans, a managed agent verifies in a sandbox, companion models each do one job, and the verification loop catches and fixes real failures on screen.

**Problem and usefulness (25%).** A specific person with a specific gap: 20 minutes, a coffee and a croissant, and the need to be back on time. Track: world models (a live, verified model of the street you stand on), plus Best Use of Managed Agents. It grows into an open "verified next hour" engine for conference apps, tourism boards, campus guides and accessibility planning where time budgets matter.

**Originality (15%).** A live world model of a real street, assembled from vision, voice and live Places data, reasoned over by Argon with a 565K-token city memory, proven by a sandboxed agent and rendered as a cut-open 3D world. Not possible before a model that holds a city's worth of places and reviews in one context while orchestrating vision, voice, tools and agents.

**Clarity (10%).** Who: a person with 20 minutes. Three minutes, no slides: say the request, watch the building open, watch a stop fail and get fixed, then ask the judges to name any street.

## Run it

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
python3 verifier/test_verify_quest.py                    # offline, 10 tests
export GEMINI_API_KEY=... MAPS_SERVER_KEY=... MAPS_BROWSER_KEY=...   # never commit keys
.venv/bin/python -m uvicorn server.main:app --port 8010  # open http://localhost:8010 and /sim
```

* `scripts/dev.sh` reads the three keys from the macOS Keychain instead of the shell.
* `scripts/setup_maps.sh PROJECT_ID` enables the Maps APIs and creates the two restricted keys.
* `scripts/build_city_memory.py "San Francisco Ferry Building" 4.0` builds and primes City Memory.
* `scripts/gen_assets.py` regenerates sprites, the music loop and the cited merchant notes.
* `scripts/fetch_gallery.py` snapshots the Google I/O Hackathon gallery.
* Deploy: `gcloud run deploy cityquest --source . --region us-west1 --allow-unauthenticated --min-instances 1 --max-instances 1 --no-cpu-throttling` with the three keys as environment variables.

Maps keys: the browser key is limited to Maps JavaScript and Map Tiles with a referrer allowlist; the server key to Places and Routes.

## Repo layout

```
server/     main.py (API, SSE, Live token)  area.py (live areas)  director.py (Argon, Flash, Flash-Lite)
            verify.py (local loop)  managed.py (Antigravity agent)  citymem.py (City Memory)  scan.py (cost)
web/        index.html app.js map3d.js hud.js live.js   phone app, Photorealistic 3D map, HUD, Gemini Live
            sim.html sim.js                              Three.js + Google 3D Tiles, breakdown, headset
            architecture.html sprites/ audio/ assets/stall.glb
verifier/   verify_quest.py  test_verify_quest.py
prompts/    director.md  verifier_agent.md  live_guide.md
schema/     quest.schema.json
scripts/    setup, City Memory, assets, gallery, submission video
docs/       architecture.svg, images
AGENTS.md   every quirk we hit today, with the fix
```

## Honesty notes

* Prices are Google's per-place price ranges, never menu prices. Missing Places fields are shown as unknown, never as no.
* The sim is Google Photorealistic 3D Tiles. Tiles are a surface mesh, so the "inside" of a building is our floor plan of real place positions with an illustrative stall model (Higgsfield GPT Image 2.5 to Hunyuan3D).
* The submission video uses real footage; the stylized segment is labeled as a Higgsfield redo. A Higgsfield reframe that invented a person was not used.
* Google Places content is fetched live and not committed; City Memory snapshots stay local (`data/` is git-ignored for Places data).
* Keys live only in environment variables or the Keychain. The repo was scanned for keys before every push.

## Credits

Built by Rakesh at the Gemini 4 Argon SF Hackathon (Cerebral Valley and Google DeepMind), Oct 25, 2026. Map data and 3D tiles: Google. Generated assets: Gemini (Nano Banana 2.1, Lyria), Higgsfield (GPT Image 2.5, Hunyuan3D, Seedance 2.5).
