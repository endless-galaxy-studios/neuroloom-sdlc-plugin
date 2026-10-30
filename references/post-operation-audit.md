# Post-Operation Audit

Shared post-operation audit protocol used by `/sdlc-initialize`, `/sdlc-migrate`, and `/sdlc-port` after the mutation stages complete.

**Purpose:** Catch integration failures before declaring success. The operation may have written files without errors, but silent regressions (MCP calls reverted, phrases missed by transformation, manifest out of sync) only surface here.

**When this runs:** Last stage before the success report, after all mutations (file writes, knowledge ingestion, manifest updates) are complete.

**Outcome model:** Hard-fail if any regression is found. The operation is halted, CD is given specific recovery instructions, and no success message is printed. If all checks pass, the operation reports success and proceeds to the user-facing summary.

---

## Shared Checks (all three skills)

Run every check. Collect failures. Report together at the end. Do not short-circuit.

### Check 1 — MCP integration health (Neuroloom-specific)

For Neuroloom projects (`neuroloom_backend: true` in manifest), the installed files should contain `memory_search(` / `memory_store(` calls in files detected by the phrasing-contract runtime scan (see `sdlc-migrate/SKILL.md` § "Detecting Files That Contain Phrasing-Contract Patterns") and in the Pattern Mapping rules.

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

### Check 2 — No residual knowledge-layer references

For Neuroloom projects, no installed file should still point at a file in the z-sdlc knowledge or discipline layer. Those files do not exist in a Neuroloom project (the content lives in the memory graph), so a reference to one is a dead pointer that a reader, or a dispatched subagent, will try to open.

This check is a **generic scan**, not a phrase list. A fixed list of canonical phrases cannot see a backtick-wrapped instance, an Integration `Uses:` line, a path inside a dispatch prompt, or a phrasing its author did not anticipate. The list this check replaces missed all of those in sleeved (z-sdlc 2.2.0 migration, 2026-10-29), and it searched only `.claude/sdlc/` and `.claude/agents/`, so it never looked at `.claude/skills/`, where most of the residue was.

