# Per-Category File Handling Rules

These rules apply after the §4.2.0 MCP Preservation Gate. They govern category-specific merge behavior for the non-MCP portions of each file.

#### Skills

**Plugin skills** (`sdlc-initialize`, `sdlc-migrate`): These are owned by `neuroloom-sdlc-plugin/skills/` — NOT `.claude/skills/`. Do not write cc-sdlc originals to `.claude/skills/`. If stale cc-sdlc originals exist from a prior installation, delete them:

```
rm -rf .claude/skills/sdlc-initialize/ .claude/skills/sdlc-migrate/
```

The plugin versions are the authoritative replacements, updated from the plugin repo, not cc-sdlc upstream.

**cc-sdlc core skills** (all other skills in `.claude/skills/`, including opt-in bundle skills listed in `.sdlc-manifest.json` → `installed_bundles`): Apply the §4.2.0 preservation gate. These skills frequently contain MCP calls injected during `/sdlc-port` (e.g., `sdlc-design-consult`, `research-external`, `sdlc-review-fix`, `sdlc-tests-create`, `sdlc-tests-run` all carry cross-domain knowledge injection that was transformed to `memory_search`). Do NOT assume core skills have no customizations — the gate will detect and preserve MCP content. Non-MCP framework sections update verbatim from upstream.

**Enhanced skills** (`sdlc-archive`, `sdlc-audit`): Apply the §4.2.0 preservation gate, then merge — keep Neuroloom-specific sections (API call patterns, MCP tool references, tag schema), update cc-sdlc sections (stage logic, verification checklists, red flags tables). Present a diff via `AskUserQuestion` if the Neuroloom sections appear to have been modified by the project.

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

**Framework agent files** (`sdlc-reviewer.md`, `sdlc-compliance-auditor.md`): Apply the §4.2.0 preservation gate. Non-MCP framework sections update verbatim from upstream.

**Agent template** (`agent-template.md`): Now lives at `[sdlc-root]/templates/agent-template.md`, not `.claude/agents/`. Apply the §4.2.0 preservation gate when updating. If the project has an old `.claude/agents/AGENT_TEMPLATE.md`, delete it after verifying the templates/ copy is in place.

**Ephemeral files cleanup:** `AGENT_SUGGESTIONS.md` and `sdlc-initialize` are now ephemeral upstream — used during initialization only, then deleted. During migration, remove stale copies:
```
rm -f .claude/agents/AGENT_SUGGESTIONS.md
rm -rf .claude/skills/sdlc-initialize/
```

**Project domain agents** (all other files in `.claude/agents/`): Apply the §4.2.0 preservation gate. The Knowledge Context and Communication Protocol sections of project agents contain MCP calls (injected during port/initialize) and MUST be preserved — do NOT blanket-rewrite them from the upstream template. The gate's section-level preservation handles this automatically. Preserve the agent name, domain description, scope ownership, anti-rationalization tables, and any project-added agents that do not exist in the upstream template set.

**Template upgrade (non-MCP changes):** The upstream template may introduce changes to non-MCP sections of `## Knowledge Context` or `## Communication Protocol` (e.g., `knowledge_feedback` was removed from the Knowledge Context section upstream). Apply those non-MCP changes only — do NOT re-inject file-path references into sections that already contain MCP calls.

If an upstream agent template was renamed: flag it. Do not silently overwrite a renamed agent.

#### Process docs

Apply the §4.2.0 preservation gate for every process doc. After the gate has produced the merged content, apply PROJECT-SECTION marker extraction/re-injection on top. Preserve files that were added by the project and have no upstream equivalent — identify these by checking `.sdlc-manifest.json` for the file origin.

**Never overwrite `process/agent-selection.yaml`** — this file contains the project's agent roster and dispatch rules with project-specific agent names. It becomes project-specific after initialization. If upstream added new entries (e.g., new infrastructure domains, new tier definitions), flag them for CD review rather than overwriting.

#### Templates

Apply the §4.2.0 preservation gate. Templates like `test_spec_template.md` contain `memory_search` references that guide test authors to retrieve knowledge — these MCP calls are the Neuroloom-transformed equivalents of cc-sdlc's file-based guidance and must be preserved.

#### `.sdlc-manifest.json`

Update the `sdlc_version` field and `source_version` to `LATEST_VERSION`. Set `source_version_sha` to the commit SHA of the release tag (via `gh api repos/Inpacchi/cc-sdlc/git/ref/tags/{LATEST_VERSION} --jq '.object.sha'`; store `"unknown"` if unavailable). Preserve all project-specific fields. Add missing fields introduced in newer cc-sdlc versions if absent:

- `sdlc_root` — set to the detected SDLC root path (`ops/sdlc/` or `.claude/sdlc/`)
- `neuroloom_backend` — set to `true` if absent (load-bearing: `/sdlc-port` uses this to detect prior Neuroloom initialization)
- `installed_bundles` — back-fill from the Bundle Awareness detection (empty array if no bundles detected)
- `last_applied_contract_id` — back-fill to `"0000"` if absent (covers projects installed before cc-sdlc 1.3.0)

**Any `manifest_field_added` entry in the §4.3 pending_changes set** contributes its `field` + `default` to this back-fill list.

**Advance `last_applied_contract_id`** to the newest entry's `id` in the fetched `skeleton/contract_changes.yaml`. Do this only after §4.3 (contract-driven renames), bundle handling, and any other pending-change consumers have completed successfully — if any failed, leave the old id so the next migration retries. If `contract_changes.yaml` is absent from upstream (pre-1.3.0 cc-sdlc), skip this advancement.

**Refresh `installed_files` hashes.** For every file the migration just wrote (overwrites + merges + drift resolutions), recompute SHA-256 of the final on-disk content and update the corresponding entry in `installed_files`. For drift cases where CD chose "keep mine", record the current hash so subsequent migrations see a clean baseline. For files CD chose to overwrite with upstream, the hash reflects the new upstream content. This keeps drift detection accurate for the next migration.

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

