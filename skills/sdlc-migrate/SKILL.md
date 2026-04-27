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

## Bundle Awareness

cc-sdlc's `skeleton/manifest.json` has a `bundles` section listing opt-in skill bundles (e.g., `design`) that are **not** part of the default install. A project's `.sdlc-manifest.json` records which bundles it adopted under `installed_bundles`.

**Behavior for Neuroloom migrations:**

1. **Detect installed bundles.** Read `.sdlc-manifest.json` → `installed_bundles`. If the field is missing (project installed before bundles existed), fall back to file-existence detection: for each bundle in upstream's `manifest.bundles`, check whether any of its skill paths exist under `.claude/skills/` and mark the bundle installed if so.
2. **Never remove installed bundle skills.** Bundle skills are exempt from the "removed upstream → remove in project" rule. Their absence from `source_files.skills` means "not default-installed," not "deleted."
3. **Apply §4.2.0 MCP gate to bundle skills** the same way it applies to core skills — `/sdlc-port` injects MCP calls into `sdlc-design-consult` etc. The gate already runs per-file and does not distinguish by bundle membership.
4. **Offer uninstalled bundles at the end of migration** (mirrors cc-sdlc's §4.7). For each bundle not installed, use `AskUserQuestion` to offer adoption. If accepted, copy the bundle's skills and append the bundle name to `installed_bundles`.
5. **Persist `installed_bundles`** in §4.4's manifest update. Back-fill from detection when absent.

**Rename handling:** Skill and agent renames are driven by `skeleton/contract_changes.yaml` — see Stage 4.3 for the full algorithm.

**Merge-rename semantics:** Multiple `from` values mapping to the same `to` in a single `rename_skill` entry mean a skill merge (e.g., `sdlc-review-commit` + `sdlc-review-diff` → `sdlc-review-code` in entry `0006`). Both old directories are upstream-deleted via the normal §2.1a flow; the merged skill is installed once. If the old files contained MCP-injected customizations, the §4.2.0 gate surfaces them — the migrator must re-inject them into the merged skill before deleting the old files, or log a `TRANSFORMATION_WARNING` for CD to resolve manually.

---

## Project-Specific Files (Never Overwrite)

These files become project-specific after initialization. They must NOT be direct-copied during migration:

| File | Reason |
|------|--------|
| `process/agent-selection.yaml` | Project's agent roster and dispatch rules — contains project-specific agent names |
| `knowledge/agent-context-map.yaml` | Configuration file, not knowledge — already excluded from knowledge layer |
| `knowledge/provenance_log.md` | Project's append-only ingestion/research records |

---

## Transformation-Exempt Files (HARD GATE — must be copied verbatim from upstream, no Pattern Mapping)

These files contain canonical phrases as **data** (validation criteria, historical quotes, contract documentation). Applying Pattern Mapping to them destroys their function. Unlike the "Project-Specific Files" table above (which are never overwritten), these files ARE overwritten from upstream — but the upstream content is copied **verbatim** with zero transformation applied.

| File | Reason |
|------|--------|
| `process/knowledge-routing.md` | The phrasing contract itself — lists canonical AND forbidden phrases as documentation |
| `process/sdlc_changelog.md` | Historical record — entries quote canonical phrases as context; transformation corrupts the history |
| `agents/sdlc-reviewer.md` | Reviewer's checklist quotes the canonical phrases as validation criteria — transforming them removes the phrases the reviewer exists to detect |
| `agents/sdlc-compliance-auditor.md` | Auditor's "Phrasing Contract Validation" section lists the canonical phrases as scan targets |
| `process/path-mappings.md` | Path mapping table lists `[sdlc-root]/knowledge/`, `[sdlc-root]/disciplines/`, and `agent-context-map.yaml` as data — transformation corrupts the mapping documentation |

**CLAUDE-SDLC.md is NOT on the exempt list** (changed post-knowledge-routing-audit). Earlier versions of this spec exempted it on the theory that it "contains canonical phrases as examples", but an audit of upstream cc-sdlc's `CLAUDE-SDLC.md` at v1.2.2 found zero canonical instruction phrases, two path-metadata sites (in a table describing commit completeness), and three concept-terminology leaks (`knowledge stores`, `Discipline parking lot entries`, `Knowledge store updates`). Exempting the file propagates that file-speak into every fresh Neuroloom installation's top-level `CLAUDE.md` — which is the first framework doc any agent reads. That's the exact opposite of what the exempt list exists for. `CLAUDE-SDLC.md` runs through Pass 1 (handles the two path-metadata sites via the existing parenthetical/table-cell metadata rules) and Pass 2 (handles the three concept-terminology sites via the concept-terminology class). Output has been spot-checked against upstream cc-sdlc v1.2.2.

**Enforcement (Stage 4.2):** Before invoking the Pattern Mapping transformer on any file, the executor MUST check the file's install path against this list. If matched:

1. Copy upstream content **verbatim** (no Pattern Mapping invocation, no metadata rule evaluation, no section-level preservation rewrite).
2. Log `file_merged` with `subtype: "exempt_verbatim"`, `rules_fired: []`, and `mcp_before == mcp_after` (no MCP count change expected).
3. Skip the §4.2-gate MCP Retention Audit's per-file classification for this file — exempt files are not subject to the audit because their canonical-phrase content is intentional.

**Why hard-gated:** The 2026-04-22 `migrate-f01a70` run transformed `agents/sdlc-reviewer.md` and `process/sdlc_changelog.md` despite both being in prior informational exempt lists. Listing a file as exempt without enforcement is equivalent to not listing it. The `sdlc-reviewer.md` transformation in particular destroyed the forbidden-phrases checklist (`:82-86`) that the reviewer uses to catch contract violations — turning the validation agent into one that can't validate.

**Post-migration verification:** The Stage 5.0 Telemetry Assertion (added earlier) must additionally verify that every file on this table emitted a `file_merged` event with `subtype: "exempt_verbatim"`. A `subtype: "mcp_preserved"` or `"mcp_backfilled"` event on an exempt file is a regression — halt with a specific error.

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

Pattern Mapping tables (instruction rules, wildcard rules, audit-description metadata, concept-terminology, metadata transformation), match rules (7 rules with worked examples and bug-prevention rationale), output regression scans, Integration/fenced-code/non-transformable-path hard exclusions, and capture-target context guards: see `references/pattern-mapping-rules.md`.

### Detecting Files That Contain Phrasing-Contract Patterns (Runtime Scan)

Rather than maintaining a hardcoded table of files, the migrator **scans each upstream file at merge time** to determine whether it contains phrasing-contract patterns that need transformation. The scan uses the same anchors the Pattern Mapping rules match against.

**Scan algorithm (runs per file in the merge set, AFTER Transformation-Exempt and Non-transformable-path exclusions):**

1. Check the file against the Transformation-Exempt list. If matched → copy verbatim, skip scan.
2. Grep the upstream file content for any of these anchors (case-insensitive):
   - `[sdlc-root]/knowledge/` (not followed by `provenance_log.md`)
   - `[sdlc-root]/disciplines/`
   - `consult [sdlc-root]/knowledge/`
   - `agent-context-map.yaml` (outside Integration sections and fenced code blocks)
3. If zero matches → no phrasing-contract patterns exist. Copy upstream verbatim (standard direct-copy). No Pattern Mapping invocation.
4. If one or more matches → the file contains transformable patterns. Route it through the Pattern Mapping transformer, subject to all existing exclusion masks (Integration sections, fenced code blocks, non-transformable path prefixes, capture-target context guards).

**Why scan beats a table:** cc-sdlc adds canonical phrases to skills regularly (12 were normalized in a single commit). A hardcoded table drifts silently — the migrator skips files it doesn't know about, producing installations with untransformed file-path references that break Neuroloom's semantic search. The scan derives the file set from file content, which is the actual source of truth.

**Performance:** The scan is a grep over files already in memory for the merge. No additional I/O.

#### Special-Case Overrides

A small number of files need behavior beyond "scan and transform." These overrides apply regardless of scan results:

| File | Override Behavior |
|------|-------------------|
| `process/knowledge-routing.md` | If the installed version contains `memory_search(` calls, preserve the entire file verbatim — the project has a Neuroloom variant. Otherwise, copy upstream verbatim (it's on the Transformation-Exempt list). |
| `skills/sdlc-create-agent/SKILL.md` | The `## Knowledge Context` scaffolding section generates new agents. After transformation, verify the scaffolded template uses `memory_search` — not `consult [sdlc-root]/knowledge/agent-context-map.yaml`. |
| `skills/sdlc-ingest/SKILL.md` | The WIRE step (knowledge wiring to agent-context-map) is skipped in Neuroloom — knowledge is stored with tags instead. The scan will flag this file; the transformer handles it via normal Pattern Mapping. |
| `skills/sdlc-audit/references/compliance-methodology.md` | Dimension 6 references `agent-context-map.yaml` concepts as audit criteria — checks must translate to memory-graph equivalents. The scan will flag this file; the transformer handles it via normal Pattern Mapping. |

### Content-Merge Rules for Neuroloom

1. **Detection heuristic:** Before merging any file flagged by the scan, check the project's current installed version for `memory_search(` or `memory_store(`. If present, the project already has Neuroloom integration for this file.

2. **Section-level preservation:** When merging a file with existing Neuroloom patterns:
   - Identify sections containing MCP tool calls (usually delimited by `##` headings)
   - Extract the project's MCP-based version of those sections
   - Apply upstream framework updates to sections WITHOUT MCP calls
   - Re-inject the project's MCP-based sections verbatim
   - Log: `Neuroloom pattern preserved: [file] § [section]`

3. **Per-file detection:** Even though this is a Neuroloom workspace, apply detection at file level before merging. Some files may have been added after the port and still use file path patterns. Only preserve MCP patterns where they actually exist.

4. **Reviewer checklist transformation:** The `sdlc-reviewer.md` contains checklists that validate knowledge wiring. Preserve: `Knowledge Context section includes a memory_search call`. Don't overwrite with: `Knowledge Context section references agent-context-map.yaml`.

5. **Agent template sections:** The `agent-template.md` (at `[sdlc-root]/templates/`) drives new agent creation. Preserve: `call memory_search(query="[agent-name] domain-specific patterns...`. Don't overwrite with: `consult [sdlc-root]/knowledge/agent-context-map.yaml`.

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
- **Contract changes** — entries tagged `[contract-change]`, indicating a new or modified phrase in cc-sdlc's phrasing contract that may require updating the Pattern Mapping table in this skill (see "Neuroloom-Aware Content Transformation" above). Since cc-sdlc 1.3.0, structured contract changes are also recorded in `skeleton/contract_changes.yaml` — read that file alongside the changelog. Every `[contract-change]` tag in the migration range should have a corresponding entry in the YAML; missing correspondence on either side is a cc-sdlc source defect worth filing upstream.

Note any changelog items that reference CLAUDE.md sections, skill invocation patterns, or agent configurations — these require a CLAUDE.md compatibility check in Stage 4.

### 2.2a Contract Change Gate (deterministic semver check)

Deterministic gate comparing `plugin.json → supported_ccsdlc_version` against each `[contract-change]` entry in the migration range. Full procedure (PSV lookup, dual-source scanning, halt conditions, maintainer update workflow): see `references/contract-change-gate.md`.

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

#### 3.3.1 Initial summary + 3.3.2 Preview options

Change manifest summary template and AskUserQuestion drill-down options (5 preview categories + Apply/Cancel): see `references/preview-templates.md` § "Summary and Preview Options".

#### 3.3.3 Category preview behavior

Output format templates for each preview category (new/updated/deprecated knowledge, updated/modified operational files): see `references/preview-templates.md`.

#### 3.3.4 Return to options

After displaying any category preview, return to the options prompt (3.3.2). CD can preview multiple categories before deciding to apply or cancel.

**Loop until CD selects `Apply migration` or `Cancel`.**

If there are modified operational files, note that Stage 4 will present a per-file confirmation for each one (the preview here shows what to expect; the gate in Stage 4 is where the decision is made).


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

**REQUIRED READING — read these before executing any procedure in §4.2 (NO EXCEPTIONS):**

1. `${CLAUDE_PLUGIN_ROOT}/skills/sdlc-migrate/references/pattern-mapping-rules.md` — the canonical Pattern Mapping table (instruction rules, wildcard rules, audit-description metadata, concept-terminology with all noun-phrase variants, metadata transformation, hard exclusions, capture-target context guards, post-write halt patterns). **Reading this file from disk is non-optional.** Do NOT reconstruct the rules from memory — the file contains specific singular/plural/hyphenated/case variants and post-`migrate-XXXXXX` bug-prevention rationale that cannot be reproduced from generic knowledge of the phrasing contract.
2. `${CLAUDE_PLUGIN_ROOT}/skills/sdlc-migrate/references/content-merge-audits.md` — the §4.2-gate audit procedures (Structural Content-Loss, MCP Retention, Stale Agent Reference, Contract Residue, sanity checks). **Each audit has explicit halt conditions and event schemas the executor must emit.**
3. `${CLAUDE_PLUGIN_ROOT}/references/post-operation-audit.md` — runs at §5.2a but informs what §4.2 must produce so the post-op audit passes. Read at §4.2 entry, not after writes complete.

**Why this banner exists:** sleeved `migrate-0957db` (2026-04-26) self-audit attributed 79% of regressions (56 of 71) to LLM skips of explicit skill requirements. The single highest-impact skip was: "I never read references/pattern-mapping-rules.md (415 lines, contains the EXACT singular/bare-form rules I was missing in Pass 2) or references/post-operation-audit.md ... I treated them as appendix material." If you are reading this section right now and feel tempted to proceed without reading those three files end-to-end, STOP. The references are not appendix; they are load-bearing. Treating them as appendix is the failure mode that has produced the largest class of regressions across two consecutive migrations.

**Stage 4.2 runs as a TWO-PASS TRANSFORMATION PIPELINE (new in 0.4.0).**

Prior versions applied all transformation rules in a single pass. That worked for path-bearing content but left a gap: concept-terminology (file-speak describing the knowledge layer, such as "parking lot entries" or "Knowledge YAML files") couldn't be safely applied inside Integration sections or fenced code blocks because hard-exclusion rules for those regions blocked all transformation, including harmless prose translations. Running concept terminology as a separate, later pass — with stricter "prose-only" scope — addresses this without compromising the hard exclusions that protect paths and code examples.

**Pipeline structure:**

```
Stage 4.2
├── Pass 1: Path + Instruction Transformation (existing behavior)
│   ├── §4.2.0 pre-write MCP preservation + transformation gate
│   ├── Pattern Mapping application (canonical phrases → MCP calls)
│   ├── Metadata transformation (parentheticals + table cells)
│   ├── Audit-description metadata (prose path references)
│   ├── Hard exclusions: exempt files, Integration sections, fenced code blocks, non-transformable paths
│   └── Per-file write + file_merged event
├── Pass 2: Prose Concept-Terminology (new in 0.4.0)
│   ├── Re-read each file written by Pass 1
│   ├── Identify prose-only regions (see scope rules below)
│   ├── Apply concept-terminology rule class (added in 0.3.9) to prose regions ONLY
│   ├── Write updated content
│   └── Per-file concept_terminology_applied event
└── §4.2-gate: audit passes run AFTER both transformation passes
    ├── Structural Content-Loss Audit
    ├── MCP Retention Audit
    └── Output-regression scans (orphan debris, double-paren, malformed verbs, etc.)
```

**Why two passes:** Pass 1's hard exclusions are about protecting content integrity — paths must not be corrupted, fenced code must not be syntactically altered, Integration-section path references must not be rewritten to something that breaks the semantic of "this depends on that file". Pass 2's scope is narrower: translate file-mode vocabulary to memory-graph vocabulary, touching ONLY prose. Pass 2 cannot alter paths, cannot touch YAML keys or values, cannot modify code inside fenced blocks. It can transform the *descriptor prose* after a path in an Integration section, the *body* of a heading, and bare prose anywhere not covered by another rule class.

Pass 2 scope (prose-region definition, can/cannot transform examples), transaction log event schema, regression-halt rules, and fenced-code-demo deferral (0.5.0): see `references/pattern-mapping-rules.md` § "Pass 2".

---

#### 4.2.0 Mandatory Pre-Write MCP Preservation + Transformation Gate (Pass 1)

**This gate runs BEFORE any file write in Stage 4.2. It applies to every file, regardless of category.**

Neuroloom projects contain `memory_search(` / `memory_store(` calls injected by `/sdlc-port` or `/sdlc-initialize` into many cc-sdlc files. Blindly overwriting with upstream content (file-based references) reverts the Neuroloom integration and silently breaks knowledge retrieval. Equally important: NEW files and existing files that somehow missed earlier transformation must get their standard phrases transformed to MCP calls as upstream lands. **Writing any file without this gate is a critical bug.**

**For each file the migration would write:**

1. **Read the project's current version** (if it exists). Count `memory_search(` + `memory_store(` → `MCP_COUNT_BEFORE`. If the file does not exist in the project, `MCP_COUNT_BEFORE = 0` and the file is flagged as a new install.

2. **Read the upstream version** and apply the **Pattern Mapping table** (see "Neuroloom-Aware Content Transformation" above) — substitute each matched cc-sdlc standard phrase with its Neuroloom equivalent. This produces `UPSTREAM_TRANSFORMED`. This step runs for **every file in a Neuroloom project** (i.e., when `.sdlc-manifest.json` has `neuroloom_backend: true`), whether or not the project already had MCP calls. New files and previously-untransformed files get transformed here; existing files get upstream's new content transformed before any merge.

3. **Branch by project state:**

   **Case A — new file (project had no prior version):** Write `UPSTREAM_TRANSFORMED`. Log `mcp_new_file` with the post-write MCP count.

   **Case B — existing file, `MCP_COUNT_BEFORE == 0`:** The project has a prior version but it never had MCP calls (earlier install missed it, or file was added later without transformation). Write `UPSTREAM_TRANSFORMED`. Log `mcp_backfilled` with before/after counts.

   **Case C — existing file, `MCP_COUNT_BEFORE > 0`:** The file has been Neuroloom-transformed. Apply the **section-level preservation overlay** on top of `UPSTREAM_TRANSFORMED`:

   a. Scan the project version for `memory_search(` / `memory_store(` calls that do NOT match any Pattern Mapping row (e.g., domain-specific queries like `memory_search(query="debugging methodology...", tags=[...])`).
   b. Extract the sections containing those calls (delimited by `##` or `###` headings).
   c. If the upstream version of the same section does not have equivalent MCP calls after Pattern Mapping, preserve the project's section verbatim by replacing the corresponding section in `UPSTREAM_TRANSFORMED` with it.
   d. Write the merged content. Target: `MCP_COUNT_AFTER >= MCP_COUNT_BEFORE` (see §4.2-gate).
   e. Log `mcp_preserved` with before/after counts and per-section decisions.

   **Heading match for section preservation (fuzzy):** Upstream may rephrase a heading's parenthetical or body while keeping the section number/stem. A strict text match orphans these sections. Match in this priority order, and stop at the first hit:

   1. **Exact text match** — headings identical after trimming whitespace.
   2. **Numeric-stem match** — extract the leading identifier (e.g., `### 6b.`, `## 2.1`, `#### 11f.`) and match on the identifier alone, ignoring the rest of the heading. `### 6b. Knowledge Stores (Neuroloom Knowledge Layer)` matches `### 6b. Knowledge Stores ([sdlc-root]/knowledge/)`.
   3. **Stem-before-parenthetical match** — strip the trailing `(...)` from both headings and match the remainder. `### Knowledge Stores (Neuroloom Knowledge Layer)` matches `### Knowledge Stores ([sdlc-root]/knowledge/)`.
   4. **Slug match (last resort)** — slugify both (lowercase, strip punctuation, collapse whitespace, drop parenthetical content). Used only when (1)–(3) all miss and the heading level matches.

   If only (2)–(4) hits, log a `heading_fuzzy_match` transaction-log event with the project heading, upstream heading, and tier used — this surfaces orphan risk to the audit. If no tier hits, the section is genuinely orphaned — append it at the end of the file with the existing `MIGRATION WARNING` comment (see PROJECT-SECTION-START preservation rules above).

   **Scope of fuzzy match:** applies to the §4.2.0 section-preservation overlay AND to the §4.2-gate MCP Retention Audit's "heading exists upstream?" check. Both must use the same matcher so the audit doesn't flag a preserved section as a regression simply because the heading text drifted.

   **Heading-text preservation policy (added post-`migrate-0957db` sleeved 2026-04-26):** when fuzzy match (tiers 2–4) hits and the project's heading text differs from upstream's, the **default is to keep the project's heading text** rather than overwrite with upstream's, IF either of these conditions hold:

   a. The project heading contains Neuroloom-mode terminology (`memory entries`, `memory graph`, `Neuroloom Knowledge Layer`, `discipline memory`, `knowledge memory`, `sdlc:` tag references, `via memory_search`, `via memory_store`, etc.) AND the upstream heading contains file-mode terminology (`[sdlc-root]/`, `parking lots`, `knowledge stores`, `YAML files`, etc.) for the same concept. Reason: the project's heading is already correctly Neuroloom-aware; overwriting with upstream's file-mode form is a regression.

   b. The project heading was previously generated by a Pass 2 concept-terminology rule (e.g., upstream `### 6b. Knowledge Stores ([sdlc-root]/knowledge/)` → project's `### 6b. Knowledge Memory (Neuroloom Knowledge Layer)`). Reason: the rule fired correctly on a prior migration; reverting is undoing the rule's work.

   In these cases:
   - Keep the project's heading text verbatim
   - Apply Pass 2 concept-terminology rules to the upstream heading IF it has not yet been transformed (so future projects without prior Pass 2 hits get the same outcome)
   - Log `heading_preserved_neuroloom` event with project heading, upstream heading, and the tier that matched

   When both headings use the same vocabulary class (both file-mode or both Neuroloom) but differ in detail (e.g., upstream renamed a parenthetical, added a section number suffix), upstream wins for the heading text — the project's customization, if any, lives in the section body, not the heading.

   **Why this matters:** sleeved Flag 9 (`migrate-0957db` self-audit) had 6 heading regressions in `compliance-methodology.md` where the previous migration had correctly transformed `### 6b. Knowledge Stores` to `### 6b. Knowledge Memory (Neuroloom Knowledge Layer)`, then this migration's fuzzy-match correctly identified the matching section but defaulted to keeping upstream's `### 6b. Knowledge Stores` heading text and rewrote the project's heading back to file-mode. The skill was silent on this default; the LLM picked the wrong one. This rule makes the default explicit: project's Neuroloom heading wins when there's a vocabulary mismatch, every time.

4. **Non-Neuroloom projects** (`neuroloom_backend: false` or absent): Skip Pattern Mapping. Write upstream verbatim. This is the cc-sdlc base behavior.

**Transaction log entries — MANDATORY per-file emission:**

Every file processed by stage 4.2 MUST produce exactly one of these events, emitted **immediately after the file is written**, before processing the next file. Batching, deferring, or skipping emission is a telemetry regression and causes the post-run gate to fail.

```
file_merged       — generic per-file event with before/after MCP counts (required for every file, including when no MCP change)
mcp_new_file      — subtype: file didn't exist in project; wrote transformed upstream
mcp_backfilled    — subtype: file existed but had no MCP; wrote transformed upstream
mcp_preserved     — subtype: file had MCP; merged transformed upstream + project sections
mcp_drop          — MCP count decreased (subject to §4.2-gate classification)
heading_fuzzy_match — logged when §4.2.0 section preservation fell back to a non-exact heading tier (tiers 2–4)
```

**Schema for `file_merged` (and subtype events):**
```json
{
  "ts": "ISO-8601",
  "run_id": "migrate-xxxxxx",
  "event": "file_merged",
  "stage": "4.2",
  "file": "relative/path/to/file",
  "subtype": "mcp_new_file | mcp_backfilled | mcp_preserved",
  "mcp_before": <int>,
  "mcp_after": <int>,
  "headings_preserved": [<list of heading strings kept verbatim>],
  "headings_fuzzy_matched": [{"tier": 2|3|4, "project": "...", "upstream": "..."}],
  "rules_fired": [<pattern-mapping row labels applied>]
}
```

**Why mandatory:** The 2026-04-22 `migrate-f01a70` run wrote stage-4.2 files without emitting any `file_merged` events and without emitting the `mcp_retention_audit_complete` event below. The migration reported `run_complete` successfully despite the audit being invisible — silent gate bypass. The pre-`run_complete` assertion in §5 below now fails if these events are missing for any file written during stage 4.2.

**Recurrence in `migrate-6f4217` (sleeved 2026-04-26) — read this if you are the executor:** the same regression recurred 4 days after the §5 pre-`run_complete` assertion was added. The 2026-04-26 run emitted exactly 7 events for 88 written files: a `checkpoint`, five aggregate `stage_end` summaries (one per stage 4.1–5), and `run_complete`. Zero `file_merged`, zero subtype events, zero `concept_terminology_applied`, zero `mcp_retention_audit_complete`, zero `structural_audit_complete`. The §5 assertion was bypassed because the executor never reached it as a separate step — it emitted `run_complete` from inside the stage 5 summary without running the assertion procedure. **If you are running this skill right now and find yourself thinking "I'll batch the events" or "the stage_end summary is good enough" or "I'll write the events at the end" — STOP. The events are not optional, the assertion is not optional, and the per-file emission is what the gates need to detect regressions. Emit `file_merged` IMMEDIATELY after each file write — don't continue to the next file until you've written the event to `.sdlc-transaction-log`.** Concretely: each file write is a two-step pattern (Write tool → Edit `.sdlc-transaction-log` to append the event) and you do these two steps for file N before starting file N+1's two steps. There is no version of "I'll catch up on telemetry later" that produces valid output.

**Why this gate exists:** A 2026-04-22 migration regression overwrote 65 MCP calls across 44 files because the content-merge rules were inconsistent across file categories. This gate enforces uniform MCP preservation AND uniform forward transformation — every upstream file lands as Neuroloom-native in a Neuroloom project, whether it's new, newly-transformed, or merged with an existing MCP-bearing version.

**When this gate does NOT apply:**
- Project-specific files listed in "Project-Specific Files (Never Overwrite)" — those are skipped entirely
- Non-Neuroloom projects — this plugin is not installed in them; cc-sdlc's own sdlc-migrate handles those

---

Once the gate has been applied for a file, the following category-specific rules define additional handling (PROJECT-SECTION markers, review gates, etc.). None of them override the MCP preservation gate — if Step 3 kept the project's MCP sections, category rules only govern the non-MCP portions of the merged content.

Per-category merge rules (Skills, Agents, Process docs, Templates, Manifest, Hooks, Modified file review gate): see `references/file-category-handling.md`.

### 4.2-gate. Content-Merge Verification

Before proceeding to CLAUDE.md checks, verify the content-merge results. **Five mandatory audits** — Structural Content-Loss Audit (6 structural counts), MCP Retention Audit (regression vs. legitimate removal classification), Stale Agent Reference Audit (0.4.7 — proactive scan of every written file for agent-name refs that don't resolve to `<target>/.claude/agents/`, classifying each as halt/warn/substitute), Contract Residue Audit (0.4.8 — proactive scan for untransformed cc-sdlc canonical phrasing in non-exempt context, catches the `mcp_new_file` Pattern Mapping bypass class), and quick sanity checks. Full procedures, halt conditions, event schemas, and recovery instructions: see `references/content-merge-audits.md`.

The Stale Agent Reference Audit consumes the optional `agent_renames` field in `<target>/.sdlc-manifest.json` — a project-side rename map of the form `{"<canonical-cc-sdlc-name>": "<project-name>"}` that tells the audit to substitute references to `<canonical-cc-sdlc-name>` with `<project-name>` in framework content. Projects that have renamed an agent (e.g., `security-engineer` → `infosec-engineer`) declare it once in the manifest and the audit applies it consistently every migration.

### 4.3 CLAUDE.md compatibility check

Check the CLAUDE.md SDLC section for references that may have gone stale.

**Primary driver — `skeleton/contract_changes.yaml`:** Read `skeleton/contract_changes.yaml` from the fetched cc-sdlc source. Read `.sdlc-manifest.json` → `last_applied_contract_id` (treat missing as `"0000"`). Select entries with `id > last_applied_contract_id` — call this set **pending_changes**. Collect all `from → to` pairs from `type: rename_skill` entries (and, future, `type: rename_agent` entries). Apply them in id order with the guarded-rename rule below. Chained renames walk automatically because entries apply in order.

If `contract_changes.yaml` is absent from the cc-sdlc source (upstream predates cc-sdlc 1.3.0), skip the contract-driven rename step and fall back to per-entry changelog inspection for any Stage 2-flagged renames.

**Also check** (beyond structured renames):

- Skill invocation patterns (e.g., `/sdlc-initialize`, `/sdlc-audit`) still resolve
- Stage or phase terminology that was renamed by prose in the changelog (captured during Stage 2.2)
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

**Scope of this rule (added post-`migrate-0957db` clarification):** the §4.3 guarded-rename rule above covers **explicit-divergence renames** — where `contract_changes.yaml` declares a `rename_agent` mapping and the LLM must rewrite references in CLAUDE.md and known referencing skills. It does **not** cover **implicit-divergence cases** — where cc-sdlc upstream uses a canonical agent name (`security-engineer`, `data-architect`, `ml-engineer`) that the project never adopted, with no contract_changes entry driving it because there was no upstream rename. The implicit case is handled by the §4.2-gate **Stale Agent Reference Audit** (see `references/content-merge-audits.md` § "Mandatory: Stale Agent Reference Audit") which proactively scans every written framework file for agent-name refs that don't resolve to `<target>/.claude/agents/`. Both rules run on every migration; together they cover both divergence directions.

**Do NOT hardcode rename pairs in this skill.** Every rename goes in cc-sdlc's `contract_changes.yaml`. Adapter-maintainers: if you find yourself wanting to add a special case here, file an upstream PR adding the entry to `contract_changes.yaml` instead. The phrasing-contract Pattern Mapping table remains adapter-specific and lives here — that's the only rename-shaped data the adapter owns.

**CLAUDE-SDLC.md standalone cleanup:** If `[sdlc-root]/CLAUDE-SDLC.md` exists as a separate file (legacy from older installations), verify its content is already merged into `CLAUDE.md`, then remove it. CLAUDE-SDLC.md is no longer installed as a standalone file — its content lives directly in the project's CLAUDE.md.

**New CLAUDE-SDLC.md sections:** Compare the project's CLAUDE.md SDLC sections against the current upstream `CLAUDE-SDLC.md` source. If new sections were added upstream (e.g., new workflow rules, new verification policies), merge them into the project's CLAUDE.md.

For each stale reference found, either update it automatically (if the change is a clear 1:1 rename with a verified target) or flag it for CD review via `AskUserQuestion`.

If pending_changes is empty and no changelog items flagged CLAUDE.md-relevant changes, this check is a no-op — report "No CLAUDE.md updates needed."

### 4.4 Sentinel

The sentinel is managed SERVER-SIDE by `seed()`. Do not create, update, or tag it manually. The server updates the sentinel's `sdlc:seed-version:{version}` tag automatically when the knowledge re-seed completes. After Stage 4.1 completes, re-read the sentinel via `memory_search(query="SDLC workspace sentinel", tags=["sdlc:sentinel"])` to confirm the server updated it.

---

## Stage 5 — Verification + Compliance Audit + Report

### 5.0 Telemetry Assertion (pre-flight for Stage 5 — NO OVERRIDE, NO EXCEPTIONS)

Before any verification runs, assert the Stage 4.2 telemetry is intact. Full procedure (event counting, schema validation, halt conditions): see `references/content-merge-audits.md` § "Telemetry Assertion".

**This gate is hard-blocking. The executor MUST NOT emit `run_complete` until every assertion below passes. There is no override flag, no "skip-this-time" mode, no batch mode that defers it.** Sleeved's `migrate-6f4217` (2026-04-26) emitted exactly 7 events for an 88-file migration: a checkpoint, five `stage_end` summaries, and `run_complete`. Zero `file_merged`, zero `mcp_retention_audit_complete`, zero `structural_audit_complete`, zero `concept_terminology_applied`. The migration was declared successful and the user discovered the regression only via outside-the-run diff audit. **That failure mode is the reason this gate exists — bypassing it is the worst class of plugin defect because it hides every other defect.**

**Required assertions (the executor MUST pass all of these before emitting `run_complete`; if any fails, emit a `TELEMETRY REGRESSION` halt and refuse to proceed):**

1. Count `file_merged` events for the current `run_id`. The count MUST equal the number of operational files written in stage 4.2 (cross-check against the change manifest). Zero is only acceptable if the manifest declared zero operational files (rare — knowledge-only re-seed runs).
2. Count `concept_terminology_applied` events. For Neuroloom-backend installations (`.sdlc-manifest.json` shows `neuroloom_backend: true`), the count MUST equal the `file_merged` count. Pass 2 fires for every file Pass 1 wrote, even if no substitutions actually applied — the empty-substitutions event is what proves Pass 2 was evaluated.
3. Verify exactly one `mcp_retention_audit_complete` event with `audit_result: "PASS"` (or `"FAIL"` and a corresponding halt earlier — never silently skipped).
4. Verify exactly one `structural_audit_complete` event with `audit_result: "PASS"` and ALL six structural counts (`heading_count`, `table_row_count`, `numbered_step_count`, `fenced_block_count`, `mandatory_step_count`, `bullet_count`) present per file.
5. Verify exactly one `agent_resolution_audit_complete` event with `audit_result: "PASS"` (added 0.4.7 post-`migrate-6f4217` sleeved audit). The event reports roster size, candidates found, resolved-direct vs resolved-via-renames vs halt/warn/accepted classifications. `warn_class > 0` is permissible at this gate (CD reviews descriptive-context unresolved refs in §5.4) but `halt_class > 0` reaching §5.0 is impossible — it means an earlier §4.2-gate halt was bypassed.
6. Verify exactly one `contract_residue_audit_complete` event with `audit_result: "PASS"` (added 0.4.8 — second sleeved follow-up). The event reports per-class hit counts (path-bearing residue from Pass 1 territory, concept-terminology residue from Pass 2 territory, exempt vs warn vs defect classifications). `defect_hits > 0` reaching §5.0 means an earlier halt was bypassed.
7. Verify every file on the Transformation-Exempt list emitted `file_merged` with `subtype: "exempt_verbatim"`. Any other subtype on an exempt file is a regression — surface it before emitting `run_complete`.
8. Verify zero unresolved `transformation_warning` events (warnings must be either resolved by a later event in the same run, or the run halted before `run_complete`).

**No telemetry → no `run_complete`.** If you (the executor running this skill) reach this point and notice you didn't emit `file_merged` events during stage 4.2 because you "did the writes in a loop and didn't think to log each one" or "summarized them in stage_end", **that is the failure mode**. Roll back via `git checkout -- .claude/` and restart from stage 4.0 with per-file telemetry enabled. Do not paper over by emitting after-the-fact reconstructed events — those don't carry the actual `mcp_before/after`, `headings_preserved`, or `rules_fired` data that the gate uses to detect regressions.

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

### 5.2a Post-Operation Audit (NO OVERRIDE, NO EXCEPTIONS)

**Run the shared post-operation audit** at `${CLAUDE_PLUGIN_ROOT}/references/post-operation-audit.md`. Execute the shared checks AND the `/sdlc-migrate`-specific subset.

**This audit is hard-blocking. The executor MUST run it before §5.3 — there is no override flag, no "the §4.2-gate audits already cover it" shortcut, no "skip when self-checks pass" mode.** Sleeved's `migrate-0957db` self-audit (2026-04-26) attributed roughly 56 of 71 manual fixes to LLM skips of explicit skill requirements; the post-operation audit was *not run at all* — it would have caught Classes A, C, E, and F as a single residual-file-path-refs scan. The §4.2-gate audits run per-file at write time on files this run touched; the post-operation audit runs aggregate and cross-file checks on the entire installation. Both are required; neither replaces the other.

**Operational pattern for the executor:** running the audit means actually executing the procedures in `${CLAUDE_PLUGIN_ROOT}/references/post-operation-audit.md` — Read the file, run each check listed, surface specifics ("Check 6 found 3 residual file-based refs in agent-context-map replacements at sdlc-execute.md:218, sdlc-plan.md:154, sdlc-review.md:79"), not "post-op audit completed cleanly." Skipping the read of post-operation-audit.md and inferring its content from memory is the pattern that produced the sleeved regressions — the reference doc contains check details and recovery procedures the executor cannot reconstruct.

The audit cross-verifies what §4.2-gate already caught at the per-file level by applying aggregate and cross-file checks:
- MCP integration health across the full installation
- Residual cc-sdlc standard phrases that should have been transformed
- Inline adapter conditionals that violate the contract
- Manifest-to-filesystem hash consistency
- Knowledge layer sentinel state

**If the audit fails:** Halt. Do NOT proceed to §5.3. Follow the audit's recovery instructions. Typical recovery for migrate is `git checkout -- .claude/` (migration is uncommitted at this point).

**If you find yourself wanting to skip this** because "the §4.2-gate audits already passed" or "this is just an aggregate version of what already ran" — STOP. The §4.2-gate runs per-file with the limited context of one file at a time. Cross-file invariants (manifest-to-filesystem hash consistency, knowledge layer sentinel state, no residual file-path refs across the whole install) are only visible at the aggregate level. The audit is not redundant; it covers a different dimension.

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
Output the full migration summary. Report template (DS1/DS4-compliant headline + executive summary + per-layer breakdown + Neuroloom transformation summary + migration decisions + CTA): see `references/preview-templates.md` § "Final Migration Report Template".

**After the report, present the manual diff spot-check option to CD** (added 0.4.9 post-`migrate-0957db` sleeved follow-up):

```
Five mandatory §4.2-gate audits + §5.0 telemetry assertion have all passed.
The migration is on disk and the §5.2/5.2a/5.3 verifications also passed.

For high-leverage final verification, consider a manual diff spot-check.
The 9-dimension compliance audit and 5 §4.2-gate audits between them
caught everything machine-detectable — but the sleeved migrate-0957db
review found that CD-level diff review against HEAD finds an additional
~70-100% beyond what audits surface, especially:
- Heading regressions where Neuroloom-aware project text was overwritten
  with cc-sdlc upstream's file-mode phrasing (audit catches if the
  heading body still has a path; misses bare title-case)
- Subtle phrasing drift in newly-introduced upstream sections
- Project-specific examples (agent names, paths, terminology) that
  diverged from upstream's defaults

Recommended:
   git diff HEAD -- .claude/ | less

Spot-review the top 5–10 files by diff size. Flag anything that looks
like project-specific Neuroloom-aware content being overwritten by
upstream file-mode terminology, or any agent name that doesn't match
your .claude/agents/ roster (the gate caught dispatch-position hits;
descriptive-context hits surfaced as warnings in the report).

Skip if you've already done multiple migrations on this project and
trust the audits — the spot-check has diminishing value as the audit
machinery catches more classes. But for the first 2-3 migrations
after a major upstream version bump, it's the highest-yield 5 minutes
of CD time available.
```

This is advisory, not gating. CD may skip if confident in the gates. The migration's `run_complete` is already emitted at this point — the spot-check produces follow-up work, not a halt.


## Content-Merge Strategy Reference

Per-category merge strategy table (18 file categories) and early-exit logic for layer-independent version states: see `references/content-merge-strategy.md`.

---

## Error Handling

Recovery principles, failure modes (21 entries with detection/response/recovery), and emergency restore procedures: see `references/recovery-procedures.md`.

---

## Red Flags

Common anti-patterns and their corrections (25 entries covering MCP preservation, guarded renames, project-specific file protection, and more): see `references/red-flags.md`.

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
