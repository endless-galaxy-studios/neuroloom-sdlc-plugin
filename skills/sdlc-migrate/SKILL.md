---
name: sdlc-migrate
description: >
  Updates SDLC knowledge in a Neuroloom workspace to the latest cc-sdlc version. Compares the
  workspace's current seeded version against the latest upstream release, re-seeds changed entries,
  deprecates removed entries (without deleting them), and updates the workspace sentinel.
  Triggers on "migrate sdlc", "update sdlc knowledge", "upgrade sdlc version",
  "sdlc update available", "update the sdlc backend".
  Do NOT use for first-time workspace setup — use sdlc-initialize.
  Do NOT use for porting an existing local cc-sdlc installation to Neuroloom — use sdlc-port.
---

# SDLC Migrate

Apply cc-sdlc upstream updates to this Neuroloom workspace while preserving project-specific customizations. Unlike a raw re-initialization, this skill is **content-aware** — it understands the two-layer architecture and migrates each layer independently.

Run this when the `SessionStart` hook reports an update is available, or at any time to check for updates manually.

---

## Two-Layer Architecture

Every SDLC workspace has two independent layers. Both must be in sync with the same cc-sdlc version.

| Layer | What Lives Here | How Updated |
|-------|----------------|-------------|
| **Knowledge layer** (Neuroloom API) | Knowledge YAMLs, discipline entries, deliverable doc templates | `document_ingest_batch` MCP tool with `knowledge_id` for server-side upsert |
| **Operational layer** (filesystem) | Skills, agents, process docs, templates, `CLAUDE.md`, `.sdlc-manifest.json`, `hooks/` files | Direct file writes via Write/Edit tools |

**Both layers must be updated together.** Knowledge current but skills stale causes tool failures. Skills current but knowledge stale produces outdated guidance. If one layer is already at the target version, update only the other — but always verify both are current before reporting success.

---

## Stage 1 — Pre-Flight + Version Check

### 1.1 Verify workspace is initialized

Call `memory_search(query="SDLC workspace sentinel", tags=["sdlc:sentinel"])`. If no result is returned, output:

```
This workspace has not been initialized. Run /sdlc-initialize first.
```

Do not proceed.

### 1.2 Verify API is reachable

Call `sdlc_get_version`. This doubles as an API reachability check.

- If it fails with an auth error: "Neuroloom API key not configured or invalid. Check ~/.neuroloom/config.json."
- If it fails with a network error: "Cannot reach Neuroloom API. Check your api_url in ~/.neuroloom/config.json."

Do not proceed if either check fails.

### 1.3 Extract current versions

From the sentinel memory:
- Extract the `sdlc:seed-version:{version}` tag to get `KNOWLEDGE_VERSION` (the version the knowledge layer was last seeded at).

From `.sdlc-manifest.json` in the project root:
- Read `sdlc_version` to get `OPERATIONAL_VERSION` (the version the filesystem layer was last updated at).

If `.sdlc-manifest.json` is missing, treat `OPERATIONAL_VERSION` as unknown and flag it in the pre-flight report.

### 1.4 Get latest upstream version

Store the result of `sdlc_get_version` as `LATEST_VERSION`.

### 1.5 Version comparison and early-exit logic

Compare both layer versions against `LATEST_VERSION`:

| Knowledge layer | Operational layer | Action |
|----------------|-------------------|--------|
| Current | Current | Output "SDLC is up to date ({LATEST_VERSION})." Stop. |
| Current | Stale or unknown | Skip Stage 3 knowledge fetch. Jump to Stage 4 operational update only. |
| Stale | Current | Perform knowledge re-seed only. Skip operational file updates in Stage 4. |
| Stale | Stale or unknown | Full migration — both layers. |

Report the assessment to CD before proceeding:

```
Pre-flight complete.

  Knowledge layer:   {KNOWLEDGE_VERSION} (target: {LATEST_VERSION}) — [current / update needed]
  Operational layer: {OPERATIONAL_VERSION} (target: {LATEST_VERSION}) — [current / update needed]

Proceeding with: [full migration / knowledge only / operational only]
```

---

## Stage 2 — Changelog Review Gate

**CD must confirm before any changes are applied.**

### 2.1 Fetch the changelog

Download the cc-sdlc CHANGELOG.md at `LATEST_VERSION` from GitHub:

```
gh api repos/Inpacchi/cc-sdlc/contents/CHANGELOG.md --jq '.content' | base64 -d
```

