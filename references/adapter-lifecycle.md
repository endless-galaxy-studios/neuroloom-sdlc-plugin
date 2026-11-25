# Adapter Lifecycle Handlers — Neuroloom SDLC Plugin

Phase handler instructions for the z-sdlc adapter lifecycle protocol. Upstream's `sdlc-initialize` and `sdlc-migrate` read this file and execute the relevant H2 section at each phase.

**Required reading before any phase:** `${CLAUDE_PLUGIN_ROOT}/references/pattern-mapping-rules.md` must be read from disk before executing `post-file-write`. Do NOT reconstruct transformation rules from memory.

**Pre-flight:** `${CLAUDE_PLUGIN_ROOT}/references/preflight.md` lists the environment checks (Neuroloom API reachability, MCP tool availability, GitHub API access, disk space). Upstream doesn't run that file, so only its check 0, the SDLC root, is enforced, as step 0 of three phases (below). The others are worth running by hand before a migration, and a phase that needs the API fails on its first call without them.

**SDLC root check: halt before any phase.** This plugin supports one SDLC root, `ops/sdlc`. Upstream reads this file before its first phase fires: during `sdlc-migrate`'s pre-flight, before any write, and during `sdlc-initialize` before its Phase 1 copies (z-sdlc 3.0.0 finds the adapter first, so `post-file-write` runs on each copy). Run `preflight.md` check 0 then, and if it fails, stop the operation with that check's message. Do not let upstream pick `.claude/sdlc/` as `[sdlc-root]`; every audit this adapter runs reads `ops/sdlc`, and over another root it would pass without having looked. Upstream promises only to look for this file's H2 phase headings, not to act on this paragraph, so `knowledge-seed`, `knowledge-update` and `post-file-write` each run the check as their step 0. Which of them fires first depends on the operation and on which files a release changes (a knowledge-only release may write no file `post-file-write` matches), and the step costs one command.

**Authority in a Neuroloom-backed project: the adapter wins.** CD decided (2026-10-29) that in a project with `neuroloom_backend: true` the adapter's transforms are authoritative where they differ from z-sdlc's verbatim or exempt treatment. Three cases: (1) `process/knowledge-routing.md` is this plugin's Neuroloom variant (`docs/knowledge-routing.md`), not z-sdlc's phrasing contract; (2) `agents/sdlc-reviewer.md` has its phrasing-contract checklist rewritten to the Neuroloom canonical forms, because the reviewer must check files that use those forms (only the quoted span of a `- [ ] No` anti-residue item stays verbatim); (3) knowledge-layer paths in Integration `Uses:`, `Depends on:`, `Feeds into:`, `DRY notes:` and `Knowledge routing:` lines are rewritten, not preserved. An audit that finds these files differing from z-sdlc is looking at the adapter's design, not at drift. One consequence: the project holds no copy of z-sdlc's phrasing contract, so a z-sdlc phrasing change shows up at migration time (the `[contract-change]` entries), not by reading the installed files.

**Contract change version gate:** Upstream reads `adapter.json → supported_zsdlc_version` during pre-flight. `adapter.json` carries only the `zsdlc` keys: the pre-rename keys z-sdlc v1.9.0 and earlier read are gone, since this plugin requires 3.0.0. If any `[contract-change]` entry in the migration range has a version above the adapter's declared support, upstream halts with a message identifying the uncovered entries. The adapter maintainer must update `adapter.json` after verifying handler coverage before migration can proceed.

**Halts and their recoveries.** A phase that halts may do so after upstream has already written files: `sdlc-migrate` §2.1 copies scripts, YAML, the factory bundle (`.github/`) and `.gitignore` before the first `.md` reaches `post-file-write`, and `knowledge-update` runs in Phase 2 after the file writes; `sdlc-initialize` writes its manifest in Phase 1 and its agents in Phase 4 before `knowledge-seed`. Whatever halts in this file (a step that says halt, a phase whose **On failure** is halt, a transformer HALT), its message ends with its operation's recovery from this table, and there are only two. `post-operation` is the exception: it is `warn-continue`, upstream writes the manifest after it, and its REGRESSION reports carry their own recovery (§ Recovery on failure), which also puts the manifest back. Whatever halts, a headless run ends with status `failed` and the halt's message (z-sdlc's protocol § Phase Failure Semantics).

| Operation | Recovery | Why |
|---|---|---|
| `/sdlc-migrate` | **Save, then undo only a clean run, then re-run.** `sdlc-migrate` has no dirty-tree check, and git can't tell a run's writes from changes that were there before it (CD's own edits, an initialize never committed). So first save everything, whatever happens next, in `<dir>` = `$(git rev-parse --git-path sdlc-undo)/<timestamp>/` (inside the repository's git directory, which `--git-path` finds even in a worktree or submodule where `.git` is a file: untracked, and not cleared like a temp directory; give CD the path). If any save step fails, undo nothing (outside a git repository, where every git step fails, copy `.sdlc-manifest.json` to `.sdlc-manifest.json.pre-undo-<timestamp>`, then restore only the manifest, from its snapshot): `git diff --binary > <dir>/pre-undo.patch` (what a checkout would throw away; staged changes stay in the index) and a copy of every untracked file `git status --porcelain -z --untracked-files=all` lists, at its path under `<dir>/new/` (`-z` keeps a path with spaces whole), and a copy of `.sdlc-manifest.json` itself at `<dir>/sdlc-manifest.json` whatever git makes of it (a git-ignored manifest is in neither the patch nor that list). Then ask CD whether the tree was clean (everything committed) when the run started; with no one to ask, the answer is no. Git overrules a yes: a staged change other than upstream's `.claude/agent-memory/` deletions, a change outside `.claude/`, `ops/sdlc/`, `CLAUDE.md`, `.github/`, `.gitignore`, `docs/_index.md` and `.sdlc-manifest.json` (the paths a migration writes), or an untracked `.sdlc-manifest.json` means the tree wasn't clean. Leave `.sdlc-transaction-log` out of the check and out of the undo: upstream appends to it on every run, and the recovery reads it. **Clean:** everything `git status` lists is the run's: restore each changed tracked file with `git checkout -- <path>` (`.sdlc-manifest.json` from the run's manifest snapshot when there is one), put back each staged deletion with `git restore --staged -- <path>`, and remove each new file (its copy is saved). **Not clean, or not sure:** change nothing, with one exception: if upstream has already rewritten `.sdlc-manifest.json` (§4.5: a post-operation REGRESSION, or a run that reached the target tag), put it back alone from the run's **manifest snapshot** (below), which holds it as it was before the run, uncommitted keys included; without a snapshot, `git checkout -- .sdlc-manifest.json` when git tracks it, and when git doesn't either, CD sets its `source_version`, `source_version_sha` and `last_applied_contract_id` back by hand to the run's from-release (in its report). Otherwise a re-run stops at "Already on [target_tag]". Show CD the list and the saved copies; CD undoes the rest by hand, or runs `/sdlc-migrate` again without undoing and, at its drift questions, takes upstream's version for the files this run already wrote. Either way, fix the cause the halt names before running again. | Nothing is lost on any path: the patch and copies hold every change, and Neuroloom's writes are idempotent upserts, so the re-run repeats them safely. |
| `/sdlc-initialize` | **Keep, then finish by hand.** Undo nothing: the manifest Phase 1 wrote carries this plugin's in-progress and workspace keys, and undoing it would leave Neuroloom records no manifest accounts for. Fix the cause, then go back to the start of the upstream phase that called the halted handler and follow `.claude/skills/sdlc-initialize/SKILL.md` from there: upstream calls `project-knowledge` and `post-file-write` once per item or file, so a halt partway through a phase leaves the rest of that phase's items unsent, and every handler repeats its own writes safely. A `post-file-write` halt during Phase 1's copies comes before the manifest exists (z-sdlc 3.0.0 finds the adapter before copying): after fixing the cause, send every file Phase 1 has written so far through `post-file-write` before carrying on with Phase 1, since Phase 1 skips a file that exists and would leave those untransformed; and never re-run `/sdlc-initialize` plainly after a Phase 1 halt: with `ops/sdlc/` on disk and no manifest, it resumes past Phase 1 without the adapter. For `knowledge-seed`, which is the whole of Phase 6, run its section from this file (the pre-seed check, steps 0 to 9 and the post-seed check), then Phase 5's adapter check, then Phase 7 onward. A plain re-run reports "Already initialized" once Phase 4 has made the agents, and never reaches the phases still owed. In a new session, find the inputs again: `PLUGIN_DIR` is the `installPath` of the enabled `neuroloom-sdlc@endless-galaxy-studios` entry in `claude plugin list --json`, the one z-sdlc's § Finding the plugin picks (this project's install, project scope then local, else the user's, never another project's; else a copy vendored in the project); `[z-sdlc-path]` is any clone of the manifest's `source_repo` that has the install's release, either a full `git clone <source_repo> <dir>`, or a shallow one plus `git -C <dir> fetch --depth 1 origin tag <source_version>` (for an untagged install, `git -C <dir> fetch --depth 1 origin <source_version_sha>`), then `git -C <dir> checkout --detach <that ref>`: the phases after the seed read upstream's files from the clone's working tree, not from the tag. Upstream's bootstrap clone is shallow and may be gone. | Nothing upstream writes on initialize is worth undoing, and every Neuroloom write repeats safely. |

