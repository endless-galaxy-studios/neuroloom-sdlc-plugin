---
name: sdlc-port
description: >
  Migrates an existing local cc-sdlc installation to use Neuroloom as the backend. Reads local
  knowledge stores, discipline files, and deliverable docs; ingests them into Neuroloom via batch
  ingestion; then transforms agent and skill files to use semantic search instead of local file reads.
  Triggers on "port sdlc to neuroloom", "migrate local sdlc", "move sdlc to backend",
  "port my knowledge to neuroloom", "migrate my existing sdlc to neuroloom".
  Do NOT use for fresh installation without an existing local cc-sdlc — use sdlc-initialize instead.
  Do NOT use for updating an already-ported Neuroloom workspace to a newer cc-sdlc version — use sdlc-migrate.
---

# SDLC Port

Port an existing local cc-sdlc installation to use Neuroloom as the backend. This skill reads all
local knowledge stores, discipline files, and deliverable docs, ingests them into Neuroloom via
batch ingestion, transforms agent and skill files to replace local file-read patterns with
`memory_search` calls, and writes a manifest marking the workspace as ported.

Run this once on a project that already has cc-sdlc installed locally (`ops/sdlc/` present). For a
project that has never had cc-sdlc, run `/sdlc-initialize` instead. For updating an already-ported
workspace to a newer cc-sdlc release, run `/sdlc-migrate` instead.

---

## Mode Detection

Before executing any stage, determine which mode applies.

| State | Mode | Action |
|-------|------|--------|
| `ops/sdlc/` exists, no sentinel, no manifest with `neuroloom_backend: true` | **Fresh port** | Full port flow (Stages 1-5) |
| Sentinel found OR manifest has `neuroloom_backend: true` | **Re-port** | Confirm via AskUserQuestion, then full flow |
| Sentinel found but seeded count < local file count | **Partial port** | Resume from Stage 3; re-ingest all content |

Detect the sentinel via:
```
memory_search(query="SDLC workspace sentinel", tags=["sdlc:sentinel"])
```

Detect manifest state by reading `.sdlc-manifest.json` at the project root (if it exists) and
checking whether `neuroloom_backend` equals `true`.

In **Partial port** mode, inform the user which batch failed and resume from Stage 3 without a new
confirmation gate — the user already confirmed once.

---

## Stage 1 — Pre-flight and Inventory

### Gate 1: Local cc-sdlc installation exists

Check whether `ops/sdlc/` is present in the project root. If absent, stop and output:

```
No cc-sdlc installation found. Run /sdlc-initialize instead.
```

Do not proceed.

### Gate 2: Neuroloom API is reachable

Call `sdlc_get_version` as a dedicated connectivity and authentication check. If it fails with an authentication error, output:

```
Neuroloom API authentication failed. Verify your API key is set and valid.
```

If it fails with a network error, output:

```
Neuroloom API unreachable. Check your network connection and API URL configuration.
```

Stop in both cases. Do not proceed to Gate 3 or Stage 2.

Store the returned version as `CURRENT_SDLC_VERSION` for use in the manifest (Stage 5).

### Gate 3: Check for existing port

Run the sentinel search and check `.sdlc-manifest.json`:

```
memory_search(query="SDLC workspace sentinel", tags=["sdlc:sentinel"])
```

If either the sentinel is found or the manifest contains `neuroloom_backend: true`, this is a
**Re-port**. Use `AskUserQuestion` before continuing:

```
This workspace has already been ported to Neuroloom (ported at {ported_at}).
Re-porting re-ingests all content from local files, overwriting any updates made
directly in Neuroloom since the last port.
```

Options:
1. Re-port (re-sync all content from local files, update manifest)
2. Cancel

If the user cancels, stop. Do not write anything.

### Inventory

