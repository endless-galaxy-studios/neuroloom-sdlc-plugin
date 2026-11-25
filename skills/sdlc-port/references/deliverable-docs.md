# Stage 3b — Deliverable Docs

Read by `/sdlc-port` Stage 3b (`${CLAUDE_SKILL_DIR}/SKILL.md`).

Use the extraction script to generate batch files, then use the appropriate ingestion tool to
upload them. Do NOT manually construct entries or write custom extraction scripts — the
extraction script already handles frontmatter parsing, tag derivation, `knowledge_id`
construction, source type classification, and batching to 50 documents per file.

**Step 1 — Generate the batch files:**

```bash
python "${CLAUDE_SKILL_DIR}/scripts/extract_deliverable_docs.py" --output /tmp/neuroloom_doc_batch.json
```

This produces one or more batch files at `/tmp/neuroloom_doc_batch_batch_001.json`,
`/tmp/neuroloom_doc_batch_batch_002.json`, etc. (or a single `/tmp/neuroloom_doc_batch.json`
if all docs fit in one batch). Each file contains a flat JSON array of document objects.

Use `--dry-run` first to verify the scan results before writing files.

**Step 2 — Ingest each batch file:**

The tool to use depends on transport mode:

- **stdio mode:** The extraction script outputs flat JSON arrays, which is the format
  `document_ingest_batch_from_file` expects. Call directly:
  ```
  document_ingest_batch_from_file(path="/tmp/neuroloom_doc_batch_batch_001.json")
  ```

- **HTTP mode:** The extraction script outputs flat arrays, but `document_ingest_batch_get_upload_url`
  requires `{"documents": [...]}` wrapping (curl sends directly to the API). Wrap each batch
  file before uploading:
  ```bash
  python3 -c "import json,sys; d=json.load(open(sys.argv[1])); json.dump({'documents':d},open(sys.argv[1],'w'))" /tmp/neuroloom_doc_batch_batch_001.json
  ```
  Then call `document_ingest_batch_get_upload_url(path="/tmp/neuroloom_doc_batch_batch_001.json")`
  and execute the returned `curl_command` via Bash.

Report progress between batches. Check `summary.errors > 0` after every batch response. If
errors are present, log the failed entries from `results` and continue with the remaining
batches. Do not abort the full stage on partial batch failure — surface errors in the final
summary.

**Response shape** (identical for both tools):
```json
{
  "summary": {"total": N, "created": N, "updated": N, "unchanged": N, "errors": N},
  "results": [{"index": N, "title": "...", "status": "...", ...}]
}
```

**Deliverable Docs (`docs/current_work/**/*.md` and `docs/chronicle/**/*.md`)**

Per file:
- `source_type` — `"sdlc_deliverable"` for `docs/current_work/`, `"sdlc_chronicle"` for `docs/chronicle/`
- `format` — `"markdown"`
- `knowledge_id` — `"deliverable:{filename_without_ext}"`
- `tags` — from the file's YAML frontmatter, which the script reads: `sdlc:deliverable` on every
  doc, plus `sdlc:tier:<tier>`, `sdlc:type:<type>` and `sdlc:status:<status>` for the fields the
  frontmatter has. A doc with no frontmatter is skipped (the dry run lists them); it stays on disk,
  unchanged, and simply isn't searchable until it gets frontmatter
