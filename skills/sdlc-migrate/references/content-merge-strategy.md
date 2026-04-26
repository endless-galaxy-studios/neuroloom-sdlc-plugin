# Content-Merge Strategy Reference

This table governs Stage 4 decisions. Consult it when a file's category is ambiguous.

| File Category | Strategy | Rationale |
|---------------|----------|-----------|
| cc-sdlc core skills | §4.2.0 MCP gate + marker preservation | Port injects MCP calls into many core skills; must preserve |
| Plugin skills (initialize, migrate, port) | Always overwrite | Maintained in this plugin repo |
| Enhanced skills (archive, audit) | §4.2.0 MCP gate + merge | Contain Neuroloom-specific API sections |
| Agent files (framework: template, suggestions, reviewer, auditor) | §4.2.0 MCP gate | Preserve MCP patterns, update non-MCP sections |
| Agent files (project domain agents) | §4.2.0 MCP gate + non-MCP tailoring update | Framework sections update outside MCP; domain desc preserved |
| Agent files (project-added) | Skip | No upstream equivalent — never touch |
| Process docs (upstream originals) | §4.2.0 MCP gate + marker preservation | Many process docs have MCP calls; preserve before overwriting |
| `process/agent-selection.yaml` | **Never overwrite** | Project-specific agent roster and dispatch rules |
| Process docs (project-added) | Skip | No upstream equivalent |
| Knowledge YAMLs | Server-side upsert | `knowledge_id` matching handles new/updated/unchanged/deprecated |
| `knowledge/provenance_log.md` | **Never overwrite/ingest** | Project-specific append-only records |
| Discipline files | §4.2.0 MCP gate + preserve parking lots | Update framework sections, preserve project entries and MCP calls |
| `.sdlc-manifest.json` | Partial update | Update version + add missing fields (`sdlc_root`, `neuroloom_backend`, `installed_bundles`, `last_applied_contract_id`) |
| `hooks/` files | Always overwrite | Plugin-managed; no project customizations |
| `CLAUDE.md` SDLC section | Targeted update + guarded renames | Only stale references; preserve project additions |
| Standalone `CLAUDE-SDLC.md` | Delete | Legacy file; content merged into CLAUDE.md |
| Templates | §4.2.0 MCP gate | `test_spec_template.md` and others contain `memory_search` references |

**§4.2.0 MCP gate:** Before every file write, count `memory_search(` + `memory_store(` occurrences in the project's current version. If > 0, apply Neuroloom-preserving merge (Pattern Mapping + section-level preservation). See Stage 4.2.0 for full procedure. See §4.2-gate for the mandatory post-write MCP Retention Audit.

**Modified file rule:** If git diff shows the project has changed a file that would normally be overwritten, treat it as Modified and surface a review gate (Stage 4.2). Never silently overwrite a file with project customizations.

---

## Early-Exit Logic

The skill has two independent early-exit conditions. Both must be satisfied before reporting the workspace as fully up to date.

**Knowledge layer current, operational layer current:** Both versions match `LATEST_VERSION`. Output "SDLC is up to date." Stop.

**Knowledge layer current, operational layer stale:** Skip Stage 3 knowledge fetch and Stage 4.1 re-seed. Run Stage 4.2–4.4 only. Report as "Operational layer updated; knowledge layer was already current."

**Knowledge layer stale, operational layer current:** Run Stage 3 and Stage 4.1 only. Skip Stage 4.2 file updates. Report as "Knowledge layer updated; operational layer was already current."

**Neither layer version known:** `.sdlc-manifest.json` missing, sentinel missing. Cannot determine current state — abort and tell CD to run `/sdlc-initialize`.
