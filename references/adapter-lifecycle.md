# Adapter Lifecycle Handlers — Neuroloom SDLC Plugin

Phase handler instructions for the cc-sdlc adapter lifecycle protocol. Upstream's `sdlc-initialize` and `sdlc-migrate` read this file and execute the relevant H2 section at each phase.

**Required reading before any phase:** `${CLAUDE_PLUGIN_ROOT}/references/pattern-mapping-rules.md` must be read from disk before executing `post-file-write`. Do NOT reconstruct transformation rules from memory.

**Pre-flight dependency:** Before any lifecycle phase fires, the adapter's pre-flight protocol (`${CLAUDE_PLUGIN_ROOT}/references/preflight.md`) must have passed. This validates Neuroloom API reachability, MCP tool availability (`document_ingest_batch`, `memory_search`, `memory_store`, `sdlc_get_version`), GitHub API access, and disk space. Pre-flight is the adapter's own gate — it runs before upstream's skill begins its Phase 1.

**Contract change version gate:** Upstream reads `adapter.json → supported_ccsdlc_version` during pre-flight. If any `[contract-change]` entry in the migration range has a version above the adapter's declared support, upstream halts with a message identifying the uncovered entries. The adapter maintainer must update `adapter.json` after verifying handler coverage before migration can proceed.

---

## knowledge-seed
**On failure:** halt

Ingest all knowledge into the Neuroloom API via `document_ingest_batch`. No flat YAML files are written to `[sdlc-root]/knowledge/` (except `provenance_log.md`, which is project-specific and lives on disk).

### Pre-seed: Check existing knowledge

Before ingesting, check what already exists in the workspace for each domain:

```
memory_search(query="SDLC knowledge entries", tags=["sdlc:knowledge", "sdlc:domain:{domain}"])
```

If results exist, this is a re-initialization. Count entries tagged `sdlc:project-specific` — these will be preserved (never overwritten). Report the count to upstream so it can include it in its confirmation gate:

```
Re-initialization detected. {N} project-specific knowledge entries will be preserved.
WARNING: Base importance scores will be reset to seed values. Accumulated
importance adjustments from memory_rate feedback will be lost for non-project-specific entries.
```

Upstream presents this in its Phase 4 confirmation gate alongside its own summary.

### Procedure

1. **Resolve version.** Call `sdlc_get_version` MCP tool to retrieve the latest cc-sdlc release tag. Store as `SDLC_VERSION`. This tag is embedded in all seeded entries as `sdlc:seed-version:{SDLC_VERSION}`.

2. **Filter knowledge files.** From the set of knowledge YAMLs upstream provides, exclude:
   - `knowledge/agent-context-map.yaml` — configuration file, not knowledge content
   - `knowledge/provenance_log.md` — create empty template on filesystem only
   - `knowledge/README.md` and subdirectory READMEs — documentation only

3. **Evaluate applicability.** For each knowledge YAML, check its `project_applicability.relevant_when` field against the project profile. Apply `action_if_irrelevant`: `keep` (seed regardless), `customize` (rewrite for project stack), `remove` (skip entirely).

4. **Batch-ingest via `document_ingest_batch`.** Groups of up to 50 documents per call. Each document must include:

   | Field | Value |
   |-------|-------|
   | `title` | Entry name or filename |
   | `content` | YAML text content |
   | `source_type` | `"sdlc_knowledge"` |
   | `format` | `"yaml"` for knowledge stores, `"markdown"` for discipline files |
   | `version` | `{SDLC_VERSION}` |
   | `knowledge_id` | YAML `id` field; fallback `{filename}:{entry_index}` |
   | `tags` | See tag schema below |
   | `importance` | From YAML `importance` field, or `0.7` default |

5. **Tag construction per entry:**

   ```
   sdlc:knowledge                          # Always present
   sdlc:seed                               # Always present (marks as seed entry)
   sdlc:seed-version:{SDLC_VERSION}        # Always present
   sdlc:pattern:{pattern}                  # From YAML: entries | gotchas | rules | methodology
   sdlc:domain:{domain}                    # From YAML domain field
   sdlc:type:{type}                        # From YAML type field if present
   ```

6. **`knowledge_id` is mandatory.** Omitting it breaks idempotent upsert on re-initialization. Do NOT manually add `sdlc:knowledge-id:{id}` to tags — the server creates it automatically.

