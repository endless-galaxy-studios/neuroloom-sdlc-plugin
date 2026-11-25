# Error Handling and Recovery

This file covers the Neuroloom side of a failed run: the four phase handlers in `adapter-lifecycle.md` (`knowledge-seed`, `knowledge-update`, `post-file-write`, `post-operation`) and the knowledge layer they write. For the upstream steps, read `sdlc-migrate`'s and `sdlc-initialize`'s own recovery references (`references/recovery-procedures.md`, `references/recovery-emergency.md`). Step numbers below are `sdlc-migrate` sections unless the row says otherwise.

## Recovery principles

1. **A halt follows its operation's recovery; a crash resumes.** A phase that halts names its recovery from `adapter-lifecycle.md` § Halts and their recoveries (a migration saves everything, undoes only a run that began on a clean tree, and is re-run; an initialize keeps its writes and is finished by hand). A run that crashed without a halt message is resumable: there is no "undo" for a completed batch ingest, and `knowledge_id` upsert and PROJECT-SECTION marker preservation make a re-run of `/sdlc-migrate` safe. An initialize re-run after a crash reports "Already initialized" once Phase 4 has made the agents, so it is finished by hand as the table says.
2. **Never delete to recover.** If something looks half-applied, do not `rm` files or delete memory entries to force a clean retry. The upsert and marker logic re-apply correctly. Destructive recovery loses work.
3. **Version tags are authoritative.** The sentinel's `sdlc:seed-version:{v}` and `.sdlc-manifest.json`'s `source_version` determine state. If they disagree with observed behavior, trust the tags. Don't correct them by hand.
4. **Knowledge and file layers fail independently.** A `knowledge-update` failure does not invalidate the files upstream and `post-file-write` wrote, and the reverse. Report the state of each layer separately in failure reports.

## Failure modes

