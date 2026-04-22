---
name: sdlc-migrate
description: >
  Updates SDLC knowledge in a Neuroloom workspace to the latest cc-sdlc version. Compares the
  workspace's current seeded version against the latest upstream release, re-seeds changed entries,
  deprecates removed entries (without deleting them), updates the workspace sentinel, and applies
  content-aware operational file merges with PROJECT-SECTION marker preservation and Neuroloom-aware
  content transformation.
  Triggers on "migrate sdlc", "update sdlc knowledge", "upgrade sdlc version",
  "sdlc update available", "update the sdlc backend".
  Do NOT use for first-time workspace setup — use sdlc-initialize.
  Do NOT use for porting an existing local cc-sdlc installation to Neuroloom — use sdlc-port.
---

# SDLC Migrate

Apply cc-sdlc upstream updates to this Neuroloom workspace while preserving project-specific customizations. Unlike a raw re-initialization, this skill is **content-aware** — it understands the two-layer architecture and migrates each layer independently.

Run this when the `SessionStart` hook reports an update is available, or at any time to check for updates manually.

---

## Two-Layer Architecture

Every SDLC workspace has two independent layers. Both must be in sync with the same cc-sdlc version.

| Layer | What Lives Here | How Updated |
|-------|----------------|-------------|
| **Knowledge layer** (Neuroloom API) | Knowledge YAMLs, discipline entries, deliverable doc templates | `document_ingest_batch` MCP tool with `knowledge_id` for server-side upsert |
| **Operational layer** (filesystem) | Skills, agents, process docs, templates, `CLAUDE.md`, `.sdlc-manifest.json`, `hooks/` files | Direct file writes via Write/Edit tools |

**Both layers must be updated together.** Knowledge current but skills stale causes tool failures. Skills current but knowledge stale produces outdated guidance. If one layer is already at the target version, update only the other — but always verify both are current before reporting success.

---

## PROJECT-SECTION Marker Convention

Framework files (skills, process docs) may contain `PROJECT-SECTION` markers that protect project-specific content across migrations. This skill is responsible for **consuming** markers: extracting, preserving, and re-injecting marked blocks during framework updates.

**Marker format:**
```html
<!-- PROJECT-SECTION-START: descriptive-label -->
... project content ...
<!-- PROJECT-SECTION-END: descriptive-label -->
```

**During any operational file overwrite:**
1. Scan the project's current version for `PROJECT-SECTION-START` / `PROJECT-SECTION-END` marker pairs
2. Extract each marked block along with its label and the heading it appears under (nearest `#`/`##`/`###` above)
3. After copying the upstream file, re-inject each block at its original heading position
4. If the heading no longer exists in the upstream file, append the block at the end with a warning comment: `<!-- MIGRATION WARNING: heading "[heading]" no longer exists in upstream — block preserved at end of file -->`
5. Log all re-injected blocks in the migration report

**When to skip marker review:**
- If the project has no markers (first migration, or project never customized framework files)
- If a block is < 7 days old (parse date from label) — too recent to be stale

**Markers are only for process docs and skill files.** Knowledge YAMLs, discipline files, and agent-context-map are project-specific by nature and don't need markers.

---

## Project-Specific Files (Never Overwrite)

These files become project-specific after initialization. They must NOT be direct-copied during migration:

| File | Reason |
|------|--------|
| `process/agent-selection.yaml` | Project's agent roster and dispatch rules — contains project-specific agent names |
| `knowledge/agent-context-map.yaml` | Configuration file, not knowledge — already excluded from knowledge layer |
| `knowledge/provenance_log.md` | Project's append-only ingestion/research records |

---

## Neuroloom-Aware Content Transformation

When merging operational files, **preserve MCP tool calls** in framework content. The cc-sdlc source uses file path references (generic), but Neuroloom projects use MCP tools for knowledge access.

### Source of Truth: The Phrasing Contract

The pattern mapping below derives from cc-sdlc's phrasing contract, documented at [`cc-sdlc/process/knowledge-routing.md` § "Adapter Plugins and the Phrasing Contract"](https://github.com/Inpacchi/cc-sdlc/blob/main/process/knowledge-routing.md). That section lists the exact phrases cc-sdlc commits to using — every row in the table below transforms one of those phrases.

**When pulling a new cc-sdlc release:** Before applying the content-merge, scan the upstream changelog for entries tagged `[contract-change]` in the commit range being migrated (from current `sdlc:seed-version` to the new version). Any such entry indicates a new or modified standard phrase that may require an update to the Pattern Mapping table below. If the scan finds `[contract-change]` entries:

1. List them to the maintainer with a summary of what changed
2. Pause migration until the Pattern Mapping table below is updated
3. Only proceed once every new contract phrase has a corresponding transformation rule

### Pattern Mapping

> **How coverage actually works:** This table lists 5 explicit phrase-to-call mappings, but they cover only a fraction of real-world transformation sites. The vast majority of cc-sdlc files with knowledge references (skills, agents, process docs) are handled via the **section-level preservation rule** documented in "Content-Merge Rules for Neuroloom" below — scan each file for `memory_search(` / `memory_store(` presence and preserve those sections verbatim during merge. The explicit patterns below are what the transformer SEEKS during fresh installation (`/sdlc-initialize`) and during migration when a file has no prior MCP patterns. Once a file contains MCP calls, section-level preservation takes over.

| cc-sdlc Generic Pattern | Neuroloom Pattern (preserve if present) |
|-------------------------|----------------------------------------|
| `consult [sdlc-root]/knowledge/agent-context-map.yaml` | `memory_search(query="[agent-name] domain-specific patterns...", tags=["sdlc:knowledge"])` |
| `Read [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml` | `memory_search(query="agent communication protocol...", tags=["sdlc:knowledge", "sdlc:domain:architecture"])` |
| `Append to [sdlc-root]/disciplines/*.md` | `memory_store(tags=["sdlc:discipline:{name}", "sdlc:parking-lot"])` |
| `knowledge stores ([sdlc-root]/knowledge/)` | `Neuroloom knowledge store (via memory_store)` |
| `look up agent's mapped files from agent-context-map.yaml` | `memory_search(query="{agent-name} domain patterns", tags=["sdlc:knowledge"])` |

### Files Containing These Patterns