7. **Discipline seeding.** Discipline files are also ingested (not written as flat files):

   | Content Type | Tags | `knowledge_id` |
   |--------------|------|----------------|
   | Framework section | `sdlc:discipline:{name}`, `sdlc:seed`, `sdlc:seed-version:{v}` | `discipline:{name}:framework` |

8. **Spec-relevant importance boost.** After base seeding, prompt CD to select which domains inform spec writing. For selected domains, call `document_ingest_batch` to update matching entries' `importance` to `0.9`.

9. **Sentinel note.** The sentinel memory is managed server-side by `seed()`. Do NOT create or update it via `document_ingest`. Verify via `memory_search(query="SDLC workspace sentinel", tags=["sdlc:sentinel"])` after seeding.

10. **Error handling.** If batch response shows `summary.errors > 0`, log each failure. If more than 10% of entries errored, halt.

### Post-seed: Domain tag verification

After seeding completes, verify domain routing works for each created agent:

```
memory_search(query="SDLC knowledge entries", tags=["sdlc:domain:{domain}"])
```

This confirms agents can find their relevant knowledge via tag-scoped queries.

---

## knowledge-update
**On failure:** halt

Update the Neuroloom knowledge layer using server-side idempotent upsert. No flat files are created, diffed, or cleaned up.

### Procedure

1. **Resolve version.** Call `sdlc_get_version` to get the latest release tag → `LATEST_VERSION`.

2. **Build the change manifest.** For each `knowledge_id` in the new upstream release, compare against workspace entries:

   | Category | Detection |
   |----------|-----------|
   | New | `knowledge_id` not found in workspace |
   | Updated | `knowledge_id` exists, content differs |
   | Unchanged | `knowledge_id` exists, content identical |
   | Deprecated | `knowledge_id` present in workspace, absent from new release |

3. **Upsert new and changed entries.** Call `document_ingest_batch` with only the New + Updated entries. Batch in groups of up to 50.

   Each document must include:
   - `knowledge_id` — stable ID from initialization (mandatory — omitting breaks upsert)
   - `version` — `{LATEST_VERSION}`
   - `source_type` — `"sdlc_knowledge"`
   - `format` — `"yaml"` or `"markdown"`
   - `tags` — `["sdlc:knowledge", "sdlc:seed", "sdlc:seed-version:{LATEST_VERSION}"]` plus domain/type tags

   Do NOT manually add `sdlc:knowledge-id:{id}` to tags.

4. **Server handles migration cases:**
   - New entries → created with new version tag
   - Changed entries → content updated, version tag updated, importance preserved
   - Unchanged entries → no-op (not sent)
   - Removed entries → tagged `sdlc:deprecated` server-side (never deleted)
   - Project-specific entries (`sdlc:project-specific` tag) → never modified

5. **Discipline re-seed.** Same diff-then-send logic. `knowledge_id = discipline:{name}:framework`. Only New + Updated discipline frameworks are sent. Parking-lot entries (tagged `sdlc:parking-lot`) and promoted entries (tagged `sdlc:project-specific`) are never touched.

6. **Sentinel management.** The sentinel is read-only during migration — the server updates its `sdlc:seed-version:{version}` tag automatically when the knowledge re-seed completes. Do NOT write to the sentinel directly.

7. **Verify after re-seed (updated disciplines only):**
   ```
   memory_search(query="{discipline-name} framework methodology",
                 tags=["sdlc:discipline:{name}", "sdlc:seed-version:{LATEST_VERSION}"])
   ```
   Should return upstream framework content with new version tag. Separate search for `sdlc:parking-lot` should still return project entries.

8. **Knowledge layer spot-check.** Sample 3–5 entries from the change manifest that were expected to change. Call `memory_search` and verify the content matches the new upstream version and `sdlc:seed-version:{LATEST_VERSION}` tag is present.

9. **Error handling.** If `summary.errors > 0`, log failed entries. Do not abort — continue to post-file-write phase. Report errors in the final migration report.

---

## post-file-write
**On failure:** halt
**Applies to:** `[sdlc-root]/**/*.md`, `.claude/agents/*.md`, `.claude/skills/*/SKILL.md`, `.claude/skills/*/references/*.md`
**Skip:** `[sdlc-root]/knowledge/**/*.yaml`