Or via raw URL: `https://raw.githubusercontent.com/Inpacchi/cc-sdlc/{LATEST_VERSION}/CHANGELOG.md`

### 2.2 Extract entries since workspace version

Parse all changelog entries between `KNOWLEDGE_VERSION` (or the older of the two layer versions) and `LATEST_VERSION`. Identify:

- **Breaking changes** — marked with `BREAKING` or `breaking change` in the changelog
- **Deprecations** — entries removed from the knowledge layer
- **Convention renames** — skill renames, tag renames, parameter changes
- **New capabilities** — new skills, new knowledge domains, new MCP tools

Note any changelog items that reference CLAUDE.md sections, skill invocation patterns, or agent configurations — these require a CLAUDE.md compatibility check in Stage 4.

### 2.3 Present to CD for confirmation

Use `AskUserQuestion` to present the changelog summary and require explicit confirmation before proceeding:

```
cc-sdlc changelog: {KNOWLEDGE_VERSION} → {LATEST_VERSION}

Breaking changes:
  [list or "None"]

Deprecations:
  [list or "None"]

Convention renames:
  [list or "None"]

New capabilities:
  [list or "None"]

Proceed with migration?
```

Options: `Yes, apply migration` / `No, cancel` / `Show full changelog first`

If CD selects "Show full changelog first," display the raw changelog and re-present the confirmation.

If CD cancels, stop. Do not apply any changes.

---

## Stage 3 — Fetch + Diff

Only run this stage for layers that need updating (per Stage 1.5 assessment).

### 3.1 Fetch the new release

Download the full file listing of the `Inpacchi/cc-sdlc` repo at `LATEST_VERSION`:

```
gh api repos/Inpacchi/cc-sdlc/git/trees/{LATEST_VERSION}?recursive=1
```

Download the content of all knowledge YAMLs, discipline markdown files, skill files, agent templates, process docs, templates, and CLAUDE.md from the new release.

Use the GitHub contents API for individual files:

```
gh api repos/Inpacchi/cc-sdlc/contents/{path}?ref={LATEST_VERSION} --jq '.content' | base64 -d
```

### 3.2 Build the change manifest

For the **knowledge layer**, compare each `knowledge_id` in the new release against workspace entries:

| Change Type | Definition |
|-------------|-----------|
| New | `knowledge_id` not found in workspace |
| Updated | `knowledge_id` exists, content differs |
| Unchanged | `knowledge_id` exists, content identical |
| Deprecated | `knowledge_id` present at `KNOWLEDGE_VERSION`, absent from new seed |

For the **operational layer**, compare each file in the new release against the current filesystem version. Use `.sdlc-manifest.json` to identify the base version for diff. Categorize as: unchanged, updated (framework-only changes), or modified (project has customizations).

### 3.3 Present change manifest and request confirmation

Use `AskUserQuestion`:

```
Change manifest: {KNOWLEDGE_VERSION} → {LATEST_VERSION}

Knowledge layer:
  New:        {N} entries
  Updated:    {N} entries
  Unchanged:  {N} entries
  Deprecated: {N} entries (will be tagged deprecated, not deleted)

Operational layer:
  Unchanged:  {N} files
  Updated:    {N} files (framework-only changes — will overwrite)
  Modified:   {N} files (project customizations detected — will require review)

Apply migration?
```

Options: `Yes, apply` / `No, cancel` / `Show detailed file list`

If there are modified operational files, note that Stage 4 will present a per-file confirmation for each one.

---

## Stage 4 — Apply Migration

### 4.1 Re-seed the knowledge layer

Call `document_ingest_batch` with all new and updated knowledge entries. Batch in groups of up to 50 documents per call.

The server handles all migration cases automatically via `knowledge_id` matching:
- **New entries** — created with the new version tag
- **Changed entries** — content updated, version tag updated, importance scores preserved
- **Unchanged entries** — no-op (server detects no diff)
- **Removed entries** — tagged `sdlc:deprecated` server-side, NOT deleted
- **Project-specific entries** (`sdlc:project-specific` tag) — never modified by re-seeding

Each document must include:
- `knowledge_id` — the stable ID used at initialization (must always be included — omitting it breaks upsert)
- `version` — `{LATEST_VERSION}`
- `source_type` — `"sdlc_knowledge"`
- `format` — `"yaml"` or `"markdown"` as appropriate
- `tags` — `["sdlc:knowledge", "sdlc:seed", "sdlc:seed-version:{LATEST_VERSION}"]` plus applicable domain/type tags per the tag schema