| Failure Mode | Detection | Response | Recovery |
|-------------|-----------|---------|----------|
| Neuroloom API unreachable | `sdlc_get_version` fails with a network error (preflight check 1, or step 1 of `knowledge-seed` / `knowledge-update`) | Stop and report the config issue. Both handlers are `halt` on failure. | Fix network/config, re-run. In a migration, the handler runs in Phase 2, so files upstream copied earlier in the phase are already on disk. The re-run completes them (see "Match state to recovery action"). |
| Neuroloom auth invalid | `sdlc_get_version` returns 401 | Stop. Show API key setup instructions. | Re-configure the key, re-run. |
| Auth token expires mid-run | Any MCP call after the first returns 401 | Stop at the current phase. Report which phase and how many entries completed. Keep partial progress. | Re-configure the key, then follow the operation's recovery (`adapter-lifecycle.md` § Halts and their recoveries). Upsert skips entries already ingested. |
| GitHub rate limit too low | `gh api rate_limit` shows `remaining` ≤ 50 (preflight check 2) | Stop, report the reset time. | Wait until reset or run `gh auth login`, re-run. |
| `.sdlc-manifest.json` missing or unreadable | Preflight check 8 warns. In `sdlc-migrate` §1.1 a missing or `"unknown"` `source_version` is treated as a full migration. | A full migration compares every framework file and asks about each difference (§2.1c). | Restore the manifest from git if it was committed. |
| A `[contract-change]` entry is newer than the adapter supports | `sdlc-migrate` §1.2 compares each entry's z-sdlc version with `supported_zsdlc_version` in `adapter.json` | Halt. The message names the uncovered entries and the adapter's version. | Maintainer updates the Pattern Mapping rules (`references/pattern-mapping-rules.md`) and the handlers, raises `supported_zsdlc_version` in `adapter.json`, re-runs migration. |
| CD stops at the Phase 1 decision point | CD answers "Stop" to the §1.2 summary and the drift, deviation and mark questions | Exit cleanly. Phase 1 writes only the transaction log and fetched refs, so no project file changed. | Re-run when ready. |
| CD keeps their version of a drifted file | `drift_decision` of `keep` (§1.2a) | Skip that file. The decision is logged. | No action. This is intentional project preservation. |
| A seed file is rejected | `sdlc_seed_from_file` (or the upload) returns an `"error"` key (`knowledge-seed` step 6, `knowledge-update` step 10) | The phase halts, naming the file. The server rejects a whole call for one bad entry, so nothing from that file was written; earlier files' entries stay as written. | Fix the cause the error names, then follow the operation's recovery in `adapter-lifecycle.md` § Halts and their recoveries: on `/sdlc-initialize`, keep the run's files, run `knowledge-seed` again from that file and finish the remaining phases by hand; on `/sdlc-migrate`, undo the run and re-run it. Either way every file goes again with `skip_deprecation: true`, and upsert by `knowledge_id` makes a repeat safe: entries already written return `unchanged`. |
| A seed call times out | No response, or a partial one | The file's state is indeterminate. Send it again with `skip_deprecation: true`. | If it still fails, halt: both handlers are `halt` on failure. |
| Discipline re-seed partial error | The step 8 verification search in `knowledge-update` returns nothing for one or more disciplines | Log the per-discipline failure. Continue with the remaining disciplines. Report it in the migration report. | Re-run migration. Framework-section `knowledge_id`s (`discipline:{name}:framework`) are deterministic, so failed disciplines retry. If the manifest already names the target, see the row above. |
| Malformed PROJECT-SECTION marker (unpaired, label mismatch, nested) | `sdlc-compliance-auditor` lists it as a minor finding (§4.4). If a marker is lost during transformation, the PROJECT-SECTION Preservation Audit in `post-file-write` halts (`content-merge-audits.md`). | Fix before declaring the migration done. | Fix the markers in the project file, re-run migration. |
| Transformation phrase unmatched | `post-file-write`: upstream file contains a standard-phrase-adjacent pattern not in Pattern Mapping | Log as `TRANSFORMATION_WARNING`. Apply upstream content verbatim. Continue. | Post-migration: review the warnings. If a genuinely new phrase appeared without a `[contract-change]` entry, file an upstream issue. Update Pattern Mapping if confirmed. |
| `post-file-write` audit halts | `neuroloom-transformer` reports HALT from one of the audits in `content-merge-audits.md` | The phase fails (`halt`). The halt message names the file and the recovery. | Fix the cause the message names, then follow the operation's recovery (`adapter-lifecycle.md` § Halts and their recoveries); on an initialize, re-dispatch the transformer on the file after the fix. |
| Filesystem write fails | `Write`/`Edit` returns an error | Log path + error. Offer retry. Continue with other files. | Fix the underlying issue (permissions, disk, lock), retry the specific write. |
| `.sdlc-manifest.json` write fails in §4.5 | The manifest update errors | Migration is effectively incomplete: version tracking won't reflect the new state. | Retry the manifest write directly. If the filesystem is failing broadly, address that first. |
| Post-operation regressions | `post-operation` reports a REGRESSION (the telemetry assertion included). The handler is `warn-continue`, so upstream goes on to write the new manifest. | The report lists each regression. | Follow migrate's recovery in `adapter-lifecycle.md` § Halts and their recoveries: save first, then undo only a run that began on a clean tree, the manifest included (restoring files without it leaves a manifest that says "already on" the target). Then re-run `/sdlc-migrate`. |
| Sentinel version tag still old after `knowledge-update` | `post-operation` Check 5 (sentinel carries the current version tag) or its migrate check on `[target_tag]` | Reported as a regression or WARN. The manifest is written anyway. | Search the sentinel again, since the server updates its tag after the re-seed. If it is still stale, the knowledge layer is at an intermediate state: follow migrate's recovery (`adapter-lifecycle.md` § Halts and their recoveries), which puts the manifest back even on a tree that wasn't clean, so §1.1 sees the old version, then re-run `/sdlc-migrate`. |
| Compliance audit finds Critical or Major | `sdlc-compliance-auditor` (§4.4) returns the finding | Fix before continuing, then re-dispatch the auditor. Minor and Info findings go in the migration report. | Usually wiring or marker issues. Fix per finding, re-audit. |

## Recovery / Emergency Restore

If `/sdlc-migrate` crashes, is interrupted, or leaves the workspace in an inconsistent state, use this section to diagnose and recover. Most scenarios resolve by re-running the skill.

### Step 1: Diagnose

**Transaction log** (authoritative timeline):
```bash
tail -n 200 .sdlc-transaction-log | jq -c 'select(.run_id | startswith("migrate-"))'
# The last `run_start` marks the crashed migration run
# The last `phase_start` with no `phase_end` is where it stopped
# `checkpoint: point_of_no_return` tells you whether file writes had begun
```
The log records counts, not file paths (a `mutation` event says how many files were written, not which). To see what changed on disk, use `git status` and `git diff`.

**Sentinel version tag:**
```
memory_search(query="SDLC workspace sentinel", tags=["sdlc:sentinel"])
```
Check the `sdlc:seed-version:{v}` tag. It is the authoritative knowledge-layer version.

**Manifest version:**
```bash
jq -r '.source_version' .sdlc-manifest.json
```
`source_version` is the version `sdlc-migrate` last completed (§4.5 writes it last).