**The manifest snapshot (migrate).** Whichever of this plugin's phases runs first in a `/sdlc-migrate` (`post-file-write` step 0 or `knowledge-update` step 1; both steps say so) copies `.sdlc-manifest.json` to `$(git rev-parse --git-path sdlc-undo)/<run_id>/manifest-before.json` before anything else, if that copy doesn't exist yet (outside a git repository, to `.sdlc-manifest.json.pre-migrate-<run_id>` beside it; earlier runs' copies are never deleted automatically (a run that crashed mid-rewrite may have left its copy as the only good manifest): list them for CD to remove; there the undo can't save anything else, so it restores only the manifest, from this copy, then deletes the copy). A failed copy halts the phase before any write. Upstream rewrites the manifest's release and file keys only at §4.5 (its pre-flight refreshes just the adapter's version), after every handler, so this copy is the manifest as it was before the run, uncommitted keys included; migrate's recovery restores it when git can't (an untracked manifest, or uncommitted keys such as a decision in `declined_files`).

**The workspace check.** Every phase that writes to Neuroloom first finds out which workspace the API key reaches: `memory_search(query="SDLC workspace sentinel", tags=["sdlc:sentinel"])` echoes it as `filters.workspace_id` in every successful response, even when nothing matches. A response without it (an error, a timeout) halts the phase: it says nothing about the workspace. When the manifest records a `workspace_id` and the filters name another, halt before any write: the key reaches a different workspace from this project's, and spot checks of knowledge ids can't tell (other projects' workspaces hold most of the same ids). On `/sdlc-migrate` a manifest with no `workspace_id` halts too: `knowledge-seed` and `/sdlc-port` record it with the id-scheme marker, so a marked manifest without one was edited by hand; add the id of this project's workspace and re-run. The halt message names both ids.

---

## knowledge-seed
**On failure:** halt

Seed the workspace from upstream's knowledge layer with the plugin's extractor (`${CLAUDE_PLUGIN_ROOT}/skills/sdlc-port/scripts/extract_sdlc_knowledge.py`, in `--upstream` mode) and `sdlc_seed`. The extractor is the one owner of `knowledge_id`s: `/sdlc-port` runs the same script on a project's own files, so a ported project and an initialized one key the same knowledge the same way, and `knowledge-update` finds both. No flat YAML files are written to `[sdlc-root]/knowledge/`, and no `provenance_log.md` either: provenance is kept as memories tagged `sdlc:provenance` (see § "Provenance records" in `${CLAUDE_PLUGIN_ROOT}/references/pattern-mapping-rules.md`).

### Pre-seed: Check existing knowledge

Before ingesting, check what already exists in the workspace for each domain:

```
memory_search(query="SDLC knowledge entries", tags=["sdlc:knowledge", "sdlc:domain:{domain}"], tags_match="all")
```

Run **The workspace check** (top of this file) on this search's response; a manifest with no `workspace_id` yet passes here, and step 5 records the one the filters name. Whether the workspace already holds SDLC records, decide by exact tag, `memory_get_index(tags=[<t>], limit=1)` for each of `sdlc:sentinel`, `sdlc:seed`, `sdlc:knowledge` and `sdlc:discipline` (records older versions wrote can exist without a sentinel), not by the search above (it ranks by relevance, and a record with no embedding yet, or one in no domain, can be missed). A failed lookup halts: it says nothing about the workspace. If any returns a row, the manifest has `"knowledge_id_scheme": 2` or `knowledge_seed_in_progress`, and it has no `workspace_id`, halt: the marker says these are this install's records, but nothing ties them to this workspace (a marker without its workspace was edited by hand). If any returns a row, this is a re-initialization, or the continuation of this install's own seed: when the manifest has `"knowledge_seed_in_progress": true` with this `workspace_id` (step 5 wrote it before the first call), carry on. If the manifest has neither that nor `"knowledge_id_scheme": 2`, nothing says whose those entries are or which ids they use: this project's from before 0.7.0, another project's in the same workspace, or an earlier install of this one whose manifest was written afresh (initialize's Phase 1 writes a new one). Seeding now could put the current ids beside other ones and then write the marker over both. Halt before any Neuroloom write, naming the workspace the search's applied filters show, and list the three possibilities for CD: a conversion (`knowledge-update` step 1), a workspace of its own, or, when CD knows the records are this project's from a 0.7.0 initialize, setting `"knowledge_seed_in_progress": true` and `workspace_id` (not the scheme marker, which step 6 writes once the seed is complete) and running this section again. The recovery is initialize's (**Halts and their recoveries**, top of this file). Otherwise count entries tagged `sdlc:project-specific` (`memory_get_index(tags=["sdlc:project-specific"], limit=500)`) — these will be preserved (never overwritten). Report the count to upstream so it can include it in its confirmation gate, or to CD when this section is run by hand:

```
Re-initialization detected. {N} project-specific knowledge entries will be preserved.
WARNING: Base importance scores will be reset to seed values. Accumulated
importance adjustments from memory_rate feedback will be lost for non-project-specific entries.
```

Upstream presents this in its Phase 4 confirmation gate alongside its own summary.

### Procedure

0. **SDLC root.** Run `preflight.md` check 0 first. If it fails, this phase fails: halt with that check's message before any Neuroloom write.

1. **Resolve the source.** Seed the knowledge of the commit this initialize installs, never a newer or older one. `SOURCE_REF` is the manifest's `source_version` (`sdlc-initialize` writes it in Phase 1, before this phase) when `git -C [z-sdlc-path] rev-parse --verify "<it>^{commit}"` succeeds; otherwise its `source_version_sha` when that resolves (an untagged install records `"unknown"` and the commit). If neither resolves, halt: seeding `HEAD` would label newer content with the install's release, which happens when a recovery runs later against a clone that has moved on. `SDLC_VERSION` is the manifest's `source_version` (or, when it is `"unknown"`, the short commit id: the first 7 characters of `source_version_sha`); `sdlc_seed` records it as `sdlc:seed-version:{SDLC_VERSION}` on every entry. `PLUGIN_DIR` is the directory upstream found for this plugin (contract 0025): write it out in the commands below, because `${CLAUDE_PLUGIN_ROOT}` is not set in a Bash call. The extractor needs `python3` with `pyyaml` (`python3 -c 'import yaml'`); without it, halt and say so.

