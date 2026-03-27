#!/usr/bin/env bash
set -euo pipefail
trap 'exit 0' ERR

# Debug logging — set NEUROLOOM_DEBUG=true to enable
DEBUG="${NEUROLOOM_DEBUG:-false}"
debug_log() { [[ "$DEBUG" == "true" ]] && echo "[neuroloom-sdlc] $*" >&2 || true; }

# Dependency check — silent exit if required tools absent
command -v jq >/dev/null 2>&1 || exit 0
command -v curl >/dev/null 2>&1 || exit 0

# Read tool event from stdin
TOOL_EVENT=$(cat)

# Extract file_path from tool_input
FILE_PATH=$(echo "$TOOL_EVENT" | jq -r '.tool_input.path // .tool_input.file_path // empty' 2>/dev/null)
[[ -n "$FILE_PATH" ]] || exit 0

debug_log "PostToolUse triggered for: ${FILE_PATH}"

# Fast exit for non-matching paths (<100ms budget)
# Only process docs/current_work/**/*.md
# Match both absolute paths (/repo/docs/current_work/...) and relative paths (docs/current_work/...)
if [[ ! "$FILE_PATH" =~ docs/current_work/.*\.md$ ]]; then
  debug_log "Path does not match docs/current_work/**/*.md — skipping"
  exit 0
fi

debug_log "Path matched SDLC deliverable pattern"

# Read config from ~/.neuroloom/config.json
CONFIG_FILE="${HOME}/.neuroloom/config.json"
[[ -f "$CONFIG_FILE" ]] || exit 0

API_TOKEN=$(jq -r '.api_key // empty' "$CONFIG_FILE" 2>/dev/null)
API_URL=$(jq -r '.api_url // empty' "$CONFIG_FILE" 2>/dev/null)
[[ -n "$API_TOKEN" && -n "$API_URL" ]] || exit 0

# Read file content
[[ -f "$FILE_PATH" ]] || exit 0
FILE_CONTENT=$(cat "$FILE_PATH" 2>/dev/null)
[[ -n "$FILE_CONTENT" ]] || exit 0

# Extract deliverable ID from filename: d(\d+[a-z]?)_
FILENAME=$(basename "$FILE_PATH")
DELIVERABLE_ID=""
if [[ "$FILENAME" =~ ^d([0-9]+[a-z]?)_ ]]; then
  DELIVERABLE_ID="${BASH_REMATCH[1]}"
fi

# Derive doc type from filename suffix
DOC_TYPE=""
if [[ "$FILENAME" =~ _spec\.md$ ]]; then
  DOC_TYPE="spec"
elif [[ "$FILENAME" =~ _plan\.md$ ]]; then
  DOC_TYPE="plan"
elif [[ "$FILENAME" =~ _result\.md$ ]]; then
  DOC_TYPE="result"
elif [[ "$FILENAME" =~ _COMPLETE\.md$ ]]; then
  DOC_TYPE="chronicle"
fi

debug_log "Deliverable ID: ${DELIVERABLE_ID:-<none>}, Doc type: ${DOC_TYPE:-<none>}"

# Build tags array
TAGS_JSON="[]"
if [[ -n "$DELIVERABLE_ID" ]]; then
  TAGS_JSON=$(jq -n --arg id "sdlc:deliverable:${DELIVERABLE_ID}" '[$id]')
fi
if [[ -n "$DOC_TYPE" ]]; then
  TAGS_JSON=$(echo "$TAGS_JSON" | jq --arg t "sdlc:doc:${DOC_TYPE}" '. + [$t]')
fi

# Build ingest payload using jq (no shell interpolation into JSON strings)
# NOTE: content_hash is NOT sent — server computes it
PAYLOAD=$(jq -n \
  --arg title "$FILENAME" \
  --arg content "$FILE_CONTENT" \
  --arg source_path "$FILE_PATH" \
  --argjson tags "$TAGS_JSON" \
  '{
    title: $title,
    content: $content,
    source_type: "sdlc_deliverable",
    source_path: $source_path,
    tags: $tags
  }')

BUFFER_FILE="${HOME}/.neuroloom/sdlc-sync-buffer.json"

# Fire-and-forget sync — background subshell with reset trap
(
  trap - ERR  # Reset trap in subshell so failures don't bubble
  debug_log "Syncing ${FILE_PATH} to Neuroloom..."

  HTTP_STATUS=$(curl -s -o /tmp/nl_ingest_response_$$.json -w "%{http_code}" \
    -X POST "${API_URL}/api/v1/documents/ingest" \
    -H "Authorization: Token ${API_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" \
    --connect-timeout 5 --max-time 15 2>/dev/null) || {
      # Network error — buffer payload for retry
      echo "$PAYLOAD" >> "$BUFFER_FILE"
      exit 0
    }

  if [[ "$HTTP_STATUS" =~ ^2 ]]; then
    debug_log "Sync successful for ${FILE_PATH}"
  else
    debug_log "Sync failed (HTTP ${HTTP_STATUS}) for ${FILE_PATH} — buffering"
    echo "$PAYLOAD" >> "$BUFFER_FILE"
  fi

  rm -f "/tmp/nl_ingest_response_$$.json"
) &
disown
