### Pattern Mapping

> **How coverage actually works:** This table lists 5 explicit phrase-to-call mappings, but they cover only a fraction of real-world transformation sites. The vast majority of cc-sdlc files with knowledge references (skills, agents, process docs) are handled via the **section-level preservation rule** documented in "Content-Merge Rules for Neuroloom" below — scan each file for `memory_search(` / `memory_store(` presence and preserve those sections verbatim during merge. The explicit patterns below are what the transformer SEEKS during fresh installation (`/sdlc-initialize`) and during migration when a file has no prior MCP patterns. Once a file contains MCP calls, section-level preservation takes over.

**Match rules:**
1. **Case-insensitive on the leading verb, regardless of sentence position.** A rule `Read [sdlc-root]/disciplines/*.md and find [X]` matches both sentence-start `Read [sdlc-root]/disciplines/*.md and find...` and mid-sentence `..., read [sdlc-root]/disciplines/*.md and find...`. The verb (`Read`/`Consult`/`Append`/`Update`/`Look up`/etc.) is the anchor, not the sentence start. When substituting, preserve the original case of the verb only if the substitution keeps a verb at that position; otherwise the replacement's casing wins.
2. Patterns must match as a full phrase within a sentence.
3. **Inline backticks around paths are markdown formatting — match THROUGH them.** A rule `Append to [sdlc-root]/disciplines/*.md` matches `Append to \`[sdlc-root]/disciplines/*.md\`` (with inline backticks) and vice versa. Strip inline backticks before matching.
4. Only skip matching inside **fenced code blocks** (triple backticks ```` ``` ````) — those are literal code examples, not instructions.
5. When the rule pattern contains `<domain>` or `{name}` or `[agent-name]`, treat as a wildcard that captures the substring at that position. **The wildcard matches ANY value at that position, including other angle-bracket-looking placeholders in the source.** If upstream cc-sdlc content uses a different placeholder name (e.g., `<discipline>`, `<file>`, `<name>`) at the same structural position, the rule's wildcard matches that placeholder string as its captured value. When substituting, the captured string (placeholder and all) is inserted into the replacement.

   **The bug this prevents:** In `migrate-f01a70` AND `migrate-fa70ef`, `sdlc-ingest.md:231` had upstream `- Files from the same discipline (e.g., \`[sdlc-root]/knowledge/<discipline>/\`)`. The metadata rule `(e.g., [sdlc-root]/knowledge/<domain>/)` → `(e.g., memory entries tagged sdlc:knowledge + sdlc:domain:<domain>)` should match, capturing `<discipline>` into the `<domain>` wildcard slot. But both runs left the upstream text untransformed — the executor was requiring `<domain>` in the rule pattern to match a real domain value in the source, not another placeholder. Correct behavior: the wildcard matches `<discipline>` and the output is `(e.g., memory entries tagged sdlc:knowledge + sdlc:domain:<discipline>)` — the captured placeholder survives into the replacement because documentation describing a template should remain template-shaped after transformation.

   **Explicit worked example:**
   - Rule pattern: `(e.g., [sdlc-root]/knowledge/<domain>/)` with `<domain>` as wildcard per rule #5
   - Input (with backticks stripped per rule #3): `(e.g., [sdlc-root]/knowledge/<discipline>/)`
   - Match: `<domain>` wildcard captures the literal string `<discipline>`
   - Output: `(e.g., memory entries tagged sdlc:knowledge + sdlc:domain:<discipline>)`

   Do NOT require the captured value to be a "real" domain name. The rule's job is structural transformation, not semantic validation.
6. **Wildcard captures (`[X]`, `<name>`, `<purpose>`, `<tag-expr>`, etc.) are non-greedy and MUST terminate at any of:** `(`, `)`, `[` (not the opening `[` of the wildcard itself), `]`, `,`, `.`, `;`, `:` followed by whitespace, **`for `**, **`to `**, **`during `**, **`when `**, **`per `**, **`with `**, or end-of-line. A capture MUST NOT swallow a following parenthetical, list comma, sentence boundary, OR a purpose-clause introducer (`for X`, `to X`, `with X`, etc.). Specifically: if the text after the wildcard is `(e.g., ...)` or `, [...]` or `. Sentence continues` or `for knowledge wiring` or `to retrieve X`, the capture stops **before** that token.

   **The bug this prevents:** In `migrate-f01a70`, `sdlc-archive.md:175` matched `read [sdlc-root]/disciplines/*.md and find parking lot entries tagged with that deliverable's ID (e.g., [D05 — phase 2], [D05 — planning]).` The `[X]` capture in rule `Read [sdlc-root]/disciplines/*.md and find [X]` greedily consumed up through `ID (e` then stopped at an arbitrary character, producing a query string of `"parking lot entries tagged with that deliverable's ID (e"` and leaking the remaining `g., [D05 — phase 2]...)` outside the `memory_search(...)` call as orphan text. A non-greedy capture with explicit terminators stops at `(` and produces a clean `memory_search(query="parking lot entries tagged with that deliverable's ID", tags=[...])` followed by the original `(e.g., [D05 — phase 2], [D05 — planning]).` preserved verbatim.

   **Bullet-tail consumption — sleeved `migrate-6f4217` regression class (added post-`migrate-6f4217`, 2026-04-26):** in a bullet item like `- Consult [sdlc-root]/knowledge/agent-context-map.yaml for knowledge wiring`, the matcher fired the rule `Consult [sdlc-root]/knowledge/agent-context-map.yaml for knowledge wiring` → `memory_search(query="agent knowledge wiring", tags=["sdlc:knowledge"])` (rule on line 45) but the capture additionally swallowed the `for knowledge wiring` tail into the replacement query string instead of leaving it as bullet context. Output became `- call memory_search(query="knowledge wiring", tags=["sdlc:knowledge"])` — losing both the explicit `agent` qualifier of the documented replacement AND the bullet's `for [purpose]` context that gave the reader a reason for the lookup. Match rule #6's expanded terminator list (above) prevents this — `for ` is now a hard terminator regardless of whether the surrounding rule has a literal `for ` in its pattern. Rules that intentionally consume `for [purpose]` (e.g., `Read [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml for the handoff schema` on line 52) take precedence as longest-match-wins per rule ordering, so explicit `for X` rules still fire first; only opportunistic mid-sentence captures are stopped at the `for` boundary.

   **Post-write regression check:** scan output for `- (call |Call )memory_search\(query="[a-z]` followed by no surrounding context that explains the lookup's purpose. A bullet that became a bare MCP call with no remaining prose has lost its semantic context — flag as bullet-tail-consumption regression and halt.

7. **Verb-phrase awareness — rules that replace a verb phrase MUST produce a verb phrase** (added post-`migrate-fa70ef`). When the source phrase is a verb + object (`update X`, `read Y`, `append to Z`), the replacement must also be a verb + object — never a parenthetical aside, noun phrase, or standalone clause that can't take an object.

   If a rule's replacement is a parenthetical like `(skip — X)` or a bare noun phrase, it MUST NOT fire mid-sentence where surrounding text assumes a verb phrase. For such rules, the matcher has three options:

   a. **Preferred: extend the match to the full sentence clause**, replacing everything from the verb to the next sentence boundary. Example for `update [sdlc-root]/knowledge/agent-context-map.yaml to wire newly created knowledge files to relevant agents`: match the entire clause, replace with `Tag new knowledge via memory_store with sdlc:agent:[agent-name] and domain tags`. The extended-match form already exists in the specific-rule table (lines 135–136) — the matcher should prefer these extended variants over the terse `update X` rule whenever the surrounding context contains `to <verb>` or `with <object>`.

   b. **Acceptable: emit a grammatically-valid verb-phrase replacement.** If no extended variant matches, rewrite the rule's replacement to a phrase that can accept following objects. Instead of `(skip — Neuroloom uses tag-based wiring)`, use `skip this step (Neuroloom uses tag-based wiring via memory_store)` which remains grammatical even if the original sentence had trailing `with the mapping` — the reader parses it as a dangling qualifier rather than a broken sentence.

   c. **Last resort: emit `TRANSFORMATION_WARNING` and leave verbatim.** If the rule's replacement genuinely can't be reformulated as a verb phrase AND no extended variant covers the compound form, the matcher emits a warning and writes the original upstream text unchanged. This surfaces a Pattern Mapping gap rather than producing malformed output.

   **The bug this prevents:** In `migrate-fa70ef`, `sdlc-create-agent.md:256` had upstream `2. update [sdlc-root]/knowledge/agent-context-map.yaml with the mapping` — and the `update [sdlc-root]/knowledge/agent-context-map.yaml` rule fired with its `(skip — Neuroloom uses tag-based wiring via memory_store; no map to update)` replacement, producing the ungrammatical `2. (skip — Neuroloom uses tag-based wiring via memory_store; no map to update) with the mapping`. A verb-phrase-aware matcher would either extend the match to consume `with the mapping` (option a, since "update X with Y" is a compound verb construction), or rewrite the replacement to a clause-starting verb (option b). Same-class bug at `sdlc-audit.md:121`.

   **Enforcement:** the matcher MUST tag every Pattern Mapping rule as either `VERB_PHRASE` or `CLAUSE_REPLACEMENT`. Rules emitting parentheticals or noun phrases are `CLAUSE_REPLACEMENT` and MUST match whole-clause spans. Rules emitting verb phrases are `VERB_PHRASE` and may match mid-sentence. Applying a `CLAUSE_REPLACEMENT` rule to a sub-clause match produces grammatical corruption — halt with `TRANSFORMATION_WARNING` rather than write the broken output.

| cc-sdlc Generic Pattern | Neuroloom Pattern (preserve if present) |
|-------------------------|----------------------------------------|
| `consult [sdlc-root]/knowledge/agent-context-map.yaml` | `memory_search(query="[agent-name] domain-specific patterns", tags=["sdlc:knowledge"])` |
| `Consult [sdlc-root]/knowledge/agent-context-map.yaml for the [agent-name] entry and include relevant knowledge files in the dispatch prompt` | `memory_search(query="[agent-name] domain patterns for cross-domain dispatch", tags=["sdlc:knowledge"]) and include results in the dispatch prompt` |
| `Before starting substantive work, consult [sdlc-root]/knowledge/agent-context-map.yaml and find your entry. Read the mapped knowledge files...` | `Before starting substantive work, call memory_search(query="[agent-name] domain-specific patterns anti-patterns guidance", tags=["sdlc:knowledge"]) to retrieve domain-specific patterns...` |
| `Consult [sdlc-root]/knowledge/agent-context-map.yaml for the agent's mapped files` | `memory_search(query="[agent-name] mapped knowledge", tags=["sdlc:knowledge"])` |
| `Consult [sdlc-root]/knowledge/agent-context-map.yaml for knowledge wiring` | `memory_search(query="agent knowledge wiring", tags=["sdlc:knowledge"])` |
| `Consult [sdlc-root]/knowledge/agent-context-map.yaml to identify agents whose mappings include` | `memory_search(query="agents with mappings in [discipline]", tags=["sdlc:knowledge"])` |
| `update [sdlc-root]/knowledge/agent-context-map.yaml` (whole-clause match only — see match rule #7; if surrounded by `to <verb>` or `with <object>`, prefer the extended-compound rules below) | `skip this step (Neuroloom uses tag-based wiring via memory_store; no map to update)` — `VERB_PHRASE` class, can slot mid-sentence |
| `Update [sdlc-root]/knowledge/agent-context-map.yaml to add a new entry mapping the agent to relevant knowledge files` | Store knowledge tagged with `sdlc:agent:[agent-name]` and domain tags via memory_store |
| `Update [sdlc-root]/knowledge/agent-context-map.yaml to wire newly created knowledge files to relevant agents` | Tag new knowledge via memory_store with `sdlc:agent:[agent-name]` and domain tags |
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
| `listed in [sdlc-root]/knowledge/agent-context-map.yaml` | `indexed by sdlc:agent:* tags in the memory graph` |
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
| `agent-context-map.yaml` (referenced as a live config file) | `the memory graph (agents indexed by sdlc:agent:* tags)` |
| `agent-context-map` (bare, used as a live thing) | `the memory graph's agent index` |
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
- **Do NOT apply inside:** Integration sections, fenced code blocks, headings that are the literal title of a framework-defined procedure (e.g., `### 9a. Scan Related Parking Lot Entries` as a defined section of the archive skill is a different case — see below), changelog entries, the phrasing contract doc itself.
- **Headings are a special case.** An H3/H4 heading like `### 9a. Scan Related Parking Lot Entries` names a procedure that cc-sdlc defines. In Neuroloom the procedure still exists but operates on memory entries, so rename the heading to `### 9a. Scan Related Discipline Memory Entries` AND adjust the body's procedure text to match. Do NOT transform the heading without transforming the body — that produces a mismatch where the heading says "memory entries" and the body says "files".
- **Procedure-specific steps are a special case.** Content like "Write new YAML files or append to existing ones" is a file-mode procedure. In Neuroloom, the procedure is "call `memory_store(content=..., tags=[...])`" — a completely different mechanism. When you see a numbered step that's a file-mode procedure, the replacement must be the Neuroloom procedure equivalent, not a word-for-word term swap. When no clean equivalent exists (e.g., "update the README.md structure listing"), emit `TRANSFORMATION_WARNING` and consider dropping the step since it's file-mode-only work the adapter doesn't need.
- **Fragments match independently within sentences,** same rule as audit-description. A sentence with multiple concept-terms must have each term transformed separately.

**The bug this prevents:** `migrate-fa70ef` left `improvement-methodology.md:213` with the full sentence: "No markers needed for project-specific files: Knowledge YAML files, discipline parking lot entries, and agent-context-map.yaml are project-owned..." All three concept terms describe the knowledge layer in file terms; none contain a `[sdlc-root]/` path so audit-description rules didn't fire. The new class catches this: `Knowledge YAML files` → `memory entries tagged sdlc:knowledge`; `discipline parking lot entries` → `discipline memory entries`; `agent-context-map.yaml` (live reference) → `the memory graph`. Same class of bug at `improvement-methodology.md:47/80/137–138/196–197`, `sdlc-archive.md:171/173/185`, `sdlc-ingest.md:214–218`, `research-external.md:72/204`.

**Audit-description match notes:**
- These rules apply in PROSE contexts where `[sdlc-root]/knowledge/` or `/disciplines/` appear as concept references, not runtime read instructions. Most common in `compliance-methodology.md` audit dimension descriptions.
- Do NOT apply inside Integration sections (`**Uses:**`, `**Depends on:**`), table cells, or code blocks — use the metadata-transformation table above for those.
- Distinguishing signal: if removing the path would leave the sentence still making sense (just less specific), it's audit-description metadata. If removing it breaks an instruction, it's a runtime ref — use the instruction rules above.
- **Fragments match independently within compound sentences.** A sentence with multiple path references (e.g., `Any memory entry tagged sdlc:knowledge not listed in any agent's mapping in [sdlc-root]/knowledge/agent-context-map.yaml. Severity: Warning...`) must have every `[sdlc-root]/...` fragment matched separately. The matcher walks the sentence and applies each audit-description rule to each fragment independently. Mixed results (one half transformed, one half untransformed) are a known failure mode and indicate the matcher only ran once per sentence.

   **The bug this prevents:** In `migrate-f01a70`, `compliance-methodology.md:208` became a compound mess: `Any memory entry tagged sdlc:knowledge not listed in any agent's mapping in the agent knowledge graph (via memory_store with sdlc:agent:{name} tags). Severity: Warning (the knowledge exists but no agent consumes it).` — the `listed in [sdlc-root]/knowledge/agent-context-map.yaml` fragment got the canonical `indexed by sdlc:agent:* tags` replacement on ONE half but the other half was independently misrewritten. The matcher must treat each `[sdlc-root]/...` occurrence as a separate match target.
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
| `` - Agent knowledge context: `[sdlc-root]/knowledge/agent-context-map.yaml` `` | `- Agent knowledge context: memory graph (agents indexed by sdlc:agent:* tags)` |
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

**Integration sections are structurally exempt — HARD EXCLUSION:**

Any line matching `^\*\*(Uses|Depends on|Updates|Feeds into|Complements|Downstream|Does NOT replace|DRY notes):\*\*` and every bullet/text line following it up to the next blank line, the next `^\*\*[A-Z]` (new Integration label), or the next `^#{1,6} ` (heading) is an **Integration section**. Integration sections are exempt from ALL transformation:

- No instruction-rule matching
- No metadata-rule matching
- No capture-target-rule matching
- No audit-description rule matching

Integration sections describe logical dependencies between skills/agents/files, not runtime operations. Transforming `**Uses:** [sdlc-root]/knowledge/agent-context-map.yaml (for wiring)` into `**Uses:** memory graph (agents indexed by sdlc:agent:* tags) (knowledge wiring)` adds noise (the parenthetical purpose tag now wraps a non-file reference) and produces double-paren corruption. Leave Integration sections verbatim.

**Enforcement:** The matcher must mask out Integration sections before any rule evaluation. A post-write regression scan for `\*\*(Uses|Depends on|Updates|Feeds into):\*\*.*memory_(search|store)` on a single line halts the write — the Integration section was transformed and must be re-copied verbatim.

**VERBATIM means byte-identical, not "semantically preserved":** Integration-section lines must be written out byte-for-byte identical to the upstream source. This includes — and this is the failure mode `migrate-fa70ef` surfaced across 20+ files — **surrounding backticks on path references**. `` **Uses:** `[sdlc-root]/process/manager-rule.md` `` must remain with its inline backticks intact. Any incidental side-effect that strips backticks (e.g., a path-normalization pass that runs alongside the Pattern Mapping) violates the hard exclusion.

**Post-write backtick-preservation check:** diff the written Integration-section block against the upstream Integration-section block byte-for-byte. Any character-level difference — backticks stripped, whitespace adjusted, punctuation altered — halts the write. The Integration block is verbatim or the migration is wrong.

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
| `([sdlc-root]/knowledge/agent-context-map.yaml)` | `(memory graph, agents indexed by sdlc:agent:* tags)` |
| `([sdlc-root]/knowledge/**/*.yaml)` | `(memory graph, entries tagged sdlc:knowledge)` |
| `([sdlc-root]/knowledge/*.md)` | `(memory graph, entries tagged sdlc:knowledge)` |
| `([sdlc-root]/knowledge/<domain>/*.yaml)` | `(memory graph, entries tagged sdlc:knowledge and sdlc:domain:<domain>)` |
| `([sdlc-root]/knowledge/<domain>/)` | `(memory graph, entries tagged sdlc:knowledge and sdlc:domain:<domain>)` |
| `([sdlc-root]/disciplines/*.md)` | `(memory graph, entries tagged sdlc:discipline:*)` |
| `([sdlc-root]/disciplines/<name>.md)` | `(memory graph, entries tagged sdlc:discipline:<name>)` |
| `(e.g., [sdlc-root]/knowledge/<domain>/)` | `(e.g., memory entries tagged sdlc:knowledge + sdlc:domain:<domain>)` |
| `(e.g., [sdlc-root]/knowledge/<domain>/*.yaml)` | `(e.g., memory entries tagged sdlc:knowledge + sdlc:domain:<domain>)` |
| `(e.g., [sdlc-root]/disciplines/<name>.md)` | `(e.g., memory entries tagged sdlc:discipline:<name>)` |
| Bullet label + colon + path: `<Label>: [sdlc-root]/knowledge/agent-context-map.yaml` (e.g., `- Agent knowledge context: [sdlc-root]/knowledge/agent-context-map.yaml`) | `<Label>: memory graph (agents indexed by sdlc:agent:* tags)` |
| Bullet label + colon + path: `<Label>: [sdlc-root]/knowledge/<domain>/<file>.yaml` | `<Label>: memory entries tagged sdlc:knowledge + sdlc:domain:<domain>` |
| Bullet label + colon + path: `<Label>: [sdlc-root]/disciplines/<name>.md` | `<Label>: memory entries tagged sdlc:discipline:<name>` |
| Table cell containing `[sdlc-root]/knowledge/agent-context-map.yaml` (any column) | Cell becomes `memory graph (sdlc:agent:* tags)` |
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
- It is NOT a YAML key, YAML value, JSON key, or JSON value (when the surrounding context is structured data, even if outside a fence — e.g., frontmatter fields)
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
- YAML frontmatter fields like `name:`, `description:`, `model:`
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

**Fenced code blocks containing file-mode demos — deferred to 0.5.0:** Pass 2 intentionally does not modify fenced-block contents, even when those contents are file-mode demos (e.g., a ` ```yaml ` block demonstrating `mappings: ui-ux-designer: [paths]` in an adapter-unreachable format). Surrounding prose is transformed by Pass 2; the demo itself is preserved as cc-sdlc's original file-mode reference. Future work (0.5.0) may add an optional pre-fence annotation (e.g., *"In Neuroloom mode, the equivalent operation is `memory_store(..., tags=[...])`."*) as a demonstration-mapping rule class. Until then, fenced-block file-mode demos remain a project-specific customization zone — if your installation wants to replace the demo, wrap the whole fenced block in `PROJECT-SECTION` markers.

