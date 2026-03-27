---
name: sdlc-initialize
description: >
  Seeds cc-sdlc knowledge from upstream GitHub into a Neuroloom workspace. Analyzes the project
  stack, filters and customizes knowledge by applicability, presents a confirmation gate, then seeds
  all knowledge entries via batch ingestion and writes operational files (agents, skills, process docs).
  Triggers on "initialize sdlc", "bootstrap sdlc", "set up sdlc", "sdlc init",
  "initialize this project", "bootstrap this project", "set up the SDLC",
  "I want to use cc-sdlc", "integrate sdlc", "initialize sdlc in neuroloom",
  "seed sdlc knowledge", "set up neuroloom sdlc", "initialize the SDLC backend",
  "set up the sdlc backend".
  Do NOT use for updating an already-initialized workspace to a newer cc-sdlc version — use sdlc-migrate.
  Do NOT use for porting an existing local cc-sdlc installation — use sdlc-port.
---

# SDLC Initialize

Orchestrate the full initialization of the Neuroloom-backed SDLC in a project. This skill detects the project state, selects the right initialization mode, fetches the cc-sdlc framework from GitHub, seeds knowledge into the Neuroloom API, and writes operational files to the filesystem.

**This skill sets up the framework. It does NOT create deliverables beyond the founding spec.** After initialization, hand off to `sdlc-plan` or `sdlc-lite-plan` for the first piece of implementation work.

**Argument:** `$ARGUMENTS` (optional — project description for greenfield, or omit to auto-detect)

---

## Pre-Agent Reality

In greenfield mode, **no domain agents exist until Stage 6.** This means:

- Stages 1–5 are a direct conversation between CD and CC. There is no one to dispatch.
- The Manager Rule does not apply until agents exist. CC writes the spec, CLAUDE.md section, and catalog entries directly.
- The Manager Rule activates at Stage 6 and applies for the remainder of the skill and the full session.

This is the only SDLC skill where CC does domain work directly. The justification is structural: you cannot dispatch agents that haven't been created yet.

---

## Two-Layer Architecture

Every operation in this skill maps to exactly one layer:

| Layer | What Lives Here | How Updated |
|-------|----------------|-------------|
| **Knowledge layer (Neuroloom API)** | Knowledge YAMLs, discipline entries, deliverable docs | `document_ingest_batch` MCP tool with `knowledge_id` for upsert |
| **Operational layer (filesystem)** | Skills, agents, process docs, templates, CLAUDE.md, `.sdlc-manifest.json`, `hooks/` files | Direct file writes via Write/Edit tools |

Never mix layers. Knowledge that belongs in Neuroloom is not written to disk. Operational files that belong on disk are not ingested into Neuroloom.

---

## Mode Detection

Before starting any work, scan the project and determine which mode applies. Output the assessment:

```
INITIALIZATION ASSESSMENT
Project directory: [path]
Has existing code:                    [yes/no]
Has existing docs:                    [yes/no]
Has ops/sdlc/ on filesystem:          [yes/no]
Has .claude/skills/ on filesystem:    [yes/no]
Has .sdlc-manifest.json:              [yes/no]
Has spec in docs/current_work/specs/: [yes/no]
Has agents in .claude/agents/:        [yes/no]
Sentinel in Neuroloom API:            [yes/no — check via memory_search]
```

Check the sentinel via: `memory_search(query="SDLC workspace sentinel", tags=["sdlc:sentinel"])`

| State | Mode | Entry Point |
|-------|------|-------------|
| Sentinel exists AND `ops/sdlc/` populated AND agents exist | **Already initialized** | Report status, suggest `/sdlc-migrate` or `/sdlc-status` |
| No code, no docs (or only boilerplate), no spec, no sentinel | **Greenfield — fresh** | Stage 1 (ideation + spec) |
| Spec exists in `docs/current_work/specs/`, sentinel absent | **Greenfield — resume** | Stage 3 (skip ideation, begin fetch) |
| Sentinel exists, `ops/sdlc/` present, no agents | **Greenfield — resume (post-skeleton)** | Stage 6 (agent roster) |
| Has code and/or docs, no sentinel, no `ops/sdlc/` | **Retrofit** | Stop — redirect to `/sdlc-port` |
| `.sdlc-manifest.json` exists but sentinel absent | **Repair** | Stage 1 (re-run full init) |
| Sentinel exists but user explicitly requests re-initialization | **Re-initialize** | Stage 1 with destructive-action warning gate |

**Retrofit redirect:** If the project has existing code and documentation but no SDLC infrastructure, do not proceed with this skill. Output:

```
This project has existing code and documentation. Use /sdlc-port instead, which
performs discovery analysis before seeding knowledge rather than treating the
project as greenfield. /sdlc-initialize is for new projects only.
```