| File | Section | Pattern Type |
|------|---------|--------------|
| `agents/AGENT_TEMPLATE.md` | `## Knowledge Context` | Agent knowledge retrieval |
| `agents/AGENT_TEMPLATE.md` | `## Communication Protocol` | Protocol retrieval |
| `agents/AGENT_TEMPLATE.md` | "Surfacing Learnings" | Knowledge store reference |
| `agents/sdlc-compliance-auditor.md` | Methodology reference | Knowledge retrieval |
| `agents/sdlc-reviewer.md` | Agent wiring checklist | Knowledge wiring validation |
| `process/discipline_capture.md` | Agent knowledge lookup | Knowledge retrieval |
| `process/overview.md` | Knowledge capture | Knowledge store |
| `process/knowledge-routing.md` | Entire file (Neuroloom variant) | `memory_search` query patterns — if the installed version contains `memory_search(` calls, preserve the entire file verbatim; upstream has a file-based variant |
| `skills/sdlc-plan/SKILL.md` | Agent Selection / Cross-domain injection | `consult [sdlc-root]/knowledge/agent-context-map.yaml` phrases |
| `skills/sdlc-execute/SKILL.md` | Agent Dispatch Protocol / Cross-domain injection | `consult [sdlc-root]/knowledge/agent-context-map.yaml` phrases |
| `skills/sdlc-lite-execute/SKILL.md` | Cross-domain injection during phase dispatch | `consult [sdlc-root]/knowledge/agent-context-map.yaml` phrases |
| `skills/sdlc-tests-create/SKILL.md` | SDET cross-domain injection | `consult [sdlc-root]/knowledge/agent-context-map.yaml` phrases |
| `skills/sdlc-tests-run/SKILL.md` | Domain agent cross-domain injection during fixes | `consult [sdlc-root]/knowledge/agent-context-map.yaml` phrases |
| `skills/review-fix/SKILL.md` | Cross-domain injection when fixer differs from finder | `consult [sdlc-root]/knowledge/agent-context-map.yaml` phrases |
| `skills/team-review-fix/SKILL.md` | Reviewer spawn / fixer spawn knowledge context | `consult [sdlc-root]/knowledge/agent-context-map.yaml` phrases |
| `skills/sdlc-create-agent/SKILL.md` | Agent template Knowledge Context scaffolding | Generated agent `## Knowledge Context` section — must scaffold with `memory_search` for Neuroloom projects |
| `skills/sdlc-ingest/SKILL.md` | WIRE step (knowledge wiring to agent-context-map) | Wiring logic itself is skipped in Neuroloom — knowledge is stored with tags instead |
| `skills/sdlc-audit/references/compliance-methodology.md` | Dimension 6 (knowledge layer health), knowledge wiring validation | References `agent-context-map.yaml` concepts — checks must translate to memory-graph equivalents |
| `skills/sdlc-audit/references/improvement-methodology.md` | Knowledge gap identification | References knowledge store concepts |

### Content-Merge Rules for Neuroloom

1. **Detection heuristic:** Before merging any file listed above, scan the project's current version for `memory_search(` or `memory_store(`. If present, the project uses Neuroloom integration.

2. **Section-level preservation:** When merging a file with Neuroloom patterns:
   - Identify sections containing MCP tool calls (usually delimited by `##` headings)
   - Extract the project's MCP-based version of those sections
   - Apply upstream framework updates to sections WITHOUT MCP calls
   - Re-inject the project's MCP-based sections verbatim
   - Log: `Neuroloom pattern preserved: [file] § [section]`

3. **Per-file detection:** Even though this is a Neuroloom workspace, apply detection at file level before merging. Some files may have been added after the port and still use file path patterns. Only preserve MCP patterns where they actually exist.

4. **Reviewer checklist transformation:** The `sdlc-reviewer.md` contains checklists that validate knowledge wiring. Preserve: `Knowledge Context section includes a memory_search call`. Don't overwrite with: `Knowledge Context section references agent-context-map.yaml`.

5. **Agent template sections:** The `AGENT_TEMPLATE.md` drives new agent creation. Preserve: `call memory_search(query="[agent-name] domain-specific patterns...`. Don't overwrite with: `consult [sdlc-root]/knowledge/agent-context-map.yaml`.

**Why this matters:** Overwriting MCP tool calls with file path references breaks semantic search, cross-domain discovery, and context injection — the core value proposition of the Neuroloom backend.

---

## Stage 0 — Pre-Flight Health Check

**Before anything else**, run the shared pre-flight protocol at `${CLAUDE_PLUGIN_ROOT}/references/preflight.md`.

The protocol validates:
- Neuroloom API reachability and auth
- GitHub API reachability and rate limit
- Required MCP tools (`document_ingest_batch`, `memory_search`, `memory_store`, `sdlc_get_version`)
- Required CLI tools (`gh`, `git`, `jq`, `python3`)
- Sufficient disk space
- **Migrate-specific:** Sentinel present, manifest parseable, dirty-tree warning gate

**Failure policy:** Collect all failures and report together. Do not proceed on any hard failure. Preflight is read-only — failures leave no partial state.

Record the preflight result as the first entry in the transaction log.

Once preflight passes, continue to Stage 1 for migrate-specific state extraction.

---

## Transaction Log

Every stage start/end, gate decision, mutation, and failure writes an append-only JSONL entry to `.sdlc-transaction-log` in the project root. Full schema and event types are documented in `skills/sdlc-initialize/SKILL.md` § "Transaction Log" — this skill follows the same format.

**Run ID convention for migrate:** `migrate-{6-char-random-hex}` (e.g., `migrate-def456`).

**Migrate-specific events to log:**
- `contract_change_detected` — when Stage 2.2a identifies `[contract-change]` changelog entries
- `drift_detected` — when Stage 3.2a finds a drifted file (one entry per file)
- `drift_decision` — CD's choice at the drift gate (`overwrite`/`keep`/`extract_markers`)
- `discipline_reseed` — per-discipline framework section re-seed outcome
- `layer_skip` — when early-exit logic skips knowledge or operational stage

**Recovery from migrate crash:**
```
tail -n 50 .sdlc-transaction-log | jq 'select(.run_id | startswith("migrate-"))'
# Last mutation event = what was last committed
# Last stage_start without stage_end = crash point
# Search for drift_decision events to recover CD's intent on partial runs
```

---

## Transformation Warning Log

Content-merge operations (Stage 4.2) may encounter upstream patterns that look standard-phrase-adjacent but don't match any rule in the Pattern Mapping table. These surface as `TRANSFORMATION_WARNING` entries at `.sdlc-transformation-warnings.log`. Schema and review workflow are documented in `skills/sdlc-initialize/SKILL.md` § "Transformation Warning Log".

