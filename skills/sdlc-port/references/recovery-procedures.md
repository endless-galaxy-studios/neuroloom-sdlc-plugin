## Error Handling

### Stage 1 — Pre-flight failures

| Failure | Recovery |
|---------|----------|
| `ops/sdlc/` absent | Stop. Output: "No cc-sdlc installation found. Run /sdlc-initialize instead." |
| API auth failure | Stop. Output auth error with link to API key settings. Do not proceed. |
| API network failure | Stop. Output network error. Check connectivity and retry. |
| Manifest unreadable (malformed JSON) | Treat as no manifest — proceed as fresh port. Log the parse error. |

### Stage 2 — User cancels

Stop immediately. No writes have occurred. Nothing to roll back.

### Stage 3a — `sdlc_seed` failures

| Failure | Recovery |
|---------|----------|
| Response contains `"error"` key | Stop. Log the error message. Do not proceed to Stage 3b. Stage 3a is not retryable in the same run — surface the error and advise the user to re-run after resolving the issue. |
| Call fails entirely (network / server error) | Stop. Report the failure. Do not proceed to Stage 3b. User can re-run the port — `sdlc_seed` is idempotent via `knowledge_id` upsert. |

### Stage 3b — Document ingestion failures

| Failure | Recovery |
|---------|----------|
| `summary.errors > 0` in a batch response | Log failed entries from `results`. Continue remaining batches. Surface all failures in final summary. |
| `document_ingest_batch_from_file` or `document_ingest_batch_get_upload_url` call fails (network / server error) | Retry the batch once. If it fails again, skip and continue. Log the batch index. |
| All batches fail | Stop. Report total failure. User can re-run — Stage 3b is idempotent via `knowledge_id` upsert. |

### Stage 4 — Transformation failures

| Failure | Recovery |
|---------|----------|
| Edit tool fails on a file | Skip the file. Log the failure. Continue with remaining targets. |
| Validation finds stale `ops/sdlc/knowledge/` reference after edit | Restore the specific file: `git checkout .claude/agents/{file}.md`. Log the specific reference. |
| Validation finds stale `ops/sdlc/disciplines/` reference after edit | Restore the specific file: `git checkout .claude/agents/{file}.md`. Log the specific reference. |
| `memory_search` returns no match for a reference | Use the file path as the query basis. If still no match, skip transformation for that reference and log it. |

### Stage 5 — Manifest or verification failures

| Failure | Recovery |
|---------|----------|
| `sdlc_get_version` fails | Use `"local"` as the version value. Continue. |
| Sentinel not found after ingestion | Expected — sentinel is server-managed. Do not attempt to create it. If the sentinel is missing and ingestion completed successfully, report the discrepancy and advise the user to contact support. |
| Verification spot-check shows zero results for knowledge/discipline entries | Re-run `sdlc_seed` (Stage 3a). It is idempotent via `knowledge_id` upsert. |
| Verification spot-check shows zero results for deliverable docs | Re-run the specific batch from Stage 3b for that category using `document_ingest_batch_from_file` (stdio) or `document_ingest_batch_get_upload_url` (HTTP). Both tools are idempotent via `knowledge_id` upsert. |
| `.sdlc-manifest.json` write fails | Report the failure with the intended contents. User can write it manually. |
