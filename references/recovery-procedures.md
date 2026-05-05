# Error Handling and Recovery

## Recovery principles

1. **Migration is resumable, not rollback-able.** There is no "undo" for a completed batch ingest or filesystem write. If a stage fails partway through, resume by re-running the skill — `knowledge_id` upsert and PROJECT-SECTION marker preservation make every stage idempotent.
2. **Never delete to recover.** If something looks half-applied, do not `rm` files or delete memory entries to force a clean retry. The upsert + marker logic handles re-application correctly. Destructive recovery loses work.
3. **Version tags are authoritative.** The sentinel's `sdlc:seed-version:{v}` and `.sdlc-manifest.json`'s `source_version` determine state. If they disagree with observed behavior, trust the tags and re-run — don't try to manually correct them.
4. **Knowledge and operational layers fail independently.** A knowledge-layer failure (Stage 4.1) does not invalidate operational-layer work (Stage 4.2) and vice versa. Report the state of each layer separately in failure reports.

## Failure modes

| Failure Mode | Detection | Response | Recovery |
|-------------|-----------|---------|----------|
| Neuroloom API unreachable | `sdlc_get_version` fails with network error | Stop at Stage 1.2. Report config issue. | Fix network/config, re-run. Stage 1 is read-only, safe to restart. |
| Neuroloom auth invalid | `sdlc_get_version` returns 401 | Stop at Stage 1.2. Show API key setup instructions. | Re-configure key, re-run. |
| Auth token expires mid-migration | Any MCP call after Stage 1 returns 401 | Stop at current stage. Report which stage and how many entries completed. Preserve partial progress. | Re-configure key, re-run — idempotent stages resume from where they stopped. |
| GitHub rate limit hit during fetch | 403 + `X-RateLimit-Remaining: 0` at Stage 3.1 | Stop, report reset time. | Wait until reset or run `gh auth login`, re-run from Stage 3. |
| `.sdlc-manifest.json` missing or corrupt | Stage 1.3 can't read `source_version` | Check sentinel as fallback. If sentinel also missing, abort and tell CD to run `/sdlc-initialize`. | Restore from git if committed; otherwise full re-init. |
| `sdlc:seed-version` tag missing from sentinel | Stage 1.3 sentinel lookup returns no version tag | Treat as `KNOWLEDGE_VERSION = "0.0.0"` — forces full re-seed. Warn CD: "Sentinel version tag missing; will re-seed all knowledge." | Proceed; re-seed restores tag via server-side `seed()`. |
| Contract change detected (Stage 2.2a) | Changelog contains `[contract-change]` entries | Hard stop per Stage 2.2a gate. | Maintainer updates Pattern Mapping table in this skill, re-runs migration. |
| CD cancels at preview gate | CD selects "Cancel" at Stage 3.3 | Exit cleanly. No mutations performed yet (preview is read-only). | Re-run when ready. |
| `document_ingest_batch` partial error | `summary.errors > 0` at Stage 4.1 | Log failed entries (title + error). Continue if <10% failed. | Re-issue failed entries via follow-up batch; `knowledge_id` upsert is idempotent. |
| `document_ingest_batch` network interruption mid-batch | Call times out, response partial or absent | Batch state is indeterminate — re-issue the full batch. Idempotent upsert makes it safe. | Automatic single retry. If still fails, log + continue. |
| Discipline re-seed (Stage 4.1a) partial error | Framework-section upsert fails for one or more disciplines | Log per-discipline failure. Continue with remaining disciplines. Report in Stage 5. | Re-run migration — framework-section `knowledge_id`s (`discipline:{name}:framework`) are deterministic, failed disciplines retry automatically on next run. |
| >10% of knowledge entries errored | Count check after all Stage 4.1 batches | Stop. Ask CD whether to continue with operational layer or abort. | CD decides. If proceed, knowledge layer stays at intermediate version; re-run migration later to complete. |
| PROJECT-SECTION marker mismatch during merge | Stage 4.2: opening marker without close, or label mismatch | Abort that specific file's merge. Report marker error. Continue with other files. | Fix markers in the project file, re-run migration — only the affected file re-merges. |
| Transformation phrase unmatched | Stage 4.2: upstream file contains a standard-phrase-adjacent pattern not in Pattern Mapping | Log as `TRANSFORMATION_WARNING`. Apply upstream content verbatim. Continue. | Post-migration: review warnings. If a genuinely new phrase appeared without `[contract-change]` tag, file an upstream issue. Update Pattern Mapping if confirmed. |
| Filesystem write fails | `Write`/`Edit` returns error | Log path + error. Offer retry. Continue with other files. | Fix underlying issue (permissions, disk, lock), retry the specific write. |
| Modified file rejected by CD | Stage 4.2 per-file gate: CD selects "Keep mine" | Skip that file. Log decision. | No action — intentional project preservation. |
| `.sdlc-manifest.json` write fails at Stage 4.4 | Stage 4.4 manifest update errors | Migration is effectively incomplete — version tracking won't reflect new state. | Retry manifest write directly. If filesystem is failing broadly, address that first. |
| Sentinel version tag doesn't update after Stage 4.1 | Stage 5.1 verification: sentinel still shows old version | Wait 5s and re-check (server-side tag update may lag). Retry 3× before reporting as migration incomplete. | If still stale: knowledge layer is at intermediate state. Re-run migration — idempotent upsert completes. |
| Agent context-map paths don't resolve | Stage 5.2 (N/A for Neuroloom — skipped) | N/A — Neuroloom projects don't have agent-context-map.yaml | — |
| Compliance audit finds CRITICAL | Stage 5.3 auditor returns CRITICAL findings | Fix before declaring complete. | Typically indicates wiring or marker issues — address per finding, re-audit. |

