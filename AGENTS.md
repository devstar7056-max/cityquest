# AGENTS.md: quirks we hit today

One line each: symptom, cause, fix. Newest at the bottom.

- Measured latencies (fill in): gemini-4-argon low = 5.00 s, medium = 4.43 s (2:13 PM, one short planning prompt each, Interactions API, `generation_config={"thinking_level": ...}`); managed agent verify = ? s; local verify = ? s.
- Default `python3` on this Mac is Anaconda 3.7, too old for google-genai 2.x. Use `.venv/bin/python` (built from /usr/local/bin/python3.13).
- gcloud default account (lab account from an earlier event) returns `invalid_grant: Account has been deleted`. Maps keys need `gcloud auth login` with Rakesh's own account, or the console.
- `npx skills add google-gemini/gemini-skills` was blocked by the Claude Code auto-mode classifier. Read the skills as docs from GitHub instead (gemini-api-dev, gemini-live-api-dev).
- Argon returns JSON wrapped in a ```json fence when no response schema is set. Use structured output, or strip fences before `json.loads`.
- Antigravity sandbox latency (2:24 PM): cold 19.7 s, warm (same environment_id) 18.5 s for one `echo`; each extra command adds about 5 to 7 s of agent thinking. Too slow for the 25 s / 15 s targets, so the managed agent runs in parallel as a second, independent proof: the local verifier drives the map, and the agent's real commands stream into the HUD as `agent` lines with its own verdict.
- Agent streaming: `step.start` events carry the whole `code_execution_call` (arguments.code) and `code_execution_result` (result with [STDOUT]/[STDERR]), so commands can be shown live without waiting for the end.
- Agent files: use environment `sources` of type `inline` (1 MB per file) for verify_quest.py, quest.json and candidates.json instead of making the agent write a 13 KB script (slow output tokens). Sources only apply to a new environment, so each audit uses a fresh sandbox; cold vs warm cost is about the same.
- Agent Maps auth: `client.credentials.create(type="bearer_token", header_name="x-goog-api-key", prefix="")`; the default is `Authorization: Bearer`, which Maps rejects.
- Director with the full PLACES list: low 11.4 s, medium 14.6 s, replan (low, previous_interaction_id) 10.9 s. Kept low for every turn.
- Port 8000 on this Mac is taken by another project (Steelos). CityQuest runs on 8010 locally; add `http://localhost:8010/*` to the browser key.
- Deep Research (deep-research-preview-04-2026) took 704 s for 42 merchants; 41 came back with a source URL. Some "what" lines are non-answers ("Details ... unavailable"); director._lore() drops those and only fills fields the official seed left null.
- Nano Banana 2.1 returns 16:9 images even for icons; crop to a centered square with `sips -c` before using them as pin glyphs. One of 15 calls failed with a transient TLS decode error; rerunning `gen_assets.py sprites` only redoes missing files.
- Map showed "Oops! Something went wrong" with RefererNotAllowedMapError: `gcloud services api-keys create` with repeated `--allowed-referrers` keeps only the last one. Pass one comma-separated list (fixed in scripts/setup_maps.sh). Key restriction changes take a minute or more to apply. `*.run.app` is allowed for now; narrow it to our URL after deploy.
- Maps APIs need the Maps Platform terms accepted once per project in the console (FAILED_PRECONDITION UREQ_TOS_NOT_ACCEPTED); only the account owner can click accept.
- The Frenchy Gourmet has no Google Places listing (three queries tried); it stays "check" and the Director never sees it. The clock tower resolves to the Ferry Building (same structure) and is accepted explicitly.
- Integration 1 (2:37 PM, typed, local verifier): 13.3 s end to end. route 1.5 s (flash-lite), director 10.8 s, places 114 ms, routes 191 ms, verify 0.95 s. Real fail-then-fix: Argon planned 4 stops, Routes said 46 of 45 min, verifier dropped Pier 14, rerun passed at 27 min.
- Replan "15 minutes, something sweet" (typed): 11.0 s end to end (director 9.1 s, verify 0.5 s). Managed agent sandbox reached Places/Routes through the credential proxy and independently found the same over-budget failure.
- 3D PinElement with glyphSrc (our PNG sprites) renders a black square on Marker3DElement; switched pins to numbered glyphText and kept sprites in the quest card.
- `genai.Client().interactions.create(...)` with an unreferenced client fails mid-request with "Cannot send a request, as the client has been closed". Keep the client in a variable (server uses one shared client).
- Live scan (3:02 PM): Places details for 45 places in parallel in 379 to 476 ms; 37 open on a Sunday afternoon. Fields used: currentOpeningHours.openNow, servesCoffee, servesBreakfast, servesDessert, priceRange, priceLevel. Missing fields stay null (unknown). Cost = sum of each stop's priceRange (a range, never menu prices).
- gemini-3.8-live recognized the Ferry Building from a single frame of Google Photorealistic 3D Tiles (it called plan_quest with seen "San Francisco Ferry Building") and answered the I/O hackathon question through the past_hackathons tool (data/io_gallery.json, 152 projects, award field).
- gemini-3.8-flash-tts reads style instructions aloud if they are in the input ("Say casually: ..."); pass only the words.
- Cerebral Valley gallery: winners are in the page's schema.org ListItem objects (`award` field). The Next.js flight chunks must be JSON-decoded one by one; joined, they break escapes. Breadcrumb ListItems have a string `item`.
- Three.js + Google tiles: 3d-tiles-renderer@0.4.6 (raw ES modules via an import map: three@0.170.0 plus three/ and three/addons/) with GoogleCloudAuthPlugin, GLTFExtensionsPlugin (DRACO from gstatic), ReorientationPlugin({lat, lon in radians, height: -29, up: '+y'}). Convert lat/lng with tiles.ellipsoid.getCartographicToPosition then group.matrixWorld after load-tile-set.
- Headset view: stacking two radial gradients on one overlay element leaves only their overlap visible (it looked like the eyes showed different images). Use one gradient per lens element. The right lens mirrors the WebGL canvas with a 2D drawImage in the same frame.
- Sprite labels in a city-scale scene: use sizeAttenuation: false or they become huge when the camera flies close.
