# Error Handling and Recovery

## Recovery principles

1. **Knowledge-layer failures don't block operational-layer progress** unless more than 10% of entries errored. The operational layer is independent; filesystem writes can proceed even with partial knowledge seed.
2. **Operational-layer failures are recoverable in-place.** If a filesystem write fails, retry the specific write — do not restart the whole stage.
3. **Never half-commit the sentinel.** The sentinel is the single point of truth for initialization state. If ingestion completes but the sentinel isn't readable server-side, init is not complete — and re-running `/sdlc-initialize` (not `/sdlc-migrate`) is the right recovery path.
4. **Preserve partial progress on cancellation.** If CD cancels mid-stage, do not roll back already-completed writes. Report the partial state and tell CD which stage to resume from.

## Failure modes

| Failure Mode | Detection | Response | Recovery |
|-------------|-----------|---------|----------|
| Neuroloom API unreachable | `sdlc_get_version` fails with network error | Output actionable config error. Do not proceed. | Fix network/config, re-run from Stage 0. |
| Neuroloom auth invalid | `sdlc_get_version` fails with 401 | Output API key setup instructions. Do not proceed. | Re-configure key via `/plugins configure neuroloom`, re-run. |
| Auth token expires mid-session | Any subsequent MCP call returns 401 | Stop at current stage, report which stage and how many entries completed. | Re-configure key, resume from the failed stage (Stage 5 Knowledge seed resumes idempotently via `knowledge_id`). |
| GitHub rate limit hit | 403 + `X-RateLimit-Remaining: 0` | Stop, report reset time, suggest `gh auth login`. | Wait until reset or authenticate `gh`, re-run from Stage 2 fetch. |
| Individual file fetch fails | Non-200 from file content endpoint | Log failure, continue. Report count at Stage 2 completion. | No action if <20%. If stopped, re-run from Stage 2. |
| >20% files failed to download | Count check at Stage 2 completion | Stop, ask CD whether to proceed with partial content. | CD decides: partial proceed (knowledge gaps documented) or full retry. |
| `document_ingest_batch` partial error | `summary.errors > 0` | Log each errored entry with title + error message. Continue if <10% failed. | Re-run failed entries only via a follow-up `document_ingest_batch` with just those `knowledge_id`s. `knowledge_id` upsert makes this idempotent. |
| `document_ingest_batch` network interruption mid-batch | Call times out or returns partial response | Assume batch state is indeterminate. Re-issue the batch — `knowledge_id` upsert makes it safe. | Automatic retry (once). If retry fails, log + continue with next batch. |
| >10% batch entries errored | Count check after all batches | Stop, ask CD whether to continue with operational file writes. | CD decides: proceed with degraded knowledge layer or abort + re-run. |
| Sentinel not present after seeding | `memory_search` returns empty post-ingest | Retry after 2s (server may still be processing). If still missing, report to CD — sentinel is server-managed. | Check Neuroloom workspace config; may indicate an API-side issue. Do not create sentinel manually. |
| Sentinel present but version tag stale | `sdlc:seed-version:` tag doesn't match `LATEST_VERSION` | Wait 5s and re-read. Server may still be processing the tag update. | If still stale after 3 retries, report as `INIT_INCOMPLETE` — re-run `/sdlc-initialize`. |
| Agent creation fails in Stage 6 | `/sdlc-create-agent` returns error | Report failure, offer to retry or skip that agent. Do not hand-write the agent file. | Retry the specific agent creation. If repeat failures, check `/sdlc-create-agent` skill logs. |
| Mandatory agent missing after Stage 6 | Stage 10a check: `software-architect` or `code-reviewer` not in `.claude/agents/` | Stop. Re-dispatch `/sdlc-create-agent` for the missing agent. Do not proceed to Stage 10b. | Fix roster, re-run Stage 6b, re-run Stage 10a verification. |
| Filesystem write fails | `Write` tool returns error (permission, disk full) | Report path + error. Offer retry. | Fix underlying issue (permissions, space), retry the specific write. |
| Transformation phrase not matched | During install-time transformation, a file contains a standard-phrase-adjacent pattern that doesn't match any rule | Log as `TRANSFORMATION_WARNING` with file + line. Continue — the file may have already been transformed or use a variant phrasing. | Post-init: review the `TRANSFORMATION_WARNING` log, update plugin's Pattern Mapping table if a new phrase needs coverage. |
| Compliance audit finds CRITICAL | Stage 10b auditor returns CRITICAL findings | Fix before declaring complete. Do not output final success report until all CRITICALs resolved. | Address findings (typically roster/wiring gaps), re-run audit. |

