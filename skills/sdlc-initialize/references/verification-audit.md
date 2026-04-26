## Stage 10 — Verification + Compliance Audit

### 10a. Verification Checklist

Run through all verification checks before declaring initialization complete:

**Knowledge layer:**
- [ ] Sentinel readable via `memory_search(query="SDLC workspace sentinel", tags=["sdlc:sentinel"])`
- [ ] Knowledge entries present in all wired domains
- [ ] No duplicate entries (check `summary.unchanged` was > 0 on re-init, not `summary.created`)
- [ ] Spec-relevant importance boosts applied
- [ ] Discipline entries tagged `sdlc:triage:ready-to-promote`

**Operational layer (filesystem):**
- [ ] `.claude/skills/` populated with cc-sdlc skills
- [ ] `.claude/agents/` populated with all approved agents
- [ ] `.claude/sdlc/process/` populated with process docs
- [ ] `.claude/sdlc/templates/` populated with document templates
- [ ] `CLAUDE.md` has `## SDLC Process` section
- [ ] `.sdlc-manifest.json` written with correct version + workspace_id
- [ ] `.gitignore` contains `.claude/agent-memory/`
- [ ] `hooks/` SessionStart hook entry written

**Agents:**
- [ ] Mandatory agents created: `software-architect`, `code-reviewer` (hard gate — init is incomplete without both)
- [ ] All agents created via `/sdlc-create-agent` — confirmed
    Created: [list all agents]
- [ ] Spec-vs-roster reconciliation complete — all spec-listed roles created or deviation logged
- [ ] Framework subagents present in `.claude/agents/`: sdlc-reviewer.md, sdlc-compliance-auditor.md

**Catalog:**
- [ ] D1 registered in `docs/_index.md`
- [ ] D1 spec exists at `docs/current_work/specs/d1_project_spec.md`

**Plugins:**
- [ ] context7: [installed / NOT INSTALLED]
- [ ] LSP: [installed / not applicable / NOT INSTALLED]

### 10b. Post-Operation Audit

**Run the shared post-operation audit** at `${CLAUDE_PLUGIN_ROOT}/references/post-operation-audit.md`. Execute the shared checks AND the `/sdlc-initialize`-specific subset.

The audit verifies the Neuroloom transformation landed correctly across all installed files — not just the 10a checklist items. Critical checks include:
- Every file flagged by the phrasing-contract runtime scan (see `sdlc-migrate` § "Detecting Files That Contain Phrasing-Contract Patterns") contains at least one MCP call
- No residual cc-sdlc standard phrases (they should have been transformed to `memory_search`/`memory_store`)
- No inline adapter conditionals (contract violations)
- Project agents created (initialization didn't skip the agent roster stage)
- Founding spec ingested and sentinel exists

**If the audit fails:** Halt. Do NOT proceed to §10c. Follow the audit's recovery instructions. For init failures: `rm -rf .claude/sdlc/ .claude/agents/`, coordinate sentinel removal with support, then re-run after the plugin's Pattern Mapping rules are updated.

### 10c. Compliance Audit

Dispatch the `sdlc-compliance-auditor` subagent to verify initialization integrity. Pass:
- The checklist above
- The `.sdlc-manifest.json` path
- The workspace_id
- The list of created agent names

The auditor checks for unmapped knowledge, missing agent wiring, and initialization gaps that compound as the project grows. Collect findings and triage. Fix any CRITICAL findings before declaring initialization complete.

This is distinct from the §10b post-operation audit: post-operation checks **Neuroloom integration correctness** (did the transformation apply?), while the compliance audit checks **framework conventions** (is the installed SDLC structurally sound?). Both must pass.

### 10d. Final Report

```
SDLC Initialization Complete — {N} entries seeded, {M} agents created, all gates passed

Seeded cc-sdlc {SDLC_VERSION} into workspace {workspace_id} with {K} skills and {N} knowledge entries ({C} customized for this stack, {R} removed as irrelevant). Compliance audit: {PASS/PARTIAL}.

  Initialized:              {ISO_DATE}
  Knowledge entries seeded: {N} ({C} customized, {R} removed as irrelevant)
  Agents created:           {M}
  Skills installed:         {K}
  Maturity level:           2 (knowledge + routing active)
  Compliance audit:         {PASS/PARTIAL} — {finding count} findings, {critical count} critical

Next step: Run /sdlc-plan to create the first real deliverable.
```

---
