# Content-Merge Verification Audits

These audits run after all Stage 4.2 file writes complete, before proceeding to §4.3.

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


---

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

