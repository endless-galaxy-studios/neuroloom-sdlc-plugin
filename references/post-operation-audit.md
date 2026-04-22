# Post-Operation Audit

Shared post-operation audit protocol used by `/sdlc-initialize`, `/sdlc-migrate`, and `/sdlc-port` after the mutation stages complete.

**Purpose:** Catch integration failures before declaring success. The operation may have written files without errors, but silent regressions (MCP calls reverted, phrases missed by transformation, manifest out of sync) only surface here.

**When this runs:** Last stage before the success report, after all mutations (file writes, knowledge ingestion, manifest updates) are complete.

**Outcome model:** Hard-fail if any regression is found. The operation is halted, CD is given specific recovery instructions, and no success message is printed. If all checks pass, the operation reports success and proceeds to the user-facing summary.

---

## Shared Checks (all three skills)

Run every check. Collect failures. Report together at the end. Do not short-circuit.

### Check 1 — MCP integration health (Neuroloom-specific)

For Neuroloom projects (`neuroloom_backend: true` in manifest), the installed files should contain `memory_search(` / `memory_store(` calls in the places listed in the Pattern Mapping + Files Containing These Patterns tables in `skills/sdlc-migrate/SKILL.md`.

**Procedure:**
1. Count `memory_search(` + `memory_store(` occurrences across `.claude/sdlc/` and `.claude/agents/` → `MCP_COUNT_INSTALLED`
2. Verify at minimum these files each contain at least one MCP call:
   - `.claude/agents/AGENT_TEMPLATE.md` — Knowledge Context + Communication Protocol
   - `.claude/agents/sdlc-reviewer.md` — wiring checklist
   - `.claude/agents/sdlc-compliance-auditor.md` — methodology reference
   - `.claude/sdlc/process/discipline_capture.md` — agent knowledge lookup
   - `.claude/sdlc/process/overview.md` — knowledge capture
3. If any listed file has zero MCP calls: **REGRESSION** — transformation did not apply

**Expected counts by operation:**
- `/sdlc-initialize` — expect non-zero (fresh Pattern Mapping applied)
- `/sdlc-migrate` — expect `>= MCP_COUNT_PRE_MIGRATION` (from transaction log)
- `/sdlc-port` — expect non-zero (port applies Pattern Mapping in bulk)

### Check 2 — No residual cc-sdlc standard phrases

For Neuroloom projects, canonical phrases from cc-sdlc's phrasing contract should have been transformed by the installer. Their continued presence in installed files indicates the transformation was skipped.

**Canonical phrases (all should return zero hits in `.claude/sdlc/` and `.claude/agents/`):**
- `consult [sdlc-root]/knowledge/agent-context-map.yaml`
- `Consult [sdlc-root]/knowledge/agent-context-map.yaml for`
- `update [sdlc-root]/knowledge/agent-context-map.yaml`
- `Update [sdlc-root]/knowledge/agent-context-map.yaml`
- `Read [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml`
- `look up the agent's mapped files from [sdlc-root]/knowledge/agent-context-map.yaml`
- `Before starting substantive work, consult [sdlc-root]/knowledge/agent-context-map.yaml`
- `Append to [sdlc-root]/disciplines/*.md`
- `Append each insight or GAP entry to the relevant [sdlc-root]/disciplines/*.md`
- `knowledge stores ([sdlc-root]/knowledge/)`

**Action on hit:** **REGRESSION** (outside the exception list) — the transformation didn't apply to this file/section. The Pattern Mapping table has a rule for each of these; a hit means the rule didn't fire (likely due to file-level merge without §4.2.0 gate running, or a prior install bug).

### Check 2a — No forbidden pre-contract phrasings

The phrasing contract explicitly forbids non-canonical variants that cc-sdlc source may have used before standardization (pre-2026-04-22). Upstream cc-sdlc should have rewritten these, but scan the installed copy as a safety net — if a forbidden form shows up, it means cc-sdlc regressed OR the plugin was pulling from a pre-standardization version.

**Forbidden patterns (all should return zero hits):**
- `Read [sdlc-root]/knowledge/agent-context-map.yaml` (as instruction — distinguishable from canonical `Read [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml`)
- `Look up ... in [sdlc-root]/knowledge/agent-context-map.yaml` (the `in` form — canonical uses `from` or `Consult ... for`)
- `via [sdlc-root]/knowledge/agent-context-map.yaml` (as instruction — e.g., `Connect ... via ...`)
- `directing them to [sdlc-root]/knowledge/agent-context-map.yaml`
- `Connect [any text] via [sdlc-root]/knowledge/agent-context-map.yaml`

