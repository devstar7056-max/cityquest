#!/usr/bin/env bash
# Enable the four Maps APIs and create the two restricted keys, storing them in the macOS Keychain.
# Never prints a key. Usage: scripts/setup_maps.sh PROJECT_ID [https://your-app.run.app]
set -euo pipefail
P="${1:?project id}"
RUN_URL="${2:-}"
gcloud services enable apikeys.googleapis.com maps-backend.googleapis.com tile.googleapis.com \
  places.googleapis.com routes.googleapis.com --project "$P"

# One comma-separated list: repeating --allowed-referrers keeps only the last value.
ref_list="http://localhost:8010/*,http://127.0.0.1:8010/*,http://localhost:8000/*,https://*.trycloudflare.com/*,https://*.run.app/*"
[ -n "$RUN_URL" ] && ref_list="$ref_list,${RUN_URL%/}/*"
refs=(--allowed-referrers="$ref_list")

mk() { # display-name keychain-service extra-args...
  local name="$1" svc="$2"; shift 2
  local id
  id=$(gcloud services api-keys create --project "$P" --display-name "$name" "$@" \
        --format="value(response.uid)" 2>/dev/null | tail -1)
  [ -n "$id" ] || id=$(gcloud services api-keys list --project "$P" --filter="displayName=$name" --format="value(uid)" | head -1)
  security add-generic-password -U -a "$USER" -s "$svc" \
    -w "$(gcloud services api-keys get-key-string "$id" --project "$P" --format='value(keyString)')"
  local k; k="$(security find-generic-password -a "$USER" -s "$svc" -w)"
  echo "$name -> Keychain $svc (length ${#k})"
}

mk cityquest-browser cityquest-maps-browser \
  --api-target=service=maps-backend.googleapis.com --api-target=service=tile.googleapis.com "${refs[@]}"
mk cityquest-server cityquest-maps-server \
  --api-target=service=places.googleapis.com --api-target=service=routes.googleapis.com
