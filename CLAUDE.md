# CityQuest: Gemini 4 Argon SF Hackathon (Sun Oct 25, 2026)

**Hard deadline: submissions close 5:00 PM PDT today. We submit at 4:45 PM.** Run `date` before planning. Feature freeze at 3:45 PM.

## What we're building
A judge says how much time they have and what they want: "45 minutes, good coffee, something uniquely San Francisco, back on time." Gemini 4 Argon turns that into a quest of 2 to 4 real stops around the Ferry Building, where the event is (SHACK15, 1 Ferry Building, Suite 201). A managed agent checks every stop against live Google data (today's opening hours, walking minutes), catches what fails, swaps it, and the route redraws on a photorealistic 3D map. The judge changes their mind out loud and the quest rebuilds in seconds.

One line: maps tell you where to go; games give you a reason to explore; CityQuest makes your next hour a quest where every collectible is a real place that is open right now.

The judges score working demos, live, with real inputs, in under 3 minutes (see the builder guide). Everything below serves that.

## Rules that do not bend
1. Keys come only from environment variables: `GEMINI_API_KEY`, `MAPS_SERVER_KEY`, `MAPS_BROWSER_KEY`. Never write a key into a file, log, commit, screenshot or chat, and never print env values. The server injects `MAPS_BROWSER_KEY` into the page at request time, so it is never in the repo.
2. Every stop is a real `place_id` from `data/merchants.json` (official Ferry Building map plus four landmarks, resolved through Places). The model never invents places, hours, prices, menu items or events.
3. Never fake the verifier. A failure on screen must come from a real API response. If everything happens to pass, the 15 minute replan fails the time check on its own.
4. Nothing that spends Higgsfield or ElevenLabs credits runs until Rakesh has seen the cost and said "y".
5. Don't delete files; move them to `_to_delete/`.
6. No em dashes in any UI copy, README or prompt.
7. No Walmart data. Event terms say shared materials are not confidential.
8. Human control: CityQuest never books, buys or messages anyone. Outbound links sit behind a tap.

## Stack: Google products, one job each
| Job | Product | ID / API | Priority |
|---|---|---|---|
| Plan and replan the quest ("World Director") | Gemini 4 Argon on the Interactions API | `gemini-4-argon`; `thinking_level` "low" for live turns (measure "medium" for the first plan; keep it only if under 15 s); replans pass `previous_interaction_id` | P0 |
| Verify against live data, fix, rerun | Antigravity managed agent | `antigravity-preview-09-2026`, `agent_config={"type":"antigravity","model":"gemini-4-argon"}`, remote environment with network allowlist `["places.googleapis.com","routes.googleapis.com"]`, Maps key registered with `client.credentials.create` | P0 |
| Voice in and out, barge-in, function calls | Gemini 3.8 Live | `gemini-3.8-live` in the browser with ephemeral tokens minted by our server | P0 |
| 3D world | Maps JavaScript API, Photorealistic 3D Maps | `Map3DElement`, `Marker3DElement`, `Polyline3DElement`, `flyCameraTo` | P0 |
| Opening hours today | Places API (New), Place Details | field mask `id,displayName,businessStatus,currentOpeningHours,utcOffsetMinutes` | P0 |
| Walking minutes and the route line | Routes API `computeRoutes` | `travelMode: "WALK"`, placeId waypoints | P0 |
| HTTPS hosting (phone mic needs it) | Cloud Run | `gcloud run deploy --source .` | P0 |
| Parallel leaf work | Gemini 3.8 Flash | `gemini-3.8-flash`: per-stop objective and reward copy in parallel | P1 |
| Intent routing, guardrail | Gemini 3.5 Flash-Lite | `gemini-3.5-flash-lite`: classify a transcript as new_quest / replan / chit_chat | P1 |
| Collectible sprites | Nano Banana 2.1 | `gemini-nano-banana-2.1`, generated once into `web/sprites/` (15 names in the schema), never at demo time; emoji fallback | P1 |
| Spoken quest card | Gemini 3.8 Flash TTS | `gemini-3.8-flash-tts` only where Live isn't already speaking | P1 |
| Background loop | Lyria | `lyria-3-clip-preview`, one 30 s loop, generated once | P2 |
| Architecture explainer | Gemini 4 Argon | interactive HTML diagram of what we built, generated at 4:05 PM | P1 |
| Video b-roll | Gemini Omni Flash | `gemini-omni-1.1-flash` (direct, or via Higgsfield) | video only |

**Before writing any Gemini code, install and read the official skills** (SETUP.md step 4). They hold the current Interactions API, Live API, Managed Agents and Credentials API shapes. Where a skill and this file disagree, the skill wins; write the difference in `AGENTS.md`. Docs: ai.google.dev/gemini-api/docs, ai.google.dev/gemini-api/docs/antigravity-agent, developers.google.com/maps/documentation/javascript/3d.

## Architecture
```
BROWSER (web/)                      SERVER (FastAPI, server/)                 GOOGLE
mic -> Gemini 3.8 Live ------------ tool call plan_quest / replan
          (ephemeral token)                 |
typed box ------------------------> POST /api/plan, /api/replan
                                            |-> director.py -> gemini-4-argon -> quest JSON (schema-checked)
                                            |-> verify.py   -> antigravity-preview-09-2026 sandbox
                                            |                    runs verifier/verify_quest.py -> Places + Routes
                                            |                    (fallback after 20 s: same script locally)
3D map + HUD <-- SSE /api/events <-- one event per step {t, step, status, ms, detail}
```

## Repo layout
```
cityquest/
  CLAUDE.md  AGENTS.md (quirks: symptom, cause, fix)  SETUP.md  DEMO.md  KICKOFF.md
  data/merchants.seed.json      official map units + categories (do not edit by hand)
  data/merchants.json           made by scripts/resolve_places.py (place_id, lat, lng)
  schema/quest.schema.json      Director output contract
  prompts/director.md  prompts/verifier_agent.md  prompts/live_guide.md
  scripts/resolve_places.py
  verifier/verify_quest.py  verifier/test_verify_quest.py   (written and tested offline)
  server/   main.py director.py verify.py live_token.py events.py
  web/      index.html app.js map3d.js hud.js live.js styles.css sprites/
  requirements.txt  Procfile (or Dockerfile)
```
Python 3.11+, FastAPI, `google-genai>=2.3.0`, `httpx`, `jsonschema`. Front end is vanilla JS ES modules with no bundler. One Cloud Run service serves `web/` and `/api`.

## Contracts
**Quest JSON.** `schema/quest.schema.json`. Validate every Director output with `jsonschema`. On failure retry once with the validation error appended; then show the error in the HUD. If the Interactions API structured-output mode rejects `$ref`/`$defs`, inline them in code; keep the file as the source of truth.

**Endpoints.**
- `POST /api/plan {request, minutes?, wants?}` runs Director then verifier, emits SSE steps, returns the final quest.
- `POST /api/replan {quest_id, request, minutes?, wants?, drop?}` same, using `previous_interaction_id`.
- `GET /api/events?quest_id=` SSE step stream for the HUD.
- `POST /api/live-token` returns a single-use ephemeral Live token. Never the API key.
- `GET /api/merchants` for the map legend. `GET /api/quest/{id}` for the QR phone view (P1).

**Director.** System prompt in `prompts/director.md`. Input: now, start/end, the person's words, and `PLACES` (the resolved list with `place_id`, name, unit, category, what, local). Reject any output whose `place_id` is not in `data/merchants.json`.

**Verifier.** `verifier/verify_quest.py` is deterministic, standard library only, tested offline in mock mode. It checks `business_status`, `open_during_visit` (arrival through dwell, from today's `currentOpeningHours.periods`) and `time_budget` (walk + dwell vs `deadline_min`), and returns JSON with `status`, `failing_stop_ids`, a per-stop timeline, per-check latency and the encoded polyline. Exit 0 pass, 1 fail, 2 error. `--check-place PLACE_ID --at ISO --dwell N` checks one candidate.

The managed agent follows `prompts/verifier_agent.md`: write quest.json, candidates.json and the script into its sandbox, run it, swap failing stops only from candidates, rerun, at most 2 rounds, and return the final quest plus a log of each command and exit code. **That log streams into the HUD; it is our Managed Agents prize story.** Fallback: if the agent hasn't answered in 20 s or errors, run the same script locally via subprocess and let Argon pick swaps with `thinking_level` "low". The HUD labels which path ran. Measure sandbox latency at 2:30 PM and write it in AGENTS.md. Reuse the sandbox environment between calls if the API allows it.

**3D map.**
- Center on SHACK15 from merchants.json (fallback 37.7955, -122.3937), tilt about 60, range about 800 m, heading toward the bay.
- One numbered marker per stop with its sprite (emoji fallback). A failing stop pulses red; its replacement drops in green.
- Route: decode `encoded_polyline` (geometry library) into a `Polyline3DElement`; redraw on every verified quest.
- `flyCameraTo` the first stop on a new quest.
- Keep Google attribution visible; don't trace or extract geometry from the tiles.
- If 3D fails to load (key or billing), fall back to a 2D `google.maps.Map` with the same markers so the demo still runs.

**HUD: the real-time proof (P0).** A fixed panel, readable from 3 m:
- wall clock to the second;
- "Quest generated 3:52:07 PM, 12 s ago";
- step timings in ms: transcript, director, places, routes, verify, render;
- a streaming monospace log of real calls, e.g. `15:52:09 places Foodwise Ferry Plaza Farmers Market: opens Tue (closed today)`, `15:52:10 routes WALK 3 stops: 31 min`, `15:52:12 swap farmers market -> Recchiuti Confections`;
- a badge: PASS / FIXED / FAIL, and which verifier path ran.
Nothing in the HUD is mocked or hardcoded. Ever.

## Phases and gates (PDT)
- **1:45 to 2:45** four parallel workstreams, one subagent each, separate files: A map + HUD shell rendering a sample quest built from real merchants.json entries; B Director + schema validation; C verifier wiring (managed agent + local fallback); D Live voice (ephemeral token, tools `plan_quest` and `replan`).
- **2:45 to 3:00** Integration 1: typed prompt -> quest -> verify -> render with a live HUD.
- **3:00 GATE.** If Integration 1 isn't working end to end, stop all new work and fix only the break.
- **3:00 to 3:45** voice replan, fail-then-fix animation, deploy to Cloud Run, phone check over HTTPS.
- **3:45 FEATURE FREEZE.** P1 only if every P0 box below is checked.
- **3:45 to 4:05** record 2 clean full runs as the backup video.
- **4:05 to 4:45** architecture diagram, README, repo public, submission video.
- **4:45 SUBMIT.**

## Done means (P0)
- [ ] Typed prompt returns a verified quest with 2 to 4 stops in under 25 s; every `place_id` is in merchants.json.
- [ ] Across the demo flow the verifier shows at least one real failure and fix, and the HUD log shows the API result behind it.
- [ ] Voice "i only have 15 minutes and want something sweet" replans and re-verifies in under 15 s; the route redraws.
- [ ] HUD clock, timings and log are live.
- [ ] The HTTPS URL works on a phone (mic permission granted, map loads).
- [ ] Backup video recorded.
- [ ] No key in the repo: `git grep -nE "AIza|AQ\." || echo clean` before it goes public.

## When something breaks
Write one line in AGENTS.md (symptom, cause, fix). Ask Rakesh before spending money beyond Gemini and Maps calls, changing the demo flow, or cutting a P0 item.
