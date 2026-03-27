#!/usr/bin/env bash
set -euo pipefail
trap 'exit 0' ERR

# Debug logging — set NEUROLOOM_DEBUG=true to enable
DEBUG="${NEUROLOOM_DEBUG:-false}"
debug_log() { [[ "$DEBUG" == "true" ]] && echo "[neuroloom-sdlc] $*" >&2 || true; }

# Dependency check — silent exit if required tools absent
command -v jq >/dev/null 2>&1 || exit 0
command -v curl >/dev/null 2>&1 || exit 0

# Read config from ~/.neuroloom/config.json
CONFIG_FILE="${HOME}/.neuroloom/config.json"
[[ -f "$CONFIG_FILE" ]] || exit 0

API_TOKEN=$(jq -r '.api_key // empty' "$CONFIG_FILE" 2>/dev/null)
API_URL=$(jq -r '.api_url // empty' "$CONFIG_FILE" 2>/dev/null)
[[ -n "$API_TOKEN" && -n "$API_URL" ]] || exit 0

debug_log "Config loaded. API_URL=${API_URL}"

# Temp file paths
VERSION_TMP="/tmp/nl_version_response_$$.json"
SENTINEL_TMP="/tmp/nl_sentinel_response_$$.json"

# Step 1: Get latest cc-sdlc version via Neuroloom version proxy
# NOTE: We call the Neuroloom version proxy, NOT GitHub directly.
debug_log "Checking cc-sdlc version via proxy..."
HTTP_STATUS=$(curl -s -o "$VERSION_TMP" -w "%{http_code}" \
  "${API_URL}/api/v1/sdlc/cc-sdlc-version" \
  -H "Authorization: Token ${API_TOKEN}" \
  --connect-timeout 5 --max-time 10 2>/dev/null) || exit 0

if [[ "$HTTP_STATUS" != "200" ]]; then
  debug_log "Version proxy returned ${HTTP_STATUS}, skipping"
  rm -f "$VERSION_TMP"
  exit 0
fi

LATEST_VERSION=$(jq -r '.version // empty' "$VERSION_TMP" 2>/dev/null)
[[ -n "$LATEST_VERSION" ]] || { rm -f "$VERSION_TMP"; exit 0; }

debug_log "Latest cc-sdlc version: ${LATEST_VERSION}"

# Step 2: Search for sentinel memory to determine workspace initialization state
debug_log "Checking for workspace sentinel..."
SENTINEL_STATUS=$(curl -s -o "$SENTINEL_TMP" -w "%{http_code}" \
  -X POST "${API_URL}/api/v1/memories/search" \
  -H "Authorization: Token ${API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"tags": ["sdlc:sentinel"], "limit": 1}' \
  --connect-timeout 5 --max-time 10 2>/dev/null) || exit 0

if [[ "$SENTINEL_STATUS" != "200" ]]; then
  debug_log "Sentinel search returned ${SENTINEL_STATUS}, skipping"
  rm -f "$VERSION_TMP" "$SENTINEL_TMP"
  exit 0
fi

# Step 3: If no sentinel, prompt initialization
SENTINEL_COUNT=$(jq -r '.results | length // 0' "$SENTINEL_TMP" 2>/dev/null)
if [[ "$SENTINEL_COUNT" == "0" || "$SENTINEL_COUNT" == "null" ]]; then
  echo "Neuroloom SDLC: workspace not initialized. Run /sdlc-initialize to seed SDLC knowledge."
  rm -f "$VERSION_TMP" "$SENTINEL_TMP"
  exit 0
fi

# Step 4: Extract workspace version from sentinel tags (sdlc:seed-version:{version})
WORKSPACE_VERSION=$(jq -r '.results[0].tags[]? | select(startswith("sdlc:seed-version:")) | ltrimstr("sdlc:seed-version:")' "$SENTINEL_TMP" 2>/dev/null)

debug_log "Workspace version: ${WORKSPACE_VERSION:-<none>}"

# Step 5: Compare versions — notify if update available
if [[ -n "$WORKSPACE_VERSION" && "$WORKSPACE_VERSION" != "$LATEST_VERSION" ]]; then
  echo "Neuroloom SDLC: update available (${WORKSPACE_VERSION} -> ${LATEST_VERSION}). Run /sdlc-migrate to update."
fi

# Cleanup temp files
rm -f "$VERSION_TMP" "$SENTINEL_TMP"
