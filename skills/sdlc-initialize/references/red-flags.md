# Red Flags

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
| "The project only needs 2 agents" | `software-architect` and `code-reviewer` are mandatory — that's already 2. Add at least one implementer. The minimum viable set is 3+. |
| "We don't need a software-architect or code-reviewer for a small project" | Both are mandatory. The architect mediates debate, reviews plans, and seeds knowledge. The code-reviewer is unconditionally dispatched by every review skill. Without them, review and planning skills are broken. |
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
| "I should ingest agent-context-map.yaml into Neuroloom" | `agent-context-map.yaml` is a configuration file, not knowledge content. It maps agent roles to file paths — a pattern replaced by tags in Neuroloom. Ingesting it adds garbage to the knowledge layer and causes YAML parse errors. Exclude it. |
