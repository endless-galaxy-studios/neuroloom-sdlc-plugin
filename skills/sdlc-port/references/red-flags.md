## Red Flags

| Thought | Reality |
|---------|---------|
| "I'll delete the local knowledge files after porting." | Keep them until verified. Git is not enough — verify seeded counts match local counts before removing anything. |
| "All agent files need transformation." | Only files referencing `ops/sdlc/knowledge/` or `ops/sdlc/disciplines/` paths (or their `[sdlc-root]/` forms) need transformation. User-created agents may have no such references — scan before assuming. |
| "I only need to search for full `ops/sdlc/knowledge/` paths." | z-sdlc's own files mostly write `[sdlc-root]/knowledge/` and relative `](knowledge/…)` / `](disciplines/…)` links; search for those too. Also search for bare YAML filenames (`agent-context-map.yaml`, `agent-communication-protocol.yaml`). Validation checklists, maturity criteria, and template instructions reference these by name without the full path prefix. |
| "The transformation is just find-and-replace." | Transformations are LLM-driven because replacement context varies per reference. A file-read becomes a `memory_search` with domain-specific tags and a meaningful query string — not a mechanical substitution. |
| "Re-porting is safe and non-destructive." | A re-port re-sends the knowledge files and parking-lot entries still on disk, resetting those entries to the files' text, except entries tagged `sdlc:project-specific`, which the server never updates, and never a discipline's framework or project data (status, Active Questions, Project Context, tracker); with no files left it sends no knowledge at all. An upstream entry edited directly in Neuroloom since the last port is overwritten. Warn the user with Gate 3's wording. |
| "I can create the sentinel after Stage 3 completes." | The sentinel lifecycle is owned by `seed()` server-side. This skill never creates or updates the sentinel — it only reads it. |
| "A tags-only memory_search is fine for transformed files." | `memory_search` requires an explicit `query` parameter. Tags-only calls are invalid. Every replacement must include a meaningful query string. |
| "The seed files go in one by one; the last one can leave `skip_deprecation` off." | Every file goes with `skip_deprecation: true`. `sdlc_seed` without it marks every earlier seed memory the call leaves out as deprecated, whatever its version, and a weekly job deletes them: the other files' entries, and on a re-port everything the cleanup removed from disk. |
| "`CLAUDE.md` has no markers, so it isn't part of the SDLC." | z-sdlc merged its sections into it all the same. Find them by heading (Stage 4a), add the markers, and transform inside them; a markerless `CLAUDE.md` with knowledge references fails the audit. |
| "I'll use document_ingest_batch for SDLC knowledge." | Use `sdlc_seed` — it creates the sentinel, deduplicates via `knowledge_id`, and processes MemoryEntry semantics. `document_ingest_batch` produces generic documents with no sentinel and no deduplication guarantee. |
| "I'll write a script to extract YAML entries and build the seed file." | Use `${CLAUDE_SKILL_DIR}/scripts/extract_sdlc_knowledge.py` — it's bundled with this skill and handles all extraction, tag derivation, and JSON output. Do not write custom extraction scripts. |

---

