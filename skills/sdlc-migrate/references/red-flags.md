# Red Flags

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
| "CD said 'apply' so I'll skip the preview options." | The preview gate (Stage 3.3.2) must be presented every time. CD may want to inspect content even on familiar migrations. Never jump straight to Apply without offering the preview options. |
| "There are only 2 updated entries — I don't need to show content." | The count doesn't determine whether preview is valuable. A single entry could contain a breaking change. Always offer the preview options regardless of count. |
| "I should re-seed agent-context-map.yaml into Neuroloom" | `agent-context-map.yaml` is a configuration file, not knowledge content. It maps agent roles to file paths — a pattern replaced by tags in Neuroloom. Ingesting it adds garbage to the knowledge layer. Exclude it from all knowledge layer operations. |
| "I'll just overwrite all skills without checking for markers." | PROJECT-SECTION markers protect project-specific content. Extract marked blocks before overwriting, then re-inject. Skipping this destroys intentional project customizations. |
| "I'll copy agent-selection.yaml with the other process files." | `agent-selection.yaml` is project-specific — it contains the project's agent roster, not the framework's. Never overwrite it. |
| "I'll rename all skill references to match upstream." | Guarded renames only — check that the target skill directory exists in `.claude/skills/` before renaming. Renaming to a nonexistent skill causes silent process failures. |
| "I'll rename agent names in skills to match upstream." | Projects use different agent names (`frontend-engineer` vs `frontend-developer`). Only rename if the target agent exists in `.claude/agents/`. |
| "The AGENT_TEMPLATE.md can be copied directly from upstream." | Neuroloom projects use `memory_search` in Knowledge Context, not file path references. Scan for MCP patterns before merging — preserve them. |
| "Core cc-sdlc skills have no project customizations, I can overwrite them." | FALSE for Neuroloom projects. `/sdlc-port` injects MCP calls into `sdlc-design-consult`, `sdlc-review-fix`, `sdlc-tests-create`, `sdlc-tests-run`, `research-external`, and others. Every file write in §4.2 must pass the §4.2.0 MCP preservation gate — no exceptions by category. |
| "Process docs are framework-only, direct-copy is fine." | Process docs like `discipline_capture.md`, `overview.md`, `incident_response.md` contain MCP call patterns after port/initialize. The §4.2.0 gate applies to them too. |
| "Templates are boilerplate, no MCP there." | FALSE. `test_spec_template.md` guides authors to retrieve knowledge via `memory_search` in Neuroloom projects. Apply §4.2.0. |
| "I'll just run the content-merge and trust the rules worked." | Always run the MCP Retention Audit (§4.2-gate). A silent regression that drops `memory_search` calls breaks knowledge retrieval in every subsequent session with no visible symptom until an agent fails to find what it needs. |
| "I'll ingest provenance_log.md into the knowledge layer." | The provenance log is a project-specific append-only record. It's not seed content — never ingest or overwrite it. |
| "CLAUDE-SDLC.md should be a separate file." | Since upstream refactored this, CLAUDE-SDLC.md content lives directly in the project's CLAUDE.md. Remove any standalone copy after verifying its content is in CLAUDE.md. |