## Recovery / Emergency Restore

If `/sdlc-initialize` crashes, is interrupted, or leaves the workspace in a visibly bad state, this section is how to diagnose and recover.

### Step 1: Diagnose — what state are we in?

Check these four sources of truth, in order:

**1. Transaction log** (most specific):
```bash
tail -n 100 .sdlc-transaction-log | jq -c '.'
# Find the last `run_start` for sdlc-initialize
# Walk forward: what stages completed (stage_end + result)?
# Where did it stop (last event)? Before or after the point_of_no_return checkpoint?
```

**2. Sentinel** (knowledge-layer truth):
```
memory_search(query="SDLC workspace sentinel", tags=["sdlc:sentinel"])
```
- Returns nothing → knowledge layer was never seeded. Safe to fully re-run init.
- Returns with `sdlc:seed-version` tag → knowledge layer partially or fully seeded.

**3. Manifest** (operational-layer truth):
```bash
cat .sdlc-manifest.json 2>/dev/null | jq .
```
- Missing → operational layer was never written. Safe to fully re-run init.
- Present with `sdlc_version` → operational layer partially or fully written.

**4. Agent directory:**
```bash
ls .claude/agents/ 2>/dev/null
```
- Missing `software-architect.md` or `code-reviewer.md` → Stage 6 did not complete.

### Step 2: Match state to recovery action

| State | Recovery Action |
|-------|-----------------|
| No sentinel, no manifest, no agents | **Full re-run.** `/sdlc-initialize` — workspace is clean. |
| Sentinel exists, manifest missing | **Repair mode.** Re-run `/sdlc-initialize`; it detects sentinel + no manifest via mode detection and runs as Repair (Stage 1 re-entry, sentinel re-read). Knowledge layer is preserved; operational layer rebuilt. |
| Manifest exists, sentinel missing | **Unusual — investigate.** This usually indicates the Neuroloom API was unreachable during seeding but operational writes completed. Check API health, then re-run init — it will re-seed knowledge without duplicating operational files (idempotent writes). |
| Both present, agents missing | **Resume from Stage 6.** Re-run `/sdlc-initialize`; mode detection identifies "post-skeleton" state and resumes from agent roster. |
| Both present, all agents present, but compliance audit failed | **Targeted fix.** The CRITICAL finding identifies what to fix. Apply the fix, then dispatch `sdlc-compliance-auditor` manually to re-verify. Full init re-run is not required. |
| Sentinel version tag doesn't match manifest version | **Version drift.** Run `/sdlc-migrate` — it handles layer-independent version skew natively. |
| `installed_files` missing from manifest | **Pre-drift-detection install.** Next `/sdlc-migrate` will back-fill automatically (see Stage 3.2a of migrate). |

### Step 3: Never do these things

- **Do not manually edit the sentinel.** It is server-managed by `seed()`. Manual writes corrupt version tracking.
- **Do not delete `.claude/` to force a clean retry.** That loses agents, memory, and any project customizations. Use mode detection + repair instead.
- **Do not delete `.sdlc-manifest.json`.** Same reason — loses `installed_files` hashes needed for drift detection.
- **Do not hand-write agent files to skip `/sdlc-create-agent`.** Skipping validation is the fastest way to ship broken agents into production.

### Step 4: If nothing works — reset

Absolute last resort. Requires CD confirmation.

1. Note everything worth preserving: project customizations in `.claude/skills/*`, agent memories in `.claude/agent-memory/`, any PROJECT-SECTION blocks.
2. Back up: `git stash` or `cp -r .claude .claude.backup`.
3. Re-initialize explicitly via `/sdlc-initialize` with the re-initialize destructive-action gate — preserving knowledge-layer importance scores if possible.
4. Manually port project customizations back from the backup.
