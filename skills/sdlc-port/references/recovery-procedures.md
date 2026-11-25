## Error Handling

### Stage 1 — Pre-flight failures

| Failure | Recovery |
|---------|----------|
| SDLC root check fails (`${CLAUDE_PLUGIN_ROOT}/references/preflight.md` check 0) | Stop with the message in that file's § Failure 0. Nothing has been written. |
| `ops/sdlc/` absent | Stop. Output: "No z-sdlc installation found. Run /sdlc-initialize instead." |
| The extractor's dry run exits non-zero (Inventory) | Stop. Nothing has been written. Do what its message says for each refusal: a duplicate id, or a `discipline:` id written in a knowledge file (rename it); a `discipline:` id the extractor built from a file's path (rename or move the file, or its directory, so its path under `knowledge/` no longer begins `discipline`); a tag Neuroloom adds itself (remove it from the item); a malformed `tags` value (make it a list of strings, quoting an element YAML would read as a boolean or number). One in upstream's release is a plugin bug: report it, don't edit the file. Then re-run `/sdlc-port`. |
| The upstream baseline fetch fails (Inventory) | Stop. Nothing has been written. Re-run once `gh` reaches GitHub: without the baseline, the project's own entries would be seeded without `sdlc:project-specific`, and tags can't be added to a row later. |
| `decide_port_gate.py` exits 2 | Stop. Nothing has been written. A fact is missing or malformed (the message names it); gather it again, never decide by hand. |
| Gate 3 finds an install `/sdlc-initialize` set up with the plugin (reasons `initialized_project`, `unfinished_initialize`, `pre_0_7_0_initialize`) | Stop. Nothing has been written. There is no file-mode install to port. An unfinished initialize is finished with its own recovery (`${CLAUDE_PLUGIN_ROOT}/references/adapter-lifecycle.md` § Halts and their recoveries); one from before 0.7.0 needs the one-time conversion. |
| Gate 3 refuses a re-port (case 3) | Stop with the script's message. Nothing has been written. `pre_0_7_0_port`: the workspace needs the one-time conversion this release doesn't do. `no_workspace_id`: the manifest doesn't record the workspace; add the id of this project's workspace if CD knows it, and re-run. `different_workspace`: the API key reaches another workspace (fix the key, or the manifest if the workspace really moved). `no_sentinel`: the recorded workspace has no sentinel, so it doesn't hold this project's knowledge; check the key and the workspace. `label_differs` / `sentinel_moved`: a migration ran since the port, and the knowledge is edited in Neuroloom from here on. `no_seed_version`: the manifest was edited; a re-port is refused. `incomplete_port_record` (`ported_at` without `neuroloom_backend`): the manifest was edited; if this project was ported, put `"neuroloom_backend": true` back and run the port again. |
| Gate 3 finds records the manifest doesn't account for (case 4, `unaccounted_rows`: none of `port_in_progress`, `ported_at` or `neuroloom_backend`) | Stop with Gate 3's message, which names the workspace. Nothing has been written. The records are this project's from before 0.7.0 (conversion needed), another project's (port into a workspace of its own), or this project's own stopped port whose marker was lost: when `label_matches` is true and CD confirms, put back `port_in_progress` and `workspace_id`, and re-run. |
| A continued port (case 1, `no_workspace_id` or `different_workspace`) whose manifest records no `workspace_id`, or one other than the search's `filters.workspace_id` | Stop with Gate 3's message. Nothing has been written by this run. A different id: point the API key back at the workspace the port started in. No id: add the `workspace_id` of the workspace the port started in, if CD knows it, and re-run. |
| Gate 3's search returns an error (case 0, `search_failed`) | Stop. Nothing has been written. Re-run once the search works. |
| Inventory finds zero entries on a fresh or continued port | Stop with the Inventory's message. Nothing has been written. Put the project's `knowledge/` and `disciplines/` in place first. |
| API auth failure | Stop. Output the auth error and the setup command (`/plugins configure neuroloom`). Do not proceed. |
| API network failure | Stop. Output network error. Check connectivity and retry. |
| Manifest unreadable (malformed JSON) | Stop. Report the parse error. Stage 5 merges into the manifest, so writing over an unreadable one would drop its `installed_files`, `declined_files` and `adapter` block: the user fixes the file (or restores it from git) and re-runs. |

### Stage 2 — User cancels

Stop immediately. No writes have occurred. Nothing to roll back.

### Stage 3a — `sdlc_seed` failures