**Migrate-specific:** If a file was successfully transformed at init but the same phrase appears in a newer upstream version and doesn't match an updated rule, that's a signal the Pattern Mapping table is stale. Investigate whether the upstream changelog missed a `[contract-change]` tag — file an upstream issue if so.

---

## Stage 1 — State Extraction

*Preflight (Stage 0) has already confirmed the API is reachable, sentinel exists, and manifest is readable. This stage extracts the version information needed to compute the change manifest.*

### 1.1 Extract current versions

From the sentinel memory:
- Extract the `sdlc:seed-version:{version}` tag to get `KNOWLEDGE_VERSION` (the version the knowledge layer was last seeded at).

From `.sdlc-manifest.json` in the project root:
- Read `sdlc_version` to get `OPERATIONAL_VERSION` (the version the filesystem layer was last updated at).

If `.sdlc-manifest.json` is missing, treat `OPERATIONAL_VERSION` as unknown and flag it in the pre-flight report.

### 1.2 Get latest upstream version

Store the result of `sdlc_get_version` as `LATEST_VERSION`.

### 1.3 Version comparison and early-exit logic

Compare both layer versions against `LATEST_VERSION`:

| Knowledge layer | Operational layer | Action |
|----------------|-------------------|--------|
| Current | Current | Output "SDLC is up to date ({LATEST_VERSION})." Stop. |
| Current | Stale or unknown | Skip Stage 3 knowledge fetch. Jump to Stage 4 operational update only. |
| Stale | Current | Perform knowledge re-seed only. Skip operational file updates in Stage 4. |
| Stale | Stale or unknown | Full migration — both layers. |

Report the assessment to CD before proceeding:

```
Pre-flight complete.

  Knowledge layer:   {KNOWLEDGE_VERSION} (target: {LATEST_VERSION}) — [current / update needed]
  Operational layer: {OPERATIONAL_VERSION} (target: {LATEST_VERSION}) — [current / update needed]

Proceeding with: [full migration / knowledge only / operational only]
```

---

## Stage 2 — Changelog Review Gate

**CD must confirm before any changes are applied.**

### 2.1 Fetch the changelog

Download the cc-sdlc CHANGELOG.md at `LATEST_VERSION` from GitHub:

```
gh api repos/Inpacchi/cc-sdlc/contents/CHANGELOG.md --jq '.content' | base64 -d
```

Or via raw URL: `https://raw.githubusercontent.com/Inpacchi/cc-sdlc/{LATEST_VERSION}/CHANGELOG.md`

### 2.2 Extract entries since workspace version

Parse all changelog entries between `KNOWLEDGE_VERSION` (or the older of the two layer versions) and `LATEST_VERSION`. Identify:

- **Breaking changes** — marked with `BREAKING` or `breaking change` in the changelog
- **Deprecations** — entries removed from the knowledge layer
- **Convention renames** — skill renames, tag renames, parameter changes
- **New capabilities** — new skills, new knowledge domains, new MCP tools
- **Contract changes** — entries tagged `[contract-change]`, indicating a new or modified phrase in cc-sdlc's phrasing contract that may require updating the Pattern Mapping table in this skill (see "Neuroloom-Aware Content Transformation" above)

Note any changelog items that reference CLAUDE.md sections, skill invocation patterns, or agent configurations — these require a CLAUDE.md compatibility check in Stage 4.

### 2.2a Contract Change Gate

If any `[contract-change]` entries were identified in 2.2, stop and prompt the maintainer before proceeding:

```
⚠ Contract Change Detected

cc-sdlc has changed the phrasing contract between {KNOWLEDGE_VERSION} and {LATEST_VERSION}.
This plugin's Pattern Mapping table must be reviewed before migration can safely proceed —
otherwise upstream phrases the transformer doesn't recognize will be content-merged verbatim,
leaving file path references in Neuroloom-installed skills.

Contract-change entries:
  - {date}: {title}
    {summary}

Next step: read [sdlc-root]/process/knowledge-routing.md § "Standard Phrases" in the upstream
release, compare to the Pattern Mapping table in this skill, and add/update transformation
rules as needed. Then re-run /sdlc-migrate.
```

Do not proceed to Stage 3 or Stage 4 until the Pattern Mapping table has been updated and the maintainer confirms the plugin is ready. This is a hard gate — skipping it ships a silently-broken migration.

### 2.3 Present to CD for confirmation

Use `AskUserQuestion` to present the changelog summary and require explicit confirmation before proceeding:

```
cc-sdlc changelog: {KNOWLEDGE_VERSION} → {LATEST_VERSION}

Breaking changes:
  [list or "None"]

Deprecations:
  [list or "None"]

Convention renames:
  [list or "None"]

New capabilities:
  [list or "None"]

Proceed with migration?
```

Options: `Yes, apply migration` / `No, cancel` / `Show full changelog first`

If CD selects "Show full changelog first," display the raw changelog and re-present the confirmation.

If CD cancels, stop. Do not apply any changes.

---

## Stage 3 — Fetch + Diff

Only run this stage for layers that need updating (per Stage 1.5 assessment).

### 3.1 Fetch the new release

Download the full file listing of the `Inpacchi/cc-sdlc` repo at `LATEST_VERSION`:

```
gh api repos/Inpacchi/cc-sdlc/git/trees/{LATEST_VERSION}?recursive=1
```

Download content from the following categories:

| Category | Path | Target Layer |
|----------|------|--------------|
| Knowledge stores | `knowledge/**/*.yaml` | Knowledge (Neuroloom API) |
| Discipline parking lots | `disciplines/` | Knowledge (Neuroloom API) |
| Skills | `skills/` | Operational (filesystem) |
| Agent templates | `agents/` | Operational (filesystem) |
| Process docs | `process/` | Operational (filesystem) |
| Templates | `templates/` | Operational (filesystem) |
| CLAUDE.md | `CLAUDE-SDLC.md` | Operational (filesystem) |

**Knowledge layer exclusions:**
- `knowledge/agent-context-map.yaml` — This is a configuration file that maps agent roles to knowledge file paths. In Neuroloom, agents use `memory_search` with tags instead of file paths. This file is not knowledge content and must NOT be ingested.
- `knowledge/provenance_log.md` — This is a project-specific append-only record of knowledge ingestions and research handoffs. It contains the project's audit lineage, not seed content. Must NOT be ingested or overwritten.
- `knowledge/README.md` and subdirectory READMEs — Documentation only, not knowledge entries.

