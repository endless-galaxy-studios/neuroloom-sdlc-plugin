# Pre-Flight Health Check

Shared pre-flight protocol used by `/sdlc-initialize` and `/sdlc-migrate` before any mutations.

**Purpose:** Fail fast on environmental issues instead of discovering them mid-stage after partial state has been written. Every external dependency gets checked once, at the top, before any user confirmation gate or mutation.

**When this runs:** First stage of both skills, before mode detection, before any user prompts.

---

## Check Matrix

| # | Check | Tool / Mechanism | Pass Condition | Failure Response |
|---|-------|-----------------|----------------|------------------|
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
