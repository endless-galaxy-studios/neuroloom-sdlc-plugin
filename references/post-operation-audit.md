# Post-Operation Audit

Shared post-operation audit protocol used by `/sdlc-initialize`, `/sdlc-migrate`, and `/sdlc-port` after the mutation stages complete.

**Purpose:** Catch integration failures before declaring success. The operation may have written files without errors, but silent regressions (MCP calls reverted, phrases missed by transformation, manifest out of sync) only surface here.

**When this runs:** Last stage before the success report, after the file writes and knowledge ingestion are complete. For `/sdlc-initialize` and `/sdlc-port` the manifest is written by then too. **`/sdlc-migrate` runs this before it updates the manifest:** z-sdlc's §4.4a fires the adapter's `post-operation` phase after its compliance audit (§4.4) and before §4.5 writes `.sdlc-manifest.json` (z-sdlc `process/adapter-lifecycle-protocol.md`, "After all files written, before final manifest update"). On a migration the file still holds the previous version's `source_version`, `source_version_sha`, `file_count`, `declined_files` and hashes, so Check 4 and the migrate checks below judge it against what §4.5 is about to write, never against the new values.

**Outcome model:** Hard-fail if any regression is found. The operation is halted, CD is given specific recovery instructions, and no success message is printed. If all checks pass, the operation reports success and proceeds to the user-facing summary.

---

## Shared Checks (all three skills)

Run every check. Collect failures. Report together at the end. Do not short-circuit.

### Check 1 — MCP integration health (Neuroloom-specific)

For Neuroloom projects (`neuroloom_backend: true` in manifest), the installed files should contain `memory_search(` / `memory_store(` calls in files detected by the phrasing-contract runtime scan (see `${CLAUDE_PLUGIN_ROOT}/agents/neuroloom-transformer.md` § "Step 1: Runtime Scan") and in the Pattern Mapping rules.

