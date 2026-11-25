# Stage 3c — Provenance Records

Read by `/sdlc-port` Stage 3c (`${CLAUDE_SKILL_DIR}/SKILL.md`).

If `ops/sdlc/knowledge/provenance_log.md` exists, store each of its entries as a memory. In a
Neuroloom project provenance is not a file (CD, 2026-10-29). This is ingestion, like 3a and 3b, so it
runs here, after the Stage 2 confirmation, and never waits on the Stage 4b transformation choice.

For each `prov-…` entry call `memory_store(title="<prov-id>: <short description>", content=<the entry's fields, status kept>,
tags=["sdlc:provenance", "sdlc:source-type:<type>", "sdlc:prov:<prov-id>", "sdlc:prov-status:<status>"], memory_type="general")`.
An `audit-sweep-…` entry takes the sweep record's tags instead. Both shapes are in
`${CLAUDE_PLUGIN_ROOT}/references/pattern-mapping-rules.md` § "Provenance records".

Before storing, look the entry up, because `memory_store` has no upsert and a re-port or a re-run
after a recovery reads the same file again. Every entry, sweep or not, is found by its id tag
`sdlc:prov:<id>`, together with `sdlc:provenance` so that no other memory carrying a matching tag
answers. `memory_get_index` returns ids and titles, not tags, so read a found record with
`memory_get_detail`: its tags carry the status, and its content carries the fields the entry was
stored with, `source` among them.
1. `memory_get_index(tags=["sdlc:provenance", "sdlc:prov:<id>"], limit=1)`. No row: store the entry.
2. A row: `memory_get_detail(id=<that id>)`. If its `source` differs from the entry's, it is a
   different record with the same id (provenance ids are numbered per day, so a branch that ran in
   file mode and the workspace can each have given one id to a different source): touch neither,
   store nothing for that entry, and list the id for the user.
3. Same source: a sweep entry has no status, so skip it. Otherwise compare statuses. The order is
   `pending-review` → `approved-for-ingest` → `ingested`, and `rejected` counts as later than all three;
   a stored `rejected` is never changed. Update only when the log's status is later:
   `memory_update(id=<that id>, narrative=<the entry's fields>, tags=<its full tag list, with the log's
   status>)`. A record Neuroloom already moved further on keeps its status: the file is the older copy.

There is no script for this step; do it by hand and report the counts stored, updated and skipped,
and the ids left alone for a source mismatch.

If any call for an entry fails (`memory_get_index`, `memory_get_detail`, `memory_store` or
`memory_update`), log the entry's id and continue with the rest, as Stage 3b does for a failed
batch; re-running the port retries what is still missing. Leave the file where it is. Post-Port
Cleanup removes it only when every entry was stored, updated or skipped as already current: an
entry that failed or was left alone for a source mismatch has no other copy, so the cleanup keeps
the file and names those ids.
