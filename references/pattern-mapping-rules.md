### Pattern Mapping

> **How coverage actually works:** This table lists 5 explicit phrase-to-call mappings, but they cover only a fraction of real-world transformation sites. The vast majority of cc-sdlc files with knowledge references (skills, agents, process docs) are handled via the **section-level preservation rule** documented in "Content-Merge Rules for Neuroloom" below — scan each file for `memory_search(` / `memory_store(` presence and preserve those sections verbatim during merge. The explicit patterns below are what the transformer SEEKS during fresh installation (`/sdlc-initialize`) and during migration when a file has no prior MCP patterns. Once a file contains MCP calls, section-level preservation takes over.

**Match rules:**
1. **Case-insensitive on the leading verb, regardless of sentence position.** A rule `Read [sdlc-root]/disciplines/*.md and find [X]` matches both sentence-start `Read [sdlc-root]/disciplines/*.md and find...` and mid-sentence `..., read [sdlc-root]/disciplines/*.md and find...`. The verb (`Read`/`Consult`/`Append`/`Update`/`Look up`/etc.) is the anchor, not the sentence start. When substituting, preserve the original case of the verb only if the substitution keeps a verb at that position; otherwise the replacement's casing wins.
2. Patterns must match as a full phrase within a sentence.
3. **Inline backticks around paths are markdown formatting — match THROUGH them.** A rule `Append to [sdlc-root]/disciplines/*.md` matches `Append to \`[sdlc-root]/disciplines/*.md\`` (with inline backticks) and vice versa. Strip inline backticks before matching.
4. Only skip matching inside **fenced code blocks** (triple backticks ```` ``` ````) — those are literal code examples, not instructions.
5. When the rule pattern contains `<domain>` or `{name}` or `[agent-name]`, treat as a wildcard that captures the substring at that position. **The wildcard matches ANY value at that position, including other angle-bracket-looking placeholders in the source.** The captured string (placeholder and all) is inserted into the replacement. Do NOT require the captured value to be a "real" domain name — the rule's job is structural transformation, not semantic validation.

   **Worked example:**
   - Rule: `(e.g., [sdlc-root]/knowledge/<domain>/)` → `(e.g., memory entries tagged sdlc:knowledge + sdlc:domain:<domain>)`
   - Input: `(e.g., [sdlc-root]/knowledge/<discipline>/)`
   - `<domain>` wildcard captures `<discipline>`
   - Output: `(e.g., memory entries tagged sdlc:knowledge + sdlc:domain:<discipline>)`
6. **Wildcard captures (`[X]`, `<name>`, `<purpose>`, `<tag-expr>`, etc.) are non-greedy and MUST terminate at any of:** `(`, `)`, `[` (not the opening `[` of the wildcard itself), `]`, `,`, `.`, `;`, `:` followed by whitespace, **`for `**, **`to `**, **`during `**, **`when `**, **`per `**, **`with `**, or end-of-line. A capture MUST NOT swallow a following parenthetical, list comma, sentence boundary, or purpose-clause introducer. Rules that intentionally consume `for [purpose]` (e.g., `Read ... for the handoff schema`) take precedence as longest-match-wins; only opportunistic captures are stopped at these boundaries.

   **Wrong:** `find parking lot entries tagged with that deliverable's ID (e.g., [D05])` → capture swallows through `(e` → query = `"...ID (e"`
   **Correct:** capture stops at `(` → query = `"parking lot entries tagged with that deliverable's ID"`, parenthetical preserved verbatim

   **Post-write check:** scan output for `- (call |Call )memory_search\(query="[a-z]` with no surrounding prose context. A bullet that became a bare MCP call has lost its semantic context — halt.

7. **Verb-phrase awareness — rules that replace a verb phrase MUST produce a verb phrase.** When the source is verb + object (`update X`, `read Y`), the replacement must also be verb + object. Three options when a rule's replacement is a parenthetical or noun phrase:

   a. **Preferred:** extend the match to the full sentence clause (consume trailing `with Y`, `to Z`). Use extended-variant rules when the context contains `to <verb>` or `with <object>`.
   b. **Acceptable:** emit a grammatically-valid verb-phrase replacement (e.g., `skip this step (reason)` instead of bare `(reason)`).
   c. **Last resort:** emit `TRANSFORMATION_WARNING` and leave verbatim.

   **Enforcement:** tag every rule as `VERB_PHRASE` or `CLAUSE_REPLACEMENT`. `CLAUSE_REPLACEMENT` rules MUST match whole-clause spans. Applying one to a sub-clause match produces grammatical corruption — halt.

   **Wrong:** `2. update [sdlc-root]/knowledge/agent-context-map.yaml with the mapping` → `2. (skip — Neuroloom uses tag-based wiring) with the mapping`
   **Correct:** extend match to consume `with the mapping` → `2. Tag new knowledge via memory_store with sdlc:domain:[domain] tags`

8. **Concept-terminology is unidirectional (file-mode → Neuroloom only).** Before applying a substitution, check if the target text already contains the Neuroloom form. If it does, SKIP. If a substitution would produce a LEFT-column term from the concept-terminology table, the rule is running backwards — halt.

   **Wrong:** `"knowledge memory entries"` (already Neuroloom) → `"knowledge files"` (reverted to file-mode)
   **Correct:** text already says `"knowledge memory entries"` → no substitution, leave as-is

9. **Integration sections with existing MCP calls are preserved verbatim.** The "do not transform Integration sections" exclusion means "do not apply new forward transforms." It does NOT mean "revert existing `memory_search()`/`memory_store()` calls back to `[sdlc-root]/` file paths." If an Integration line already contains MCP calls, those are the final form.

   **Wrong:** `- **Knowledge routing:** memory_search(query="...", tags=[...])` → `- **Knowledge routing:** [sdlc-root]/knowledge/agent-context-map.yaml`
   **Correct:** line has `memory_search(` → skip entirely, already transformed

10. **Never flatten domain-specific queries into generic ones.** Existing `memory_search()` calls with specific tags (`sdlc:domain:*`, `sdlc:discipline:*`) are already in their final form. Pattern Mapping defines what to PRODUCE from file-mode input — not how to rewrite existing MCP calls. If tags get shorter or less specific after transformation, flag as precision loss and halt.

    **Wrong:** `tags=["sdlc:knowledge", "sdlc:domain:testing"]` → `tags=["sdlc:knowledge"]` (lost domain scope)
    **Correct:** existing MCP call with domain tags → preserve verbatim

11. **Multi-step conditional logic survives transformation intact.** Pattern Mapping fires on individual PHRASES within algorithmic blocks (if/then/else, numbered conditional steps) but must NOT restructure the surrounding algorithm. If a section has 4 conditional steps pre-transform, it must have 4 post-transform — only the MCP call syntax within each step changes.

    **Wrong:** 4-step conditional (check tags → fallback → filter → always-include) → collapsed to 3-step unconditional
    **Correct:** each step's `memory_search()` syntax is transformed but the branching structure and step count are preserved

| cc-sdlc Generic Pattern | Neuroloom Pattern (preserve if present) |
|-------------------------|----------------------------------------|
| `consult [sdlc-root]/knowledge/agent-context-map.yaml` | `memory_search(query="[agent-name] domain-specific patterns", tags=["sdlc:knowledge"])` |
| `Consult [sdlc-root]/knowledge/agent-context-map.yaml for the [agent-name] entry and include relevant knowledge files in the dispatch prompt` | `memory_search(query="[agent-name] domain patterns for cross-domain dispatch", tags=["sdlc:knowledge"]) and include results in the dispatch prompt` |
| `Before starting substantive work, consult [sdlc-root]/knowledge/agent-context-map.yaml and find your entry. Read the mapped knowledge files...` | `Before starting substantive work, call memory_search(query="[agent-name] domain-specific patterns anti-patterns guidance", tags=["sdlc:knowledge"]) to retrieve domain-specific patterns...` |
| `Consult [sdlc-root]/knowledge/agent-context-map.yaml for the agent's mapped files` | `memory_search(query="[agent-name] mapped knowledge", tags=["sdlc:knowledge"])` |
| `Consult [sdlc-root]/knowledge/agent-context-map.yaml for knowledge wiring` | `memory_search(query="agent knowledge wiring", tags=["sdlc:knowledge"])` |
| `Consult [sdlc-root]/knowledge/agent-context-map.yaml to identify agents whose mappings include` | `memory_search(query="agents with mappings in [discipline]", tags=["sdlc:knowledge"])` |
| `update [sdlc-root]/knowledge/agent-context-map.yaml` (whole-clause match only — see match rule #7; if surrounded by `to <verb>` or `with <object>`, prefer the extended-compound rules below) | `skip this step (Neuroloom uses tag-based wiring via memory_store; no map to update)` — `VERB_PHRASE` class, can slot mid-sentence |
| `Update [sdlc-root]/knowledge/agent-context-map.yaml to add a new entry mapping the agent to relevant knowledge files` | Skip — Neuroloom uses domain-scoped tags (`sdlc:domain:[domain]`) for routing; no map to update |
| `Update [sdlc-root]/knowledge/agent-context-map.yaml to wire newly created knowledge files to relevant agents` | Skip — tag new knowledge with `sdlc:domain:[domain]` via memory_store; agents self-route by domain |
| `Read [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml` | `memory_search(query="agent communication protocol structured progress handoff format", tags=["sdlc:knowledge", "sdlc:domain:architecture"])` |
| `Read [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml and follow the canonical agent communication protocol it defines` | `memory_search(query="agent communication protocol structured progress handoff format", tags=["sdlc:knowledge", "sdlc:domain:architecture"]) and follow the canonical agent communication protocol it defines` |
| `Read [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml for the handoff schema` | `Call memory_search(query="agent communication protocol handoff schema", tags=["sdlc:knowledge", "sdlc:domain:architecture"]) for the handoff schema` |
| `Read [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml for <purpose>` (generic `for <purpose>` suffix) | `Call memory_search(query="agent communication protocol <purpose>", tags=["sdlc:knowledge", "sdlc:domain:architecture"]) for <purpose>` |
| `Append to [sdlc-root]/disciplines/*.md` | `memory_store(tags=["sdlc:discipline:{name}", "sdlc:parking-lot"])` |
| `Append each insight or GAP entry to the relevant [sdlc-root]/disciplines/*.md parking lot` | `memory_store(tags=["sdlc:discipline:{name}", "sdlc:parking-lot"]) each insight or GAP entry` |
| `look up the agent's mapped files from [sdlc-root]/knowledge/agent-context-map.yaml` | `memory_search(query="{agent-name} domain patterns", tags=["sdlc:knowledge"])` |
| `knowledge stores ([sdlc-root]/knowledge/)` | `Neuroloom knowledge store (via memory_store)` |
| `[sdlc-root]/knowledge/testing/` (as capture target) | `memory_store with tags ["sdlc:knowledge", "sdlc:domain:testing"]` |
| `[sdlc-root]/knowledge/<domain>/` (as capture target) | `memory_store with tags ["sdlc:knowledge", "sdlc:domain:<domain>"]` |
| `Append to [sdlc-root]/knowledge/<domain>/` | `memory_store with tags ["sdlc:knowledge", "sdlc:domain:<domain>"]` |
| `Cross-project knowledge updates append to [sdlc-root]/knowledge/<domain>/` | `Cross-project knowledge updates go to memory_store with tags ["sdlc:knowledge", "sdlc:domain:<domain>"]` |
| `[sdlc-root]/knowledge/provenance_log.md` | **No transformation** — file lives on disk in Neuroloom projects too (project-specific, append-only; treated like `process/sdlc_changelog.md`). Preserve references verbatim. |
| `Read [sdlc-root]/knowledge/provenance_log.md` | **No transformation** — preserve verbatim (on-disk file read, not a knowledge-layer lookup). |
| `[sdlc-root]/knowledge/compliance-methodology.md` | `Neuroloom compliance methodology (memory_search with sdlc:knowledge, sdlc:methodology:compliance tags)` |
| `Read [sdlc-root]/knowledge/compliance-methodology.md for the full methodology` | `memory_search(query="SDLC compliance audit methodology", tags=["sdlc:knowledge"]) for the full methodology` |

**Wildcard rules (apply to any matching path not already covered by a specific rule above):**

| cc-sdlc Wildcard Pattern | Neuroloom Replacement |
|--------------------------|------------------------|
| `Read [sdlc-root]/knowledge/<domain>/<file>.yaml` | `memory_search(query="<file-name-as-topic>", tags=["sdlc:knowledge", "sdlc:domain:<domain>"])` |
| `Read [sdlc-root]/knowledge/<domain>/<file>.yaml and <verb> [rest]` | `memory_search(query="<file-name-as-topic>", tags=["sdlc:knowledge", "sdlc:domain:<domain>"]) and <verb> [rest]` |
| `Read [sdlc-root]/disciplines/<name>.md` | `memory_search(query="<name> discipline entries", tags=["sdlc:discipline:<name>"])` |
| `Read [sdlc-root]/disciplines/*.md` (glob across all disciplines) | `memory_search(query="discipline entries", tags=["sdlc:discipline:*"])` |
| `Read [sdlc-root]/disciplines/*.md and find [X]` | `memory_search(query="[X]", tags=["sdlc:discipline:*"])` |
| `read [sdlc-root]/disciplines/*.md and find parking lot entries tagged with <tag-expr>` (mid-sentence verb) | `memory_search(query="parking lot entries tagged <tag-expr>", tags=["sdlc:discipline:*", "sdlc:parking-lot"])` |
| `Read [sdlc-root]/disciplines/<name>.md and find [X]` | `memory_search(query="[X]", tags=["sdlc:discipline:<name>"])` |
| `scan [sdlc-root]/disciplines/ for [X]` / `scan [sdlc-root]/disciplines/*.md for [X]` | `memory_search(query="[X]", tags=["sdlc:discipline:*"])` |
| `Read relevant files under [sdlc-root]/knowledge/ and [sdlc-root]/disciplines/ for [X]` | `memory_search(query="[X]", tags=["sdlc:knowledge", "sdlc:discipline:*"])` |
| `Read relevant methodology files in [sdlc-root]/knowledge/` | `memory_search(query="methodology [context]", tags=["sdlc:knowledge"])` |
| `Read [sdlc-root]/knowledge/architecture/` or `[sdlc-root]/knowledge/testing/` YAML files and follow their general pattern | `memory_search(query="knowledge YAML pattern", tags=["sdlc:knowledge", "sdlc:domain:architecture", "sdlc:domain:testing"]) and follow the pattern` |
| `Read [sdlc-root]/knowledge/README.md § "<section>"` | `memory_search(query="knowledge layer <section>", tags=["sdlc:knowledge"])` |
| Evidence/citation parenthetical `[sdlc-root]/knowledge/<domain>/<file>.yaml, <section>` | `memory graph reference: sdlc:knowledge + sdlc:domain:<domain>, <section>` |

**Audit-description metadata (prose references in audit dimensions, compliance criteria, analysis descriptions):**

| cc-sdlc Audit-Description Pattern | Neuroloom Replacement |
|-----------------------------------|-----------------------|
| `Any YAML file in [sdlc-root]/knowledge/` | `Any memory entry tagged sdlc:knowledge` |
| `files in [sdlc-root]/knowledge/` | `memory entries tagged sdlc:knowledge` |
| `listed in [sdlc-root]/knowledge/agent-context-map.yaml` | `discoverable via domain-scoped memory_search (sdlc:domain:* tags)` |
| `[sdlc-root]/knowledge/<discipline>/ directory` | `sdlc:knowledge + sdlc:domain:<discipline> memory entries` |
| `entries in [sdlc-root]/disciplines/` | `entries tagged sdlc:discipline:*` |
| `patterns that should be in [sdlc-root]/knowledge/ or [sdlc-root]/disciplines/` | `patterns that should be in the memory graph (sdlc:knowledge / sdlc:discipline:* tags)` |
| `no corresponding [sdlc-root]/knowledge/<discipline>/ directory` | `no corresponding sdlc:knowledge + sdlc:domain:<discipline> memory entries` |
| `YAML files under [sdlc-root]/knowledge/` | `memory entries tagged sdlc:knowledge` |
| `in [sdlc-root]/knowledge/` or `in [sdlc-root]/disciplines/` (prose, non-instruction) | `in the Neuroloom memory graph (sdlc:knowledge / sdlc:discipline:* tags)` |

**Knowledge-layer concept terminology (prose describing the knowledge layer's shape, not its paths):**

Audit-description metadata (table above) handles path-reference prose. This new class handles the **shape-describing terminology** — prose that talks about the knowledge layer using file-based vocabulary ("parking lot entries", "Knowledge YAML files", "agent-context-map.yaml" as a live thing) where no `[sdlc-root]/` path appears. These terms describe *what* knowledge lives in cc-sdlc by reference to its storage medium (files). In a Neuroloom install the storage medium is the memory graph, so the vocabulary must be translated even though no path is visible.

Added post-`migrate-fa70ef` audit: the previous audit-description rules fired on `[sdlc-root]/knowledge/<domain>/ directory` and similar path-bearing prose but left untouched pure file-speak like "parking lot entries" that doesn't contain a path. The translation is still needed because these terms leak the file-based architecture into the Neuroloom documentation.

| cc-sdlc Concept Terminology | Neuroloom Replacement |
|-----------------------------|------------------------|
| `parking lot entries` (used as a live concept, not describing a procedure specific to file-based mode) | `discipline memory entries` |
| `parking lot entries tagged with <X>` | `discipline memory entries tagged sdlc:discipline:* and <X>` |
| `parking lot entry` (singular) | `discipline memory entry` |
| `discipline parking lots` (used as a live concept) | `discipline memory entries` (or just `discipline memories` where plural-noun-phrase is needed) |
| `Knowledge YAML files` / `knowledge YAML files` / `YAML knowledge files` | `memory entries tagged sdlc:knowledge` |
| `knowledge YAML addition (new file or new rules in existing file)` | `knowledge memory addition (new entries or new rules in existing entries)` |
| `knowledge YAML` (bare, as live concept — not describing a file format) | `memory entries tagged sdlc:knowledge` |
| `agent-context-map.yaml` (referenced as a live config file) | `domain-scoped memory search (agents query by sdlc:domain:* tags)` |
| `agent-context-map` (bare, used as a live thing) | `domain-scoped memory routing` |
| `Disciplines exercised without parking lots` | `Disciplines exercised without memory entries` |
| `Discipline parking lot entry` (as a log-of-insight type) | `Discipline memory entry` |
| `YAML files` (when referring to knowledge-layer storage) | `memory entries` |
| `new YAML files` / `existing YAML files` / `these YAML files` (in a knowledge-layer context) | `new memory entries` / `existing memory entries` / `these memory entries` |
| `Write new YAML files or append to existing ones` (knowledge-layer step) | `Store new memory entries or update existing entries` |
| `Update the knowledge store's README.md to list new files` / `add them to the README's structure listing and "Knowledge Categories" table` | `Update the knowledge index (memory entries tagged sdlc:knowledge + sdlc:knowledge-index) to list new entries` — OR, more commonly, drop the instruction entirely since Neuroloom has no README-listing equivalent and tag-based indexing is automatic |
| `project-specific files` (when enumerating knowledge-layer content) | `project-specific memory entries` |
| `on-disk knowledge` / `file-based knowledge` / `knowledge on disk` | `memory-graph knowledge` |
| `discipline file exists` / `no discipline file` (for layer-existence check) | `discipline memories exist` / `no discipline memories` |
| `knowledge store` (bare singular, used as a concept — not as a path or heading) | `knowledge layer` (or `memory-graph knowledge` where "layer" reads oddly) |
| `knowledge stores` (bare plural, used as a concept) | `knowledge memory entries` |
| `knowledge store maturation` | `knowledge layer maturation` |
| `knowledge store population` | `knowledge memory population` |
| `knowledge store's README.md` (live reference to file-mode index) | drop the reference entirely; Neuroloom has no README-based index — tag-based indexing is automatic |
| `existing knowledge stores` (as a source to query, e.g., "for deduplication") | `existing knowledge memory entries` |
| `target knowledge store` (for placement) | `target knowledge domain (`sdlc:knowledge + sdlc:domain:<name>` tags)` |
| `discipline files` (bare plural) | `discipline memory entries` |
| `discipline file` (bare singular) | `discipline memory entry` |
| `parking lot placement` / `parking lot triage` / `parking lot candidate` | `discipline memory placement` / `discipline memory triage` / `discipline memory candidate` |
| `knowledge file` (bare singular, used as a concept) | `knowledge memory entry` |
| `knowledge-store entry` / `knowledge-store entries` (hyphenated compound, added post-`migrate-0957db` 2026-04-26) | `knowledge memory entry` / `knowledge memory entries` |
| `knowledge-store` (bare hyphenated, used as a concept) | `knowledge memory` |
| `parking-lot entry` / `parking-lot entries` (hyphenated, added post-`migrate-0957db`) | `discipline memory entry` / `discipline memory entries` |
| `parking-lot memory entries` / `parking-lot memory entry` (hyphenated form already partially Neuroloom-ified — drop the `parking-lot` prefix) | `discipline memory entries` / `discipline memory entry` |
| `discipline parking-lot entry` / `discipline parking-lot entries` (hyphenated compound) | `discipline memory entry` / `discipline memory entries` |
| `knowledge store gaps` / `knowledge-store gaps` | `knowledge layer gaps` |
| `knowledge index` (bare, describing the knowledge layer's table of contents) | drop the reference — Neuroloom uses tag-based indexing; there is no manual index to maintain |
| `under the ## Parking Lot heading` / `under the Parking Lot heading` / `in the parking lot section` (markdown-structure reference to discipline file layout) | drop or rephrase — Neuroloom discipline entries are discrete memory entries, not sections within a file; e.g., `as a discipline memory entry` |
| `produces knowledge YAML in [sdlc-root]/knowledge/` / `produces knowledge YAML under [sdlc-root]/knowledge/` | `produces knowledge memory entries via memory_store` |
| `knowledge area` (bare, in "Suggested knowledge area: <X>" / "the knowledge area for <X>") | `domain tag` (`Suggested domain tag: sdlc:domain:<X>`) |
| `Suggested knowledge area: [sdlc-root]/knowledge/<domain>/` (full template form) | `Suggested domain tag: sdlc:domain:<domain>` |

**Contextual file→entry substitutions (added post-v1.5.4 second-pass audit):**

The first-pass rules catch explicit terms (`knowledge stores`, `knowledge files`, `agent-context-map.yaml`). This class catches **contextual "file" usage** — places where "file" is used generically to mean "piece of knowledge content" without being paired with "knowledge" or "discipline" as a keyword. Examples: "one file says", "mapped files", "per-file staleness".

**Scope restriction (CRITICAL — prevents false positives):** These rules fire ONLY within sections that deal with knowledge or discipline content. A section qualifies if its nearest enclosing heading (any `#` level) contains any of: `Knowledge`, `Discipline`, `Parking Lot`, `Agent Knowledge`, `Contradiction`, `Staleness`, `Knowledge Layer`, `Knowledge Wiring`, `Knowledge Store`. This avoids false positives in sections discussing actual on-disk files (process docs, agent files, skill files, source code).

| cc-sdlc Contextual Pattern | Neuroloom Replacement | Context |
|-----------------------------|------------------------|---------|
| `mapped files` (agent dispatch context — "the agent's mapped files") | `mapped entries` | Knowledge wiring sections |
| `spec-relevant files` | `spec-relevant entries` | Spec filtering in sdlc-plan |
| `loaded files` (agent memory section — "loaded files from knowledge") | `loaded memory entries` | Agent knowledge context |
| `Cross-File` (in section headings, e.g., "Cross-File Contradiction") | `Cross-Entry` | Compliance methodology headings |
| `one file says` / `two files recommend` / `N files <verb>` (report prose) | `one entry says` / `two entries recommend` / `N entries <verb>` | Contradiction detection reports |
| `File A:` / `File B:` (report template labels) | `Entry A:` / `Entry B:` | Report templates showing contradictions |
| `per-file staleness` / `per-file freshness` | `per-entry staleness` / `per-entry freshness` | Staleness audit dimensions |
| `unmapped files` (report placeholder) | `unmapped entries` | Audit reports |
| `N design files mapped` (display blocks) | `N design entries mapped` | Ingest UI examples |
| `agents with N+ files from` | `agents with N+ entries from` | Ingest coverage reports |
| `YAML skeleton` (for knowledge additions) | `memory entry draft (content and tags)` | Improvement methodology |
| `discipline/store` (compound shorthand) | `discipline/domain` | Audit improvement tables |
| `knowledge/discipline stores` (compound) | `knowledge/discipline memory entries` | Audit summary prose |

**Bare path fragments in example tables (not instruction contexts):**

| cc-sdlc Example-Table Pattern | Neuroloom Replacement |
|-------------------------------|------------------------|
| `knowledge/architecture/` (in example table cells, not instructions) | `knowledge memory (sdlc:domain:architecture)` |
| `knowledge/<domain>/` (in example table cells) | `knowledge memory (sdlc:domain:<domain>)` |
| `disciplines/<name>.md` (in example table cells) | `discipline memory (sdlc:discipline:<name>)` |

These fire only in table cells (`|...|`) where the path is illustrative, not in instruction contexts (which are handled by Pass 1 rules).

**Verb-of-path constructions (added post-`migrate-0957db` 2026-04-26 — sleeved Class G):**

Upstream prose sometimes uses a verb followed by a prepositional phrase referring to a path-as-noun-phrase, rather than the canonical `<verb> [sdlc-root]/<path>` form. Example: `Explicit reads of [sdlc-root]/knowledge/ files` — the `[sdlc-root]/knowledge/` is the object of `of` rather than the direct object of `reads`. Pass 2 noun-phrase rules don't fire on this construction because the noun phrase is split across the path and the trailing `files` token. Pass 1 instruction rules don't fire either because the verb isn't immediately adjacent to a recognizable canonical-phrase pattern.

| Construction | Replacement |
|---|---|
| `<verb> of [sdlc-root]/knowledge/ files` (e.g., `Explicit reads of [sdlc-root]/knowledge/ files`) | `<verb> of memory entries tagged sdlc:knowledge` |
| `<verb> of [sdlc-root]/disciplines/ files` | `<verb> of memory entries tagged sdlc:discipline:*` |
| `<verb> against [sdlc-root]/knowledge/ files` | `<verb> against memory entries tagged sdlc:knowledge` |
| `<verb> across [sdlc-root]/knowledge/ files` | `<verb> across memory entries tagged sdlc:knowledge` |
| `<verb> through [sdlc-root]/knowledge/ files` | `<verb> through memory entries tagged sdlc:knowledge` |
| `<verb> from [sdlc-root]/knowledge/ files` | `<verb> from memory entries tagged sdlc:knowledge` |

**Captured verbs (non-exhaustive):** `reads`, `writes`, `consults`, `lookups`, `references`, `mentions`, `searches`, `queries`, `iterations`, `passes`. The capture is `<verb>` not a literal — match any preceding word followed by `of [sdlc-root]/...` (or `against`, `across`, `through`, `from`).

**Match scope:** verb-of-path rules apply in PROSE contexts only — not inside fenced code blocks, Integration sections, or YAML/JSON structured data. Same exclusions as other Pass 2 rules.

**Bug this prevents:** sleeved `migrate-0957db` left `analysis-methodology.md:66` with `- Explicit reads of [sdlc-root]/knowledge/ files` — the only known instance of the verb-of-path class at the time. The cc-sdlc upstream line has been rephrased to canonical form (`Explicit \`Read [sdlc-root]/knowledge/<file>.yaml\` calls`) so the existing Pass 1 wildcard rule fires; this Pass 2 class catches any future verb-of-path constructions that slip through.
| `knowledge files` (bare plural, used as a concept) | `knowledge memory entries` |
| `YAML rule file` / `rule YAML file` / `rule file` (knowledge-layer context) | `knowledge memory entry` |
| `Knowledge Stores` (heading label) | `Knowledge Memory` (heading label) — paired with body-text update per heading rule |
| `Knowledge YAMLs` (bare plural short form — NOT "Knowledge YAML files") | `knowledge memory entries` |
| `Discipline Parking Lots` (heading label) | `Discipline Memory Entries` (heading label) — paired with body-text update per heading rule |
| `Parking Lot Entries` (heading label) | `Discipline Memory Entries` (heading label) |
| Numbered-list bold-label prefix `N. **Discipline parking lot entries** (...)` / `- **Discipline parking lot entries** (...)` | `**Discipline memory entries** (...)` — label rewritten; parenthetical continues via metadata rule |
| Numbered-list bold-label prefix `N. **Knowledge store updates** (...)` / `- **Knowledge store updates** (...)` | `**Knowledge memory updates** (...)` — label rewritten; parenthetical continues via metadata rule |
| Numbered-list bold-label prefix `N. **Knowledge YAML addition** (...)` | `**Knowledge memory addition** (...)` |

**Label-prefix-before-parenthetical combined rule (added after migrate-fa70ef audit):**

When a metadata-transformation parenthetical rule fires (e.g., `([sdlc-root]/disciplines/*.md)` → `(memory graph, entries tagged sdlc:discipline:*)`), the matcher MUST also scan the immediately-preceding text for a concept-terminology label. If the label is in the concept-terminology table (above), rewrite the label in the same pass. Examples:

- Input: `- **Discipline parking lot entries** (\`[sdlc-root]/disciplines/*.md\`)`
- After parenthetical rule alone (incorrect): `- **Discipline parking lot entries** (memory graph, entries tagged sdlc:discipline:*)`
- After combined rule (correct): `- **Discipline memory entries** (memory graph, entries tagged sdlc:discipline:*)`

**Why this matters:** Without the combined rule, half-transformed output surfaces in numbered lists and bullet lists where the file-speak label precedes a correctly-Neuroloom-ified parenthetical. The sleeved audit surfaced ~6 such sites in `sdlc-execute.md`, `sdlc-lite-execute.md`, and `compliance-methodology.md`. Single-pass parenthetical rules must look left to find these labels and rewrite them together.

**Scope:** the look-left scan only considers text on the same line, up to the line-start or the previous sentence boundary (`. ` / `! ` / `? `). It does not cross line boundaries or sentence boundaries — labels and their parentheticals are always written as a single logical unit on one line.

**Concept-terminology match notes:**

- These rules apply in PROSE contexts that describe the knowledge layer's **shape** rather than its **paths**. They're distinguished from audit-description rules by the absence of `[sdlc-root]/` in the matched text.
- **Do NOT apply inside:** fenced code blocks, changelog entries, the phrasing contract doc itself. **Integration sections ARE eligible** for concept-terminology (Pass 2) — only Pass 1 path transforms are excluded from Integration sections. Headings that are the literal title of a framework-defined procedure (e.g., `### 9a. Scan Related Parking Lot Entries` as a defined section of the archive skill) are a different case — see below.
- **Headings are a special case.** An H3/H4 heading like `### 9a. Scan Related Parking Lot Entries` names a procedure that cc-sdlc defines. In Neuroloom the procedure still exists but operates on memory entries, so rename the heading to `### 9a. Scan Related Discipline Memory Entries` AND adjust the body's procedure text to match. Do NOT transform the heading without transforming the body — that produces a mismatch where the heading says "memory entries" and the body says "files".
- **Procedure-specific steps are a special case.** Content like "Write new YAML files or append to existing ones" is a file-mode procedure. In Neuroloom, the procedure is "call `memory_store(content=..., tags=[...])`" — a completely different mechanism. When you see a numbered step that's a file-mode procedure, the replacement must be the Neuroloom procedure equivalent, not a word-for-word term swap. When no clean equivalent exists (e.g., "update the README.md structure listing"), emit `TRANSFORMATION_WARNING` and consider dropping the step since it's file-mode-only work the adapter doesn't need.
- **Fragments match independently within sentences,** same rule as audit-description. A sentence with multiple concept-terms must have each term transformed separately.

**The bug this prevents:** `migrate-fa70ef` left `improvement-methodology.md:213` with the full sentence: "No markers needed for project-specific files: Knowledge YAML files, discipline parking lot entries, and agent-context-map.yaml are project-owned..." All three concept terms describe the knowledge layer in file terms; none contain a `[sdlc-root]/` path so audit-description rules didn't fire. The new class catches this: `Knowledge YAML files` → `memory entries tagged sdlc:knowledge`; `discipline parking lot entries` → `discipline memory entries`; `agent-context-map.yaml` (live reference) → `the memory graph`. Same class of bug at `improvement-methodology.md:47/80/137–138/196–197`, `sdlc-archive.md:171/173/185`, `sdlc-ingest.md:214–218`, `research-external.md:72/204`.

**Audit-description match notes:**
- These rules apply in PROSE contexts where `[sdlc-root]/knowledge/` or `/disciplines/` appear as concept references, not runtime read instructions. Most common in `compliance-methodology.md` audit dimension descriptions.
- Do NOT apply inside Integration sections (`**Uses:**`, `**Depends on:**`), table cells, or code blocks — use the metadata-transformation table above for those.
- Distinguishing signal: if removing the path would leave the sentence still making sense (just less specific), it's audit-description metadata. If removing it breaks an instruction, it's a runtime ref — use the instruction rules above.
- **Fragments match independently within compound sentences.** A sentence with multiple path references (e.g., `Any memory entry tagged sdlc:knowledge not listed in any agent's mapping in [sdlc-root]/knowledge/agent-context-map.yaml. Severity: Warning...`) must have every `[sdlc-root]/...` fragment matched separately. The matcher walks the sentence and applies each audit-description rule to each fragment independently. Mixed results (one half transformed, one half untransformed) are a known failure mode and indicate the matcher only ran once per sentence.

   **The bug this prevents:** In `migrate-f01a70`, a compound sentence with multiple `[sdlc-root]/...` fragments got only one fragment transformed, leaving the other as a corrupted hybrid. The matcher must treat each `[sdlc-root]/...` occurrence as a separate match target — walk the sentence and apply rules independently to each fragment.
- **Bare target-path rewrites (`.claude/sdlc/...`, `ops/sdlc/...`) are NOT audit-description transforms.** If a fragment already shows a resolved `.claude/sdlc/knowledge/` or `ops/sdlc/knowledge/` path (not `[sdlc-root]/`), that's a prior bug where path-variable rewriting fired instead of knowledge-layer transformation. Flag as `TRANSFORMATION_WARNING` — don't silently leave the target-path in installed content (`research-external.md:72` exemplar).
- `<domain>`, `<name>`, `<file>`, `<section>`, `[X]` capture the substring at that position
- For `<file-name-as-topic>`, convert the filename to a natural-language topic (e.g., `testing-paradigm.yaml` → `"testing paradigm"`, `debugging-methodology.yaml` → `"debugging methodology"`)
- If a specific rule above matches first, use it; wildcards only fire when no specific rule applies
- Wildcards fire only in instruction contexts (not in metadata/Integration sections/tables) — apply the same instruction-vs-metadata distinction as specific rules

#### Metadata transformation (parenthetical and table-cell path refs)

Parenthetical paths and table-cell paths in cc-sdlc source describe WHERE something lives in filesystem mode. In Neuroloom, those paths don't exist — the content is in the memory graph. Transform these metadata refs to their Neuroloom-native equivalent so Neuroloom users aren't pointed at non-existent files.

Apply these rules to: parenthetical paths `(...)`, table cells containing paths (any column, not just first/last), bullet-point labels with paths (both `Label: path` and `Label (path)` forms). Do NOT apply inside fenced code blocks or when the path is in a canonical instruction already handled above.

**Match rules for metadata transformation:**

1. **Strip inline backticks before matching — MANDATORY for metadata rows.** A rule `([sdlc-root]/knowledge/*.md)` matches all of these forms; the executor MUST normalize by stripping single backticks around the path before the rule is tested:
   - `([sdlc-root]/knowledge/*.md)` — bare
   - `` (`[sdlc-root]/knowledge/*.md`) `` — path in backticks inside parens
   - `` `([sdlc-root]/knowledge/*.md)` `` — entire parenthetical in backticks
   - `(\`[sdlc-root]/knowledge/*.md\`)` — escaped-backtick in markdown source
   This is the identical rule as instruction-pattern match rule #3. If you are reading this spec and find yourself wondering "does backtick-stripping apply to metadata rows the same way as to instruction rows?" — yes, always, no exceptions. Do not treat any metadata row as "only matches when no backticks present."
2. **`(e.g., ...)` prefix is absorbed.** The `e.g.,` ( / `e.g.` / `i.e.,`) prefix inside parens is treated as boilerplate and preserved in the replacement.
3. **Table-cell match is column-agnostic.** Match any cell whose content contains the target path — first column, last column, or middle. Do not restrict to specific column positions.
4. **Bullet label separator can be `:` or `(`.** Both `- Label: path` and `- Label (path)` are metadata forms — the transformation preserves the label and the separator form.
5. `<domain>`, `<name>`, `<file>` are wildcards that capture the substring at that position.

**Worked examples (executor-facing — verify your matcher produces exactly these outputs):**

| Input (before) | Output (after) |
|----------------|----------------|
| `` - Knowledge store updates (`[sdlc-root]/knowledge/*.md`) `` | `- Knowledge store updates (memory graph, entries tagged sdlc:knowledge)` |
| `` - Discipline parking lot entries (`[sdlc-root]/disciplines/*.md`) `` | `- Discipline parking lot entries (memory graph, entries tagged sdlc:discipline:*)` |
| `` - Files from the same discipline (e.g., `[sdlc-root]/knowledge/<discipline>/`) `` | `- Files from the same discipline (e.g., memory entries tagged sdlc:knowledge + sdlc:domain:<discipline>)` |
| `` \| Validated, testable rules \| `[sdlc-root]/knowledge/<discipline>/<file>.yaml` \| Specific, testable... \| `` | `\| Validated, testable rules \| memory entries tagged sdlc:knowledge + sdlc:domain:<discipline> \| Specific, testable... \|` |
| `` - Agent knowledge context: `[sdlc-root]/knowledge/agent-context-map.yaml` `` | `- Agent knowledge context: domain-scoped memory search (sdlc:domain:* tags)` |
| `### 6a. Discipline Parking Lots (`[sdlc-root]/disciplines/`)` | `### 6a. Discipline Parking Lots (memory graph, entries tagged sdlc:discipline:*)` |
| `` Read `[sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml` for the handoff schema. `` | `Call memory_search(query="agent communication protocol handoff schema", tags=["sdlc:knowledge", "sdlc:domain:architecture"]) for the handoff schema.` (NOT `Read memory_store with tags [...]` — that's a capture-target rule leaking into a Read context, see below) |
| `` belong in knowledge stores (`[sdlc-root]/knowledge/`), not agent memory. `` | `belong in the Neuroloom knowledge store (via memory_store), not agent memory.` (the `knowledge stores ([sdlc-root]/knowledge/)` rule must match mid-sentence with backticks around the path — match rule #1 applies) |

If your matcher leaves any of these untransformed, or produces output with double-parens or orphan `*.md\`)` debris, it has a **rule-priority** or **backtick-normalization** defect — halt and file a plugin bug, do not write partial output.

**Rule ordering (CRITICAL — longest parenthetical-whole wins):**

When multiple rows could match the same substring, apply them in this order and stop at the first hit:

1. **Full-parenthetical rules** — rows whose pattern begins with `(` and ends with `)`. Match the entire `(...)` span including its parens. These consume their own parens and produce replacement parens, so they splice cleanly into surrounding text.
2. **Full-label+separator rules** — `<Label>: <path>` and `<Label> (<path>)` rows. Match the label + separator + path as one span.
3. **Full-table-cell rules** — match the entire cell content between `|` bars.
4. **Bare-path rules** — rows whose pattern is just `[sdlc-root]/...` with no surrounding delimiters. Apply ONLY when no higher-priority rule matched this position.

**Why ordering matters:** If a bare-path rule fires inside an already-open `(...)` context, its replacement (which typically itself contains `(...)` boilerplate like `(memory graph, ...)`) gets spliced inside the outer parens, producing `((...) *.md`)` debris. This is the double-paren corruption observed in the 2026-04-22 `migrate-f01a70` run (`sdlc-execute/SKILL.md:279` and five other sites). The full-parenthetical rule at row 1 consumes the outer parens as part of its match, so this class of bug cannot occur when the matcher prioritizes correctly.

**Verification the matcher has correct priority:** After transforming a file, scan the output for these regressions and halt on any hit:

- `((` followed by any alphanumeric (double-open-paren)
- `*.md\`)` anywhere (orphaned glob-suffix-with-backtick)
- ``*.md`)`` mid-line (same, without escape)
- `) *.md)` (orphan-glob-without-backtick)
- `Read memory_store` anywhere (nonsensical — `memory_store` is the write API, can't be `Read`)
- `Read memory_search` anywhere (`memory_search` is a function call; `Call memory_search(...)` is the correct verb — `Read memory_search` is a malformed transformation)
- `Update memory_search` anywhere (added post-`migrate-6f4217`, sleeved 2026-04-26 — symmetric to `Read memory_store`. `memory_search` is the read API; you cannot update entries via it. Correct destination is `memory_store`)
- `Add memory_search` / `Append to memory_search` / `Wire memory_search` / `Tag memory_search` / `Store via memory_search` (same write-of-read class)
- `Add to memory_search` / `Append memory_search` (same class, different word order)
- `query="\* ` (literal asterisk-space at the START of an MCP query string — added post-`migrate-6f4217`. This indicates a glob (`*.md`) was literally injected into a query string instead of being normalized into a tag wildcard. Exemplar: `memory_search(query="* discipline", tags=["sdlc:discipline"])` at sleeved `sdlc-execute.md:345/367`. Correct form: `memory_search(query="discipline entries", tags=["sdlc:discipline:*"])` — the `*` belongs in the tag, not the query)
- `query=".*\.md` (file extension `.md` inside a query string — added post-`migrate-6f4217`. Same root cause as the asterisk-in-query case)
- `\`the knowledge graph (memory_search` (added post-`migrate-6f4217` — the prose-concept replacement `the knowledge graph` ran INSIDE backtick-formatted code context. Exemplar at sleeved `sdlc-execute.md:368`: `Knowledge store updates (\`the knowledge graph (memory_search with tags=["sdlc:knowledge"]) *.md\`)` — Pass 2 prose-concept terminology fired inside an inline-backtick code span where it should have been excluded)
- ``) \*\.md\`\)`` (terminal orphan-glob-with-backtick — broader form of `*.md\`)` that also catches the surrounding paren close. Exemplar at sleeved `sdlc-lite-execute.md:302`)

**Orphan extension-debris scan (added post-`migrate-fa70ef`):** extend the same halt-on-hit policy to these patterns. They're the same bug class as `*.md\`)` — partial-consume leaving a file-extension or glob suffix outside a completed replacement.

- `]\.yaml` (close-bracket immediately followed by `.yaml` with no separator — the matcher consumed the array-close of `tags=[...]` and left the original file extension as a tail). Exemplar: `memory_store with tags ["sdlc:knowledge"].yaml`
- `]\.yml` (same for YAML's alternate extension)
- `]\.md` (same for markdown)
- `]testing-paradigm\.yaml` / `]\w+\.yaml` (bracket-close concatenated to a file name — `migrate-fa70ef` exemplar at `sdlc-tests-create.md:250`)
- `\]/\.` and `/\.[^/a-zA-Z0-9]` (trailing `/.` left when a directory suffix was consumed) — exemplar at `process/overview.md:45` `memory_store with tags [...]/.`
- `"\]\.\w+` (quoted-bracket followed by dot-extension — stricter form catching edge cases)

If any of these match the written content, the matcher picked a rule whose replacement didn't consume the trailing file-extension token, leaving it concatenated to the replacement's array-close. The output file MUST NOT be written. Re-examine the rule whose replacement ends in `]` — it's missing the trailing `.yaml` / `.md` / `/` suffix consumption.

**Fence-parity assertion (added post-`migrate-fa70ef`):** count lines matching `^\s*\`\`\`` in both the pre-merge project version and the post-write content. The post-write count must be either **equal to the upstream count** (no net change in fenced blocks) OR **equal to `project_pre_merge_count`** (preserved as-is), whichever is applicable per the merge subtype:

- `exempt_verbatim` / `mcp_backfilled` subtype → post count must equal upstream count
- `mcp_preserved` subtype → post count must equal `project_pre_merge_count + (upstream_count - project_pre_upstream_count)` where `project_pre_upstream_count` was the fence count in the upstream version the project last migrated from
- `mcp_new_file` → post count must equal upstream count

A post count that differs from the expected by an odd number = an unclosed fence (someone added an opener without a closer or vice versa). Halt on this; it means the content-merge spliced a block mid-fence. Exemplar: `migrate-fa70ef` at `sdlc-ingest.md:192` — merge introduced `` ```yaml `` without a matching close-fence.

If any match, the matcher picked a bare-path rule over a parenthetical rule, OR a capture-target rule over an instruction rule, OR the merge window was misaligned — the output file MUST NOT be written.

**Integration sections are structurally exempt from Pass 1 — HARD EXCLUSION:**

Any line matching `^\*\*(Uses|Depends on|Updates|Feeds into|Complements|Downstream|Does NOT replace|DRY notes):\*\*` and every bullet/text line following it up to the next blank line, the next `^\*\*[A-Z]` (new Integration label), or the next `^#{1,6} ` (heading) is an **Integration section**. Integration sections are exempt from **Pass 1** transformation:

- No instruction-rule matching
- No metadata-rule matching
- No capture-target-rule matching
- No audit-description rule matching

Integration sections describe logical dependencies between skills/agents/files, not runtime operations. Transforming `**Uses:** [sdlc-root]/knowledge/agent-context-map.yaml (for wiring)` into a Neuroloom equivalent adds noise and produces double-paren corruption. Leave path references in Integration sections verbatim.

**Pass 2 concept-terminology IS allowed in Integration sections.** Prose descriptors within Integration bullets — parenthetical explanations, trailing descriptions — use concept terms like "knowledge stores" and "parking lot entries" that describe the knowledge layer's shape. These are prose, not paths, and must be transformed. Example:
- Input: `` **Depends on:** `[sdlc-root]/disciplines/*.md` (parking lot entries for knowledge hygiene) ``
- After Pass 2: `` **Depends on:** `[sdlc-root]/disciplines/*.md` (discipline memory entries for knowledge hygiene) ``
- The backticked path is untouched (Pass 1 exempt); the parenthetical prose is transformed (Pass 2).

**What Pass 2 MUST NOT touch in Integration sections:**
- Path references (backticked or bare `[sdlc-root]/...` paths) — these are Pass 1's domain
- Backticks around paths — preserve byte-identical
- The `**Label:**` prefix itself

**Enforcement (Pass 1):** The matcher must mask out Integration sections before Pass 1 rule evaluation. A post-write regression scan for `\*\*(Uses|Depends on|Updates|Feeds into):\*\*.*memory_(search|store)` on a single line halts the write — Pass 1 leaked into an Integration section.

**Path byte-preservation in Integration sections:** Path references and their surrounding backticks in Integration-section lines must be written out byte-for-byte identical to the upstream source. This includes — and this is the failure mode `migrate-fa70ef` surfaced across 20+ files — **surrounding backticks on path references**. `` **Uses:** `[sdlc-root]/process/manager-rule.md` `` must retain its inline backticks intact. Any incidental side-effect that strips backticks violates the hard exclusion. Pass 2 concept-terminology changes to non-path prose tokens are the ONLY allowed difference.

**Post-write Integration check:** diff Integration-section path references (any token matching `[sdlc-root]/...` or `.claude/...` including surrounding backticks) byte-for-byte against upstream. Any path-character difference halts the write. Non-path prose tokens may differ only if they match a Pass 2 concept-terminology substitution.

**Why hard-gated:** The `migrate-f01a70` run transformed Integration sections in `sdlc-archive.md:230,232`, `sdlc-create-agent.md:219`, `sdlc-ingest.md:398`, `sdlc-tests-create.md:250` — producing double-paren corruption in all four. Listing Integration sections as "informationally exempt" without a structural mask is equivalent to not listing them. The `migrate-fa70ef` run exposed the follow-on: the hard-exclusion mask blocked transformation but didn't block the transformer's ancillary backtick-normalization, which stripped inline backticks from 20+ Integration lines across the repo.

**Non-transformable paths — byte-verbatim preservation (added post-`migrate-fa70ef`):**

The following path prefixes are NEVER touched by the transformer — not for Pattern Mapping transformation, not for audit-description metadata transformation, not for backtick normalization, not for any reason:

- `[sdlc-root]/process/` — process docs live on disk in Neuroloom projects too
- `[sdlc-root]/templates/` — templates live on disk
- `[sdlc-root]/playbooks/` — playbooks live on disk
- `[sdlc-root]/agents/` — agents install to `.claude/agents/`
- `[sdlc-root]/knowledge/provenance_log.md` — project-specific on-disk file
- `skills/` — skill paths

**Byte-verbatim rule:** a file reference where the path prefix matches any of the above is preserved **character-for-character** from upstream, including:
- Surrounding inline backticks (`` `[sdlc-root]/process/manager-rule.md` ``)
- Escape sequences (`` \`[sdlc-root]/templates/test_spec_template.md\` ``)
- Surrounding quotes, parentheses, brackets
- Whitespace before and after

**Why this matters:** `migrate-fa70ef` showed backticks stripped from ~20 files' references to non-transformable paths (`skills/sdlc-execute/SKILL.md`, `process/manager-rule.md`, `process/debate-protocol.md`, etc.). Individually minor — a backtick here or there doesn't break a migration — but cumulatively visible in diffs against upstream and suggests the transformer isn't honoring the exempt list strictly. Explicit byte-verbatim preservation closes this.

**Post-write scan (non-transformable-path backtick audit):** for each non-transformable path prefix, grep for any occurrence of that path in the written content. For each hit, extract the ±5 surrounding characters. Compare byte-by-byte to the same surrounding characters in the upstream version. If any character differs and the path itself is unchanged, the transformer touched content it wasn't allowed to touch. Halt the write.

**Fenced code blocks are structurally exempt — HARD EXCLUSION:**

Everything between a ` ``` ` opening fence and its matching closing fence (same number of backticks) is exempt from ALL transformation, same scope as Integration sections above. This includes ` ```yaml `, ` ```json `, ` ```bash `, ` ``` ` (no language tag), and indented code blocks (lines starting with 4+ spaces inside a list context).

**Enforcement:** Before matching, the transformer must parse fence boundaries and mask all content between them. Post-write, assert: **the count of `memory_search(` / `memory_store(` calls inside fenced code blocks must equal the pre-merge count in the same blocks**. Any increase means the transformer inserted MCP into a code example — halt and report.

**Why hard-gated:** `migrate-f01a70` transformed a ```yaml ``` block in `sdlc-ingest.md:271-273`, producing syntactically broken YAML with nested double-quotes. YAML examples demonstrate file FORMAT; transforming them removes the example's informational value AND breaks the syntax.

**Capture-target rules must NEVER fire in `Read ...` contexts:**

Rows labelled `(as capture target)` or whose replacement begins with `memory_store with tags [...]` (e.g., plugin lines 115–117) describe WRITE destinations. They exist to transform "where to write new knowledge" sentences like `Append to [sdlc-root]/knowledge/<domain>/`. These rules MUST NOT match inside a `Read ...` instruction.

**The bug this prevents:** In the 2026-04-22 `migrate-f01a70` run, `AGENT_TEMPLATE.md:133` read upstream as:
```
Read `[sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml` for the handoff schema.
```
The matcher fired the capture-target wildcard `[sdlc-root]/knowledge/<domain>/` → `memory_store with tags [...]` against a fragment of the read path, producing:
```
Read memory_store with tags ["sdlc:knowledge", "sdlc:domain:architecture"] for the handoff schema.
```
This is doubly wrong: `memory_store` is the write API (can't be read), and the correct transformation for `Read [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml for <purpose>` is the specific rule added in the instruction table (`Call memory_search(query="...<purpose>", tags=[...])`).

**Matcher requirement:** When the enclosing sentence begins with `Read ` (or `read ` mid-sentence per match rule #1), the matcher must exclude capture-target rules from the candidate set entirely. Only instruction rules (those whose replacement begins with `memory_search(` or preserves a `Read`/`Call` verb) are eligible. If the only matching rule in a `Read` context is a capture-target row, the matcher emits a `TRANSFORMATION_WARNING` for a missing instruction rule rather than producing malformed output.

**Read-rules must NEVER fire in `Update`/`Add`/`Append` contexts (added post-`migrate-6f4217` sleeved audit, 2026-04-26):**

The symmetric failure mode of "Read memory_store" is "Update memory_search" / "Add memory_search" / "Append to memory_search". `memory_search` is the read API; you cannot add, update, or append entries via it. The correct destination for write operations is always `memory_store`.

**The bug this prevents:** In the 2026-04-26 `migrate-6f4217` run, `sdlc-create-agent.md:124-128` had upstream:
```
Update `[sdlc-root]/knowledge/agent-context-map.yaml` to add a new entry mapping the agent to relevant knowledge files
```
The matcher fired a generic `[sdlc-root]/knowledge/agent-context-map.yaml` → `memory_search with tags=["sdlc:knowledge"]` rule against the path inside a write-context sentence, producing:
```
Update memory_search with tags=["sdlc:knowledge"] to add a new entry mapping the agent to relevant knowledge files
```
This is semantically impossible — `memory_search` returns entries; "Update memory_search to add a new entry" is nonsensical. Same defect at `sdlc-create-agent.md:138` (`Update memory_search with tags=["sdlc:knowledge"] with the mapping`).

**Matcher requirement:** When the enclosing sentence begins with `Update `, `Add `, `Append to `, `Wire `, `Tag `, `Store `, `Write to ` (case-insensitive on the verb per match rule #1), the matcher must exclude `memory_search`-replacement rules from the candidate set entirely. Only `memory_store`-targeted rules (those whose replacement begins with `memory_store(` or describes a write/tag operation) are eligible. If the only matching rule in an `Update`/`Add`/`Append` context is a `memory_search`-replacement, the matcher emits a `TRANSFORMATION_WARNING` and falls back to the rule on line 47 (`update [sdlc-root]/knowledge/agent-context-map.yaml` → `skip this step (Neuroloom uses tag-based wiring via memory_store; no map to update)`) or to verbatim preservation. Producing `Update memory_search` output is a hard halt — see the post-write halt list in the metadata-rules section below.

The full guard set is now bidirectional:

| Verb context (case-insensitive) | Forbidden replacement family | Why |
|---|---|---|
| `Read ...`, `read ...` | `memory_store with tags [...]` | `memory_store` is the write API; cannot be read |
| `Update ...`, `update ...`, `Add ...`, `Append to ...`, `Wire ...`, `Tag ...`, `Store ...` | `memory_search(...)` | `memory_search` is the read API; cannot accept new entries |

If a sentence's verb belongs to one column, replacements from the other column are forbidden. Symmetric handling closes the write-of-read loophole that `migrate-6f4217` exposed.

| cc-sdlc Metadata Pattern | Neuroloom Metadata Replacement |
|--------------------------|--------------------------------|
| `([sdlc-root]/knowledge/agent-context-map.yaml)` | `(domain-scoped memory search, sdlc:domain:* tags)` |
| `([sdlc-root]/knowledge/**/*.yaml)` | `(memory graph, entries tagged sdlc:knowledge)` |
| `([sdlc-root]/knowledge/*.md)` | `(memory graph, entries tagged sdlc:knowledge)` |
| `([sdlc-root]/knowledge/<domain>/*.yaml)` | `(memory graph, entries tagged sdlc:knowledge and sdlc:domain:<domain>)` |
| `([sdlc-root]/knowledge/<domain>/)` | `(memory graph, entries tagged sdlc:knowledge and sdlc:domain:<domain>)` |
| `([sdlc-root]/disciplines/*.md)` | `(memory graph, entries tagged sdlc:discipline:*)` |
| `([sdlc-root]/disciplines/<name>.md)` | `(memory graph, entries tagged sdlc:discipline:<name>)` |
| `(e.g., [sdlc-root]/knowledge/<domain>/)` | `(e.g., memory entries tagged sdlc:knowledge + sdlc:domain:<domain>)` |
| `(e.g., [sdlc-root]/knowledge/<domain>/*.yaml)` | `(e.g., memory entries tagged sdlc:knowledge + sdlc:domain:<domain>)` |
| `(e.g., [sdlc-root]/disciplines/<name>.md)` | `(e.g., memory entries tagged sdlc:discipline:<name>)` |
| Bullet label + colon + path: `<Label>: [sdlc-root]/knowledge/agent-context-map.yaml` (e.g., `- Agent knowledge context: [sdlc-root]/knowledge/agent-context-map.yaml`) | `<Label>: domain-scoped memory search (sdlc:domain:* tags)` |
| Bullet label + colon + path: `<Label>: [sdlc-root]/knowledge/<domain>/<file>.yaml` | `<Label>: memory entries tagged sdlc:knowledge + sdlc:domain:<domain>` |
| Bullet label + colon + path: `<Label>: [sdlc-root]/disciplines/<name>.md` | `<Label>: memory entries tagged sdlc:discipline:<name>` |
| Table cell containing `[sdlc-root]/knowledge/agent-context-map.yaml` (any column) | Cell becomes `domain-scoped memory search (sdlc:domain:* tags)` |
| Table cell containing `[sdlc-root]/knowledge/<domain>/<file>.yaml` (any column) | Cell becomes `memory entries tagged sdlc:knowledge + sdlc:domain:<domain>` |
| Table cell containing `[sdlc-root]/knowledge/<domain>/` (any column, directory ref) | Cell becomes `memory entries tagged sdlc:knowledge + sdlc:domain:<domain>` |
| Table cell containing `[sdlc-root]/knowledge/**/*.yaml` or `[sdlc-root]/knowledge/*.md` (any column) | Cell becomes `memory entries tagged sdlc:knowledge` |
| Table cell containing `[sdlc-root]/disciplines/*.md` or `[sdlc-root]/disciplines/<name>.md` (any column) | Cell becomes `memory entries tagged sdlc:discipline:*` (or `:<name>`) |

**Exempt from metadata transformation:**
- `[sdlc-root]/process/` references (process files exist on disk in Neuroloom projects too)
- `[sdlc-root]/templates/` references (templates exist on disk)
- `[sdlc-root]/playbooks/` references (playbooks exist on disk)
- `[sdlc-root]/agents/` references (agents exist at `.claude/agents/` — handled by path transformation, not knowledge transformation)
- `[sdlc-root]/knowledge/provenance_log.md` references (on-disk append-only file, project-specific; treated like `process/sdlc_changelog.md`)
- Integration-section `**Depends on:**` / `**Uses:**` lists where the ref is an individual bullet rather than a parenthetical — these are kept verbatim as metadata; the agent understands they describe logical dependencies, not runtime file reads

---

## Pass 2 — Prose Concept-Terminology Scope and Event Schema

**Pass 2 scope — what counts as "prose":**

A region of text is "prose" (and thus subject to concept-terminology transformation) if ALL of these hold:
- It is NOT inside a fenced code block (```` ```...``` ````, any language)
- It is NOT inside inline backticks (`` `...` ``)
- It is NOT a YAML key, YAML value, JSON key, or JSON value (when the surrounding context is structured data, even if outside a fence — e.g., frontmatter fields) — **EXCEPTION:** `description:` values in skill/agent YAML frontmatter ARE prose-eligible, because agents read these descriptions to decide whether to invoke a skill. Terms like "knowledge stores" in a description field must be transformed. Other frontmatter fields (`name:`, `model:`, `tools:`, `allowed_tools:`) remain exempt.
- It is NOT a path reference matching `[sdlc-root]/...`, `.claude/...`, `ops/sdlc/...`, `skills/`, or similar
- It is NOT an MCP call already emitted by Pass 1 (`memory_search(...)`, `memory_store(...)`)
- It is NOT a Pattern Mapping replacement string from Pass 1 (e.g., `Neuroloom knowledge store (via memory_store)`)

Examples of text Pass 2 CAN transform:
- Integration-section parenthetical descriptors after a path: `` **Depends on:** `[sdlc-root]/disciplines/*.md` (parking lot entries for knowledge hygiene) `` — the path is Pass-1-exempt, but "parking lot entries for knowledge hygiene" is prose descriptor and Pass 2 rewrites it
- Heading bodies: `### 9a. Scan Related Parking Lot Entries` — Pass 2 rewrites to `### 9a. Scan Related Discipline Memory Entries`
- Prose paragraphs outside any path/fence/structured-data context
- Bullet text that doesn't contain a path or code

Examples of text Pass 2 MUST NOT transform:
- Inside ``` ```yaml ``` ``` fences — never, even if the content contains "knowledge/design/file.yaml" as a value
- Inline `` `[sdlc-root]/knowledge/agent-context-map.yaml` `` — path refs handled by Pass 1 (or hard-excluded)
- YAML frontmatter fields like `name:`, `model:`, `tools:` — but NOT `description:` values (those are prose-eligible per the frontmatter exception above)
- MCP call arguments: `memory_search(query="parking lot entries tagged X", ...)` — the query string is an MCP call argument, not prose

**Pass 2 rules:** the concept-terminology rule class defined in § "Knowledge-layer concept terminology" of the Pattern Mapping section (above). Pass 2 applies those rules to matched prose regions.

**Pass 2 transaction log event:**
```json
{
  "ts": "ISO-8601",
  "run_id": "migrate-xxxxxx",
  "event": "concept_terminology_applied",
  "stage": "4.2-pass2",
  "file": "<install-path>",
  "substitutions": [
    {"rule": "<rule-label>", "before": "<snippet>", "after": "<snippet>", "region": "integration-descriptor|heading|prose"}
  ]
}
```

One event per file; includes an array of substitutions (may be empty if no concept-terminology rules fired). Emission is mandatory if Pass 1 wrote the file — absence of the event for a written file is a telemetry regression per Stage 5.0.

**Pass 2 halts on output regression:** after Pass 2 writes, re-run the existing post-write output-regression scans (orphan debris, double-paren, malformed verbs). If Pass 2 introduces any of those patterns, halt and roll back that file to its Pass 1 output — Pass 2 must only make prose-level concept translations; producing structural corruption is a rule bug.

**Pass 2 residue scan — added post-`migrate-6f4217` (sleeved 2026-04-26):** after Pass 2 completes for a file in a Neuroloom-backend project, scan the written content for bare concept-terminology forms that should have been transformed. If any are present **outside** the legitimate-retention contexts listed below, Pass 2 didn't fire (or didn't fire on this file) and the output is still in upstream's file-mode prose despite a Neuroloom installation:

```bash
# Run on every file Pass 2 wrote, after the write completes. A non-zero hit count
# in non-retention contexts indicates a Pass 2 misfire.
grep -inE '\bknowledge files?\b|\bdiscipline files?\b|\bparking[- ]lot entr|\bknowledge stores?\b|\bknowledge-store entr|\bdiscipline parking lots?\b|\bknowledge YAMLs?\b|\bYAML knowledge files?\b|\bagent-context-map\b|\bknowledge area\b|\bsuggested knowledge area\b' <written-file>
```

**Legitimate-retention contexts (these are NOT regressions and should be excluded from the halt):**

- Inside fenced code blocks (already excluded by Pass 2 scope rules — but verify)
- Inside Integration sections (`**Uses:**`, `**Depends on:**`, `**Feeds into:**`, etc.)
- Where the term refers to a YAML file mechanism specifically rather than the live knowledge layer (e.g., `sdlc-ingest`'s "Existing knowledge: 3 YAML files" describes the upstream file structure ingest consumes; `compliance-methodology.md` audit-dimension prose where `agent-context-map.yaml` is named as a config artifact's identity)
- The exempt files list (`process/knowledge-routing.md`, `process/sdlc_changelog.md`, `agents/sdlc-reviewer.md`, `agents/sdlc-compliance-auditor.md`, `process/path-mappings.md`) — these contain the canonical phrases as data
- Project-authored content under `.claude/agent-memory/` (filtered upstream)

**Halt condition:** if non-retention hits exist after Pass 2 wrote a file, EITHER (a) Pass 2 didn't actually run on this file (telemetry assertion will catch this independently) OR (b) the Pass 2 rules have a coverage gap. In both cases the file is in a hybrid-mode state — partial-Neuroloom, partial-file-mode prose — which is the worst output state because it's harder to detect than uniform regression. Halt before declaring `concept_terminology_applied: PASS` for that file; emit `transformation_warning` with the specific phrase, line number, and surrounding context.

**The bug this prevents:** sleeved's `process/deliverable_lifecycle.md:76` post-`migrate-6f4217` had `- Testing knowledge files updated` written to disk despite the Pass 2 rule `knowledge files` → `knowledge memory entries` existing in the table above. Pass 2 didn't fire on this file (along with ~37 sibling sites across sleeved). The user found it manually after the outside-the-run audit also missed it — the audit's path-bearing-residue grep doesn't catch bare forms. This residue scan halts the write before silent regression reaches disk; the audit skill's Scan 3b (cc-sdlc `ccsdlc-audit-adapter-installation`) catches anything that still slips through.

**Fenced code blocks containing file-mode demos — deferred to 0.5.0:** Pass 2 intentionally does not modify fenced-block contents, even when those contents are file-mode demos (e.g., a ` ```yaml ` block demonstrating `mappings: ui-ux-designer: [paths]` in an adapter-unreachable format). Surrounding prose is transformed by Pass 2; the demo itself is preserved as cc-sdlc's original file-mode reference. Future work (0.5.0) may add an optional pre-fence annotation (e.g., *"In Neuroloom mode, the equivalent operation is `memory_store(..., tags=[...])`."*) as a demonstration-mapping rule class. Until then, fenced-block file-mode demos remain a project-specific customization zone — if your installation wants to replace the demo, wrap the whole fenced block in `PROJECT-SECTION` markers.

**EXCEPTION — Agent template code blocks (added post-v1.5.4 audit):**

Fenced code blocks that serve as **copy-paste templates for new agent content** (not format demos) ARE eligible for transformation. These blocks contain instructions or sections that get literally inserted into new agents — if they reference `[sdlc-root]/knowledge/agent-context-map.yaml`, the created agent will have stale file-mode instructions.

**Identification:** A template code block is eligible if it meets ALL of:
1. It appears inside an agent-creation or agent-modification skill (e.g., `sdlc-create-agent`)
2. Its content contains `## Knowledge Context` or `## Communication Protocol` headings, OR it's introduced by surrounding prose that says "inject", "insert", "add this section", "template for", or "paste into the agent"
3. It is NOT a ` ```yaml ` or ` ```json ` block showing data format — it's a ` ```markdown ` or unfenced template block showing agent prose

**Transformation:** Apply the same Pass 1 instruction rules that would fire if the content were outside a fence. The template block's `consult [sdlc-root]/knowledge/agent-context-map.yaml` becomes `memory_search(query="[agent-name] domain-specific patterns", tags=["sdlc:knowledge"])`.

**Transaction log:** Log `template_block_transformed` event with the file, block line range, and rules fired. The post-write MCP-in-fenced-block assertion must be updated to EXCLUDE template blocks from the count comparison — these blocks are expected to gain MCP calls.

**Currently known template blocks:**
- `sdlc-create-agent/SKILL.md` step 3b — Knowledge Context section template
- `sdlc-create-agent/SKILL.md` step 3c — Communication Protocol section template
- `AGENT_TEMPLATE.md` — the full agent template file