Dispatch the `neuroloom-transformer` agent with the full list of written files. The agent handles the entire transformation pipeline (two-pass Pattern Mapping, MCP preservation gate, five verification audits) and returns an aggregate pass/fail report.

### Dispatch

```
Dispatch: neuroloom-transformer
Input:
  files: [list of all file paths written by upstream in this phase]
  operation: "initialize" | "migrate"
  sdlc_root: "{detected SDLC root path}"
  run_id: "{current transaction log run_id}"
```

The agent reads `${CLAUDE_PLUGIN_ROOT}/references/pattern-mapping-rules.md` and `${CLAUDE_PLUGIN_ROOT}/references/content-merge-audits.md` as its reference material. It processes all files, emits per-file transaction log events, runs the seven verification audits (Structural Content-Loss, PROJECT-SECTION Preservation, MCP Retention, Stale Agent Reference, Contract Residue, Telemetry Sanity, Concept-Terminology Residue), and returns a structured report.

**If the agent reports HALT** → this phase fails. Upstream stops the migration/initialization per the `On failure: halt` directive.

**If the agent reports PASS** → proceed to the **mandatory post-transformer steps** below IN ORDER, then return control to upstream. All steps marked "(initialize and migrate)" MUST execute on every operation — skipping any step is a regression that surfaces as missing wiring or stale docs on next skill invocation.

### Agent tool injection (initialize and migrate)

After the transformer completes Pattern Mapping, ensure all agent files in `.claude/agents/*.md` have the correct Neuroloom MCP tools in their frontmatter. Read `${CLAUDE_PLUGIN_ROOT}/transforms.yaml` for tool profiles and agent-to-profile mappings.

For each agent file:
1. Look up the agent's name in `transforms.yaml → agent_profiles` (default: `full`)
2. Resolve to the tool list from `tool_profiles`
3. If the agent's `tools:` frontmatter line is missing any declared tools, append them

This runs on EVERY migration (not just init) to catch agents that were created before the plugin was installed or before tool profiles were defined. It's idempotent — agents that already have the correct tools are unchanged.

### Adapter content injection (initialize only)

After the transformer completes, inject the Neuroloom Tool Usage section into `CLAUDE.md` if not present:

```markdown
## Neuroloom Tool Usage

All agents with Neuroloom tools follow these patterns:

- **Task start**: `memory_search` with domain-relevant query before substantive work
- **Before modifying key files**: `memory_by_file` on the 1-3 central files (skip new/config files)
- **Deep dive**: `memory_get_detail` when a search result needs full narrative, relationships and source files
- **Code understanding**: `code_search` (grep replacement for semantic symbol lookup), `code_context` (call chain + linked memories), `code_callers`/`code_callees` (trace a function's calls in & out), `code_navigate` (1-hop graph of a symbol's relationships)
- **After decisions/discoveries**: `memory_store` for design decisions, non-obvious patterns/gotchas, bug root causes, undocumented external API behavior. Do NOT store routine implementation details.
- **Feedback**: `memory_rate` positively when a memory answered a question or saved you from a mistake, negatively when outdated/wrong. Skip if merely irrelevant.
```

### Skill transform wiring (initialize and migrate — MANDATORY)

**This step is MANDATORY on every migration, not just initialization.** Upstream's direct-copy overwrites skill files with upstream versions that lack the `## Neuroloom Post-Execution Transform` section. Without re-wiring, skills created or modified after migration won't trigger the transformer, causing silent regression in all future agent-creation and knowledge-ingestion operations.

After the transformer completes on the batch of operational files, wire post-execution transforms into installed skills. Read `${CLAUDE_PLUGIN_ROOT}/transforms.yaml` — for each entry, inject a dispatch instruction at the end of the target skill's SKILL.md so the skill itself triggers the transformer after it runs.