Use the GitHub contents API for individual files:

```
gh api repos/Inpacchi/cc-sdlc/contents/{path}?ref={LATEST_VERSION} --jq '.content' | base64 -d
```

### 3.2 Build the change manifest

For the **knowledge layer**, compare each `knowledge_id` in the new release against workspace entries:

| Change Type | Definition |
|-------------|-----------|
| New | `knowledge_id` not found in workspace |
| Updated | `knowledge_id` exists, content differs |
| Unchanged | `knowledge_id` exists, content identical |
| Deprecated | `knowledge_id` present at `KNOWLEDGE_VERSION`, absent from new seed |

For the **operational layer**, compare each file in the new release against the current filesystem version. Use `.sdlc-manifest.json` to identify the base version for diff. Categorize as: unchanged, updated (framework-only changes), or modified (project has customizations).

#### 3.2a Operational-layer drift detection

Before computing updated-vs-modified, detect **drift** — files where the installed hash (`installed_files[path].sha256` in the manifest) no longer matches the current on-disk hash. Drift indicates the file was edited post-install without going through PROJECT-SECTION markers.

For each file listed in `manifest.installed_files`:

```
current_hash = sha256(file contents on disk)
installed_hash = manifest.installed_files[path].sha256

if current_hash != installed_hash:
  mark as DRIFTED
  categorize based on upstream comparison:
    - DRIFTED + upstream unchanged → "project edited a framework file that upstream didn't change"
    - DRIFTED + upstream changed   → "project edited a file AND upstream changed it — conflict"
    - DRIFTED + file missing upstream → "project edited a deprecated framework file"
```

**Drift categories:**

| Category | Meaning | Default Action |
|----------|---------|----------------|
| `DRIFTED-CLEAN` | Project edited, upstream unchanged since install | Prompt user: overwrite with upstream, keep project version, or extract changes into PROJECT-SECTION markers |
| `DRIFTED-CONFLICT` | Project edited AND upstream changed | Hard prompt: three-way merge required. Show both diffs. |
| `DRIFTED-ORPHAN` | Project edited, file no longer in upstream | Prompt: keep as project-owned file, or delete |

Drifted files surface in the change manifest at Stage 3.3 with a `⚠ DRIFT` marker. CD sees them before any mutation.

**Why this matters:** Without drift detection, migration silently overwrites manual edits. With it, every manual edit gets surfaced and consented before being touched.

**New installs (no `installed_files` in manifest):** Projects initialized before drift detection was introduced won't have this field. In that case:
1. Log: "Drift detection unavailable — manifest predates installed_files field"
2. Back-fill: hash current files and record them to manifest under `installed_files` with `installed_at: "backfilled-{LATEST_VERSION}"`
3. Proceed without drift analysis this run — it becomes available from the next migration forward

### 3.3 Present change manifest with expandable preview

**This is the primary preview gate.** CD must be able to inspect actual content before any mutations occur.

#### 3.3.1 Initial summary

Output the change manifest summary (not via `AskUserQuestion` — this is informational):

```
Change manifest: {KNOWLEDGE_VERSION} → {LATEST_VERSION}

Knowledge layer:
  New:        {N} entries
  Updated:    {N} entries
  Unchanged:  {N} entries
  Deprecated: {N} entries (will be tagged deprecated, not deleted)

Operational layer:
  Unchanged:  {N} files
  Updated:    {N} files (framework-only changes — will overwrite)
  Modified:   {N} files (project customizations detected — will require review)
```

#### 3.3.2 Preview options

Use `AskUserQuestion` with category-based drill-down options:

```
What would you like to review before applying?
```

Options (show only categories with count > 0):
- `Preview new knowledge entries ({N})` — shows titles + full content of entries to be created
- `Preview updated knowledge entries ({N})` — shows titles + content diff (old vs new)
- `Preview deprecated knowledge entries ({N})` — shows titles of entries that will be tagged deprecated
- `Preview updated operational files ({N})` — shows file paths + unified diff
- `Preview modified operational files ({N})` — shows file paths + diff highlighting project customizations
- `Apply migration` — proceed to Stage 4
- `Cancel` — abort without changes

#### 3.3.3 Category preview behavior

When CD selects a preview category, output the full content for that category:

**New knowledge entries:**
```
New entries to be created ({N}):

1. {title}
   knowledge_id: {id}
   tags: [{tags}]
   ---
   {full content}

2. {title}
   ...
```

**Updated knowledge entries:**
```
Updated entries ({N}):

1. {title}
   knowledge_id: {id}
   
   --- Current (in workspace)
   {current content}
   
   +++ New (from cc-sdlc {LATEST_VERSION})
   {new content}

2. {title}
   ...
```

For large diffs, show a unified diff format highlighting only changed lines.

**Deprecated knowledge entries:**
```
Entries to be deprecated ({N}):

These entries exist in your workspace but are no longer in cc-sdlc {LATEST_VERSION}.
They will be tagged sdlc:deprecated but NOT deleted.

1. {title} (knowledge_id: {id})
2. {title} (knowledge_id: {id})
...
```

**Updated operational files:**
```
Operational files to be overwritten ({N}):

1. {file_path}
   @@ unified diff @@
   ...

2. {file_path}
   ...
```

**Modified operational files:**
```
Modified files requiring review ({N}):

These files have project customizations that differ from the upstream version.
Each will get a per-file confirmation in Stage 4.

1. {file_path}
   Project customization detected:
   {summary of what's different}
   
   @@ unified diff (project vs upstream) @@
   ...

2. {file_path}
   ...
```

#### 3.3.4 Return to options

After displaying any category preview, return to the options prompt (3.3.2). CD can preview multiple categories before deciding to apply or cancel.

**Loop until CD selects `Apply migration` or `Cancel`.**

If there are modified operational files, note that Stage 4 will present a per-file confirmation for each one (the preview here shows what to expect; the gate in Stage 4 is where the decision is made).

---

## Stage 4 — Apply Migration