2. **Extract.** Run the extractor on upstream's knowledge and disciplines at `SOURCE_REF`:
   ```bash
   set -o pipefail
   SRC="$(mktemp -d)" && echo "$SRC" \
     && git -C [z-sdlc-path] rev-parse --verify "$SOURCE_REF^{commit}" \
     && git -C [z-sdlc-path] archive "$SOURCE_REF" knowledge disciplines | tar -x -C "$SRC" \
     && python3 "$PLUGIN_DIR/skills/sdlc-port/scripts/extract_sdlc_knowledge.py" --upstream \
     --knowledge-dir "$SRC/knowledge" --disciplines-dir "$SRC/disciplines" \
     --manifest .sdlc-manifest.json --version "$SDLC_VERSION" --output "$SRC/seed.json"
   ```
   It prints the seed files it wrote, one per line, each within the API's limits (500 entries, and a size under the 1 MiB upload limit); it writes none when there is nothing to seed. A non-zero exit fails this phase: the extractor refuses duplicate ids, a knowledge file's id in the `discipline:` namespace, a tag Neuroloom adds itself and a malformed `tags` value, rather than guess which entry wins. They hold every section and field of every knowledge YAML, every knowledge Markdown document (z-sdlc's `knowledge/search/*.md`, for example: agents reach them only through Neuroloom, since the map that pointed at them is gone), and, for each discipline file, a `discipline:<name>:framework` entry (every section outside the project's data, as z-sdlc's `sdlc-migrate` §2.3 divides a discipline file) plus one entry per seeded parking-lot insight upstream ships. They leave out `agent-context-map.yaml` (configuration, not knowledge), the READMEs, `provenance_log.md`, and any knowledge file whose installed path is in `.sdlc-manifest.json` → `declined_files` (z-sdlc `process/project-section-markers.md` § Deleted Files). Don't build entries by hand, and don't send knowledge through `document_ingest_batch`: its parser keys entries differently, and a keyed Markdown document sent there collapses to its last section.

3. **Evaluate applicability.** (A seed file left with no entries after this step is not sent: the API rejects an empty call.) For each knowledge YAML (the entries share its `source_path`), check its `project_applicability.relevant_when` field against the project profile. Apply `action_if_irrelevant`: `keep` (seed regardless), `customize` (rewrite its entries' content for the project stack in the seed files), `remove` (delete its entries from the seed files, and record it in `.sdlc-manifest.json` → `declined_files` under the path it would have had, `"[sdlc-root]/knowledge/<path>": {"why": "not relevant: <its relevant_when>", "decided": "<CD, or knowledge-seed>, <date>"}`, so no later update seeds it).

4. **Spec-relevant importance.** Prompt CD to select which domains inform spec writing, record them in `.sdlc-manifest.json` → `spec_relevant_domains`, and set `importance` to `0.9` on the entries of those domains in the seed files before sending them. `knowledge-update` applies the same boost to every file it sends, since the server keeps an entry's importance across a content update only when `memory_rate` feedback set it. **No ask tool** (a headless run, or `sdlc-initialize` run inside a subagent): don't choose for CD and don't boost anything. Nothing later depends on the answer (upstream's own spec-relevance step, `sdlc-initialize` 6d, leaves every store `false` when CD skips it), so the run doesn't stop: list the question in its result with the domains and a proposed set, as z-sdlc's `process/headless-mode.md` § The Rule says for a question the next step doesn't depend on. CD's later answer can't be applied to the rows already seeded: the API refuses any edit to an `sdlc_knowledge` memory (ADR-11), and re-sending an unchanged entry leaves its importance alone. Record it in `spec_relevant_domains` all the same: it takes effect as `knowledge-update` sends those domains' entries (it boosts every file it sends), which is only the ones upstream later adds or changes; say so in the result.

5. **Mark the seed as started, then seed every file with `skip_deprecation: true`.** First set `"knowledge_seed_in_progress": true` and remove `knowledge_id_scheme` if it is there (a re-seed isn't complete until step 6), and set `workspace_id` from the pre-seed search's applied filters when the manifest has none, in `.sdlc-manifest.json` (upstream wrote it in Phase 1): a re-run after a failed file then finds the files that did go in and carries on instead of halting at the pre-seed check. Then seed. stdio: `sdlc_seed_from_file(path=<file>, skip_deprecation=true)`; HTTP: `sdlc_seed_get_upload_url(path=<file>, skip_deprecation=true)`, then run the returned `curl_command` with `-sS --fail-with-body` in place of `-s`. A file succeeded only when the response holds all four counts (`created`, `updated`, `unchanged`, `deprecated`); anything else (`detail`, `error`, a non-2xx status, an expired upload token) is a failure. Without the flag, `sdlc_seed` marks every earlier seed memory the call leaves out as `sdlc:deprecated`, whatever its version or origin, and the weekly `cleanup_deprecated_sdlc_entries` job (Sundays, 12:00 UTC) deletes them: the second file would retire the first file's entries. This plugin never retires entries automatically; `knowledge-update` lists what upstream removed, for CD.

6. **Errors, then the complete marker.** A failed file (step 5) fails this phase: halt, naming the file, with initialize's recovery (**Halts and their recoveries**): every file is sent again, safely, and entries already written come back `unchanged`. The server rejects a whole call for one bad entry, so nothing from that file was written. When every file succeeded, set `"knowledge_id_scheme": 2` and remove `knowledge_seed_in_progress`. The marker means the seed is complete: `knowledge-update` requires it, so a migration of a half-seeded workspace halts instead of sending only a delta and leaving the missing entries missing for good.

7. **Sentinel note.** The sentinel memory is managed server-side by `sdlc_seed`. Do NOT create or update it. Verify after seeding by exact tag, `memory_get_index(tags=["sdlc:sentinel"], limit=1)`: the call just reset its embedding, so a relevance search may not find it yet.

8. **No agent-context-map.** A Neuroloom project keeps none: agents reach knowledge through their `memory_search` calls. `sdlc-initialize` Phase 1 copies `[sdlc-root]/knowledge/agent-context-map.yaml`. Remove it the way z-sdlc removes any framework file a project doesn't want (`process/project-section-markers.md` § Deleted Files: deleted and recorded, never just deleted):
    - `rm -f ops/sdlc/knowledge/agent-context-map.yaml` (git records the deletion if it tracked the file). On `/sdlc-initialize` this is the copy Phase 1 just made. When another operation's recovery runs this section by hand, remove the map only as `knowledge-update` step 11 does (git tracks it and shows no change), and otherwise leave it and list it: it may hold routing nobody has committed;
    - when the map was removed, add `"ops/sdlc/knowledge/agent-context-map.yaml": {"why": "Neuroloom project: agents reach knowledge through memory_search, no map", "decided": "<knowledge-seed or knowledge-update>, <date>"}` to `.sdlc-manifest.json` → `declined_files`, so a later migration neither asks about the missing file nor copies it back;
    - and, when it was removed, drop the file's `installed_files` entry, if it has one, and then lower `file_count` by one.

    Upstream does the rest (contract 0024): with the map recorded as declined, `sdlc-initialize` skips Phase 5, and its Phases 9a, 10 and 11 treat knowledge as reaching agents through this adapter. Post-operation Check 6 reports a map that is still there.

9. **Phase 1's knowledge and discipline copies.** With the map gone the knowledge layer is this plugin's (contracts 0024 and 0026): it seeds those files from the z-sdlc source (step 2), `knowledge-update` keeps them up to date, and `sdlc-migrate` leaves alone each file this step removes (off disk, no `installed_files` entry, not declined). So once steps 2 to 7 have succeeded, remove the copies `sdlc-initialize` Phase 1 made of the files Neuroloom now holds, with step 8's bookkeeping but no new declined record. Only on `/sdlc-initialize` (its Phase 6, its recovery re-running this phase, or the initialize audit's fix for a knowledge-layer regression): when `knowledge-update` step 1's recovery runs this section by hand on an empty workspace, skip the removal, since the files under those directories are then the project's own, which this seed of upstream's knowledge doesn't hold.
    - for each `installed_files` key under `ops/sdlc/knowledge/` or `ops/sdlc/disciplines/` that a seed file this phase sent names as an entry's `source_path` (relative to `ops/sdlc/knowledge/` for an entry tagged `sdlc:knowledge`, to `ops/sdlc/disciplines/` for one tagged `sdlc:discipline`), or that `declined_files` lists (step 3's decisions, or an earlier run's), and whose file is on disk with content that still matches its recorded hash (`installed_files[<path>].sha256`, the first column of `shasum -a 256 <path>`) and is byte for byte the file this phase seeded from (`cmp -s ops/sdlc/<rel> "$SRC"/<rel>`, where `<rel>` is the key without its `ops/sdlc/` prefix, such as `knowledge/coding/x.yaml`: Phase 1 copies from the clone's working tree, which can be ahead of `SOURCE_REF`): `rm -f` the file and drop the entry; then set `file_count` to the number of entries left;
    - never record them in `declined_files`: a declined record would stop this plugin updating the entry, and a file it handles has no copy on disk to go missing;
    - keep any other file there with its entry, and name it in this phase's report: one no seed entry names (a README, a diagram, `provenance_log.md`, the project's own record: their text isn't in Neuroloom), one `installed_files` doesn't list, or one edited since Phase 1. They stay on disk with their entries: `sdlc-migrate` updates a kept discipline or other Markdown file on its ordinary path (contract 0026), and a kept knowledge YAML stays as the project left it (`knowledge-update` step 11 reports it when upstream changes it).

    Upstream's Phases 7, 8 and 9a then hand the project's own content to `project-knowledge` instead of writing these files. Re-running this phase from its start finds nothing left to remove.

