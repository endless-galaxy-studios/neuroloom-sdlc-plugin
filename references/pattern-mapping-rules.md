### Pattern Mapping

> **How coverage actually works:** This table lists 5 explicit phrase-to-call mappings, but they cover only a fraction of real-world transformation sites. The vast majority of z-sdlc files with knowledge references (skills, agents, process docs) are handled via the **section-level preservation rule** documented in "Content-Merge Rules for Neuroloom" below — scan each file for `memory_search(` / `memory_store(` presence and preserve those sections verbatim during merge. The explicit patterns below are what the transformer SEEKS during fresh installation (`/sdlc-initialize`) and during migration when a file has no prior MCP patterns. Once a file contains MCP calls, section-level preservation takes over.

> **Tag-argument semantics (read before writing any `memory_search(...)` call).** `tags` is an exact-match filter; `tag_prefixes` is a prefix-match filter. By default `tags` is an OR: an entry matches when it carries ANY listed tag. `tag_prefixes` is an OR of prefix matches. When both are given they are ANDed with each other (Neuroloom API `memory_search_service`). A `*` is an ordinary character in both, so a `tags` list containing `sdlc:discipline:*` matches nothing (verified live 2026-10-29: 0 results, against 12 for the colon-prefix form, which still misses the 4 entries tagged with the bare `sdlc:discipline`).
>
> **AND across exact tags is `tags_match="all"`.** With the default OR, a second value in `tags` widens the result: a `tags` list of `sdlc:knowledge` plus `sdlc:domain:coding` returns every knowledge entry, and the domain tag scopes nothing. Emit `tags=["sdlc:knowledge", "sdlc:domain:coding"], tags_match="all"`. `tags_match: "any" | "all"` needs the D178a server change on the API. It is safe to emit before that deploys: the MCP server validates input against the tool schema, which does not set `additionalProperties: false`, and `call_tool` drops arguments an older handler does not take, so an older server ignores `tags_match` and answers with today's OR. Once D178a is deployed (API before MCP server) the same call is an exact AND. Every exact-tag AND uses it: knowledge + domain, discipline tag + seed-version, parking-lot + a named discipline.
>
> **Prefixes are for real tag families only.** Never use an exact tag as a prefix (live data: `sdlc:domain:data` is a prefix of `data-engineering`, `data-modeling` and `data-pipeline`; `process` of `process-improvement`; `infra` of `infrastructure`). Never prefix-match `sdlc:knowledge`: it also matches every `sdlc:knowledge-id:…` tag, so an entry that was demoted by removing `sdlc:knowledge` but kept its `-id` tag would still match. The discipline family prefix has NO colon: `tag_prefixes=["sdlc:discipline"]` matches the bare `sdlc:discipline` tag that `sdlc-port` writes (4 entries in sleeved) and every `sdlc:discipline:<name>` tag; the colon form misses the bare ones. "Any discipline" is therefore `tag_prefixes=["sdlc:discipline"]`.
>
> **Knowledge OR discipline cannot be one call.** `tags=["sdlc:knowledge"]` is an exact match and the discipline family is a prefix; a single call would AND them (`tags` with `tag_prefixes`) or need a prefix on `sdlc:knowledge`. Emit two calls (`memory_search(query="[X]", tags=["sdlc:knowledge"])` and `memory_search(query="[X]", tag_prefixes=["sdlc:discipline"])`) and let the reader merge the results.
>
> **Agent tags are not emitted by default.** The rules never add `sdlc:agent:<a>` to a search: no entry in the observed workspace carries one, so `tags=["sdlc:knowledge", "sdlc:agent:<a>"], tags_match="all"` returns zero results where the agent-less search returns the relevant entries. The agent name goes in the query. A project that has wired agent tags through `sdlc-ingest` (which applies `sdlc:agent:<a>` to the same entry as `sdlc:knowledge`) keeps them: the transformer checks live (`memory_get_index(tags=["sdlc:agent:<a>"], limit=1)`) before it drops one, per the legacy-repair row.
>
> Notation such as `sdlc:discipline:<name>` or `sdlc:domain:<name>` in PROSE is shorthand for "a tag of that family"; never copy a `*` into a `tags=[...]` or `tag_prefixes=[...]` argument. (A `{name}` placeholder is legitimate only inside a `memory_store` tag template that the caller fills in; `memory_store` applies every listed tag, so there the list is an AND by nature.)