**Re-initialize warning:** If the user requests re-initialization of an already-initialized workspace, present a destructive-action gate via `AskUserQuestion` before proceeding:

```
Re-initializing will overwrite importance scores and accumulated feedback stored
in Neuroloom since the last initialization. Knowledge entries will be re-seeded
at their base importance values and any project-specific adjustments will be lost.
```

Options: 1. Proceed with re-initialization (destructive), 2. Cancel — use /sdlc-migrate to update version instead.

---

## Stage 1 — Ideation + Spec Drafting

*Applies to: Greenfield — fresh only. Skip to Stage 3 for resume modes.*

### 1a. If a spec already exists

Read it. Verify it establishes at minimum:
- Problem statement — what you're building and why
- Technology stack — languages, frameworks, databases, infrastructure
- Repository structure — monorepo packages or directory layout

If all three are present, summarize and ask CD: "This spec covers the foundations. Ready to proceed with SDLC scaffolding, or do you want to refine it first?"

If critical sections are missing, note what's missing and ask CD whether to flesh it out now or proceed as-is.

Skip to Stage 1b (Spec Drafting).

### 1a-alt. If no spec exists — Ideation

If `$ARGUMENTS` contains a project description, use it as the ideation seed. Otherwise, prompt CD:

> This is a greenfield project. Before I set up the SDLC framework, we need to define what we're building. Tell me about your project — what problem are you solving, who is it for, and what's your initial vision?

Then enter the ideation loop:

**Ground in what you can observe.** Before asking follow-up questions, check:
- Does the repo have any files that hint at direction (package.json, requirements.txt, Cargo.toml)?
- Is there a README with any project description?
- Are there any prior art references in the repo?

**Ask one question at a time.** Do not batch questions. Let each answer inform the next. Use `AskUserQuestion` for every question — no conversational text questions.

**Question priorities for initialization** (these establish what the spec needs):

| Priority | Question Area | Why It Matters |
|----------|--------------|----------------|
| 1 | **Problem + audience** | What are we building and who is it for? |
| 2 | **Technology stack** | Languages, frameworks, databases — determines agents and knowledge |
| 3 | **Repository structure** | Monorepo vs single package, directory layout — determines agent scope |
| 4 | **Deployment target** | Where it runs — determines infrastructure agents and knowledge |
| 5 | **Data model** (if applicable) | Key entities — determines data-modeling knowledge |
| 6 | **Business model** (if applicable) | Monetization, auth model — determines business-analysis discipline |
| 7 | **Non-functional requirements** | Performance bar, security model, compliance needs |

**You do NOT need to ask all of these.** CD may cover several in their initial description. Ask only what's missing. If CD gives a comprehensive description, you may only need 1–2 follow-up questions.

**When CD describes a problem without a solution:** Help them think through the solution space. Sketch 2–3 high-level approaches (not implementations — directional shapes) and let CD pick. This is exploratory, not prescriptive.

**When CD knows exactly what they want:** Don't over-question. If the problem, stack, and structure are clear, move to spec drafting.

**There is no minimum question count.** The goal is a spec with enough content to create agents and seed knowledge. Some projects need 10 minutes of conversation; others need an hour.

### 1b. Spec Drafting

When enough is understood, draft a D1 spec. CC writes this directly (no agents exist yet — this is the one exception to the Manager Rule).

Use the spec template at `.claude/sdlc/templates/spec_template.md` as the structural guide. For initialization, the spec must cover at minimum:

```markdown
# D1: [Project Name] — Spec

**Deliverable:** D1
**Name:** [Project Name]
**Status:** Draft
**Date:** [today]

---

## Problem Statement
[What this project solves and why it matters — from ideation conversation]

## Technology Stack
[Languages, frameworks, databases, infrastructure — specific versions where known]

## Repository Structure
[Directory layout with purpose annotations]

## Requirements
### Functional Requirements
[Key features — numbered FR-1, FR-2, etc.]

### Non-Functional Requirements
[Performance, deployment, security — numbered NFR-1, NFR-2, etc.]

## Data Model (if applicable)
[Key entities and relationships]

## Dependencies
[External services, libraries, infrastructure]

## Success Criteria
[What "done" looks like for D1]

## Open Questions
[Unknowns to resolve during planning]
```

**The spec does not need to be exhaustive.** It needs to be sufficient to:
1. Create domain agents with meaningful stack-specific system prompts
2. Seed knowledge stores with relevant technology patterns
3. Seed disciplines with project context
4. Write a CLAUDE.md with accurate project instructions

More detail is better, but don't block on completeness. Open questions are expected.

#### 1b-gate. CD Approves the Spec

