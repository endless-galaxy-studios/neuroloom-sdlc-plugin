## Stage 5 — Manifest and Verification

### Write Manifest

Write `.sdlc-manifest.json` in the project root:

```json
{
  "neuroloom_backend": true,
  "sdlc_version": "{version from sdlc_get_version, or 'local' if unavailable}",
  "sdlc_root": ".claude/sdlc",
  "source_repo": "https://github.com/Inpacchi/cc-sdlc",
  "source_version": "{version from sdlc_get_version, or 'local' if unavailable}",
  "ported_at": "{ISO 8601 timestamp}"
}
```

Note: `sdlc_version` is the canonical key read by `sdlc-migrate` to detect the operational layer version. It must always be present.

Call `sdlc_get_version` to get the current cc-sdlc release tag. If the call fails or returns no
version, use `"local"`.

Do NOT create or update the sentinel — the sentinel is managed server-side by `seed()`.
This skill triggers ingestion; the server manages the sentinel lifecycle. Only READ the sentinel
for detection purposes.

### Verification Checklist

Run these checks after writing the manifest:

| Check | MCP Call | Pass Condition |
|-------|----------|----------------|
| Sentinel exists | `memory_search(query="SDLC workspace sentinel", tags=["sdlc:sentinel"])` | At least one result returned |
| Knowledge entries seeded | `memory_search(query="SDLC knowledge entries", tags=["sdlc:knowledge"])` | Results count > 0 |
| Discipline entries seeded | `memory_search(query="discipline entries", tags=["sdlc:discipline:architecture"])` | Results count > 0 |
| Deliverable docs synced | `memory_search(query="deliverable spec", tags=["sdlc:deliverable:spec:d1"])` | Results match seeded count |
| No stale path references | Grep transformed files for `ops/sdlc/knowledge/` and `ops/sdlc/disciplines/` | Zero matches in both |
| No stale YAML references | Grep transformed files for `agent-context-map.yaml` and `agent-communication-protocol.yaml` (exclude `ops/sdlc/process/sdlc_changelog.md`) | Zero matches outside changelog |
| No stale `ops/sdlc/process/` refs | Grep transformed files | Zero matches (excluding `sdlc_changelog.md` historical entries and `~/src/ops/sdlc/` upstream refs) |
| No stale `ops/sdlc/templates/` refs | Grep transformed files | Zero matches (excluding `~/src/ops/sdlc/` upstream refs) |
| No stale `ops/sdlc/playbooks/` refs | Grep transformed files | Zero matches |
| No stale `ops/sdlc/examples/` refs | Grep transformed files | Zero matches |
| No stale `ops/sdlc/plugins/` refs | Grep transformed files | Zero matches |
| No stale `ops/sdlc/improvement-ideas/` refs | Grep transformed files | Zero matches |
| Directories present at new paths | `ls .claude/sdlc/` | All six dirs visible |
| Directories absent at old paths | `ls ops/sdlc/` | None of the six dirs present |
| Manifest present | Read `.sdlc-manifest.json` | `neuroloom_backend: true` |
| No stale `ops/sdlc/knowledge/` refs in agent memory | `grep -rn "ops/sdlc/knowledge/" .claude/agent-memory/` | Zero matches |
| No stale `ops/sdlc/disciplines/` refs in agent memory | `grep -rn "ops/sdlc/disciplines/" .claude/agent-memory/` | Zero matches |
| No stale structural `ops/sdlc/` refs in agent memory | `grep -rn "ops/sdlc/" .claude/agent-memory/` | Zero matches (excluding `~/src/ops/sdlc/` and historical audit records) |

Exclusion rules for grep checks on relocated directories:
- Exclude `sdlc_changelog.md` historical entries
- Exclude lines matching `~/src/ops/sdlc/` (upstream cc-sdlc source path)

If any check fails, report the specific failure and its recovery path (see Error Handling below).

**Count verification:**