> ## ⚠ POINT OF NO RETURN
>
> **Stages 0–3 were read-only.** Preflight validated the environment, state extraction read the sentinel and manifest, the changelog gate got CD approval, and the fetch+diff produced the change manifest — none of those touched workspace state. Cancelling at any prior stage left no trace.
>
> **Stage 4 is the first stage that commits mutations.** The first `document_ingest_batch` call in Stage 4.1 upserts to Neuroloom. The first file write in Stage 4.2 overwrites on disk. Once either has run, **cancellation leaves partial state**. The good news: migrations are designed to be resumable — re-running `/sdlc-migrate` from a crash point will complete via idempotent upsert and PROJECT-SECTION marker re-merge. The bad news: the workspace version tracking (sentinel, manifest) will be in an intermediate state until the re-run completes.
>
> Before proceeding, verify:
> - Stage 2.2a contract-change gate did not halt (no unresolved `[contract-change]` entries)
> - Stage 3.3 preview gate returned `approved`
> - Preflight passed without hard failures
> - Transaction log has the corresponding `gate` events with `approved` results
>
> Log a `checkpoint: point_of_no_return` event to the transaction log immediately before the first batch call.


### 4.1 Re-seed the knowledge layer

Call `document_ingest_batch` with all new and updated knowledge entries. Batch in groups of up to 50 documents per call.

The server handles all migration cases automatically via `knowledge_id` matching:
- **New entries** — created with the new version tag
- **Changed entries** — content updated, version tag updated, importance scores preserved
- **Unchanged entries** — no-op (server detects no diff)
- **Removed entries** — tagged `sdlc:deprecated` server-side, NOT deleted
- **Project-specific entries** (`sdlc:project-specific` tag) — never modified by re-seeding

Each document must include:
- `knowledge_id` — the stable ID used at initialization (must always be included — omitting it breaks upsert)
- `version` — `{LATEST_VERSION}`
- `source_type` — `"sdlc_knowledge"`
- `format` — `"yaml"` or `"markdown"` as appropriate
- `tags` — `["sdlc:knowledge", "sdlc:seed", "sdlc:seed-version:{LATEST_VERSION}"]` plus applicable domain/type tags per the tag schema

**Do NOT manually add `sdlc:knowledge-id:{id}` to the tags array.** Pass `knowledge_id` as a parameter; the server creates the tag automatically.

Check the batch response:

```json
{
  "summary": {"total": N, "created": N, "updated": N, "unchanged": N, "errors": N},
  "results": [{"index": N, "title": "...", "status": "...", ...}]
}
```

If `summary.errors > 0`, log the failed entries (title, error message) and report them in Stage 5. Do not abort — continue with the operational layer.

#### 4.1a Discipline re-seed

Disciplines occupy both layers logically: their **framework sections** (headers, methodology prose, structure) come from upstream cc-sdlc and need updating when cc-sdlc ships changes; their **parking-lot entries** (project-captured insights) are project data and must be preserved across migrations.

Base cc-sdlc handles this via in-file merge (§2.3 of upstream `sdlc-migrate`). Neuroloom projects handle it via tag-scoped ingestion that follows the same diff-then-send logic as regular knowledge YAMLs.

| Content Type | Tags | `knowledge_id` | Behavior |
|--------------|------|----------------|----------|
| Framework section (methodology, headers, structure from upstream) | `sdlc:discipline:{name}`, `sdlc:seed`, `sdlc:seed-version:{v}` | `discipline:{name}:framework` (deterministic) | Diffed in Stage 3.2 against workspace version. Included in Stage 4.1 batch **only if New or Updated**. Unchanged frameworks are skipped entirely — no ingest call. |
| Parking-lot entry (project-captured insight) | `sdlc:discipline:{name}`, `sdlc:parking-lot`, `sdlc:triage:{state}` | Project-generated (not in upstream seed) | Never in the change manifest — upstream doesn't know about them. Naturally excluded from re-seed. |
| Triage-promoted entry (parking-lot → validated knowledge) | `sdlc:discipline:{name}`, `sdlc:knowledge`, `sdlc:project-specific` | Project-generated | `sdlc:project-specific` tag explicitly protects from re-seed per Stage 4.1 rules. |

**Why not re-seed every migration?** `document_ingest_batch` with `knowledge_id` is idempotent — unchanged content would return `unchanged` from the server — but sending it anyway wastes bandwidth, clutters the change manifest, and makes Stage 5 verification noisier. The idempotent upsert is a safety net for races and retries, not the primary filter. Use the Stage 3.2 change manifest as the authoritative list of what needs sending.

**Implementation:**
1. In Stage 3.1, fetch disciplines from upstream alongside knowledge YAMLs (already documented at line 298 of this skill).
2. In Stage 3.2, for each fetched discipline framework section, compute `knowledge_id = discipline:{name}:framework` and compare against workspace entry with that ID. Categorize as New / Updated / Unchanged / Deprecated using the same definitions as knowledge YAMLs.
3. In Stage 4.1, include only the New + Updated discipline framework entries in the batch. Skip Unchanged. Deprecated get `sdlc:deprecated` tagged server-side (same handling as knowledge YAMLs).
4. If the manifest shows all discipline frameworks are Unchanged, report `disciplines: no changes` and skip the discipline portion of the batch entirely.

**If the base cc-sdlc discipline file shape changes** (e.g., a new canonical section added), the `[contract-change]` gate in Stage 2.2a catches it — the maintainer reviews whether discipline re-seed needs adjustment before migration proceeds.

**Verify after re-seed (only for disciplines that were actually updated):**
```
memory_search(query="{discipline-name} framework methodology",
              tags=["sdlc:discipline:{name}", "sdlc:seed-version:{LATEST_VERSION}"])
```
Should return the upstream framework content with the new version tag. A separate search for `sdlc:parking-lot` tag should still return project entries — confirming they were preserved.

### 4.2 Update operational layer files

Apply the content-merge strategy for each file category:

#### Skills

**Plugin skills** (`sdlc-initialize`, `sdlc-migrate`): These are owned by `neuroloom-sdlc-plugin/skills/` — NOT `.claude/skills/`. Do not write cc-sdlc originals to `.claude/skills/`. If stale cc-sdlc originals exist from a prior installation, delete them:

```
rm -rf .claude/skills/sdlc-initialize/ .claude/skills/sdlc-migrate/
```

The plugin versions are the authoritative replacements, updated from the plugin repo, not cc-sdlc upstream.

**cc-sdlc core skills** (all other skills in `.claude/skills/`): Always overwrite with the new upstream content. These have no project customizations.

**Enhanced skills** (`sdlc-archive`, `sdlc-audit`): Merge — keep Neuroloom-specific sections (API call patterns, MCP tool references, tag schema), update cc-sdlc sections (stage logic, verification checklists, red flags tables). Present a diff via `AskUserQuestion` if the Neuroloom sections appear to have been modified by the project.