**Match rules:**
1. **Case-insensitive on the leading verb, regardless of sentence position.** A rule `Read [sdlc-root]/disciplines/*.md and find [X]` matches both sentence-start `Read [sdlc-root]/disciplines/*.md and find...` and mid-sentence `..., read [sdlc-root]/disciplines/*.md and find...`. The verb (`Read`/`Consult`/`Append`/`Update`/`Look up`/etc.) is the anchor, not the sentence start. When substituting, preserve the original case of the verb only if the substitution keeps a verb at that position; otherwise the replacement's casing wins.
2. Patterns must match as a full phrase within a sentence.
3. **Inline backticks around paths are markdown formatting — match THROUGH them.** A rule `Append to [sdlc-root]/disciplines/*.md` matches `Append to \`[sdlc-root]/disciplines/*.md\`` (with inline backticks) and vice versa. Strip inline backticks before matching.
4. Only skip matching inside **fenced code blocks** (triple backticks ```` ``` ````) — those are literal code examples, not instructions.
5. When the rule pattern contains `<domain>` or `{name}` or `[agent-name]`, treat as a wildcard that captures the substring at that position. **The wildcard matches ANY value at that position, including other angle-bracket-looking placeholders in the source.** The captured string (placeholder and all) is inserted into the replacement. Do NOT require the captured value to be a "real" domain name — the rule's job is structural transformation, not semantic validation.

   **A capture never takes a glob (`*`) as its value, and a `{name}` placeholder is never filled from one.** `<name>`, `<domain>` and `{name}` capture a NAME. `*.md` is a glob across names, not a name: `Read [sdlc-root]/disciplines/*.md` must reach the glob row (`tag_prefixes=["sdlc:discipline"]`), never the `<name>` row with `<name>` = `*`, which would emit a tag ending in `*`. Rows whose pattern contains a glob are listed BEFORE the rows that capture a name, and the first match wins. The same holds for the Integration carve-out's write-targets row: its `{name}` stays a literal placeholder for the caller.

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

10. **Never flatten domain-specific queries into generic ones.** Existing `memory_search()` calls with specific tags (`sdlc:domain:<name>`, `sdlc:discipline:<name>`) are already in their final form. Pattern Mapping defines what to PRODUCE from file-mode input — not how to rewrite existing MCP calls. If tags get shorter or less specific after transformation, flag as precision loss and halt.

    **Wrong:** `tags=["sdlc:knowledge", "sdlc:domain:testing"], tags_match="all"` → `tags=["sdlc:knowledge"]` (lost domain scope: the call now returns every knowledge entry)
    **Correct:** existing MCP call with domain tags → preserve verbatim

    **Exception — legacy-repair rows (§ "Legacy repair" below).** They rewrite a call that was never correct (a `*` inside a tag argument; a knowledge + domain pair that is an OR and so scoped nothing). The repaired call is MORE specific than the original, not less, so this rule does not apply to it. Rule 10 still forbids every other rewrite of an existing call.

11. **Multi-step conditional logic survives transformation intact.** Pattern Mapping fires on individual PHRASES within algorithmic blocks (if/then/else, numbered conditional steps) but must NOT restructure the surrounding algorithm. If a section has 4 conditional steps pre-transform, it must have 4 post-transform — only the MCP call syntax within each step changes.

    **Wrong:** 4-step conditional (check tags → fallback → filter → always-include) → collapsed to 3-step unconditional
    **Correct:** each step's `memory_search()` syntax is transformed but the branching structure and step count are preserved

12. **Sentence punctuation after a path does not stop a rule from matching.** A rule whose pattern ends at a path (`…/<file>.yaml`, `…/disciplines/<name>.md`, `…/agent-context-map.yaml`) also matches when the path is followed by `.`, `,`, `;`, `:` or `)`, whether or not the path sits in inline backticks (rule 3). The trailing punctuation and everything after it are preserved after the replacement. Rule 6's "terminate at `.`" applies to wildcard CAPTURES (`<file>` stops before `.yaml`); it does not shorten the rule's literal text. A rule that fires on `Read X.yaml and apply it` must also fire on `Read X.yaml. It is the rule.`

    **Worked example (sleeved, 2026-10-29 — the line the hand-run missed):**
    - Input: `Read [sdlc-root]/knowledge/coding/comment-discipline.yaml. It is the rule. Follow all of it.`
    - Rule: `Read [sdlc-root]/knowledge/<domain>/<file>.yaml` (wildcard table) with `<domain>` = `coding`, `<file>` = `comment-discipline`
    - Output: `Call memory_search(query="comment discipline", tags=["sdlc:knowledge", "sdlc:domain:coding"], tags_match="all"). It is the rule. Follow all of it.`

13. **Escape sequences are literal text.** A backslash followed by `n` (likewise `t`, `r`, `\"` and `\\`) inside a quoted string or a fenced block is two characters of content, never a control character. The transformer reads and writes it as it stands: it does not expand `\n` into a real newline, does not "unescape" or re-wrap a string, and no row's replacement contains one. This holds for every quoted string: graphviz node labels, JSON and YAML examples, message-envelope payloads, shell strings. Match rule 4 already forbids matching inside fences and rules do not match inside quoted strings, so the failure is in the WRITE step: a model that copies a line "faithfully" can still turn `\n` into a line break.

    **Worked examples (sleeved, found by the z-sdlc adapter audit 2026-10-29; both pre-dated the v2.2.0 migration):**
    - Upstream `"0. Identify test targets\nand verify services" [shape=box];` in `sdlc-tests-run` was written as two lines, which breaks the graphviz label.
    - Upstream `description: "File: src/components/GalleryCarousel.tsx:42\nCategory: correctness\n[full description with evidence]",` in `process/team-communication-protocol.md` was written as three lines.

    **Post-write assertion:** count the two-character sequence backslash-`n` in the written file and in a baseline, and compare region by region. A **preserved region** is either a `PROJECT-SECTION` / `BUNDLE-SECTION` block or a section the Step 2b MCP preservation gate kept (the sections it extracted from the project's version because they hold MCP calls no Pattern Mapping row produces, and merged back by heading in step 3c). The baseline for everything OUTSIDE a preserved region is the upstream file at the version being installed: strip the preserved regions from the written file, and its count must not be lower than upstream's. The baseline for the INSIDE of each preserved region is the project's merged (pre-transform) version of that block or section, whose count the written region must not fall below. Upstream is the wrong baseline inside a region: project-authored text has no upstream counterpart, and a Step 2b section is paired with its upstream namesake only by a heading match, so that namesake can hold more backslash-`n` sequences than the project's section, and restoring upstream's bytes over it would silently overwrite content the preservation gate deliberately kept. The merged version is the wrong baseline outside a region (a project that already expanded a string would pass its own damage). No row emits one, so a drop means a string was expanded.

    **Action on a drop: restore, do not halt.** Put the lines back from the region's baseline, byte for byte (re-applying a Pass 1 or Pass 2 row to the same line only if one matched it, with the `\n` kept literal), re-count, and log a `warning` event with `category: "escape_restored"`, the file and the line range. Restore, because the baseline holds the exact bytes, so the repair is mechanical and needs no judgment; halting would stop every remaining file in the run over a defect the transformer can fix itself. The log event keeps it visible, and the post-operation audit lists `escape_restored` warnings in its report.

| z-sdlc Generic Pattern | Neuroloom Pattern (preserve if present) |
|-------------------------|----------------------------------------|
| `consult [sdlc-root]/knowledge/agent-context-map.yaml` | `memory_search(query="[agent-name] domain-specific patterns", tags=["sdlc:knowledge"])` |
| `Consult [sdlc-root]/knowledge/agent-context-map.yaml for the [agent-name] entry and include relevant knowledge files in the dispatch prompt` | `memory_search(query="[agent-name] domain patterns for cross-domain dispatch", tags=["sdlc:knowledge"]) and include results in the dispatch prompt` |
| `Before starting substantive work, consult [sdlc-root]/knowledge/agent-context-map.yaml and find your entry. Read the mapped knowledge files...` | `Before starting substantive work, call memory_search(query="[agent-name] domain-specific patterns anti-patterns guidance", tags=["sdlc:knowledge"]) to retrieve domain-specific patterns...` |
| `Consult [sdlc-root]/knowledge/agent-context-map.yaml for the agent's mapped files` | `memory_search(query="[agent-name] mapped knowledge", tags=["sdlc:knowledge"])` |
| `Consult [sdlc-root]/knowledge/agent-context-map.yaml for knowledge wiring` | `memory_search(query="agent knowledge wiring", tags=["sdlc:knowledge"])` |
| `Consult [sdlc-root]/knowledge/agent-context-map.yaml to identify agents whose mappings include` | `memory_search(query="agents with mappings in [discipline]", tags=["sdlc:knowledge"])` |
| `Consult [sdlc-root]/knowledge/agent-context-map.yaml for where <X> live(s)` (with or without backticks around the path; `<X>` is a noun phrase such as `the project's standing principles`; fires before the generic `for <purpose>` row below) | `Call memory_search(query="<X-as-topic>", tags=["sdlc:knowledge"]) to find <X>` (`<X-as-topic>` drops the leading article and any possessive: `the project's standing principles` becomes `project standing principles`) — if `<X>` is only a pronoun (`they`, `it`), emit `TRANSFORMATION_WARNING` and leave verbatim: the antecedent cannot be read from the phrase |
| `Consult [sdlc-root]/knowledge/agent-context-map.yaml for <purpose>` (generic `for <purpose>` suffix; fires only when none of the specific `Consult … for …` rows above matches; with or without backticks around the path) | `Call memory_search(query="<purpose-as-topic>", tags=["sdlc:knowledge"]) for <purpose>` |
| `update [sdlc-root]/knowledge/agent-context-map.yaml` (whole-clause match only — see match rule #7; if surrounded by `to <verb>` or `with <object>`, prefer the extended-compound rules below) | `skip this step (Neuroloom uses tag-based wiring via memory_store; no map to update)` — `VERB_PHRASE` class, can slot mid-sentence |
| `Update [sdlc-root]/knowledge/agent-context-map.yaml to add a new entry mapping the agent to relevant knowledge files` | Skip — Neuroloom uses domain-scoped tags (`sdlc:domain:[domain]`) for routing; no map to update |
| `Update [sdlc-root]/knowledge/agent-context-map.yaml to wire newly created knowledge files to relevant agents` | Skip — tag new knowledge with `sdlc:domain:[domain]` via memory_store; agents self-route by domain |
| `Read [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml` | `memory_search(query="agent communication protocol structured progress handoff format", tags=["sdlc:knowledge", "sdlc:domain:architecture"], tags_match="all")` |
| `Read [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml and follow the canonical agent communication protocol it defines` | `memory_search(query="agent communication protocol structured progress handoff format", tags=["sdlc:knowledge", "sdlc:domain:architecture"], tags_match="all") and follow the canonical agent communication protocol it defines` |
| `Read [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml for the handoff schema` | `Call memory_search(query="agent communication protocol handoff schema", tags=["sdlc:knowledge", "sdlc:domain:architecture"], tags_match="all") for the handoff schema` |
| `Read [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml for <purpose>` (generic `for <purpose>` suffix) | `Call memory_search(query="agent communication protocol <purpose>", tags=["sdlc:knowledge", "sdlc:domain:architecture"], tags_match="all") for <purpose>` |
| `Append to [sdlc-root]/disciplines/*.md` | `memory_store(tags=["sdlc:discipline:{name}", "sdlc:parking-lot", "sdlc:deliverable:{id}"])` |
| `Append each insight or GAP entry to the relevant [sdlc-root]/disciplines/*.md parking lot` | `memory_store(tags=["sdlc:discipline:{name}", "sdlc:parking-lot", "sdlc:deliverable:{id}"]) each insight or GAP entry` |
**`sdlc:deliverable:{id}` derivation for discipline entries:** The `{id}` placeholder is the deliverable ID extracted from the entry's context tag at store time. The discipline capture protocol defines four context formats — the orchestrator derives the tag as follows:

| Context format | Tag |
|---|---|
| `[DNN — phase N]` | `sdlc:deliverable:DNN` |
| `[DNN — planning]` | `sdlc:deliverable:DNN` |
| `[idea: {slug}]` | `sdlc:context:idea:{slug}` |
| `[sdlc-design-consult: {slug}]` | `sdlc:context:design-consult:{slug}` |

For idea and design-consult entries, use `sdlc:context:` instead of `sdlc:deliverable:` since these aren't tied to a numbered deliverable. The `sdlc-archive` skill's step 9a can filter by `sdlc:deliverable:{id}` for precise retrieval instead of scanning entry content.

| `look up the agent's mapped files from [sdlc-root]/knowledge/agent-context-map.yaml` | `memory_search(query="{agent-name} domain patterns", tags=["sdlc:knowledge"])` |
| `knowledge stores ([sdlc-root]/knowledge/)` | `Neuroloom knowledge store (via memory_store)` |
| `[sdlc-root]/knowledge/testing/` (as capture target) | `memory_store with tags ["sdlc:knowledge", "sdlc:domain:testing"]` |
| `[sdlc-root]/knowledge/<domain>/` (as capture target) | `memory_store with tags ["sdlc:knowledge", "sdlc:domain:<domain>"]` |
| `Append to [sdlc-root]/knowledge/<domain>/` | `memory_store with tags ["sdlc:knowledge", "sdlc:domain:<domain>"]` |
| `Cross-project knowledge updates append to [sdlc-root]/knowledge/<domain>/` | `Cross-project knowledge updates go to memory_store with tags ["sdlc:knowledge", "sdlc:domain:<domain>"]` |
| `Extract to [sdlc-root]/process/ or [sdlc-root]/knowledge/` (also `Move`/`Put`/`Place`/`Store`/`Write` … `to`/`in`; bare `[sdlc-root]/knowledge/` with no `<domain>`, as a capture target, with or without backticks) | `Extract to [sdlc-root]/process/ or a knowledge memory entry (memory_store with tags ["sdlc:knowledge", "sdlc:domain:<domain>"])` — the `[sdlc-root]/process/` half stays byte-verbatim; `<domain>` stays a literal placeholder because the source names none |
| `[sdlc-root]/knowledge/provenance_log.md` (any phrasing: read it, append to it, "logged to" it, name it in an Integration list) | **Transformed** — CD decided (2026-10-29) that provenance lives as Neuroloom memories tagged `sdlc:provenance`, not as a file. See § "Provenance records" below for the record shape and the rows. |
| `Read [sdlc-root]/knowledge/provenance_log.md` | `Call memory_get_index(tags=["sdlc:provenance"], limit=500)` — see § "Provenance records" for the three purposes of the read (next id, select records, staleness dates) |
| `[sdlc-root]/knowledge/compliance-methodology.md` | `Neuroloom compliance methodology (memory_search with sdlc:knowledge, sdlc:methodology:compliance tags)` |
| `Read [sdlc-root]/knowledge/compliance-methodology.md for the full methodology` | `memory_search(query="SDLC compliance audit methodology", tags=["sdlc:knowledge"]) for the full methodology` |

**Wildcard rules (apply to any matching path not already covered by a specific rule above). Glob rows come first and the first match wins (match rule 5: a name capture never takes a glob). The leading verb may be `Read`, `read`, `Consult` or `consult`; the rows show `Read`.**

| z-sdlc Wildcard Pattern | Neuroloom Replacement |
|--------------------------|------------------------|
| `Read [sdlc-root]/disciplines/*.md` (glob across all disciplines) | `memory_search(query="discipline entries", tag_prefixes=["sdlc:discipline"])` |
| `Read [sdlc-root]/disciplines/*.md and find [X]` | `memory_search(query="[X]", tag_prefixes=["sdlc:discipline"])` |
| `Read each [sdlc-root]/disciplines/*.md parking lot` (glob; `parking lot` here is the file's section) | `Call memory_search(query="discipline parking lot entries", tags=["sdlc:parking-lot"], tag_prefixes=["sdlc:discipline"]) and read each discipline memory entry it returns` |
| `read [sdlc-root]/disciplines/*.md and find parking lot entries tagged with <tag-expr>` (mid-sentence verb) | Two cases. **(a) `<tag-expr>` names a deliverable** (a concrete ID such as `D05`, a placeholder such as `{id}`, or the words "the deliverable ID"): `memory_search(query="parking lot entries tagged <tag-expr>", tags=["sdlc:deliverable:<ID>"], tag_prefixes=["sdlc:discipline"])` for the exact pass, then `memory_search(query="parking lot entries tagged <tag-expr>", tags=["sdlc:parking-lot"], tag_prefixes=["sdlc:discipline"])` for entries written before the deliverable tag existed, and the sentence `keep only the entries whose context tag names <ID>` after the second call. **(b) otherwise:** `memory_search(query="parking lot entries tagged <tag-expr>", tags=["sdlc:parking-lot"], tag_prefixes=["sdlc:discipline"])` followed by `then keep only the entries that match <tag-expr>`. In both cases the filtering sentence is part of the OUTPUT text, not a note to the transformer. `tags` and `tag_prefixes` are ANDed, which is the intent. Never put `sdlc:deliverable:<ID>` into the same `tags` list as `sdlc:parking-lot` unless the call also sets `tags_match="all"`: without it that list is an OR and returns every entry carrying either tag |
| `scan [sdlc-root]/disciplines/ for [X]` / `scan [sdlc-root]/disciplines/*.md for [X]` | `memory_search(query="[X]", tag_prefixes=["sdlc:discipline"])` |
| `grep [X] across [sdlc-root]/disciplines/*.md` / `Grep the entry's key across [sdlc-root]/disciplines/*.md` (also `search`, `look through`) | `call memory_search(query="[X]", tag_prefixes=["sdlc:discipline"])` |
| `Search [sdlc-root]/knowledge/ YAML files for [X]` / `scan [sdlc-root]/knowledge/ for [X]` (glob across all knowledge) | `Call memory_search(query="[X]", tags=["sdlc:knowledge"])` |
| `Read relevant files under [sdlc-root]/knowledge/ and [sdlc-root]/disciplines/ for [X]` | `memory_search(query="[X]", tags=["sdlc:knowledge"])` and `memory_search(query="[X]", tag_prefixes=["sdlc:discipline"])` — two calls, results merged by the reader. One call cannot hold both: `tags` with `tag_prefixes` would demand BOTH families, and prefix-matching `sdlc:knowledge` also matches every `sdlc:knowledge-id:…` tag |
| `Read each [sdlc-root]/knowledge/**/*.yaml that the project has customized (use \`git diff HEAD -- [sdlc-root]/knowledge/\` to identify project-modified files)` (glob) | `Call memory_get_index(tags=["sdlc:knowledge"], limit=500)` for every knowledge entry (K) and `memory_get_index(tags=["sdlc:knowledge", "sdlc:seed"], limit=500)` for the seeded ones (S); the entries the project added or ingested are K minus S, matched on `id`, and are read with `memory_get_detail`. `memory_get_index` is a hard filter with `tags` as an AND and no relevance gate, so a search's top-N cannot miss an entry. Document ingestion never adds `sdlc:seed` (only the server's seed path does), so project knowledge ingested through `sdlc-ingest` is in K minus S, and it shares the `sdlc_knowledge` memory type with seeds, which is why the filter is NOT on `memory_type`. The tool takes `limit` (the API caps it at 500) and no offset, so raise `limit` rather than page, and treat a `count` equal to `limit` as truncated. The index rows carry no tags, hence the set difference. An edited seeded entry stays in S and is not found. Do not search `sdlc:project-specific`: nothing sets that tag unless a person does |
| `Read [sdlc-root]/disciplines/README.md` (the discipline list) | `Call memory_search(query="discipline list", tag_prefixes=["sdlc:discipline"])` |
| `[sdlc-root]/disciplines/README.md § "Creating a New Discipline"` (criteria) | `memory_search(query="creating a new discipline criteria", tag_prefixes=["sdlc:discipline"])` |
| `Read [sdlc-root]/knowledge/<domain>/<file>.yaml` (also when the path is followed by sentence punctuation — match rule 12) | `memory_search(query="<file-name-as-topic>", tags=["sdlc:knowledge", "sdlc:domain:<domain>"], tags_match="all")` |
| `Read [sdlc-root]/knowledge/<domain>/<file>.yaml and <verb> [rest]` | `memory_search(query="<file-name-as-topic>", tags=["sdlc:knowledge", "sdlc:domain:<domain>"], tags_match="all") and <verb> [rest]` |
| `Read [sdlc-root]/disciplines/<name>.md` (a NAMED discipline, never a glob) | `memory_search(query="<name> discipline entries", tag_prefixes=["sdlc:discipline"])`. The name goes in the query, not in a tag: entries ported by `sdlc-port` carry only the bare `sdlc:discipline` tag, and `sdlc:discipline:<name>` would miss them |
| `Read [sdlc-root]/disciplines/<name>.md and find [X]` | `memory_search(query="[X] <name> discipline", tag_prefixes=["sdlc:discipline"])` |
| `read [sdlc-root]/disciplines/<name>.md and <verb> [rest]` (e.g. `and verify:`) | `call memory_search(query="<name> discipline entries", tag_prefixes=["sdlc:discipline"]) and <verb> [rest]` |
| `Read relevant methodology files in [sdlc-root]/knowledge/` | `memory_search(query="methodology [context]", tags=["sdlc:knowledge"])` |
| `Read [sdlc-root]/knowledge/architecture/` or `[sdlc-root]/knowledge/testing/` YAML files and follow their general pattern | `memory_search(query="knowledge YAML pattern", tags=["sdlc:knowledge", "sdlc:domain:architecture"], tags_match="all")` and `memory_search(query="knowledge YAML pattern", tags=["sdlc:knowledge", "sdlc:domain:testing"], tags_match="all")`, then follow the pattern — one call per domain, because `tags_match="all"` cannot say "knowledge AND (architecture OR testing)" |
| `Read [sdlc-root]/knowledge/README.md § "<section>"` | `memory_search(query="knowledge layer <section>", tags=["sdlc:knowledge"])` |
| Validation-checklist items that test whether an agent file wires the knowledge layer: `<Section> section referencing [sdlc-root]/knowledge/agent-context-map.yaml`; `<Section> section referencing [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml`; `Agent has an entry in [sdlc-root]/knowledge/agent-context-map.yaml`; `At minimum [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml is mapped` | `<Section> section containing a domain-scoped memory_search call`; `<Section> section containing the agent communication protocol memory_search call`; `Agent's Knowledge Context makes a domain-scoped memory_search call`; `At minimum the agent communication protocol query is present`. These tests exist in file mode only because the map is a file; the Neuroloom equivalent is the call |
| **Canonical-form checklist items** (the POSITIVE items under `**Canonical forms:**` in the framework reviewer; they state the form the reviewer enforces, so they are rewritten, not exempt): `- [ ] Lookups use \`consult [sdlc-root]/knowledge/agent-context-map.yaml\``; `- [ ] Wiring instructions use \`update [sdlc-root]/knowledge/agent-context-map.yaml\``; `- [ ] Communication protocol references use \`Read [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml\``; `- [ ] Parking lot captures use \`Append to [sdlc-root]/disciplines/*.md\`` | `- [ ] Agent self-lookup at session start uses \`memory_search(query="[agent-name] domain-specific patterns and conventions", tags=["sdlc:knowledge"])\``; `- [ ] Domain-scoped lookups tag \`sdlc:domain:{domain}\` matching the role-to-domain mapping in \`[sdlc-root]/process/knowledge-routing.md\` § Quick Reference`; `- [ ] Communication protocol references use \`memory_search(query="agent communication protocol handoff format progress updates", tags=["sdlc:knowledge", "sdlc:domain:architecture"], tags_match="all")\``; `- [ ] Parking lot captures use \`memory_store(tags=["sdlc:discipline:{name}", "sdlc:parking-lot"])\``. The advice parenthetical on a `- [ ] No \`…\`` item (`(use \`consult\` or \`update\`)`, `(use \`from\` or \`Consult ... for\`)`) becomes `(use \`memory_search\` or \`memory_store\`)` |
| `Verify <X> references [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml` (a check on agent files; `<X>` = `Communication Protocol` or similar) | `Verify <X> calls memory_search(query="agent communication protocol structured progress handoff format", tags=["sdlc:knowledge", "sdlc:domain:architecture"], tags_match="all")` |
| Evidence/citation parenthetical `[sdlc-root]/knowledge/<domain>/<file>.yaml, <section>` | `memory graph reference: sdlc:knowledge + sdlc:domain:<domain>, <section>` |
| A structure check that sits under a transformed read and asserts file structure: `<!-- PROJECT-TRACKER-START -->` / `<!-- PROJECT-TRACKER-END -->` markers are present; `spot-check N discipline files` | `markers: N/A under neuroloom_backend (a memory entry carries no file markers)` and `spot-check N discipline memory entries`; the bullets that check CONTENT (the project's levels, the tracker table) are rewritten from `file`/`between markers` to `entry`. Pass 2's `discipline files` rule applies to this prose as it does to every other skill; `sdlc-migrate` is not exempt from it |

**Verb note for the wildcard table:** a row that consumes the leading `Read` / `scan` verb emits `Call memory_search(...)` (or `call` mid-sentence) — match rule 7: a verb phrase in, a verb phrase out. The table shows the call alone. `Read X.yaml. It is the rule.` becomes `Call memory_search(...). It is the rule.`, never a sentence that starts with a bare call or with `Read memory_search`.

**Provenance records (CD decision, 2026-10-29, plugin 0.5.7).** In a Neuroloom project provenance is not a file. `[sdlc-root]/knowledge/provenance_log.md` is not created and not read; each record its entries carried is one memory tagged `sdlc:provenance`. This replaces the earlier "No transformation" rows, which kept the file on disk.

**Record shape.** Store one memory per entry:

```
memory_store(title="<prov-id>: <short description>",
             content=<the entry's fields, one `key: value` line each>,
             tags=["sdlc:provenance", "sdlc:source-type:<type>", "sdlc:prov:<prov-id>", "sdlc:prov-status:<status>"],
             memory_type="general")
```

- **ids:** the existing formats stay: `prov-YYYY-MM-DD-NNN` for ingest and research, `audit-sweep-YYYY-MM-DD-NNN` for Deep Verify sweeps. The id is also the `sdlc:prov:<id>` tag, so one exact tag finds one record.
- **Status is a tag as well as a line.** `sdlc:prov-status:<status>` (`pending-review`, `approved-for-ingest`, `ingested`, `rejected`) lets the skills select records exactly, so they do not read every record to find the approved ones. The `status:` line in the narrative stays (it is the record's own text); the tag is what selection uses. A sweep record has no status (it is an event, not a handoff) and carries no status tag.
- **`content=`, not `narrative=`.** `memory_store` takes `content`; the stored field is called the narrative, and `memory_update` takes `narrative=`.
- **`memory_type="general"`.** It is one of the 7 types a caller may write. `sdlc_knowledge` and `wiki` are system-only and the API rejects them from `memory_store`, so a provenance record must not use either.
- **Fields** (the old entry format): `id`, `status`, `source-type` (`reference-doc`, `file`, `directory`, `url`, `manual`, `audit-sweep`), `source`, `source-url`, `discipline`, `files-created`, `files-updated`, `rule-count`, `ingested-by`, `notes`; the conditional ones only when `status: ingested`. A sweep record opens with `source-type:`, `sweep-id:`, `date:` and `scope:` lines, then the judge configuration and the counts, and adds the tag `sdlc:sweep:<sweep-id>` that the demotion machinery already uses. The one sweep record written before this decision (2026-07-16) carries `sdlc:sweep:` but no `sdlc:prov:` tag; find sweeps by `sdlc:source-type:audit-sweep`.
- **Order:** none. The file kept newest-first; a memory store has no order to keep.

**Next id.** `memory_get_index(tags=["sdlc:provenance"], limit=500)`. The index rows carry titles but no tags. Take the highest `prov-<today>-NNN` at the start of a title (for a sweep, `audit-sweep-<today>-NNN` anywhere in a title), add 1, and use `001` when there is none. **If `count` equals 500 the list is truncated: do not guess an id; say so and ask CD to choose it.** Several records in one run (`sdlc-research` stores one per researched source) take consecutive ids, the next id, then +1, +2 and so on, and the duplicate check below runs per record. A sweep id is different: allocate it ONCE at the start of the sweep, before anything uses it (the demotion journals and the "Demotion Record" text write it down), and run the duplicate check then; see the sweep rows.

**Lookup and selection.** `memory_get_index(tags=["sdlc:prov:<id>"])` for one record by id. To select by status, `tags` is an AND on this tool, so `memory_get_index(tags=["sdlc:provenance", "sdlc:source-type:reference-doc", "sdlc:prov-status:approved-for-ingest"], limit=500)` returns exactly the approved research handoffs, and `memory_get_detail` is called on those rows only. `sdlc:source-type:reference-doc` is in the selection because only `sdlc-research` writes approval handoffs today; a new source type that can be approved must be added to that selection. To search the records by meaning, `memory_search(query="<topic>", tags=["sdlc:provenance"])`. A tag is an exact match, so `sdlc:prov:prov-2026-10-29-001` never matches `…-0011`.

**Status change** (`pending-review` to `approved-for-ingest` to `ingested`, or `rejected` at any point): read the record with `memory_get_detail` for its current tags, then `memory_update(memory_id=<id>, tags=[<the record's full tag list, status tag swapped>], narrative=<the whole record, status line updated>)`. `memory_update` REPLACES `tags` (and the narrative): omit `tags` and the old status tag stays and selection goes on returning the record; send a partial list and the missing tags are gone. Always send every tag and every field.

**Two limits to know before relying on the store.**

1. *The index list is cut by importance, then by age.* `memory_get_index` returns memories ordered by `importance_score` descending, then `created_at` descending, and exposes no ordering and no offset. Records stored with the default importance tie, so past the 500 cap the oldest fall off first; a record whose importance has been lowered since (`memory_rate` feedback, decay) falls off before newer, higher-scored ones. Today's ids are new and normally inside the cap, and the cap is why the next-id step stops at `count == 500` instead of guessing.
2. *Free-tier retention deletes memories by age.* The daily cron `prune_stale_memories` (`api/neuroloom_api/jobs/pruning.py`, 11:00 on the worker's clock) deletes every memory in a workspace whose `created_at` is older than the workspace's `retention_days`: no exemption by memory type, tag or importance, so a provenance record goes the same way as seeded knowledge. It applies to an active workspace with NO active superuser member and NO paid subscription: with no subscription row the window is 30 days, with a subscription row that sets `retention_days` it is that value. It skips a workspace whose subscription row has `retention_days` NULL (paid, unlimited), a workspace with any active superuser member, and inactive workspaces. In an affected workspace a `pending-review` handoff older than the window is gone before anyone approves it. The sleeved workspace's 2026-07-16 sweep record was still present on 2026-10-29 (105 days), which suggests that workspace is exempt; that is an inference from the record, not a check of its subscription.

| Upstream phrasing | Neuroloom replacement |
|---|---|
| `Read [sdlc-root]/knowledge/provenance_log.md to determine the next \`prov-YYYY-MM-DD-NNN\` ID` | `Call memory_get_index(tags=["sdlc:provenance"], limit=500) to determine the next \`prov-YYYY-MM-DD-NNN\` ID: the highest \`prov-<today>-NNN\` at the start of a title plus 1, or 001 when there is none; if count is 500 the list is truncated, so say so and ask CD for the id` |
| `1. Read [sdlc-root]/knowledge/provenance_log.md` (select a record by status, e.g. `approved-for-ingest`) | `1. Call memory_get_index(tags=["sdlc:provenance", "sdlc:source-type:reference-doc", "sdlc:prov-status:approved-for-ingest"], limit=500), then memory_get_detail on those rows only` — the status tag selects exactly; index rows carry titles only. Only `sdlc-research` writes approval handoffs today, so `reference-doc` is the one source type in the selection; a new source type that can be approved needs adding here. The next step, `Filter for entries with status: approved-for-ingest`, stays (match rule 11: a step is not dropped) and becomes `Filter for records with status: approved-for-ingest (the tags already selected them; confirm the status line in each narrative)` |
| `Read [sdlc-root]/knowledge/provenance_log.md for each knowledge file's last ingestion or refresh date` | `Call memory_get_index(tags=["sdlc:provenance"], limit=500) and read each record's date and files-created / files-updated fields with memory_get_detail` (if count is 500 the list is truncated: say so and stop) |
| `read [sdlc-root]/knowledge/provenance_log.md and find entries with matching \`files-created\` or \`files-updated\` paths` (an exhaustive scan: every knowledge entry is matched against every record) | `call memory_get_index(tags=["sdlc:provenance"], limit=500) once, then memory_get_detail on each record once, and build a map from every path in its \`files-created\` / \`files-updated\` fields to that record; match every knowledge entry against the map by its source path or title. If count is 500 the list is truncated: say so and stop rather than report ages from a partial list.` Do NOT emit a per-entry `memory_search` for this: a ranked search returns a top-N by meaning, record narratives carry file paths rather than entry titles, and a match can be missed |
| `Append one entry (or entries) to [sdlc-root]/knowledge/provenance_log.md` (also `Record the ingestion in the provenance log`, `Log the sweep in [sdlc-root]/knowledge/provenance_log.md with \`source-type: audit-sweep\``, `The sweep is logged to [sdlc-root]/knowledge/provenance_log.md with \`source-type: audit-sweep\``) | `Call memory_store(title="<prov-id>: <short description>", content=<the fields>, tags=["sdlc:provenance", "sdlc:source-type:<type>", "sdlc:prov:<prov-id>", "sdlc:prov-status:<status>"], memory_type="general")` once per entry, with consecutive ids when one run stores several (the next id, +1, +2; once per sweep, not per demotion; a sweep has no status tag). **Then, per record,** call `memory_get_index(tags=["sdlc:prov:<prov-id>"])`: one row is expected. If two rows share the id (another session chose it at the same moment), the one with the later `created_at` takes the next free id with `memory_update(memory_id=<its id>, title=<title with the new id>, tags=[<its tags with the new sdlc:prov:<id>>], narrative=<the record with its id line updated>)`. **A sweep is the exception:** its id was allocated and checked at sweep start, so a duplicate at store time means STOP and ask CD; never renumber, because the id is already written into the demotion journals and the demotion records |
| `update that entry's status to \`ingested\` and populate the ingestion fields` (also `update the selected provenance entry's status to \`ingested\``) | `Call memory_get_detail(id=<the record's id>) for its current tags, then memory_update(memory_id=<the record's id>, tags=[<its full tag list, sdlc:prov-status:approved-for-ingest swapped for sdlc:prov-status:ingested>], narrative=<the whole record, status: ingested and the ingestion fields filled>)`. `tags` replaces the list, so a call that sends only the status tag drops `sdlc:provenance` and `sdlc:prov:<id>` |
| `the user approves them to \`approved-for-ingest\`` (the approval step, which upstream does by editing the file) | `the user approves a record by asking for it, and the agent calls memory_get_detail(id=<id>) for its current tags, then memory_update(memory_id=<id>, tags=[<its full tag list, status tag swapped to sdlc:prov-status:approved-for-ingest>], narrative=<the whole record, status: approved-for-ingest>)`; the same call with `sdlc:prov-status:rejected` rejects it. `tags` replaces the list, so a call that sends only the status tag drops `sdlc:provenance` and `sdlc:prov:<id>` |
| `The provenance log (\`[sdlc-root]/knowledge/provenance_log.md\`) is the prepared handoff mechanism` (the concept and its path in one phrase; **listed before the two single rows below, first match wins**, so the line gets ONE parenthetical, not two) | `The provenance records (memories tagged \`sdlc:provenance\`) are the prepared handoff mechanism` |
| `List all knowledge YAML files across [sdlc-root]/knowledge/` (also `List all YAML files under [sdlc-root]/knowledge/ domain directories`; the staleness and orphan scans, which must see EVERY knowledge entry) | `Call memory_get_index(tags=["sdlc:knowledge"], limit=500) to list every knowledge entry. If count is 500 the list is truncated: say so and stop rather than report on a partial list.` Not a ranked `memory_search`: its default limit returns a handful of the best matches, and the scan that follows is only as complete as this list |
| Deep Verify pre-flight: the paragraph ending `Never start judging without CD's confirmation of scope and cost.` | Append: `**Allocate the sweep id now.** Once CD confirms, choose the sweep id S (audit-sweep-YYYY-MM-DD-NNN, from the index of sdlc:source-type:audit-sweep, plus 1, or 001; if count is 500 ask CD) and call memory_get_index(tags=["sdlc:prov:<S>"]): it must return no row. Use this S everywhere that follows; it is written into the demotion journals and the provenance record, so it is never renumbered later.` |
| `(projects can override via [sdlc-root]/knowledge/provenance_log.md header)` (the thresholds clause) | `(a Neuroloom project has no log header to override them in)` |
| `event records (\`provenance_log.md\` itself, ledgers)` (the Deep Verify scoping exclusion) | `event records (provenance records themselves — memories tagged \`sdlc:provenance\` — and ledgers)` |
| `**No provenance entry** for a knowledge file (pre-dates the log)` (the staleness severity list) | `**No provenance entry** for a knowledge entry (pre-dates provenance records)` |
| a bare list item `- provenance_log.md` in an exclusion list | drop the item: there is no such file to exclude |
| `[sdlc-root]/knowledge/provenance_log.md` named in an Integration list (`**Feeds into:**`, `**Uses:**`) | `memories tagged \`sdlc:provenance\`` |
| the concept `provenance log` / `provenance entries` (a live reference to the knowledge-layer log, with no path beside it) | `provenance records (memories tagged \`sdlc:provenance\`)`. NOT inside text about the `github-provenance` bundle or `process/github-checkpoints.md`, whose "provenance" is the GitHub checkpoint convention |
| `sdlc-migrate`: `provenance_log.md` in the list of project-specific files that must never be overwritten (also the `Current exclusions:` list of Step 0) | drop it from the list |
| `sdlc-migrate` table row `**Provenance log** \| knowledge/provenance_log.md \| Never overwrite — project's append-only ingestion/research records` | `**Provenance records** \| memories tagged \`sdlc:provenance\` \| Never touched by a migration: they are memories, not a file` |
| `sdlc-migrate`: `NOT knowledge/provenance_log.md; that's project-specific` after the `knowledge/README.md` copy entry | drop the clause |
| `process/path-mappings.md` row `knowledge/provenance_log.md \| Project's knowledge provenance records — append-only log ...` | `Provenance records \| memories tagged \`sdlc:provenance\` (no file); ...` — the one row of `path-mappings.md` the transformer rewrites; the rest of that file stays byte-verbatim |

**A project ported with an existing on-disk log** (`/sdlc-port`): ingest each `prov-…` entry as a record, with `content=` carrying the entry's fields as written, the status line kept, and the `sdlc:prov-status:<status>` tag set to match it, then remove the file with the other flat knowledge files. There is no script for this; it is a manual step the port skill describes.

**Legacy repair (item 4/8 of the 0.5.7 review; runs BEFORE the preservation gate's step 2b(a); exempt from match rule 10).**

Plugin 0.5.6 and earlier emitted two call shapes that never worked: a `*` inside a `tags` list, and a `sdlc:knowledge` + domain pair that is an OR and so scoped nothing. A project those versions migrated carries them as "existing MCP calls". Rule 10 forbids rewriting them, step 2b(a) keeps them verbatim, and Check 2a halts on the first kind in every later migration. These rows repair them first.

**Where they run:** over every `*.md` under `.claude/skills`, `.claude/agents` and `.claude/sdlc` in the project, NOT only the files upstream wrote (a file upstream left unchanged still carries the old call). Hard-excluded files, `sdlc_changelog.md` and `changelog-archive/*.md` are skipped.

**They are idempotent.** Every row applies only to a call that has NO `tags_match` argument (and, for the `*` rows, only while the `*` is there). A call that already carries `tags_match`, with either value, is correct or deliberate: it is left alone, no `mcp_repaired` event is logged for it, and a deliberate `tags_match="any"` is never overwritten. Running the sweep twice changes nothing the second time.

**What they touch:** search specs only: `memory_search(...)` calls, and `query=…, tags=[…]` specs in tables. Never a `memory_store(...)` / `document_ingest*(...)` call, never a `memory_get_index(...)` call (its `tags` filter is AND by design), and never a `tags` list that contains a `<placeholder>` or `{placeholder}` (a store template: every listed tag is applied, so the list is an AND already). Decide by the nearest call name on the same or the previous four lines.

| Legacy form (search spec) | Repaired form |
|---|---|
| a `tags` list holding only `sdlc:discipline:` + `*` | `tag_prefixes=["sdlc:discipline"]` |
| `sdlc:discipline:` + `*` together with `sdlc:parking-lot` | `tags=["sdlc:parking-lot"], tag_prefixes=["sdlc:discipline"]` |
| `sdlc:knowledge` together with `sdlc:discipline:` + `*` | two calls: `tags=["sdlc:knowledge"]` and `tag_prefixes=["sdlc:discipline"]` (knowledge OR discipline cannot be one call) |
| any other `X*` element (e.g. a domain family) | `TRANSFORMATION_WARNING` and leave it: a prefix of an exact name matches its siblings (`sdlc:domain:data` also matches `data-pipeline`), so there is no safe automatic rewrite. Check 2a keeps halting until a person rewrites it |
| `sdlc:knowledge` together with one other exact tag of ONE kind (`sdlc:domain:<d>` or `sdlc:type:<t>`), in either order, **and no `tags_match` argument on the call** | `tags=["sdlc:knowledge", <the other tag>], tags_match="all"` |
| the same with two or more domain tags (the intent was knowledge AND (A OR B)) and no `tags_match` argument | one call per domain, each `tags=["sdlc:knowledge", "sdlc:domain:<d>"], tags_match="all"` |
| `sdlc:knowledge` together with `sdlc:agent:<a>` (with or without a domain tag) | **Check first, live:** `memory_get_index(tags=["sdlc:agent:<a>"], limit=1)`. **Zero entries** (the usual case): drop `sdlc:agent:<a>`, put the agent's name in the query if it is not already there, then apply the rows above to what is left. **Entries exist** (the project wired agent tags through `sdlc-ingest`): keep the tag, as `tags=["sdlc:knowledge", "sdlc:agent:<a>"], tags_match="all"` (plus the domain tag if there was one). **Cannot check** (no `memory_get_index` tool, API unreachable): emit `TRANSFORMATION_WARNING`, name the call, and drop the tag, because a silent zero-result search is worse than a broader one. Check once per distinct `<a>`, not once per call |
| tags of mixed families that match none of the rows above (e.g. `sdlc:knowledge` + `sdlc:domain:<d>` + `sdlc:type:<t>` + `sdlc:agent:<a>`, or a `sdlc:deliverable:<id>` next to `sdlc:knowledge`) | `TRANSFORMATION_WARNING` and leave it |

**Bare `sdlc:discipline` as the only tag** (`tags=["sdlc:discipline"]`) is also repaired, to `tag_prefixes=["sdlc:discipline"]`: the exact bare tag matches only the entries `sdlc-port` wrote (4 in the observed workspace), and the family prefix matches those and every `sdlc:discipline:<name>` entry. `["sdlc:discipline", "sdlc:parking-lot"]` is repaired the same way, to `tag_prefixes=["sdlc:discipline"]`: as an OR it matches the bare-tag entries plus every parking-lot entry and misses the `sdlc:discipline:<name>` framework entries, and a parking-lot entry always carries a discipline tag, so the family covers both kinds.

**Logging:** one `mcp_repaired` event per repaired call (`file`, `line`, `before`, `after`), and the file's `file_merged` subtype is `mcp_repaired`. The MCP count of the file does not change, so the retention gates are unaffected.

**Audit-description metadata (prose references in audit dimensions, compliance criteria, analysis descriptions):**

| z-sdlc Audit-Description Pattern | Neuroloom Replacement |
|-----------------------------------|-----------------------|
| `Any YAML file in [sdlc-root]/knowledge/` | `Any memory entry tagged sdlc:knowledge` |
| `files in [sdlc-root]/knowledge/` | `memory entries tagged sdlc:knowledge` |
| `listed in [sdlc-root]/knowledge/agent-context-map.yaml` | `discoverable via domain-scoped memory_search (sdlc:domain:<name> tags)` |
| `[sdlc-root]/knowledge/<discipline>/ directory` | `sdlc:knowledge + sdlc:domain:<discipline> memory entries` |
| `entries in [sdlc-root]/disciplines/` | `entries tagged sdlc:discipline:<name>` |
| `patterns that should be in [sdlc-root]/knowledge/ or [sdlc-root]/disciplines/` | `patterns that should be in the memory graph (sdlc:knowledge / sdlc:discipline:<name> tags)` |
| `no corresponding [sdlc-root]/knowledge/<discipline>/ directory` | `no corresponding sdlc:knowledge + sdlc:domain:<discipline> memory entries` |
| `YAML files under [sdlc-root]/knowledge/` | `memory entries tagged sdlc:knowledge` |
| `in [sdlc-root]/knowledge/` or `in [sdlc-root]/disciplines/` (prose, non-instruction) | `in the Neuroloom memory graph (sdlc:knowledge / sdlc:discipline:<name> tags)` |
| a markdown link whose target is the map: `A map ([\`knowledge/agent-context-map.yaml\`](knowledge/agent-context-map.yaml)) names the structured YAML knowledge files each agent role should read before it works` (the link has no `[sdlc-root]/` prefix, and the target does not exist in a Neuroloom project) | `Domain tags (\`sdlc:domain:<name>\`) route the knowledge memory entries each agent role should read before it works` — drop the link, keep the sentence's meaning; the concept-terminology rows handle the nouns |
| an install-layout table cell that is exactly `knowledge/` or `disciplines/` (a directory listing, not a path to read): `\| \`knowledge/\` \| Structured YAML knowledge stores and the agent-to-knowledge map \|` and `\| \`disciplines/\` \| Discipline parking lots for capturing insights \|` | `\| memory entries tagged \`sdlc:knowledge\` \| Structured knowledge memory entries; domain tags route them to agents \|` and `\| memory entries tagged \`sdlc:discipline:<name>\` \| Discipline memory entries for capturing insights \|` — the directories do not exist, so the rows describe where the same content lives |
| a markdown link whose target is a relative `disciplines/…` or `knowledge/…` path with no `[sdlc-root]/` prefix (the file does not exist in a Neuroloom project): `([\`disciplines/README.md\`](disciplines/README.md))` | `(see the discipline memory entries tagged \`sdlc:discipline:<name>\`)` — for a `knowledge/…` target, `(see the knowledge memory entries tagged \`sdlc:knowledge\`)`; drop the link, keep the sentence's meaning |
| a markdown link or table cell pointing at `bundles/README.md` when the installed tree has no `bundles/` directory (check `test -d`, because the transformer cannot know which projects installed the sources): `See [\`bundles/README.md\`](bundles/README.md) for what each one does, how bundles are installed and kept up to date, and how they share a project.` and `\| \`bundles/\` \| Opt-in bundle sources ([overview](bundles/README.md)) \|` | `The bundle sources are not installed in this project; see \`bundles/README.md\` in the upstream z-sdlc repository for what each one does, how bundles are installed and kept up to date, and how they share a project.` and `\| \`bundles/\` \| Opt-in bundle sources (in the upstream z-sdlc repository; not installed here) \|` — leave the links alone when `bundles/` is installed |
| `<prep> [sdlc-root]/knowledge/<domain>/<file>.yaml` as a prose citation (`<prep>` = per, in, from, of, by, `the rule:`; path with or without backticks; an optional `§ <section>` or `, <section>` stays after it; NOT preceded by `Read`/`Consult`/`Update`/`Append`, which are instruction rows) | `<prep> memory entries tagged sdlc:knowledge + sdlc:domain:<domain>` |
| `follow/apply/use … in/from [sdlc-root]/knowledge/<domain>/<file>.yaml § <section>` (the reader must open that section: `follow the full dispatch template in … § dispatch_prompt_templates`) | `follow/apply/use … from memory_search(query="<file-name-as-topic> <section>", tags=["sdlc:knowledge", "sdlc:domain:<domain>"], tags_match="all")` — the section name goes into the query because a memory entry has no addressable section |
| `[sdlc-root]/knowledge/{domain}/{topic}.yaml` as a placeholder path in a table cell or prose (an authoring template) | `memory entries tagged sdlc:knowledge + sdlc:domain:<domain>`. Never emit `{domain}` into a `memory_search` call |
| `<noun phrase> [exist(s)] at [sdlc-root]/disciplines/` (the verb is optional; also `live(s) at` / `are at` / `are stored at`; path with or without backticks; a precondition or `**Depends on:**` fragment) | `<noun phrase> [exist(s)] (memory graph, entries tagged sdlc:discipline:<name>)` — the preposition and the path collapse into the parenthetical; do not leave `at` dangling |
| `<noun phrase> [exist(s)] at [sdlc-root]/knowledge/<domain>/` (same verb family) | `<noun phrase> [exist(s)] (memory graph, entries tagged sdlc:knowledge and sdlc:domain:<domain>)` |

**Knowledge-layer concept terminology (prose describing the knowledge layer's shape, not its paths):**

Audit-description metadata (table above) handles path-reference prose. This new class handles the **shape-describing terminology** — prose that talks about the knowledge layer using file-based vocabulary ("parking lot entries", "Knowledge YAML files", "agent-context-map.yaml" as a live thing) where no `[sdlc-root]/` path appears. These terms describe *what* knowledge lives in z-sdlc by reference to its storage medium (files). In a Neuroloom install the storage medium is the memory graph, so the vocabulary must be translated even though no path is visible.

Added post-`migrate-fa70ef` audit: the previous audit-description rules fired on `[sdlc-root]/knowledge/<domain>/ directory` and similar path-bearing prose but left untouched pure file-speak like "parking lot entries" that doesn't contain a path. The translation is still needed because these terms leak the file-based architecture into the Neuroloom documentation.

| z-sdlc Concept Terminology | Neuroloom Replacement |
|-----------------------------|------------------------|
| `parking lot entries` (used as a live concept, not describing a procedure specific to file-based mode) | `discipline memory entries` |
| `parking lot entries tagged with <X>` | `discipline memory entries tagged sdlc:discipline:<name> and <X>` |
| `parking lot entry` (singular) | `discipline memory entry` |
| `discipline parking lots` (used as a live concept) | `discipline memory entries` (or just `discipline memories` where plural-noun-phrase is needed) |
| `Knowledge YAML files` / `knowledge YAML files` / `YAML knowledge files` | `memory entries tagged sdlc:knowledge` |
| `knowledge YAML addition (new file or new rules in existing file)` | `knowledge memory addition (new entries or new rules in existing entries)` |
| `knowledge YAML` (bare, as live concept — not describing a file format) | `memory entries tagged sdlc:knowledge` |
| `agent-context-map.yaml` (referenced as a live config file) | `domain-scoped memory search (agents query by sdlc:domain:<name> tags)` |
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

| z-sdlc Contextual Pattern | Neuroloom Replacement | Context |
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

| z-sdlc Example-Table Pattern | Neuroloom Replacement |
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
| `<verb> of [sdlc-root]/disciplines/ files` | `<verb> of memory entries tagged sdlc:discipline:<name>` |
| `<verb> against [sdlc-root]/knowledge/ files` | `<verb> against memory entries tagged sdlc:knowledge` |
| `<verb> across [sdlc-root]/knowledge/ files` | `<verb> across memory entries tagged sdlc:knowledge` |
| `<verb> through [sdlc-root]/knowledge/ files` | `<verb> through memory entries tagged sdlc:knowledge` |
| `<verb> from [sdlc-root]/knowledge/ files` | `<verb> from memory entries tagged sdlc:knowledge` |

**Captured verbs (non-exhaustive):** `reads`, `writes`, `consults`, `lookups`, `references`, `mentions`, `searches`, `queries`, `iterations`, `passes`. The capture is `<verb>` not a literal — match any preceding word followed by `of [sdlc-root]/...` (or `against`, `across`, `through`, `from`).

**Match scope:** verb-of-path rules apply in PROSE contexts only — not inside fenced code blocks, Integration sections, or YAML/JSON structured data. Same exclusions as other Pass 2 rules.

**Bug this prevents:** sleeved `migrate-0957db` left `analysis-methodology.md:66` with `- Explicit reads of [sdlc-root]/knowledge/ files` — the only known instance of the verb-of-path class at the time. The z-sdlc upstream line has been rephrased to canonical form (`Explicit \`Read [sdlc-root]/knowledge/<file>.yaml\` calls`) so the existing Pass 1 wildcard rule fires; this Pass 2 class catches any future verb-of-path constructions that slip through.
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

When a metadata-transformation parenthetical rule fires (e.g., `([sdlc-root]/disciplines/*.md)` → `(memory graph, entries tagged sdlc:discipline:<name>)`), the matcher MUST also scan the immediately-preceding text for a concept-terminology label. If the label is in the concept-terminology table (above), rewrite the label in the same pass. Examples:

- Input: `- **Discipline parking lot entries** (\`[sdlc-root]/disciplines/*.md\`)`
- After parenthetical rule alone (incorrect): `- **Discipline parking lot entries** (memory graph, entries tagged sdlc:discipline:<name>)`
- After combined rule (correct): `- **Discipline memory entries** (memory graph, entries tagged sdlc:discipline:<name>)`

**Why this matters:** Without the combined rule, half-transformed output surfaces in numbered lists and bullet lists where the file-speak label precedes a correctly-Neuroloom-ified parenthetical. The sleeved audit surfaced ~6 such sites in `sdlc-execute.md`, `sdlc-lite-execute.md`, and `compliance-methodology.md`. Single-pass parenthetical rules must look left to find these labels and rewrite them together.

**Scope:** the look-left scan only considers text on the same line, up to the line-start or the previous sentence boundary (`. ` / `! ` / `? `). It does not cross line boundaries or sentence boundaries — labels and their parentheticals are always written as a single logical unit on one line.

**Concept-terminology match notes:**

- These rules apply in PROSE contexts that describe the knowledge layer's **shape** rather than its **paths**. They're distinguished from audit-description rules by the absence of `[sdlc-root]/` in the matched text.
- **Do NOT apply inside:** fenced code blocks, changelog entries, the phrasing contract doc itself. **Integration sections ARE eligible** for concept-terminology (Pass 2) — only Pass 1 path transforms are excluded from Integration sections. Headings that are the literal title of a framework-defined procedure (e.g., `### 9a. Scan Related Parking Lot Entries` as a defined section of the archive skill) are a different case — see below.
- **Headings are a special case.** An H3/H4 heading like `### 9a. Scan Related Parking Lot Entries` names a procedure that z-sdlc defines. In Neuroloom the procedure still exists but operates on memory entries, so rename the heading to `### 9a. Scan Related Discipline Memory Entries` AND adjust the body's procedure text to match. Do NOT transform the heading without transforming the body — that produces a mismatch where the heading says "memory entries" and the body says "files".
- **Procedure-specific steps are a special case.** Content like "Write new YAML files or append to existing ones" is a file-mode procedure. In Neuroloom, the procedure is "call `memory_store(content=..., tags=[...])`" — a completely different mechanism. When you see a numbered step that's a file-mode procedure, the replacement must be the Neuroloom procedure equivalent, not a word-for-word term swap. When no clean equivalent exists (e.g., "update the README.md structure listing"), emit `TRANSFORMATION_WARNING` and consider dropping the step since it's file-mode-only work the adapter doesn't need.
- **Fragments match independently within sentences,** same rule as audit-description. A sentence with multiple concept-terms must have each term transformed separately.

**The bug this prevents:** `migrate-fa70ef` left `improvement-methodology.md:213` with the full sentence: "No markers needed for project-specific files: Knowledge YAML files, discipline parking lot entries, and agent-context-map.yaml are project-owned..." All three concept terms describe the knowledge layer in file terms; none contain a `[sdlc-root]/` path so audit-description rules didn't fire. The new class catches this: `Knowledge YAML files` → `memory entries tagged sdlc:knowledge`; `discipline parking lot entries` → `discipline memory entries`; `agent-context-map.yaml` (live reference) → `the memory graph`. Same class of bug at `improvement-methodology.md:47/80/137–138/196–197`, `sdlc-archive.md:171/173/185`, `sdlc-ingest.md:214–218`, `research-external.md:72/204`.

**Audit-description match notes:**
- **A `<placeholder>` in running prose is backtick-wrapped in the output.** `memory entries tagged sdlc:discipline:<name>` as plain Markdown loses `<name>` when the page is rendered as HTML (it reads as a tag). Write ``memory entries tagged `sdlc:discipline:<name>` ``. Inside a table cell that is already a code span, or inside a `memory_search(...)` call, the placeholder is safe as written.
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

Parenthetical paths and table-cell paths in z-sdlc source describe WHERE something lives in filesystem mode. In Neuroloom, those paths don't exist — the content is in the memory graph. Transform these metadata refs to their Neuroloom-native equivalent so Neuroloom users aren't pointed at non-existent files.

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
| `` - Discipline parking lot entries (`[sdlc-root]/disciplines/*.md`) `` | `- Discipline parking lot entries (memory graph, entries tagged sdlc:discipline:<name>)` |
| `` - Files from the same discipline (e.g., `[sdlc-root]/knowledge/<discipline>/`) `` | `- Files from the same discipline (e.g., memory entries tagged sdlc:knowledge + sdlc:domain:<discipline>)` |
| `` \| Validated, testable rules \| `[sdlc-root]/knowledge/<discipline>/<file>.yaml` \| Specific, testable... \| `` | `\| Validated, testable rules \| memory entries tagged sdlc:knowledge + sdlc:domain:<discipline> \| Specific, testable... \|` |
| `` - Agent knowledge context: `[sdlc-root]/knowledge/agent-context-map.yaml` `` | `- Agent knowledge context: domain-scoped memory search (sdlc:domain:<name> tags)` |
| `### 6a. Discipline Parking Lots (`[sdlc-root]/disciplines/`)` | `### 6a. Discipline Parking Lots (memory graph, entries tagged sdlc:discipline:<name>)` |
| `` Read `[sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml` for the handoff schema. `` | `Call memory_search(query="agent communication protocol handoff schema", tags=["sdlc:knowledge", "sdlc:domain:architecture"], tags_match="all") for the handoff schema.` (NOT `Read memory_store with tags [...]` — that's a capture-target rule leaking into a Read context, see below) |
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
- `query="\* ` (literal asterisk-space at the START of an MCP query string — added post-`migrate-6f4217`. This indicates a glob (`*.md`) was literally injected into a query string instead of being normalized into a tag-prefix filter. Exemplar: `memory_search(query="* discipline", tags=["sdlc:discipline"])` at sleeved `sdlc-execute.md:345/367`. Correct form: `memory_search(query="discipline entries", tag_prefixes=["sdlc:discipline"])` — "any discipline" is a prefix match; a `*` belongs in neither the query nor a tag argument)
- `\btag(s|_prefixes)=\[[^\]]*\*` (a literal `*` inside a `tags=[…]` or `tag_prefixes=[…]` argument — added 2026-10-29. `tags` and `tag_prefixes` do not expand wildcards, so a `*` in either list silently returns zero results; sleeved had it in `sdlc-reflect`, `sdlc-idea` and `sdlc-archive` for a full migration cycle because the rule table itself emitted it. The `*` belongs nowhere in these arguments. Emit `tag_prefixes=["sdlc:discipline"]` for "any discipline"; prose notation uses `sdlc:discipline:<name>`)
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

**Integration sections are structurally exempt from Pass 1, except for knowledge-layer paths — HARD EXCLUSION with one carve-out (changed 2026-10-29, plugin 0.5.7):**

Any line matching `^\s*(- )?\*\*(Uses|Depends on|Updates|Feeds into|Complements|Downstream|Does NOT replace|DRY notes|DRY discipline|Knowledge routing):\*\*` (with or without the leading list bullet) and every bullet/text line following it up to the next blank line, the next `^\s*(- )?\*\*[A-Z]` (a new bold label, bulleted or not), or the next `^#{1,6} ` (heading) is an **Integration section**. The terminator allows the leading bullet because Integration entries are usually list items: with the old bare `^\*\*[A-Z]` a `- **Knowledge routing:**` or `- **DRY discipline:**` bullet was swallowed into the region of the bullet above it. Integration sections are exempt from **Pass 1** transformation:

- No instruction-rule matching
- No metadata-rule matching
- No capture-target-rule matching
- No audit-description rule matching

Integration sections describe logical dependencies between skills/agents/files, not runtime operations. Process, template, playbook, agent and skill paths in them are metadata: leave them verbatim.

**The carve-out — knowledge-layer paths ARE rewritten.** A path under `[sdlc-root]/knowledge/` or `[sdlc-root]/disciplines/` inside an Integration section is rewritten by the table below, and only by it. The original exemption existed to prevent double-paren corruption, not to preserve pointers to files that no longer exist. A `**Uses:** … [sdlc-root]/knowledge/agent-context-map.yaml` line tells a reader to open a file a Neuroloom project does not have; sleeved carried seven such lines (`Uses`, `Depends on` and `DRY notes`, across five skills) through a full migration cycle because this exemption (and the matching exemption in `content-merge-audits.md`'s Contract Residue audit) hid them from every check. Instruction rules (`Read …`, `Consult …`, `Append to …`) still do not fire in Integration sections; list items have no verb. The replacement is spliced in place of the path token, before any role parenthetical that follows it, never inside one (rule-ordering below still applies: a path already inside a parenthetical is handled by the full-parenthetical rows).

| Integration-section token (backticks stripped before matching; a role parenthetical that follows, such as `(the rule)` or `(dispatch template)`, is preserved after the replacement) | Replacement |
|---|---|
| `[sdlc-root]/knowledge/agent-context-map.yaml`, used for agent dispatch or injection (the default reading) | `memory_search(query="[agent-name] domain patterns for cross-domain dispatch", tags=["sdlc:knowledge"])`. When the file's body already carries a call for the same purpose, reuse its query verbatim. Keep the item's own role parenthetical; when it has none, add `(dispatch-time injection)` so the call is not a bare entry in the list |
| `[sdlc-root]/knowledge/agent-context-map.yaml`, used to locate standing principles (the role parenthetical, e.g. `(subject resolution)`, or the surrounding sentence says so) | `memory_search(query="project standing principles", tags=["sdlc:knowledge"])` |
| `[sdlc-root]/knowledge/<domain>/<file>.yaml` | `memory_search(query="<file-name-as-topic>", tags=["sdlc:knowledge", "sdlc:domain:<domain>"], tags_match="all")`. When the file's body already carries a call for that file (e.g. `query="comment discipline"`), reuse its query verbatim |
| `[sdlc-root]/knowledge/<domain>/<file>.yaml` as the subject of a prose clause in an Integration line (`**DRY notes:** the lists live only in …`) | `the <file-name-as-topic> knowledge entry (memory_search(query="<file-name-as-topic>", tags=["sdlc:knowledge", "sdlc:domain:<domain>"], tags_match="all"))`; a later `that file` naming the same path becomes `that entry` |
| `[sdlc-root]/disciplines/*.md` or `[sdlc-root]/disciplines/<name>.md`, bare list item, no stated role | `memory entries tagged sdlc:discipline:<name>` |
| `[sdlc-root]/disciplines/*.md` or `<name>.md` followed by `(write targets)`, `(write target)` or `(append targets)` | `memory_store(tags=["sdlc:discipline:{name}", "sdlc:parking-lot"])`, followed by the same parenthetical |
| `<noun phrase> at [sdlc-root]/disciplines/` after `**Depends on:**` | the `at` rows of the audit-description table |
| `[sdlc-root]/disciplines/<name>.md` for a NAMED discipline (e.g. `design.md`), bare list item | `memory entries tagged sdlc:discipline:<name>` with the real name (`sdlc:discipline:design`) |
| `[sdlc-root]/knowledge/agent-context-map.yaml` followed by the role `(knowledge wiring)` or `(for wiring)` | `memory_search(query="agent knowledge wiring", tags=["sdlc:knowledge"])` followed by the same role parenthetical: Neuroloom wires knowledge to agents by domain tag, so there is no map to name. Every `memory_search` the rules emit carries a `query`; a call with only `tags` is a defect |
| `files under [sdlc-root]/knowledge/<domain>/` (also `all N files under …`) | `memory entries tagged sdlc:knowledge + sdlc:domain:<domain>` (`all 8 files under …` becomes `all 8 memory entries tagged …`) |
| bare `[sdlc-root]/knowledge/` or bare `[sdlc-root]/disciplines/` token, no file name (`… (as extraction targets for shared content)`) | `memory entries tagged sdlc:knowledge` / `memory entries tagged sdlc:discipline:<name>` |
| `[sdlc-root]/knowledge/{domain}/{topic}.yaml` or `[sdlc-root]/knowledge/<domain>/<topic>.yaml` with placeholder names (an authoring template, not a file) | `memory entries tagged sdlc:knowledge + sdlc:domain:<domain>`. Never emit `{domain}` or `{topic}` into a `memory_search` call: a placeholder in a call asks the API for a tag literally named `{domain}` |

**Worked examples (sleeved, 2026-10-29):**

| Input | Output |
|---|---|
| `` - **Uses:** `git log` (session survey); `[sdlc-root]/disciplines/*.md` (write targets); `[sdlc-root]/process/discipline_capture.md` (gap detection) `` | `` - **Uses:** `git log` (session survey); `memory_store(tags=["sdlc:discipline:{name}", "sdlc:parking-lot"])` (write targets); `[sdlc-root]/process/discipline_capture.md` (gap detection) `` — the `process/` path is byte-verbatim |
| `` - **Uses:** `[sdlc-root]/knowledge/coding/comment-discipline.yaml` (the rule), `[sdlc-root]/process/manager-rule.md` `` | `` - **Uses:** `memory_search(query="comment discipline", tags=["sdlc:knowledge", "sdlc:domain:coding"], tags_match="all")` (the rule), `[sdlc-root]/process/manager-rule.md` `` |
| `` - **Uses:** `docs/_index.md`, `[sdlc-root]/disciplines/*.md`, `scripts/changelog_archive.py` `` | `` - **Uses:** `docs/_index.md`, memory entries tagged sdlc:discipline:<name>, `scripts/changelog_archive.py` `` — the replacement is plain prose, so the token's own backticks go with it |
| `` - **DRY discipline:** … `[sdlc-root]/process/{topic}.md` (universal protocols), `[sdlc-root]/knowledge/{domain}/{topic}.yaml` (domain rules), per-skill `references/` `` | `` - **DRY discipline:** … `[sdlc-root]/process/{topic}.md` (universal protocols), memory entries tagged sdlc:knowledge + sdlc:domain:<domain> (domain rules), per-skill `references/` `` |

**Pass 2 concept-terminology IS allowed in Integration sections.** Prose descriptors within Integration bullets — parenthetical explanations, trailing descriptions — use concept terms like "knowledge stores" and "parking lot entries" that describe the knowledge layer's shape. These are prose, not paths, and must be transformed. Example:
- Input: `` **Depends on:** `[sdlc-root]/process/discipline_capture.md` (parking lot entries for knowledge hygiene) ``
- After Pass 2: `` **Depends on:** `[sdlc-root]/process/discipline_capture.md` (discipline memory entries for knowledge hygiene) ``
- The backticked path is untouched (Pass 1 exempt); the parenthetical prose is transformed (Pass 2).

**What Pass 2 MUST NOT touch in Integration sections:**
- Path references (backticked or bare `[sdlc-root]/...` paths) — these are Pass 1's domain
- Backticks around paths — preserve byte-identical
- The `**Label:**` prefix itself

**Enforcement (Pass 1):** The matcher must mask out Integration sections before Pass 1 rule evaluation, then re-admit only the knowledge-layer tokens the carve-out table covers. **Post-write comparison for each Integration line:** strip inline backticks from both the upstream line and the output line, then mask (a) every knowledge-layer token in the upstream line together with the backticks around it, and (b) every carve-out replacement in the output line together with any backticks it carries. The two remaining strings must be byte-identical, except for Pass 2 prose substitutions and the one wording change the audit-description `at` rows make (`at` + path collapses into the parenthetical). Masking the backticks is deliberate: the carve-out table replaces some tokens with plain prose (`memory entries tagged …`) and others with a backticked call, and a comparison that kept the backticks would halt on the plugin's own worked examples. Anything else that differs halts the write, and so does a `memory_search(` / `memory_store(` anywhere outside a masked span.

**Path byte-preservation in Integration sections:** Path references and their surrounding backticks in Integration-section lines must be written out byte-for-byte identical to the upstream source (every path EXCEPT the knowledge-layer tokens the carve-out rewrites; for those the token and its surrounding backticks are the masked span). This includes — and this is the failure mode `migrate-fa70ef` surfaced across 20+ files — **surrounding backticks on path references**. `` **Uses:** `[sdlc-root]/process/manager-rule.md` `` must retain its inline backticks intact. Any incidental side-effect that strips backticks violates the hard exclusion. Pass 2 concept-terminology changes to non-path prose tokens are the ONLY allowed difference.

**Post-write Integration check:** diff Integration-section path references (any token matching `[sdlc-root]/...` or `.claude/...` including surrounding backticks) byte-for-byte against upstream, comparing with inline backticks stripped and skipping the masked knowledge-layer spans described under "Enforcement (Pass 1)". Any other path-character difference halts the write. Non-path prose tokens may differ only if they match a Pass 2 concept-terminology substitution.

**Why hard-gated:** The `migrate-f01a70` run transformed Integration sections in `sdlc-archive.md:230,232`, `sdlc-create-agent.md:219`, `sdlc-ingest.md:398`, `sdlc-tests-create.md:250` — producing double-paren corruption in all four. Listing Integration sections as "informationally exempt" without a structural mask is equivalent to not listing them. The `migrate-fa70ef` run exposed the follow-on: the hard-exclusion mask blocked transformation but didn't block the transformer's ancillary backtick-normalization, which stripped inline backticks from 20+ Integration lines across the repo.

**Non-transformable paths — byte-verbatim preservation (added post-`migrate-fa70ef`):**

The following path prefixes are NEVER touched by the transformer — not for Pattern Mapping transformation, not for audit-description metadata transformation, not for backtick normalization, not for any reason:

- `[sdlc-root]/process/` — process docs live on disk in Neuroloom projects too
- `[sdlc-root]/templates/` — templates live on disk
- `[sdlc-root]/playbooks/` — playbooks live on disk
- `[sdlc-root]/agents/` — agents install to `.claude/agents/`
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

| z-sdlc Metadata Pattern | Neuroloom Metadata Replacement |
|--------------------------|--------------------------------|
| `([sdlc-root]/knowledge/agent-context-map.yaml)` | `(domain-scoped memory search, sdlc:domain:<name> tags)` |
| `([sdlc-root]/knowledge/**/*.yaml)` | `(memory graph, entries tagged sdlc:knowledge)` |
| `([sdlc-root]/knowledge/*.md)` | `(memory graph, entries tagged sdlc:knowledge)` |
| `([sdlc-root]/knowledge/<domain>/*.yaml)` | `(memory graph, entries tagged sdlc:knowledge and sdlc:domain:<domain>)` |
| `([sdlc-root]/knowledge/<domain>/)` | `(memory graph, entries tagged sdlc:knowledge and sdlc:domain:<domain>)` |
| `([sdlc-root]/disciplines/*.md)` | `(memory graph, entries tagged sdlc:discipline:<name>)` |
| `([sdlc-root]/disciplines/<name>.md)` | `(memory graph, entries tagged sdlc:discipline:<name>)` |
| `(e.g., [sdlc-root]/knowledge/<domain>/)` | `(e.g., memory entries tagged sdlc:knowledge + sdlc:domain:<domain>)` |
| `(e.g., [sdlc-root]/knowledge/<domain>/*.yaml)` | `(e.g., memory entries tagged sdlc:knowledge + sdlc:domain:<domain>)` |
| `(e.g., [sdlc-root]/disciplines/<name>.md)` | `(e.g., memory entries tagged sdlc:discipline:<name>)` |
| Bullet label + colon + path: `<Label>: [sdlc-root]/knowledge/agent-context-map.yaml` (e.g., `- Agent knowledge context: [sdlc-root]/knowledge/agent-context-map.yaml`) | `<Label>: domain-scoped memory search (sdlc:domain:<name> tags)` |
| Bullet label + colon + path: `<Label>: [sdlc-root]/knowledge/<domain>/<file>.yaml` | `<Label>: memory entries tagged sdlc:knowledge + sdlc:domain:<domain>` |
| Bullet label + colon + path: `<Label>: [sdlc-root]/disciplines/<name>.md` | `<Label>: memory entries tagged sdlc:discipline:<name>` |
| Table cell containing `[sdlc-root]/knowledge/agent-context-map.yaml` (any column) | Cell becomes `domain-scoped memory search (sdlc:domain:<name> tags)` |
| Table cell containing `[sdlc-root]/knowledge/<domain>/<file>.yaml` (any column) | Cell becomes `memory entries tagged sdlc:knowledge + sdlc:domain:<domain>` |
| Table cell containing `[sdlc-root]/knowledge/<domain>/` (any column, directory ref) | Cell becomes `memory entries tagged sdlc:knowledge + sdlc:domain:<domain>` |
| Table cell containing `[sdlc-root]/knowledge/**/*.yaml` or `[sdlc-root]/knowledge/*.md` (any column) | Cell becomes `memory entries tagged sdlc:knowledge` |
| Table cell containing `[sdlc-root]/disciplines/*.md` or `[sdlc-root]/disciplines/<name>.md` (any column) | Cell becomes `memory entries tagged sdlc:discipline:<name>` |

**Exempt from metadata transformation:**
- `[sdlc-root]/process/` references (process files exist on disk in Neuroloom projects too)
- `[sdlc-root]/templates/` references (templates exist on disk)
- `[sdlc-root]/playbooks/` references (playbooks exist on disk)
- `[sdlc-root]/agents/` references (agents exist at `.claude/agents/` — handled by path transformation, not knowledge transformation)
- Integration-section `**Depends on:**` / `**Uses:**` lists where the ref is an individual bullet rather than a parenthetical, EXCEPT knowledge-layer paths (`[sdlc-root]/knowledge/` and `[sdlc-root]/disciplines/`), which the Integration carve-out table rewrites. Every other path there is kept verbatim as metadata

---

## Pass 2 — Prose Concept-Terminology Scope and Event Schema

**Pass 2 scope — what counts as "prose":**

A region of text is "prose" (and thus subject to concept-terminology transformation) if ALL of these hold:
- It is NOT inside a fenced code block (```` ```...``` ````, any language)
- It is NOT inside inline backticks (`` `...` ``)
- It is NOT a YAML key, YAML value, JSON key, or JSON value (when the surrounding context is structured data, even if outside a fence — e.g., frontmatter fields) — **EXCEPTION:** `description:` values in skill/agent YAML frontmatter ARE prose-eligible, because agents read these descriptions to decide whether to invoke a skill. Terms like "knowledge stores" in a description field must be transformed. Other frontmatter fields (`name:`, `model:`, `tools:`, `allowed_tools:`) remain exempt. **Exception to the exception: the user's own words.** Two kinds of quoted span inside the value stay byte-identical, because rewriting them stops the skill matching what the user types: (a) a quoted phrase in an explicit trigger list, the kind a description introduces with `Triggers on` (the upstream convention, 29 skills) or an equivalent lead-in such as `Use when the user says` or `Trigger phrases:` (upstream `sdlc-audit`: `"verify the knowledge store"`), in a plain or folded/literal-block `description:` or as the escaped quotes of a double-quoted YAML value; (b) the quoted text of a `user: \"…\"` line in an `<example>` block. Every other quoted span in a description is prose and IS transformed: `assistant: \"…\"` lines, the text inside `<commentary>`, and any quoted example that is neither a trigger list nor a `user:` line. The outer quotes of a double-quoted YAML value are delimiters, not a phrase. The prose around the preserved quotes in the same description is still transformed.
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
- A quoted trigger phrase or a `user:` line in a `description:` value: the folded `description: >` block of upstream `sdlc-audit` lists `"verify the knowledge store"` and `"full content sweep"` after `Triggers on`, and keeps both as written. An `assistant: \"…\"` line or `<commentary>` text in the same kind of value is prose and is transformed. Outside any quote in the same value, `already-promoted knowledge-store entries` becomes `already-promoted knowledge memory entries`.

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
- The exempt files list (`process/knowledge-routing.md`, `process/sdlc_changelog.md`, `process/changelog-archive/*.md`, `process/path-mappings.md`) — these contain the canonical phrases as data
- A quoted phrase in a trigger list, or the text of a `user: \"…\"` line, in a skill or agent `description:` value (the user's own words; `assistant:` lines and `<commentary>` are NOT retained; see the Pass 2 scope above)
- A hit directly followed by a `(memory …` parenthetical: the shape of a replacement's own output (`knowledge index (memory entries tagged …)`, `Discipline Parking Lots (memory graph, …)`)
- Checklist items (`- [ ] ...`) in `agents/sdlc-reviewer.md` that quote canonical phrasing as validation criteria — these CHECK other files' compliance, they are not operational instructions themselves
- Project-authored content under `.claude/agent-memory/` (filtered upstream)

**Halt condition:** if non-retention hits exist after Pass 2 wrote a file, EITHER (a) Pass 2 didn't actually run on this file (telemetry assertion will catch this independently) OR (b) the Pass 2 rules have a coverage gap. In both cases the file is in a hybrid-mode state — partial-Neuroloom, partial-file-mode prose — which is the worst output state because it's harder to detect than uniform regression. Halt before declaring `concept_terminology_applied: PASS` for that file; emit `transformation_warning` with the specific phrase, line number, and surrounding context.

**The bug this prevents:** sleeved's `process/deliverable_lifecycle.md:76` post-`migrate-6f4217` had `- Testing knowledge files updated` written to disk despite the Pass 2 rule `knowledge files` → `knowledge memory entries` existing in the table above. Pass 2 didn't fire on this file (along with ~37 sibling sites across sleeved). The user found it manually after the outside-the-run audit also missed it — the audit's path-bearing-residue grep doesn't catch bare forms. This residue scan halts the write before silent regression reaches disk; the audit skill's Scan 3b (z-sdlc `ccsdlc-audit-adapter-installation`) catches anything that still slips through.

**Fenced code blocks containing file-mode demos — deferred to 0.5.0:** Pass 2 intentionally does not modify fenced-block contents, even when those contents are file-mode demos (e.g., a ` ```yaml ` block demonstrating `mappings: ui-ux-designer: [paths]` in an adapter-unreachable format). Surrounding prose is transformed by Pass 2; the demo itself is preserved as z-sdlc's original file-mode reference. Future work (0.5.0) may add an optional pre-fence annotation (e.g., *"In Neuroloom mode, the equivalent operation is `memory_store(..., tags=[...])`."*) as a demonstration-mapping rule class. Until then, fenced-block file-mode demos remain a project-specific customization zone — if your installation wants to replace the demo, wrap the whole fenced block in `PROJECT-SECTION` markers.

**EXCEPTION — Agent template code blocks (added post-v1.5.4 audit):**

Fenced code blocks that serve as **copy-paste templates for new agent content** (not format demos) ARE eligible for transformation. These blocks contain instructions or sections that get literally inserted into new agents — if they reference `[sdlc-root]/knowledge/agent-context-map.yaml`, the created agent will have stale file-mode instructions.

**Identification:** A template code block is eligible if it meets ALL of:
1. It appears inside an agent-creation or agent-modification skill (e.g., `sdlc-develop-agent`)
2. Its content contains `## Knowledge Context` or `## Communication Protocol` headings, OR it's introduced by surrounding prose that says "inject", "insert", "add this section", "template for", or "paste into the agent"
3. It is NOT a ` ```yaml ` or ` ```json ` block showing data format — it's a ` ```markdown ` or unfenced template block showing agent prose

**Transformation:** Apply the same Pass 1 instruction rules that would fire if the content were outside a fence. The template block's `consult [sdlc-root]/knowledge/agent-context-map.yaml` becomes `memory_search(query="[agent-name] domain-specific patterns", tags=["sdlc:knowledge"])`.

**Transaction log:** Log `template_block_transformed` event with the file, block line range, and rules fired. The post-write MCP-in-fenced-block assertion must be updated to EXCLUDE template blocks from the count comparison — these blocks are expected to gain MCP calls.

**Currently known template blocks:**
- `sdlc-develop-agent/SKILL.md` step 3b — Knowledge Context section template
- `sdlc-develop-agent/SKILL.md` step 3c — Communication Protocol section template
- `AGENT_TEMPLATE.md` — the full agent template file

**EXCEPTION — Dispatch-prompt template blocks (added 2026-10-29, plugin 0.5.7):**

A fenced block that holds a **prompt the skill sends to a dispatched agent** is a runtime instruction, not a format demo. The agent that receives it will try to do what it says, so a `Read [sdlc-root]/knowledge/…yaml` inside it points a subagent at a file that does not exist. sleeved's `sdlc-cleanup-comments/references/dispatch-prompts.md` carried two such lines (:13, :61), inside `markdown` fences, through a full migration; the fence exclusion plus the audit's "exempt — fenced code block" class hid both.

**Identification:** a fenced block is a dispatch-prompt template if it meets ALL of:
1. It appears in a skill file (`SKILL.md` or `references/*.md`) or an agent file.
2. It is a ` ```markdown ` or untagged block, and EITHER the file is named `dispatch-prompts.md`, OR the block is introduced by prose containing "prompt" or "dispatch", OR the block contains the dispatch-template headings `**Objective:**` and `**Constraints:**`.
3. It is NOT a block showing a file format or a command: a ` ```yaml `, ` ```json ` or ` ```bash ` block, OR a ` ```markdown ` / untagged block that demonstrates an entry format and meets none of the tests in criterion 2 (e.g. `process/discipline_capture.md`'s "Promoted entry format" block). Those are format demos; they stay verbatim and the audit exempts them (`post-operation-audit.md` Check 2, fenced-block row).

**Transformation:** the same as for agent template blocks: Pass 1 instruction rules fire inside the block (`Read [sdlc-root]/knowledge/coding/comment-discipline.yaml.` becomes `Call memory_search(query="comment discipline", tags=["sdlc:knowledge", "sdlc:domain:coding"], tags_match="all").`). Pass 2 does not run inside the block. Integration-section rules do not apply (a block has none). Log `template_block_transformed` with `kind: "dispatch_prompt"`, and exclude these blocks from the MCP-in-fenced-block count comparison.

**One more row fires inside these blocks, and has no `[sdlc-root]` path:**

| Pattern (inside a dispatch-prompt block) | Replacement |
|---|---|
| `Read {the agent's mapped knowledge files}` (the curly-brace text is the prompt's own placeholder for the agent's mapped knowledge; the trailing `for this codebase's patterns` stays) | `Call memory_search(query="{agent-name} domain-specific patterns and conventions", tags=["sdlc:knowledge"])`. If the prompt names the agent's domain, use the domain AND form instead: `tags=["sdlc:knowledge", "sdlc:domain:<d>"], tags_match="all"`. `{agent-name}` stays a literal placeholder: the orchestrator fills it when it builds the prompt, like every other brace in the template |

The prose that introduces the blocks (`All three follow the full dispatch template in … § dispatch_prompt_templates`) is outside the fence and is covered by the audit-description row "follow/apply/use … in/from … § <section>".

**EXCEPTION — Output-template blocks (added 2026-10-29, plugin 0.5.7).**

A ` ```markdown ` or untagged fence that the skill INSTANTIATES and writes or shows at runtime (a changelog entry, a report, a summary) is an instruction too: the agent fills in its brackets and writes the result into the project's changelog or to the user, so a `[sdlc-root]/knowledge/…yaml` file listed in it as "created" or an agent-context map "wired" reports work a Neuroloom project does not do. **Identification:** all of (1) it is in a skill or process file; (2) the nearest non-blank line before the fence contains `update`, `append`, `write`, `present`, `report`, `output`, `summary` or `display`; (3) the block holds `[bracketed placeholders]` (`[count]`, `[date]`, `[name]`). Pass 1 fires inside it, with these rows:

| Pattern (inside an output-template block) | Replacement |
|---|---|
| `**\`[sdlc-root]/knowledge/[discipline]/[file].yaml\`** — [created/updated] with [count] new rules ([ID range])` | `**Knowledge memory entries (sdlc:knowledge + sdlc:domain:[discipline])** — [created/updated] with [count] new rules ([ID range])` |
| `**\`[sdlc-root]/knowledge/agent-context-map.yaml\`** — wired [count] files to [list of agents]` | `**Domain-tag wiring** — tagged [count] entries with sdlc:domain:[discipline]; [list of agents] find them by domain tag`. If the project wires agents with `sdlc:agent:<name>` tags (`sdlc-ingest` step 6.3 does), say `tagged [count] entries with sdlc:agent:<name> for [list of agents]` instead |
| `**\`[sdlc-root]/disciplines/[name].md\`** — [count] new parking lot entries added` | `**Discipline memory entries (sdlc:discipline:[name])** — [count] new parking lot memory entries added` |
| `**\`[sdlc-root]/knowledge/[discipline]/README.md\`** — updated structure listing` | `Tag-based indexing is automatic — no separate index update needed` (the list number is dropped from the sequence's meaning, not renumbered) |

One more row fires in audit-report templates of this kind: the concept-table row `Suggested knowledge area: [sdlc-root]/knowledge/<domain>/` → `Suggested domain tag: sdlc:domain:<domain>` (`skills/sdlc-audit/references/compliance-methodology.md`, the promotion cluster template). Log `template_block_transformed` with `kind: "output_template"`. A block that only demonstrates a format (`process/discipline_capture.md`'s "Promoted entry format": intro line names a format, no verb from criterion 2) is not an output template and stays verbatim.

**Currently known blocks:** `sdlc-ingest/SKILL.md` step 9 (the changelog entry); `sdlc-cleanup-comments/references/dispatch-prompts.md` (trimmer, check and fix prompts; carries the comment-discipline `Read` and the mapped-files `Read`); `sdlc-develop-verify-skill/references/dispatch-prompts.md` (helper script, source reader and review prompts; carries the mapped-files `Read` twice).