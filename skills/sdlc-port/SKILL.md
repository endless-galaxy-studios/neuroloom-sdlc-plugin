---
name: sdlc-port
description: >
  Migrates an existing local z-sdlc installation to use Neuroloom as the backend. Reads local
  knowledge stores, discipline files, and deliverable docs; ingests them into Neuroloom via batch
  ingestion; then transforms agent and skill files to use semantic search instead of local file reads.
  Triggers on "port sdlc to neuroloom", "migrate local sdlc", "move sdlc to backend",
  "port my knowledge to neuroloom", "migrate my existing sdlc to neuroloom".
  Do NOT use for fresh installation without an existing local z-sdlc — use sdlc-initialize instead.
  Do NOT use for updating an already-ported Neuroloom workspace to a newer z-sdlc version — use sdlc-migrate.
---

# SDLC Port

Port a local z-sdlc installation to Neuroloom: ingest its knowledge stores, discipline files and
deliverable docs, replace file reads in agent and skill files with `memory_search` calls, and mark
the workspace ported in the manifest. Run it once on a project with `ops/sdlc/`; a project without
z-sdlc runs `/sdlc-initialize`, an already-ported one moving to a newer release, `/sdlc-migrate`.

---

## Mode Detection

Before executing any stage, determine which mode applies.

| State | Mode | Action |
|-------|------|--------|
| `ops/sdlc/` exists, no sentinel or other SDLC records, no port keys in the manifest | **Fresh port** | Full port flow (Stages 1-5) |
| Manifest has `port_in_progress: true` and neither `ported_at` nor `neuroloom_backend` | **Fresh port, continued** | Full port flow, after Gate 3's workspace check; no Post-Port Cleanup |
| Manifest has `ported_at` | **Re-port** | Gate 3's refusals, then confirm via AskUserQuestion; Stage 3a only when the files hold entries; no Post-Port Cleanup |

Gate 3 below decides between them, and stops on the states that are none of these: an install
`/sdlc-initialize` set up with the plugin, and a sentinel the manifest doesn't account for. A port
that failed partway needs no mode of its own: every write it makes is idempotent (upserts by
`knowledge_id`, and Stage 3c's lookups), so re-running it from the start finishes it; the
manifest's `port_in_progress` tells Gate 3 the records already in Neuroloom are this port's.

---

## Stage 1 — Pre-flight and Inventory

### Gate 1: Local z-sdlc installation exists at `ops/sdlc/`

First run the SDLC root check, `${CLAUDE_PLUGIN_ROOT}/references/preflight.md` check 0. If it fails, stop
with its message. `ops/sdlc/` is the only root this plugin supports.

Then check whether `ops/sdlc/` is present in the project root. If absent, stop and output:

```
No z-sdlc installation found. Run /sdlc-initialize instead.
```

Do not proceed.

### Gate 2: Neuroloom API is reachable

Call `sdlc_get_version` as a dedicated connectivity and authentication check. If it fails with an authentication error, output:

```
Neuroloom API authentication failed. Verify your API key is set and valid
(the base neuroloom plugin's setup, `/plugins configure neuroloom`).
```

If it fails with a network error, output:

```
Neuroloom API unreachable. Check your network connection and API URL configuration.
```

Stop in both cases. Do not proceed to Gate 3 or Stage 2.

Store the returned version as `CURRENT_SDLC_VERSION`: Stage 3a labels the seed with it only when the project has no `source_version`.

### Gate 3: Check for existing port

Every stop here comes before any write. Gather what
`${CLAUDE_SKILL_DIR}/references/gate-3.md` § The facts lists: from Neuroloom, the
sentinel search's `filters.workspace_id` and exact-tag lookups (`search_ok` and `index_ok` record
whether they worked: a failed lookup says nothing, so it is never "no row"); from the manifest, its
port keys.

Write them as `{"manifest": {...}, "observed": {...}}` to a file in a temporary directory and run:
```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/decide_port_gate.py" --facts <file>
```
It prints `{"case", "action", "reason", "message", "recovery"}`, and case 4 adds `label_matches`:
- `stop`: show `message` and `recovery`, and stop. Write nothing.
- `continue_fresh`: an earlier port of this project stopped before Stage 5. Continue as a fresh
  port, from the Inventory, without the re-port question (whatever its Stage 3 already wrote, Stage
  3 skips or upserts).
