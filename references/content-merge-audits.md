# Content-Merge Verification Audits

These audits run in the `post-file-write` handler (`adapter-lifecycle.md`). The `neuroloom-transformer` runs them after it has processed every file in its dispatch list and before it returns its report to upstream. A HALT fails the phase, and `post-file-write` is `halt` on failure.

#### Mandatory: Structural Content-Loss Audit

**This check is MANDATORY — it catches the failure mode that silently broke the `migrate-f01a70` run.**

MCP count can be preserved while structural content is lost. `migrate-f01a70` deleted 12 rows of Red Flags table body in `sdlc-develop-skill.md:224-234`, 5 steps of Library Verification procedure in `sdlc-plan.md:240-254`, and an entire dispatch-step body in `sdlc-review.md:49-59` — all while MCP counts stayed unchanged. The MCP Retention Audit (below) didn't catch these because they weren't MCP-bearing sections.

**Procedure:** For every file in the dispatch list, compute six structural counts from the **project's pre-merge version**, the **upstream version**, and the **final on-disk content**:

1. `heading_count` — number of lines matching `^#{1,6} ` (H1 through H6)
2. `table_row_count` — number of lines matching `^\|.*\|.*\|\s*$` inside any table (excludes header/separator rows)
3. `numbered_step_count` — number of lines matching `^\s*\d+\.\s+\*\*` (numbered steps with bold lead)
4. `fenced_block_count` — number of ` ``` ` delimiters divided by 2 (count of fenced code blocks)
5. `mandatory_step_count` (added post-`migrate-fa70ef`) — number of numbered-bold steps that appear within a section whose heading or lead-in contains the word `MANDATORY` (case-insensitive) or within a block opened by a line matching `^\*\*[^*]+\(MANDATORY[^)]*\):\*\*`. These are high-weight steps — losing one is always a regression regardless of tolerance.
6. `bullet_count` — number of lines matching `^\s*[-*] ` (dashes and asterisks; excludes table rows and inside fenced blocks)

**Comparison rules:**

For each count except `mandatory_step_count`:
- **`post == upstream`** → pass (expected state after a clean merge)
- **`post == project_pre_merge`** AND upstream differs → `mcp_preserved` merge kept project's version; verify this is intentional by checking if the difference is inside a preservation boundary (PROJECT-SECTION markers, a target a `replaces` block or `PROJECT-SECTION-REMOVED` line names, or MCP-bearing section)
- **`post < upstream` by more than 1**, and the delta doesn't match `project_pre_merge - upstream` → **CONTENT-MERGE REGRESSION**. Halt. Before halting, take out of the upstream count what the project's marks set aside: a section a ``PROJECT-SECTION-START: <label> replaces `<target>` `` block stands in for, and a section a ``PROJECT-SECTION-REMOVED: <label> `<target>` `` line names, are absent by the project's marked choice (z-sdlc `process/project-section-markers.md` § The Three Kinds of Change).
- **`post < upstream` by exactly 1** → **WARN but don't halt** — could be a legitimate one-off project customization. Log `structural_audit_warning` for review.

For `mandatory_step_count`:
- **`post < upstream` by any amount, with no PROJECT-SECTION around the lost step, and no `replaces` block or `PROJECT-SECTION-REMOVED` line naming its section** → **ALWAYS REGRESSION**. No tolerance. MANDATORY-tagged content is labelled that way because the framework considers it non-optional; silently dropping it breaks the framework's intent even if the numeric delta is small.

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

Recovery: the operation's, in adapter-lifecycle.md § Halts and their recoveries
(on /sdlc-initialize, after the fix, re-dispatch the transformer on {path}).
If it reoccurs, the merge implementation has a section-alignment bug — file a plugin issue
```

**Log on pass:** Emit `structural_audit_complete` to the transaction log with all six counts for each file (`heading_count`, `table_row_count`, `numbered_step_count`, `fenced_block_count`, `mandatory_step_count`, `bullet_count`) and the aggregate totals.

**Mandatory event schema (added post-`migrate-fa70ef` — previous runs emitted events missing the `audit_result` field):**