**Scan** (all three trees; `.claude/skills/` includes each skill's `references/`; Markdown only, because Markdown is the transform scope and `process/agent-selection.yaml` legitimately names paths):

```bash
grep -rnE --include='*.md' '\[sdlc-root\]/(knowledge|disciplines)/' .claude/skills .claude/agents .claude/sdlc
```

The scan is deliberately not fence-aware and not Integration-aware: a hit inside a fenced dispatch prompt or on an Integration `Uses:` / `Depends on:` / `DRY notes:` line is a regression, because the transformer rewrites both (see `pattern-mapping-rules.md` § "Integration sections" and § "Dispatch-prompt template blocks"). Classify every hit against the exemption list below; row 5 is the only place fences are consulted. A hit that matches no exemption is a **REGRESSION**.

**Exemptions.** These are the legitimate, by-design references. The list is closed: to exempt something else, add a row here with its reason, so the next reader can see why.

| # | Exempt hits | Why it is legitimate |
|---|-------------|----------------------|
| 1 | In `.claude/skills/sdlc-migrate/`, lines that map an upstream path to its install path or list the project-specific files. Shape: a bare upstream path (`knowledge/`, `knowledge/README.md`) beside `→` or `(to` + an install path, e.g. SKILL.md "Source-to-project path mappings" and the file-copy list | Framework mechanics: they describe where the framework puts files in file mode. Exempt LINE BY LINE, not by tree: every other hit in `sdlc-migrate` is a live read (a check on the project's own disciplines or knowledge: "read … and verify", "Read each … parking lot", "Verify … references …", the post-migration review table, "new knowledge lands in …") and the transformer rewrites it, so it is a regression here. |
| 2 | On `.claude/agents/sdlc-reviewer.md` and `.claude/agents/sdlc-compliance-auditor.md` lines that start `` - [ ] No ` `` (anti-residue items), the backtick-quoted span right after `No` | The span quotes the phrase the item forbids (`No \`consult [sdlc-root]/knowledge/agent-context-map.yaml\``). Only the span is exempt; the rest of the line is checked like any other. **Positive checklist items are not exempt**: `- [ ] Lookups use \`consult [sdlc-root]/knowledge/agent-context-map.yaml\`` names the canonical form the reviewer enforces, and a project whose reviewer still says the file-mode form flags every correctly transformed agent. A backticked bare path (`Extract to \`[sdlc-root]/knowledge/\``) is not a quoted phrase either. |
| 3 | `.claude/sdlc/process/knowledge-routing.md`, `project-section-markers.md`, `path-mappings.md`, `adapter-lifecycle-protocol.md` | Documentation and data that name the paths: the phrasing contract (lists canonical AND forbidden phrases), the file-ownership table, the path-mapping table, the lifecycle protocol. |
| 4 | `.claude/sdlc/process/sdlc_changelog.md` and `.claude/sdlc/process/changelog-archive/*.md` | History. Entries quote phrases as an accurate record of what happened (z-sdlc contract 0017). |
| 5 | Hits inside a fenced block that shows a file format or a command and is NOT a dispatch-prompt template block, an agent template block or an output-template block (identification criteria: `pattern-mapping-rules.md` § "Dispatch-prompt template blocks" and § "Output-template blocks"). Upstream examples: `sdlc-ingest/SKILL.md` and `sdlc-develop-agent/SKILL.md` ` ```yaml ` demos of an `agent-context-map.yaml` entry, `process/discipline_capture.md`'s ` ```markdown ` "Promoted entry format", and a ` ```bash ` command | A format or command demo illustrates upstream's file layout; rewriting it removes the example's value and can break its syntax. A ` ```markdown ` or untagged fence holding a prompt sent to a dispatched agent is NOT exempt: a subagent acts on it literally. |

**Second scan: the on-disk provenance log.** CD decided (2026-10-29) that provenance lives as memories tagged `sdlc:provenance`, so the string `provenance_log` must not appear in any installed file:

```bash
grep -rn --include='*.md' 'provenance_log' .claude/skills .claude/agents .claude/sdlc
```

The only exempt hits are row 4 of the table (the changelog and its archive record what happened). Every other hit is a **REGRESSION**: a skill still tells an agent to read or append to a file that does not exist. This includes the lines of `sdlc-migrate` and `process/path-mappings.md` that list it among project-specific files, which are rewritten (they are not framework mechanics).

**Action on hit:** **REGRESSION**, naming file, line and the matched text. Possible causes, in order of likelihood: (1) the file was not in the transformer's input list (check `.claude/skills/*/references/*.md`); (2) the phrasing has no Pattern Mapping row (add one); (3) the hit sits in a context a hard exclusion wrongly covered (fence, Integration section). Pre-contract phrasings that z-sdlc standardized away in 2026-04 (`Read [sdlc-root]/knowledge/agent-context-map.yaml`, `Look up … in …`, `via [sdlc-root]/knowledge/…`, `directing them to …`, `Read and follow the full methodology at …`, `go to your SDLC knowledge store (…)`) all contain a `[sdlc-root]/knowledge/` path and are caught by this scan; a hit means z-sdlc regressed (file a bug upstream, tag `[contract-change]`) or the plugin pulled a pre-standardization release.

### Check 2a — No wildcard in tag arguments

`tags` and `tag_prefixes` match literally. A `*` inside either list is an ordinary character, so the call returns zero results and raises no error. The rule table itself once emitted `sdlc:discipline:` followed by `*` in a `tags` list, and sleeved's `sdlc-reflect`, `sdlc-idea` and `sdlc-archive` searched for nothing through a full migration cycle.

**Scan:**

```bash
grep -rnE --include='*.md' 'tag(s|_prefixes)=\[[^]]*\*' .claude/skills .claude/agents .claude/sdlc
```

Zero hits expected. Any hit is a **HALT**: the call it names does not do what it says. The correct form for "any discipline" is `tag_prefixes=["sdlc:discipline"]`; prose notation is `sdlc:discipline:<name>`.

**Exemptions:** `.claude/sdlc/process/sdlc_changelog.md` and `.claude/sdlc/process/changelog-archive/*.md` only (history quoting the old form).

**Related checks this grep cannot make** (no `*` is involved, so 2a does not see them):

- **A `tags` list of two or more tags is an OR unless `tags_match="all"` is on the same call.** Detect candidates with `grep -rnE --include='*.md' 'tags=\[[^]]*"[^"]*"[^]]*,' .claude/skills .claude/agents .claude/sdlc`. Every hit on a search spec (not a `memory_store` / `document_ingest*` / `memory_get_index` call, not a list with a `<placeholder>`) must carry `tags_match="all"` or be a deliberate OR that the report lists; the form to expect for knowledge + domain is `tags=["sdlc:knowledge", "sdlc:domain:<d>"], tags_match="all"`.
- **No prefix on `sdlc:knowledge`, and no colon on the discipline family.** `grep -rnE --include='*.md' 'tag_prefixes=\["sdlc:knowledge|tag_prefixes=\["sdlc:discipline:"' …` must return nothing: a `sdlc:knowledge` prefix also matches `sdlc:knowledge-id:…`, and `sdlc:discipline:` misses the bare `sdlc:discipline` tag.

### Check 2b — Concept-terminology residue (WARN; REGRESSION in one case)

Check 2 finds paths. Pass 2 translates bare flat-file vocabulary that names no path ("discipline parking lots", "knowledge store", "Knowledge files"), which a path grep cannot see. sleeved carried such wording in four files through a migration to z-sdlc 2.2.0 (`sdlc/README.md`, `process/commands.md`, `process/guardrail-lifecycle.md`, `skills/sdlc-playbook-generate/SKILL.md`) for two reasons the audit now closes: no post-operation check looked for it, and the transformer's Step 1 scan used path anchors only, so each file was logged `no_patterns` and Pass 2 never ran on it.

**Scan** (the regex is Audit 7's, and Step 1's concept scan uses the same one):

```bash
grep -rinE --include='*.md' '\bknowledge stores?\b|\bknowledge files?\b|\bdiscipline files?\b|\bparking[- ]lot entr|\bknowledge-store entr|\bdiscipline parking[- ]lots?\b|\bknowledge YAMLs?\b|\bYAML knowledge files?\b|\bknowledge index\b|\bknowledge store gaps?\b' .claude/skills .claude/agents .claude/sdlc
```

**Not reported** (legitimate retention): everything under `.claude/skills/sdlc-migrate/` (it describes the framework's file layout); `.claude/sdlc/process/knowledge-routing.md`, `project-section-markers.md`, `path-mappings.md`, `adapter-lifecycle-protocol.md`; `sdlc_changelog.md` and `changelog-archive/*.md`; hits inside fenced blocks; hits inside a quoted phrase of a trigger list or a `user: \"…\"` line in a skill or agent description (`"verify the knowledge store"`); an `assistant:` line or `<commentary>` text is prose and IS reported; hits inside an MCP `query="…"` string; the Neuroloom replacement strings themselves (`Neuroloom knowledge store`); a hit directly followed by a `(memory …` parenthetical, which is the shape of the replacement's own output (`Update the knowledge index (memory entries tagged sdlc:knowledge + sdlc:knowledge-index)`, `Discipline Parking Lots (memory graph, entries tagged sdlc:discipline:<name>)`); and the quoted span of a `- [ ] No` checklist item.

**Action on hit:** every other hit is a **WARN**: report file, line and the text, so CD can fix it or accept it. A hit in a file whose `file_merged` event for this run says `subtype: "no_patterns"` is a **REGRESSION**: Step 1 skipped Pass 2 on a file that needed it.

### Check 2c — Escape preservation (WARN)

Match rule 13 (`pattern-mapping-rules.md`) has the transformer restore any line whose backslash-`n` count fell below its baseline, and log it. This check makes those repairs visible.

**Procedure:** count `warning` events with `category: "escape_restored"` for this run in `.sdlc-transaction-log`.

**Action:** zero is a pass. Each one is a **WARN**: list the file and line range, because the transformer expanded a string and a rule or prompt is letting that happen. A pass still means the file on disk has the escapes intact.

### Check 2d — Dead relative links into layers the project does not carry

Check 2 and Check 2b cannot see a markdown link such as `](disciplines/README.md)`: it has no `[sdlc-root]/` prefix and no concept term. sleeved kept three of them through the 2.2.0 migration (`sdlc/README.md:80, :131, :185`).

**Scan:**

```bash
grep -rnoE --include='*.md' '\]\((\./|\.\./)*(knowledge|disciplines|bundles)/[^)#[:space:]]*' .claude/skills .claude/agents .claude/sdlc
```

**Action:** resolve each target against the file that links it (`test -e`). A target that exists is a pass (a project that installed `bundles/` keeps its links). A target that does not exist is a **REGRESSION**, except in `sdlc_changelog.md` and `changelog-archive/*.md`, which quote history. The rows that fix them are in `pattern-mapping-rules.md` § "Audit-description metadata" (the two relative-link rows after the install-layout row).

### Check 3 — No inline adapter conditionals

The phrasing contract forbids inline conditionals like `(Neuroloom projects: use memory_search instead)` in z-sdlc source files. After transformation, these should never appear in installed files.

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

**Action on failure:** **REGRESSION** — a port/init/migrate left behind the z-sdlc file-based config.

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

- **Bulk transformation applied** — `/sdlc-port` converts a file-based z-sdlc install to Neuroloom. Verify the transformation touched the expected file set:
  - All files flagged by the phrasing-contract runtime scan (see `sdlc-migrate/SKILL.md` § "Detecting Files That Contain Phrasing-Contract Patterns")
  - All project-tailored agents in `.claude/agents/` (Knowledge Context, Communication Protocol sections)
  - Process docs: `discipline_capture.md`, `overview.md`, `incident_response.md`, etc.
- **Knowledge ingestion complete** — all knowledge YAMLs from the file-based source were ingested into the memory graph with correct tags (`sdlc:knowledge`, `sdlc:domain:<name>`)
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
[✓] No residual knowledge-layer paths: 0 hits outside the exemption list (3 trees)
[✓] No wildcard in tag arguments: 0 hits
[✓] Concept-terminology residue: 0 unexplained hits (WARN-class; every hit listed)
[✓] Escape preservation:          0 `escape_restored` warnings (else {N} files, each listed with its line range)
[✓] No dead relative links:       0 targets missing (knowledge/, disciplines/, bundles/)
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
[✗] No residual knowledge-layer paths: 3 hits found
    .claude/sdlc/process/discipline_capture.md:18 — consult [sdlc-root]/knowledge/agent-context-map.yaml
    .claude/skills/sdlc-cleanup-comments/references/dispatch-prompts.md:13 — Read [sdlc-root]/knowledge/coding/comment-discipline.yaml
    .claude/skills/sdlc-reflect/SKILL.md:294 — `[sdlc-root]/disciplines/*.md` (write targets)

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