- `ask`: a re-port; ask the question below.
- `fresh`: a fresh port.
Exit 2 means the facts file didn't parse, a fact is missing or the wrong type, or `index_ok` is false
(the error names it): gather that fact again, and never write a value for one you couldn't observe or
decide by hand. If a lookup keeps failing, stop and run the port again once it works.

What each case means, and why: `${CLAUDE_SKILL_DIR}/references/gate-3.md` § The cases.

```
This workspace has already been ported to Neuroloom (ported at {ported_at}).
Re-porting re-sends the local knowledge files and parking-lot entries,
overwriting updates made directly in Neuroloom since the last port, except
entries tagged sdlc:project-specific, which the server never updates. It never
re-sends a discipline's framework, status, Active Questions, Project Context
or tracker: their Neuroloom copy is the live one. Edit those there.
Post-Port Cleanup is skipped on a re-port.
```

Options:
1. Re-port (re-send local knowledge and parking-lot entries, update manifest)
2. Cancel

If the user cancels, stop. Do not write anything.

### Inventory

After all three gates pass, run the extraction script in dry-run mode to get knowledge/discipline
entry counts, then glob deliverable docs and agent/skill files separately:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/extract_sdlc_knowledge.py" --dry-run
```
(On a re-port, add Stage 3a's `--exclude-kinds`.) A non-zero exit stops the port with its message; nothing has been written.

Its stderr summary gives the files scanned by kind, the entry total, the knowledge files
`declined_files` excluded and any file with no entries: parse it for the counts. Show zero-count rows for empty categories, and
show the zero-entry files, and any it couldn't read, at the Stage 2 gate: nothing from them reaches
Neuroloom, so they stay on disk after Post-Port Cleanup.

**Zero entries.** On a re-port this is the usual state after the first port's cleanup deleted the
files. Neuroloom's copy is then the live one (Gate 3 checked that this workspace holds the sentinel),
so Stage 3a is skipped (say so at Stage 2) and the port continues at Stage 3b. On a fresh port, a
continued one included, zero entries means there is nothing to seed, and with no seed there is no
sentinel for Stage 5 to find: stop, and say the project's `knowledge/` and `disciplines/` are empty.

**Upstream baseline.** When there are entries, make the port's temporary directory and fetch
upstream z-sdlc's knowledge into it at the release the project's files came from, so Stage 3a can
tell the project's own entries from upstream's. This writes nothing in the project. First:
```bash
mktemp -d
```
It prints the directory; this skill calls it `<SEED>` from here on. Write it out literally in every
later command, since a shell variable doesn't survive from one Bash call to the next. Then, with
`<ref>` the manifest's `source_version`, or its `source_version_sha` when `source_version` isn't a
tag z-sdlc has (an initialize from an untagged commit records `"unknown"`); `"unknown"` with no sha
counts as no version key. z-sdlc is public:
```bash
set -o pipefail
gh api "repos/endless-galaxy-studios/z-sdlc/tarball/<ref>" > "<SEED>/z.tgz" \
  && mkdir "<SEED>/base" && tar -xzf "<SEED>/z.tgz" --strip-components=1 -C "<SEED>/base" \
  && test -d "<SEED>/base/knowledge" && test -d "<SEED>/base/disciplines"
