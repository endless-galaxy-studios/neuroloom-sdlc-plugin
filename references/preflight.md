# Pre-Flight Health Check

Shared pre-flight protocol used by `/sdlc-initialize` and `/sdlc-migrate` before any mutations. `/sdlc-port` runs check 0 in its own Stage 1, and the `knowledge-seed`, `knowledge-update` and `post-file-write` handlers (`adapter-lifecycle.md`) each run it as their step 0, so the check fires even when upstream does not run this file.

**Purpose:** Fail fast on environmental issues instead of discovering them mid-stage after partial state has been written. Every external dependency gets checked once, at the top, before any user confirmation gate or mutation.

**When this runs:** First stage of both skills, before mode detection, before any user prompts.

---

## Check Matrix

| # | Check | Tool / Mechanism | Pass Condition | Failure Response |
|---|-------|-----------------|----------------|------------------|
| 0 | SDLC root is `ops/sdlc` (run first) | `git ls-files --cached --others --exclude-standard -- .claude/sdlc`, keeping only the paths that exist on disk (a plain `mv` leaves the old paths in the index until it is staged); outside a git repository, `test -e .claude/sdlc`; read `sdlc_root` from `.sdlc-manifest.json` if the file exists; upstream's `[sdlc-root]` once it has chosen one | No path is left; `sdlc_root` is `ops/sdlc` or not set; no key of the manifest's `installed_files` or `declined_files`, and no target path (value) in `bundle_fragments`, starts with `.claude/sdlc/`; and `[sdlc-root]` is `ops/sdlc` | See Failure 0 below |
| 1 | Neuroloom API reachable + authed | `sdlc_get_version` MCP call | Returns a version string (e.g., `"v1.2.3"`) | See Failure 1 below |
| 2 | GitHub reachable + not rate-limited | `gh api rate_limit` | `remaining > 50` (enough for fetches) | See Failure 2 below |
| 3 | Required MCP tools available | Attempt `ToolSearch` or tool listing | All four tools resolve: `document_ingest_batch`, `memory_search`, `memory_store`, `sdlc_get_version` | See Failure 3 below |
| 4 | Required CLI tools | `command -v gh git jq python3` | All four exit 0 | See Failure 4 below |
| 5 | Disk space | `df -k .` | At least 50MB free | See Failure 5 below |
| 6 | Git repo state (migrate only) | `git status --short` | Clean or user confirms dirty-tree migration | See Failure 6 below |

---

## Execution

Run all checks in order. Do **not** short-circuit — collect all failures and report them together. A user dealing with a stale API token AND missing `gh` auth shouldn't have to fix one, re-run, fix the other, re-run.

### Health check output format

```
PRE-FLIGHT HEALTH CHECK
═══════════════════════════════════════
[✓] SDLC root:         ops/sdlc
[✓] Neuroloom API:      reachable (workspace: {workspace_id})
[✓] Neuroloom auth:     valid (key configured)
[✓] GitHub API:         reachable ({remaining}/{limit} calls available, resets at {reset_time})
[✓] MCP tools:          document_ingest_batch, memory_search, memory_store, sdlc_get_version
[✓] CLI tools:          gh 2.x, git 2.x, jq 1.x, python3 3.x
[✓] Disk space:         {free_mb}MB free (need 50MB)
[✓] Git state:          clean | dirty (user confirmed proceed)

All checks passed. Proceeding to {next stage name}.
```

On any failure, replace `✓` with `✗` and inline the specific error. Example:

```
[✗] GitHub API:         rate-limited (0/5000 calls, resets at 15:42 UTC)
                         → Run `gh auth login` to authenticate, OR wait 47 minutes
```

---

## Failure Responses

### Failure 0 — SDLC root is not `ops/sdlc`

Plugin 0.7.0 and later support one SDLC root, `ops/sdlc/`. Earlier versions moved the process docs, templates and playbooks into `.claude/sdlc/`. z-sdlc's factory treats `.claude/` as protected agent configuration and refuses to edit anything under it, so that root can't take part in the factory. Fail when `.claude/sdlc/` holds any tracked file or new, unignored file (even beside `ops/sdlc/`: upstream would pick `ops/sdlc/` and leave the other copy to drift), when the manifest names any other `sdlc_root` or still names a file by a `.claude/sdlc/` path, or when upstream has chosen any other `[sdlc-root]`. The paths matter: `declined_files` is looked up by path, so a stale key makes `knowledge-update` miss a file CD declined. On a migration with a `source_version` the file only lands in the report ("removed by the project"), but on a full migration with no baseline it is seeded into Neuroloom, which this plugin cannot undo. Ignored files left behind after a move (a `.local/` directory, for example) do not count, which is why the check asks `git ls-files` instead of testing whether the directory exists. If `git ls-files` exits non-zero inside a repository, the check fails: it did not look.

