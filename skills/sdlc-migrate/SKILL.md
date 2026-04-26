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

> **How coverage actually works:** This table lists 5 explicit phrase-to-call mappings, but they cover only a fraction of real-world transformation sites. The vast majority of cc-sdlc files with knowledge references (skills, agents, process docs) are handled via the **section-level preservation rule** documented in "Content-Merge Rules for Neuroloom" below — scan each file for `memory_search(` / `memory_store(` presence and preserve those sections verbatim during merge. The explicit patterns below are what the transformer SEEKS during fresh installation (`/sdlc-initialize`) and during migration when a file has no prior MCP patterns. Once a file contains MCP calls, section-level preservation takes over.

**Match rules:**
1. **Case-insensitive on the leading verb, regardless of sentence position.** A rule `Read [sdlc-root]/disciplines/*.md and find [X]` matches both sentence-start `Read [sdlc-root]/disciplines/*.md and find...` and mid-sentence `..., read [sdlc-root]/disciplines/*.md and find...`. The verb (`Read`/`Consult`/`Append`/`Update`/`Look up`/etc.) is the anchor, not the sentence start. When substituting, preserve the original case of the verb only if the substitution keeps a verb at that position; otherwise the replacement's casing wins.
2. Patterns must match as a full phrase within a sentence.
3. **Inline backticks around paths are markdown formatting — match THROUGH them.** A rule `Append to [sdlc-root]/disciplines/*.md` matches `Append to \`[sdlc-root]/disciplines/*.md\`` (with inline backticks) and vice versa. Strip inline backticks before matching.
4. Only skip matching inside **fenced code blocks** (triple backticks ```` ``` ````) — those are literal code examples, not instructions.
5. When the rule pattern contains `<domain>` or `{name}` or `[agent-name]`, treat as a wildcard that captures the substring at that position. **The wildcard matches ANY value at that position, including other angle-bracket-looking placeholders in the source.** If upstream cc-sdlc content uses a different placeholder name (e.g., `<discipline>`, `<file>`, `<name>`) at the same structural position, the rule's wildcard matches that placeholder string as its captured value. When substituting, the captured string (placeholder and all) is inserted into the replacement.

   **The bug this prevents:** In `migrate-f01a70` AND `migrate-fa70ef`, `sdlc-ingest.md:231` had upstream `- Files from the same discipline (e.g., \`[sdlc-root]/knowledge/<discipline>/\`)`. The metadata rule `(e.g., [sdlc-root]/knowledge/<domain>/)` → `(e.g., memory entries tagged sdlc:knowledge + sdlc:domain:<domain>)` should match, capturing `<discipline>` into the `<domain>` wildcard slot. But both runs left the upstream text untransformed — the executor was requiring `<domain>` in the rule pattern to match a real domain value in the source, not another placeholder. Correct behavior: the wildcard matches `<discipline>` and the output is `(e.g., memory entries tagged sdlc:knowledge + sdlc:domain:<discipline>)` — the captured placeholder survives into the replacement because documentation describing a template should remain template-shaped after transformation.

   **Explicit worked example:**
   - Rule pattern: `(e.g., [sdlc-root]/knowledge/<domain>/)` with `<domain>` as wildcard per rule #5
   - Input (with backticks stripped per rule #3): `(e.g., [sdlc-root]/knowledge/<discipline>/)`
   - Match: `<domain>` wildcard captures the literal string `<discipline>`
   - Output: `(e.g., memory entries tagged sdlc:knowledge + sdlc:domain:<discipline>)`

   Do NOT require the captured value to be a "real" domain name. The rule's job is structural transformation, not semantic validation.
6. **Wildcard captures (`[X]`, `<name>`, `<purpose>`, `<tag-expr>`, etc.) are non-greedy and MUST terminate at any of:** `(`, `)`, `[` (not the opening `[` of the wildcard itself), `]`, `,`, `.`, `;`, `:` followed by whitespace, or end-of-line. A capture MUST NOT swallow a following parenthetical, list comma, or sentence boundary. Specifically: if the text after the wildcard is `(e.g., ...)` or `, [...]` or `. Sentence continues`, the capture stops **before** that punctuation.

   **The bug this prevents:** In `migrate-f01a70`, `sdlc-archive.md:175` matched `read [sdlc-root]/disciplines/*.md and find parking lot entries tagged with that deliverable's ID (e.g., [D05 — phase 2], [D05 — planning]).` The `[X]` capture in rule `Read [sdlc-root]/disciplines/*.md and find [X]` greedily consumed up through `ID (e` then stopped at an arbitrary character, producing a query string of `"parking lot entries tagged with that deliverable's ID (e"` and leaking the remaining `g., [D05 — phase 2]...)` outside the `memory_search(...)` call as orphan text. A non-greedy capture with explicit terminators stops at `(` and produces a clean `memory_search(query="parking lot entries tagged with that deliverable's ID", tags=[...])` followed by the original `(e.g., [D05 — phase 2], [D05 — planning]).` preserved verbatim.

7. **Verb-phrase awareness — rules that replace a verb phrase MUST produce a verb phrase** (added post-`migrate-fa70ef`). When the source phrase is a verb + object (`update X`, `read Y`, `append to Z`), the replacement must also be a verb + object — never a parenthetical aside, noun phrase, or standalone clause that can't take an object.

   If a rule's replacement is a parenthetical like `(skip — X)` or a bare noun phrase, it MUST NOT fire mid-sentence where surrounding text assumes a verb phrase. For such rules, the matcher has three options:

   a. **Preferred: extend the match to the full sentence clause**, replacing everything from the verb to the next sentence boundary. Example for `update [sdlc-root]/knowledge/agent-context-map.yaml to wire newly created knowledge files to relevant agents`: match the entire clause, replace with `Tag new knowledge via memory_store with sdlc:agent:[agent-name] and domain tags`. The extended-match form already exists in the specific-rule table (lines 135–136) — the matcher should prefer these extended variants over the terse `update X` rule whenever the surrounding context contains `to <verb>` or `with <object>`.

   b. **Acceptable: emit a grammatically-valid verb-phrase replacement.** If no extended variant matches, rewrite the rule's replacement to a phrase that can accept following objects. Instead of `(skip — Neuroloom uses tag-based wiring)`, use `skip this step (Neuroloom uses tag-based wiring via memory_store)` which remains grammatical even if the original sentence had trailing `with the mapping` — the reader parses it as a dangling qualifier rather than a broken sentence.

   c. **Last resort: emit `TRANSFORMATION_WARNING` and leave verbatim.** If the rule's replacement genuinely can't be reformulated as a verb phrase AND no extended variant covers the compound form, the matcher emits a warning and writes the original upstream text unchanged. This surfaces a Pattern Mapping gap rather than producing malformed output.

   **The bug this prevents:** In `migrate-fa70ef`, `sdlc-create-agent.md:256` had upstream `2. update [sdlc-root]/knowledge/agent-context-map.yaml with the mapping` — and the `update [sdlc-root]/knowledge/agent-context-map.yaml` rule fired with its `(skip — Neuroloom uses tag-based wiring via memory_store; no map to update)` replacement, producing the ungrammatical `2. (skip — Neuroloom uses tag-based wiring via memory_store; no map to update) with the mapping`. A verb-phrase-aware matcher would either extend the match to consume `with the mapping` (option a, since "update X with Y" is a compound verb construction), or rewrite the replacement to a clause-starting verb (option b). Same-class bug at `sdlc-audit.md:121`.

   **Enforcement:** the matcher MUST tag every Pattern Mapping rule as either `VERB_PHRASE` or `CLAUSE_REPLACEMENT`. Rules emitting parentheticals or noun phrases are `CLAUSE_REPLACEMENT` and MUST match whole-clause spans. Rules emitting verb phrases are `VERB_PHRASE` and may match mid-sentence. Applying a `CLAUSE_REPLACEMENT` rule to a sub-clause match produces grammatical corruption — halt with `TRANSFORMATION_WARNING` rather than write the broken output.

| cc-sdlc Generic Pattern | Neuroloom Pattern (preserve if present) |
|-------------------------|----------------------------------------|
| `consult [sdlc-root]/knowledge/agent-context-map.yaml` | `memory_search(query="[agent-name] domain-specific patterns", tags=["sdlc:knowledge"])` |
| `Consult [sdlc-root]/knowledge/agent-context-map.yaml for the [agent-name] entry and include relevant knowledge files in the dispatch prompt` | `memory_search(query="[agent-name] domain patterns for cross-domain dispatch", tags=["sdlc:knowledge"]) and include results in the dispatch prompt` |
| `Before starting substantive work, consult [sdlc-root]/knowledge/agent-context-map.yaml and find your entry. Read the mapped knowledge files...` | `Before starting substantive work, call memory_search(query="[agent-name] domain-specific patterns anti-patterns guidance", tags=["sdlc:knowledge"]) to retrieve domain-specific patterns...` |
| `Consult [sdlc-root]/knowledge/agent-context-map.yaml for the agent's mapped files` | `memory_search(query="[agent-name] mapped knowledge", tags=["sdlc:knowledge"])` |
| `Consult [sdlc-root]/knowledge/agent-context-map.yaml for knowledge wiring` | `memory_search(query="agent knowledge wiring", tags=["sdlc:knowledge"])` |
| `Consult [sdlc-root]/knowledge/agent-context-map.yaml to identify agents whose mappings include` | `memory_search(query="agents with mappings in [discipline]", tags=["sdlc:knowledge"])` |
| `update [sdlc-root]/knowledge/agent-context-map.yaml` (whole-clause match only — see match rule #7; if surrounded by `to <verb>` or `with <object>`, prefer the extended-compound rules below) | `skip this step (Neuroloom uses tag-based wiring via memory_store; no map to update)` — `VERB_PHRASE` class, can slot mid-sentence |
| `Update [sdlc-root]/knowledge/agent-context-map.yaml to add a new entry mapping the agent to relevant knowledge files` | Store knowledge tagged with `sdlc:agent:[agent-name]` and domain tags via memory_store |
| `Update [sdlc-root]/knowledge/agent-context-map.yaml to wire newly created knowledge files to relevant agents` | Tag new knowledge via memory_store with `sdlc:agent:[agent-name]` and domain tags |
| `Read [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml` | `memory_search(query="agent communication protocol structured progress handoff format", tags=["sdlc:knowledge", "sdlc:domain:architecture"])` |
| `Read [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml and follow the canonical agent communication protocol it defines` | `memory_search(query="agent communication protocol structured progress handoff format", tags=["sdlc:knowledge", "sdlc:domain:architecture"]) and follow the canonical agent communication protocol it defines` |
| `Read [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml for the handoff schema` | `Call memory_search(query="agent communication protocol handoff schema", tags=["sdlc:knowledge", "sdlc:domain:architecture"]) for the handoff schema` |
| `Read [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml for <purpose>` (generic `for <purpose>` suffix) | `Call memory_search(query="agent communication protocol <purpose>", tags=["sdlc:knowledge", "sdlc:domain:architecture"]) for <purpose>` |
| `Append to [sdlc-root]/disciplines/*.md` | `memory_store(tags=["sdlc:discipline:{name}", "sdlc:parking-lot"])` |
| `Append each insight or GAP entry to the relevant [sdlc-root]/disciplines/*.md parking lot` | `memory_store(tags=["sdlc:discipline:{name}", "sdlc:parking-lot"]) each insight or GAP entry` |
| `look up the agent's mapped files from [sdlc-root]/knowledge/agent-context-map.yaml` | `memory_search(query="{agent-name} domain patterns", tags=["sdlc:knowledge"])` |
| `knowledge stores ([sdlc-root]/knowledge/)` | `Neuroloom knowledge store (via memory_store)` |
| `[sdlc-root]/knowledge/testing/` (as capture target) | `memory_store with tags ["sdlc:knowledge", "sdlc:domain:testing"]` |
| `[sdlc-root]/knowledge/<domain>/` (as capture target) | `memory_store with tags ["sdlc:knowledge", "sdlc:domain:<domain>"]` |
| `Append to [sdlc-root]/knowledge/<domain>/` | `memory_store with tags ["sdlc:knowledge", "sdlc:domain:<domain>"]` |
| `Cross-project knowledge updates append to [sdlc-root]/knowledge/<domain>/` | `Cross-project knowledge updates go to memory_store with tags ["sdlc:knowledge", "sdlc:domain:<domain>"]` |
| `[sdlc-root]/knowledge/provenance_log.md` | **No transformation** — file lives on disk in Neuroloom projects too (project-specific, append-only; treated like `process/sdlc_changelog.md`). Preserve references verbatim. |
| `Read [sdlc-root]/knowledge/provenance_log.md` | **No transformation** — preserve verbatim (on-disk file read, not a knowledge-layer lookup). |
| `[sdlc-root]/knowledge/compliance-methodology.md` | `Neuroloom compliance methodology (memory_search with sdlc:knowledge, sdlc:methodology:compliance tags)` |
| `Read [sdlc-root]/knowledge/compliance-methodology.md for the full methodology` | `memory_search(query="SDLC compliance audit methodology", tags=["sdlc:knowledge"]) for the full methodology` |

**Wildcard rules (apply to any matching path not already covered by a specific rule above):**

| cc-sdlc Wildcard Pattern | Neuroloom Replacement |
|--------------------------|------------------------|
| `Read [sdlc-root]/knowledge/<domain>/<file>.yaml` | `memory_search(query="<file-name-as-topic>", tags=["sdlc:knowledge", "sdlc:domain:<domain>"])` |
| `Read [sdlc-root]/knowledge/<domain>/<file>.yaml and <verb> [rest]` | `memory_search(query="<file-name-as-topic>", tags=["sdlc:knowledge", "sdlc:domain:<domain>"]) and <verb> [rest]` |
| `Read [sdlc-root]/disciplines/<name>.md` | `memory_search(query="<name> discipline entries", tags=["sdlc:discipline:<name>"])` |
| `Read [sdlc-root]/disciplines/*.md` (glob across all disciplines) | `memory_search(query="discipline entries", tags=["sdlc:discipline:*"])` |
| `Read [sdlc-root]/disciplines/*.md and find [X]` | `memory_search(query="[X]", tags=["sdlc:discipline:*"])` |
| `read [sdlc-root]/disciplines/*.md and find parking lot entries tagged with <tag-expr>` (mid-sentence verb) | `memory_search(query="parking lot entries tagged <tag-expr>", tags=["sdlc:discipline:*", "sdlc:parking-lot"])` |
| `Read [sdlc-root]/disciplines/<name>.md and find [X]` | `memory_search(query="[X]", tags=["sdlc:discipline:<name>"])` |
| `scan [sdlc-root]/disciplines/ for [X]` / `scan [sdlc-root]/disciplines/*.md for [X]` | `memory_search(query="[X]", tags=["sdlc:discipline:*"])` |
| `Read relevant files under [sdlc-root]/knowledge/ and [sdlc-root]/disciplines/ for [X]` | `memory_search(query="[X]", tags=["sdlc:knowledge", "sdlc:discipline:*"])` |
| `Read relevant methodology files in [sdlc-root]/knowledge/` | `memory_search(query="methodology [context]", tags=["sdlc:knowledge"])` |
| `Read [sdlc-root]/knowledge/architecture/` or `[sdlc-root]/knowledge/testing/` YAML files and follow their general pattern | `memory_search(query="knowledge YAML pattern", tags=["sdlc:knowledge", "sdlc:domain:architecture", "sdlc:domain:testing"]) and follow the pattern` |
| `Read [sdlc-root]/knowledge/README.md § "<section>"` | `memory_search(query="knowledge layer <section>", tags=["sdlc:knowledge"])` |
| Evidence/citation parenthetical `[sdlc-root]/knowledge/<domain>/<file>.yaml, <section>` | `memory graph reference: sdlc:knowledge + sdlc:domain:<domain>, <section>` |

**Audit-description metadata (prose references in audit dimensions, compliance criteria, analysis descriptions):**

| cc-sdlc Audit-Description Pattern | Neuroloom Replacement |
|-----------------------------------|-----------------------|
| `Any YAML file in [sdlc-root]/knowledge/` | `Any memory entry tagged sdlc:knowledge` |
| `files in [sdlc-root]/knowledge/` | `memory entries tagged sdlc:knowledge` |
| `listed in [sdlc-root]/knowledge/agent-context-map.yaml` | `indexed by sdlc:agent:* tags in the memory graph` |
| `[sdlc-root]/knowledge/<discipline>/ directory` | `sdlc:knowledge + sdlc:domain:<discipline> memory entries` |
| `entries in [sdlc-root]/disciplines/` | `entries tagged sdlc:discipline:*` |
| `patterns that should be in [sdlc-root]/knowledge/ or [sdlc-root]/disciplines/` | `patterns that should be in the memory graph (sdlc:knowledge / sdlc:discipline:* tags)` |
| `no corresponding [sdlc-root]/knowledge/<discipline>/ directory` | `no corresponding sdlc:knowledge + sdlc:domain:<discipline> memory entries` |
| `YAML files under [sdlc-root]/knowledge/` | `memory entries tagged sdlc:knowledge` |
| `in [sdlc-root]/knowledge/` or `in [sdlc-root]/disciplines/` (prose, non-instruction) | `in the Neuroloom memory graph (sdlc:knowledge / sdlc:discipline:* tags)` |

**Knowledge-layer concept terminology (prose describing the knowledge layer's shape, not its paths):**

Audit-description metadata (table above) handles path-reference prose. This new class handles the **shape-describing terminology** — prose that talks about the knowledge layer using file-based vocabulary ("parking lot entries", "Knowledge YAML files", "agent-context-map.yaml" as a live thing) where no `[sdlc-root]/` path appears. These terms describe *what* knowledge lives in cc-sdlc by reference to its storage medium (files). In a Neuroloom install the storage medium is the memory graph, so the vocabulary must be translated even though no path is visible.

Added post-`migrate-fa70ef` audit: the previous audit-description rules fired on `[sdlc-root]/knowledge/<domain>/ directory` and similar path-bearing prose but left untouched pure file-speak like "parking lot entries" that doesn't contain a path. The translation is still needed because these terms leak the file-based architecture into the Neuroloom documentation.

| cc-sdlc Concept Terminology | Neuroloom Replacement |
|-----------------------------|------------------------|
| `parking lot entries` (used as a live concept, not describing a procedure specific to file-based mode) | `discipline memory entries` |
| `parking lot entries tagged with <X>` | `discipline memory entries tagged sdlc:discipline:* and <X>` |
| `parking lot entry` (singular) | `discipline memory entry` |
| `discipline parking lots` (used as a live concept) | `discipline memory entries` (or just `discipline memories` where plural-noun-phrase is needed) |
| `Knowledge YAML files` / `knowledge YAML files` / `YAML knowledge files` | `memory entries tagged sdlc:knowledge` |
| `knowledge YAML addition (new file or new rules in existing file)` | `knowledge memory addition (new entries or new rules in existing entries)` |
| `knowledge YAML` (bare, as live concept — not describing a file format) | `memory entries tagged sdlc:knowledge` |
| `agent-context-map.yaml` (referenced as a live config file) | `the memory graph (agents indexed by sdlc:agent:* tags)` |
| `agent-context-map` (bare, used as a live thing) | `the memory graph's agent index` |
| `Disciplines exercised without parking lots` | `Disciplines exercised without memory entries` |
| `Discipline parking lot entry` (as a log-of-insight type) | `Discipline memory entry` |
| `YAML files` (when referring to knowledge-layer storage) | `memory entries` |
| `new YAML files` / `existing YAML files` / `these YAML files` (in a knowledge-layer context) | `new memory entries` / `existing memory entries` / `these memory entries` |
| `Write new YAML files or append to existing ones` (knowledge-layer step) | `Store new memory entries or update existing entries` |
| `Update the knowledge store's README.md to list new files` / `add them to the README's structure listing and "Knowledge Categories" table` | `Update the knowledge index (memory entries tagged sdlc:knowledge + sdlc:knowledge-index) to list new entries` — OR, more commonly, drop the instruction entirely since Neuroloom has no README-listing equivalent and tag-based indexing is automatic |
| `project-specific files` (when enumerating knowledge-layer content) | `project-specific memory entries` |
| `on-disk knowledge` / `file-based knowledge` / `knowledge on disk` | `memory-graph knowledge` |
| `discipline file exists` / `no discipline file` (for layer-existence check) | `discipline memories exist` / `no discipline memories` |
| `knowledge store` (bare singular, used as a concept — not as a path or heading) | `knowledge layer` (or `memory-graph knowledge` where "layer" reads oddly) |
| `knowledge stores` (bare plural, used as a concept) | `knowledge memory entries` |
| `knowledge store maturation` | `knowledge layer maturation` |
| `knowledge store population` | `knowledge memory population` |
| `knowledge store's README.md` (live reference to file-mode index) | drop the reference entirely; Neuroloom has no README-based index — tag-based indexing is automatic |
| `existing knowledge stores` (as a source to query, e.g., "for deduplication") | `existing knowledge memory entries` |
| `target knowledge store` (for placement) | `target knowledge domain (`sdlc:knowledge + sdlc:domain:<name>` tags)` |
| `discipline files` (bare plural) | `discipline memory entries` |
| `discipline file` (bare singular) | `discipline memory entry` |
| `parking lot placement` / `parking lot triage` / `parking lot candidate` | `discipline memory placement` / `discipline memory triage` / `discipline memory candidate` |
| `knowledge file` (bare singular, used as a concept) | `knowledge memory entry` |
| `knowledge files` (bare plural, used as a concept) | `knowledge memory entries` |
| `YAML rule file` / `rule YAML file` / `rule file` (knowledge-layer context) | `knowledge memory entry` |
| `Knowledge Stores` (heading label) | `Knowledge Memory` (heading label) — paired with body-text update per heading rule |
| `Knowledge YAMLs` (bare plural short form — NOT "Knowledge YAML files") | `knowledge memory entries` |
| `Discipline Parking Lots` (heading label) | `Discipline Memory Entries` (heading label) — paired with body-text update per heading rule |
| `Parking Lot Entries` (heading label) | `Discipline Memory Entries` (heading label) |
| Numbered-list bold-label prefix `N. **Discipline parking lot entries** (...)` / `- **Discipline parking lot entries** (...)` | `**Discipline memory entries** (...)` — label rewritten; parenthetical continues via metadata rule |
| Numbered-list bold-label prefix `N. **Knowledge store updates** (...)` / `- **Knowledge store updates** (...)` | `**Knowledge memory updates** (...)` — label rewritten; parenthetical continues via metadata rule |
| Numbered-list bold-label prefix `N. **Knowledge YAML addition** (...)` | `**Knowledge memory addition** (...)` |

**Label-prefix-before-parenthetical combined rule (added after migrate-fa70ef audit):**

When a metadata-transformation parenthetical rule fires (e.g., `([sdlc-root]/disciplines/*.md)` → `(memory graph, entries tagged sdlc:discipline:*)`), the matcher MUST also scan the immediately-preceding text for a concept-terminology label. If the label is in the concept-terminology table (above), rewrite the label in the same pass. Examples:

- Input: `- **Discipline parking lot entries** (\`[sdlc-root]/disciplines/*.md\`)`
- After parenthetical rule alone (incorrect): `- **Discipline parking lot entries** (memory graph, entries tagged sdlc:discipline:*)`
- After combined rule (correct): `- **Discipline memory entries** (memory graph, entries tagged sdlc:discipline:*)`

**Why this matters:** Without the combined rule, half-transformed output surfaces in numbered lists and bullet lists where the file-speak label precedes a correctly-Neuroloom-ified parenthetical. The sleeved audit surfaced ~6 such sites in `sdlc-execute.md`, `sdlc-lite-execute.md`, and `compliance-methodology.md`. Single-pass parenthetical rules must look left to find these labels and rewrite them together.

**Scope:** the look-left scan only considers text on the same line, up to the line-start or the previous sentence boundary (`. ` / `! ` / `? `). It does not cross line boundaries or sentence boundaries — labels and their parentheticals are always written as a single logical unit on one line.

**Concept-terminology match notes:**

- These rules apply in PROSE contexts that describe the knowledge layer's **shape** rather than its **paths**. They're distinguished from audit-description rules by the absence of `[sdlc-root]/` in the matched text.
- **Do NOT apply inside:** Integration sections, fenced code blocks, headings that are the literal title of a framework-defined procedure (e.g., `### 9a. Scan Related Parking Lot Entries` as a defined section of the archive skill is a different case — see below), changelog entries, the phrasing contract doc itself.
- **Headings are a special case.** An H3/H4 heading like `### 9a. Scan Related Parking Lot Entries` names a procedure that cc-sdlc defines. In Neuroloom the procedure still exists but operates on memory entries, so rename the heading to `### 9a. Scan Related Discipline Memory Entries` AND adjust the body's procedure text to match. Do NOT transform the heading without transforming the body — that produces a mismatch where the heading says "memory entries" and the body says "files".
- **Procedure-specific steps are a special case.** Content like "Write new YAML files or append to existing ones" is a file-mode procedure. In Neuroloom, the procedure is "call `memory_store(content=..., tags=[...])`" — a completely different mechanism. When you see a numbered step that's a file-mode procedure, the replacement must be the Neuroloom procedure equivalent, not a word-for-word term swap. When no clean equivalent exists (e.g., "update the README.md structure listing"), emit `TRANSFORMATION_WARNING` and consider dropping the step since it's file-mode-only work the adapter doesn't need.
- **Fragments match independently within sentences,** same rule as audit-description. A sentence with multiple concept-terms must have each term transformed separately.

**The bug this prevents:** `migrate-fa70ef` left `improvement-methodology.md:213` with the full sentence: "No markers needed for project-specific files: Knowledge YAML files, discipline parking lot entries, and agent-context-map.yaml are project-owned..." All three concept terms describe the knowledge layer in file terms; none contain a `[sdlc-root]/` path so audit-description rules didn't fire. The new class catches this: `Knowledge YAML files` → `memory entries tagged sdlc:knowledge`; `discipline parking lot entries` → `discipline memory entries`; `agent-context-map.yaml` (live reference) → `the memory graph`. Same class of bug at `improvement-methodology.md:47/80/137–138/196–197`, `sdlc-archive.md:171/173/185`, `sdlc-ingest.md:214–218`, `research-external.md:72/204`.

**Audit-description match notes:**
- These rules apply in PROSE contexts where `[sdlc-root]/knowledge/` or `/disciplines/` appear as concept references, not runtime read instructions. Most common in `compliance-methodology.md` audit dimension descriptions.
- Do NOT apply inside Integration sections (`**Uses:**`, `**Depends on:**`), table cells, or code blocks — use the metadata-transformation table above for those.
- Distinguishing signal: if removing the path would leave the sentence still making sense (just less specific), it's audit-description metadata. If removing it breaks an instruction, it's a runtime ref — use the instruction rules above.
- **Fragments match independently within compound sentences.** A sentence with multiple path references (e.g., `Any memory entry tagged sdlc:knowledge not listed in any agent's mapping in [sdlc-root]/knowledge/agent-context-map.yaml. Severity: Warning...`) must have every `[sdlc-root]/...` fragment matched separately. The matcher walks the sentence and applies each audit-description rule to each fragment independently. Mixed results (one half transformed, one half untransformed) are a known failure mode and indicate the matcher only ran once per sentence.

   **The bug this prevents:** In `migrate-f01a70`, `compliance-methodology.md:208` became a compound mess: `Any memory entry tagged sdlc:knowledge not listed in any agent's mapping in the agent knowledge graph (via memory_store with sdlc:agent:{name} tags). Severity: Warning (the knowledge exists but no agent consumes it).` — the `listed in [sdlc-root]/knowledge/agent-context-map.yaml` fragment got the canonical `indexed by sdlc:agent:* tags` replacement on ONE half but the other half was independently misrewritten. The matcher must treat each `[sdlc-root]/...` occurrence as a separate match target.
- **Bare target-path rewrites (`.claude/sdlc/...`, `ops/sdlc/...`) are NOT audit-description transforms.** If a fragment already shows a resolved `.claude/sdlc/knowledge/` or `ops/sdlc/knowledge/` path (not `[sdlc-root]/`), that's a prior bug where path-variable rewriting fired instead of knowledge-layer transformation. Flag as `TRANSFORMATION_WARNING` — don't silently leave the target-path in installed content (`research-external.md:72` exemplar).
- `<domain>`, `<name>`, `<file>`, `<section>`, `[X]` capture the substring at that position
- For `<file-name-as-topic>`, convert the filename to a natural-language topic (e.g., `testing-paradigm.yaml` → `"testing paradigm"`, `debugging-methodology.yaml` → `"debugging methodology"`)
- If a specific rule above matches first, use it; wildcards only fire when no specific rule applies
- Wildcards fire only in instruction contexts (not in metadata/Integration sections/tables) — apply the same instruction-vs-metadata distinction as specific rules

#### Metadata transformation (parenthetical and table-cell path refs)

Parenthetical paths and table-cell paths in cc-sdlc source describe WHERE something lives in filesystem mode. In Neuroloom, those paths don't exist — the content is in the memory graph. Transform these metadata refs to their Neuroloom-native equivalent so Neuroloom users aren't pointed at non-existent files.

Apply these rules to: parenthetical paths `(...)`, table cells containing paths (any column, not just first/last), bullet-point labels with paths (both `Label: path` and `Label (path)` forms). Do NOT apply inside fenced code blocks or when the path is in a canonical instruction already handled above.

**Match rules for metadata transformation:**

1. **Strip inline backticks before matching — MANDATORY for metadata rows.** A rule `([sdlc-root]/knowledge/*.md)` matches all of these forms; the executor MUST normalize by stripping single backticks around the path before the rule is tested:
   - `([sdlc-root]/knowledge/*.md)` — bare
   - `` (`[sdlc-root]/knowledge/*.md`) `` — path in backticks inside parens
   - `` `([sdlc-root]/knowledge/*.md)` `` — entire parenthetical in backticks
   - `(\`[sdlc-root]/knowledge/*.md\`)` — escaped-backtick in markdown source
   This is the identical rule as instruction-pattern match rule #3. If you are reading this spec and find yourself wondering "does backtick-stripping apply to metadata rows the same way as to instruction rows?" — yes, always, no exceptions. Do not treat any metadata row as "only matches when no backticks present."
2. **`(e.g., ...)` prefix is absorbed.** The `e.g.,` ( / `e.g.` / `i.e.,`) prefix inside parens is treated as boilerplate and preserved in the replacement.
3. **Table-cell match is column-agnostic.** Match any cell whose content contains the target path — first column, last column, or middle. Do not restrict to specific column positions.
4. **Bullet label separator can be `:` or `(`.** Both `- Label: path` and `- Label (path)` are metadata forms — the transformation preserves the label and the separator form.
5. `<domain>`, `<name>`, `<file>` are wildcards that capture the substring at that position.

**Worked examples (executor-facing — verify your matcher produces exactly these outputs):**

| Input (before) | Output (after) |
|----------------|----------------|
| `` - Knowledge store updates (`[sdlc-root]/knowledge/*.md`) `` | `- Knowledge store updates (memory graph, entries tagged sdlc:knowledge)` |
| `` - Discipline parking lot entries (`[sdlc-root]/disciplines/*.md`) `` | `- Discipline parking lot entries (memory graph, entries tagged sdlc:discipline:*)` |
| `` - Files from the same discipline (e.g., `[sdlc-root]/knowledge/<discipline>/`) `` | `- Files from the same discipline (e.g., memory entries tagged sdlc:knowledge + sdlc:domain:<discipline>)` |
| `` \| Validated, testable rules \| `[sdlc-root]/knowledge/<discipline>/<file>.yaml` \| Specific, testable... \| `` | `\| Validated, testable rules \| memory entries tagged sdlc:knowledge + sdlc:domain:<discipline> \| Specific, testable... \|` |
| `` - Agent knowledge context: `[sdlc-root]/knowledge/agent-context-map.yaml` `` | `- Agent knowledge context: memory graph (agents indexed by sdlc:agent:* tags)` |
| `### 6a. Discipline Parking Lots (`[sdlc-root]/disciplines/`)` | `### 6a. Discipline Parking Lots (memory graph, entries tagged sdlc:discipline:*)` |
| `` Read `[sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml` for the handoff schema. `` | `Call memory_search(query="agent communication protocol handoff schema", tags=["sdlc:knowledge", "sdlc:domain:architecture"]) for the handoff schema.` (NOT `Read memory_store with tags [...]` — that's a capture-target rule leaking into a Read context, see below) |
| `` belong in knowledge stores (`[sdlc-root]/knowledge/`), not agent memory. `` | `belong in the Neuroloom knowledge store (via memory_store), not agent memory.` (the `knowledge stores ([sdlc-root]/knowledge/)` rule must match mid-sentence with backticks around the path — match rule #1 applies) |

If your matcher leaves any of these untransformed, or produces output with double-parens or orphan `*.md\`)` debris, it has a **rule-priority** or **backtick-normalization** defect — halt and file a plugin bug, do not write partial output.

**Rule ordering (CRITICAL — longest parenthetical-whole wins):**

When multiple rows could match the same substring, apply them in this order and stop at the first hit:

1. **Full-parenthetical rules** — rows whose pattern begins with `(` and ends with `)`. Match the entire `(...)` span including its parens. These consume their own parens and produce replacement parens, so they splice cleanly into surrounding text.
2. **Full-label+separator rules** — `<Label>: <path>` and `<Label> (<path>)` rows. Match the label + separator + path as one span.
3. **Full-table-cell rules** — match the entire cell content between `|` bars.
4. **Bare-path rules** — rows whose pattern is just `[sdlc-root]/...` with no surrounding delimiters. Apply ONLY when no higher-priority rule matched this position.

**Why ordering matters:** If a bare-path rule fires inside an already-open `(...)` context, its replacement (which typically itself contains `(...)` boilerplate like `(memory graph, ...)`) gets spliced inside the outer parens, producing `((...) *.md`)` debris. This is the double-paren corruption observed in the 2026-04-22 `migrate-f01a70` run (`sdlc-execute/SKILL.md:279` and five other sites). The full-parenthetical rule at row 1 consumes the outer parens as part of its match, so this class of bug cannot occur when the matcher prioritizes correctly.

**Verification the matcher has correct priority:** After transforming a file, scan the output for these regressions and halt on any hit:

- `((` followed by any alphanumeric (double-open-paren)
- `*.md\`)` anywhere (orphaned glob-suffix-with-backtick)
- ``*.md`)`` mid-line (same, without escape)
- `) *.md)` (orphan-glob-without-backtick)
- `Read memory_store` anywhere (nonsensical — `memory_store` is the write API, can't be `Read`)
- `Read memory_search` anywhere (`memory_search` is a function call; `Call memory_search(...)` is the correct verb — `Read memory_search` is a malformed transformation)

**Orphan extension-debris scan (added post-`migrate-fa70ef`):** extend the same halt-on-hit policy to these patterns. They're the same bug class as `*.md\`)` — partial-consume leaving a file-extension or glob suffix outside a completed replacement.

- `]\.yaml` (close-bracket immediately followed by `.yaml` with no separator — the matcher consumed the array-close of `tags=[...]` and left the original file extension as a tail). Exemplar: `memory_store with tags ["sdlc:knowledge"].yaml`
- `]\.yml` (same for YAML's alternate extension)
- `]\.md` (same for markdown)
- `]testing-paradigm\.yaml` / `]\w+\.yaml` (bracket-close concatenated to a file name — `migrate-fa70ef` exemplar at `sdlc-tests-create.md:250`)
- `\]/\.` and `/\.[^/a-zA-Z0-9]` (trailing `/.` left when a directory suffix was consumed) — exemplar at `process/overview.md:45` `memory_store with tags [...]/.`
- `"\]\.\w+` (quoted-bracket followed by dot-extension — stricter form catching edge cases)

If any of these match the written content, the matcher picked a rule whose replacement didn't consume the trailing file-extension token, leaving it concatenated to the replacement's array-close. The output file MUST NOT be written. Re-examine the rule whose replacement ends in `]` — it's missing the trailing `.yaml` / `.md` / `/` suffix consumption.

**Fence-parity assertion (added post-`migrate-fa70ef`):** count lines matching `^\s*\`\`\`` in both the pre-merge project version and the post-write content. The post-write count must be either **equal to the upstream count** (no net change in fenced blocks) OR **equal to `project_pre_merge_count`** (preserved as-is), whichever is applicable per the merge subtype:

- `exempt_verbatim` / `mcp_backfilled` subtype → post count must equal upstream count
- `mcp_preserved` subtype → post count must equal `project_pre_merge_count + (upstream_count - project_pre_upstream_count)` where `project_pre_upstream_count` was the fence count in the upstream version the project last migrated from
- `mcp_new_file` → post count must equal upstream count

A post count that differs from the expected by an odd number = an unclosed fence (someone added an opener without a closer or vice versa). Halt on this; it means the content-merge spliced a block mid-fence. Exemplar: `migrate-fa70ef` at `sdlc-ingest.md:192` — merge introduced `` ```yaml `` without a matching close-fence.

If any match, the matcher picked a bare-path rule over a parenthetical rule, OR a capture-target rule over an instruction rule, OR the merge window was misaligned — the output file MUST NOT be written.

**Integration sections are structurally exempt — HARD EXCLUSION:**

Any line matching `^\*\*(Uses|Depends on|Updates|Feeds into|Complements|Downstream|Does NOT replace|DRY notes):\*\*` and every bullet/text line following it up to the next blank line, the next `^\*\*[A-Z]` (new Integration label), or the next `^#{1,6} ` (heading) is an **Integration section**. Integration sections are exempt from ALL transformation:

- No instruction-rule matching
- No metadata-rule matching
- No capture-target-rule matching
- No audit-description rule matching

Integration sections describe logical dependencies between skills/agents/files, not runtime operations. Transforming `**Uses:** [sdlc-root]/knowledge/agent-context-map.yaml (for wiring)` into `**Uses:** memory graph (agents indexed by sdlc:agent:* tags) (knowledge wiring)` adds noise (the parenthetical purpose tag now wraps a non-file reference) and produces double-paren corruption. Leave Integration sections verbatim.

**Enforcement:** The matcher must mask out Integration sections before any rule evaluation. A post-write regression scan for `\*\*(Uses|Depends on|Updates|Feeds into):\*\*.*memory_(search|store)` on a single line halts the write — the Integration section was transformed and must be re-copied verbatim.

**VERBATIM means byte-identical, not "semantically preserved":** Integration-section lines must be written out byte-for-byte identical to the upstream source. This includes — and this is the failure mode `migrate-fa70ef` surfaced across 20+ files — **surrounding backticks on path references**. `` **Uses:** `[sdlc-root]/process/manager-rule.md` `` must remain with its inline backticks intact. Any incidental side-effect that strips backticks (e.g., a path-normalization pass that runs alongside the Pattern Mapping) violates the hard exclusion.

**Post-write backtick-preservation check:** diff the written Integration-section block against the upstream Integration-section block byte-for-byte. Any character-level difference — backticks stripped, whitespace adjusted, punctuation altered — halts the write. The Integration block is verbatim or the migration is wrong.

**Why hard-gated:** The `migrate-f01a70` run transformed Integration sections in `sdlc-archive.md:230,232`, `sdlc-create-agent.md:219`, `sdlc-ingest.md:398`, `sdlc-tests-create.md:250` — producing double-paren corruption in all four. Listing Integration sections as "informationally exempt" without a structural mask is equivalent to not listing them. The `migrate-fa70ef` run exposed the follow-on: the hard-exclusion mask blocked transformation but didn't block the transformer's ancillary backtick-normalization, which stripped inline backticks from 20+ Integration lines across the repo.

**Non-transformable paths — byte-verbatim preservation (added post-`migrate-fa70ef`):**

The following path prefixes are NEVER touched by the transformer — not for Pattern Mapping transformation, not for audit-description metadata transformation, not for backtick normalization, not for any reason:

- `[sdlc-root]/process/` — process docs live on disk in Neuroloom projects too
- `[sdlc-root]/templates/` — templates live on disk
- `[sdlc-root]/playbooks/` — playbooks live on disk
- `[sdlc-root]/agents/` — agents install to `.claude/agents/`
- `[sdlc-root]/knowledge/provenance_log.md` — project-specific on-disk file
- `skills/` — skill paths

**Byte-verbatim rule:** a file reference where the path prefix matches any of the above is preserved **character-for-character** from upstream, including:
- Surrounding inline backticks (`` `[sdlc-root]/process/manager-rule.md` ``)
- Escape sequences (`` \`[sdlc-root]/templates/test_spec_template.md\` ``)
- Surrounding quotes, parentheses, brackets
- Whitespace before and after

**Why this matters:** `migrate-fa70ef` showed backticks stripped from ~20 files' references to non-transformable paths (`skills/sdlc-execute/SKILL.md`, `process/manager-rule.md`, `process/debate-protocol.md`, etc.). Individually minor — a backtick here or there doesn't break a migration — but cumulatively visible in diffs against upstream and suggests the transformer isn't honoring the exempt list strictly. Explicit byte-verbatim preservation closes this.

**Post-write scan (non-transformable-path backtick audit):** for each non-transformable path prefix, grep for any occurrence of that path in the written content. For each hit, extract the ±5 surrounding characters. Compare byte-by-byte to the same surrounding characters in the upstream version. If any character differs and the path itself is unchanged, the transformer touched content it wasn't allowed to touch. Halt the write.

**Fenced code blocks are structurally exempt — HARD EXCLUSION:**

Everything between a ` ``` ` opening fence and its matching closing fence (same number of backticks) is exempt from ALL transformation, same scope as Integration sections above. This includes ` ```yaml `, ` ```json `, ` ```bash `, ` ``` ` (no language tag), and indented code blocks (lines starting with 4+ spaces inside a list context).

**Enforcement:** Before matching, the transformer must parse fence boundaries and mask all content between them. Post-write, assert: **the count of `memory_search(` / `memory_store(` calls inside fenced code blocks must equal the pre-merge count in the same blocks**. Any increase means the transformer inserted MCP into a code example — halt and report.

**Why hard-gated:** `migrate-f01a70` transformed a ```yaml ``` block in `sdlc-ingest.md:271-273`, producing syntactically broken YAML with nested double-quotes. YAML examples demonstrate file FORMAT; transforming them removes the example's informational value AND breaks the syntax.

**Capture-target rules must NEVER fire in `Read ...` contexts:**

Rows labelled `(as capture target)` or whose replacement begins with `memory_store with tags [...]` (e.g., plugin lines 115–117) describe WRITE destinations. They exist to transform "where to write new knowledge" sentences like `Append to [sdlc-root]/knowledge/<domain>/`. These rules MUST NOT match inside a `Read ...` instruction.

**The bug this prevents:** In the 2026-04-22 `migrate-f01a70` run, `AGENT_TEMPLATE.md:133` read upstream as:
```
Read `[sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml` for the handoff schema.
```
The matcher fired the capture-target wildcard `[sdlc-root]/knowledge/<domain>/` → `memory_store with tags [...]` against a fragment of the read path, producing:
```
Read memory_store with tags ["sdlc:knowledge", "sdlc:domain:architecture"] for the handoff schema.
```
This is doubly wrong: `memory_store` is the write API (can't be read), and the correct transformation for `Read [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml for <purpose>` is the specific rule added in the instruction table (`Call memory_search(query="...<purpose>", tags=[...])`).

**Matcher requirement:** When the enclosing sentence begins with `Read ` (or `read ` mid-sentence per match rule #1), the matcher must exclude capture-target rules from the candidate set entirely. Only instruction rules (those whose replacement begins with `memory_search(` or preserves a `Read`/`Call` verb) are eligible. If the only matching rule in a `Read` context is a capture-target row, the matcher emits a `TRANSFORMATION_WARNING` for a missing instruction rule rather than producing malformed output.

| cc-sdlc Metadata Pattern | Neuroloom Metadata Replacement |
|--------------------------|--------------------------------|
| `([sdlc-root]/knowledge/agent-context-map.yaml)` | `(memory graph, agents indexed by sdlc:agent:* tags)` |
| `([sdlc-root]/knowledge/**/*.yaml)` | `(memory graph, entries tagged sdlc:knowledge)` |
| `([sdlc-root]/knowledge/*.md)` | `(memory graph, entries tagged sdlc:knowledge)` |
| `([sdlc-root]/knowledge/<domain>/*.yaml)` | `(memory graph, entries tagged sdlc:knowledge and sdlc:domain:<domain>)` |
| `([sdlc-root]/knowledge/<domain>/)` | `(memory graph, entries tagged sdlc:knowledge and sdlc:domain:<domain>)` |
| `([sdlc-root]/disciplines/*.md)` | `(memory graph, entries tagged sdlc:discipline:*)` |
| `([sdlc-root]/disciplines/<name>.md)` | `(memory graph, entries tagged sdlc:discipline:<name>)` |
| `(e.g., [sdlc-root]/knowledge/<domain>/)` | `(e.g., memory entries tagged sdlc:knowledge + sdlc:domain:<domain>)` |
| `(e.g., [sdlc-root]/knowledge/<domain>/*.yaml)` | `(e.g., memory entries tagged sdlc:knowledge + sdlc:domain:<domain>)` |
| `(e.g., [sdlc-root]/disciplines/<name>.md)` | `(e.g., memory entries tagged sdlc:discipline:<name>)` |
| Bullet label + colon + path: `<Label>: [sdlc-root]/knowledge/agent-context-map.yaml` (e.g., `- Agent knowledge context: [sdlc-root]/knowledge/agent-context-map.yaml`) | `<Label>: memory graph (agents indexed by sdlc:agent:* tags)` |
| Bullet label + colon + path: `<Label>: [sdlc-root]/knowledge/<domain>/<file>.yaml` | `<Label>: memory entries tagged sdlc:knowledge + sdlc:domain:<domain>` |
| Bullet label + colon + path: `<Label>: [sdlc-root]/disciplines/<name>.md` | `<Label>: memory entries tagged sdlc:discipline:<name>` |
| Table cell containing `[sdlc-root]/knowledge/agent-context-map.yaml` (any column) | Cell becomes `memory graph (sdlc:agent:* tags)` |
| Table cell containing `[sdlc-root]/knowledge/<domain>/<file>.yaml` (any column) | Cell becomes `memory entries tagged sdlc:knowledge + sdlc:domain:<domain>` |
| Table cell containing `[sdlc-root]/knowledge/<domain>/` (any column, directory ref) | Cell becomes `memory entries tagged sdlc:knowledge + sdlc:domain:<domain>` |
| Table cell containing `[sdlc-root]/knowledge/**/*.yaml` or `[sdlc-root]/knowledge/*.md` (any column) | Cell becomes `memory entries tagged sdlc:knowledge` |
| Table cell containing `[sdlc-root]/disciplines/*.md` or `[sdlc-root]/disciplines/<name>.md` (any column) | Cell becomes `memory entries tagged sdlc:discipline:*` (or `:<name>`) |

**Exempt from metadata transformation:**
- `[sdlc-root]/process/` references (process files exist on disk in Neuroloom projects too)
- `[sdlc-root]/templates/` references (templates exist on disk)
- `[sdlc-root]/playbooks/` references (playbooks exist on disk)
- `[sdlc-root]/agents/` references (agents exist at `.claude/agents/` — handled by path transformation, not knowledge transformation)
- `[sdlc-root]/knowledge/provenance_log.md` references (on-disk append-only file, project-specific; treated like `process/sdlc_changelog.md`)
- Integration-section `**Depends on:**` / `**Uses:**` lists where the ref is an individual bullet rather than a parenthetical — these are kept verbatim as metadata; the agent understands they describe logical dependencies, not runtime file reads

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
- **Contract changes** — entries tagged `[contract-change]`, indicating a new or modified phrase in cc-sdlc's phrasing contract that may require updating the Pattern Mapping table in this skill (see "Neuroloom-Aware Content Transformation" above). Since cc-sdlc 1.3.0, structured contract changes are also recorded in `skeleton/contract_changes.yaml` — read that file alongside the changelog. Every `[contract-change]` tag in the migration range should have a corresponding entry in the YAML; missing correspondence on either side is a cc-sdlc source defect worth filing upstream.

Note any changelog items that reference CLAUDE.md sections, skill invocation patterns, or agent configurations — these require a CLAUDE.md compatibility check in Stage 4.

### 2.2a Contract Change Gate (deterministic semver check)

This gate is **fully deterministic** — it does not involve LLM judgment. The plugin's `.claude-plugin/plugin.json` declares `supported_ccsdlc_version`, the highest cc-sdlc version whose `[contract-change]` entries have been reviewed and reflected in this plugin's Pattern Mapping + post-op audit. The gate compares that declaration against each contract-change entry in the migration range.

**Dual source of truth (cc-sdlc 1.3.0+):** The gate reads both `[contract-change]` changelog entries AND `skeleton/contract_changes.yaml` entries. For each, the version threshold comparison against `PSV` is the same. An entry in either source that exceeds PSV triggers the halt. Phrasing-contract entries typically appear in both; skill renames / field additions / bundle debuts typically appear only in contract_changes.yaml. The gate treats the union as one set of contract changes — it does not matter which source surfaced a given entry.

**Rationale for determinism:** prior versions of this gate halted-or-auto-resolved based on prose interpretation at runtime. Two runs of the same migration against the same source/target versions produced different outcomes — one halted, another silently resolved with a free-form "pattern_mapping_already_updated" note. A gate that sometimes fires is worse than no gate; maintainers can't reason about when to trust it. This version replaces LLM judgment with a version comparison so behavior is reproducible.

**Procedure:**

1. Read `supported_ccsdlc_version` (call it `PSV`) from this plugin's `.claude-plugin/plugin.json`. If the field is missing, **HALT** — the plugin is non-conformant; it must declare its support level before any migration can safely run.

2. For each `[contract-change]` entry collected in Stage 2.2, extract the cc-sdlc version the entry belongs to (e.g., `v1.2.1` → `1.2.1`). The version is the first changelog heading at or above the entry in `process/sdlc_changelog.md`.

3. Compare each contract-change version to `PSV` using semver:
   - If `contract_change_version <= PSV` → the plugin declares support. Emit `contract_change_covered` to the transaction log and continue.
   - If `contract_change_version > PSV` → the plugin has not been updated for this entry. **HALT deterministically**, with the message below.

4. If all entries are covered, the gate is silent — no AskUserQuestion, no maintainer prompt. Stage 2.3's general migration confirmation still runs normally.

**Deterministic halt message (when `contract_change_version > PSV`):**

```
⚠ Contract Change Gate — plugin behind upstream

Plugin `{plugin_name}` declares supported_ccsdlc_version: {PSV}
Migration target is cc-sdlc {LATEST_VERSION}

The following [contract-change] entries are in the migration range but ABOVE the plugin's declared support level:
  - cc-sdlc {version}: {title}
    {summary}
  - ...

This is a hard, deterministic halt. The plugin's Pattern Mapping and post-op
audit must be reviewed against each listed contract change. After review,
bump `supported_ccsdlc_version` in plugin.json to the new level, push, and
re-run /sdlc-migrate. The gate will then auto-resolve.

Do NOT clear this halt by "eyeballing" the changelog — that re-introduces the
LLM-judgment non-determinism this gate was designed to replace.
```

**Transaction-log events:**
```
contract_change_covered   — per entry: {version, title, psv}
contract_change_uncovered — per entry on halt: {version, title, psv}
```

**Edge cases:**
- Pre-release versions (e.g., `1.2.3-rc.1`) compare via semver rules. A pre-release is less than its corresponding stable release.
- If the target cc-sdlc version is below PSV, no contract-change entries are in range — the gate is trivially silent.
- If the changelog has a `[contract-change]` tag without a version heading above it (malformed), treat as `uncovered` and halt. This also flags upstream changelog defects.

**What changing PSV means for the plugin maintainer:**
- Before bumping PSV, review every contract-change entry between old PSV and new PSV in cc-sdlc's changelog.
- Verify the Pattern Mapping has rules for each newly standardized phrase.
- Verify the post-op audit's forbidden-phrasings list (`references/post-operation-audit.md` Check 2a) has detectors for each newly forbidden phrase.
- Only then bump PSV. Bumping without verification means the gate will silently pass a broken migration — defeating the entire purpose of the determinism fix.

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

**Pass 2 scope — what counts as "prose":**

A region of text is "prose" (and thus subject to concept-terminology transformation) if ALL of these hold:
- It is NOT inside a fenced code block (```` ```...``` ````, any language)
- It is NOT inside inline backticks (`` `...` ``)
- It is NOT a YAML key, YAML value, JSON key, or JSON value (when the surrounding context is structured data, even if outside a fence — e.g., frontmatter fields)
- It is NOT a path reference matching `[sdlc-root]/...`, `.claude/...`, `ops/sdlc/...`, `skills/`, or similar
- It is NOT an MCP call already emitted by Pass 1 (`memory_search(...)`, `memory_store(...)`)
- It is NOT a Pattern Mapping replacement string from Pass 1 (e.g., `Neuroloom knowledge store (via memory_store)`)

Examples of text Pass 2 CAN transform:
- Integration-section parenthetical descriptors after a path: `` **Depends on:** `[sdlc-root]/disciplines/*.md` (parking lot entries for knowledge hygiene) `` — the path is Pass-1-exempt, but "parking lot entries for knowledge hygiene" is prose descriptor and Pass 2 rewrites it
- Heading bodies: `### 9a. Scan Related Parking Lot Entries` — Pass 2 rewrites to `### 9a. Scan Related Discipline Memory Entries`
- Prose paragraphs outside any path/fence/structured-data context
- Bullet text that doesn't contain a path or code

Examples of text Pass 2 MUST NOT transform:
- Inside ``` ```yaml ``` ``` fences — never, even if the content contains "knowledge/design/file.yaml" as a value
- Inline `` `[sdlc-root]/knowledge/agent-context-map.yaml` `` — path refs handled by Pass 1 (or hard-excluded)
- YAML frontmatter fields like `name:`, `description:`, `model:`
- MCP call arguments: `memory_search(query="parking lot entries tagged X", ...)` — the query string is an MCP call argument, not prose

**Pass 2 rules:** the concept-terminology rule class defined in § "Knowledge-layer concept terminology" of the Pattern Mapping section (above). Pass 2 applies those rules to matched prose regions.

**Pass 2 transaction log event:**
```json
{
  "ts": "ISO-8601",
  "run_id": "migrate-xxxxxx",
  "event": "concept_terminology_applied",
  "stage": "4.2-pass2",
  "file": "<install-path>",
  "substitutions": [
    {"rule": "<rule-label>", "before": "<snippet>", "after": "<snippet>", "region": "integration-descriptor|heading|prose"}
  ]
}
```

One event per file; includes an array of substitutions (may be empty if no concept-terminology rules fired). Emission is mandatory if Pass 1 wrote the file — absence of the event for a written file is a telemetry regression per Stage 5.0.

**Pass 2 halts on output regression:** after Pass 2 writes, re-run the existing post-write output-regression scans (orphan debris, double-paren, malformed verbs). If Pass 2 introduces any of those patterns, halt and roll back that file to its Pass 1 output — Pass 2 must only make prose-level concept translations; producing structural corruption is a rule bug.

**Fenced code blocks containing file-mode demos — deferred to 0.5.0:** Pass 2 intentionally does not modify fenced-block contents, even when those contents are file-mode demos (e.g., a ` ```yaml ` block demonstrating `mappings: ui-ux-designer: [paths]` in an adapter-unreachable format). Surrounding prose is transformed by Pass 2; the demo itself is preserved as cc-sdlc's original file-mode reference. Future work (0.5.0) may add an optional pre-fence annotation (e.g., *"In Neuroloom mode, the equivalent operation is `memory_store(..., tags=[...])`."*) as a demonstration-mapping rule class. Until then, fenced-block file-mode demos remain a project-specific customization zone — if your installation wants to replace the demo, wrap the whole fenced block in `PROJECT-SECTION` markers.

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

**Why this gate exists:** A 2026-04-22 migration regression overwrote 65 MCP calls across 44 files because the content-merge rules were inconsistent across file categories. This gate enforces uniform MCP preservation AND uniform forward transformation — every upstream file lands as Neuroloom-native in a Neuroloom project, whether it's new, newly-transformed, or merged with an existing MCP-bearing version.

**When this gate does NOT apply:**
- Project-specific files listed in "Project-Specific Files (Never Overwrite)" — those are skipped entirely
- Non-Neuroloom projects — this plugin is not installed in them; cc-sdlc's own sdlc-migrate handles those

---

Once the gate has been applied for a file, the following category-specific rules define additional handling (PROJECT-SECTION markers, review gates, etc.). None of them override the MCP preservation gate — if Step 3 kept the project's MCP sections, category rules only govern the non-MCP portions of the merged content.

#### Skills

**Plugin skills** (`sdlc-initialize`, `sdlc-migrate`): These are owned by `neuroloom-sdlc-plugin/skills/` — NOT `.claude/skills/`. Do not write cc-sdlc originals to `.claude/skills/`. If stale cc-sdlc originals exist from a prior installation, delete them:

```
rm -rf .claude/skills/sdlc-initialize/ .claude/skills/sdlc-migrate/
```

The plugin versions are the authoritative replacements, updated from the plugin repo, not cc-sdlc upstream.

**cc-sdlc core skills** (all other skills in `.claude/skills/`, including opt-in bundle skills listed in `.sdlc-manifest.json` → `installed_bundles`): Apply the §4.2.0 preservation gate. These skills frequently contain MCP calls injected during `/sdlc-port` (e.g., `sdlc-design-consult`, `research-external`, `sdlc-review-fix`, `sdlc-tests-create`, `sdlc-tests-run` all carry cross-domain knowledge injection that was transformed to `memory_search`). Do NOT assume core skills have no customizations — the gate will detect and preserve MCP content. Non-MCP framework sections update verbatim from upstream.

**Enhanced skills** (`sdlc-archive`, `sdlc-audit`): Apply the §4.2.0 preservation gate, then merge — keep Neuroloom-specific sections (API call patterns, MCP tool references, tag schema), update cc-sdlc sections (stage logic, verification checklists, red flags tables). Present a diff via `AskUserQuestion` if the Neuroloom sections appear to have been modified by the project.

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

**Framework agent files** (`AGENT_TEMPLATE.md`, `AGENT_SUGGESTIONS.md`, `sdlc-reviewer.md`, `sdlc-compliance-auditor.md`): Apply the §4.2.0 preservation gate. Non-MCP framework sections update verbatim from upstream. If `AGENT_SUGGESTIONS.md` doesn't exist in the project, install it.

**Project domain agents** (all other files in `.claude/agents/`): Apply the §4.2.0 preservation gate. The Knowledge Context and Communication Protocol sections of project agents contain MCP calls (injected during port/initialize) and MUST be preserved — do NOT blanket-rewrite them from the upstream template. The gate's section-level preservation handles this automatically. Preserve the agent name, domain description, scope ownership, anti-rationalization tables, and any project-added agents that do not exist in the upstream template set.

**Template upgrade (non-MCP changes):** The upstream template may introduce changes to non-MCP sections of `## Knowledge Context` or `## Communication Protocol` (e.g., `knowledge_feedback` was removed from the Knowledge Context section upstream). Apply those non-MCP changes only — do NOT re-inject file-path references into sections that already contain MCP calls.

If an upstream agent template was renamed: flag it. Do not silently overwrite a renamed agent.

#### Process docs

Apply the §4.2.0 preservation gate for every process doc. After the gate has produced the merged content, apply PROJECT-SECTION marker extraction/re-injection on top. Preserve files that were added by the project and have no upstream equivalent — identify these by checking `.sdlc-manifest.json` for the file origin.

**Never overwrite `process/agent-selection.yaml`** — this file contains the project's agent roster and dispatch rules with project-specific agent names. It becomes project-specific after initialization. If upstream added new entries (e.g., new infrastructure domains, new tier definitions), flag them for CD review rather than overwriting.

#### Templates

Apply the §4.2.0 preservation gate. Templates like `test_spec_template.md` contain `memory_search` references that guide test authors to retrieve knowledge — these MCP calls are the Neuroloom-transformed equivalents of cc-sdlc's file-based guidance and must be preserved.

#### `.sdlc-manifest.json`

Update the `sdlc_version` field to `LATEST_VERSION`. Preserve all project-specific fields. Add missing fields introduced in newer cc-sdlc versions if absent:

- `sdlc_root` — set to the detected SDLC root path (`ops/sdlc/` or `.claude/sdlc/`)
- `neuroloom_backend` — set to `true` if absent (load-bearing: `/sdlc-port` uses this to detect prior Neuroloom initialization)
- `installed_bundles` — back-fill from the Bundle Awareness detection (empty array if no bundles detected)
- `last_applied_contract_id` — back-fill to `"0000"` if absent (covers projects installed before cc-sdlc 1.3.0)

**Any `manifest_field_added` entry in the §4.3 pending_changes set** contributes its `field` + `default` to this back-fill list.

**Advance `last_applied_contract_id`** to the newest entry's `id` in the fetched `skeleton/contract_changes.yaml`. Do this only after §4.3 (contract-driven renames), bundle handling, and any other pending-change consumers have completed successfully — if any failed, leave the old id so the next migration retries. If `contract_changes.yaml` is absent from upstream (pre-1.3.0 cc-sdlc), skip this advancement.

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

#### Mandatory: Structural Content-Loss Audit

**This check is MANDATORY — it catches the failure mode that silently broke the `migrate-f01a70` run.**

MCP count can be preserved while structural content is lost. `migrate-f01a70` deleted 12 rows of Red Flags table body in `sdlc-develop-skill.md:224-234`, 5 steps of Library Verification procedure in `sdlc-plan.md:240-254`, and an entire dispatch-step body in `sdlc-review.md:49-59` — all while MCP counts stayed unchanged. The MCP Retention Audit (below) didn't catch these because they weren't MCP-bearing sections.

**Procedure:** For every file written in Stage 4.2, compute six structural counts from the **project's pre-merge version**, the **upstream version**, and the **final on-disk content**:

1. `heading_count` — number of lines matching `^#{1,6} ` (H1 through H6)
2. `table_row_count` — number of lines matching `^\|.*\|.*\|\s*$` inside any table (excludes header/separator rows)
3. `numbered_step_count` — number of lines matching `^\s*\d+\.\s+\*\*` (numbered steps with bold lead)
4. `fenced_block_count` — number of ` ``` ` delimiters divided by 2 (count of fenced code blocks)
5. `mandatory_step_count` (added post-`migrate-fa70ef`) — number of numbered-bold steps that appear within a section whose heading or lead-in contains the word `MANDATORY` (case-insensitive) or within a block opened by a line matching `^\*\*[^*]+\(MANDATORY[^)]*\):\*\*`. These are high-weight steps — losing one is always a regression regardless of tolerance.
6. `bullet_count` — number of lines matching `^\s*[-*] ` (dashes and asterisks; excludes table rows and inside fenced blocks)

**Comparison rules:**

For each count except `mandatory_step_count`:
- **`post == upstream`** → pass (expected state after a clean merge)
- **`post == project_pre_merge`** AND upstream differs → `mcp_preserved` merge kept project's version; verify this is intentional by checking if the difference is inside a preservation boundary (PROJECT-SECTION markers or MCP-bearing section)
- **`post < upstream` by more than 1**, and the delta doesn't match `project_pre_merge - upstream` → **CONTENT-MERGE REGRESSION**. Halt.
- **`post < upstream` by exactly 1** → **WARN but don't halt** — could be a legitimate one-off project customization. Log `structural_audit_warning` for review.

For `mandatory_step_count`:
- **`post < upstream` by any amount, with no PROJECT-SECTION around the lost step** → **ALWAYS REGRESSION**. No tolerance. MANDATORY-tagged content is labelled that way because the framework considers it non-optional; silently dropping it breaks the framework's intent even if the numeric delta is small.

**Why the `mandatory_step_count` addition:** `migrate-fa70ef` dropped the entire 5-step "Library verification (MANDATORY)" procedure in `sdlc-plan.md`, going from 11 numbered-bold steps upstream to 6 in sleeved. But the plain `numbered_step_count` regression check reported no issue because the absolute delta (5) was within the "maybe legitimate project customization" range when the plugin was evaluating only pre-vs-post (not pre-vs-upstream-vs-post). The `MANDATORY` flag in the heading tells us those steps are framework-required — dropping them is always wrong.

**Halt and report (regression case):**

```
CRITICAL: Structural content-loss regression detected
File: {path}
Count: {count_name}
Project pre-merge: {pre}
Upstream:          {upstream}
Written content:   {post}

Expected: post ≈ upstream (= {upstream})
Observed: post = {post} (lost {upstream - post} vs upstream)

{if count_name == 'mandatory_step_count':}
MANDATORY STEPS DROPPED — this halt has no tolerance. The lost steps are in a
section the framework marks as required (heading contains "MANDATORY" or the
block's lead-in is **Label (MANDATORY...):**).
{else:}
Likely cause: misaligned merge window replaced upstream content with a duplicate
of a different section. Inspect the merge output — typically the lost content
was replaced by a verbatim copy of an earlier or later section.
{endif}

Recovery:
1. git checkout -- {path} (restore pre-migration state)
2. Re-run /sdlc-migrate
3. If it reoccurs, the merge implementation has a section-alignment bug — file a plugin issue
```

**Log on pass:** Emit `structural_audit_complete` to the transaction log with all six counts for each file (`heading_count`, `table_row_count`, `numbered_step_count`, `fenced_block_count`, `mandatory_step_count`, `bullet_count`) and the aggregate totals.

**Mandatory event schema (added post-`migrate-fa70ef` — previous runs emitted events missing the `audit_result` field):**

```json
{
  "ts": "ISO-8601",
  "run_id": "migrate-xxxxxx",
  "event": "structural_audit_complete",
  "stage": "4.2-gate",
  "files_scanned": <int>,
  "regressions": <int>,
  "warnings": <int>,
  "legitimate_drops": <int>,
  "drops_detail": "<comma-separated>",
  "audit_result": "PASS | FAIL"   // REQUIRED — presence is checked by Stage 5.0 telemetry assertion
}
```

The `audit_result` field is required. `migrate-fa70ef` emitted the event without it — Stage 5.0's telemetry assertion must be extended to check that this field is present (not just that the event exists) and halts if missing. A `structural_audit_complete` event without `audit_result` is treated identically to a missing event — the run is blocked from declaring `run_complete`.

#### Mandatory: MCP Retention Audit

**This check is MANDATORY — it catches the failure mode that silently broke the 2026-04-22 migration.**

A drop in MCP count is not automatically a bug. Upstream may legitimately remove a section that had MCP calls (e.g., cc-sdlc retired the `knowledge_feedback` reference in AGENT_TEMPLATE.md). The audit must distinguish **regression** (merge bug lost MCP content whose enclosing section still exists upstream) from **legitimate removal** (upstream deleted the enclosing section entirely, or refactored it into a non-MCP form).

For every file written in Stage 4.2:

1. Count `memory_search(` + `memory_store(` in the **final on-disk content** → `MCP_COUNT_AFTER`
2. Recall `MCP_COUNT_BEFORE` from the §4.2.0 preservation gate transaction log
3. **If `MCP_COUNT_AFTER >= MCP_COUNT_BEFORE`:** pass, move to next file
4. **If `MCP_COUNT_AFTER < MCP_COUNT_BEFORE`:** a drop occurred. Classify it:

   **Classification procedure:**
   - Re-read the project's pre-migration version (via `git show HEAD:{path}` if uncommitted, or from the transaction log snapshot)
   - For each `memory_search(` / `memory_store(` call present in the project version but absent in the written content:
     - Identify the nearest preceding heading (nearest `#`/`##`/`###` above the call)
     - Check whether that heading exists in the upstream version of the file **using the same fuzzy heading matcher as §4.2.0 (numeric-stem → stem-before-parenthetical → slug)**. Using exact text here would mis-classify a preservation failure as "legitimate removal" whenever upstream simply rephrased the heading's parenthetical.
     - If the heading EXISTS upstream (by any matcher tier) and the upstream section does NOT contain an equivalent MCP call (after Pattern Mapping): **REGRESSION** — the preservation gate failed to preserve this section
     - If the heading is MISSING upstream (section removed/renamed, no tier hits) OR the upstream section has an equivalent MCP call that replaces this one: **LEGITIMATE REMOVAL** — upstream deleted or refactored the section; acceptable

5. **Aggregate classification:**
   - If any call is classified `REGRESSION` → this is a **critical failure**, halt migration
   - If all dropped calls are `LEGITIMATE REMOVAL` → pass, log each removal for the Stage 5 report

**Halt and report (regression case):**

```
CRITICAL: MCP preservation regression detected
File: {path}
Before: {N} MCP calls
After: {M} MCP calls
Lost: {N - M} call(s)

Regressions (heading still exists upstream, MCP should have been preserved):
- § {heading}: memory_search(query="{query}", tags=[...])
- § {heading}: memory_store(tags=[...])

Legitimate removals (heading removed upstream, acceptable):
- § {removed heading}: memory_search(...)

This migration would break Neuroloom knowledge retrieval. Aborting.
Recovery: git checkout -- {path} to restore; then re-run /sdlc-migrate after
updating Pattern Mapping rules in the plugin (or report a bug if the preservation
gate missed content it should have kept).
```

**Log and continue (legitimate removal case):**

Record each legitimate removal in the transaction log with entry type `mcp_removed_upstream`:
```
{file: "...", heading: "...", mcp_call: "memory_search(...)", reason: "upstream removed section"}
```

These appear in the Stage 5 report under "Upstream-driven MCP reductions" so CD is aware the call is gone but not surprised — the migration message explicitly explains each one.

**Aggregate report (both cases):**

```
MCP Retention Audit — Stage 4.2
Files scanned: {N}
Files with MCP preserved or increased: {M}
Files with legitimate upstream removals: {K} (details in transaction log)
Regressions detected: 0  ← MUST BE 0 TO PROCEED
Total MCP calls (before → after): {X} → {Y}
```

**Mandatory emission — `mcp_retention_audit_complete`:**

Before Stage 4.2 is considered finished, the audit MUST emit this event to the transaction log (no exceptions, no batching):

```json
{
  "ts": "ISO-8601",
  "run_id": "migrate-xxxxxx",
  "event": "mcp_retention_audit_complete",
  "stage": "4.2-gate",
  "mcp_before": <int>,
  "mcp_after": <int>,
  "net_delta": <int>,
  "files_scanned": <int>,
  "regressions": <int>,
  "legitimate_drops": <int>,
  "drops_detail": "<comma-separated summaries>",
  "audit_result": "PASS | FAIL"
}
```

If the audit is skipped (e.g., no files modified this run), the executor MUST still emit this event with `files_scanned: 0` and `audit_result: "PASS"` — so downstream tools can verify the gate was evaluated, not silently bypassed.

**Gate rule:** If regressions > 0, migration is halted. Do not proceed to Stage 4.3. Instruct CD to:
1. Review the regressed files listed in the transaction log
2. Restore them via `git checkout -- {paths}` (migration is uncommitted)
3. File a bug report against the plugin's Pattern Mapping table — the transformer missed a phrase that should have matched, OR the section-level preservation logic failed to identify the MCP section

If all drops are legitimate, the audit passes and the Stage 5 report surfaces them for CD awareness.

#### Quick sanity checks

1. **Skill customization preservation** — spot-check 1 enhanced skill (e.g., `sdlc-audit`):
   - Neuroloom-specific sections (API call patterns, MCP tool references) are intact
   - Framework sections were updated (compare against cc-sdlc source)

2. **Agent integrity** — spot-check 1 agent:
   - Framework-derived sections (Knowledge Context, Communication Protocol) retain their MCP calls if the project-side version had them
   - Domain-specific content (scope, principles, workflow) was preserved

3. **Audit skill completeness** — verify all `references/` files were updated and any project-specific audit dimensions preserved

**Gate rule:** If any check fails, fix the merge before continuing. Do not proceed to Stage 4.3 with corrupted content.

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

**Do NOT hardcode rename pairs in this skill.** Every rename goes in cc-sdlc's `contract_changes.yaml`. Adapter-maintainers: if you find yourself wanting to add a special case here, file an upstream PR adding the entry to `contract_changes.yaml` instead. The phrasing-contract Pattern Mapping table remains adapter-specific and lives here — that's the only rename-shaped data the adapter owns.

**CLAUDE-SDLC.md standalone cleanup:** If `[sdlc-root]/CLAUDE-SDLC.md` exists as a separate file (legacy from older installations), verify its content is already merged into `CLAUDE.md`, then remove it. CLAUDE-SDLC.md is no longer installed as a standalone file — its content lives directly in the project's CLAUDE.md.

**New CLAUDE-SDLC.md sections:** Compare the project's CLAUDE.md SDLC sections against the current upstream `CLAUDE-SDLC.md` source. If new sections were added upstream (e.g., new workflow rules, new verification policies), merge them into the project's CLAUDE.md.

For each stale reference found, either update it automatically (if the change is a clear 1:1 rename with a verified target) or flag it for CD review via `AskUserQuestion`.

If pending_changes is empty and no changelog items flagged CLAUDE.md-relevant changes, this check is a no-op — report "No CLAUDE.md updates needed."

### 4.4 Sentinel

The sentinel is managed SERVER-SIDE by `seed()`. Do not create, update, or tag it manually. The server updates the sentinel's `sdlc:seed-version:{version}` tag automatically when the knowledge re-seed completes. After Stage 4.1 completes, re-read the sentinel via `memory_search(query="SDLC workspace sentinel", tags=["sdlc:sentinel"])` to confirm the server updated it.

---

## Stage 5 — Verification + Compliance Audit + Report

### 5.0 Telemetry Assertion (pre-flight for Stage 5)

Before any verification runs, assert the Stage 4.2 telemetry is intact. This catches the silent-bypass failure mode where the executor skipped per-file emission and the MCP Retention Audit summary event.

**Procedure:**

1. Read the transaction log entries for this `run_id`.
2. Count events of each required type:
   - `file_merged` — MUST equal the number of files written in stage 4.2 (cross-check against the change manifest). Zero is only acceptable if the change manifest says no operational files changed. (Pass 1 event.)
   - `concept_terminology_applied` — MUST equal the `file_merged` count for Neuroloom-backend projects (new in 0.4.0; every file Pass 1 wrote must also have a Pass 2 event, even if no substitutions fired). For non-Neuroloom projects (`neuroloom_backend: false`), this count MUST be exactly 0 because Pass 2 only runs in Neuroloom mode.
   - `mcp_retention_audit_complete` — MUST be exactly 1 with `audit_result: "PASS"` present. Zero means the audit gate was bypassed; missing the `audit_result` field means schema regression.
   - `structural_audit_complete` — MUST be exactly 1 with `audit_result: "PASS"` present. Same rules as mcp_retention.
3. If any count is wrong or any required field is missing, **halt** the migration with:

```
TELEMETRY REGRESSION — Stage 4.2 audit trail incomplete.

Expected: {N} file_merged events, {N} concept_terminology_applied events,
          1 mcp_retention_audit_complete event (with audit_result),
          1 structural_audit_complete event (with audit_result)
Found:    {M} file_merged, {P} concept_terminology_applied,
          {K} mcp_retention_audit_complete, {S} structural_audit_complete

{if counts mismatch between file_merged and concept_terminology_applied:}
  Pass 2 (Prose Concept-Terminology) was skipped or partial. Pass 2 is
  mandatory for Neuroloom-backend projects — concept-terminology leaks
  (file-speak in prose descriptions of the knowledge layer) go undetected
  without it.
{endif}

Stage 4.2 ran but did not emit the mandatory audit trail. The migration
cannot declare run_complete because there is no record that the mandatory
audit gates evaluated the written files.

Recovery:
1. git checkout -- .claude/ (restore pre-migration state)
2. File a plugin bug with this run_id: {run_id}
3. Re-run /sdlc-migrate after the executor is fixed
```

Do NOT proceed to 5.1 unless all counts match. Do NOT emit `run_complete` without this assertion passing.

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

### 5.2a Post-Operation Audit

**Run the shared post-operation audit** at `${CLAUDE_PLUGIN_ROOT}/references/post-operation-audit.md`. Execute the shared checks AND the `/sdlc-migrate`-specific subset.

The audit cross-verifies what §4.2-gate already caught at the per-file level by applying aggregate and cross-file checks:
- MCP integration health across the full installation
- Residual cc-sdlc standard phrases that should have been transformed
- Inline adapter conditionals that violate the contract
- Manifest-to-filesystem hash consistency
- Knowledge layer sentinel state

**If the audit fails:** Halt. Do NOT proceed to §5.3. Follow the audit's recovery instructions. Typical recovery for migrate is `git checkout -- .claude/` (migration is uncommitted at this point).

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
| cc-sdlc core skills | §4.2.0 MCP gate + marker preservation | Port injects MCP calls into many core skills; must preserve |
| Plugin skills (initialize, migrate, port) | Always overwrite | Maintained in this plugin repo |
| Enhanced skills (archive, audit) | §4.2.0 MCP gate + merge | Contain Neuroloom-specific API sections |
| Agent files (framework: template, suggestions, reviewer, auditor) | §4.2.0 MCP gate | Preserve MCP patterns, update non-MCP sections |
| Agent files (project domain agents) | §4.2.0 MCP gate + non-MCP tailoring update | Framework sections update outside MCP; domain desc preserved |
| Agent files (project-added) | Skip | No upstream equivalent — never touch |
| Process docs (upstream originals) | §4.2.0 MCP gate + marker preservation | Many process docs have MCP calls; preserve before overwriting |
| `process/agent-selection.yaml` | **Never overwrite** | Project-specific agent roster and dispatch rules |
| Process docs (project-added) | Skip | No upstream equivalent |
| Knowledge YAMLs | Server-side upsert | `knowledge_id` matching handles new/updated/unchanged/deprecated |
| `knowledge/provenance_log.md` | **Never overwrite/ingest** | Project-specific append-only records |
| Discipline files | §4.2.0 MCP gate + preserve parking lots | Update framework sections, preserve project entries and MCP calls |
| `.sdlc-manifest.json` | Partial update | Update version + add missing fields (`sdlc_root`, `neuroloom_backend`, `installed_bundles`, `last_applied_contract_id`) |
| `hooks/` files | Always overwrite | Plugin-managed; no project customizations |
| `CLAUDE.md` SDLC section | Targeted update + guarded renames | Only stale references; preserve project additions |
| Standalone `CLAUDE-SDLC.md` | Delete | Legacy file; content merged into CLAUDE.md |
| Templates | §4.2.0 MCP gate | `test_spec_template.md` and others contain `memory_search` references |

**§4.2.0 MCP gate:** Before every file write, count `memory_search(` + `memory_store(` occurrences in the project's current version. If > 0, apply Neuroloom-preserving merge (Pattern Mapping + section-level preservation). See Stage 4.2.0 for full procedure. See §4.2-gate for the mandatory post-write MCP Retention Audit.

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
| "Core cc-sdlc skills have no project customizations, I can overwrite them." | FALSE for Neuroloom projects. `/sdlc-port` injects MCP calls into `sdlc-design-consult`, `sdlc-review-fix`, `sdlc-tests-create`, `sdlc-tests-run`, `research-external`, and others. Every file write in §4.2 must pass the §4.2.0 MCP preservation gate — no exceptions by category. |
| "Process docs are framework-only, direct-copy is fine." | Process docs like `discipline_capture.md`, `overview.md`, `incident_response.md` contain MCP call patterns after port/initialize. The §4.2.0 gate applies to them too. |
| "Templates are boilerplate, no MCP there." | FALSE. `test_spec_template.md` guides authors to retrieve knowledge via `memory_search` in Neuroloom projects. Apply §4.2.0. |
| "I'll just run the content-merge and trust the rules worked." | Always run the MCP Retention Audit (§4.2-gate). A silent regression that drops `memory_search` calls breaks knowledge retrieval in every subsequent session with no visible symptom until an agent fails to find what it needs. |
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