**Procedure:**
1. Count `memory_search(` + `memory_store(` occurrences across `ops/sdlc/` and `.claude/agents/` → `MCP_COUNT_INSTALLED`
2. Verify at minimum these files each contain at least one MCP call, and where the line names two sections, one in each of them:
   - `ops/sdlc/templates/agent-template.md` — Knowledge Context + Communication Protocol (z-sdlc installs the agent template there; there is no `.claude/agents/AGENT_TEMPLATE.md`)
   - `.claude/agents/sdlc-reviewer.md` — wiring checklist
   - `.claude/agents/sdlc-compliance-auditor.md` — Knowledge Context + Communication Protocol (z-sdlc 2.9.6 gave the auditor both sections; one call in the file no longer shows that both were transformed)
   - `ops/sdlc/process/discipline_capture.md` — agent knowledge lookup
   - `ops/sdlc/process/overview.md` — knowledge capture
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
grep -rnE --include='*.md' '(\[sdlc-root\]|ops/sdlc)/(knowledge|disciplines)/' .claude/skills .claude/agents ops/sdlc CLAUDE.md | grep -vE '^ops/sdlc/(knowledge|disciplines)/'
```

**Every residue scan in this file (Checks 2, 2a, 2b, 2d and the provenance scan) skips `ops/sdlc/knowledge/` and `ops/sdlc/disciplines/`** (the trailing `grep -vE`). Those two directories hold file-mode data, knowledge YAML and parking-lot entries. No live instruction in a Neuroloom project reads them: Check 2 polices every file that would. On a port they are still on disk when this audit runs (Post-Port Cleanup then offers to remove the ones Neuroloom holds), and `post-file-write` skips both directories, because their content reaches Neuroloom through `knowledge-seed` and `knowledge-update`. A hit there says nothing about whether an instruction was transformed. Check 6 is the check that looks at them. They also take the project-root `CLAUDE.md`, where only hits between its `<!-- SDLC-START -->` and `<!-- SDLC-END -->` lines count: the rest of the file is the project's own text. Run each scan's pattern on the region with `awk '/<!-- SDLC-START -->/{f=1} f; /<!-- SDLC-END -->/{f=0}' CLAUDE.md | grep -nE '<pattern>'`, and drop the `CLAUDE.md` hits of the tree-wide grep. A `CLAUDE.md` with no markers and any hit is a **REGRESSION**: its SDLC sections can't be told from the project's, so nothing transformed them, and Post-Port Cleanup would leave them reading deleted files. Check 2 matches the written-out form `ops/sdlc/knowledge/` too, because a file the transformer missed may name the resolved path, and Post-Port Cleanup deletes what it points at. If grep reports `ops/sdlc: No such file or directory`, the scan did not run: that is a **REGRESSION** (Check 4), never a pass.

The scan is deliberately not fence-aware and not Integration-aware: a hit inside a fenced dispatch prompt or on an Integration `Uses:` / `Depends on:` / `DRY notes:` line is a regression, because the transformer rewrites both (see `pattern-mapping-rules.md` § "Integration sections" and § "Dispatch-prompt template blocks"). Classify every hit against the exemption list below; row 5 is the only place fences are consulted. A hit that matches no exemption is a **REGRESSION**.

**Exemptions.** These are the legitimate, by-design references. The list is closed: to exempt something else, add a row here with its reason, so the next reader can see why.

| # | Exempt hits | Why it is legitimate |
|---|-------------|----------------------|
| 1 | In `.claude/skills/sdlc-migrate/`, lines that map an upstream path to its install path or list the project-specific files. Shape: a bare upstream path (`knowledge/`, `knowledge/README.md`) beside `→` or `(to` + an install path, e.g. SKILL.md "Source-to-project path mappings" and the file-copy list | Framework mechanics: they describe where the framework puts files in file mode. Exempt LINE BY LINE, not by tree: every other hit in `sdlc-migrate` is a live read (a check on the project's own disciplines or knowledge: "read … and verify", "Read each … parking lot", "Verify … references …", the post-migration review table, "new knowledge lands in …") and the transformer rewrites it, so it is a regression here. |
| 2 | On `.claude/agents/sdlc-reviewer.md` and `.claude/agents/sdlc-compliance-auditor.md` lines that start `` - [ ] No ` `` (anti-residue items), the backtick-quoted span right after `No` | The span quotes the phrase the item forbids (`No \`consult [sdlc-root]/knowledge/agent-context-map.yaml\``). Only the span is exempt; the rest of the line is checked like any other. **Positive checklist items are not exempt**: `- [ ] Lookups use \`consult [sdlc-root]/knowledge/agent-context-map.yaml\`` names the canonical form the reviewer enforces, and a project whose reviewer still says the file-mode form flags every correctly transformed agent. A backticked bare path (`Extract to \`[sdlc-root]/knowledge/\``) is not a quoted phrase either. |
| 3 | `ops/sdlc/process/knowledge-routing.md`, `project-section-markers.md`, `path-mappings.md`, `adapter-lifecycle-protocol.md` | Documentation and data that name the paths: the phrasing contract (lists canonical AND forbidden phrases), the file-ownership table, the path-mapping table, the lifecycle protocol. |
| 4 | `ops/sdlc/process/sdlc_changelog.md` and `ops/sdlc/process/changelog-archive/*.md` | History. Entries quote phrases as an accurate record of what happened (z-sdlc contract 0017). |
| 5 | Hits inside a fenced block that shows a file format or a command and is NOT a dispatch-prompt template block, an agent template block or an output-template block (identification criteria: `pattern-mapping-rules.md` § "Dispatch-prompt template blocks" and § "Output-template blocks"). Upstream examples: `sdlc-ingest/SKILL.md` and `sdlc-develop-agent/SKILL.md` ` ```yaml ` demos of an `agent-context-map.yaml` entry, `process/discipline_capture.md`'s ` ```markdown ` "Promoted entry format", and a ` ```bash ` command | A format or command demo illustrates upstream's file layout; rewriting it removes the example's value and can break its syntax. A ` ```markdown ` or untagged fence holding a prompt sent to a dispatched agent is NOT exempt: a subagent acts on it literally. |
| 6 | Contract 0026's file-presence lines: z-sdlc's own rules for telling a file the adapter took (no copy on disk, no `installed_files` entry) from a missing one. A closed list, each line found by its opening words: in `.claude/skills/sdlc-migrate/` (the skill file), the paragraph starting `**The knowledge layer is the adapter's** when`, its bullet starting `- **Every other file there**`, its bullet starting `` - **In a full migration** (no `source_version`) ``, the §2.3 line starting `When the knowledge layer is the adapter's (Pre-Flight Check, Step 2, The knowledge layer is the adapter's), skip the discipline files the adapter took.` and the §4.4 auditor-prompt line starting `> - Dimension 7 (Migration Integrity):`; in `.claude/agents/sdlc-compliance-auditor.md`, the item starting `7. **Migration integrity**`; in `.claude/skills/sdlc-audit/references/compliance-methodology.md`, the bullet starting `- **7b. File completeness:**`; in `ops/sdlc/process/adapter-lifecycle-protocol.md` (row 3 already exempts its paths), the paragraph starting `**The knowledge layer is the adapter's** when`, for its `provenance_log.md`. The whole line is exempt from the path scan, the provenance scan and the concept-term scans; any other line in these files is checked as usual. One exception keeps the list honest: if such a line also tells an agent to read, consult, append to or look up a knowledge-layer path, it is not exempt but a **REGRESSION**, since upstream changed it and the plugin needs a review. | They test whether a file is on disk; they don't read it. This plugin depends on them: `sdlc-migrate` leaves alone the files `knowledge-seed` and `knowledge-update` took, and the compliance auditor doesn't report them missing, only because these lines say so. Rewriting them into `memory_search` would break that, so the transformer keeps them verbatim (`pattern-mapping-rules.md` § "Contract 0026's file-presence lines"). They name `provenance_log.md` only as the project's own record, which a migration never copies and nothing reads or writes. Sleeved's migration to z-sdlc 3.0.0 halted on them (2026-11-26). |

**Second scan: the on-disk provenance log.** CD decided (2026-10-29) that provenance lives as memories tagged `sdlc:provenance`, so no installed file may tell an agent to read or write an on-disk log, and the string `provenance_log` must not appear in any installed file outside the exemptions below:

```bash
grep -rn --include='*.md' 'provenance_log' .claude/skills .claude/agents ops/sdlc CLAUDE.md | grep -vE '^ops/sdlc/(knowledge|disciplines)/'
```

The only exempt hits are row 4 of the table (the changelog and its archive record what happened) and row 6 (contract 0026's file-presence lines, which name it only as the project's own record, which nothing reads or writes). Every other hit is a **REGRESSION**: a skill still tells an agent to read or append to a file that does not exist. This includes the lines of `sdlc-migrate` and `process/path-mappings.md` that list it among project-specific files, which are rewritten (they are not framework mechanics).

**Action on hit:** **REGRESSION**, naming file, line and the matched text. Possible causes, in order of likelihood: (1) the file was not in the transformer's input list (check `.claude/skills/*/references/*.md`); (2) the phrasing has no Pattern Mapping row (add one); (3) the hit sits in a context a hard exclusion wrongly covered (fence, Integration section). Pre-contract phrasings that z-sdlc standardized away in 2026-04 (`Read [sdlc-root]/knowledge/agent-context-map.yaml`, `Look up … in …`, `via [sdlc-root]/knowledge/…`, `directing them to …`, `Read and follow the full methodology at …`, `go to your SDLC knowledge store (…)`) all contain a `[sdlc-root]/knowledge/` path and are caught by this scan; a hit means z-sdlc regressed (file a bug upstream, tag `[contract-change]`) or the plugin pulled a pre-standardization release.

### Check 2a — No wildcard in tag arguments

`tags` and `tag_prefixes` match literally. A `*` inside either list is an ordinary character, so the call returns zero results and raises no error. The rule table itself once emitted `sdlc:discipline:` followed by `*` in a `tags` list, and sleeved's `sdlc-reflect`, `sdlc-idea` and `sdlc-archive` searched for nothing through a full migration cycle.

**Scan:**

```bash
grep -rnE --include='*.md' 'tag(s|_prefixes)=\[[^]]*\*' .claude/skills .claude/agents ops/sdlc CLAUDE.md | grep -vE '^ops/sdlc/(knowledge|disciplines)/'
```

Zero hits expected. Any hit is a **HALT**: the call it names does not do what it says. The correct form for "any discipline" is `tag_prefixes=["sdlc:discipline"]`; prose notation is `sdlc:discipline:<name>`.

**Exemptions:** `ops/sdlc/process/sdlc_changelog.md` and `ops/sdlc/process/changelog-archive/*.md` only (history quoting the old form).

**Related checks this grep cannot make** (no `*` is involved, so 2a does not see them):

- **A `tags` list of two or more tags is an OR unless `tags_match="all"` is on the same call.** Detect candidates with `grep -rnE --include='*.md' 'tags=\[[^]]*"[^"]*"[^]]*,' .claude/skills .claude/agents ops/sdlc CLAUDE.md | grep -vE '^ops/sdlc/(knowledge|disciplines)/'`. Every hit on a search spec (not a `memory_store` / `document_ingest*` / `memory_get_index` call, not a list with a `<placeholder>`) must carry `tags_match="all"` or be a deliberate OR that the report lists; the form to expect for knowledge + domain is `tags=["sdlc:knowledge", "sdlc:domain:<d>"], tags_match="all"`.
- **No prefix on `sdlc:knowledge`, and no colon on the discipline family.** `grep -rnE --include='*.md' 'tag_prefixes=\["sdlc:knowledge|tag_prefixes=\["sdlc:discipline:"' …` must return nothing: a `sdlc:knowledge` prefix also matches `sdlc:knowledge-id:…`, and `sdlc:discipline:` misses the bare `sdlc:discipline` tag.

### Check 2b — Concept-terminology residue (WARN; REGRESSION in one case)

Check 2 finds paths. Pass 2 translates bare flat-file vocabulary that names no path ("discipline parking lots", "knowledge store", "Knowledge files"), which a path grep cannot see. sleeved carried such wording in four files through a migration to z-sdlc 2.2.0 (`sdlc/README.md`, `process/commands.md`, `process/guardrail-lifecycle.md`, `skills/sdlc-playbook-generate/SKILL.md`) for two reasons the audit now closes: no post-operation check looked for it, and the transformer's Step 1 scan used path anchors only, so each file was logged `no_patterns` and Pass 2 never ran on it.

**Scan** (the regex is Audit 7's, and Step 1's concept scan uses the same one):

```bash
grep -rinE --include='*.md' '\bknowledge stores?\b|\bknowledge files?\b|\bdiscipline files?\b|\bparking[- ]lot entr|\bknowledge-store entr|\bdiscipline parking[- ]lots?\b|\bknowledge YAMLs?\b|\bYAML knowledge files?\b|\bknowledge index\b|\bknowledge store gaps?\b' .claude/skills .claude/agents ops/sdlc CLAUDE.md | grep -vE '^ops/sdlc/(knowledge|disciplines)/'
```

**Not reported** (legitimate retention): everything under `.claude/skills/sdlc-migrate/` (it describes the framework's file layout); `ops/sdlc/process/knowledge-routing.md`, `project-section-markers.md`, `path-mappings.md`, `adapter-lifecycle-protocol.md`; `sdlc_changelog.md` and `changelog-archive/*.md`; hits inside fenced blocks; hits inside a quoted phrase of a trigger list or a `user: \"…\"` line in a skill or agent description (`"verify the knowledge store"`); an `assistant:` line or `<commentary>` text is prose and IS reported; hits inside an MCP `query="…"` string; the Neuroloom replacement strings themselves (`Neuroloom knowledge store`); a hit directly followed by a `(memory …` parenthetical, which is the shape of the replacement's own output (`Update the knowledge index (memory entries tagged sdlc:knowledge + sdlc:knowledge-index)`, `Discipline Parking Lots (memory graph, entries tagged sdlc:discipline:<name>)`); and the quoted span of a `- [ ] No` checklist item.

**Action on hit:** every other hit is a **WARN**: report file, line and the text, so CD can fix it or accept it. A hit in a file whose `file_merged` event for this run says `subtype: "no_patterns"` is a **REGRESSION**: Step 1 skipped Pass 2 on a file that needed it.

### Check 2c — Escape preservation (WARN)

Match rule 13 (`pattern-mapping-rules.md`) has the transformer restore any line whose backslash-`n` count fell below its baseline, and log it. This check makes those repairs visible.

**Procedure:** count `warning` events with `category: "escape_restored"` for this run in `.sdlc-transaction-log`.

**Action:** zero is a pass. Each one is a **WARN**: list the file and line range, because the transformer expanded a string and a rule or prompt is letting that happen. A pass still means the file on disk has the escapes intact.

### Check 2d — Dead relative links into layers the project does not carry

Check 2 and Check 2b cannot see a markdown link such as `](disciplines/README.md)`: it has no `[sdlc-root]/` prefix and no concept term. sleeved kept three of them through the 2.2.0 migration (`sdlc/README.md:80, :131, :185`).

**Scan:**

```bash
grep -rnoE --include='*.md' '\]\((\./|\.\./)*(knowledge|disciplines|bundles)/[^)#[:space:]]*' .claude/skills .claude/agents ops/sdlc CLAUDE.md | grep -vE '^ops/sdlc/(knowledge|disciplines)/'
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
   - `source_version` — init: matches the version the operation targeted. Port: unchanged from before the port, or absent (the port changes no file's release). Migrate: still the pre-migration version (§4.5 has not run), or absent when the project was ported from an install with no manifest version, so don't compare it with the target. `knowledge-update` labels its seed with `[target_tag]`, so the knowledge layer and the files reach the same release; Check 5 checks the label.
   - `sdlc_root` — `ops/sdlc`, the only root this plugin supports (on `/sdlc-migrate` a manifest that has no `sdlc_root` yet passes, as in check 0: §4.5 writes the key after this phase); `ops/sdlc/` exists; and `.claude/sdlc/` holds no tracked or unignored file (`preflight.md` check 0). Anything else: **REGRESSION**, because every scan in this file reads `ops/sdlc`, and grep over a missing directory prints an error and finds nothing, so the scans would pass over a root they never looked at
   - `neuroloom_backend` — set to `true`. On `/sdlc-initialize` this phase writes it before checking (`adapter-lifecycle.md` § post-operation item 5): nothing earlier does. It writes `workspace_id` only if absent; one `knowledge-seed` recorded that differs from the sentinel search's `filters.workspace_id` is a **REGRESSION**, never overwritten
   - `install_date` (init) or `ported_at` (port) — set to this operation's timestamp. A migration writes no timestamp field (z-sdlc `sdlc-migrate` §4.5), so there is none to check
   - Initialize: `"knowledge_id_scheme": 2` present and no `knowledge_seed_in_progress` (the seed finished; a run finished by hand that skipped the seed's re-run would otherwise pass here and surface only at the next migration). **REGRESSION** if not.
   - Port: no `port_in_progress` key. Stage 3 writes it and Stage 5 removes it; left behind, it makes the next run's Gate 3 treat a re-port as a continued first port, skipping the re-port refusals
3. `installed_files` map (if present): each entry's on-disk SHA-256 should match the recorded hash. Drift here means a file was edited after the operation wrote it. Migrate: skip every file this run touched, which is every file §4.5 step 3 rehashes after this phase: written, merged or drift-resolved, scripts, templates and bundle tree files included (not only the operational files that have `file_merged` events). A mismatch on a file the run didn't touch is drift from before the run: list it as a WARN, not a regression of this operation. Port: check every entry. Stage 5 rehashed each file this run created, and each it edited whose copy under `<undo>/files/` matched its hash in the pre-run manifest, so a mismatch on one of those means Stage 5 missed it: **REGRESSION**. Any other mismatch (a file the run didn't touch, one that held the project's own edits before the run, or one an earlier attempt transformed) is drift Stage 5 kept on purpose, so a migration asks about it: WARN.

**Action on failure:** **REGRESSION** — manifest and on-disk state are out of sync.

### Check 5 — Knowledge layer reachable (Neuroloom-specific)

**Procedure:**
1. Call `memory_search(query="SDLC workspace sentinel", tags=["sdlc:sentinel"])`, and check that the response's `filters.workspace_id` is the manifest's `workspace_id` (a different one means this check read another workspace: **REGRESSION**)
2. Expect exactly one result whose `sdlc:seed-version:{version}` tag is this operation's seed label: on `/sdlc-initialize`, the manifest's `source_version` (or the short commit id `knowledge-seed` used for an untagged one); on `/sdlc-migrate`, the run's `[target_tag]`; on `/sdlc-port`, the manifest's `knowledge_seed_version`, the label Stage 3a passed (`/sdlc-port` § Inventory, **The seed's label**). A re-port that skipped Stage 3a sends no seed, so the sentinel keeps the first port's label, `knowledge_seed_version`.

Before calling the sentinel missing, look it up by exact tag (`memory_get_index(tags=["sdlc:sentinel"], limit=1)`, then `memory_get_detail` for its tags): the search ranks by relevance, and a sentinel the run just wrote may not have its embedding yet.

**Action on failure:**
- Zero results: sentinel missing or server state corrupted
- Multiple results: workspace has duplicate sentinels (bug in a prior operation)
- Wrong version tag: migrate/port did not update the sentinel

All three are **REGRESSION**, with one exception: a migration whose `knowledge-update` sent nothing and reported that no entry matched exactly for the no-op send (its `noop_ids.txt` was empty) leaves the sentinel on the previous release by design. That is a **WARN** naming both releases.

### Check 6 — No file-mode knowledge layer at the SDLC root

A Neuroloom project keeps the knowledge and parking lots Neuroloom holds in the memory graph, not on disk, and above all has no `ops/sdlc/knowledge/agent-context-map.yaml` acting as live configuration: memory-graph tags replace that file. What Neuroloom doesn't hold stays on disk (z-sdlc contract 0026): the READMEs, diagrams, `provenance_log.md`, and files the project edited. The scans above skip these two directories, so this check is the one that looks at them.

**Procedure:**
1. `/sdlc-port`: skip steps 2 and 3. The port's source files are still there when this audit runs, and Post-Port Cleanup, which runs after it, offers to remove them.
2. List the files under `ops/sdlc/knowledge/` and `ops/sdlc/disciplines/` with whether `installed_files` lists each and, for a listed one, whether its SHA-256 (the first column of `shasum -a 256`) matches the recorded hash, and read `git status --porcelain --untracked-files=all -- ops/sdlc/knowledge ops/sdlc/disciplines`. The flag matters: without it, git reports a directory that is wholly untracked as one line (`?? ops/sdlc/knowledge/`) and names no file in it.
3. A new `ops/sdlc/knowledge/agent-context-map.yaml` (status `??` or `A`) that this run created: **REGRESSION**. On a migration, a `??` or `A` map that `knowledge-update` step 11 listed as left in place was there before the run (an uncommitted map from an older initialize or a port that kept its files): a **WARN**, as for a tracked one below. It is the one file here that changes upstream's behaviour: `sdlc-migrate` §3.3 edits the map whenever it finds one. The `knowledge-update` handler tells a migration never to create it, and the `knowledge-seed` handler (step 8) deletes the one `sdlc-initialize` copies, so a new one means a handler step did not run. A map git already tracks is a **WARN** (an initialize from before plugin 0.7.0 left it, or a port that kept its files; `knowledge-update` step 11 removes it on a migration when git shows it unmodified, and lists it otherwise), with the fix: once any routing in it that isn't committed is saved elsewhere, remove and record it as `knowledge-seed` step 8 does (`rm -f`, a `declined_files` record, and its `installed_files` entry dropped). On `/sdlc-initialize`, an `installed_files` entry here whose content still matches its recorded hash and whose file the extractor seeds (a `.yaml` under `knowledge/` other than the map, a `.md` under `knowledge/` other than a README or `provenance_log.md`, or a `disciplines/*.md` other than `README.md`) is a **REGRESSION**: `knowledge-seed` step 9 didn't remove it (run step 9). On `/sdlc-migrate`, `knowledge-update` step 11 takes only a copy whose every entry it checked this run; a copy it listed as likely redundant is a WARN, pointing at that list (CD compares it with Neuroloom and removes it by hand as the list says). A discipline file it keeps stays for z-sdlc and isn't reported. On a run that began with the map on disk, step 11 took nothing and removed the map only if git showed it unmodified: a map still on disk afterwards is the map WARN above, tracked or not. The files step 9 keeps, and every other file here, are the project's to keep and aren't reported: text Neuroloom doesn't hold (a README, a diagram, `provenance_log.md`) and files the project edited. `sdlc-migrate` updates and merges a kept discipline or other Markdown file on its ordinary path (contract 0026); a kept knowledge YAML stays as the project left it, since its merge is this plugin's and the plugin doesn't merge files. `knowledge-update` step 11 lists an edited one whose upstream text changed, and the files off disk that Neuroloom doesn't hold.
4. All operations: check for any remaining references to `agent-context-map.yaml` as a runtime lookup (vs. a historical mention in the changelog).

**Action on failure:** as in step 3: only a new map, and on initialize a seeded copy step 9 didn't remove, is a **REGRESSION** there. A runtime reference (step 4) is a **REGRESSION**.

---

## Operation-Specific Checks

### /sdlc-initialize

After the shared checks, additionally verify:

- **Project agents created** — `.claude/agents/` contains more than just the framework agents (sdlc-reviewer, sdlc-compliance-auditor, AGENT_TEMPLATE, AGENT_SUGGESTIONS). If no project-specific agents exist, initialization skipped the agent roster stage.
- **Founding spec or README captured** — if the project was greenfield, verify the spec was written and ingested
- **Neuroloom Tool Usage section** — `CLAUDE.md` has the `## Neuroloom Tool Usage` section `post-file-write`'s content injection adds. Missing → **REGRESSION**, with the fix: re-dispatch `post-file-write` on `CLAUDE.md` (z-sdlc runs it once Phase 2 saves the file, contract 0026; content injection waits for that call).
- **Agent names resolve** — re-run the Stale Agent Reference scan (`content-merge-audits.md` § Mandatory: Stale Agent Reference Audit) over the framework files Phase 1 wrote and `CLAUDE.md`'s SDLC region, against the roster Phase 4 made and the manifest's `agent_renames`: in Phase 1 there was no roster, so it could only warn. List each dispatch-position name that still doesn't resolve as a **WARN**, with its file and line and the fix: create the agent, or map the name to one the project has in `.sdlc-manifest.json` → `agent_renames` (`{"<name>": "<agent>"}`), which the next migration's scan substitutes. A stock install's small roster can lack agents z-sdlc's skills name (`debug-specialist`, `research-analyst`, `ui-ux-designer`), so this is a list for CD rather than an initialize failure. The first migration that writes a file naming one of them halts at its stale-agent audit until the agent is created or mapped, so fix them before migrating; a descriptive name is a WARN too.
- **First-run sentinel** — `memory_get_index(tags=["sdlc:sentinel"], limit=2)` returns exactly one row (an exact tag, so a memory that only mentions the sentinel doesn't count), created during this init

### /sdlc-migrate

After the shared checks, additionally verify:

- **The `post-file-write` MCP Retention Audit** already passed (or that phase would have halted). The post-operation audit re-verifies the file counts as a double-check.
- **PROJECT-SECTION markers preserved** — spot-check one file with markers from the transaction log to confirm re-injection happened.
- **Sentinel at the target** — the sentinel's `sdlc:seed-version:` tag is the run's `[target_tag]`, which `knowledge-update` labels its seed with (Check 5), or a WARN when `knowledge-update` reported that nothing matched exactly for the no-op send. It clears at the next seed call: a release with a knowledge change, or a later release with none whose no-op entry the workspace holds byte for byte. Don't check the manifest's `source_version` for the target: §4.5 writes it after this phase (see **When this runs**).
- **Changelog entries consumed** — any `[contract-change]` entries in the migrated range were resolved (not just deferred).
- **Snapshots (outside a git repository)** — leave this run's `.sdlc-manifest.json.pre-migrate-<run_id>` in place (upstream rewrites the manifest after this audit) and list every such copy for CD to remove (`adapter-lifecycle.md` § post-operation item 10).

### /sdlc-port

After the shared checks, additionally verify:

- **Bulk transformation applied** — `/sdlc-port` converts a file-based z-sdlc install to Neuroloom. Verify the transformation touched the expected file set:
  - All files flagged by the phrasing-contract runtime scan (see `${CLAUDE_PLUGIN_ROOT}/agents/neuroloom-transformer.md` § "Step 1: Runtime Scan")
  - All project-tailored agents in `.claude/agents/` (Knowledge Context, Communication Protocol sections)
  - Process docs: `discipline_capture.md`, `overview.md`, `incident_response.md`, etc.
- **Knowledge ingestion complete** — all knowledge YAMLs from the file-based source were ingested into the memory graph with correct tags (`sdlc:knowledge`, `sdlc:domain:<name>`)
- **Original file-based knowledge files listed for Post-Port Cleanup** — the audit runs before the cleanup, so they are still on disk here. List `ops/sdlc/knowledge/` and `ops/sdlc/disciplines/` with their file counts; if the cleanup leaves them behind, a later migration's `knowledge-update` takes the ones whose every entry it confirms Neuroloom holds and lists the rest of upstream's text as likely redundant (Check 6)

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
[✓] No file-mode knowledge layer: no agent-context-map.yaml created by this run (a tracked map, and a copy of what Neuroloom holds left on disk: WARN, each listed)

OPERATION-SPECIFIC CHECKS
[✓] {operation-specific check 1}
[✓] {operation-specific check 2}
...

VERDICT: PASSED — {operation} completed successfully
```

On any failure, replace `✓` with `✗` and inline the specific regression detail. Example:

```
[✗] No residual knowledge-layer paths: 3 hits found
    ops/sdlc/process/discipline_capture.md:18 — consult [sdlc-root]/knowledge/agent-context-map.yaml
    .claude/skills/sdlc-cleanup-comments/references/dispatch-prompts.md:13 — Read [sdlc-root]/knowledge/coding/comment-discipline.yaml
    .claude/skills/sdlc-reflect/SKILL.md:294 — `[sdlc-root]/disciplines/*.md` (write targets)

VERDICT: FAILED — 3 regressions detected
Recovery: {operation-specific recovery instructions}
```

---

## Recovery Instructions by Operation

### /sdlc-initialize failures

Initialization wrote partial state, here and in Neuroloom. The recovery is initialize's in `adapter-lifecycle.md` § Halts and their recoveries: undo nothing (the manifest carries the seed's marker and workspace, and Neuroloom's records stay either way, so undoing the files would leave records no manifest accounts for). Then:
1. File a bug against the plugin for the regression this audit names, and update the plugin.
2. Re-dispatch the transformer on the files the regression names (`post-file-write` § Dispatch), or fix them by hand. A regression in the knowledge layer (Check 4's marker, Check 5's sentinel) is fixed by running `knowledge-seed`'s section again from `adapter-lifecycle.md`.
3. Run this audit again. Never delete `.claude/agents/` wholesale: it holds the agents the project had before initialization.

### /sdlc-migrate failures

Migration changes are uncommitted. Recovery:
1. Follow migrate's recovery in `adapter-lifecycle.md` § Halts and their recoveries: save first, then undo only a run that began on a clean tree. It includes `.sdlc-manifest.json`, which upstream writes after this audit (`warn-continue`): left alone, it says "already on" the target
2. File a bug against the plugin — the transformation missed a phrase
3. Re-run `/sdlc-migrate` after the plugin update

### /sdlc-port failures

Port may have partially transformed files AND partially ingested knowledge. Recovery:
1. Copy every file under this run's `<undo>/files/` back to its path and remove each one `<undo>/created` lists (`<undo>` is `$(git rev-parse --git-path sdlc-port-undo)/<run timestamp>/`, or `.sdlc-port-undo/<run timestamp>/` outside git, the one this run fixed at the start of Stage 4c; never a `git checkout`, which would also discard uncommitted edits in them and in files the port never touched); restore only `CLAUDE.md`'s SDLC region from `CLAUDE.md.pre-port`, first copying (not moving) the current file to `CLAUDE.md.pre-port.before-restore-<timestamp>` (between its markers, or with `CLAUDE.md.pre-port.region` when it had none), as the port's Stage 4d does (if 4d hasn't already used and removed them), and `.sdlc-manifest.json` from `.sdlc-manifest.json.pre-port`, the copies Stages 4c and 5 made, and delete those copies; agent memory comes back with the rest of `<undo>/files/`, where Stage 4g copies each file it changes, since git ignores them (`skills/sdlc-port/references/verification-manifest.md` § Post-Operation Audit). Then delete this run's `<undo>`, so no later recovery applies it again; in the halt report, say the run was undone and its `<undo>` deleted, without naming it as a recovery path, and name every `CLAUDE.md.pre-port*` file other than `CLAUDE.md.pre-port` and `CLAUDE.md.pre-port.region` (Stage 4c's set-aside copies: one may hold the only untransformed original). On a continued port (Gate 3 case 1), also name every other directory under `$(git rev-parse --git-path sdlc-port-undo)/` (or `.sdlc-port-undo/` outside git): an earlier run this one continued, still unrestored, which abandoning the port undoes as well.
2. The knowledge ingestion is idempotent (server-side upsert via `knowledge_id`) so re-running port is safe
3. Re-run `/sdlc-port` after the plugin update

---

## Integration

This protocol is referenced by:
- `/sdlc-initialize` — Phase 10 (Final Verification), before upstream's own checks
- `/sdlc-migrate` — §4.4a, after the compliance audit (§4.4) and before the manifest update (§4.5)
- `/sdlc-port` — final stage before success report

Each skill runs the full shared checks plus its operation-specific subset. Regressions halt the skill.

**Relationship to other gates:**
- **Pre-flight** (`references/preflight.md`) — environmental checks before mutations
- **The transformer's MCP preservation gate** (`agents/neuroloom-transformer.md` Step 2, migrate only) — prevents regressions before they're written
- **The `post-file-write` MCP Retention Audit** (migrate only) — catches file-level regressions immediately after write
- **Post-Operation Audit** (this file) — catches aggregate and cross-file issues after all mutations complete

The layers are defense-in-depth: the preservation gate prevents most bugs, the retention audit catches what it missed, and this audit catches what both missed.