**What gets injected (appended before the skill's `## Integration` section):**

```markdown
## Neuroloom Post-Execution Transform

After this skill completes its work, dispatch the `neuroloom-transformer` agent to apply Neuroloom-specific augmentation to the output files.

**Dispatch:**
- files: [target_patterns from transforms.yaml, resolved against project root]
- operation: "transform"
- actions: [actions list from transforms.yaml]

The transformer reads `${CLAUDE_PLUGIN_ROOT}/references/pattern-mapping-rules.md` and applies the declared actions to matching files.
```

**`path_pairs` dispatch shape (added for `sdlc-archive` — the exception to the `files:` glob shape above):**

The `files:` field above works because every other wired skill's target files still exist at a discoverable path when the transformer runs — `target_patterns` resolves to a live glob. `sdlc-archive` breaks that assumption: by the time its Step 5 (Archive Deliverables, copy-then-delete — not `git mv`) has run, the pre-move path no longer exists on disk, so a glob can't recover it. The skill already knows both paths (it read the file from the pre-move path before copying it to the post-move path), so it must pass them explicitly instead of relying on glob resolution.

When a `transforms.yaml` entry declares `dispatch_mode: path_pairs` (currently only `sdlc-archive`), the injected section replaces the `files:` line with a `path_pairs:` line, and the skill collects the pairs itself over the course of its own run rather than the transformer resolving them:

```markdown
## Neuroloom Post-Execution Transform

After this skill completes its work, dispatch the `neuroloom-transformer` agent to apply Neuroloom-specific augmentation to the output files.

**Dispatch:**
- path_pairs: [{old: pre-move path, new: post-move path} for every deliverable doc archived in this run — collect from Step 5's approval table as each item is moved]
- operation: "transform"
- actions: [actions list from transforms.yaml]

The transformer reads `${CLAUDE_PLUGIN_ROOT}/references/pattern-mapping-rules.md` and applies the declared actions to the given path pairs.
```

All other action handlers (`inject_mcp_tools`, `ensure_mcp_tools`, `transform_knowledge_context`, `transform_communication_protocol`, `pattern_mapping`, `ingest_to_neuroloom`) are unaffected — they keep the `files:` glob shape. Only `sync_archive_status` reads `path_pairs`.

**The injected section is idempotent** — if the skill already contains a `## Neuroloom Post-Execution Transform` section, replace it (in case the transforms.yaml was updated between migrations). If the section is absent, inject it.

**Currently declared transforms** (see `${CLAUDE_PLUGIN_ROOT}/transforms.yaml`):

| Skill | Target | Actions |
|-------|--------|---------|
| `sdlc-create-agent` | `.claude/agents/*.md` | Inject MCP tools per agent's tool profile, transform Knowledge Context and Communication Protocol sections |
| `sdlc-create-agent` (ENRICH mode) | `.claude/agents/*.md` | Ensure MCP tools still present per profile, re-transform Knowledge Context and Communication Protocol |
| `sdlc-develop-skill` | `.claude/skills/*/SKILL.md` | Apply full two-pass Pattern Mapping pipeline |
| `sdlc-ingest` | `[sdlc-root]/knowledge/**/*.yaml`, `[sdlc-root]/disciplines/*.md` | Route to Neuroloom backend via `document_ingest_batch` instead of writing flat files |
| `sdlc-archive` | `path_pairs` (pre-move -> post-move, assembled by the skill, no glob) | Sync each archived doc's DocumentSource anchor via `PATCH /api/v1/documents/by-path` |

**Why wire at install/migrate time:** The skill becomes self-contained at runtime — it knows to dispatch the transformer without hooks, config lookups, or runtime adapter detection. Adding new skills to `transforms.yaml` takes effect on the next migration.

### Adapter-specific docs (initialize and migrate — MANDATORY)

Copy Neuroloom-specific process docs from the plugin into the project:
- `${CLAUDE_PLUGIN_ROOT}/docs/knowledge-routing.md` → `[sdlc-root]/process/knowledge-routing.md`

This overrides the upstream version with the Neuroloom-aware variant that documents `memory_search`/`memory_store` patterns instead of file-path routing. **This step is MANDATORY on every migration** because upstream's direct-copy (§2.1) overwrites the file with the file-mode original before post-file-write fires. Without re-applying, the project retains upstream's flat-file knowledge-routing doc, which tells agents to use `[sdlc-root]/knowledge/agent-context-map.yaml` — a file that doesn't exist in Neuroloom projects.

**Verification:** After copying, diff the first 5 lines of `[sdlc-root]/process/knowledge-routing.md` against the plugin's version. If they don't match, the copy failed or was overwritten by a later step.

---

## post-operation
**On failure:** warn-continue

Run the shared post-operation audit to verify integration integrity after all mutations are complete.

### Procedure

Execute the checks documented in `${CLAUDE_PLUGIN_ROOT}/references/post-operation-audit.md`. Summary of required checks:

1. **MCP integration health** — count `memory_search(` + `memory_store(` across `[sdlc-root]/` and `.claude/agents/`. Verify minimum-MCP files each have at least one call. If any listed file has zero → REGRESSION.

2. **No residual cc-sdlc standard phrases** — grep for canonical phrasing-contract anchors (`consult [sdlc-root]/knowledge/agent-context-map.yaml`, etc.) outside the exemption list. Any hit → REGRESSION.

3. **No forbidden pre-contract phrasings** — grep for non-canonical variants (`Look up ... in`, `via [sdlc-root]/knowledge/`, etc.). Any hit → REGRESSION.

4. **No inline adapter conditionals** — grep for `(Neuroloom projects:`, `(skip for Neuroloom`, etc. Any hit → REGRESSION.

5. **Manifest integrity** — `.sdlc-manifest.json` valid JSON, required fields present, `neuroloom_backend: true`, `workspace_id` populated. On initialize, inject `neuroloom_backend: true` and `workspace_id` (from the Neuroloom API sentinel response) into the manifest after upstream writes it.

6. **Knowledge layer reachable** — `memory_search(query="SDLC workspace sentinel", tags=["sdlc:sentinel"])` returns exactly one result with current version tag.

7. **No stale agent-context-map** — verify `[sdlc-root]/knowledge/agent-context-map.yaml` does not exist as a live config file.

8. **Skill transform wiring intact** — for each skill listed in `${CLAUDE_PLUGIN_ROOT}/transforms.yaml`, verify the installed skill file contains a `## Neuroloom Post-Execution Transform` section. If any declared skill is missing its wiring → REGRESSION (the mandatory skill-transform-wiring step in post-file-write was skipped).

9. **Knowledge-routing.md is Neuroloom-aware** — verify `[sdlc-root]/process/knowledge-routing.md` contains `memory_search` or `memory_store` (the Neuroloom-aware version). If it contains `agent-context-map.yaml` as a live reference without MCP equivalents → REGRESSION (the adapter-specific docs copy was skipped or overwritten).

### Telemetry assertion (migrate only)

Before post-operation checks, assert Stage 4.2 telemetry is intact. This is hard-blocking — do not emit `run_complete` until all assertions pass:

1. Count `file_merged` events for current `run_id` = number of operational files written
2. Count `concept_terminology_applied` events = `file_merged` count (Pass 2 fires for every file)
3. Exactly one `mcp_retention_audit_complete` event with `audit_result: "PASS"`
4. Exactly one `structural_audit_complete` event with all six structural counts present per file
5. Exactly one `agent_resolution_audit_complete` event
6. Exactly one `contract_residue_audit_complete` event
7. Every exempt file emitted `file_merged` with `subtype: "exempt_verbatim"` (any other subtype = regression)
8. Zero unresolved `transformation_warning` events

If any assertion fails → emit `TELEMETRY REGRESSION` halt. Do not paper over with after-the-fact reconstructed events.

### Operation-specific additions

**After `/sdlc-initialize`:**
- Project agents created (more than just framework agents in `.claude/agents/`)
- First-run sentinel exists via `memory_search`
- Agent frontmatter contains Neuroloom MCP tools
- Agent template transformed for future agent creation

**After `/sdlc-migrate`:**
- `source_version` in manifest equals the target (not pre-migration version)
- PROJECT-SECTION markers preserved (spot-check from transaction log)
- Any `[contract-change]` entries in range were resolved (via upstream's guarded rename logic)
- Sentinel version tag matches `LATEST_VERSION` (server updates it after re-seed)

### Failure handling

Collect all check results. If any check returns REGRESSION:
- Log each regression with file, line, and pattern
- Report all regressions to the user in a structured list
- This phase uses `warn-continue` — upstream continues to manifest update and user report, but the report includes the regression findings prominently

### Recovery on failure

If post-operation finds regressions in a migration:
- Operational layer: `git checkout -- .claude/` (migration is uncommitted)
- Knowledge layer: re-run `/sdlc-migrate` — idempotent upsert will re-apply correctly
- For detailed recovery procedures: see `${CLAUDE_PLUGIN_ROOT}/references/recovery-procedures.md`