Compare seeded counts against the Stage 1 inventory. Run:
```
memory_search(query="SDLC knowledge entries", tags=["sdlc:knowledge"], limit=500)
```
The result count should be approximately equal to the Stage 1 entry count for
knowledge + disciplines combined. This is a spot-check, not an exact enumeration.
If the workspace has more than 500 entries the check is indicative only — a
significantly lower result warrants investigation but is not necessarily a hard block.

If the seeded count appears materially short of the Stage 1 count, identify the gap:
1. Note which category is short (knowledge vs. discipline)
2. Re-run `sdlc_seed` for that category only
3. Re-run the count check

Do not mark the port complete if a material discrepancy cannot be explained.

### Post-Operation Audit

**Run the shared post-operation audit** at `${CLAUDE_PLUGIN_ROOT}/references/post-operation-audit.md`. Execute the shared checks AND the `/sdlc-port`-specific subset.

The audit verifies the bulk transformation landed correctly — every file-based reference that should have become a `memory_search`/`memory_store` call actually did, across all targeted files. The port touches a much larger surface than a typical migration (it converts an entire file-based install), so aggregate checks are essential:
- Every file flagged by the phrasing-contract runtime scan (see `sdlc-migrate` § "Detecting Files That Contain Phrasing-Contract Patterns") contains at least one MCP call
- No residual cc-sdlc standard phrases (they should all be transformed)
- No inline adapter conditionals (contract violations)
- Knowledge YAMLs fully ingested with correct domain tags
- Original file-based knowledge files removed or marked (no drift risk)

**If the audit fails:** Halt. Do NOT proceed to Post-Port Cleanup. Follow the audit's recovery instructions. For port failures: `git checkout -- .claude/` to restore filesystem; knowledge ingestion is idempotent so re-running port after a plugin fix is safe.

### Post-Port Cleanup

Use `AskUserQuestion` to ask the user whether to remove the following content,
which is now redundant now that Neuroloom is the source of truth and operational
files have been moved to `.claude/sdlc/`:

Question text:
```
The following local directories are now redundant — Neuroloom holds their
knowledge content, and operational files have been moved to .claude/sdlc/:

  ops/sdlc/knowledge/       ({N} files) — ingested into Neuroloom
  ops/sdlc/disciplines/     ({M} files) — ingested into Neuroloom
  ops/sdlc/                 (remaining: CLAUDE-SDLC.md, README.md, and
                             empty dirs if any) — source directories now moved

Remove the remaining ops/sdlc/ content now?
```

Options:
1. Remove ops/sdlc/knowledge/ and ops/sdlc/disciplines/ (leaves ops/sdlc/ root files)
2. Remove all remaining ops/sdlc/ content (knowledge/, disciplines/, and root files)
3. Keep all (I'll remove manually)
4. Keep all and skip this prompt on future re-ports

If the user selects option 1: run `rm -rf ops/sdlc/knowledge/ ops/sdlc/disciplines/`.
If the user selects option 2: run `rm -rf ops/sdlc/`.
If the user selects option 3: do nothing.
If the user selects option 4: do nothing to the directories, but write `skip_cleanup_prompt: true`
  into `.sdlc-manifest.json`. On future re-ports, Stage 1 (Mode Detection) must check this flag
  and skip the cleanup question entirely if it is set.

Always keep:
- `.claude/sdlc/process/` — process docs (moved here by Stage 4f)
- `.claude/sdlc/templates/` — templates (moved here by Stage 4f)
- `docs/_index.md` — deliverable catalog remains filesystem-local

### Final Summary

Output a completion summary:

```
Neuroloom SDLC Port Complete — {N} knowledge + {M} discipline entries seeded, {J} files transformed

Ported local cc-sdlc installation to Neuroloom backend. {N} knowledge entries and {M} discipline entries are now searchable via memory_search; {K} deliverable docs synced; {J} agent/skill files transformed from file-path to MCP references.

  Knowledge entries seeded:  {N}
  Discipline entries seeded: {M}
  Deliverable docs synced:   {K}
  Agent/skill files updated: {J}

Next step: Run /sdlc-migrate to check for upstream cc-sdlc updates.
```

---

