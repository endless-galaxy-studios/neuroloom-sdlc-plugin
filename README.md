# Neuroloom SDLC Plugin

cc-sdlc knowledge lives in files that die when the context window clears. This plugin backs cc-sdlc with Neuroloom persistent memory — knowledge stores become searchable, deliverable docs sync across sessions, and version updates arrive at session start. It is a companion to the base Neuroloom Claude Code plugin, not a standalone tool.

---

## Prerequisites

- **Neuroloom API key** — get one at [app.neuroloom.dev/settings/api-keys](https://app.neuroloom.dev/settings/api-keys)
- **neuroloom-claude-plugin** — you'll need the Neuroloom Claude Code plugin installed first — this plugin extends it with SDLC-specific memory
- **jq** — required for JSON parsing in hook scripts (`brew install jq` or `apt install jq`)
- **curl** — required for API calls (present on most systems)

---

## Install

### 1. Install the base plugin

If you have not already installed `neuroloom-claude-plugin`, do that first. This plugin declares it as a dependency.

### 2. Install this plugin from the marketplace

```
/plugin install neuroloom-sdlc@endless-galaxy-studios
```

### 3. Reload plugins

```
/reload-plugins
```

### 4. Initialize or port your workspace

**New project (no existing cc-sdlc):**

In Claude Code, run:
```
/sdlc-initialize
```

**Existing project (cc-sdlc already installed locally):**

```
/sdlc-port
```

---

## Skill Inventory

| Skill | When to use |
|-------|-------------|
| `/sdlc-initialize` | New project — seeds cc-sdlc knowledge from upstream and writes operational files |
| `/sdlc-migrate` | Workspace already initialized — pulls latest cc-sdlc release and re-seeds changed entries |
| `/sdlc-port` | Project has local cc-sdlc installed — migrates local knowledge and deliverables to Neuroloom |

---

## How it works

### SessionStart hook

At the start of each Claude Code session, `session-start.sh` runs automatically. It calls the Neuroloom version proxy to check whether a cc-sdlc update is available and compares it to the version seeded in your workspace.

- If the workspace is not initialized: prompts you to run `/sdlc-initialize`
- If an update is available: prints a one-line notice and the command to update
- On any network error: silent exit — never blocks session startup

### PostToolUse hook

After Claude Code writes or edits a file matching `docs/current_work/**/*.md`, `post-tool-use.sh` fires. It reads the file, derives deliverable ID and doc type from the filename, and syncs the content to Neuroloom in a background subshell.

The hook uses a fire-and-forget pattern — it never blocks Claude Code's response cycle. If the API call fails, the payload is buffered to `.neuroloom-sdlc-sync-buffer.json` for retry.

---

## Verification

After installation and initialization, verify the setup:

1. Start a new Claude Code session — you should see no output from the hooks (or a version notice if an update is available)
2. Edit a file under `docs/current_work/` — the PostToolUse hook fires in the background
3. In Claude Code, ask: "Search Neuroloom for recent SDLC deliverables" — the synced docs should appear

To enable debug logging for hook scripts:

```bash
export NEUROLOOM_DEBUG=true
```

---

## Troubleshooting

**"workspace not initialized" on every session start**
Run `/sdlc-initialize` or `/sdlc-port` to create the sentinel memory.

**Hook scripts not firing**
Verify the scripts are executable: `chmod +x hooks/session-start.sh hooks/post-tool-use.sh`. Check that hooks are registered in your Claude Code settings.

**Sync buffer growing**
The file `.neuroloom-sdlc-sync-buffer.json` accumulates payloads when the API is unreachable. Once the API is reachable again, run `/sdlc-port` or manually retry the buffered payloads.

**jq not found**
Install jq: `brew install jq` (macOS) or `apt install jq` (Linux). The hooks exit silently without jq rather than failing.

---

## Reference

### Tag Schema

All SDLC data in Neuroloom is organized via tags with the `sdlc:` prefix. These are the tags the plugin creates and queries:

| Tag | Purpose | Set by |
|-----|---------|--------|
| `sdlc:sentinel` | Marks the workspace sentinel memory (exactly one per workspace) | `/sdlc-initialize`, `/sdlc-port`, `/sdlc-migrate` |
| `sdlc:seed` | Marks memories created by the seed algorithm | `seed()` |
| `sdlc:seed-version:{version}` | Tracks which cc-sdlc version a memory was seeded from | `seed()`, sentinel |
| `sdlc:knowledge-id:{id}` | Stable identifier for upsert deduplication | All ingestion paths |
| `sdlc:project-specific` | Protects memories from being overwritten or deprecated during re-seed | User (manual tag) |
| `sdlc:deprecated` | Marks entries removed from upstream cc-sdlc (not deleted, just tagged) | `seed()` |
| `sdlc:deliverable:{id}` | Links a memory to a deliverable (e.g., `sdlc:deliverable:d17`) | PostToolUse hook |
| `sdlc:doc:{type}` | Document type: `spec`, `plan`, `result`, `chronicle` | PostToolUse hook |
| `sdlc:pattern:{name}` | YAML pattern type: `entries`, `gotchas`, `rules`, `methodology` | YAML parsers |
| `sdlc:triage:{marker}` | Discipline parking lot triage state | Discipline parser |
| `sdlc:project-context` | Workspace project profile (tech stack, conventions) | `/sdlc-initialize` |

### API Endpoints

The plugin communicates with these Neuroloom API endpoints:

| Method | Endpoint | Used by |
|--------|----------|---------|
| `POST` | `/api/v1/documents/ingest` | PostToolUse hook, `/sdlc-port` |
| `POST` | `/api/v1/documents/ingest/batch` | `/sdlc-initialize`, `/sdlc-migrate`, `/sdlc-port` |
| `GET` | `/api/v1/sdlc/cc-sdlc-version` | SessionStart hook |
| `DELETE` | `/api/v1/sdlc/cc-sdlc-version/cache` | `/sdlc-migrate` |
| `POST` | `/api/v1/memories/search` | SessionStart hook (sentinel lookup) |

All endpoints require `Authorization: Token <api_key>`. Workspace is resolved server-side from the API key.

### MCP Tools

The slash commands use these MCP tools (available when the base Neuroloom plugin is installed):

| Tool | Used by |
|------|---------|
| `document_ingest` | `/sdlc-initialize`, `/sdlc-port` (individual knowledge files) |
| `document_ingest_batch` | `/sdlc-initialize`, `/sdlc-migrate`, `/sdlc-port` (batch operations) |
| `sdlc_get_version` | `/sdlc-initialize`, `/sdlc-migrate` |
| `memory_search` | `/sdlc-migrate` (sentinel lookup), `/sdlc-port` (transformation matching) |

### Source Repository

Knowledge is seeded from [Inpacchi/cc-sdlc](https://github.com/Inpacchi/cc-sdlc). The plugin fetches from upstream at init/migrate time — it never vendors or forks the framework.