Present the full spec to CD. Use `AskUserQuestion`:

> Here's the D1 spec. Review it and let me know:
> 1. Approved as-is — proceed to scaffolding
> 2. Changes needed — tell me what to adjust
> 3. Need more exploration — let's keep ideating

If CD requests changes, make them directly (no agents to dispatch) and re-present.

**Gate:** CD must approve (option 1) before Stage 2.

### 1c. Catalog Registration

Register D1 in the deliverable catalog. Write or update `docs/_index.md`:

```
## D1 — Project Foundation Spec
Status: In Progress
Spec: docs/current_work/specs/d1_project_spec.md
```

---

## Stage 2 — Upstream Fetch

*Applies to: All modes (Greenfield fresh + resume, Re-initialize).*

### 2a. Resolve Version

Call `sdlc_get_version` to retrieve the latest cc-sdlc release tag. Store as `SDLC_VERSION`. This version tag is embedded in all seeded knowledge entries as `sdlc:seed-version:{SDLC_VERSION}`.

If `sdlc_get_version` fails:
- Auth error → "Neuroloom API key not configured. Add your API key to the Neuroloom config."
- Network error → "Cannot reach Neuroloom API. Check your api_url configuration."
- Do not proceed if either failure occurs.

### 2b. Fetch Repository Tree

Fetch the full file listing from the cc-sdlc GitHub repo:

```
GET https://api.github.com/repos/Inpacchi/cc-sdlc/git/trees/{SDLC_VERSION}?recursive=1
```

Or use the GitHub CLI: `gh api repos/Inpacchi/cc-sdlc/git/trees/{SDLC_VERSION}?recursive=1`

If the GitHub API returns a rate limit error (403 with `X-RateLimit-Remaining: 0`), stop and report:

```
GitHub API rate limit hit during file tree fetch. Wait until {X-RateLimit-Reset}
and retry, or authenticate with a GitHub token via: gh auth login
```

### 2c. Download Content Categories

Download all files under these paths. Handle each category's content format:

| Category | Path | Format | Target Layer |
|----------|------|--------|-------------|
| Knowledge stores | `ops/sdlc/knowledge/` | YAML | Knowledge (Neuroloom API) |
| Discipline parking lots | `ops/sdlc/disciplines/` | Markdown | Knowledge (Neuroloom API) |
| Skills | `.claude/skills/` | Markdown | Operational (filesystem) |
| Agent templates | `.claude/agents/` | Markdown | Operational (filesystem) |
| Process docs | `ops/sdlc/process/` | Markdown | Operational (filesystem) |
| Templates | `ops/sdlc/templates/` | Markdown | Operational (filesystem) |

Fetch each file via:
```
gh api repos/Inpacchi/cc-sdlc/contents/{path} --jq '.content' | base64 -d
```
Or raw URL: `https://raw.githubusercontent.com/Inpacchi/cc-sdlc/{SDLC_VERSION}/{path}`

Track download status. If any individual file fetch fails, log it and continue. After all downloads, report the count of successfully fetched vs. failed files. If more than 20% of files fail, stop and ask CD whether to proceed with partial content.

---

## Stage 3 — Project Analysis + Knowledge Filtering

*Applies to: All modes.*

### 3a. Project Profile

Scan the current project to build a profile. Read (if they exist):
- `CLAUDE.md` — conventions, tech stack description
- `package.json` or `pyproject.toml` — languages and dependencies
- Top-level directory structure — presence of `api/`, `web/`, `mcp/`, `docs/`, etc.

Build a project profile:

```
PROJECT PROFILE
Languages:      [e.g., Python, TypeScript]
Frameworks:     [e.g., FastAPI, React]
Package mgr:    [e.g., uv, pnpm]
Test runner:    [e.g., pytest, vitest]
Build tooling:  [e.g., Docker, Vite]
Project type:   [e.g., monorepo, service, library]
Domains:        [which SDLC domains apply: architecture, coding, data-modeling, design, product-research, testing]
```

### 3b. Knowledge Applicability Evaluation

For each YAML knowledge store fetched in Stage 2, evaluate its `project_applicability.relevant_when` field against the project profile.

Apply the file's `action_if_irrelevant` directive:
- `keep` — seed regardless of stack match
- `customize` — rewrite content for the project's actual stack before seeding
- `remove` — skip this file entirely

For `customize` entries: rewrite content to be accurate for the project's detected stack while preserving structural intent. Example: TypeScript-specific patterns become Python patterns in a Python-only project.

For agent templates: rename to project-appropriate names, update descriptions with the project's stack. An agent named `typescript-specialist` becomes irrelevant in a Python-only project and should be flagged for removal or renaming.

