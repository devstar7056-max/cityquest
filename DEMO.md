# Demo (3 minutes), pitch and submission video

## Two minutes before your slot
- Laptop on power; phone hotspot ready in case the venue network dies.
- Run one warm-up quest so map tiles and the sandbox are warm.
- Backup video open in a second tab, paused at 0:00.
- HUD font big enough to read from the back row.
- Test the mic and one interruption.

## The 3 minutes
**0:00 to 0:20, pitch.** "Maps tell you where to go. Games give you a reason to explore. CityQuest turns your next hour into a quest, and every collectible is a real place that's open right now. We're standing in it: the Ferry Building."

**0:20 to 1:10, hero run (you speak).** "i've got 45 minutes before my next session. i want good coffee, something uniquely San Francisco, and to be back on time."
Point at: the 3D Ferry Building, the log streaming real calls, a stop turning red when the verifier rejects it and the green swap. Then: "That stop failed on today's real hours. Nobody scripted that."
Note: the Ferry Plaza Farmers Market usually runs on weekdays and Saturday, so Places will likely report it closed today; if Argon picks it, that's your real failure. Don't force it.

**1:10 to 2:00, the judge drives.** Hand over the mic: "Change the plan. Anything you want." If they freeze: "Try: i only have 15 minutes and i want something sweet." Point at the route redraw, the re-check and the latency in the HUD.

**2:00 to 2:30, control and proof.** "It never books, buys or messages anyone; every link is a tap you make." P1: show the QR so they open the quest on their own phone.

**2:30 to 3:00, why Argon.** "Argon plans the world as structured data. A managed agent proves it's true by running real code against live Google data. Gemini Live lets you change your mind mid-sentence." End on the architecture diagram.

## If something breaks
"The venue network is slow; here's the run from 4 PM." Play the backup. Don't debug on stage.

## Questions judges may ask
- **"Is this canned?"** Ask them for any constraint, or open the HUD log and show today's date and times in the API results.
- **"Why Argon?"** The Director plans under time, hours and theme constraints and replans as a delta with previous_interaction_id; Flash does the parallel leaf work.
- **"What did the managed agent do?"** Show its command log: it ran the verifier, read the failure, checked a candidate, swapped it in and reran until it passed.
- **"Who is this for?"** Name a real person and say only what's true: you this morning, a teammate, a friend visiting SF.

## 30-second pitch (fill the first line with something true)
"[True moment, e.g. This morning i had an hour between doors and kickoff and no idea where to go.] CityQuest turns your next hour into a quest. Tell it your time and what you're craving, and Gemini 4 Argon builds a game where every stop is a real merchant in the Ferry Building. A managed agent checks today's hours and walking times by running real code, fixes what's wrong, and replans the moment you change your mind. Maps tell you where to go. Games give you a reason to explore. Change your plans, and the world changes with you."

## Submission video: 60 to 75 s, one person, 4:05 to 4:45 PM
1. **0 to 6 s:** title over real b-roll you shoot on your phone now (clock tower, the market hall, the bay). Real footage of a real building beats a generated one.
2. **6 to 12 s:** one Higgsfield transition made from your own photo of the market hall (image-to-video). Prompt: "Slow push-in down the arched market hall; the floor tiles light up into a glowing game path; small floating icons, a coffee cup, an ice cream cone and a book, rise above three shopfronts; warm afternoon light; smooth camera; no text; 6 seconds." Use Gemini Omni Flash if Higgsfield lists it, otherwise Kling 3.0. Expect about 10 to 20 credits; read the cost shown and say "y" before it runs.
3. **12 to 50 s:** the screen recording of the backup run, with the real HUD visible.
4. **50 to 60 s:** Argon's architecture diagram and the closing line.

Narration: your own voice. The room is loud, so clean the take with ElevenLabs Voice Isolator; no cloned voice needed. Music: one 30 s Lyria loop (`lyria-3-clip-preview`) keeps the soundtrack Google-made. Cut it in CapCut or iMovie; export H.264 1080p.

## Judging plan (rubric-mapped, measured numbers only)

**One line:** CityQuest turns the street you are standing on into a live, verified game: it sees where you are, checks what is actually open right now, and proves the plan before you take a step.

| Time | Beat | Rubric |
|---|---|---|
| 0:00 to 0:15 | Lens POV of Rakesh jogging to the Ferry Building: "20 minutes, a coffee and a croissant, no idea what is open." | Clarity, Problem |
| 0:15 to 1:10 | Phone, real inputs: GPS plus camera plus voice. Laptop /sim in headset mode: live area scan (about 40 places in about 0.5 s), building breaks open with stalls at real positions, Argon plans, verifier fixes if a check fails, route, estimated cost from Google price ranges, the guide speaks. | Live demo (50%) |
| 1:10 to 1:50 | Judge names any street. The sim flies there and scans, plans and verifies live. Nothing is precomputed. | Live demo (50%) |
| 1:50 to 2:20 | HUD `agent` lines: Antigravity managed agent runs verify_quest.py in a Google sandbox against live Places and Routes (key injected by the credential proxy) and reaches its own verdict. | Live demo, Managed Agents |
| 2:20 to 2:40 | City Memory: one gemini-4-argon context holds 2,088 live places with their Google reviews (565,115 input tokens, API-reported). It reviews every quest in parallel and answers "best croissant in the whole city". | Originality (15%) |
| 2:40 to 3:00 | What it becomes: an open-source "verified next hour" engine for conference organizers, tourism boards and city guides. Architecture page. | Problem (25%), Clarity |

Honest claims: more than half of the 1M window is used by City Memory (565K tokens); prices are Google price ranges, never menu prices; the sim is Google Photorealistic 3D Tiles, the interior is our floor plan of real place positions with an illustrative stall model; the jog footage is real.

Fallbacks: phone hotspot; typed box if Live voice fails; the agent and City Memory run in parallel so nobody waits on them; backup recording.