```
This project's SDLC root is not ops/sdlc/ ({.claude/sdlc/ holds files | .sdlc-manifest.json has sdlc_root "{value}" | .sdlc-manifest.json names {N} files under .claude/sdlc/ | the run chose [sdlc-root] "{value}"}).
neuroloom-sdlc supports only ops/sdlc/. Before re-running:
  1. Move the contents of .claude/sdlc/ into ops/sdlc/ with git mv
     (or stage the move), so the old paths leave the index.
  2. In .sdlc-manifest.json, set "sdlc_root": "ops/sdlc", re-key every
     installed_files and declined_files entry from .claude/sdlc/... to
     ops/sdlc/..., and update the bundle_fragments target paths.
  3. Update the live references that name .claude/sdlc/ (CLAUDE.md,
     .claude/agents/, .claude/skills/, .claude/agent-memory/); leave
     changelog and deliverable history as written.
  4. Point adapter.plugin_root in the manifest at this plugin version's
     install directory.
  5. Commit the move before re-running, so a recovery can tell your move
     apart from what a run writes.
If .claude/sdlc/ holds only ignored leftovers and the run chose it as
[sdlc-root] anyway (upstream picks any existing .claude/sdlc/), delete the
directory instead of moving it.
If upstream already wrote files in this run and the move was committed
(step 5), `git status --porcelain --untracked-files=all` lists only the
run's writes: restore each changed one with `git checkout -- <path>` and
remove each new one with `git clean -f -- <path>`. If the move was not
committed, git can't tell the run's writes from the move: take the list
from this run's entries in .sdlc-transaction-log instead. Don't restore
whole directories: that would also undo the move.
```
Stop, do not proceed.

### Failure 1 — Neuroloom API issues

**Unreachable:**
```
Cannot reach Neuroloom API at {api_url}. Check:
  - Your network connection
  - NEUROLOOM_API_BASE environment variable
  - The neuroloom-claude-plugin is installed: `/plugins list | grep neuroloom`
```
Stop, do not proceed.

**Auth invalid (401):**
```
Neuroloom API key invalid or expired. Re-configure via:
  /plugins configure neuroloom
Then re-run this skill.
```
Stop, do not proceed.

**Workspace mismatch (403):**
```
API key does not have access to the configured workspace.
  Current workspace_id: {workspace_id}
  Contact your Neuroloom admin or use a different API key.
```
Stop, do not proceed.

### Failure 2 — GitHub API issues

**Rate limited:**
```
GitHub API rate limit exhausted.
  Remaining: 0/{limit}
  Resets at: {reset_time} ({minutes_until_reset} minutes from now)

Options:
  1. Authenticate for higher limits: gh auth login
  2. Wait until reset
```
Stop, do not proceed.

**Unreachable:**
```
Cannot reach GitHub API. Check your network connection.
```
Stop, do not proceed.

### Failure 3 — Missing MCP tools

```
Required MCP tools not available:
  {list of missing tool names}

This usually means neuroloom-claude-plugin is not installed or not active.
  1. Verify installation: /plugins list
  2. Verify the plugin is enabled
  3. Restart Claude Code after installation

Cannot proceed without these tools.
```
Stop, do not proceed.

### Failure 4 — Missing CLI tools

```
Required CLI tools not installed:
  {list of missing tools with install hints}

Install hints:
  gh:       https://cli.github.com/
  git:      system package manager
  jq:       `brew install jq` (macOS) or `apt install jq` (Linux)
  python3:  should be available on modern systems
```
Stop, do not proceed.

### Failure 5 — Insufficient disk space

```
Insufficient disk space in project directory:
  Available: {free_mb}MB
  Required:  50MB minimum ({fetch_size}MB for framework fetch + headroom)

Free up space and re-run.
```
Stop, do not proceed.

### Failure 6 — Dirty git tree (migrate only)

```
Project has uncommitted changes:
{git status output}

Migration will modify files. Recommended actions:
  1. Commit or stash current changes
  2. Re-run /sdlc-migrate on a clean tree

Proceed anyway? (modified files will be diffed individually at Stage 4.2)
```
Ask user. If they proceed, continue. If they cancel, stop.

Not a hard failure — just a warning gate.

---

## Skill-Specific Checks

### Additional checks for `/sdlc-initialize`

None. Init starts from a clean slate, so there's no additional state to verify.

### Additional checks for `/sdlc-migrate`

| # | Check | Pass Condition | Failure Response |
|---|-------|---------------|------------------|
| 7 | Sentinel present | `memory_search(query="SDLC workspace sentinel", tags=["sdlc:sentinel"])` returns one entry | "Workspace not initialized. Run `/sdlc-initialize` first." — stop |
| 8 | Manifest present and valid | `.sdlc-manifest.json` exists + parseable + has `sdlc_version` | Warn "Manifest missing/corrupt — will attempt recovery from sentinel tags" and continue |
| 9 | Transaction log present | `.sdlc-transaction-log` exists (optional, informational) | No failure — just note if this is a first-time migrate post-log-adoption |

---

## Integration With Downstream Stages

- **If all checks pass:** Emit the `All checks passed` line and proceed to Stage 1 (or the skill's first functional stage).
- **If any hard failure:** Emit the full failure report, do not proceed, do not transition state.
- **If only soft warnings (Failure 6, Check 8):** Present the warning, gate on user confirmation, then proceed.

**Record the result** as the first entry in the transaction log (if applicable) so subsequent stages know the environment was validated.

---

## Recovery From Preflight Failure

Preflight is read-only — failures here never leave partial state. Fix the underlying issue (configure key, authenticate gh, free disk, etc.) and re-run the skill from the top. No stage 1+ cleanup required.