**Do NOT manually add `sdlc:knowledge-id:{id}` to the tags array.** Pass `knowledge_id` as a parameter; the server creates the tag automatically.

Check the batch response:

```json
{
  "summary": {"total": N, "created": N, "updated": N, "unchanged": N, "errors": N},
  "results": [{"index": N, "title": "...", "status": "...", ...}]
}
```

If `summary.errors > 0`, log the failed entries (title, error message) and report them in Stage 5. Do not abort — continue with the operational layer.

### 4.2 Update operational layer files

Apply the content-merge strategy for each file category:

#### Skills

**Plugin skills** (`sdlc-initialize`, `sdlc-migrate`): These are owned by `neuroloom-sdlc-plugin/skills/` — NOT `.claude/skills/`. Do not write cc-sdlc originals to `.claude/skills/`. If stale cc-sdlc originals exist from a prior installation, delete them:

```
rm -rf .claude/skills/sdlc-initialize/ .claude/skills/sdlc-migrate/
```

The plugin versions are the authoritative replacements, updated from the plugin repo, not cc-sdlc upstream.

**cc-sdlc core skills** (all other skills in `.claude/skills/`): Always overwrite with the new upstream content. These have no project customizations.

**Enhanced skills** (`sdlc-archive`, `sdlc-audit`): Merge — keep Neuroloom-specific sections (API call patterns, MCP tool references, tag schema), update cc-sdlc sections (stage logic, verification checklists, red flags tables). Present a diff via `AskUserQuestion` if the Neuroloom sections appear to have been modified by the project.

**Audit skill special handling:** The `sdlc-audit` skill has framework audit methodology in `SKILL.md` and `references/` that must stay current:

1. Read the cc-sdlc source versions of all audit skill files
2. Read the project's versions
3. Update SKILL.md workflow, modes, and reference pointers — **verbatim from cc-sdlc source, not rephrased**
4. Update `references/compliance-methodology.md` audit dimensions and report format
5. Update `references/improvement-methodology.md` extraction patterns and categorization
6. Update `references/session-reading.md` JSONL format reference
7. Preserve any project-specific audit dimensions or improvement categories added by the project

**Migration note:** The `sdlc-compliance-auditor` agent has been restored as a subagent dispatched by `sdlc-audit`. If the project has an old version, update it to the current version. If the project removed it during a prior migration, re-install it.

#### Agents

Re-run the project-stack tailoring logic from `sdlc-initialize`: update the framework-derived sections of each agent file (tool lists, knowledge query patterns, handoff format) while preserving the agent name, domain description, and any project-added agents that do not exist in the upstream template set.

If an upstream agent template was renamed: flag it. Do not silently overwrite a renamed agent.

#### Process docs

Overwrite cc-sdlc originals (files that originated from the upstream framework). Preserve files that were added by the project and have no upstream equivalent — identify these by checking `.sdlc-manifest.json` for the file origin.

#### `.sdlc-manifest.json`

Update the `sdlc_version` field to `LATEST_VERSION`. Preserve all project-specific fields.

#### `hooks/` files

Overwrite all files under `neuroloom-sdlc-plugin/hooks/` with the upstream plugin versions.

#### Modified file review gate

For each operational file flagged as modified (project customizations detected):

Use `AskUserQuestion` with the file path, a diff summary, and three options:

```
File: {path}
Status: Modified — project customizations detected

Upstream change: {one-line summary}
Your local change: {one-line summary of the detected customization}

How should this be handled?
```

Options: `Accept upstream (overwrite)` / `Keep mine (skip this file)` / `Show full diff`

If CD chooses "Show full diff," display it and re-present the same three options.

Record the outcome for the Stage 5 report.

### 4.2-gate. Content-Merge Verification

**Before proceeding to CLAUDE.md checks**, verify the content-merge results didn't corrupt project data. This catches merge errors before they propagate.

**Quick checks (< 2 minutes):**

1. **Skill customization preservation** — spot-check 1 enhanced skill (e.g., `sdlc-audit`):
   - Neuroloom-specific sections (API call patterns, MCP tool references) are intact
   - Framework sections were updated (compare against cc-sdlc source)

2. **Agent integrity** — spot-check 1 agent:
   - Framework-derived sections (Knowledge Context, Communication Protocol) were updated
   - Domain-specific content (scope, principles, workflow) was preserved

