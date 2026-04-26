## Red Flags

| Thought | Reality |
|---------|---------|
| "I'll delete the local knowledge files after porting." | Keep them until verified. Git is not enough — verify seeded counts match local counts before removing anything. |
| "All agent files need transformation." | Only files referencing `ops/sdlc/knowledge/` or `ops/sdlc/disciplines/` paths need transformation. User-created agents may have no such references — scan before assuming. |
| "I only need to search for full `ops/sdlc/knowledge/` paths." | Also search for bare YAML filenames (`agent-context-map.yaml`, `agent-communication-protocol.yaml`). Validation checklists, maturity criteria, and template instructions reference these by name without the full path prefix. |
| "The transformation is just find-and-replace." | Transformations are LLM-driven because replacement context varies per reference. A file-read becomes a `memory_search` with domain-specific tags and a meaningful query string — not a mechanical substitution. |
| "Re-porting is safe and non-destructive." | Re-porting re-ingests everything, resetting knowledge entries to local file state. If Neuroloom knowledge has been updated directly since the last port, re-port overwrites those changes. Warn the user explicitly. |
| "I can create the sentinel after Stage 3 completes." | The sentinel lifecycle is owned by `seed()` server-side. This skill never creates or updates the sentinel — it only reads it. |
| "A tags-only memory_search is fine for transformed files." | `memory_search` requires an explicit `query` parameter. Tags-only calls are invalid. Every replacement must include a meaningful query string. |
| "I'll use document_ingest_batch for SDLC knowledge." | Use `sdlc_seed` — it creates the sentinel, deduplicates via `knowledge_id`, and processes MemoryEntry semantics. `document_ingest_batch` produces generic documents with no sentinel and no deduplication guarantee. |
| "I'll write a script to extract YAML entries and build the seed file." | Use `${CLAUDE_SKILL_DIR}/scripts/extract_sdlc_knowledge.py` — it's bundled with this skill and handles all extraction, tag derivation, and JSON output. Do not write custom extraction scripts. |

---