After all three gates pass, run the extraction script in dry-run mode to get knowledge/discipline
entry counts, then glob deliverable docs and agent/skill files separately:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/extract_sdlc_knowledge.py" --dry-run
```

This prints a summary to stderr with the total entry count (knowledge YAML + discipline entries
combined). Parse the summary for the counts. Show zero-count rows for empty categories.

For deliverable docs and agent/skill files, glob and count files:

| Category | Glob | What to count |
|----------|------|---------------|
| Deliverable docs | `docs/current_work/**/*.md` + `docs/chronicle/**/*.md` | Files |
| Agent/skill files | `.claude/agents/*.md` + `.claude/skills/**/*.md` | Files (transformation targets) |

---

## Stage 2 — Confirmation Gate

Present the inventory summary. Do not begin any writes until the user confirms.

```
cc-sdlc installation found. Ready to port to Neuroloom.

  Knowledge files:    {N} files, {M} entries
  Discipline files:   {N} files, {M} entries
  Deliverable docs:   {N} files
  Agent/skill files:  {N} files (transformation targets)

This will ingest all content into Neuroloom and modify agent/skill files to use
semantic search. Original files are recoverable via git checkout.
```

Use `AskUserQuestion` with options:
1. Proceed with port
2. Cancel

Do not proceed past this gate without explicit confirmation.

---

## Stage 3 — Knowledge Ingestion

Ingest SDLC knowledge and discipline files into Neuroloom via `sdlc_seed` (Stage 3a),
then ingest deliverable docs via the file-based batch ingestion tools (Stage 3b). Report
progress between stages. Do not begin Stage 3b if Stage 3a fails.

### Stage 3a — SDLC Knowledge via `sdlc_seed`

Use the extraction script to generate the seed file, then use the appropriate seed tool to
ingest it. Do NOT manually construct entries or write custom extraction scripts — the
extraction script already handles all knowledge YAML parsing, discipline file parsing, tag
derivation, and entry construction.

**Step 1 — Generate the seed file:**

```bash
python "${CLAUDE_SKILL_DIR}/scripts/extract_sdlc_knowledge.py" --version "{CURRENT_SDLC_VERSION}" --output /tmp/sdlc_seed.json
```

This produces a JSON file with `{"entries": [...], "version": "..."}` containing all knowledge
YAML entries AND discipline entries combined. The script handles all entry construction
including `knowledge_id`, tags, importance, concepts, and source paths.

**Step 2 — Ingest the seed file:**

The tool to use depends on transport mode:

- **stdio mode:** Use `sdlc_seed_from_file(path="/tmp/sdlc_seed.json")`
- **HTTP mode:** Use `sdlc_seed_get_upload_url(path="/tmp/sdlc_seed.json")`, then run the
  returned `curl_command` via Bash

Both tools return the same response shape:
```json
{
  "created": N, "updated": N, "unchanged": N, "deprecated": N
}
```

Check for API error keys (`"error"`) on the response. If present, log the error message
and stop — do not continue to Stage 3b (deliverable docs ingestion). Stage 3 is not
partially recoverable if `sdlc_seed` fails (stop on failure — this is not retryable in
the same way as Stage 3b).

**Deduplication:** `sdlc_seed` matches entries by `knowledge_id` server-side.
Re-porting is safe — identical entries produce "unchanged" counts, not duplicates. This
replaces the prior duplicate risk from `document_ingest_batch` which had no `knowledge_id`
upsert guarantee for discipline files.

### Stage 3b — Deliverable Docs

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
- `tags` — derive from filename:
  - `sdlc:deliverable:spec:{id}` from `_spec.md` (e.g., `d12_foo_spec.md` → `sdlc:deliverable:spec:d12`)
  - `sdlc:deliverable:plan:{id}` from `_plan.md`
  - `sdlc:deliverable:result:{id}` from `_result.md`
  - `sdlc:chronicle:{concept}` from `_COMPLETE.md` in `docs/chronicle/` (derive concept from the directory or filename slug)
  - Where `{id}` is extracted from the `d(\d+[a-z]?)_` pattern in the filename

---

## Stage 4 — Transformation

Transform agent files, skill files, reference docs, and the agent template to replace local
`ops/sdlc/knowledge/` file-read patterns and bare YAML filename references with `memory_search`
calls. This stage has five sub-steps.

### Stage 4a — Identify Targets

Scan all files matched by `.claude/agents/*.md`, `.claude/skills/**/*.md`, and
`.claude/skills/*/references/*.md` for TWO categories of references:

1. **Path references**: `ops/sdlc/knowledge/` paths and `ops/sdlc/disciplines/` paths —
   any instruction to read, load, or consult a file at either path.
2. **Named YAML references**: bare references to `agent-context-map.yaml` or
   `agent-communication-protocol.yaml` — even without the full path prefix. These appear
   in validation checklists, maturity criteria, integration steps, and template instructions.

Also scan `ops/sdlc/templates/agent-template.md` — it contains runtime instructions
(Knowledge Context, Communication Protocol) that direct agents to read local YAML files.

For each reference found, call `memory_search` to locate the matching seeded entry:
```
memory_search(query="{semantic description of the referenced content}", tags=["sdlc:knowledge"])
```

Build a mapping:
```
{file_path} → [{old_reference} → {proposed memory_search call or updated instruction}]
```

Files with no matching references are not transformation targets — skip them.

**What to transform:**
- Agent files: instructions to read `ops/sdlc/knowledge/agent-context-map.yaml`, discipline files,
  or process docs
- Skill files: only those that directly reference local knowledge paths (verify before including)
- Process docs: file-write patterns for discipline entries that should become `memory_store` calls
- **Validation checklists** (e.g., sdlc-reviewer agent): checklist items that validate agents
  "reference `agent-context-map.yaml`" or "reference `agent-communication-protocol.yaml`" →
  update to check for `memory_search` calls in Knowledge Context and Communication Protocol sections
- **Agent template** (`ops/sdlc/templates/agent-template.md`): Knowledge Context and Communication
  Protocol sections that instruct agents to read local YAML files → update to use `memory_search`.
  Also update the "Surfacing Learnings" parenthetical `(see agent-communication-protocol.yaml)` →
  `(retrievable via memory_search)`
- **Skill integration steps** (e.g., sdlc-create-agent): steps that say "update
  `agent-context-map.yaml`" → update to reflect Neuroloom as the knowledge backend
- **Compliance/audit methodology** (e.g., compliance-methodology.md): maturity level criteria and
  wiring tier descriptions that reference `agent-context-map` as a concept → update to reference
  Neuroloom retrieval
- **`process/knowledge-routing.md`**: file-path references to `ops/sdlc/knowledge/` lookup
  patterns → replace with `memory_search()` calls. The target state is the Neuroloom variant at
  `neuroloom-sdlc-plugin/docs/knowledge-routing.md`

**What NOT to transform:**
- Template structural scaffolding in `ops/sdlc/templates/` (section headers, placeholder text) —
  only transform runtime instructions within templates (Knowledge Context, Communication Protocol)
- `docs/_index.md` — remains filesystem-local
- Agent or skill files with no matching references
- Historical changelog entries in `ops/sdlc/process/sdlc_changelog.md` — these are an accurate
  record of what happened at the time and must not be rewritten
- `ops/sdlc/knowledge/provenance_log.md` — project-specific append-only record; relocate with
  other files in Stage 4f, do not transform or ingest

**Project-specific files to preserve during relocation:**
- `process/agent-selection.yaml` — project's agent roster and dispatch rules; relocate but never
  overwrite during future migrations
- `knowledge/provenance_log.md` — project's ingestion/research lineage log; relocate but never
  ingest into knowledge layer

### Stage 4b — Present Proposed Changes

Show the full list before applying any change. Use this format:

```
Proposed transformations ({K} files):

  .claude/agents/software-architect.md
    ops/sdlc/knowledge/architecture-patterns.yaml
    -> memory_search(query="architecture patterns", tags=["sdlc:knowledge", "sdlc:domain:architecture"])

  .claude/skills/sdlc-plan/SKILL.md
    ops/sdlc/knowledge/gotchas.yaml
    -> memory_search(query="SDLC gotchas", tags=["sdlc:knowledge", "sdlc:type:gotcha"])
  ...
```

Use `AskUserQuestion` with options:
1. Apply all transformations
2. Skip transformations (port without modifying agent/skill files)
3. Cancel port

If the user skips or cancels here, all content seeded in Stage 3 is retained. The user can re-run
`/sdlc-port` to retry transformations without re-ingesting (Stage 3 will upsert unchanged entries).

### Stage 4c — Apply Transformations

**Subagent permissions caveat:**

If you dispatch subagents to perform file transformations, they may not have
Edit tool permissions approved for the target project. If a transformation
subagent returns without making changes due to permission denial, do not
re-dispatch — fall back to performing transformations directly. The
transformations are templated string replacements (not creative edits) and
are safe for the main agent to execute in bulk.

Alternatively, perform all Stage 4 transformations directly rather than
dispatching subagents. The batch-replacement pattern (identify common
boilerplate → replace across all matching files) is efficient enough that
subagent parallelism provides minimal benefit.

After confirmation, apply replacements using the Edit tool. Transformations are LLM-driven: the
replacement `memory_search` call must preserve the surrounding context and intent of the original
file-read instruction. A single file-read may map to multiple `memory_search` calls if it covered
multiple knowledge domains.

Every replacement `memory_search` call must include an explicit `query` string. A tags-only call
is invalid — `query` is required.

Example replacement:

Before:
```
Read ops/sdlc/knowledge/developer-documentation-patterns.yaml for DX heuristics.
```

After:
```
Call memory_search(query="developer documentation DX heuristics", tags=["sdlc:knowledge", "sdlc:domain:design"])
to retrieve current documentation patterns.
```

**Distinct queries per reference:**

When a single agent or skill file contains multiple `ops/sdlc/knowledge/` (or
`ops/sdlc/disciplines/`) references, every replacement `memory_search` call must
use a distinct query string that accurately reflects the specific knowledge concept
being retrieved. Do NOT reuse the same query string across multiple replacements in
the same file or across files.

Examples of distinct queries for different concepts:
- `"chaos hypothesis fault injection patterns"` (for chaos engineering guidance)
- `"feature flag isolation test configuration"` (for feature flag testing patterns)
- `"backend service integration test setup"` (for service integration test setup)

A tags-only or near-identical query is not acceptable — it produces ambiguous
retrieval results that defeat the purpose of semantic search.

**Shared references across agents:**

References that appear in many agent files (e.g., communication protocol,
investigation report format) still require per-agent differentiation. These
references typically have agent-specific instantiation parameters (section
order, severity vocabulary, field names). Include the agent name in the query:

- `"agent communication protocol structured progress handoff format for code-reviewer"`
- `"investigation report format section order severity for accessibility-auditor"`
- `"agent communication protocol structured progress handoff format for sdet"`

Do NOT use the same query string across all agents that share a reference —
even if the reference file is the same, each agent's instantiation context
differs, and the query should reflect that to improve retrieval relevance.

### Stage 4d — Validate Transformations

After all edits, verify each transformed file:
- No remaining `ops/sdlc/knowledge/` or `ops/sdlc/disciplines/` path references
- No remaining bare `agent-context-map.yaml` or `agent-communication-protocol.yaml` references
  (except in historical changelog entries, which are preserved as-is)
- Every replacement `memory_search` call includes `query`
- File is still valid markdown (no broken code fences or truncated sections)

If validation fails for a file, restore it via:
```
git checkout .claude/agents/{specific_file}.md
```
or
```
git checkout .claude/skills/{specific_skill}/SKILL.md
```

List specific file paths — do NOT run `git checkout .claude/` as that restores all files including
user-created agents that were never touched.

### Stage 4e — Remove cc-sdlc Originals for Plugin-Owned Skills

The Neuroloom SDLC plugin provides its own versions of `sdlc-initialize` and
`sdlc-migrate`. The cc-sdlc originals placed by framework installation in
`.claude/skills/sdlc-initialize/` and `.claude/skills/sdlc-migrate/` must be
removed to prevent skill resolution conflicts.

Run without asking for confirmation:
```
rm -rf .claude/skills/sdlc-initialize/ .claude/skills/sdlc-migrate/
```

Do NOT ask whether to remove these directories — this is automatic cleanup, not a user decision.

Do NOT remove skill directories from `neuroloom-sdlc-plugin/skills/` — those are the plugin's own skill definitions and are never touched by this skill.

**Do NOT remove** any other skill directories from `.claude/skills/`. All other
cc-sdlc skills remain active and are not replaced by the plugin.

### Stage 4f — Relocate Operational SDLC Directories

Move the six operational SDLC directories from `ops/sdlc/` to `.claude/sdlc/`. Run without asking
for confirmation — this is part of the automatic post-transformation cleanup, same as Stage 4e.

**Scope:** Only the six directories listed below. `ops/sdlc/knowledge/` and `ops/sdlc/disciplines/`
are managed by Stage 3 ingestion and Post-Port Cleanup — not Stage 4f. `docs/_index.md` remains
at its current path.

**Step 1 — Create target directory:**

```bash
mkdir -p .claude/sdlc/
```

**Step 2 — Move directories (re-port collision guard):**

Check whether `.claude/sdlc/process/` already exists. If ANY target directory pre-exists, use
rsync+rm for ALL directories:

```bash
rsync -a ops/sdlc/process/ .claude/sdlc/process/ && rm -rf ops/sdlc/process
rsync -a ops/sdlc/templates/ .claude/sdlc/templates/ && rm -rf ops/sdlc/templates
rsync -a ops/sdlc/playbooks/ .claude/sdlc/playbooks/ && rm -rf ops/sdlc/playbooks
rsync -a ops/sdlc/examples/ .claude/sdlc/examples/ && rm -rf ops/sdlc/examples
rsync -a ops/sdlc/plugins/ .claude/sdlc/plugins/ && rm -rf ops/sdlc/plugins
rsync -a ops/sdlc/improvement-ideas/ .claude/sdlc/improvement-ideas/ && rm -rf ops/sdlc/improvement-ideas
```

On fresh port (no target dirs exist), use plain `mv`:

```bash
mv ops/sdlc/process .claude/sdlc/process
mv ops/sdlc/templates .claude/sdlc/templates
mv ops/sdlc/playbooks .claude/sdlc/playbooks
mv ops/sdlc/examples .claude/sdlc/examples
mv ops/sdlc/plugins .claude/sdlc/plugins
mv ops/sdlc/improvement-ideas .claude/sdlc/improvement-ideas
```

**Step 3 — Remap path references:**

After moving, remap the following path prefixes in all transformed files:

| Old path | New path |
|----------|----------|
| `ops/sdlc/process/` | `.claude/sdlc/process/` |
| `ops/sdlc/templates/` | `.claude/sdlc/templates/` |
| `ops/sdlc/playbooks/` | `.claude/sdlc/playbooks/` |
| `ops/sdlc/examples/` | `.claude/sdlc/examples/` |
| `ops/sdlc/plugins/` | `.claude/sdlc/plugins/` |
| `ops/sdlc/improvement-ideas/` | `.claude/sdlc/improvement-ideas/` |

**Exclusions from remapping:**
- Lines matching `~/src/ops/sdlc/` — upstream cc-sdlc source paths, not local installation
- Historical entries in `sdlc_changelog.md`

### Stage 4g — Remap Agent Memory Files

Agent memory files (`.claude/agent-memory/*/*.md`) may contain stale `ops/sdlc/` references from
pre-port agent sessions. These are runtime hints agents wrote to self-load knowledge from the
filesystem. Post-port, knowledge lives in Neuroloom and operational directories have moved to
`.claude/sdlc/`.

**Step 1 — Scan for stale references:**

```bash
grep -rn "ops/sdlc/" .claude/agent-memory/ 2>/dev/null
```

If no matches found, skip to Stage 5.

**Step 2 — Classify and remap:**

Three categories of stale references exist in agent memory files:

| Category | Pattern | Replacement |
|----------|---------|-------------|
| Knowledge file paths | `ops/sdlc/knowledge/{path}.yaml` | Replace the file-read instruction with a `memory_search()` call using the knowledge content as the query and appropriate `sdlc:knowledge` tags |
| Discipline file paths | `ops/sdlc/disciplines/{name}.md` | Replace with `memory_search()` call using `tags=["sdlc:discipline:{domain}"]` |
| Structural references | `ops/sdlc/` referring to process, templates, or other relocated dirs | Replace `ops/sdlc/` with `.claude/sdlc/` |

For knowledge and discipline paths, the replacement follows the same `memory_search()` pattern used
in Stage 4c for agent files. Example:

Before:
```
General TypeScript patterns for type safety are in
`ops/sdlc/knowledge/coding/typescript-patterns.yaml`. Apply those patterns
when designing new types.
```

After:
```
General TypeScript patterns for type safety are retrievable via
memory_search(query="TypeScript type safety patterns", tags=["sdlc:knowledge", "sdlc:domain:coding"]).
Apply those patterns when designing new types.
```

For structural references, apply the same path substitution as Stage 4f:
```
ops/sdlc/process/   →  .claude/sdlc/process/
ops/sdlc/templates/ →  .claude/sdlc/templates/
ops/sdlc/           →  .claude/sdlc/  (when referring to the directory generally)
```

**Step 3 — Preserve historical context:**

Agent memory files that are clearly historical audit records or point-in-time observations (e.g.,
dated audit findings, migration reports) should be left as-is OR annotated with a brief header note
rather than rewritten. These are accurate records of past state.

Use judgment: if the memory is a **runtime instruction** ("load this file for context"), remap it.
If the memory is a **historical record** ("the audit on 2026-03-17 found X at ops/sdlc/..."), leave
it.

**Exclusions from remapping:**
- `sdlc_changelog.md` historical entries (if referenced)
- `~/src/ops/sdlc/` upstream cc-sdlc source refs

Run without asking for confirmation — this is automatic cleanup, same as Stage 4e and 4f.

---

## Stage 5 — Manifest and Verification

Manifest schema, verification checklist (19 checks across knowledge layer, path references, directories, and manifest), and final summary template: see `references/verification-manifest.md`.

## Verification Checklist (Summary)

Consolidated pass/fail checklist (14 items covering sentinel, knowledge, disciplines, deliverables, stale path refs, directories, manifest, agent memory): see `references/verification-manifest.md` § "Verification Checklist".

## Red Flags

Common anti-patterns and corrections (11 entries covering re-porting safety, transformation assumptions, sentinel lifecycle, seed tool selection): see `references/red-flags.md`.

## Integration

**Feeds in:**
- `ops/sdlc/knowledge/**/*.yaml` — local knowledge stores
- `ops/sdlc/disciplines/**/*.md` — local discipline files
- `docs/current_work/**/*.md` and `docs/chronicle/**/*.md` — deliverable docs
- `.claude/agents/*.md` and `.claude/skills/**/*.md` — transformation targets

**Feeds out:**
- Neuroloom knowledge entries (knowledge YAMLs, disciplines, deliverable docs)
- Transformed agent and skill files (local filesystem — `ops/sdlc/knowledge/` refs replaced)
- `.sdlc-manifest.json` (written at project root)
- Sentinel memory (managed server-side by `seed()` — not written by this skill)

**After port:**
- `sdlc-migrate` can update the workspace to newer cc-sdlc releases without re-porting
- The SessionStart hook (`hooks/session-start.sh`) begins checking versions against the manifest
- Agent files now retrieve knowledge via `memory_search` instead of local file reads

**Sibling skills:**
- `sdlc-initialize` — fresh install when no local cc-sdlc exists; handles Neuroloom seeding from scratch
- `sdlc-migrate` — updates an already-ported workspace to a newer cc-sdlc version; does not re-port

---

## Error Handling

Per-stage failure modes and recovery procedures (Stage 1 pre-flight, Stage 2 cancellation, Stage 3a/3b ingestion, Stage 4 transformation, Stage 5 manifest/verification): see `references/recovery-procedures.md`.