3. **Audit skill completeness** — verify all `references/` files were updated and any project-specific audit dimensions preserved

**Gate rule:** If any check fails, fix the merge before continuing. Do not proceed to Stage 4.3 with corrupted content.

### 4.3 CLAUDE.md compatibility check

Check the CLAUDE.md SDLC section for references that may have gone stale based on changelog-flagged items noted in Stage 2:

- Skill invocation patterns (e.g., `/sdlc-initialize`, `/sdlc-audit`)
- Stage or phase terminology that was renamed
- Tool parameter names that changed
- Tag names that were renamed

For each stale reference found, either update it automatically (if the change is a clear 1:1 rename) or flag it for CD review via `AskUserQuestion`.

If no changelog items flagged CLAUDE.md-relevant changes, this check is a no-op — report "No CLAUDE.md updates needed."

### 4.4 Sentinel

The sentinel is managed SERVER-SIDE by `seed()`. Do not create, update, or tag it manually. The server updates the sentinel's `sdlc:seed-version:{version}` tag automatically when the knowledge re-seed completes. After Stage 4.1 completes, re-read the sentinel via `memory_search(query="SDLC workspace sentinel", tags=["sdlc:sentinel"])` to confirm the server updated it.

---

## Stage 5 — Verification + Compliance Audit + Report

### 5.1 Knowledge layer spot-check

Verify the knowledge layer updated correctly by sampling 3–5 entries that were expected to change:

For each sampled entry, call `memory_search` with a query matching the entry's content and confirm:
- The `sdlc:seed-version:{LATEST_VERSION}` tag is present
- The content matches the new upstream version

If any spot-check fails, flag the entry in the report. Do not silently pass.

### 5.2 Operational layer verification

Confirm the following:

- [ ] All overwritten skill files contain the new upstream content
- [ ] `.sdlc-manifest.json` shows `sdlc_version: {LATEST_VERSION}`
- [ ] Sentinel's `sdlc:seed-version` tag reads `{LATEST_VERSION}` (confirmed via `memory_search`)
- [ ] `hooks/` files match upstream plugin versions
- [ ] No agent files were silently overwritten without project review (modified files were presented to CD)
- [ ] CLAUDE.md compatibility check completed and stale references resolved

### 5.3 Compliance audit

Dispatch the `sdlc-compliance-auditor` agent with a post-migration context:

```
Context: Post-migration audit. cc-sdlc version just updated from {KNOWLEDGE_VERSION} to {LATEST_VERSION}.
Check: knowledge layer integrity, operational file consistency, sentinel validity, deprecated entry tagging.
Flag: any version skew between knowledge and operational layers.
```

Wait for the auditor's report. If findings are CRITICAL, address them before closing the migration.

### 5.4 Report to CD

Output the full migration summary:

```
SDLC migration complete: {KNOWLEDGE_VERSION} → {LATEST_VERSION}

Knowledge layer:
  Created:     {N} new entries
  Updated:     {N} changed entries
  Unchanged:   {N} entries
  Deprecated:  {N} entries (preserved, tagged sdlc:deprecated)
  Errors:      {N} (see below if > 0)

Operational layer:
  Overwritten: {N} files
  Skipped:     {N} files (kept project version)
  Modified:    {N} files (required manual review — see decisions below)

CLAUDE.md: {updated N references / no updates needed}

Compliance audit: {pass / N findings — see below}

Migration decisions:
  [table of modified files and CD's chosen action for each]

Errors (if any):
  [list of knowledge entries that failed to ingest, with error messages]
```

---

## Content-Merge Strategy Reference

This table governs Stage 4 decisions. Consult it when a file's category is ambiguous.

| File Category | Strategy | Rationale |
|---------------|----------|-----------|
| cc-sdlc core skills | Always overwrite | No project customizations expected |
| Plugin skills (initialize, migrate, port) | Always overwrite | Maintained in this plugin repo |
| Enhanced skills (archive, audit) | Merge | Contain Neuroloom-specific API sections |
| Agent files (upstream templates) | Re-run tailoring | Framework sections update; domain desc preserved |
| Agent files (project-added) | Skip | No upstream equivalent — never touch |
| Process docs (upstream originals) | Overwrite | No project customizations expected |
| Process docs (project-added) | Skip | No upstream equivalent |
| `.sdlc-manifest.json` | Partial update | Only update version fields |
| `hooks/` files | Always overwrite | Plugin-managed; no project customizations |
| `CLAUDE.md` SDLC section | Targeted update | Only stale references; preserve project additions |

