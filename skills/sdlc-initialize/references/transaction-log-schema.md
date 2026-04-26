# Transaction Log — Schema and Recovery Diagnostics

Every stage start/end, gate decision, and failure writes an append-only JSONL entry to `.sdlc-transaction-log` in the project root. This enables recovery diagnostics — if a session crashes mid-migration, the next session can read the log to understand what completed and what didn't.

## Log location and lifecycle

- **Path:** `.sdlc-transaction-log` (project root, gitignored by default)
- **Format:** JSONL — one JSON object per line, newline-terminated, append-only
- **Rotation:** On each new init/migrate run, append a `"run_start"` marker. Logs are not truncated — they accumulate history across all runs.
- **Gitignore:** Ensure `.sdlc-transaction-log` is added to `.gitignore` during Stage 5b (alongside `.claude/agent-memory/`).

## Entry schema

```json
{"ts": "2026-04-21T18:30:00Z", "run_id": "init-abc123", "skill": "sdlc-initialize", "event": "stage_start", "stage": "0", "details": {"stage_name": "Pre-Flight Health Check"}}
{"ts": "2026-04-21T18:30:02Z", "run_id": "init-abc123", "skill": "sdlc-initialize", "event": "check", "check": "neuroloom_api", "result": "pass", "details": {"workspace_id": "..."}}
{"ts": "2026-04-21T18:30:05Z", "run_id": "init-abc123", "skill": "sdlc-initialize", "event": "stage_end", "stage": "0", "details": {"duration_ms": 5230, "result": "pass"}}
{"ts": "2026-04-21T18:31:00Z", "run_id": "init-abc123", "skill": "sdlc-initialize", "event": "gate", "stage": "4", "gate": "confirmation", "result": "approved"}
{"ts": "2026-04-21T18:32:15Z", "run_id": "init-abc123", "skill": "sdlc-initialize", "event": "mutation", "stage": "5a", "details": {"type": "batch_ingest", "entries": 127, "batch": 1}}
{"ts": "2026-04-21T18:35:42Z", "run_id": "init-abc123", "skill": "sdlc-initialize", "event": "failure", "stage": "6b", "details": {"agent": "backend-engineer", "error": "sdlc-create-agent returned non-zero"}}
{"ts": "2026-04-21T18:40:00Z", "run_id": "init-abc123", "skill": "sdlc-initialize", "event": "run_end", "details": {"result": "success", "duration_ms": 600000}}
```

## Required event types

| `event` | When to log | Required `details` |
|---------|-------------|---------------------|
| `run_start` | First action after preflight passes | `skill`, `run_id`, `invocation_args` |
| `stage_start` | Entering a stage | `stage`, `stage_name` |
| `stage_end` | Exiting a stage | `stage`, `duration_ms`, `result` (`pass`/`fail`) |
| `check` | Individual pre-flight or verification check | `check`, `result`, optional details |
| `gate` | User confirmation or hard-fail gate | `stage`, `gate` (name), `result` (`approved`/`rejected`/`cancelled`) |
| `mutation` | Any action that changes state (batch ingest, file write, manifest update) | `stage`, `type`, scope details |
| `warning` | Non-fatal issue (e.g., TRANSFORMATION_WARNING) | `stage`, `category`, `message`, `location` |
| `failure` | Any error condition | `stage`, `error`, remediation hints |
| `run_end` | Final exit | `result` (`success`/`failure`/`cancelled`), `duration_ms` |

## Run ID generation

`run_id = "{skill-shortname}-{6-char-random-hex}"` — e.g., `init-abc123`, `migrate-def456`. Consistent run_id lets future diagnostics filter all events from a single invocation.

## Reading the log for recovery

If a session ended abnormally:

```
tail -n 50 .sdlc-transaction-log | jq -c '.'
# Look for: last stage_start without matching stage_end = where it crashed
# Last mutation event = what was last committed
# Last gate event = whether the run was past point-of-no-return
```
