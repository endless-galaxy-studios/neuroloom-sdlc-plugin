# Manifest Schema and Field Explanations

**`.sdlc-manifest.json`:** Write to project root. Includes an `installed_files` map of hash-at-install for every operational-layer file written in Stage 5b. This enables `/sdlc-migrate` to detect post-install manual edits (drift) before overwriting.

```json
{
  "sdlc_version": "{SDLC_VERSION}",
  "sdlc_root": "{detected sdlc_root — typically ops/sdlc for new projects}",
  "neuroloom_backend": true,
  "source_repo": "https://github.com/Inpacchi/cc-sdlc",
  "source_version": "{SDLC_VERSION}",
  "source_version_sha": "{commit SHA of the release tag, for cross-compatibility with cc-sdlc git-based migrations}",
  "initialized_at": "{ISO_DATE}",
  "workspace_id": "{workspace_id}",
  "agent_count": {M},
  "installed_bundles": ["design"],
  "last_applied_contract_id": "{newest id in cc-sdlc contract_changes.yaml at install time}",
  "installed_files": {
    ".claude/skills/sdlc-plan/SKILL.md":       { "sha256": "{hash}", "size": {bytes}, "installed_at": "{ISO_DATE}" },
    ".claude/skills/sdlc-execute/SKILL.md":    { "sha256": "{hash}", "size": {bytes}, "installed_at": "{ISO_DATE}" },
    "{sdlc_root}/templates/agent-template.md":  { "sha256": "{hash}", "size": {bytes}, "installed_at": "{ISO_DATE}" },
    ".claude/sdlc/process/overview.md":        { "sha256": "{hash}", "size": {bytes}, "installed_at": "{ISO_DATE}" },
    "...every file written in Stage 5b...":    { ... }
  }
}
```

**`installed_bundles`:** Array of bundle names CD accepted during the 5b prompt. Empty array if none. Used by `/sdlc-migrate` to preserve opt-in skills and propagate bundle updates.

**`last_applied_contract_id`:** Newest id in cc-sdlc's `skeleton/contract_changes.yaml` at install time (fetched in Stage 2c). New projects start caught up — `/sdlc-migrate` will not re-apply historical renames and field additions intended for older projects. Parse the fetched `skeleton/contract_changes.yaml` and take the `id` of the last entry in `changes`. If the file is absent (upstream cc-sdlc predates 1.3.0), set this field to `"0000"`.

**Hash generation:** Use SHA-256 of the **post-transformation** content (after Neuroloom pattern mapping has been applied, since that's what actually lands on disk). Record via:

```bash
sha256sum "{path}" | awk '{print $1}'
# or in Python: hashlib.sha256(content.encode()).hexdigest()
```

**Scope of `installed_files`:**
- **Include:** All framework-origin files written during Stage 5b (skills, agents, process docs, templates, `.claude/CLAUDE.md` additions if applicable)
- **Exclude:** Project-generated files (`docs/_index.md`, `docs/current_work/specs/*`), user-owned files (`CLAUDE.md` project root — hashed content would drift on every user edit), hook files owned by the plugin itself (already controlled), `.sdlc-manifest.json` itself

**Project-owned files** (`process/agent-selection.yaml` after customization, any file CD edited during Stage 5b review gate) — do NOT hash these. They are expected to drift. The purpose of `installed_files` is to flag **unexpected** drift in files CD never intended to modify.

Note: `sdlc_root` should be set to the actual SDLC root path detected during initialization (typically `ops/sdlc/` for new projects). `neuroloom_backend` must be present for `sdlc-port` mode detection consistency.

**`.gitignore` entries:** Ensure the following are in the project's `.gitignore` — all are private session/diagnostic state, never git-tracked:
- `.claude/agent-memory/` — agent private scratchpads
- `.sdlc-transaction-log` — per-run JSONL transaction log
- `.sdlc-transformation-warnings.log` — per-run content-transformation warnings

**`hooks/` files:** Write the SessionStart hook entry to `.claude/hooks/` per the Neuroloom hooks convention. The hook checks the sentinel on session start and routes to the appropriate skill.