**Check for existing knowledge before seeding.** For each domain in the project profile, run:
```
memory_search(query="SDLC knowledge entries", tags=["sdlc:knowledge", "sdlc:domain:{domain}"])
```

If results exist, this is a re-initialization. Flag entries that would overwrite project-specific content accumulated since last init (tagged `sdlc:project-specific`). Do not overwrite those entries — present them to CD in the confirmation gate.

Track counts:
- N entries: kept as-is
- C entries: customized for project stack
- R entries: removed as irrelevant
- M agents: to be created
- D disciplines: to be seeded
- P project-specific entries: would be overwritten (re-initialize only)

---

## Stage 4 — Confirmation Gate

Present a summary and wait for user confirmation before any writes occur.

```
cc-sdlc initialization ready.

  cc-sdlc version:           {SDLC_VERSION}
  Knowledge entries:         {N} kept, {C} customized, {R} removed
  Agents to create:          {M}
  Discipline domains:        {D}
  Skills to write:           {K}
  Process docs + templates:  {P}
  [Re-init only] Project-specific entries preserved: {PP}

Knowledge will be seeded into: Neuroloom API (workspace: {workspace_id})
Operational files written to:  filesystem (current project directory)

Proceed? (this will write files and seed Neuroloom)
```

Use `AskUserQuestion` with options:
1. Proceed with initialization
2. Adjust — show me the filtered knowledge list before proceeding
3. Cancel

If CD selects "Adjust", output the full filtered knowledge list grouped by domain and wait for confirmation again before proceeding.

Do not proceed to Stage 5 unless CD explicitly confirms.

---

## Stage 5 — Seed Knowledge + Write Operational Files

*This is the main execution stage. Complete knowledge seeding before writing operational files.*

### 5a. Batch-Ingest Knowledge into Neuroloom

Call `document_ingest_batch` with the filtered and customized knowledge entries. Batch in groups of up to 50 documents per call.

Each document must include:

| Field | Value |
|-------|-------|
| `title` | Entry name or filename |
| `content` | Entry content (YAML text or extracted entry body) |
| `source_type` | `"sdlc_knowledge"` |
| `format` | `"yaml"` for knowledge stores, `"markdown"` for discipline files |
| `version` | `{SDLC_VERSION}` |
| `knowledge_id` | YAML `id` field for gotchas/rules; `{filename}:{section_key}` for entries/methodology |
| `tags` | See tag schema below |
| `importance` | From the YAML entry's `importance` field, or `0.7` if absent |

**Tag construction per entry:**

```
sdlc:knowledge                          # Always present
sdlc:seed                               # Always present (marks as seed entry)
sdlc:seed-version:{SDLC_VERSION}        # Always present
sdlc:pattern:{pattern}                  # From YAML: entries | gotchas | rules | methodology
sdlc:domain:{domain}                    # From YAML domain field
sdlc:type:{type}                        # From YAML type field if present
```

**`knowledge_id` is mandatory on every call.** Omitting it breaks idempotent upsert on re-initialization and creates duplicate entries. If a YAML entry has no `id` field, derive one as `{filename}:{entry_index}`.

**Do NOT manually include `sdlc:knowledge-id:{id}` in tags.** Pass `knowledge_id` as a parameter. The server creates the `sdlc:knowledge-id:{id}` tag automatically.

**Sentinel note:** The sentinel memory is managed server-side by `seed()`. Do NOT create or update the sentinel via `document_ingest`. After seeding completes, the sentinel already exists — read it via `memory_search(query="SDLC workspace sentinel", tags=["sdlc:sentinel"])` if you need to verify it.

**Batch response handling:** Each batch call returns:
```json
{
  "summary": {"total": N, "created": C, "updated": U, "unchanged": X, "errors": E},
  "results": [{"index": i, "title": "...", "status": "created|updated|unchanged|error", "error": "..."}]
}
```

If `summary.errors > 0`, iterate `results` where `status == "error"` and log each failure with its title and error message. After all batches complete, report total errors. If more than 10% of entries errored, stop and ask CD whether to continue writing operational files or abort.

### 5b. Write Operational Files to Filesystem

Write all non-knowledge framework files. These go to the filesystem — not into Neuroloom.

| Content | Destination |
|---------|-------------|
| Skills | `.claude/skills/` |
| Agent templates | `.claude/agents/` (customized names from Stage 3) |
| Process docs | `.claude/sdlc/process/` |
| Templates | `.claude/sdlc/templates/` |

**Plugin skill exclusion:** Do NOT write `sdlc-initialize` or `sdlc-migrate` to `.claude/skills/`. These skills are owned by the Neuroloom SDLC plugin (`neuroloom-sdlc-plugin/skills/`) and must not have cc-sdlc originals competing for skill resolution. If cc-sdlc originals already exist in `.claude/skills/`, delete them:

```
rm -rf .claude/skills/sdlc-initialize/ .claude/skills/sdlc-migrate/
```

**CLAUDE.md update:**

**If CLAUDE.md already exists:** Read it. Preserve all existing content. Add the SDLC process section if not present.

**If CLAUDE.md does not exist:** Author it from scratch.

**Required sections for CLAUDE.md:**

1. **Project header** — name, one-paragraph description
2. **Repository layout** — directory tree with purpose annotations (from spec)
3. **Technology stack** — per-package if monorepo (from spec)
4. **Coding standards** — per-language conventions
   - If multi-language: document the boundary conventions (e.g., snake_case API, camelCase frontend)
5. **SDLC process section** — read `ops/sdlc/CLAUDE-SDLC.md` (from the fetched cc-sdlc source) and adapt the full content for this project. Use heading `## SDLC Process`. Do not create a separate `CLAUDE-SDLC.md`.
6. **Verification policy** — zero-assumption rule, Context7 for external libs, read code before asserting
7. **Agent dispatch conventions** — agent-first, never self-implement, manager rule

**Gate:** Present the drafted CLAUDE.md to CD. Use `AskUserQuestion`: "CLAUDE.md is ready for review. Any changes before I save it?"

**`.sdlc-manifest.json`:** Write to project root:
```json
{
  "sdlc_version": "{SDLC_VERSION}",
  "initialized_at": "{ISO_DATE}",
  "workspace_id": "{workspace_id}",
  "agent_count": {M}
}
```

**`.gitignore` entry:** Ensure `.claude/agent-memory/` is in the project's `.gitignore`. Agent memories are private scratchpads — never git-tracked.

**`hooks/` files:** Write the SessionStart hook entry to `.claude/hooks/` per the Neuroloom hooks convention. The hook checks the sentinel on session start and routes to the appropriate skill.

### 5c. Report Stage 5 Completion

```
Stage 5 complete.

  Knowledge seeded:     {total} entries ({created} created, {updated} updated, {unchanged} unchanged)
  Errors:               {E}
  Skills written:       {K}
  Process docs:         {P}
  Templates:            {T}
  CLAUDE.md:            updated (## SDLC Process section appended)
  .sdlc-manifest.json:  written
  .gitignore:           .claude/agent-memory/ confirmed
```

---

## Stage 6 — Agent Roster Proposal + Creation

*The Manager Rule activates at this stage and applies for the remainder of the skill.*

### 6a. Propose Agent Roster

Based on the project profile from Stage 3, propose an initial agent roster. Consider the detected domains and project type. Every project needs at minimum:

- **backend-engineer** (or equivalent domain engineer for the primary language/framework)
- **code-reviewer** (language-aware review agent)
- **sdet** (test strategy and test writing)

Monorepos and full-stack projects typically also benefit from:
- **frontend-engineer**
- **architect** (for cross-cutting concerns)

Present the proposed roster with a one-line description of each agent's role:

```
Proposed agent roster ({M} agents):

  backend-engineer   — FastAPI + SQLAlchemy + pgvector expert; writes routers, models, migrations
  frontend-engineer  — React 19 + TypeScript + TanStack Query expert; writes components and hooks
  code-reviewer      — cross-domain reviewer; checks for correctness, conventions, and DX
  sdet               — test strategy and pytest/vitest authoring; owns test coverage
  architect          — cross-cutting design decisions; owns schema, API surface, integration points

Does this roster fit the project? Add, remove, or rename agents before proceeding.
```

Use `AskUserQuestion` with options:
1. Approve roster as proposed
2. Modify roster (describe changes in free text)
3. Cancel agent creation — I'll create agents manually later

### 6b. Create Agents

**MANDATORY: Invoke `/sdlc-create-agent` for each agent.** Do NOT write agent files directly. The skill handles:
- Frontmatter validation (name format, description with `<example>` blocks)
- System prompt scaffolding (Knowledge Context, Communication Protocol, Anti-Rationalization Table)
- Template compliance (AGENT_TEMPLATE.md structure)

**Creation order:**
1. Roles dispatched most often first (usually backend + frontend + code-reviewer)
2. Specialized roles (db-engineer, security, performance)
3. Cross-cutting roles (architect, sdet)

**Framework agents (pre-installed — do NOT create as domain agents):**
- `sdlc-reviewer` — reviews skill/agent files against cc-sdlc conventions (dispatched by `sdlc-create-skill`, `sdlc-create-agent`, `sdlc-review`)
- `sdlc-compliance-auditor` — performs 9-dimension compliance scan (dispatched by `sdlc-audit`)