## Recovery / Emergency Restore

If `/sdlc-migrate` crashes, is interrupted, or leaves the workspace in an inconsistent state, use this section to diagnose and recover. Migration is designed to be resumable — most scenarios resolve via re-running the skill.

### Step 1: Diagnose

**Transaction log** (authoritative timeline):
```bash
tail -n 200 .sdlc-transaction-log | jq -c 'select(.run_id | startswith("migrate-"))'
# Last `run_start` marks the crashed migration run
# Last `mutation` event shows what was last committed
# Presence of `checkpoint: point_of_no_return` tells you whether mutations were attempted
```

**Sentinel version tag:**
```
memory_search(query="SDLC workspace sentinel", tags=["sdlc:sentinel"])
```
Check the `sdlc:seed-version:{v}` tag — this is the authoritative knowledge-layer version.

**Manifest version:**
```bash
jq -r '.sdlc_version' .sdlc-manifest.json
```
Authoritative operational-layer version.

### Step 2: Match state to recovery action

| State | Recovery Action |
|-------|-----------------|
| Crash before point_of_no_return | **Safe — no recovery needed.** Re-run `/sdlc-migrate` from the top. Preflight and state extraction are idempotent. |
| Crash after point_of_no_return, sentinel tag updated, manifest not updated | **Knowledge layer committed, operational layer partial.** Re-run `/sdlc-migrate` — early-exit logic detects "knowledge current, operational stale" and completes only the operational portion. |
| Crash after point_of_no_return, sentinel tag NOT updated, manifest updated | **Operational committed, knowledge partial.** Re-run `/sdlc-migrate` — detects "knowledge stale, operational current" and re-runs only Stage 4.1 knowledge re-seed. |
| Crash during Stage 4.1 (batch ingest mid-flight) | **Idempotent upsert saves you.** Re-run `/sdlc-migrate` — `document_ingest_batch` with `knowledge_id` re-applies without duplicates. Entries already ingested return `unchanged`. |
| Crash during Stage 4.2 (file writes mid-flight) | **File-level idempotency saves you.** Re-run `/sdlc-migrate` — PROJECT-SECTION markers are re-extracted and re-injected; overwrites produce the same result; skipped files stay skipped. |
| Sentinel and manifest versions both at `LATEST_VERSION` but workspace feels broken | **Completion state reached but something else failed.** Dispatch `sdlc-compliance-auditor` directly to identify the issue. Migration itself is complete. |
| Drift detection flagged files but decisions were lost to crash | **Re-run `/sdlc-migrate`.** Drift re-detected at Stage 3.2a; CD re-prompted with same options. Prior decisions not preserved across crashes (no drift_decision log replay yet). |
| Contract-change gate was about to block but user dismissed prematurely | **Update Pattern Mapping manually**, commit the plugin change, then re-run `/sdlc-migrate`. |

### Step 3: Never do these things

- **Do not manually update the sentinel's version tag.** The server owns this — manually writing it breaks future version tracking.
- **Do not edit `.sdlc-manifest.json` to match what you think the state should be.** If the manifest is wrong, re-run migrate; don't synthesize state.
- **Do not delete `.claude/` and re-run `/sdlc-initialize`.** That loses drift-detection history and treats the workspace as greenfield. Always prefer re-running migrate for mid-migration recovery.
- **Do not ignore `TRANSFORMATION_WARNING` entries.** They signal Pattern Mapping gaps that will compound at each migration.

### Step 4: Absolute last resort

If the workspace is so corrupted that re-running migrate cannot resolve it:

1. Back up: `cp -r .claude .claude.backup-{date}`, `cp .sdlc-manifest.json .sdlc-manifest.backup-{date}.json`
2. Export Neuroloom workspace state (if supported by your Neuroloom tier) for reference
3. Run `/sdlc-initialize` in re-initialize mode (destructive gate — loses importance scores)
4. Re-apply project customizations from backup

This path loses accumulated feedback and importance scores — use only when no other recovery works.
