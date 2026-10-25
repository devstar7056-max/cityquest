# Paste this into Claude Code as your first message

```
Read CLAUDE.md fully, then SETUP.md, DEMO.md, schema/quest.schema.json, the three files in prompts/, and verifier/verify_quest.py. We're building CityQuest for the Gemini 4 Argon hackathon. Hard deadline 5:00 PM PDT; run `date` now and plan against it.

Before writing app code:
1. Confirm the Gemini skills gemini-api-dev and gemini-live-api-dev are installed; if not, run SETUP.md step 4. Read them and use them for every Gemini call shape (Interactions API, Live ephemeral tokens, Managed Agents, Credentials API).
2. Check env vars without printing values:
   for v in GEMINI_API_KEY MAPS_SERVER_KEY MAPS_BROWSER_KEY; do [ -n "$(printenv $v)" ] && echo "$v set" || echo "$v MISSING"; done
3. Run python3 verifier/test_verify_quest.py (offline), then python3 scripts/resolve_places.py (live). Show me only the places marked "check" or "error".
4. Make one real gemini-4-argon call with thinking_level "low" and one with "medium" on a short planning prompt; report both latencies.
5. Ask me at most 3 questions in one message, only ones that change what you build. If I don't answer within 2 minutes, take the reading in CLAUDE.md and go.

Then build with four parallel subagents, one per workstream in CLAUDE.md (A map + HUD, B Director, C verifier wiring, D Live voice), each owning its own files so they don't collide. CLAUDE.md's "Rules that do not bend" apply to every subagent: never print or write a key, never invent a place, never fake a verifier result.

Integration 1 is due by 2:45 PM: typed prompt -> quest -> verify -> render with a live HUD. Tell me the moment it works, with measured timings for each step. After each workstream lands, run it, measure it, and write any quirk into AGENTS.md (symptom, cause, fix). Respect the 3:00 PM gate and the 3:45 PM feature freeze.
```