**Pass stack context to the agent creation skill.** Each agent's system prompt must reference the project's actual technologies, not generic placeholders. Include in the creation prompt:
- Which packages/directories the agent owns
- Which frameworks/libraries the agent should know
- Key file paths and conventions from the spec

For each `/sdlc-create-agent` dispatch, include:
- Agent name
- One-line description
- Domain tags (from the tag schema: `sdlc:domain:{domain}`)
- Project-specific context (stack, conventions from CLAUDE.md)

After each agent is created, report to CD: "Created [agent-name] — [domain coverage]." After all agents are created, list the full roster.

### 6b-gate. Spec-vs-Roster Reconciliation

Before moving to Stage 6c, compare the created agent roster against any agent roles mentioned in the spec (e.g., FR requirements that reference "domain agents" or list specific roles). If the spec lists agents that were not created, or agents were created that the spec doesn't mention:

```
ROSTER RECONCILIATION
Spec-listed roles:    [list from spec FRs/NFRs]
Created agents:       [list from .claude/agents/]
Match:                [yes / deviations listed below]
Deviations:
  - [role] — [not created / created but not in spec] — [reason]
```

Present deviations to CD. This prevents gaps where spec-listed agents are silently dropped without a deviation record.

Report:
```
Stage 6 complete. {M} agents created.
  [list agent names]

Manager Rule is now active. All domain work from this point dispatches to agents.
```

### 6c. Wire Domain Tags in Neuroloom

For each created agent, update its domain knowledge entries to include the agent's routing tag. Run:
```
memory_search(query="SDLC knowledge entries", tags=["sdlc:domain:{domain}"])
```

This confirms the agent can find its relevant knowledge. No writes are needed — the tags were applied during Stage 5a seeding.

---

## Stage 7 — Knowledge `spec_relevant` Tagging

CD selects which knowledge stores inform spec writing. These entries get a boosted importance so the spec-writing agent surfaces them first.

Present the seeded knowledge domains to CD:

```
Which knowledge stores should inform spec and plan writing for this project?
Select all that apply.

  [1] architecture   — system design patterns, integration approaches
  [2] coding         — language-specific conventions, error patterns
  [3] data-modeling  — schema design, pgvector, migration patterns
  [4] design         — UI/UX patterns, component conventions
  [5] testing        — test strategy, coverage patterns, anti-patterns
  [6] product-research — user research, market analysis patterns
```

Use `AskUserQuestion` with a multi-select option list.

For each selected domain, call `document_ingest_batch` to update the `importance` of matching entries. Use `knowledge_id` to target specific entries. Boost importance to `0.9` for selected domains, leave unselected at their seeded value.

Report:
```
Stage 7 complete. Spec-relevant tagging applied to {N} entries across {D} domains.
```

---

## Stage 8 — Discipline Seeding + Testing Knowledge

### 8a. Seed Discipline Parking Lots

For each domain in the project profile, seed an initial discipline parking lot entry. Discipline entries are observations, patterns, or learnings — not prescriptive rules. Start with the fetched discipline files from Stage 2, customized for the project stack.

Dispatch the `software-architect` agent (or nearest equivalent) to produce the seed content for all 9 disciplines in one pass, given the spec as input. The agent returns the seed content; the orchestrator ingests it per discipline.

| Discipline | Seed Focus |
|-----------|-----------|
| architecture | Repo layout, service boundaries, API-first vs monolith |
| coding | Per-language conventions, cross-language boundaries |
| testing | Test suites per package, isolation challenges, mocking stance |
| design | Theme direction, component library, brand constraints |
| data-modeling | ORM/query patterns, migration safety, special column types |
| deployment | Target platform, service topology, local dev stack |
| business-analysis | Revenue model, multi-tenancy, auth strategy |
| product-research | Market context, competitive landscape, ecosystem position |
| process-improvement | Note: "First project from cc-sdlc — capture friction for upstream" |

Call `document_ingest_batch` with each discipline entry:

| Field | Value |
|-------|-------|
| `title` | e.g., "Backend coding discipline entry — FastAPI routing conventions" |
| `content` | Discipline observation text |
| `source_type` | `"sdlc_knowledge"` |
| `format` | `"markdown"` |
| `knowledge_id` | `"discipline:{domain}:{slug}"` |
| `tags` | `["sdlc:discipline:{domain}", "sdlc:knowledge", "sdlc:seed", "sdlc:triage:ready-to-promote"]` |
| `importance` | `0.6` (discipline entries start lower; they grow through promotion) |

Starting with a few bullets per domain costs 2 minutes. Discovering the gap mid-execution costs a full review round.

### 8b. Dispatch SDET for Test Knowledge