**Audit skill special handling:** The `sdlc-audit` skill has framework audit methodology in `SKILL.md` and `references/` that must stay current:

1. Read the cc-sdlc source versions of all audit skill files
2. Read the project's versions
3. Update SKILL.md workflow, modes, and reference pointers — **verbatim from cc-sdlc source, not rephrased**
4. Update `references/compliance-methodology.md` audit dimensions and report format
5. Update `references/improvement-methodology.md` extraction patterns and categorization
6. Update `references/session-reading.md` JSONL format reference
7. Preserve any project-specific audit dimensions or improvement categories added by the project

**Migration note:** The `sdlc-compliance-auditor` agent has been restored as a subagent dispatched by `sdlc-audit`. If the project has an old version, update it to the current version. If the project removed it during a prior migration, re-install it.

#### Agents

**Framework agent files** (`AGENT_TEMPLATE.md`, `AGENT_SUGGESTIONS.md`, `sdlc-reviewer.md`, `sdlc-compliance-auditor.md`): Apply Neuroloom-Aware Content Transformation rules (see section above). Scan each file for `memory_search(` or `memory_store(` patterns before merging. Preserve MCP-based sections; update non-MCP framework sections verbatim from upstream. If `AGENT_SUGGESTIONS.md` doesn't exist in the project, install it.

**Project domain agents** (all other files in `.claude/agents/`): Re-run the project-stack tailoring logic from `sdlc-initialize`: update the framework-derived sections of each agent file (Knowledge Context, Communication Protocol, "Surfacing Learnings" sections) while preserving the agent name, domain description, scope ownership, anti-rationalization tables, and any project-added agents that do not exist in the upstream template set. Note: `knowledge_feedback` was removed from the Knowledge Context section template upstream — remove it from project agents during tailoring.

If an upstream agent template was renamed: flag it. Do not silently overwrite a renamed agent.

#### Process docs

Overwrite cc-sdlc originals (files that originated from the upstream framework) with PROJECT-SECTION marker extraction/re-injection. Preserve files that were added by the project and have no upstream equivalent — identify these by checking `.sdlc-manifest.json` for the file origin.

**Never overwrite `process/agent-selection.yaml`** — this file contains the project's agent roster and dispatch rules with project-specific agent names. It becomes project-specific after initialization. If upstream added new entries (e.g., new infrastructure domains, new tier definitions), flag them for CD review rather than overwriting.

#### `.sdlc-manifest.json`

Update the `sdlc_version` field to `LATEST_VERSION`. Preserve all project-specific fields. Add missing fields introduced in newer cc-sdlc versions if absent:

- `sdlc_root` — set to the detected SDLC root path (`ops/sdlc/` or `.claude/sdlc/`)
- `neuroloom_backend` — set to `true` if absent (load-bearing: `/sdlc-port` uses this to detect prior Neuroloom initialization)

**Refresh `installed_files` hashes.** For every file the migration just wrote (overwrites + merges + drift resolutions), recompute SHA-256 of the final on-disk content and update the corresponding entry in `installed_files`. For drift cases where CD chose "keep mine", record the current hash so subsequent migrations see a clean baseline. For files CD chose to overwrite with upstream, the hash reflects the new upstream content. This keeps drift detection accurate for the next migration.

#### `hooks/` files

Overwrite all files under `neuroloom-sdlc-plugin/hooks/` with the upstream plugin versions.

#### Modified file review gate

For each operational file flagged as modified (project customizations detected):

Use `AskUserQuestion` with the file path, a diff summary, and three options:

```
File: {path}
Status: Modified — project customizations detected

Upstream change: {one-line summary}
Your local change: {one-line summary of the detected customization}

How should this be handled?
```

Options: `Accept upstream (overwrite)` / `Keep mine (skip this file)` / `Show full diff`

If CD chooses "Show full diff," display it and re-present the same three options.

Record the outcome for the Stage 5 report.

### 4.2-gate. Content-Merge Verification

**Before proceeding to CLAUDE.md checks**, verify the content-merge results didn't corrupt project data. This catches merge errors before they propagate.

**Quick checks (< 2 minutes):**

1. **Skill customization preservation** — spot-check 1 enhanced skill (e.g., `sdlc-audit`):
   - Neuroloom-specific sections (API call patterns, MCP tool references) are intact
   - Framework sections were updated (compare against cc-sdlc source)

2. **Agent integrity** — spot-check 1 agent:
   - Framework-derived sections (Knowledge Context, Communication Protocol) were updated
   - Domain-specific content (scope, principles, workflow) was preserved

3. **Audit skill completeness** — verify all `references/` files were updated and any project-specific audit dimensions preserved

**Gate rule:** If any check fails, fix the merge before continuing. Do not proceed to Stage 4.3 with corrupted content.

### 4.3 CLAUDE.md compatibility check

Check the CLAUDE.md SDLC section for references that may have gone stale based on changelog-flagged items noted in Stage 2:

- Skill invocation patterns (e.g., `/sdlc-initialize`, `/sdlc-audit`)
- Stage or phase terminology that was renamed
- Tool parameter names that changed
- Tag names that were renamed

**Guarded rename rule for skills:** Before renaming any skill reference in CLAUDE.md:
1. Build the project's actual skill inventory: `ls .claude/skills/`
2. Only rename if the target skill directory exists in the project
3. If the target doesn't exist, log a warning instead of renaming:
   ```
   GUARDED RENAME SKIPPED: [old-name] → [new-name] — target directory does not exist in project
   ```

**Guarded rename rule for agents:** Skills that dispatch subagents contain agent names in examples and dispatch logic. Before renaming any agent reference:
1. Build the project's actual agent inventory: `ls .claude/agents/`
2. Only rename if the target agent file exists in the project
3. If the target doesn't exist, keep the project's original agent name

**CLAUDE-SDLC.md standalone cleanup:** If `[sdlc-root]/CLAUDE-SDLC.md` exists as a separate file (legacy from older installations), verify its content is already merged into `CLAUDE.md`, then remove it. CLAUDE-SDLC.md is no longer installed as a standalone file — its content lives directly in the project's CLAUDE.md.

**New CLAUDE-SDLC.md sections:** Compare the project's CLAUDE.md SDLC sections against the current upstream `CLAUDE-SDLC.md` source. If new sections were added upstream (e.g., new workflow rules, new verification policies), merge them into the project's CLAUDE.md.