```json
{
  "ts": "ISO-8601",
  "run_id": "migrate-xxxxxx",
  "event": "structural_audit_complete",
  "phase": "post-file-write",
  "files_scanned": <int>,
  "regressions": <int>,
  "warnings": <int>,
  "legitimate_drops": <int>,
  "drops_detail": "<comma-separated>",
  "audit_result": "PASS | FAIL"   // REQUIRED — presence is checked by the `post-operation` telemetry assertion
}
```

The `audit_result` field is required. `migrate-fa70ef` emitted the event without it. The `post-operation` telemetry assertion (end of this file) must check that the field is present, not just that the event exists. A `structural_audit_complete` event without `audit_result` counts as a missing event.

#### Mandatory: PROJECT-SECTION Preservation Audit

**This check is MANDATORY — it catches the failure mode that silently dropped a project-specific dispatch block in the v1.5.4 migration.**

PROJECT-SECTION marker blocks contain project-specific customizations (custom agent dispatches, pipeline enrichment scans, project-specific workflow steps) that `sdlc-migrate` preserves during content-merge. The transformer must not drop them during Pattern Mapping — they may not contain MCP calls and thus are invisible to the MCP Retention Audit.

For every file in the dispatch list:

1. Count `PROJECT-SECTION-START` markers and `PROJECT-SECTION-REMOVED` lines in the **project's pre-merge version** → `MARKER_COUNT_BEFORE` (from the transformer's Step 2a extraction)
2. Count `PROJECT-SECTION-START` markers and `PROJECT-SECTION-REMOVED` lines in the **final on-disk content** → `MARKER_COUNT_AFTER`

Marks inside fenced code blocks are examples and aren't counted.
3. **If `MARKER_COUNT_AFTER == MARKER_COUNT_BEFORE`:** pass
4. **If `MARKER_COUNT_AFTER < MARKER_COUNT_BEFORE`:** → **HALT**. Report each lost marker by label.

**Halt and report:**

```
CRITICAL: PROJECT-SECTION marker(s) lost during transformation
File: {path}
Before: {N} PROJECT-SECTION blocks
After: {M} PROJECT-SECTION blocks
Lost: {N - M} block(s)

Lost blocks:
- {label}: under heading "§ {heading}" — {first 80 chars of content}

This is project-specific content that sdlc-migrate preserved but the transformer
silently dropped. The transformer's Step 2a extraction failed to capture this block,
or Step 3 re-injection failed to place it.

Recovery: the operation's, in adapter-lifecycle.md § Halts and their recoveries
(on /sdlc-initialize, after the fix, re-dispatch the transformer on {path}).
```

**Log on pass:** Emit `project_section_audit_complete` with `marker_count_before`, `marker_count_after`, `audit_result: "PASS"`.

#### Mandatory: MCP Retention Audit

**This check is MANDATORY — it catches the failure mode that silently broke the 2026-04-22 migration.**

A drop in MCP count is not automatically a bug. Upstream may legitimately remove a section that had MCP calls (e.g., z-sdlc retired the `knowledge_feedback` reference in agent-template.md). The audit must distinguish **regression** (merge bug lost MCP content whose enclosing section still exists upstream) from **legitimate removal** (upstream deleted the enclosing section entirely, or refactored it into a non-MCP form).

For every file in the dispatch list:

1. Count `memory_search(` + `memory_store(` in the **final on-disk content** → `MCP_COUNT_AFTER`
2. Recall `MCP_COUNT_BEFORE` from the transformer's Step 2b MCP preservation gate (`agents/neuroloom-transformer.md`)
3. **If `MCP_COUNT_AFTER >= MCP_COUNT_BEFORE`:** pass, move to next file
4. **If `MCP_COUNT_AFTER < MCP_COUNT_BEFORE`:** a drop occurred. Classify it:

   **Classification procedure:**
   - Re-read the project's pre-migration version (via `git show HEAD:{path}` if uncommitted, or from the transaction log snapshot)
   - For each `memory_search(` / `memory_store(` call present in the project version but absent in the written content:
     - Identify the nearest preceding heading (nearest `#`/`##`/`###` above the call)
     - Check whether that heading exists in the upstream version of the file **using the same fuzzy heading matcher as the Step 2b preservation gate (numeric-stem → stem-before-parenthetical → slug)**. Using exact text here would mis-classify a preservation failure as "legitimate removal" whenever upstream simply rephrased the heading's parenthetical.
     - If the heading EXISTS upstream (by any matcher tier) and the upstream section does NOT contain an equivalent MCP call (after Pattern Mapping): **REGRESSION** — the preservation gate failed to preserve this section
     - If the heading is MISSING upstream (section removed/renamed, no tier hits) OR the upstream section has an equivalent MCP call that replaces this one: **LEGITIMATE REMOVAL** — upstream deleted or refactored the section; acceptable