Dispatch the `sdet` agent to contribute test-specific gotchas for the project's test runner and framework. Pass:
- Project profile (languages, test runner, frameworks)
- Instruction to search existing knowledge first: `memory_search(query="test gotchas {framework}", tags=["sdlc:domain:testing"])`
- Instruction to ingest new gotchas via `document_ingest_batch` with `sdlc:domain:testing` tag and `knowledge_id` for each

Wait for the SDET agent to complete before proceeding to Stage 8c.

### 8c. Verify Plugin Readiness

Check whether required plugins are installed:

**context7 (required):**
```bash
grep -r "context7" ~/.claude/settings.json ~/.claude/settings.local.json .claude/settings.json .claude/settings.local.json 2>/dev/null
```

If not found, tell CD:
> context7 is required for library verification. See `.claude/sdlc/plugins/context7-setup.md` for installation.

**LSP (highly recommended):**
Check for language-appropriate LSP plugin based on the spec's technology stack. LSP enables type-aware navigation (`hover`, `goToDefinition`, `findReferences`) that agents rely on for accurate code understanding.

---

## Stage 9 — Maturity Assessment

Assess and report the SDLC maturity level achieved by this initialization:

| Level | Criteria | Meaning |
|-------|----------|---------|
| Level 1 | Discipline parking lots seeded, no structured knowledge routing | Entries exist but agents can't self-route to them |
| Level 2 | Knowledge seeded + agent domain tags wired | Agents can search their domain knowledge; full routing active |
| Level 3 | Knowledge refined through real sessions | Achieved through use, not initialization |

A fresh initialization achieves Level 2 (knowledge seeded + agent routing active). Present the maturity tracker:

```
SDLC MATURITY TRACKER

Level 2 achieved — Knowledge layer active + agent routing wired.

  [x] Sentinel present (managed server-side)
  [x] Knowledge seeded ({N} entries across {D} domains)
  [x] Agent roster created ({M} agents)
  [x] Domain tags wired (agents can self-route to knowledge)
  [x] Discipline parking lots seeded ({D} domains)
  [x] Spec-relevant entries boosted ({N} entries)
  [ ] Level 3 — Requires real sessions and knowledge refinement

Next step: Run /sdlc-plan to create the first deliverable.
```

---

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

### 10b. Compliance Audit

Dispatch the `sdlc-compliance-auditor` subagent to verify initialization integrity. Pass:
- The checklist above
- The `.sdlc-manifest.json` path
- The workspace_id
- The list of created agent names

The auditor checks for unmapped knowledge, missing agent wiring, and initialization gaps that compound as the project grows. Collect findings and triage. Fix any CRITICAL findings before declaring initialization complete.

### 10c. Final Report

```
SDLC INITIALIZATION COMPLETE

  cc-sdlc version:          {SDLC_VERSION}
  Workspace:                {workspace_id}
  Initialized:              {ISO_DATE}

  Knowledge entries seeded: {N} ({C} customized, {R} removed as irrelevant)
  Agents created:           {M}
  Skills installed:         {K}
  Maturity level:           2 (knowledge + routing active)

Compliance audit: {PASS/PARTIAL} — {finding count} findings, {critical count} critical

Next step: Run /sdlc-plan to create the first real deliverable.
```

---

## Progress Reporting Between Stages

After each stage completes, output a one-line status before beginning the next:

```
[Stage N complete] → Starting Stage N+1: {stage name}
```

If a stage gate requires user input, output the gate prompt and wait. Do not output "Starting Stage N+1" until the gate is cleared.

---

## Red Flags