**Action on hit:** **REGRESSION** — report which file + line + forbidden pattern. Two possibilities: (1) cc-sdlc source regressed (file a bug upstream, tag `[contract-change]`), or (2) plugin pulled from a release predating the 2026-04-22 standardization. Recovery: halt, update plugin to latest cc-sdlc, re-run.

**Exceptions for Checks 2 and 2a:**
- `.claude/sdlc/process/knowledge-routing.md` — this file IS the phrasing contract; it lists canonical AND forbidden phrases as documentation, not instruction
- `.claude/sdlc/process/sdlc_changelog.md` — changelog entries may quote the phrases as metadata
- `.claude/sdlc/knowledge/provenance_log.md` — append-only project-specific record; entries may quote phrases as metadata (treated like `sdlc_changelog.md`)
- `.claude/agents/sdlc-reviewer.md` — reviewer checklist quotes the canonical phrases as validation criteria
- `.claude/agents/sdlc-compliance-auditor.md` — auditor validation section quotes phrases as criteria
- Inline code blocks (``` fenced ``` or `` `backticked` ``) within these exempt files — the phrasing contract explicitly distinguishes documentation from instruction

### Check 3 — No inline adapter conditionals

The phrasing contract forbids inline conditionals like `(Neuroloom projects: use memory_search instead)` in cc-sdlc source files. After transformation, these should never appear in installed files.

**Search patterns (all should return zero hits):**
- `(Neuroloom projects:`
- `(skip for Neuroloom`
- `(Neuroloom projects use`

**Action on hit:** **REGRESSION** — either the upstream file has a contract violation (should be fixed upstream) or the transformation didn't strip it. Halt.

### Check 4 — Manifest integrity

**Procedure:**
1. `.sdlc-manifest.json` exists and is valid JSON
2. Required fields present:
   - `source_version` — matches the version the operation targeted
   - `sdlc_root` — matches the actual installed location
   - `neuroloom_backend` — set to `true`
   - `install_date` (init) or `last_migration` (migrate) or `ported_at` (port) — set to this operation's timestamp
3. `installed_files` map (if present): each entry's on-disk SHA-256 should match the recorded hash. Drift here means a file was edited after the operation wrote it.

**Action on failure:** **REGRESSION** — manifest and on-disk state are out of sync.

### Check 5 — Knowledge layer reachable (Neuroloom-specific)

**Procedure:**
1. Call `memory_search(query="SDLC workspace sentinel", tags=["sdlc:sentinel"])`
2. Expect exactly one result with the current `sdlc:seed-version:{version}` tag

**Action on failure:**
- Zero results: sentinel missing or server state corrupted
- Multiple results: workspace has duplicate sentinels (bug in a prior operation)
- Wrong version tag: migrate/port did not update the sentinel

All three are **REGRESSION**.

### Check 6 — No stale file-based references in agent-context-map replacements

Neuroloom projects should NOT have `.claude/sdlc/knowledge/agent-context-map.yaml` as a live configuration file — that pattern is replaced by memory-graph tags.

**Procedure:**
1. If `.claude/sdlc/knowledge/agent-context-map.yaml` exists, flag it
2. Check for any remaining references to it as a runtime lookup (vs. a historical mention in the changelog)

**Action on failure:** **REGRESSION** — a port/init/migrate left behind the cc-sdlc file-based config.

---

## Operation-Specific Checks

### /sdlc-initialize

After the shared checks, additionally verify:

- **Project agents created** — `.claude/agents/` contains more than just the framework agents (sdlc-reviewer, sdlc-compliance-auditor, AGENT_TEMPLATE, AGENT_SUGGESTIONS). If no project-specific agents exist, initialization skipped the agent roster stage.
- **Founding spec or README captured** — if the project was greenfield, verify the spec was written and ingested
- **First-run sentinel** — `memory_search(query="SDLC workspace sentinel")` returns exactly one result, created during this init

### /sdlc-migrate

After the shared checks, additionally verify:

- **§4.2-gate MCP Retention Audit** already passed (or this skill would have halted). The post-operation audit re-verifies the file counts as a double-check.
- **PROJECT-SECTION markers preserved** — spot-check one file with markers from the transaction log to confirm re-injection happened.
- **source_version updated** — manifest's `source_version` equals the target (not the pre-migration version).
- **Changelog entries consumed** — any `[contract-change]` entries in the migrated range were resolved (not just deferred).

### /sdlc-port

After the shared checks, additionally verify:

- **Bulk transformation applied** — `/sdlc-port` converts a file-based cc-sdlc install to Neuroloom. Verify the transformation touched the expected file set:
  - All files in the "Files Containing These Patterns" table from `sdlc-migrate/SKILL.md`
  - All project-tailored agents in `.claude/agents/` (Knowledge Context, Communication Protocol sections)
  - Process docs: `discipline_capture.md`, `overview.md`, `incident_response.md`, etc.
- **Knowledge ingestion complete** — all knowledge YAMLs from the file-based source were ingested into the memory graph with correct tags (`sdlc:knowledge`, `sdlc:domain:*`)
- **Original file-based knowledge files either removed or marked** — if the port leaves them behind, they're a drift risk for future migrations

---

## Output Format

```
POST-OPERATION AUDIT
═══════════════════════════════════════════════════════════════
Operation: /sdlc-{initialize,migrate,port}
Started:   {ISO timestamp}
Completed: {ISO timestamp}
Duration:  {N}s

SHARED CHECKS
[✓] MCP integration health:       {N} MCP calls across {M} files
[✓] No residual standard phrases: 0 hits (searched 4 patterns across 2 trees)
[✓] No inline adapter conditionals: 0 hits
[✓] Manifest integrity:           valid JSON, all required fields, hashes match
[✓] Knowledge layer reachable:    sentinel found, version tag current
[✓] No stale file-based refs:     agent-context-map.yaml absent

OPERATION-SPECIFIC CHECKS
[✓] {operation-specific check 1}
[✓] {operation-specific check 2}
...

VERDICT: PASSED — {operation} completed successfully
```

On any failure, replace `✓` with `✗` and inline the specific regression detail. Example:

```
[✗] No residual standard phrases: 3 hits found
    .claude/sdlc/process/discipline_capture.md:18 — consult [sdlc-root]/knowledge/agent-context-map.yaml
    .claude/sdlc/process/overview.md:45 — Read [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml
    .claude/agents/sdlc-reviewer.md:84 — consult [sdlc-root]/knowledge/agent-context-map.yaml

VERDICT: FAILED — 3 regressions detected
Recovery: {operation-specific recovery instructions}
```

---

## Recovery Instructions by Operation

### /sdlc-initialize failures

Initialization wrote partial state. Recovery:
1. `rm -rf .claude/sdlc/ .claude/agents/` to clear the filesystem layer
2. Delete the sentinel: requires a manual call to the Neuroloom API support team (the skill does not have a memory-delete primitive to avoid accidental data loss)
3. Re-run `/sdlc-initialize` after the plugin's Pattern Mapping rules are fixed

### /sdlc-migrate failures

Migration changes are uncommitted. Recovery:
1. `git checkout -- .claude/` to restore the pre-migration state
2. File a bug against the plugin — the transformation missed a phrase
3. Re-run `/sdlc-migrate` after the plugin update

### /sdlc-port failures

Port may have partially transformed files AND partially ingested knowledge. Recovery:
1. `git checkout -- .claude/` to restore filesystem
2. The knowledge ingestion is idempotent (server-side upsert via `knowledge_id`) so re-running port is safe
3. Re-run `/sdlc-port` after the plugin update

---

## Integration

This protocol is referenced by:
- `/sdlc-initialize` — Stage 7 (or final stage before success report)
- `/sdlc-migrate` — Stage 5 (post-§4.2-gate, before Stage 6 success report)
- `/sdlc-port` — final stage before success report

Each skill runs the full shared checks plus its operation-specific subset. Regressions halt the skill.

**Relationship to other gates:**
- **Pre-flight** (`references/preflight.md`) — environmental checks before mutations
- **§4.2.0 Pre-Write MCP Preservation Gate** (migrate only) — prevents regressions before they're written
- **§4.2-gate MCP Retention Audit** (migrate only) — catches file-level regressions immediately after write
- **Post-Operation Audit** (this file) — catches aggregate and cross-file issues after all mutations complete

The layers are defense-in-depth: §4.2.0 prevents most bugs, §4.2-gate catches what §4.2.0 missed, post-operation audit catches what both missed.