```
When the fetch fails, stop and re-run the port once it works: the server applies tags only when it
creates a row, so entries seeded now without `--tag-new` could never be marked `sdlc:project-specific`
later. Only when the manifest has neither key is there no baseline to fetch: say so at Stage 2 (the
project's own entries then go untagged, and `knowledge-update` reports an upstream entry that reuses
one of their ids as a conflict rather than overwriting it).

**The seed's label** is the release the files reflect: `source_version` when it is a tag (anything
but `"unknown"`); for an untagged install, the first 7 characters of `source_version_sha`, the
short commit id `knowledge-seed` labels one with; `{CURRENT_SDLC_VERSION}` only when the manifest has
neither, and then on a re-port the `knowledge_seed_version` it already records (so a re-port that stops
after ingestion leaves the sentinel on the label the manifest names). Stage 3a passes it, Stage 5 records it, and Gate 3 compares a re-port with it.

For deliverable docs and agent/skill files, glob and count files:

| Category | Glob | What to count |
|----------|------|---------------|
| Deliverable docs | `python "${CLAUDE_SKILL_DIR}/scripts/extract_deliverable_docs.py" --dry-run` | Docs it will ingest, and the ones it skips for having no frontmatter |
| Agent/skill files | `.claude/agents/*.md` + `.claude/skills/**/*.md` + `ops/sdlc/**/*.md` outside `knowledge/` and `disciplines/` | Files (transformation targets) |
| Provenance records | Entries in `ops/sdlc/knowledge/provenance_log.md`, if the file exists | Entries (stored in Stage 3c) |

Also run `git status --porcelain -- .claude ops/sdlc`. If it lists anything, show it at the Stage 2
gate: every undo restores the copies Stage 4c makes before changing a file, so those changes survive.

---

## Stage 2 — Confirmation Gate

Present the inventory summary. Do not begin any writes until the user confirms.

```
z-sdlc installation found. Ready to port to Neuroloom.

  Knowledge YAML:     {N} files, {M} entries
  Knowledge docs:     {N} Markdown documents
  Discipline files:   {N} files, {M} entries
  Deliverable docs:   {N} files ({S} without frontmatter are skipped and stay unsearchable)
  Agent/skill files:  {N} files (transformation targets)
  Provenance records: {N} entries
  Upstream baseline:  {"<ref>" | "none: <reason>; the project's own entries go untagged" | "not fetched: Stage 3a is skipped"}
  Knowledge seed:     {"Stage 3a sends {M} entries" | "skipped: re-port with no entries to send, Neuroloom's copy is live"}
  Not read:           {files the dry run read nothing from, or "none"}; they stay on disk
  Uncommitted:        {paths git status listed, or "none"}; any undo keeps them

This will ingest all content into Neuroloom and modify agent/skill files to use
semantic search. Stage 4c copies each file before changing it, and an undo restores those copies.
Run it while no other session is changing this project's SDLC records in Neuroloom or its files, and
don't edit them until it ends: an undo puts each file it changed back as it was before the port.
```

Use `AskUserQuestion` with options:
1. Proceed with port
2. Cancel

Do not proceed past this gate without explicit confirmation.

---

## Stage 3 — Knowledge Ingestion

Ingest SDLC knowledge and discipline files into Neuroloom via `sdlc_seed` (Stage 3a),
then ingest deliverable docs via the file-based batch ingestion tools (Stage 3b), then store the
provenance log's records as memories (Stage 3c). Report progress between stages. Do not begin
Stage 3b if Stage 3a fails. Stage 3c runs even when some 3b batches had errors.

**On a fresh port, mark it first.** Before the first Neuroloom write, merge `"port_in_progress": true`
and `"workspace_id"` (the `filters.workspace_id` of Gate 3's sentinel search, the workspace this run
writes to) into `.sdlc-manifest.json` (create it with just those keys
if the project has none), keeping every other key. If the port stops before Stage 5, at Stage 4b or
by failing, even before its first write landed, Gate 3 reads the marker on the next run, checks the
key still reaches that workspace, and carries on; without it, the records this run writes would be
a sentinel the manifest doesn't account for, and Gate 3 would refuse them. Stage 5 removes
`port_in_progress` and writes `"knowledge_id_scheme": 2`, which means the seed is complete.

### Stage 3a — SDLC Knowledge via `sdlc_seed`

Use the extraction script to generate the seed file, then use the appropriate seed tool to
ingest it. Do NOT manually construct entries or write custom extraction scripts — the
extraction script already handles all knowledge YAML parsing, discipline file parsing, tag
derivation, and entry construction.

**Step 1 — Generate the seed files:**

Skip Stage 3a when the Inventory's **Zero entries** rule says to. Otherwise, with the baseline the
Inventory fetched and the label it chose:
```bash
python "${CLAUDE_SKILL_DIR}/scripts/extract_sdlc_knowledge.py" --version "<label>" \
  --baseline-knowledge-dir "<SEED>/base/knowledge" --baseline-disciplines-dir "<SEED>/base/disciplines" \
  --tag-new sdlc:project-specific --output "<SEED>/sdlc_seed.json"