| Failure | Recovery |
|---------|----------|
| The extractor exits non-zero (Stage 3a, a refusal its dry run couldn't see, such as one in the baseline) | Stop. Nothing has been sent to Neuroloom; on a fresh port the manifest's in-progress marker (`port_in_progress`, `workspace_id`) stays, so the re-run continues this port. Fix what the message names as for the Inventory row, then re-run `/sdlc-port`. A refusal in upstream's release repeats until the plugin is fixed. When Gate 3 saw no sentinel and no SDLC records this run (always so when its action was `fresh`), nothing in Neuroloom depends on the marker yet: to abandon the port meanwhile, take `port_in_progress` and `workspace_id` out of the manifest. Otherwise keep them: an earlier run's records are in Neuroloom, and without the marker Gate 3 stops on them as unaccounted. |
| A seed file fails (the response lacks the four counts: an `error` or `detail` key, a non-2xx status, an expired upload token) | Stop. Log the response and the file. Do not proceed to Stage 3b. The files before it stay as written. The user re-runs the port after resolving the issue; every file is sent again with `skip_deprecation: true`, and entries already written come back `unchanged`. Never re-send without the flag: it would mark the other files' entries deprecated. |
| Call fails entirely (network / server error) | Stop. Report the failure. Do not proceed to Stage 3b. User can re-run the port — `sdlc_seed` is idempotent via `knowledge_id` upsert, with `skip_deprecation: true` as always. |

### Stage 3b — Document ingestion failures

| Failure | Recovery |
|---------|----------|
| `summary.errors > 0` in a batch response | Log failed entries from `results`. Continue remaining batches. Surface all failures in final summary. |
| `document_ingest_batch_from_file` or `document_ingest_batch_get_upload_url` call fails (network / server error) | Retry the batch once. If it fails again, skip and continue. Log the batch index. |
| All batches fail | Stop. Report total failure. User can re-run — Stage 3b is idempotent via `knowledge_id` upsert. |

### Stage 3c — Provenance record failures

| Failure | Recovery |
|---------|----------|
| A `memory_store` or `memory_update` call fails | Log the entry's id. Continue with the rest. Report the ids in the final summary. Re-running the port retries them: entries already stored are skipped or updated, never stored twice. |
| The `memory_get_index` lookup fails | Don't store that entry (it might be a duplicate). Log its id and continue, as above. |

### Stage 4 — Transformation failures

| Failure | Recovery |
|---------|----------|
| Edit tool fails on a file | Skip the file. Log the failure. Continue with remaining targets. Name it in the final summary: for an agent's `tools` line (Stage 4c's **Agent tools** or Stage 4g's grant), with the tools to add by hand, since nothing later checks the line and the agent's Neuroloom calls would fail. |
| Moving a replaced `knowledge-routing.md` into `sdlc-port-kept/` fails after a passing audit | The port is finished: never undo this run. Move the file by hand (`<undo>/files/ops/sdlc/process/knowledge-routing.md` to the kept directory), then delete this run's `<undo>`, `.sdlc-manifest.json.pre-port`, `CLAUDE.md.pre-port` and `CLAUDE.md.pre-port.region`. Then, in the same session, finish the run: Post-Port Cleanup (`verification-manifest.md` § Post-Port Cleanup; a first port Gate 3 didn't continue still asks its question, since the halt came after the audit) and the final summary, naming the kept file. A re-run would be a re-port, which never offers the cleanup; in a later session, the summary is gone: take the kept file's name from `sdlc-port-kept/` and remove the knowledge files by hand as that section's skip note says. |
| The port is abandoned after Stage 4c (any halt or crash past it) | Use the run's own `<undo>`: the one its halt named. A halt that says the run was undone (an audit, checklist or count failure) left nothing of that run to undo; on a continued port (Gate 3 case 1), if another run's `<undo>` remains (the earlier stopped run it built on, which stays unrestored), undo it as after a crash. To undo a run, first undo any later run that is still unrestored, newest first (a completed whole-run undo deletes its `<undo>`, so only unrestored runs are left). After a crash with no halt, list the directories under `$(git rev-parse --git-path sdlc-port-undo)/` (or `.sdlc-port-undo/` outside git) with their timestamps and ask CD which run to undo; a run whose audit passed deleted its own and is finished, so never undo it with another run's. Copy every file under `<undo>/files/` back to its path, remove each file `<undo>/created` lists, restore `CLAUDE.md`'s region as Stage 4d does if its copy still exists (agent memory comes back with `<undo>/files/`), and, if `<undo>/sdlc-manifest.json` exists (Stage 5 had started), copy it back over the manifest, whether or not the manifest still parses. Once a run's restores above are done, delete its `<undo>`, so no later recovery applies it again. Never `git checkout` a transformed file: it would discard an uncommitted edit in it. |
| Validation finds stale `ops/sdlc/knowledge/` reference after edit | Copy the specific file back from Stage 4c's copy (`<undo>/files/<its path>`), never from git, which would discard an uncommitted edit in it. Log the specific reference. `CLAUDE.md` gets only its SDLC region back from the copy Stage 4c made, as Stage 4d says (not git, not the whole file), so edits outside the region survive. |
| Validation finds stale `ops/sdlc/disciplines/` reference after edit | Restore the specific file by its path, as above. Log the specific reference. |
| `memory_search` returns no match for a reference | Use the file path as the query basis. If still no match, skip transformation for that reference and log it. |

### Stage 4g — Agent memory edits

| Failure | Recovery |
|---------|----------|
| A remapped agent-memory file is wrong | Copy back the files under the run's `<undo>/files/.claude/agent-memory/`, where Stage 4g copies each file before changing it, and only those: the rest of the directory may hold notes added since. Git ignores `.claude/agent-memory/`, so `git checkout` cannot restore it. If the port is abandoned after 4g, follow Stage 4's abandon row instead: it copies back all of `<undo>/files/`, which holds these and the agent files 4g gave tools (`<undo>/files/.claude/agents/`). |

### Stage 5 — Manifest or verification failures

| Failure | Recovery |
|---------|----------|
| Sentinel not found after ingestion | Look again by exact tag (`memory_get_index(tags=["sdlc:sentinel"], limit=1)`): the seed reset its embedding, so a relevance search can miss it. The sentinel is server-managed: never create it. Still missing after a successful seed: the checklist fails (the manifest goes back to the pre-port copy); report the discrepancy. |
| Verification spot-check shows zero results for knowledge/discipline entries | Re-run `sdlc_seed` (Stage 3a). It is idempotent via `knowledge_id` upsert. |
| Verification spot-check shows zero results for deliverable docs | Re-run the specific batch from Stage 3b for that category using `document_ingest_batch_from_file` (stdio) or `document_ingest_batch_get_upload_url` (HTTP). Both tools are idempotent via `knowledge_id` upsert. |
| `.sdlc-manifest.json` write fails | Report the failure with the intended contents. User can write it manually. |