### Post-seed: Domain tag verification

After seeding completes, verify domain routing works for each created agent:

```
memory_search(query="SDLC knowledge entries", tags=["sdlc:domain:{domain}"])
```

This confirms agents can find their relevant knowledge via tag-scoped queries.

---

## project-knowledge
**On failure:** halt

Run **The workspace check** (top of this file) first. This phase runs after `knowledge-seed` (contract 0024), which records the manifest's `workspace_id`: if it has none, halt before any write, since nothing has checked yet whether this workspace holds someone else's records, and say upstream handed an item over out of order. Re-running that same phase would halt again: the item has to be handed over after Phase 6, which is upstream's to fix. `sdlc-initialize` hands this phase each piece of the project's own knowledge-layer content (contract 0024), with its kind, the file and section it would have gone to, and the content. Store each as a memory tagged `sdlc:project-specific`, which `knowledge-update` never overwrites and `sdlc_seed` never deprecates, and write nothing to the file: the project's agents search Neuroloom, not `ops/sdlc/`.

| Kind | Upstream source | Store as |
|------|-----------------|----------|
| `discipline-context` | Phase 7: a discipline's Project Context | `memory_store(title="<discipline> project context", content=<the section>, tags=["sdlc:discipline", "sdlc:discipline:<name>", "sdlc:project-context", "sdlc:project-specific"], memory_type="general")` |
| `knowledge-entry` | Phase 8: an entry for a knowledge file (testing gotchas: `ops/sdlc/knowledge/testing/gotchas.yaml`) | `memory_store(title=<its title>, content=<its fields>, tags=["sdlc:knowledge", "sdlc:domain:<the target's subdirectory>", "sdlc:type:<gotcha, rule or entry, from the target's pattern>", "sdlc:project-specific"], memory_type="discovery")` |
| `maturity-tracker` | Phase 9a: the Process Maturity Tracker for `disciplines/process-improvement.md` | `memory_store(title="Process maturity tracker", content=<the table and its note>, tags=["sdlc:discipline", "sdlc:discipline:process-improvement", "sdlc:maturity-tracker", "sdlc:project-specific"], memory_type="general")` |