```
`--tag-new` marks every entry upstream didn't have at that release (knowledge the project added) as
`sdlc:project-specific`, so no later upstream entry with the same id can overwrite it, and
`sdlc-migrate`'s impact analysis finds the project's knowledge by that tag. The label is the release
the content reflects, so the SessionStart hook sees a migration is due. On a re-port add
`--exclude-kinds framework,status,parking-lot-structure,active-questions,project-context,maturity-tracker`: a re-port re-syncs knowledge entries and parking-lot bullets
(whose ids are their own text's hash), never a discipline's framework or project data, whose live
copy is Neuroloom's after the first port and which a stub `sdlc-ingest` left on disk would overwrite. With no baseline, leave out
the two `--baseline-*` flags and `--tag-new` (only when the manifest has no version key), and keep the
same label.

It prints the seed files it wrote, one per line: `<SEED>/sdlc_seed.json` when the entries fit in one,
otherwise `<SEED>/sdlc_seed_001.json`, `_002.json` and so on, each within the API's limits (500 entries
per call, and under the 1 MiB upload limit). A real project's knowledge is usually more than one
file. A non-zero exit stops the port here: the extractor refuses duplicate ids, a knowledge file's id
in the `discipline:` namespace, a tag Neuroloom adds itself and a malformed `tags` value, rather than guess which entry wins. Each discipline file becomes several entries, divided as z-sdlc's `sdlc-migrate` §2.3
divides it: the framework sections as `discipline:<name>:framework` (the same entry the adapter's
handlers keep current), and the project's data: each parking-lot entry, tagged
`sdlc:project-specific` (which no update overwrites) and `sdlc:parking-lot` (which the skills'
parking-lot searches find), and Active Questions, Project Context and the maturity tracker under
fixed ids, untagged; after the first port Neuroloom's copy is the live one. No upstream release has those ids.

Each file is `{"entries": [...], "version": "..."}`. Together they hold the entries from
every knowledge YAML except `agent-context-map.yaml` (every section and field), every knowledge
Markdown document except the READMEs and `provenance_log.md`, and every discipline file except its
README. Knowledge files in `.sdlc-manifest.json`
→ `declined_files` are left out (`--manifest` names another manifest). The script handles all entry construction
including `knowledge_id`, tags, importance, concepts, and source paths.

**Step 2 — Ingest each seed file, every one with `skip_deprecation: true`:**

The tool to use depends on transport mode:

- **stdio mode:** `sdlc_seed_from_file(path=<file>, skip_deprecation=true)`
- **HTTP mode:** `sdlc_seed_get_upload_url(path=<file>, skip_deprecation=true)`, then run the
  returned `curl_command` via Bash, with `-sS --fail-with-body` in place of `-s` (the upload token
  expires after a few minutes: request it just before each upload)

A file succeeded only when its response holds all four counts below. Anything else (an `error` or
`detail` key, a non-2xx status, an expired token) is a failure, even when `curl` itself exits 0.

Never leave the flag off. Without it, `sdlc_seed` marks every earlier seed memory the call leaves
out as `sdlc:deprecated`, whatever its version or origin, and a weekly server job deletes them: the
second file would retire the first file's entries, and a re-port after Post-Port Cleanup would
retire everything the cleanup removed from disk, along with what `knowledge-update` created.
Retiring entries is never the port's job.

Both tools return the same response shape:
```json
{
  "created": N, "updated": N, "unchanged": N, "deprecated": N
}
```

On a failed file, log the response and the file, and stop — do not continue to Stage 3b (deliverable docs ingestion). The server
rejects a whole call for one bad entry, so nothing from that file was written; the files before it
stay as written. Re-running the port sends every file again, safely: entries already written come
back `unchanged`.

**Deduplication:** `sdlc_seed` matches entries by `knowledge_id` server-side, and the extractor
gives every entry an id the API accepts, unique within the run. Re-porting is safe — identical
entries produce "unchanged" counts, not duplicates. The adapter's `knowledge-seed` and
`knowledge-update` handlers build their entries with the same script (`--upstream`), so a later
migration finds and updates these entries instead of adding a second set.

### Stage 3b — Deliverable Docs

Ingest the deliverable docs with `${CLAUDE_SKILL_DIR}/scripts/extract_deliverable_docs.py` and the
batch tools, as `${CLAUDE_SKILL_DIR}/references/deliverable-docs.md` says (the tags it writes, the
batching, and what a failed batch means).

### Stage 3c — Provenance Records

Store the provenance log's records as memories, as `${CLAUDE_SKILL_DIR}/references/provenance-records.md`
says: the lookup, status order and update rules are there.

---

## Stage 4 — Transformation

Transform agent files, skill files, reference docs, and the agent template to replace local
`ops/sdlc/knowledge/` file-read patterns and bare YAML filename references with `memory_search`
calls. This stage has five sub-steps, 4a to 4d and 4g. The letters keep their earlier names, so
there is no 4e or 4f (the CHANGELOG's 0.7.0 entry says what they did).

### Stage 4a — Identify Targets

Scan all files matched by `.claude/agents/*.md`, `.claude/skills/**/*.md`,
`.claude/skills/*/references/*.md`, and every `*.md` under `ops/sdlc/` outside `knowledge/` and
`disciplines/` (process docs, templates, playbooks, and root files such as `README.md`), and the
SDLC region of the project-root `CLAUDE.md` (the lines between `<!-- SDLC-START -->` and
`<!-- SDLC-END -->`; never a line outside them), for THREE categories of references. A `CLAUDE.md`
with no markers still has z-sdlc's sections in it (merged from `CLAUDE-SDLC.md`). Find them the way
`sdlc-migrate` §2.1e does: a `##` section of `CLAUDE.md` is z-sdlc's when its heading is a `##`
heading of `CLAUDE-SDLC.md` at the project's `<ref>` or at `v<CURRENT_SDLC_VERSION>` (the tag). Read those
headings with `gh api "repos/endless-galaxy-studios/z-sdlc/contents/CLAUDE-SDLC.md?ref=<ref>" --jq
.content | base64 -d` (z-sdlc is public). The region runs from the first matching section through the last, ending before the next `#` or `##` heading outside fenced code, as a restore does. Here in 4a, only work it out: show it at Stage 4b, naming any project
section that falls inside it, so the user can correct it, and write nothing to `CLAUDE.md` yet.
Stage 4c writes `<!-- SDLC-START -->` before the region and `<!-- SDLC-END -->` after it, then
transforms inside, once the user has chosen to apply; a stop at 4b leaves the file as it was. If no heading matches but the file has knowledge references, or
`gh` can't fetch the file, ask the user which sections are z-sdlc's; with no answer (headless),
stop at 4b: the audit fails a markerless `CLAUDE.md` with matches, and the cleanup would leave it
reading deleted files. The post-operation audit scans all of these trees, so a file left out
here fails it:

1. **Path references**: `ops/sdlc/knowledge/` and `ops/sdlc/disciplines/` paths, their
   `[sdlc-root]/knowledge/` and `[sdlc-root]/disciplines/` forms (most of z-sdlc's own files use
   these), and relative markdown links into `knowledge/` or `disciplines/` — any instruction to read,
   load, or consult a file there. For the `[sdlc-root]/` forms and the links, apply the rows of
   `${CLAUDE_PLUGIN_ROOT}/references/pattern-mapping-rules.md`, the same rules `/sdlc-migrate` uses.
   The links matter after Post-Port Cleanup deletes the ingested files: a link left pointing at one
   fails the next migration's Check 2d. A link whose target resolves somewhere else (a skill's own
   `knowledge/` folder, say) is not a reference into the SDLC root: leave it. Also rewrite links to
   `bundles/README.md` when the project has no `bundles/` directory, with the rows of
   `pattern-mapping-rules.md` § "Audit-description metadata"; z-sdlc's root `README.md` has two.
2. **Named YAML references**: bare references to `agent-context-map.yaml` or
   `agent-communication-protocol.yaml` — even without the full path prefix. These appear
   in validation checklists, maturity criteria, integration steps, and template instructions.
3. **Provenance-log references**: any mention of `provenance_log` (reading, appending to or naming
   the file). Apply the provenance rows of `pattern-mapping-rules.md`; the audit's provenance scan
   exempts only the changelog and the contract 0026 file-presence lines of Check 2's row 6, which
   stay as they are.

The `ops/sdlc/` scan includes `ops/sdlc/templates/agent-template.md`, which holds runtime
instructions (Knowledge Context, Communication Protocol) that direct agents to read local YAML files.

For each reference found, call `memory_search` to locate the matching seeded entry:
```
memory_search(query="{semantic description of the referenced content}", tags=["sdlc:knowledge"])
```

Build a mapping:
```
{file_path} → [{old_reference} → {proposed memory_search call or updated instruction}]
```

Files with no matching references are not transformation targets — skip them.

**What to transform, and what not:** read `${CLAUDE_SKILL_DIR}/references/transform-targets.md` before
transforming: it lists both, with the exemptions the audit scans share. Apply it to every target.

### Stage 4b — Present Proposed Changes

Show the full list before applying any change. Use this format:

```
Proposed transformations ({K} files):

  .claude/agents/software-architect.md
    ops/sdlc/knowledge/architecture-patterns.yaml
    -> memory_search(query="architecture patterns", tags=["sdlc:knowledge", "sdlc:domain:architecture"], tags_match="all")

  .claude/skills/sdlc-plan/SKILL.md
    ops/sdlc/knowledge/gotchas.yaml
    -> memory_search(query="SDLC gotchas", tags=["sdlc:knowledge", "sdlc:type:gotcha"], tags_match="all")
  ...

CLAUDE.md SDLC region: {"marked" | "lines {a}-{b}, markers to be added: ## {first} … ## {last}"}
  project sections inside it: {list, or "none"}
```

Use `AskUserQuestion` with options:
1. Apply all transformations
2. Stop after ingestion (finish the port later; no file changes, except the manifest's in-progress marker on a fresh port; the finished port won't offer Post-Port Cleanup)
3. Cancel port

If the user stops or cancels here, all content stored in Stage 3 is retained. The user can re-run
`/sdlc-port` to retry transformations; Stage 3 then upserts or skips what is already stored.

On **Stop after ingestion** or **Cancel port**, the run ends here: no 4c, 4d or 4g, no Stage 5 manifest write (on a fresh port, Stage 3's in-progress marker stays), no
audit and no Post-Port Cleanup. On a fresh port the project is not ported; on a re-port nothing about
its state changes. Its agent and skill files still read
`ops/sdlc/knowledge/` and `ops/sdlc/disciplines/`, and a manifest saying `neuroloom_backend: true`
with an `adapter` block would make the next migration transform only the files that release
touches, leaving the project half file-mode. What was stored in Stage 3 stays in Neuroloom as a
preview. Report:

```
Port stopped before transformation. {N} knowledge + {M} discipline entries (or "the knowledge
Neuroloom already held", when Stage 3a was skipped), {K} deliverable docs
and {P} provenance records are in Neuroloom. {On a fresh or continued port: The only file changed is
the manifest, which records the port as in progress (`port_in_progress`, `workspace_id`): keep it, or the re-run can't tell this port's records from someone else's. | On a
re-port: No file was changed.}
Re-run /sdlc-port to transform the files and finish the port.
```

### Stage 4c — Apply Transformations

**`CLAUDE.md` first.** Copy it as it is now to `CLAUDE.md.pre-port`. Keep an existing copy instead only on
a continued port (Gate 3's action was `continue_fresh`) whose `CLAUDE.md` has markers: an earlier run
of this port made it from the untransformed file. Then copy (not move) the current file to
`CLAUDE.md.pre-port.before-continue-$(date -u +%Y%m%dT%H%M%SZ)`, which keeps an edit made between runs. Otherwise first move a leftover copy and region file aside, adding
`.$(date -u +%Y%m%dT%H%M%SZ)` to each name (`mv -n`, with the first suffix, `.<ts>`, `.<ts>-2` …, free for both names; copy afresh only once both are gone): never deleted automatically (the final summary lists them), as one may be the only original.
Stage 4d restores from `CLAUDE.md.pre-port` (never a set-aside copy), which keeps uncommitted edits outside the region that `git
checkout` would throw away. When the copy has no markers, first record the region's first and last `##` headings and their line
numbers (1-based) in the copy in `CLAUDE.md.pre-port.region` (kept with a kept copy, else written now from the region approved in this run): a restore takes the copy's text from the first heading through the line before the next `#`
or `##` heading outside fenced code after the last, each at its recorded line (so a repeated
heading can't mislead it), or the end of the file. Then, when the file has no markers now, insert
`<!-- SDLC-START -->` on its own line before the region approved at Stage 4b and `<!-- SDLC-END -->`
after it, and transform only between them. Touch no other line of the file. When the copy has markers, write no region file: a restore takes the text between
the copy's own markers. Delete both files
once the Stage 5 audit passes, or right after any restore from them.

**Every other file.** Fix `<undo>` once, at the start of Stage 4c (4g and Stage 5 keep this run's
undo state in it too), and write it out literally from then on: `$(git rev-parse --git-path sdlc-port-undo)/$(date -u +%Y%m%dT%H%M%SZ)/` (inside the git
directory: untracked, never cleared; outside git, `.sdlc-port-undo/<same timestamp>/`); every halt that leaves it
names it. Copy each file to `<undo>/files/<its path>` once, before its first edit or replacement
(`mkdir -p`, then `[ -e <copy> ] || cp <file> <copy>`), and before handing it to a subagent. Before creating a file
(`knowledge-routing.md` included), add its path to `<undo>/created`. Every
undo copies each file back from there, never from git, and removes each created one: an uncommitted
edit in a transformed file, and every file the port didn't touch, survive.

**Subagent permissions caveat:**

Subagents may lack Edit permission here. Do Stage 4's templated replacements directly; a subagent
denied permission is never re-dispatched.

After confirmation, apply replacements with the Edit tool, keeping each file-read instruction's
context and intent in its `memory_search` call. A single file-read may map to multiple `memory_search` calls if it covered
multiple knowledge domains.

Every replacement `memory_search` call needs an explicit `query`: a tags-only call is invalid.

Write each query as `${CLAUDE_SKILL_DIR}/references/transform-targets.md` § Replacement queries shows:
a distinct query per concept, never tags-only or reused.

A reference many agents share (the communication protocol, say) still gets a query naming the agent:
see the same section's **Shared references across agents**.

**Agent tools.** Give every agent whose text calls a Neuroloom tool (`memory_search`, `memory_store` or another), whichever run of this port transformed it, its profile's tools plus any other Neuroloom tool its text calls,
as `post-file-write` does on a migration (`${CLAUDE_PLUGIN_ROOT}/references/adapter-lifecycle.md`
§ "Agent tool injection", profiles in `${CLAUDE_PLUGIN_ROOT}/transforms.yaml`). An agent whose
frontmatter lists only `Read, Glob, Grep, Bash` (z-sdlc's compliance auditor) can't call
`memory_search` at all, however correct its text is.

**Skill transforms.** Wire each skill `${CLAUDE_PLUGIN_ROOT}/transforms.yaml` lists, as initialize
and migrate do (`adapter-lifecycle.md` § "Skill transform wiring"): inject its `## Neuroloom
Post-Execution Transform` section, or replace an older plugin's with the current
shape. Without it a ported project's `/sdlc-archive` moves a deliverable or an idea brief
while its Neuroloom document still points at the old path, and `/sdlc-ingest` writes flat files no
agent reads, until the next migration wires them.

### Stage 4d — Validate Transformations

After all edits, verify each transformed file. Each check leaves alone exactly what the audit scan
it mirrors exempts, and the audit's scans exempt different things; `knowledge-routing.md` is checked
separately, below:
- No remaining `ops/sdlc/knowledge/`, `ops/sdlc/disciplines/`, `[sdlc-root]/knowledge/` or
  `[sdlc-root]/disciplines/` path references outside the audit's Check 2 exemption rows 1 to 7 (as
  `references/transform-targets.md` lists them)
- No remaining bare `agent-context-map.yaml` or `agent-communication-protocol.yaml` references
  outside those same rows and the closed list of `sdlc-migrate` map lines in post-operation Check 6
  step 4 (kept as upstream has them)
- No remaining relative markdown link, with or without a `./` or `../` prefix (the audit's Check 2d
  pattern: `\]\((\./|\.\./)*(knowledge|disciplines|bundles)/`), whose target is a file Post-Port
  Cleanup removes or one that doesn't exist, outside `sdlc_changelog.md` and `changelog-archive/*.md`.
  Resolve each against the file that links it: a target that exists and stays is fine
- No remaining `provenance_log` outside `sdlc_changelog.md`, `changelog-archive/*.md` and the
  contract 0026 file-presence lines of the audit's Check 2 row 6 (the provenance scan exempts
  nothing else)
- Every replacement `memory_search` call includes `query`
- File is still valid markdown (no broken code fences or truncated sections)

`ops/sdlc/process/knowledge-routing.md` is not checked this way: it is the plugin's own copy and
names those files on purpose. Check instead that it is byte for byte the plugin's copy
(`cmp ops/sdlc/process/knowledge-routing.md ${CLAUDE_PLUGIN_ROOT}/docs/knowledge-routing.md`), and copy
it again if it isn't.

If validation fails for a file, copy it back from `<undo>/files/<its path>` (Stage 4c's copy), or, for
`CLAUDE.md`, restore only its SDLC region, from the copy Stage 4c made: first copy (not move) the current
file to `CLAUDE.md.pre-port.before-restore-$(date -u +%Y%m%dT%H%M%SZ)` (an edit made inside the
region since the copy was taken lives only there), then replace the lines between
the markers (and the markers, if this port added them) with the copy's text for that region (between the copy's markers, or where
`CLAUDE.md.pre-port.region` says it runs when the copy had none), leave every other line as it is
now, then `rm -f CLAUDE.md.pre-port CLAUDE.md.pre-port.region`. Neither `git checkout` nor a whole-file
copy: both would throw away edits outside the region, made before the port or between a stopped
port and its continuation.


### Stage 4g — Remap Agent Memory Files

Read `${CLAUDE_SKILL_DIR}/references/agent-memory-remap.md` before this stage, and remap the agent memory
files' knowledge-path references as it says, including its backup (only when the scan
finds a match) and what it leaves as historical record.

---

## Stage 5 — Manifest and Verification

Manifest schema, verification checklist (11 checks across knowledge layer, provenance, path references, directories, and manifest), and final summary template: see `${CLAUDE_SKILL_DIR}/references/verification-manifest.md`.

## Verification Checklist (Summary)

Consolidated pass/fail checklist (11 items covering sentinel, knowledge, provenance, disciplines, deliverables, stale path refs, the SDLC root, manifest, agent memory): see `${CLAUDE_SKILL_DIR}/references/verification-manifest.md` § "Verification Checklist".

## Red Flags

Common anti-patterns and corrections (11 entries covering re-porting safety, transformation assumptions, sentinel lifecycle, seed tool selection): see `${CLAUDE_SKILL_DIR}/references/red-flags.md`.

## Integration

**Feeds in:**
- `ops/sdlc/knowledge/**/*.yaml` and `**/*.md` — local knowledge stores and knowledge documents
- `ops/sdlc/disciplines/**/*.md` — local discipline files
- `ops/sdlc/knowledge/provenance_log.md` — provenance records, if the project has the file
- `docs/current_work/**/*.md` and `docs/chronicle/**/*.md` — deliverable docs
- `.claude/agents/*.md`, `.claude/skills/**/*.md`, `ops/sdlc/**/*.md` outside `knowledge/` and `disciplines/`, and `CLAUDE.md`'s SDLC region — transformation targets

**Feeds out:**
- Neuroloom knowledge entries (knowledge YAMLs and documents, disciplines, deliverable docs), keyed by the same extractor the adapter's handlers use, and `sdlc:provenance` memories
- Transformed agent and skill files (local filesystem — `ops/sdlc/knowledge/` refs replaced)
- `.sdlc-manifest.json` (updated at project root, including its `adapter` block)
- Sentinel memory (managed server-side by `seed()` — not written by this skill)

**Does NOT replace:** `sdlc-initialize` (a fresh install) or `sdlc-migrate` (moving to a newer z-sdlc
release). Both are z-sdlc's own skills, which call this plugin through its adapter handlers.

**After port:**
- `sdlc-migrate` can update the workspace to newer z-sdlc releases without re-porting
- The SessionStart hook (`sdlc_pyhooks.session_start`, run through `hooks/hooks.json`) begins checking versions against the workspace sentinel
- Agent files now retrieve knowledge via `memory_search` instead of local file reads

---

## Error Handling

Per-stage failure modes and recovery procedures (Stage 1 pre-flight, Stage 2 cancellation, Stage 3a/3b/3c ingestion, Stage 4 transformation, Stage 5 manifest/verification): see `${CLAUDE_SKILL_DIR}/references/recovery-procedures.md`.