For each stale reference found, either update it automatically (if the change is a clear 1:1 rename with a verified target) or flag it for CD review via `AskUserQuestion`.

If no changelog items flagged CLAUDE.md-relevant changes, this check is a no-op — report "No CLAUDE.md updates needed."

### 4.4 Sentinel

The sentinel is managed SERVER-SIDE by `seed()`. Do not create, update, or tag it manually. The server updates the sentinel's `sdlc:seed-version:{version}` tag automatically when the knowledge re-seed completes. After Stage 4.1 completes, re-read the sentinel via `memory_search(query="SDLC workspace sentinel", tags=["sdlc:sentinel"])` to confirm the server updated it.

---

## Stage 5 — Verification + Compliance Audit + Report

### 5.1 Knowledge layer spot-check

Verify the knowledge layer updated correctly by sampling 3–5 entries that were expected to change:

For each sampled entry, call `memory_search` with a query matching the entry's content and confirm:
- The `sdlc:seed-version:{LATEST_VERSION}` tag is present
- The content matches the new upstream version

If any spot-check fails, flag the entry in the report. Do not silently pass.

### 5.2 Operational layer verification

Confirm the following:

- [ ] All overwritten skill files contain the new upstream content
- [ ] `.sdlc-manifest.json` shows `sdlc_version: {LATEST_VERSION}`
- [ ] Sentinel's `sdlc:seed-version` tag reads `{LATEST_VERSION}` (confirmed via `memory_search`)
- [ ] `hooks/` files match upstream plugin versions
- [ ] No agent files were silently overwritten without project review (modified files were presented to CD)
- [ ] CLAUDE.md compatibility check completed and stale references resolved

### 5.3 Compliance audit

Dispatch the `sdlc-compliance-auditor` agent with a post-migration context:

```
Context: Post-migration audit. cc-sdlc version just updated from {KNOWLEDGE_VERSION} to {LATEST_VERSION}.
Check: knowledge layer integrity, operational file consistency, sentinel validity, deprecated entry tagging.
Flag: any version skew between knowledge and operational layers.
```

Wait for the auditor's report. If findings are CRITICAL, address them before closing the migration.

### 5.4 Report to CD

Output the full migration summary:

```
SDLC migration complete: {KNOWLEDGE_VERSION} → {LATEST_VERSION}

Knowledge layer:
  Created:     {N} new entries
  Updated:     {N} changed entries
  Unchanged:   {N} entries
  Deprecated:  {N} entries (preserved, tagged sdlc:deprecated)
  Errors:      {N} (see below if > 0)

Operational layer:
  Overwritten:    {N} files
  Skipped:        {N} files (kept project version)
  Modified:       {N} files (required manual review — see decisions below)
  Consolidated:   {N} skills removed (absorbed into other skills)
  Never-touched:  agent-selection.yaml, provenance_log.md (project-specific)

PROJECT-SECTION markers:
  Blocks found:      {N}
  Re-injected as-is: {N}
  Reviewed:          {N}
  Orphaned:          {N} (heading no longer exists — appended at end of file)

Neuroloom content transformation:
  Files with MCP patterns preserved: {N} [list files]
  Sections preserved: [list file § section]

CLAUDE.md:
  Stale references updated: {N}
  Guarded renames skipped:  {N} (targets don't exist)
  New sections merged:      {N}
  Standalone CLAUDE-SDLC.md removed: {yes/no/not present}

Manifest:
  sdlc_version: {LATEST_VERSION}
  New fields added: {list or "none"}

Compliance audit: {pass / N findings — see below}

Migration decisions:
  [table of modified files and CD's chosen action for each]

Errors (if any):
  [list of knowledge entries that failed to ingest, with error messages]
```

---

## Content-Merge Strategy Reference

This table governs Stage 4 decisions. Consult it when a file's category is ambiguous.

| File Category | Strategy | Rationale |
|---------------|----------|-----------|
| cc-sdlc core skills | Overwrite + marker preservation | Extract PROJECT-SECTION blocks, overwrite, re-inject |
| Plugin skills (initialize, migrate, port) | Always overwrite | Maintained in this plugin repo |
| Enhanced skills (archive, audit) | Merge | Contain Neuroloom-specific API sections |
| Agent files (framework: template, suggestions, reviewer, auditor) | Neuroloom-aware merge | Preserve MCP patterns, update non-MCP sections |
| Agent files (project domain agents) | Re-run tailoring | Framework sections update; domain desc preserved |
| Agent files (project-added) | Skip | No upstream equivalent — never touch |
| Process docs (upstream originals) | Overwrite + marker preservation | Extract PROJECT-SECTION blocks, overwrite, re-inject |
| `process/agent-selection.yaml` | **Never overwrite** | Project-specific agent roster and dispatch rules |
| Process docs (project-added) | Skip | No upstream equivalent |
| Knowledge YAMLs | Server-side upsert | `knowledge_id` matching handles new/updated/unchanged/deprecated |
| `knowledge/provenance_log.md` | **Never overwrite/ingest** | Project-specific append-only records |
| Discipline files | Preserve parking lots | Update framework sections, preserve project entries |
| `.sdlc-manifest.json` | Partial update | Update version + add missing fields (`sdlc_root`, `neuroloom_backend`) |
| `hooks/` files | Always overwrite | Plugin-managed; no project customizations |
| `CLAUDE.md` SDLC section | Targeted update + guarded renames | Only stale references; preserve project additions |
| Standalone `CLAUDE-SDLC.md` | Delete | Legacy file; content merged into CLAUDE.md |
| Templates | Overwrite | Framework-level; skip `templates/optional/` |

**Modified file rule:** If git diff shows the project has changed a file that would normally be overwritten, treat it as Modified and surface a review gate (Stage 4.2). Never silently overwrite a file with project customizations.

---

## Early-Exit Logic

The skill has two independent early-exit conditions. Both must be satisfied before reporting the workspace as fully up to date.

**Knowledge layer current, operational layer current:** Both versions match `LATEST_VERSION`. Output "SDLC is up to date." Stop.

**Knowledge layer current, operational layer stale:** Skip Stage 3 knowledge fetch and Stage 4.1 re-seed. Run Stage 4.2–4.4 only. Report as "Operational layer updated; knowledge layer was already current."

