# Stage 4g — Remap Agent Memory Files

Read by `/sdlc-port` Stage 4g (`${CLAUDE_SKILL_DIR}/SKILL.md`).

`.claude/agent-memory/` is gitignored, so no `git checkout` can undo this stage. When Step 1 finds a
match (and only then: with no matches, or no `.claude/agent-memory/` at all, there is nothing to
back up), copy each file to `<undo>/files/<its path>` (Stage 4c's `<undo>`, in the git directory,
which a restart doesn't clear) once, before Step 2 or Step 3 first edits it, as Stage 4c does. Every
undo of the port copies `<undo>/files/` back, so it restores exactly the files 4g changed and leaves
notes another session added to other files alone; the copies go with `<undo>`, when the audit passes or a whole-run undo completes.

Agent memory files (`.claude/agent-memory/*/*.md`) may contain stale `ops/sdlc/knowledge/` and
`ops/sdlc/disciplines/` references from pre-port agent sessions. These are runtime hints agents wrote
to self-load knowledge from the filesystem. Post-port, that knowledge lives in Neuroloom. Other
`ops/sdlc/` paths (process docs, templates, playbooks) are still correct: the SDLC root stays at
`ops/sdlc/`, so leave them as they are.

**Step 1 — Scan for stale references:**

```bash
grep -rnE "ops/sdlc/(knowledge|disciplines)/" .claude/agent-memory/ 2>/dev/null
```

If no matches found, skip to Stage 5.

**Step 2 — Classify and remap** (then give each agent whose memory now calls a Neuroloom tool its tools, as Stage 4c's **Agent tools** does, except that beyond its profile a call in memory grants only a tool in `transforms.yaml` → `memory_grant_tools`, which all read (agents write their own memory): 4c ran before this rewrite. `.claude/agent-memory/<name>/` belongs to `.claude/agents/<name>.md`; skip a directory with no such file, and copy the agent file to `<undo>/files/.claude/agents/<name>.md` first (`mkdir -p` its directory, then `[ -e <copy> ] || cp`))**:**

Two categories of stale references exist in agent memory files:

| Category | Pattern | Replacement |
|----------|---------|-------------|
| Knowledge file paths | `ops/sdlc/knowledge/{path}.yaml` | Replace the file-read instruction with a `memory_search()` call using the knowledge content as the query and appropriate `sdlc:knowledge` tags |
| Discipline file paths | `ops/sdlc/disciplines/{name}.md` | Replace with `memory_search()` call using `tag_prefixes=["sdlc:discipline"]` and the discipline's name in the query (entries an earlier version of this skill ported carry only the bare `sdlc:discipline` tag) |

Both follow the same `memory_search()` pattern used in Stage 4c for agent files. Example:

Before:
```
General TypeScript patterns for type safety are in
`ops/sdlc/knowledge/coding/typescript-patterns.yaml`. Apply those patterns
when designing new types.
```

After:
```
General TypeScript patterns for type safety are retrievable via
memory_search(query="TypeScript type safety patterns", tags=["sdlc:knowledge", "sdlc:domain:coding"], tags_match="all").
Apply those patterns when designing new types.
```

**Step 3 — Preserve historical context:**

Agent memory files that are clearly historical audit records or point-in-time observations (e.g.,
dated audit findings, migration reports) should be left as-is OR annotated with a brief header note
rather than rewritten. These are accurate records of past state.

Use judgment: if the memory is a **runtime instruction** ("load this file for context"), remap it.
If the memory is a **historical record** ("the audit on 2026-03-17 found X at ops/sdlc/..."), leave
it.

**Exclusions from remapping:**
- `sdlc_changelog.md` and `changelog-archive/*.md` historical entries (if referenced)
- `~/src/ops/sdlc/` upstream z-sdlc source refs

Run without asking for confirmation — this is automatic cleanup.