**Modified file rule:** If git diff shows the project has changed a file that would normally be overwritten, treat it as Modified and surface a review gate (Stage 4.2). Never silently overwrite a file with project customizations.

---

## Early-Exit Logic

The skill has two independent early-exit conditions. Both must be satisfied before reporting the workspace as fully up to date.

**Knowledge layer current, operational layer current:** Both versions match `LATEST_VERSION`. Output "SDLC is up to date." Stop.

**Knowledge layer current, operational layer stale:** Skip Stage 3 knowledge fetch and Stage 4.1 re-seed. Run Stage 4.2–4.4 only. Report as "Operational layer updated; knowledge layer was already current."

**Knowledge layer stale, operational layer current:** Run Stage 3 and Stage 4.1 only. Skip Stage 4.2 file updates. Report as "Knowledge layer updated; operational layer was already current."

**Neither layer version known:** `.sdlc-manifest.json` missing, sentinel missing. Cannot determine current state — abort and tell CD to run `/sdlc-initialize`.

---

## Red Flags

| If you find yourself thinking... | Stop. The correct behavior is... |
|----------------------------------|----------------------------------|
| "I'll update knowledge but skip the operational files." | Version skew between knowledge and skills causes failures. Both layers must update together unless one is already confirmed current at the target version. |
| "Re-seeding will overwrite my project-specific knowledge." | Entries tagged `sdlc:project-specific` are never touched by re-seeding. Verify the tag is present on each entry you want protected before running the migration. |
| "The version check says up-to-date so nothing needs to happen." | Check both layers independently. Knowledge and filesystem can drift — one may be current while the other is stale. |
| "I can skip the confirmation gate for a minor version bump." | Even minor bumps can deprecate entries or rename conventions. Always show the change manifest and require CD confirmation. |
| "I need to manually tag deprecated entries." | Deprecation is handled server-side by `seed()`. The skill only re-seeds; the server handles removal tagging. Never add `sdlc:deprecated` manually. |
| "I'll skip the changelog review — it's just release notes." | The changelog flags breaking changes and convention renames. Skipping it means CLAUDE.md references go stale silently and agent invocations break in ways that are hard to trace. |
| "The compliance audit can wait until next session." | Post-migration audit catches integrity issues that compound quickly. Dispatch the auditor now, in Stage 5. |
| "I can update the sentinel after the operational layer too." | The sentinel is read-only to skills. The server updates it automatically. Never write to it manually. |
| "I'll call `memory_search` without a query parameter." | `memory_search` requires a mandatory `query` string. Tags alone are not sufficient. Every call must include an explicit query. |

---

## Integration

**Depends on:**
- `sdlc-initialize` — workspace must have been initialized; migrate does not create a workspace from scratch
- `sdlc_get_version` MCP tool — provides the latest cc-sdlc release tag
- `document_ingest_batch` MCP tool — performs all knowledge layer updates
- `memory_search` MCP tool — reads sentinel and spot-checks knowledge entries
- GitHub API — source for upstream skill, agent, and process doc content

**Feeds into:**
- `sdlc-audit` — run post-migration to verify integrity; migrate dispatches auditor automatically in Stage 5
- `SessionStart` hook — reads sentinel version to detect when migration is needed; after a successful migrate, the hook should no longer report an update available

**Related skills:**
- `sdlc-initialize` — first-time workspace setup; use this when no sentinel exists
- `sdlc-port` — migrate an existing local cc-sdlc filesystem installation into a Neuroloom workspace; use this when transitioning from the old file-based model

## Migration vs Initialization

| | `sdlc-initialize` | `sdlc-migrate` |
|---|---|---|
| **When to use** | First time — no workspace exists | Workspace exists, version is outdated |
| **Sentinel** | Created by server (first seed) | Read-only; updated by server |
| **Knowledge layer** | Full seed from scratch | Upsert via `knowledge_id` matching |
| **Operational layer** | Full copy of all files | Content-merge with project diff review |
| **CD confirmation** | Required at Stage 4 (write gate) and Stage 6a (roster approval) | Required at changelog gate and change manifest gate |
| **Modified file handling** | N/A (no existing files) | Review gate per file with overwrite/skip options |
| **Compliance audit** | Dispatched in Stage 10 | Dispatched automatically in Stage 5 |