**Knowledge layer stale, operational layer current:** Run Stage 3 and Stage 4.1 only. Skip Stage 4.2 file updates. Report as "Knowledge layer updated; operational layer was already current."

**Neither layer version known:** `.sdlc-manifest.json` missing, sentinel missing. Cannot determine current state — abort and tell CD to run `/sdlc-initialize`.

---

## Error Handling

### Recovery principles

1. **Migration is resumable, not rollback-able.** There is no "undo" for a completed batch ingest or filesystem write. If a stage fails partway through, resume by re-running the skill — `knowledge_id` upsert and PROJECT-SECTION marker preservation make every stage idempotent.
2. **Never delete to recover.** If something looks half-applied, do not `rm` files or delete memory entries to force a clean retry. The upsert + marker logic handles re-application correctly. Destructive recovery loses work.
3. **Version tags are authoritative.** The sentinel's `sdlc:seed-version:{v}` and `.sdlc-manifest.json`'s `source_version` determine state. If they disagree with observed behavior, trust the tags and re-run — don't try to manually correct them.
4. **Knowledge and operational layers fail independently.** A knowledge-layer failure (Stage 4.1) does not invalidate operational-layer work (Stage 4.2) and vice versa. Report the state of each layer separately in failure reports.

### Failure modes

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

---

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

---

## Red Flags

| If you find yourself thinking... | Stop. The correct behavior is... |
|----------------------------------|----------------------------------|
| "I'll update knowledge but skip the operational files." | Version skew between knowledge and skills causes failures. Both layers must update together unless one is already confirmed current at the target version. |
| "Re-seeding will overwrite my project-specific knowledge." | Entries tagged `sdlc:project-specific` are never touched by re-seeding. Verify the tag is present on each entry you want protected before running the migration. |
| "The version check says up-to-date so nothing needs to happen." | Check both layers independently. Knowledge and filesystem can drift — one may be current while the other is stale. |
| "I can skip the confirmation gate for a minor version bump." | Even minor bumps can deprecate entries or rename conventions. Always show the change manifest and require CD confirmation. |
| "I need to manually tag deprecated entries." | Deprecation is handled server-side by `seed()`. The skill only re-seeds; the server handles removal tagging. Never add `sdlc:deprecated` manually. |
| "I'll skip the changelog review — it's just release notes." | The changelog flags breaking changes and convention renames. Skipping it means CLAUDE.md references go stale silently and agent invocations break in ways that are hard to trace. |
| "The compliance audit can wait until next session." | Post-migration audit catches integrity issues that compound quickly. Dispatch the auditor now, in Stage 5. |
| "I can update the sentinel after the operational layer too." | The sentinel is read-only to skills. The server updates it automatically. Never write to it manually. |
| "I'll call `memory_search` without a query parameter." | `memory_search` requires a mandatory `query` string. Tags alone are not sufficient. Every call must include an explicit query. |
| "CD said 'apply' so I'll skip the preview options." | The preview gate (Stage 3.3.2) must be presented every time. CD may want to inspect content even on familiar migrations. Never jump straight to Apply without offering the preview options. |
| "There are only 2 updated entries — I don't need to show content." | The count doesn't determine whether preview is valuable. A single entry could contain a breaking change. Always offer the preview options regardless of count. |
| "I should re-seed agent-context-map.yaml into Neuroloom" | `agent-context-map.yaml` is a configuration file, not knowledge content. It maps agent roles to file paths — a pattern replaced by tags in Neuroloom. Ingesting it adds garbage to the knowledge layer. Exclude it from all knowledge layer operations. |
| "I'll just overwrite all skills without checking for markers." | PROJECT-SECTION markers protect project-specific content. Extract marked blocks before overwriting, then re-inject. Skipping this destroys intentional project customizations. |
| "I'll copy agent-selection.yaml with the other process files." | `agent-selection.yaml` is project-specific — it contains the project's agent roster, not the framework's. Never overwrite it. |
| "I'll rename all skill references to match upstream." | Guarded renames only — check that the target skill directory exists in `.claude/skills/` before renaming. Renaming to a nonexistent skill causes silent process failures. |
| "I'll rename agent names in skills to match upstream." | Projects use different agent names (`frontend-engineer` vs `frontend-developer`). Only rename if the target agent exists in `.claude/agents/`. |
| "The AGENT_TEMPLATE.md can be copied directly from upstream." | Neuroloom projects use `memory_search` in Knowledge Context, not file path references. Scan for MCP patterns before merging — preserve them. |
| "I'll ingest provenance_log.md into the knowledge layer." | The provenance log is a project-specific append-only record. It's not seed content — never ingest or overwrite it. |
| "CLAUDE-SDLC.md should be a separate file." | Since upstream refactored this, CLAUDE-SDLC.md content lives directly in the project's CLAUDE.md. Remove any standalone copy after verifying its content is in CLAUDE.md. |

---

## Integration

**Depends on:**
- `sdlc-initialize` — workspace must have been initialized; migrate does not create a workspace from scratch
- `sdlc_get_version` MCP tool — provides the latest cc-sdlc release tag
- `document_ingest_batch` MCP tool — performs all knowledge layer updates
- `memory_search` MCP tool — reads sentinel and spot-checks knowledge entries
- GitHub API — source for upstream skill, agent, and process doc content

**Feeds into:**
- `sdlc-audit` — run post-migration to verify integrity; migrate dispatches auditor automatically in Stage 5
- `SessionStart` hook — reads sentinel version to detect when migration is needed; after a successful migrate, the hook should no longer report an update available

**Related skills:**
- `sdlc-initialize` — first-time workspace setup; use this when no sentinel exists
- `sdlc-port` — migrate an existing local cc-sdlc filesystem installation into a Neuroloom workspace; use this when transitioning from the old file-based model

## Migration vs Initialization

| | `sdlc-initialize` | `sdlc-migrate` |
|---|---|---|
| **When to use** | First time — no workspace exists | Workspace exists, version is outdated |
| **Sentinel** | Created by server (first seed) | Read-only; updated by server |
| **Knowledge layer** | Full seed from scratch | Upsert via `knowledge_id` matching |
| **Operational layer** | Full copy of all files | Content-merge with project diff review |
| **CD confirmation** | Required at Stage 4 (write gate) and Stage 6a (roster approval) | Required at changelog gate and change manifest gate |
| **Modified file handling** | N/A (no existing files) | Review gate per file with overwrite/skip options |
| **Compliance audit** | Dispatched in Stage 10 | Dispatched automatically in Stage 5 |
