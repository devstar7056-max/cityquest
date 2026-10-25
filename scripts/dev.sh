#!/usr/bin/env bash
# Run CityQuest locally on :8010 with keys read from the macOS Keychain (never from files).
set -euo pipefail
cd "$(dirname "$0")/.."
kc() { security find-generic-password -a "$USER" -s "$1" -w 2>/dev/null || true; }
export GEMINI_API_KEY="${GEMINI_API_KEY:-$(kc cityquest-gemini)}"
export MAPS_SERVER_KEY="${MAPS_SERVER_KEY:-$(kc cityquest-maps-server)}"
export MAPS_BROWSER_KEY="${MAPS_BROWSER_KEY:-$(kc cityquest-maps-browser)}"
for v in GEMINI_API_KEY MAPS_SERVER_KEY MAPS_BROWSER_KEY; do [ -n "${!v}" ] && echo "$v set" || echo "$v MISSING"; done
exec .venv/bin/python -m uvicorn server.main:app --host 0.0.0.0 --port "${PORT:-8010}" --log-level warning
