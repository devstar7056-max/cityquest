# Setup: 15 minutes, do it in this order

## 1. Unzip and open
```sh
mkdir -p ~/Projects && cd ~/Projects
unzip ~/Downloads/cityquest-kit.zip && cd cityquest
git init
```

## 2. Keys live in your terminal, never in a file
Type each one in; nothing echoes. Then launch Claude Code from this same terminal window so it inherits them.
```sh
read -s GEMINI_API_KEY && export GEMINI_API_KEY      # paste, press Enter
read -s MAPS_SERVER_KEY && export MAPS_SERVER_KEY    # after step 3
read -s MAPS_BROWSER_KEY && export MAPS_BROWSER_KEY  # after step 3
```
If your Gemini key came from the organizers' provisioned AI Studio account, it covers the Gemini API only. Maps needs keys from your own Cloud project (step 3).

## 3. Google Maps Platform (10 minutes, needs billing)
1. console.cloud.google.com, new project `cityquest-argon`, link a billing account.
2. Enable four APIs (console, or gcloud):
   ```sh
   gcloud config set project YOUR_PROJECT_ID
   gcloud services enable maps-backend.googleapis.com tile.googleapis.com places.googleapis.com routes.googleapis.com
   ```
   (Maps JavaScript API, Map Tiles API, Places API (New), Routes API.)
3. APIs & Services, Credentials, create two API keys:
   - **MAPS_BROWSER_KEY**: restrict to Maps JavaScript API + Map Tiles API; website restrictions `http://localhost:8000/*` and, after deploy, your `https://...run.app/*` URL.
   - **MAPS_SERVER_KEY**: restrict to Places API (New) + Routes API. Used only by the server and the verifier.
4. Export both (step 2).

## 4. Gemini skills for Claude Code (from the builder guide)
```sh
npx skills add google-gemini/gemini-skills --skill gemini-api-dev
npx skills add google-gemini/gemini-skills --skill gemini-live-api-dev
```

## 5. Python environment and the two scripts already written
```sh
python3 -m venv .venv && source .venv/bin/activate
pip install "google-genai>=2.3.0" fastapi "uvicorn[standard]" httpx jsonschema
python3 verifier/test_verify_quest.py     # offline, should print OK
python3 scripts/resolve_places.py         # live; writes data/merchants.json
```
Look at any line marked `check`: Google matched a different name or a place too far from the Ferry Building. Fix its `query` in merchants.seed.json and rerun.

## 6. Higgsfield and ElevenLabs inside Claude Code (for the video, not the app)
```sh
claude mcp add --transport http higgsfield https://mcp.higgsfield.ai/mcp
claude mcp add --transport http elevenlabs https://api.elevenlabs.io/v1/mcp
```
Start `claude`, type `/mcp`, sign in to both (OAuth; no keys in files). If either URL fails, Higgsfield is already connected in your claude.ai account and you can run the video steps there.

## 7. Start building
```sh
claude
```
Paste the block in KICKOFF.md.

## 8. Deploy over HTTPS by 3:30 PM
Phones only allow the mic on HTTPS.
```sh
gcloud run deploy cityquest --source . --region us-west1 --allow-unauthenticated \
  --set-env-vars GEMINI_API_KEY="$GEMINI_API_KEY",MAPS_SERVER_KEY="$MAPS_SERVER_KEY",MAPS_BROWSER_KEY="$MAPS_BROWSER_KEY"
```
Say yes when gcloud offers to enable Cloud Run, Cloud Build and Artifact Registry. Add the printed `run.app` URL to the browser key's website restrictions.
No gcloud on this Mac, or the deploy stalls? Quick tunnel instead (no account): `brew install cloudflared && cloudflared tunnel --url http://localhost:8000`, then add the `trycloudflare.com` URL to the browser key.

## 9. Before the repo goes public
```sh
git grep -nE "AIza|AQ\." || echo clean
```
After the event, rotate every key you pasted anywhere (including chat).
