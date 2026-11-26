# Stage 4a — What to transform, and what not

Read by `/sdlc-port` Stages 4a and 4c (`${CLAUDE_SKILL_DIR}/SKILL.md`).

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
- **Skill integration steps** (e.g., sdlc-develop-agent): steps that say "update
  `agent-context-map.yaml`" → update to reflect Neuroloom as the knowledge backend
- **Compliance/audit methodology** (e.g., compliance-methodology.md): maturity level criteria and
  wiring tier descriptions that reference `agent-context-map` as a concept → update to reference
  Neuroloom retrieval
- **`process/knowledge-routing.md`**: replace the whole file with the plugin's Neuroloom variant —
  copy `${CLAUDE_PLUGIN_ROOT}/docs/knowledge-routing.md` over `ops/sdlc/process/knowledge-routing.md`, as
  migrations do (`${CLAUDE_PLUGIN_ROOT}/references/adapter-lifecycle.md` § Adapter-specific docs). Don't
  edit it in place: the audit exempts it from the residue scans, so nothing would catch a partial rewrite

**What NOT to transform:**
- Template structural scaffolding in `ops/sdlc/templates/` (section headers, placeholder text) that
  names no knowledge, discipline or provenance path. A `[sdlc-root]/knowledge/` or
  `[sdlc-root]/disciplines/` reference anywhere in a template, placeholder text included, is
  transformed like any other, as `post-file-write` does on a migration: the audit has no template
  exemption.
- `docs/_index.md` — remains filesystem-local
- The files and blocks the post-operation audit's Check 2 exempts
  (`${CLAUDE_PLUGIN_ROOT}/references/post-operation-audit.md`, exemption rows 1 to 7: the framework-
  mechanics lines of `.claude/skills/sdlc-migrate/`, the quoted span of a reviewer's or auditor's
  `- [ ] No` item, the process docs that name the paths on purpose, such as `path-mappings.md`, the
  changelog, format or command demos in code fences, which row 5 limits (a fenced dispatch
  prompt, agent template or output template is transformed), the contract 0026 file-presence
  lines row 6 names, and the two `sdlc-ingest` destination rows row 7 names). Stage 4d's path and bare-YAML checks
  don't report them either. Two exceptions: (a) `knowledge-routing.md` is replaced whole (above);
  (b) a relative link into `knowledge/` or `disciplines/` on any of these lines except the changelog's
  (row 6's and row 7's lines carry none), or a `provenance_log` mention on any of them except the changelog's and
  row 6's, is still rewritten (rows 1 and 3 included, e.g. `sdlc-migrate`'s list of project-specific
  files), because Check 2d exempts only the changelog and the audit's provenance scan only the
  changelog and row 6.
- The `sdlc-migrate` lines that post-operation Check 6 step 4's closed list names (`${CLAUDE_PLUGIN_ROOT}/references/post-operation-audit.md`): they name `agent-context-map.yaml` as a file the project owns or act on it only when it is on disk, and `pattern-mapping-rules.md` keeps them as upstream has them, apart from the `provenance_log.md` item it drops from two of them (`Source-to-project path mappings` and Step 0), so Stage 4d's provenance check finds nothing there. Stage 4d's bare-YAML check doesn't report them either.
- Agent or skill files with no matching references
- Historical changelog entries in `ops/sdlc/process/sdlc_changelog.md` and `ops/sdlc/process/changelog-archive/*.md` — these are an accurate
  record of what happened at the time and must not be rewritten
- `ops/sdlc/knowledge/provenance_log.md` itself: Stage 3c stored its entries as `sdlc:provenance`
  memories, and Post-Port Cleanup removes the file with the other flat knowledge files once Stage 3c
  stored every entry (otherwise it keeps it)

**Project-specific files:**
- `process/agent-selection.yaml` — project's agent roster and dispatch rules; it stays where it is and
  is never overwritten during future migrations

## Replacement queries

Example replacement:

Before:
```
Read ops/sdlc/knowledge/developer-documentation-patterns.yaml for DX heuristics.
```

After:
```
Call memory_search(query="developer documentation DX heuristics", tags=["sdlc:knowledge", "sdlc:domain:design"], tags_match="all")
to retrieve current documentation patterns.
```

**Distinct queries per reference.**

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

**Shared references across agents.**

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