Give each item a key tag, `sdlc:item:<first 12 hex characters of sha1("<kind>|<target file>|<section>|<title>")>`, and a suffix `:<n>` for the n-th item (from 2) with the same key in one pass through the phase: upstream hands items in the same order every time, so a phase re-run from its start (initialize's recovery) gives each item the same key again. Before storing, look the key up (`memory_get_index(tags=["<key>"], limit=1)`; a failed lookup halts); `memory_update` a match, store otherwise. Pass `memory_update` the row's own tags (it replaces them, so leaving one out would drop the key). If `memory_store` is refused as a duplicate (the API keeps one memory per type, title and text in a workspace), the row exists without its key (stored before keys, or by an earlier pass): find it among the kind's tags by title (`memory_get_index`), then by exact text (`memory_get_detail` on each title match: two same-titled rows can differ only in text), and `memory_update` it with its tags plus the key, instead of halting on every re-run. Same-titled items keep separate rows, and a re-run or a re-initialization updates each in place instead of adding a copy. A failed `memory_store` or `memory_update` fails the phase (halt): that content has no other home.

---

## knowledge-update
**On failure:** halt

Update the workspace to the release this migration installs with the same extractor `knowledge-seed` uses and `sdlc_seed`, which creates or updates each entry by its `knowledge_id`. No flat files are created, diffed, or cleaned up.

**No agent-context-map: skip `sdlc-migrate` §3.3.** A Neuroloom project keeps none (post-operation Check 6): agents reach knowledge through their `memory_search` calls, so an upstream map change (a role added, a file mapped to a role, a file restored) needs nothing. When this migration reaches §3.3, skip its map updates and never create the map, whatever the running copy of `sdlc-migrate` says. A map an earlier initialize or a port that kept its files left behind is removed and recorded by step 11, as `knowledge-seed` step 8 does, when git shows it unmodified; otherwise step 11 lists it for CD. A project's installed copy predates z-sdlc's own adapter line in §3.3 until a migration has installed it, and the run follows the copy it started with. From z-sdlc 3.0.0 (contracts 0024 and 0026), with the map gone `sdlc-migrate` decides file by file: a file under `ops/sdlc/knowledge/` or `ops/sdlc/disciplines/` that is off disk, has no `installed_files` entry, isn't declined and was upstream's at `source_version` is one this plugin took, and migrate leaves it alone; every other file there follows its ordinary path, and step 11 takes the copies whose every entry it confirms Neuroloom holds.

### Procedure

0. **SDLC root.** Run `preflight.md` check 0 first. If it fails, this phase fails: halt with that check's message before any Neuroloom write.

1. **Resolve versions and the id scheme.** `[target_tag]` comes from the running migration and labels the seed: the release whose knowledge this phase sends (not the latest release `sdlc_get_version` reports, which can differ). The baseline is the release the project's knowledge came from: the manifest's `source_version` when `git -C [z-sdlc-path] rev-parse --verify "<it>^{commit}"` succeeds, otherwise its `source_version_sha` when that resolves (an initialize from an untagged commit records `"unknown"` and the commit). `PLUGIN_DIR` and the `pyyaml` check are as in `knowledge-seed` step 1. Take **the manifest snapshot** (top of this file) if no earlier phase of this run did. Check the id-scheme marker first, then run **The workspace check**, so a workspace from before 0.7.0 gets this message rather than the workspace check's. Then confirm the workspace still holds a sentinel (`memory_get_index(tags=["sdlc:sentinel"], limit=1)`): a marked workspace with none was emptied or reset, and a delta sent into it would leave every unchanged entry missing. Halt, with migrate's recovery. If other SDLC rows remain (`memory_get_index(tags=[<t>], limit=1)` for `sdlc:seed`, `sdlc:knowledge` or `sdlc:discipline` returns one: only the sentinel is gone), stop and ask CD: a re-seed would overwrite edits made only in Neuroloom. If the workspace is empty, run `knowledge-seed`'s section by hand from this file (it seeds upstream's knowledge at the project's release), then `/sdlc-migrate` again; a ported project's own knowledge isn't upstream's and comes back only from a Neuroloom backup or its files' git history. The manifest must have `"knowledge_id_scheme": 2`, which `knowledge-seed` (once its seed is complete) and `/sdlc-port` write from 0.7.0 on. With `"knowledge_seed_in_progress": true`, whatever else is set, an initialize's seed stopped partway; and with an `adapter` block and no `neuroloom_backend`, whatever else is set (the scheme marker included), an initialize never finished: its last check writes `neuroloom_backend`, and `/sdlc-port` writes it too, so a migration would pass here and then fail post-operation Check 4 on every re-run. Either way: halt, undo this migration as migrate's recovery says, finish the initialize with initialize's recovery, then run `/sdlc-migrate` again (sending only a delta would leave the missing entries missing). With `"port_in_progress": true` and no `ported_at`, a `/sdlc-port` stopped before it finished: halt and say to finish it with `/sdlc-port` first. With neither key otherwise, the workspace was seeded under earlier ids (`document_ingest_batch`'s `{file}:{key}` and whole-file `disciplines:<stem>` records, the pre-0.7.0 handlers' `{stem}:{key}`, or a hand-run seed's own), and this phase can't tell what the project changed. Halt, before any Neuroloom write, with migrate's recovery (**Halts and their recoveries**), and say: this workspace was seeded before 0.7.0 and needs a one-time conversion to the current ids, which this release doesn't do. Don't improvise one. Rebuilding from the project's files, even ones restored from git, loses what happened since they were written: upstream entries later migrations added (a 0.7.0 review's replay of the one such workspace's port-time files lacked 295 of the current release's 614), and edits made only in Neuroloom, which a re-seed overwrites. A conversion has to start from the workspace's own rows and needs CD's go-ahead, since it changes live data.

   **No baseline** (neither key resolves): there is nothing to compare, so sending upstream's every entry would overwrite whatever the project changed. Don't send anything. Halt, with migrate's recovery, and ask CD to set `source_version` (or `source_version_sha`) to the release the project's knowledge came from. A guess errs safe: a baseline older than the truth turns more entries into conflicts, held back for CD, rather than overwriting anything.

2. **Extract both releases, as a delta.** Fail closed: an archive of a bad ref leaves an empty directory and still exits 0, and an empty baseline would make every upstream entry look new.
   ```bash
   set -o pipefail
   set -e
   NEW="$(mktemp -d)"; OLD="$(mktemp -d)"; echo "NEW=$NEW OLD=$OLD"
   git -C [z-sdlc-path] rev-parse --verify "[target_tag]^{commit}" && git -C [z-sdlc-path] archive "[target_tag]" knowledge disciplines | tar -x -C "$NEW"
   git -C [z-sdlc-path] rev-parse --verify "$BASELINE^{commit}" && git -C [z-sdlc-path] archive "$BASELINE" knowledge disciplines | tar -x -C "$OLD"
   python3 "$PLUGIN_DIR/skills/sdlc-port/scripts/extract_sdlc_knowledge.py" --upstream \
     --knowledge-dir "$NEW/knowledge" --disciplines-dir "$NEW/disciplines" \
     --baseline-knowledge-dir "$OLD/knowledge" --baseline-disciplines-dir "$OLD/disciplines" \
     --manifest .sdlc-manifest.json --version "[target_tag]" --output "$NEW/seed.json"
   ```
   Any non-zero exit fails this phase (halt); the extractor itself exits non-zero on a missing or empty baseline. It prints the seed files it wrote (the entries upstream added or changed), then the delta file: `new`, `changed` (with both releases' content), `removed`, `unchanged_count`, `probe_ids`, a `noop_entry`, and `probe_entries` (up to 50 no-op candidates, `noop_entry` first). `--manifest` leaves out every knowledge file the project declined, in both releases. Disciplines are never left out: their framework sections are updated here whatever `declined_files` says about the on-disk copy. Record the paths (the two directories and the files it printed) and use them literally in the steps below: a shell variable doesn't survive from one Bash call to the next. The extractor also exits non-zero when a target directory is missing or empty, so a bad `[target_tag]` can't pass as "upstream removed everything".

3. **No id-scheme probe.** The marker (step 1) and the workspace check decide whether this workspace's ids are the extractor's. Looking up sample ids can't: a project may have removed those entries, and other projects' workspaces hold most of the same ids. Step 4 still reads the `probe_entries` rows, for the no-op send.

4. **Decide each entry with the classifier, not by hand.** For every `new` and `changed` id, read the workspace's row, and read the `probe_entries` rows (up to 50 no-op candidates, `noop_entry` first) ten at a time, in order, re-running the classifier after each ten and stopping once `noop_ids.txt` is non-empty (the classifier skips candidates it wasn't given): `memory_get_index(tags=["sdlc:knowledge-id:<id>"], limit=1)`, then `memory_get_detail(id=<row>, include_related=false)`. Write them to a file as `{"<id>": {"title": <title>, "content": <its narrative>, "tags": [<tags>]}}`, copying the `narrative` field exactly (it is what the server compares) and the `title` as stored, with `null` for an id not found, then:
   ```bash
   python3 "$PLUGIN_DIR/skills/sdlc-port/scripts/classify_knowledge_update.py" --delta <delta file> --workspace <that file> --output-dir <dir>
   ```
   It sorts each id into one of five outcomes, comparing after normalising line endings and trailing whitespace at the end of the text (indentation and internal spacing count):
   - **send**: a changed entry the workspace still holds as upstream's old text, or a new entry the workspace doesn't have;
   - **already current**: the workspace already holds upstream's new text;
   - **conflict**: the project changed an entry upstream also changed (its text, or its title on upstream's old text: the server refreshes the title with the text, so sending would erase the project's title; such a row also carries the three titles), or the workspace already holds a different entry under an id upstream just added (a project's own `U17` when upstream ships one). Nothing is overwritten;
   - **removed by the project**: a changed entry the workspace doesn't hold;
   - **protected**: a row tagged `sdlc:project-specific`, which the server never updates, so sending it would do nothing. Listed, not sent.
   It writes `send_ids.txt`, `noop_ids.txt` and `report.json`, and exits 2 on a malformed workspace file. Rebuild the seed files from the list instead of editing JSON: run step 2's extractor command again without the two `--baseline-*` flags and with `--only-ids <dir>/send_ids.txt`, into a fresh output path; with an empty list it writes nothing. Send those files, not step 2's. An entry upstream didn't change is never sent, so a correction the project made to it stays. This is the adapter's half of z-sdlc's deviation detection: `sdlc-migrate` leaves the knowledge layer an adapter handles to the adapter (contract 0024). This phase runs in migrate's Phase 2, which asks nothing, so the conflicts (with the three versions) and the project's removals go in the migration report; CD takes upstream's text for a conflict by re-sending that entry alone, after **The workspace check** (top of this file) confirms the API key still reaches the manifest's `workspace_id`: run step 2's extractor command on a z-sdlc clone at the release the workspace is on (`[target_tag]`, or the newer one a later migration moved it to, with `--version` set to that release so the sentinel stays put), without the two `--baseline-*` flags and with `--only-ids` pointing at a file that holds only its id, into a fresh path, and send the file it writes with `skip_deprecation=true` and step 6's importance (0.9 for a spec-relevant domain). Expect `updated: 1`. On `unchanged: 1`, read the row again: if it now holds the target text, the send (or an earlier one whose answer was lost) already worked; if it still holds other text, it is tagged `sdlc:project-specific`, which the server never updates, and CD decides whether upstream's entry should replace it (`memory_delete`, then re-send). `memory_update` can't do it: the API keeps `sdlc_knowledge` memories system-owned and refuses any edit to one (ADR-11). The seed refreshes the title with the text, so this also takes upstream's title, which stops a title conflict recurring when the stored title was an older upstream one (the server doesn't refresh a title whose text didn't change). To keep the stored title instead, set that entry's `title` in the file to it before sending.

5. **List what upstream removed.** The delta's `removed` ids stay in Neuroloom: nothing retires them automatically. List them in the migration report for CD to delete (`memory_delete`) or keep.

6. **Seed, every file with `skip_deprecation: true`,** as `knowledge-seed` step 5 does, with the same success test, after setting `importance` to `0.9` on the entries of the domains in the manifest's `spec_relevant_domains`. Without the flag, each call would mark every seed memory it leaves out as deprecated, and the weekly job would delete them. The server creates new ids and updates changed content; it never modifies an entry tagged `sdlc:project-specific`.

   **When nothing is sent** (no knowledge change in this release, which is common, or every change held back), the workspace's version marker would stay on the old release, because only a seed call moves it; post-operation Check 5 and the SessionStart hook would then report it stale. Rebuild a seed file from the classifier's `noop_ids.txt` (the step 2 command without the `--baseline-*` flags, with `--only-ids <dir>/noop_ids.txt`) and send it with `skip_deprecation=true` like every other file (without it, a one-entry call marks every other seeded entry deprecated, and the Sunday cleanup job deletes them): it holds one entry the workspace already stores byte for byte, so the server answers `unchanged` and still moves the marker. If `noop_ids.txt` is empty, nothing matched exactly: say in the report that the marker stays on the old release.

   Records this phase leaves alone: a project's parking-lot entries (`sdlc:parking-lot`), project context, maturity tracker and other project data, which `/sdlc-port` and the `project-knowledge` phase store; and the whole-file `disciplines:<stem>` records an earlier version of `/sdlc-port` stored (they belong to the pre-0.7.0 scheme, on which step 1 halts).

7. **Sentinel management.** The sentinel is read-only during migration — the server updates its `sdlc:seed-version:{version}` tag automatically when the knowledge re-seed completes. Do NOT write to the sentinel directly.

8. **Verify after re-seed (the discipline framework entries this phase sent, not the ones it held back):**
   ```
   memory_get_index(tags=["sdlc:knowledge-id:{framework_id}", "sdlc:seed-version:{target_tag}"], limit=1)
   ```
   `{framework_id}` is the discipline's entry in the delta file's `framework_ids` (the id the extractor produced: a stem like `team+tools` is sanitized, so don't rebuild it from the filename). `memory_get_index` matches tags exactly and as an AND, so the one row it returns is that discipline's framework entry at the new release. No row is a failed re-seed. Parking-lot entries are the project's and this phase never sends them; a project may have none for a discipline, so their absence says nothing here.

9. **Knowledge layer spot-check.** Sample 3–5 entries this phase sent. Call `memory_search` and verify the content matches the new upstream version and `sdlc:seed-version:{target_tag}` tag is present.

10. **Error handling.** A failed file (the `knowledge-seed` step 5 test) fails this phase: halt, naming the file. The server rejects a whole call for one bad entry, so nothing from that file was written, and earlier files' entries stay as written; re-running the migration sends them again unchanged.

11. **Take the copies Neuroloom holds** (contract 0026). Only when the knowledge layer was this plugin's for the whole run: no `ops/sdlc/knowledge/agent-context-map.yaml` on disk when the migration began, since z-sdlc decides at its pre-flight. Nothing in a run removes the map before this step, so check that it is not on disk now. With a map there (an initialize from before 0.7.0, or a port that kept its files), z-sdlc ran its ordinary path this run and still expects these files, so take nothing. Remove the map and record it declined as `knowledge-seed` step 8 does only when git tracks it (`git ls-files --error-unmatch ops/sdlc/knowledge/agent-context-map.yaml` succeeds) and `git status --porcelain -- ops/sdlc/knowledge/agent-context-map.yaml` prints nothing, so git keeps its last text. If it isn't tracked, or has changes, leave it and list it for CD: it holds routing nobody has committed (or edits this run's §2.1a made when upstream moved or removed a knowledge file), which removing it would lose; until CD removes it by hand, every migration takes z-sdlc's ordinary path. When there is no map on disk: `sdlc-migrate` §2.1 copies, before this phase, each file under `ops/sdlc/knowledge/` and `ops/sdlc/disciplines/` that upstream added since `source_version`, and an older install may have left copies there too (a discipline file is never taken: the delta always leaves out its status and structure, so Neuroloom never holds all of it, and it stays on disk for z-sdlc to update on its ordinary path). Once every file in step 6 has succeeded, run step 2's extractor command again without the two `--baseline-*` flags, with `--output <step 2's target directory>/all.json` (a non-zero exit halts, as in step 2), and read the files it prints (`all.json`, or `all_001.json`, … when split): each entry carries its `knowledge_id` and `source_path` at `[target_tag]` (relative to `ops/sdlc/knowledge/` for an entry tagged `sdlc:knowledge`, to `ops/sdlc/disciplines/` for one tagged `sdlc:discipline`). Use step 2's two directories by their literal paths, since shell variables don't survive between commands. Then:
    - **Take** a file on disk there that one of those entries names, whose content is byte for byte that file at `[target_tag]` (`cmp -s` against `$NEW/<path>`; a copy that matches only the baseline may hold an entry upstream has since moved elsewhere, so it is kept and listed), and every one of whose entries (the entries above that name it) this run checked and found in Neuroloom: each is in the delta (`new` or `changed`) and in `report.json`'s `send` list (step 6 sent it) or its `already_current` list. Only then has this run seen Neuroloom hold all of it. A file with any other entry is kept: an unchanged entry (nothing here looked it up), a discipline's status or structure (the delta leaves them out), or a rule moved between files with its text unchanged. List it for CD as a likely redundant copy instead (not a discipline file, which stays for z-sdlc to update, and not one with an entry the classifier held back, which stays without that label), with how to remove it by hand: `rm` it, drop its `installed_files` entry and lower `file_count` by one, and record nothing in `declined_files` (a declined file is one the extractor never sends again, so its Neuroloom entries would stop updating). For a file the take applies to, `rm -f` it, drop its `installed_files` entry if it has one, and set `file_count` to the number of entries left. Never record it in `declined_files`, and never `provenance_log.md`, the project's own record, which no entry names.
    - **Keep** every other file on disk, with its entry (an older install's unchanged copies included, listed as above): text Neuroloom doesn't hold (a README, a diagram, `provenance_log.md`) and files the project edited. A kept knowledge file whose upstream text changed in this release (`$NEW/<path>` differs from `$OLD/<path>`) goes in the migration report: Neuroloom now holds upstream's new text, and the copy on disk (the project's edit, or an older copy nothing merged) stays as it is, since this plugin doesn't merge files.
    - **List** each file under `knowledge/` or `disciplines/` at `[target_tag]` that no entry names, isn't declined, isn't the map or `provenance_log.md`, and is off disk (a README or diagram an earlier port removed): z-sdlc treats it as one this plugin took and never restores it, and Neuroloom doesn't hold it, so list it for CD in the migration report with the command that restores it from any z-sdlc clone at `[target_tag]` (this run's temporary clone may be gone by then): `f=$(mktemp) && git -C <clone> show [target_tag]:<path> > "$f" && mkdir -p "$(dirname ops/sdlc/<path>)" && mv "$f" ops/sdlc/<path>`, which writes nothing unless `git show` succeeds; a migration records its hash once it touches the file. Post-operation Check 6 points at these lists.

---

## post-file-write
**On failure:** halt
**Applies to:** `[sdlc-root]/**/*.md`, `.claude/agents/*.md`, `.claude/skills/*/SKILL.md`, `.claude/skills/*/references/*.md`, `CLAUDE.md` (its SDLC region only)
**Skip:** `[sdlc-root]/knowledge/**`, `[sdlc-root]/disciplines/**` (their content goes to Neuroloom through `knowledge-seed` and `knowledge-update`; a file kept on disk is data, which the post-operation audit's scans skip and Check 6 looks at)

`CLAUDE.md` is in scope because upstream merges `CLAUDE-SDLC.md` into it (`sdlc-initialize` Phase 2, `sdlc-migrate` §2.1e) and that text carries live knowledge reads, such as `Read [sdlc-root]/knowledge/coding/comment-discipline.yaml`. Only the lines between `<!-- SDLC-START -->` and `<!-- SDLC-END -->` are the framework's; the rest of the file is the project's, and the transformer never touches it (`agents/neuroloom-transformer.md` § "CLAUDE.md").

The `references/*.md` entry is in scope on purpose. A skill's `references/` files carry runtime content (dispatch prompts, procedure detail) that a subagent reads and acts on, and the post-operation audit scans them. The dispatch list MUST include every `.claude/skills/*/references/*.md` that upstream wrote in this phase, plus any that already exist in the project and have never been transformed.

**Step 0 — SDLC root.** Before the first dispatch of the run, run `preflight.md` check 0 (again, if a knowledge phase already ran it). On a migration, first take **the manifest snapshot** (top of this file) if no earlier phase of this run did, then check now what `knowledge-update` step 1 will need: the same manifest states it halts on (no `"knowledge_id_scheme": 2`, `knowledge_seed_in_progress` set, an `adapter` block without `neuroloom_backend`, a `port_in_progress` port), **The workspace check** (top of this file), a sentinel in the workspace, and a baseline that resolves (`source_version`, or `source_version_sha`), in that step's order. If check 0 or any of these fails, halt here with its message, before the transformer writes anything. Upstream calls this phase after it has already written files (at least the first `.md`, and before it the scripts and YAML §2.1 copies), so the message ends with the operation's recovery (**Halts and their recoveries**, top of this file). `[sdlc-root]` must be `ops/sdlc`.

Dispatch the `neuroloom-transformer` agent with the full list of written files. The agent handles the entire transformation pipeline (two-pass Pattern Mapping, MCP preservation gate, seven verification audits) and returns an aggregate pass/fail report.

### Dispatch

```
Dispatch: neuroloom-transformer
Input:
  files: [list of all file paths written by upstream in this phase]
  operation: "initialize" | "migrate"
  plugin_dir: "{PLUGIN_DIR, the directory upstream found for this plugin}"
  sdlc_root: "ops/sdlc"
  run_id: "{current transaction log run_id}"
```

The agent reads `${CLAUDE_PLUGIN_ROOT}/references/pattern-mapping-rules.md` and `${CLAUDE_PLUGIN_ROOT}/references/content-merge-audits.md` as its reference material. It processes all files, emits per-file transaction log events, runs the seven verification audits (Structural Content-Loss, PROJECT-SECTION Preservation, MCP Retention, Stale Agent Reference, Contract Residue, Telemetry Sanity, Concept-Terminology Residue), and returns a structured report.

**If the agent reports HALT** → this phase fails. Upstream stops the migration/initialization per the `On failure: halt` directive.

**If the agent reports PASS** → proceed to the **mandatory post-transformer steps** below IN ORDER, then return control to upstream. All steps marked "(initialize and migrate)" MUST execute on every operation — skipping any step is a regression that surfaces as missing wiring or stale docs on next skill invocation.

### Agent tool injection (initialize and migrate)

After the transformer completes Pattern Mapping, ensure all agent files in `.claude/agents/*.md` have the correct Neuroloom MCP tools in their frontmatter. Read `${CLAUDE_PLUGIN_ROOT}/transforms.yaml` for tool profiles and agent-to-profile mappings.

For each agent file:
1. Look up the agent's name in `transforms.yaml → agent_profiles` (default: `full`)
2. Resolve to the tool list from `tool_profiles`
3. Append to the agent's `tools:` frontmatter line any declared tool it lacks. Separately, append any other Neuroloom tool (`mcp__neuroloom__*`) the agent's text calls that the line lacks, and any tool in `transforms.yaml` → `memory_grant_tools` that its memory under `.claude/agent-memory/<name>/` calls (`<name>` is the agent file's name without `.md`): an upstream rewrite of the frontmatter would otherwise drop one a port granted (the port's Stage 4g grants tools for calls in agent memory). Memory grants only those, which all read: agents write their own memory, so a note must never widen an agent into writing

This runs on EVERY migration (not just init) to catch agents that were created before the plugin was installed or before tool profiles were defined. It's idempotent — agents that already have the correct tools are unchanged.

### Adapter content injection (initialize only)

After the transformer completes, inject the Neuroloom Tool Usage section into `CLAUDE.md` if not present. If `CLAUDE.md` doesn't exist yet (z-sdlc 3.0.0 runs `post-file-write` on Phase 1's copies, before Phase 2 writes it), skip this step: z-sdlc runs `post-file-write` on it once Phase 2 saves it (contract 0026), and this step runs then.

```markdown
## Neuroloom Tool Usage

All agents with Neuroloom tools follow these patterns:

- **Task start**: `memory_search` with domain-relevant query before substantive work
- **Before modifying key files**: `memory_by_file` on the 1-3 central files (skip new/config files)
- **Deep dive**: `memory_get_detail` when a search result needs full narrative, relationships and source files
- **Code understanding**: `code_search` (grep replacement for semantic symbol lookup), `code_context` (call chain + linked memories), `code_callers`/`code_callees` (trace a function's calls in & out), `code_navigate` (1-hop graph of a symbol's relationships)
- **After decisions/discoveries**: `memory_store` for design decisions, non-obvious patterns/gotchas, bug root causes, undocumented external API behavior. Do NOT store routine implementation details.
- **Feedback**: `memory_rate` positively when a memory answered a question or saved you from a mistake, negatively when outdated/wrong. Skip if merely irrelevant.
```

### Skill transform wiring (initialize and migrate — MANDATORY)

**This step is MANDATORY on every migration, not just initialization.** Upstream's direct-copy overwrites skill files with upstream versions that lack the `## Neuroloom Post-Execution Transform` section. Without re-wiring, skills created or modified after migration won't trigger the transformer, causing silent regression in all future agent-creation and knowledge-ingestion operations.

After the transformer completes on the batch of operational files, wire post-execution transforms into installed skills. Read `${CLAUDE_PLUGIN_ROOT}/transforms.yaml` — for each entry, inject a dispatch instruction at the end of the target skill's SKILL.md so the skill itself triggers the transformer after it runs.

**What gets injected (appended before the skill's `## Integration` section):**

```markdown
## Neuroloom Post-Execution Transform

After this skill completes its work, dispatch the `neuroloom-transformer` agent to apply Neuroloom-specific augmentation to the output files.

**Dispatch:**
- files: [target_patterns from transforms.yaml, resolved against project root]
- report: [for `sdlc-ingest`, its INGESTION REPORT: the files it wrote, whether it created or appended to each, and each entry it added, by title or bullet text (not a count)]
- operation: "transform"
- plugin_dir: this plugin's install directory (`claude plugin list --json`, the `installPath` of the enabled `neuroloom-sdlc@endless-galaxy-studios` entry, the one z-sdlc's § Finding the plugin picks: this project's install, project scope then local, else the user's, never another project's; else a copy vendored in the project)
- actions: [actions list from transforms.yaml]

The transformer reads `${CLAUDE_PLUGIN_ROOT}/references/pattern-mapping-rules.md` and applies the declared actions to matching files.
```

Write the `files` line as it stands: the transformer resolves the patterns when the skill dispatches it, and a literal knowledge path in the skill would fail the port's and the audit's path checks. The `report` line is the skill's own record of what it wrote, which the transformer's `ingest_to_neuroloom` needs: `git status` can't tell this run's writes from files already modified.

**`path_pairs` dispatch shape (added for `sdlc-archive` — the exception to the `files:` glob shape above):**

The `files:` field above works because every other wired skill's target files still exist at a discoverable path when the transformer runs — `target_patterns` resolves to a live glob. `sdlc-archive` breaks that assumption: by the time its Step 5 (Archive Deliverables, copy-then-delete — not `git mv`) has run, the pre-move path no longer exists on disk, so a glob can't recover it. The skill already knows both paths (it read the file from the pre-move path before copying it to the post-move path), so it must pass them explicitly instead of relying on glob resolution.

When a `transforms.yaml` entry declares `dispatch_mode: path_pairs` (currently only `sdlc-archive`), the injected section replaces the `files:` line with a `path_pairs:` line, and the skill collects the pairs itself over the course of its own run rather than the transformer resolving them:

```markdown
## Neuroloom Post-Execution Transform

After this skill completes its work, dispatch the `neuroloom-transformer` agent to apply Neuroloom-specific augmentation to the output files.

**Dispatch:**
- path_pairs: [{old: pre-move path, new: post-move path} for every deliverable doc archived in this run — collect from Step 5's approval table as each item is moved]
- operation: "transform"
- plugin_dir: this plugin's install directory (`claude plugin list --json`, the `installPath` of the enabled `neuroloom-sdlc@endless-galaxy-studios` entry, the one z-sdlc's § Finding the plugin picks: this project's install, project scope then local, else the user's, never another project's; else a copy vendored in the project)
- actions: [actions list from transforms.yaml]

The transformer reads `${CLAUDE_PLUGIN_ROOT}/references/pattern-mapping-rules.md` and applies the declared actions to the given path pairs.
```

All other action handlers (`inject_mcp_tools`, `ensure_mcp_tools`, `transform_knowledge_context`, `transform_communication_protocol`, `pattern_mapping`, `ingest_to_neuroloom`) are unaffected — they keep the `files:` glob shape. Only `sync_archive_status` reads `path_pairs`.

**The injected section is idempotent** — if the skill already contains a `## Neuroloom Post-Execution Transform` section, replace it (in case the transforms.yaml was updated between migrations). If the section is absent, inject it.

**Currently declared transforms** (see `${CLAUDE_PLUGIN_ROOT}/transforms.yaml`):

| Skill | Target | Actions |
|-------|--------|---------|
| `sdlc-develop-agent` | `.claude/agents/*.md` | Inject MCP tools per agent's tool profile, transform Knowledge Context and Communication Protocol sections |
| `sdlc-develop-agent` (ENRICH mode) | `.claude/agents/*.md` | Ensure MCP tools still present per profile, re-transform Knowledge Context and Communication Protocol |
| `sdlc-develop-skill` | `.claude/skills/*/SKILL.md`, `.claude/skills/*/references/*.md` | Apply full two-pass Pattern Mapping pipeline |
| `sdlc-ingest` | `[sdlc-root]/knowledge/**/*.yaml`, `[sdlc-root]/disciplines/*.md` | Route to Neuroloom through the plugin's extractor and `sdlc_seed`, tagged `sdlc:project-specific`, instead of writing flat files (`agents/neuroloom-transformer.md` § `ingest_to_neuroloom`) |
| `sdlc-archive` | `path_pairs` (pre-move -> post-move, assembled by the skill, no glob) | Sync each archived doc's DocumentSource anchor via `PATCH /api/v1/documents/by-path` |

**Why wire at install/migrate time:** The skill becomes self-contained at runtime — it knows to dispatch the transformer without hooks, config lookups, or runtime adapter detection. Adding new skills to `transforms.yaml` takes effect on the next migration.

### Adapter-specific docs (initialize and migrate — MANDATORY)

Copy Neuroloom-specific process docs from the plugin into the project:
- `${CLAUDE_PLUGIN_ROOT}/docs/knowledge-routing.md` → `[sdlc-root]/process/knowledge-routing.md`

This overrides the upstream version with the Neuroloom-aware variant that documents `memory_search`/`memory_store` patterns instead of file-path routing. **This step is MANDATORY on every migration** because upstream's direct-copy (§2.1) overwrites the file with the file-mode original before post-file-write fires. Without re-applying, the project retains upstream's flat-file knowledge-routing doc, which tells agents to use `[sdlc-root]/knowledge/agent-context-map.yaml` — a file that doesn't exist in Neuroloom projects.

**Verification:** After copying, diff the first 5 lines of `[sdlc-root]/process/knowledge-routing.md` against the plugin's version. If they don't match, the copy failed or was overwritten by a later step.

---

## post-operation
**On failure:** warn-continue

Run the shared post-operation audit to verify integration integrity after all mutations are complete.

### Procedure

Execute the checks documented in `${CLAUDE_PLUGIN_ROOT}/references/post-operation-audit.md`. Summary of required checks:

1. **MCP integration health** — count `memory_search(` + `memory_store(` across `[sdlc-root]/` and `.claude/agents/`. Verify minimum-MCP files each have at least one call, and one in each section their entry names. If any listed file has zero → REGRESSION.

2. **No residual knowledge-layer references** — generic scan `grep -rnE --include='*.md' '(\[sdlc-root\]|ops/sdlc)/(knowledge|disciplines)/' .claude/skills .claude/agents ops/sdlc CLAUDE.md | grep -vE '^ops/sdlc/(knowledge|disciplines)/'`, classified against the closed exemption table in `post-operation-audit.md` Check 2. It replaces the earlier fixed phrase lists (canonical and pre-contract), which missed backtick-wrapped, Integration-line and fenced-prompt instances and never searched `.claude/skills/`. Any hit outside the table → REGRESSION. Check 2b adds the concept-terminology scan (bare "discipline parking lots", "knowledge store" and the like, which name no path): WARN-class, and a REGRESSION when the file was logged `no_patterns`.

3. **No wildcard in tag arguments** — `grep -rnE --include='*.md' 'tag(s|_prefixes)=\[[^]]*\*' .claude/skills .claude/agents ops/sdlc CLAUDE.md | grep -vE '^ops/sdlc/(knowledge|disciplines)/'` (Check 2a). A `*` inside a tag argument matches nothing. Any hit → HALT.

4. **No inline adapter conditionals** — grep for `(Neuroloom projects:`, `(skip for Neuroloom`, etc. Any hit → REGRESSION.

5. **Manifest integrity** — `.sdlc-manifest.json` valid JSON, required fields present, `neuroloom_backend: true`, `workspace_id` populated and equal to the sentinel search's `filters.workspace_id`. On initialize, inject `neuroloom_backend: true` into the manifest after upstream writes it, and `workspace_id` (the sentinel search's `filters.workspace_id`) only if it is absent: `knowledge-seed` recorded the workspace it seeded, and when the key now reaches another one that is a **REGRESSION** naming both ids, never an overwrite.

6. **Knowledge layer reachable** — `memory_get_index(tags=["sdlc:sentinel"], limit=2)` returns exactly one row, whose tags (`memory_get_detail`) carry this operation's seed label (`post-operation-audit.md` Check 5, including its one WARN case).

7. **No file-mode knowledge layer** (Check 6) — an `ops/sdlc/knowledge/agent-context-map.yaml` the run created and left in place → REGRESSION; on initialize, a seeded Phase 1 copy `knowledge-seed` step 9 didn't remove → REGRESSION; a tracked map an earlier run left, an uncommitted one step 11 left in place, and on migrate a copy step 11 listed as likely redundant → WARN. What Neuroloom doesn't hold stays on disk and isn't reported, apart from step 11's lists.

8. **Skill transform wiring intact** — for each skill listed in `${CLAUDE_PLUGIN_ROOT}/transforms.yaml`, verify the installed skill file contains a `## Neuroloom Post-Execution Transform` section. If any declared skill is missing its wiring → REGRESSION (the mandatory skill-transform-wiring step in post-file-write was skipped).

9. **Knowledge-routing.md is Neuroloom-aware** — verify `[sdlc-root]/process/knowledge-routing.md` contains `memory_search` or `memory_store` (the Neuroloom-aware version). If it contains `agent-context-map.yaml` as a live reference without MCP equivalents → REGRESSION (the adapter-specific docs copy was skipped or overwritten).

10. **Snapshots (migrate, outside a git repository)** — leave this run's `.sdlc-manifest.json.pre-migrate-<run_id>` (upstream rewrites the manifest after this phase), and list every such copy in the report for CD to remove once the manifest is known good.

### Telemetry assertion (migrate only)

Before the post-operation checks, assert the `post-file-write` telemetry is intact. A failed assertion is a **REGRESSION** like any other: this phase is `warn-continue`, so upstream still writes the manifest, and the report must lead with it (recovery: § Recovery on failure, below):

1. Count `file_merged` events for current `run_id` = number of written files this phase's **Applies to** matches and its **Skip** doesn't exclude (a script, YAML or other file outside it gets none; a release that wrote only such files has zero)
2. Count `concept_terminology_applied` events = the `file_merged` events whose `subtype` is not `exempt_verbatim`, `exempt_row_rewrite` or `no_patterns` (Pass 2 runs on every file the pipeline transformed; an exempt or no-pattern file stops before it)
3. One `mcp_retention_audit_complete` event with `audit_result: "PASS"` per transformer dispatch (upstream calls `post-file-write` once per file it writes, and may batch: count the dispatches in the run's log); none when no written file matched this phase's **Applies to** (a release that changed only knowledge)
4. One `structural_audit_complete` event per dispatch, with all six structural counts present per file
5. One `agent_resolution_audit_complete` event per dispatch
6. One `contract_residue_audit_complete` event per dispatch
7. Every exempt file emitted `file_merged` with `subtype: "exempt_verbatim"`, or `"exempt_row_rewrite"` for `process/path-mappings.md` when its provenance row was rewritten (any other subtype = regression)
8. Zero unresolved `transformation_warning` events

If any assertion fails → report `TELEMETRY REGRESSION` (a REGRESSION, with § Recovery on failure). Do not paper over with after-the-fact reconstructed events.

### Operation-specific additions

**After `/sdlc-initialize`:**
- Project agents created (more than just framework agents in `.claude/agents/`)
- First-run sentinel exists, by exact tag (`memory_get_index(tags=["sdlc:sentinel"], limit=1)`)
- Agent frontmatter contains Neuroloom MCP tools
- Agent template transformed for future agent creation
- `CLAUDE.md` has the Neuroloom Tool Usage section and a transformed SDLC region (`post-file-write` on Phase 2's write)
- Agent names resolve against the roster Phase 4 made (the stale-agent scan, re-run; what doesn't resolve is listed)

**After `/sdlc-migrate`:**
- `knowledge-update` labelled its seed with `[target_tag]`, so the sentinel's version tag is `[target_tag]` after the phase, unless it reported that nothing matched exactly for the no-op send (Check 5's WARN). The manifest's `source_version` still holds the pre-migration value here, because upstream runs this phase before its manifest update (§4.4a, then §4.5): don't compare it with the target
- PROJECT-SECTION markers preserved (spot-check from transaction log)
- Any `[contract-change]` entries in range were resolved (via upstream's guarded rename logic)
- Sentinel version tag matches `[target_tag]` (the server moves it on every seed call, the no-op one included), with Check 5's one WARN case

### Failure handling

Collect all check results. If any check returns REGRESSION:
- Log each regression with file, line, and pattern
- Report all regressions to the user in a structured list
- This phase uses `warn-continue` — upstream continues to manifest update and user report, but the report includes the regression findings prominently

### Recovery on failure

If post-operation finds regressions in a migration:
- Operational layer: migrate's recovery (**Halts and their recoveries**, top of this file). It includes `.sdlc-manifest.json`, which upstream has rewritten by the time anyone acts on the report (this phase is warn-continue), so a clean run's undo restores it with the files.
- Knowledge layer: re-run `/sdlc-migrate` — idempotent upsert will re-apply correctly
- For detailed recovery procedures: see `${CLAUDE_PLUGIN_ROOT}/references/recovery-procedures.md`