### Step 2: Match state to recovery action

| State | Recovery Action |
|-------|-----------------|
| Crash before `point_of_no_return` | **Safe, no recovery needed.** Phase 1 is read-only. Re-run `/sdlc-migrate` from the top. |
| Crash after `point_of_no_return`, manifest still at the old `source_version` | **Partial run.** Re-run `/sdlc-migrate`. §1.1 sees the old version and runs the migration again. Copies and merges give the same result on a file already written (PROJECT-SECTION marks are re-extracted and kept), and `knowledge-update` upserts by `knowledge_id`, so entries already ingested return `unchanged`. Phase 1 asks its drift, deviation and mark questions again. |
| Crash during `knowledge-update` (seed files mid-flight) | **Idempotent upsert saves you.** Re-run `/sdlc-migrate`. `sdlc_seed` upserts by `knowledge_id`, so files already sent return `unchanged` and nothing is duplicated. |
| Crash during file writes (§2.1 to §2.4, or the `post-file-write` handler) | **File-level idempotency saves you.** Re-run `/sdlc-migrate`. |
| Manifest at `[target_tag]`, but the workspace feels broken | **The migration completed and something else failed.** Dispatch `sdlc-compliance-auditor` directly to identify the issue. Re-running stops at §1.1 ("Already on [target_tag]"). |
| Manifest at `[target_tag]`, but knowledge entries errored or the sentinel tag is stale | **Knowledge layer incomplete.** Re-send the failed entries, or follow migrate's recovery (`adapter-lifecycle.md` § Halts and their recoveries) and re-run `/sdlc-migrate`. It saves the tree first, so what §4.5 recorded (a new `declined_files` entry and its rationale, say) stays in the saved patch or copies (outside a git repository nothing is saved, so copy `.sdlc-manifest.json` aside first), and only then puts the manifest back from the run's snapshot (§ The manifest snapshot) whatever `git status` shows (git alone would drop uncommitted keys, such as an uncommitted port's). |

### Step 3: Never do these things

- **Do not manually update the sentinel's version tag.** The server owns it. Writing it by hand breaks future version tracking.
- **Do not edit `.sdlc-manifest.json` to match what you think the state should be.** Restore it from git or re-run migrate. Don't synthesize state.
- **Do not delete `.claude/` or `ops/sdlc/` to force a clean retry.** That loses project customizations and the drift-detection baseline. A crashed `/sdlc-initialize` is finished by hand, as initialize's recovery in `adapter-lifecycle.md` § Halts and their recoveries says: once Phase 4 has made the agents, its mode detection reports "Already initialized" and never reaches the phases still owed.
- **Do not ignore `TRANSFORMATION_WARNING` entries.** They signal Pattern Mapping gaps that compound at each migration.

### Step 4: Absolute last resort

If the workspace is so corrupted that re-running migrate cannot resolve it:

1. Back up: `cp -r .claude .claude.backup-{date}`, `cp -r ops/sdlc ops/sdlc.backup-{date}`, `cp .sdlc-manifest.json .sdlc-manifest.backup-{date}.json`
2. Export Neuroloom workspace state (if your Neuroloom tier supports it) for reference.
3. Follow upstream's reset (`sdlc-initialize`'s `references/recovery-emergency.md`, Step 4) and re-run `/sdlc-initialize`. If its Phase 1 writes a fresh manifest, then before `knowledge-seed` runs, copy `knowledge_id_scheme`, `knowledge_seed_in_progress` and `workspace_id` into it from the backed-up manifest (whichever it had) (they were there if the workspace was seeded by 0.7.0 or later); without them `knowledge-seed` finds the existing entries, can't tell whose they are, and halts. With them it reports a re-initialization: entries tagged `sdlc:project-specific` are kept, and base importance scores go back to seed values.
4. Re-apply project customizations from the backup.

This path loses the importance adjustments `memory_rate` feedback accumulated on non-project-specific entries. Use it only when no other recovery works.

### Deprecated entries

An `sdlc_seed` call without `skip_deprecation: true` tags every earlier seed memory it leaves out `sdlc:deprecated`, whatever its version or origin. The weekly `cleanup_deprecated_sdlc_entries` job (Sundays, 12:00 UTC) then deletes every memory carrying that tag. After that run the entry is gone and has to be ingested again. That is why every caller in this plugin (`knowledge-seed`, `knowledge-update`, `/sdlc-port`) sends every file with `skip_deprecation: true`, and lists what upstream removed for CD instead of retiring it.