5. **Aggregate classification:**
   - If any call is classified `REGRESSION` → this is a **critical failure**, halt migration
   - If all dropped calls are `LEGITIMATE REMOVAL` → pass, log each removal for the report the handler returns

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
Recovery: the operation's, in adapter-lifecycle.md § Halts and their recoveries, after
updating Pattern Mapping rules in the plugin (or reporting a bug if the preservation
gate missed content it should have kept).
```

**Log and continue (legitimate removal case):**

Record each legitimate removal in the transaction log with entry type `mcp_removed_upstream`:
```
{file: "...", heading: "...", mcp_call: "memory_search(...)", reason: "upstream removed section"}
```

These appear in the report the handler returns, under "Upstream-driven MCP reductions" so CD is aware the call is gone but not surprised — the migration message explicitly explains each one.

**Aggregate report (both cases):**

```
MCP Retention Audit
Files scanned: {N}
Files with MCP preserved or increased: {M}
Files with legitimate upstream removals: {K} (details in transaction log)
Regressions detected: 0  ← MUST BE 0 TO PROCEED
Total MCP calls (before → after): {X} → {Y}
```

**Mandatory emission — `mcp_retention_audit_complete`:**

Before the `post-file-write` phase is considered finished, the audit MUST emit this event to the transaction log (no exceptions, no batching):

```json
{
  "ts": "ISO-8601",
  "run_id": "migrate-xxxxxx",
  "event": "mcp_retention_audit_complete",
  "phase": "post-file-write",
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

**Gate rule:** If regressions > 0, the phase halts and migration stops. Instruct CD to:
1. Review the regressed files listed in the transaction log
2. Follow the operation's recovery (`adapter-lifecycle.md` § Halts and their recoveries); on an initialize, re-dispatch the transformer on them after the fix
3. File a bug report against the plugin's Pattern Mapping table — the transformer missed a phrase that should have matched, OR the section-level preservation logic failed to identify the MCP section

If all drops are legitimate, the audit passes and the handler's report surfaces them for CD awareness.

#### Mandatory: Stale Agent Reference Audit

**This check is MANDATORY — it catches the failure mode that silently broke `migrate-6f4217` (sleeved 2026-04-26) at `team-communication-protocol.md`, `sdlc-debug-incident.md`, `sdlc-plan.md`, and ~10 other framework files where agent-name examples don't resolve to the project's actual `.claude/agents/` roster.**

z-sdlc framework content names canonical agents in examples and dispatch maps — `security-engineer`, `data-architect`, `ml-engineer`, `devops-engineer`, etc. Projects often have a different roster (sleeved has `infosec-engineer` instead of `security-engineer`, `firebase-architect` instead of `data-architect`). When the migration writes upstream framework content verbatim, those canonical names land on disk pointing at agents the project never adopted. Result: skills dispatch agents that don't exist, message envelopes reference unknown reviewers, debug-incident routing tables misroute. The bugs are silent at write time; they surface as runtime dispatch failures days or weeks later.

**Procedure (runs after the transformer has written every file in its dispatch list):**

1. **Build the project agent roster:** scan `<target>/.claude/agents/` for `*.md` files; strip `.md` to get the roster set (e.g., `{accessibility-auditor, ai-engineer, backend-developer, infosec-engineer, ...}`).

2. **Read project-side rename declarations** from `<target>/.sdlc-manifest.json` → `agent_renames` (a new optional field; absent = empty map). The schema is `{"<canonical-name>": "<project-name>", ...}` — e.g., `{"security-engineer": "infosec-engineer", "data-architect": "firebase-architect"}`. These declarations let projects map z-sdlc canonical names to their renamed equivalents without touching framework content.

3. **Scan every file in the dispatch list** (skills, process docs, templates — exclude exempt files and project-specific files that aren't framework content). Use these patterns to extract candidate agent references:

   - Backtick-quoted role names: `` `<name>-engineer` ``, `` `<name>-developer` ``, `` `<name>-architect` ``, `` `<name>-designer` ``, `` `<name>-auditor` ``, `` `<name>-specialist` ``, `` `<name>-advisor` ``, `` `<name>-strategist` ``, `` `<name>-researcher` ``, `` `<name>-reviewer` ``, `` `<name>-officer` `` (added post-`migrate-0957db` 2026-04-26 — sleeved Flag 4 had `chief-product-officer` and `brand-officer` in `templates/decision_record_template.md` and `skills/sdlc-design-brand-asset/SKILL.md`)
   - Message envelope quoted values: `"reviewer-<name>"`, `"fixer-<name>"`, `"architect-<name>"` (strip prefix; use bare name for resolution)
   - YAML/dispatch-map keys: lines like `<name>-engineer:` or `specialist: <name>-engineer` inside fenced YAML blocks
   - Plain-prose role mentions inside dispatch tables (e.g., "auth → security-engineer")

4. **For each candidate agent name, classify:**

   a. **Resolves directly:** the bare name is a key in the project roster — no action.
   b. **Resolves via `agent_renames`:** the canonical name appears in `agent_renames` and the mapped name is in the roster — emit `agent_substituted` event and rewrite the reference in-place to the mapped name.
   c. **Stale, dispatch-position context:** the name doesn't resolve, AND the surrounding context is a dispatch instruction (e.g., a `Dispatch ...` instruction, a `from:`/`to:` field in a message envelope example, a routing-table key in `agent-selection.yaml`-shaped fenced YAML, or a Step-N "Spawn `<name>` as a teammate" instruction). **HALT** — these will fail at runtime.
   On `operation: initialize`, an unresolved name is a WARN, never a HALT: z-sdlc 3.0.0 sends Phase 1's copies through `post-file-write` before Phase 4 creates the project's agents, so the roster then holds only the framework's agents and there is no manifest to read `agent_renames` from.
   d. **Stale, descriptive context:** the name doesn't resolve, AND the surrounding context is descriptive prose (e.g., "consult security-engineer for auth issues", "(e.g., ml-engineer)", an example list item under a heading like "Common dispatch domains"). Emit `agent_unresolved_warning` event but do NOT halt — these don't break runtime, but CD should review whether to declare a rename or accept the stale reference.

5. **Substitution scope and limits:**
   - Substitution applies only to whole-token matches (`security-engineer` doesn't match `security-engineer-2` or `security-engineering`)
   - Substitution preserves the surrounding prefix (`reviewer-security-engineer` → `reviewer-infosec-engineer`)
   - Substitution does NOT cross the exempt-file boundary — files on the verbatim list (`process/knowledge-routing.md` etc.) are scanned for warnings but never rewritten
   - Substitution does NOT apply inside fenced code blocks marked as upstream-z-sdlc-canonical examples (a future fence annotation `<!-- canonical-example -->` will signal "leave verbatim regardless of project roster"; until that lands, fenced YAML blocks default to substituted)

**Halt and report (dispatch-position case):**

```
CRITICAL: Stale agent reference in dispatch-position context

File: <path>:<line>
Reference: <name>
Context: <one-line surrounding text>

Project roster (.claude/agents/): <count> agents
  <agent1>, <agent2>, ... <agentN>

The reference does not resolve and is in a dispatch position. At runtime,
the dispatching skill will spawn an agent that doesn't exist.

Resolution options:
1. If your project renamed this agent, declare it in .sdlc-manifest.json:
     "agent_renames": {"<name>": "<your-project-name>"}
   then re-run the operation (its recovery: adapter-lifecycle.md § Halts and their recoveries).
2. If your project doesn't have an equivalent, the framework content references
   a domain you don't cover. Either add the agent (project work) or accept the
   limitation (framework content will reference an unimplemented role).
3. To proceed despite the unresolved reference: explicitly add it to the
   manifest's "agent_unresolved_accepted" list (also new field). The audit
   will surface it as a warning instead of halting.

Recovery: the operation's, in adapter-lifecycle.md § Halts and their recoveries
```

**Log on pass or warn:** Emit the mandatory event below regardless of outcome.

**Mandatory event schema:**

```json
{
  "ts": "ISO-8601",
  "run_id": "migrate-xxxxxx",
  "event": "agent_resolution_audit_complete",
  "phase": "post-file-write",
  "roster_size": <int>,
  "files_scanned": <int>,
  "candidates_found": <int>,
  "resolved_direct": <int>,
  "resolved_via_renames": <int>,
  "halt_class": <int>,
  "warn_class": <int>,
  "accepted_class": <int>,
  "renames_applied": [{"file": "...", "line": <int>, "from": "...", "to": "..."}],
  "unresolved_dispatch": [{"file": "...", "line": <int>, "name": "...", "context": "..."}],
  "unresolved_descriptive": [{"file": "...", "line": <int>, "name": "...", "context": "..."}],
  "audit_result": "PASS | FAIL"
}
```

**Audit implications:**
- Missing event = the audit didn't run; treat as a telemetry regression in the `post-operation` telemetry assertion (below)
- `audit_result: "FAIL"` means at least one halt-class reference was found — the phase halts
- `warn_class > 0` should be surfaced in the migration report (`sdlc-migrate` §4.6) so CD can decide whether to declare additional renames
- `resolved_via_renames` events provide audit trail for any substitution applied — CD can verify the rename was intentional

**Why hard-gated:** sleeved's `migrate-6f4217` produced ~11 stale agent references in framework content (`security-engineer`, `data-architect`, `ml-engineer`, `db-engineer`, `devops-engineer`, `frontend-engineer`, `data-pipeline-engineer`, `database-architect`, `ml-architect`, `security-auditor`, `systems-engineer`). The user discovered them by manually diffing `team-communication-protocol.md` weeks after the migration completed. The guarded-rename rules (`sdlc-migrate` §4.3a, restricted to `contract_changes.yaml`-driven `rename_skill` entries) didn't fire because there was no contract change driving these — they were project-roster drift, not z-sdlc renames. This new gate covers the proactive case: every reference, every file, every migration.

**Schema migration for `agent_renames`:** Plugin 0.4.7+ recognizes the field. Older manifests (no field) default to empty. Adding the field is non-breaking — projects that don't declare any renames get the same behavior as before, except the audit now halts on dispatch-class stale refs. Projects that need to substitute should declare the renames before running migrate; the audit's halt message points them at the field.

#### Mandatory: Contract Residue Audit

**This check is MANDATORY — it catches the failure mode where a file is written with untransformed z-sdlc canonical phrasing despite being a Neuroloom-backend installation. Specifically targets the `mcp_new_file` install path where there's no pre-existing project version to merge against and Pattern Mapping silently bypasses.**

The transformer is meant to run Pattern Mapping on every file in a Neuroloom project, whether or not the project already had MCP calls, so new files and previously-untransformed files get transformed too. In practice, sleeved `migrate-6f4217` wrote `incident-runbook-template.md` (a new-file install introduced upstream after sleeved's previous migration) with untransformed `[sdlc-root]/knowledge/architecture/debugging-methodology.yaml` and `[sdlc-root]/knowledge/architecture/error-cascade-methodology.yaml` references. Pattern Mapping never fired for that file. The existing post-write regression scans (orphan debris, double-paren, malformed verbs) all passed because the upstream content was clean — it just hadn't been transformed.

This audit is the catch-all for Pattern Mapping bypass: *if upstream has canonical phrasing AND the post-write content still has it AND the file is non-exempt, the transformer didn't run.*

**Procedure (runs after the transformer has written every file in its dispatch list, including Pass 2):**

For every file in the dispatch list whose `subtype` is neither `exempt_verbatim` nor `exempt_row_rewrite` (this includes `.claude/skills/*/references/*.md`; `process/path-mappings.md` names the paths on purpose, and only its provenance row is rewritten), scan output for three residue classes:

1. **Path-bearing residue (Pass 1 territory):**
   ```bash
   grep -nE '\[sdlc-root\]/(knowledge|disciplines)/' <written-file>
   ```
2. **Concept-terminology residue (Pass 2 territory) — case-insensitive to catch heading title-case:**
   ```bash
   grep -inE '\bknowledge files?\b|\bdiscipline files?\b|\bparking[- ]lot entr|\bknowledge stores?\b|\bknowledge-store entr|\bdiscipline parking lots?\b|\bknowledge YAMLs?\b|\bYAML knowledge files?\b|\bagent-context-map\b|\bknowledge area\b|\bsuggested knowledge area\b' <written-file>
   ```

   **Why these specific extensions (added post-`migrate-0957db` 2026-04-26 review):**
   - `parking[- ]lot` (with `[- ]` character class) catches both `parking lot` and `parking-lot` — sleeved Flag 10 had `discipline parking-lot entry` (line 287) and `parking-lot memory entries` (line 357) that the space-only form missed.
   - `knowledge-store entr` (hyphenated compound) catches `knowledge-store entries` / `knowledge-store entry` — sleeved Flag 10 lines 265, 283.
   - `-i` (case-insensitive) catches title-cased headings — `Knowledge Stores`, `Discipline Parking Lots`, `Knowledge YAML addition` from sleeved Flag 9 lines 60, 90, 484, 491. Without `-i`, lowercase-only patterns miss heading body text.
   - `knowledge area` / `suggested knowledge area` catches the `Suggested knowledge area: [sdlc-root]/knowledge/architecture/` template prose pattern from sleeved Flag 10 line 298. The path-residue grep would catch the path on the same line, but the audit's defect detail benefits from naming the specific concept-terminology rule that should have fired.

3. **Wildcard-in-tag-argument residue (a Pass 1 output defect):**
   ```bash
   grep -nE 'tag(s|_prefixes)=\[[^]]*\*' <written-file>
   ```
   `tags` and `tag_prefixes` match literally, so a `*` inside either list makes the call return nothing. Any hit is a **defect**, never exempt (the only files that may quote the old form are the changelog and its archive, which are hard-excluded and never scanned).

For each path-bearing or concept-terminology hit, classify:

- **Exempt, and not exempt — exactly the rows of the table in `post-operation-audit.md` Check 2** (the `sdlc-migrate` path-mapping lines, the backtick-quoted span of `- [ ] No` checklist items, the four process docs, the changelog and its archive, and fenced format/command demos). That table is the single list for every path-bearing hit; this audit does not keep a second one. Three consequences it spells out, repeated here because this audit used to get them the other way round: (1) an Integration-section `[sdlc-root]/knowledge/` or `[sdlc-root]/disciplines/` path is a **defect**, not exempt (the Pass 1 carve-out rewrites it; sleeved's migration to z-sdlc 2.2.0 carried seven such lines because this class used to be exempt); (2) a ```` ```markdown ```` or untagged fence holding a prompt sent to a dispatched agent is a **defect** (`pattern-mapping-rules.md` § "Dispatch-prompt template blocks"); (3) a ```` ```yaml ````/```` ```json ````/```` ```bash ```` fence, or a ```` ```markdown ```` fence that demonstrates an entry format, is exempt (row 5).
- **Warn-class — YAML mechanism context:** the hit is in `sdlc-ingest/SKILL.md` and the surrounding sentence describes the file-mode YAML format that ingest consumes (e.g., "Existing knowledge: [count] YAML files"). Distinguishing signal: the sentence's subject is the upstream file format, not a Neuroloom-mode operation. Surface as warning, do not halt — CD reviews and either accepts or migrates the language.
- **Defect — Pattern Mapping bypass:** the hit is in operational prose describing Neuroloom-mode operation. The transformer either didn't fire on this file or has a coverage gap. **Halt.**

**Mandatory event schema:**

```json
{
  "ts": "ISO-8601",
  "run_id": "migrate-xxxxxx",
  "event": "contract_residue_audit_complete",
  "phase": "post-file-write",
  "files_scanned": <int>,
  "path_residue_hits": <int>,
  "concept_residue_hits": <int>,
  "tag_wildcard_hits": <int>,
  "exempt_hits": <int>,
  "warn_hits": <int>,
  "defect_hits": <int>,
  "details": [
    {"file": "...", "line": <int>, "phrase": "...", "class": "exempt|warn|defect", "context": "..."}
  ],
  "audit_result": "PASS | FAIL"
}
```

**Halt and report (defect case):**

```
CRITICAL: Contract residue detected — Pattern Mapping bypass

File: <path>:<line>
Phrase: <phrase>
Context: <one-line surrounding text>
Subtype: <mcp_new_file | mcp_backfilled | mcp_preserved>

This file was written for a Neuroloom-backend project but contains
untransformed z-sdlc canonical phrasing. Likely cause:

- mcp_new_file path: Pattern Mapping silently bypassed for the new
  file. The transformer must run for every file in a Neuroloom
  project regardless of whether the project had a prior version.
  Verify the handler dispatched it.

- mcp_backfilled / mcp_preserved path: Pass 2 didn't run on this file
  (concept-terminology residue) OR Pass 1 has a coverage gap for the
  specific phrasing form (path residue not in Pattern Mapping table).

Recovery: the operation's, in adapter-lifecycle.md § Halts and their recoveries
File a plugin bug with run_id <run_id> and the residue details above.
```

**Why hard-gated:** the user discovered `incident-runbook-template.md`'s untransformed knowledge yaml references manually, weeks after `migrate-6f4217`. The previous post-write checks (Pass 2 residue halt added in 0.4.6, output regression scans, MCP retention) all passed because none of them check for "upstream content with canonical phrases written verbatim." The Pass 2 residue halt only catches concept-terminology — it doesn't catch path-bearing residue, and it only fires for files that went through Pass 2. A new-file install that bypassed Pass 1 entirely also bypassed Pass 2 (Pass 2 only re-reads files Pass 1 wrote, but the bypass scenario is "Pass 1 wrote upstream content unchanged"). This audit is the catch-all that runs regardless of which pass touched the file.

**Relationship to existing audits:**

- **Pass 2 residue halt (0.4.6, in pattern-mapping-rules.md):** runs inline as Pass 2 finishes a file. Narrower scope (concept-terminology only) but tighter timing (catches bugs before the audits' aggregate step). Keep both — defense in depth.
- **MCP Retention Audit:** measures MCP count drop. Doesn't detect canonical-phrase residue in absolute terms.
- **Structural Content-Loss Audit:** measures heading/table/step counts. Doesn't detect canonical-phrase residue.
- **Stale Agent Reference Audit:** detects unresolved agent names. Different defect class.
- **Output regression scans (post-write halt list):** detects malformed transformer output. Doesn't detect "transformer didn't fire at all."

The Contract Residue Audit closes the gap between "transformer fired and produced something malformed" (regression scans) and "transformer fired and produced clean Neuroloom output" (MCP retention). It catches "transformer didn't fire and produced clean upstream output instead."

#### Quick sanity checks

1. **Skill customization preservation** — spot-check 1 enhanced skill (e.g., `sdlc-audit`):
   - Neuroloom-specific sections (API call patterns, MCP tool references) are intact
   - Framework sections were updated (compare against z-sdlc source)

2. **Agent integrity** — spot-check 1 agent:
   - Framework-derived sections (Knowledge Context, Communication Protocol) retain their MCP calls if the project-side version had them
   - Domain-specific content (scope, principles, workflow) was preserved

3. **Audit skill completeness** — verify all `references/` files were updated and any project-specific audit dimensions preserved

**Gate rule:** If any check fails, fix the merge before the handler returns PASS to upstream. Do not hand corrupted content back.


---

### Telemetry Assertion (`post-operation` handler, migrate only — NO OVERRIDE)

Before any verification runs, assert the `post-file-write` telemetry is intact. This catches the silent-bypass failure mode where the executor skipped per-file emission and the MCP Retention Audit summary event.

**This assertion has recurred as the failure mode TWICE — in `migrate-f01a70` (2026-04-22) and `migrate-6f4217` (2026-04-26).** Both runs reached `run_complete` without emitting any of the required `post-file-write` events. Each recurrence cost an after-the-fact outside-the-run diff audit to detect. **The assertion below is the only thing standing between a silent regression and a successful migration. It cannot be skipped, batched, or paraphrased — run it as a discrete step.** The `post-operation` handler is `warn-continue`: a failed assertion is reported as a regression, and upstream still writes the new manifest. The recovery at the end of this file restores `.sdlc-manifest.json` for that reason.

**Operational pattern for the executor:** the assertion is a real procedural step, not a check-box. To run it:

1. Use the `Read` tool (or shell `cat`) to read `.sdlc-transaction-log` for the current `run_id`.
2. Using the JSON event lines, count by `event` type. (Use `grep ... | wc -l` if reading the file is large.)
3. Compare each count to the expectations below. Surface specifics — "I have 6 file_merged events, expected 88" — not "telemetry looks fine."
4. The assertion passes only when every count matches its expectation.

If you are about to report the post-operation result and have not done steps 1–4 above, the assertion has not run. Stop and run it. There is no override path.

**Procedure:**

1. Read the transaction log entries for this `run_id`.
2. Count events of each required type:
   - `file_merged` — MUST equal the number of files the `post-file-write` handler dispatched (cross-check against the §1.3 change manifest). Zero is only acceptable when no file the run wrote matched `post-file-write`'s **Applies to** (a release that changed only scripts or YAML). (Pass 1 event.)
   - `concept_terminology_applied` — MUST equal the number of `file_merged` events whose `subtype` is not `exempt_verbatim`, `exempt_row_rewrite` or `no_patterns`, for Neuroloom-backend projects: every file the pipeline transformed also gets a Pass 2 event, and an exempt or no-pattern file stops before Pass 2
   - `mcp_retention_audit_complete` — MUST be exactly 1 per transformer dispatch (none when no written file matched `post-file-write`'s **Applies to**, a release that changed only scripts or YAML), with `audit_result: "PASS"` present. Zero means the audit gate was bypassed; missing the `audit_result` field means schema regression.
   - `structural_audit_complete` — MUST be exactly 1 per transformer dispatch (none when no written file matched `post-file-write`'s **Applies to**, a release that changed only scripts or YAML), with `audit_result: "PASS"` present. Same rules as mcp_retention.
   - `agent_resolution_audit_complete` — MUST be exactly 1 per transformer dispatch (none when no written file matched `post-file-write`'s **Applies to**, a release that changed only scripts or YAML), with `audit_result: "PASS"` present (added in plugin 0.4.7 post-`migrate-6f4217` sleeved audit). Zero means the agent-resolution audit was bypassed; missing the field means schema regression. Halt-class entries in `unresolved_dispatch` would have already halted `post-file-write`, so reaching this assertion with this audit's `audit_result: "FAIL"` should be impossible. If it happens, the executor kept going despite the halt.
   - `contract_residue_audit_complete` — MUST be exactly 1 per transformer dispatch (none when no written file matched `post-file-write`'s **Applies to**, a release that changed only scripts or YAML), with `audit_result: "PASS"` present (added in plugin 0.4.8 post-`migrate-6f4217` sleeved audit, second follow-up). Zero means Pattern Mapping bypass went undetected. The audit catches the failure mode where `mcp_new_file` install paths wrote upstream content verbatim without running Pattern Mapping — the existing per-pass checks miss this because they only detect malformed output, not "transformer didn't fire."
3. If any count is wrong or any required field is missing, report a REGRESSION (post-operation is warn-continue; its recovery is adapter-lifecycle.md § Recovery on failure) with:

```
TELEMETRY REGRESSION — post-file-write audit trail incomplete.

Expected: {N} file_merged events ({T} transformed), {T} concept_terminology_applied events,
          1 mcp_retention_audit_complete event (with audit_result),
          1 structural_audit_complete event (with audit_result)
Found:    {M} file_merged, {P} concept_terminology_applied,
          {K} mcp_retention_audit_complete, {S} structural_audit_complete

{if concept_terminology_applied doesn't match the transformed file_merged count:}
  Pass 2 (Prose Concept-Terminology) was skipped or partial. Pass 2 is
  mandatory for Neuroloom-backend projects — concept-terminology leaks
  (file-speak in prose descriptions of the knowledge layer) go undetected
  without it.
{endif}

The post-file-write handler ran but did not emit the mandatory audit trail.
There is no record that the mandatory audit gates evaluated the written
files.

Recovery:
1. Follow migrate's recovery in adapter-lifecycle.md § Halts and their recoveries
2. File a plugin bug with this run_id: {run_id}
3. Re-run /sdlc-migrate after the executor is fixed
```

Report every mismatch in the migration report.