| Thought | Reality |
|---------|---------|
| "I'll skip the confirmation gate for speed" | The gate prevents seeding wrong-stack knowledge into Neuroloom. Irrelevant knowledge adds search noise permanently. Always confirm. |
| "The first MCP call passed so everything is fine" | GitHub rate limits can fail mid-fetch independently of the Neuroloom API. Handle partial downloads explicitly. |
| "Re-initializing is safe" | Re-initialize overwrites importance scores and feedback accumulated since last init. Warn the user explicitly and require confirmation. |
| "All knowledge stores should be seeded" | Irrelevant stores add noise to every `memory_search`. The filtering step in Stage 3 exists for a reason — don't skip it. |
| "I can create the sentinel directly with document_ingest" | Sentinel lifecycle is owned by `seed()` server-side. Skills only READ the sentinel, never write it. Writing it would break version tracking in `/sdlc-migrate`. |
| "I'll write agent files directly — the /sdlc-create-agent skill is slow" | `/sdlc-create-agent` validates frontmatter, enforces description conventions, and checks template compliance. Hand-written agents skip these gates and cause downstream errors. |
| "I should dispatch an agent for the spec" | No agents exist in greenfield until Stage 6. CC writes the spec directly. This is the one exception to the Manager Rule. |
| "Disciplines can be seeded later" | A few bullets now costs 2 minutes. Discovering the gap mid-execution costs a full review round and a re-init of that domain. |
| "The project only needs 2 agents" | Even small projects benefit from code-reviewer + sdet separation. The minimum viable set is 3. Fewer agents means broader, less-focused prompts. |
| "I'll skip the compliance audit — it's a fresh project" | The audit catches initialization gaps (unmapped knowledge, missing agent wiring, incomplete hooks) that compound as the project grows. Run it every time. |
| "I can batch all 50 documents in one call regardless of content" | Batch size limit is 50 documents per call, but very large documents (full YAML files) may still hit payload limits. Split oversized payloads. |
| "knowledge_id is optional — I'll add it later" | Omitting `knowledge_id` on any `document_ingest_batch` call breaks idempotent upsert. Every subsequent re-initialization creates duplicate entries. Always include it. |
| "I'll skip ideation and go straight to scaffolding" | Agents and knowledge seeded without stack context are generic and unhelpful. Define the project first. |
| "The user described the project, I have enough to create agents" | You have enough to create agents when you have an approved spec with tech stack and repo structure. Not before. |
| "The context map ships with reasonable defaults" | The defaults use generic role names. If they don't match your agent filenames, self-discovery is broken. |
| "Context7 is optional for now" | Without it, agents will hallucinate library APIs from training data. Install it before any agent work begins. |
| "I'll overwrite their existing CLAUDE.md with a fresh one" | In retrofit mode (or any project with an existing CLAUDE.md), ALWAYS augment. Existing project instructions are authoritative. |
| "I'll seed knowledge from training data" | Verify all library/framework claims via Context7 before writing knowledge files. Training data goes stale. |
| "Manager Rule applies from the start" | In greenfield Stages 1–5, no agents exist. CC works directly. Manager Rule activates at Stage 6. |
| "I'll batch all the ideation questions" | One question at a time via AskUserQuestion. Batched questions get shallow answers. |

---

## Integration

**Feeds in from:**
- `sdlc_get_version` MCP tool — resolves the upstream cc-sdlc version to fetch
- GitHub API — provides skill, agent, process doc, and knowledge YAML content
- Project filesystem — `CLAUDE.md`, `package.json`, `pyproject.toml` inform the project profile
- CD (human) — ideation input, spec approval, roster approval, knowledge selection

**Feeds out to:**
- `sdlc-plan` / `sdlc-lite-plan` — first deliverable work after initialization completes
- `/sdlc-create-agent` — creates each approved agent from the Stage 6 roster
- `sdlc-compliance-auditor` — verifies initialization integrity in Stage 10
- `sdlc-migrate` — the upgrade path when a newer cc-sdlc version is released

**Downstream dependencies:**
- All SDLC skills assume the sentinel is present. If it is absent, `SessionStart` hook routes back to this skill.
- All domain agents assume their domain knowledge is seeded in Neuroloom. Knowledge seeded in Stage 5a is the foundation for all `memory_search` calls agents make during sessions.
- The `hooks/` SessionStart entry written in Stage 5b is the entry point for all future sessions. If it is missing or malformed, agents start cold without knowledge context.

---

## Error Handling

| Failure Mode | Detection | Response |
|-------------|-----------|---------|
| Neuroloom API unreachable | `sdlc_get_version` fails with network error | Output actionable config error. Do not proceed. |
| Neuroloom auth invalid | `sdlc_get_version` fails with 401 | Output API key setup instructions. Do not proceed. |
| GitHub rate limit hit | 403 + `X-RateLimit-Remaining: 0` | Stop, report reset time, suggest `gh auth login`. |
| Individual file fetch fails | Non-200 from file content endpoint | Log failure, continue. Report count at Stage 2 completion. |
| >20% files failed to download | Count check at Stage 2 completion | Stop, ask CD whether to proceed with partial content. |
| `document_ingest_batch` partial error | `summary.errors > 0` | Log each errored entry. Continue if <10% failed. |
| >10% batch entries errored | Count check after all batches | Stop, ask CD whether to continue with operational file writes. |
| Sentinel not present after seeding | `memory_search` returns empty | Report to CD. Sentinel is server-managed — do not create it manually. Ask CD to check Neuroloom workspace config. |
| Agent creation fails in Stage 6 | `/sdlc-create-agent` returns error | Report failure, offer to retry or skip that agent. Do not hand-write the agent file. |
| Compliance audit finds CRITICAL | Stage 10b auditor returns CRITICAL findings | Fix before declaring complete. Do not output final success report until all CRITICALs resolved. |
