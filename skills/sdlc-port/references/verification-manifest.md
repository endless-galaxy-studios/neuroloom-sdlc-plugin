## Stage 5 — Manifest and Verification

### Write Manifest

First copy the manifest as it is to `.sdlc-manifest.json.pre-port` and (after `mkdir -p <undo>`: a run that changed no file hasn't made it) to `<undo>/sdlc-manifest.json` (this run's own snapshot, which no later run overwrites; Stage 3 has written a manifest by
now on a fresh port, so there is always one to copy): an audit failure restores from that copy (§ Post-Operation Audit), which works whether or not git
tracks the file and on a re-port too. Once the audit passes, and before Post-Port Cleanup: if `<undo>/files/ops/sdlc/process/knowledge-routing.md` exists and differs from the plugin's copy (`cmp -s` fails: the file as it was before the port, stock z-sdlc's or the project's own text, which the port replaced whole), `mkdir -p` the kept directory (`$(git rev-parse --git-path sdlc-port-kept)`, or `.sdlc-port-kept/` outside git), move the file there as `knowledge-routing.md.<timestamp>` and name it in the final summary; if the move fails, halt and delete nothing. Then delete this run's `<undo>` whole, and after it `.sdlc-manifest.json.pre-port`, `CLAUDE.md.pre-port` and `CLAUDE.md.pre-port.region`.

Then update `.sdlc-manifest.json` in the project root, or create it if it is absent. Change only the keys
below and keep every other key: a ported z-sdlc install's manifest carries `installed_files`,
`declined_files`, `bundle_fragments` and the like, which `sdlc-migrate` reads.

Set:
- remove `port_in_progress`, which Stage 3 wrote (Gate 3 reads it to carry on a port that stopped).
  Check after writing that the key is gone: a ported manifest still carrying it would make the next
  run's Gate 3 treat a re-port as a continued first port
- `neuroloom_backend`: `true`
- `sdlc_root`: `"ops/sdlc"`
- `ported_at`: this run's ISO 8601 timestamp
- `knowledge_id_scheme`: `2`, the sign `knowledge-update` checks that this workspace's ids are the
  extractor's
- `workspace_id`: Stage 3 recorded it on a fresh port, and a re-port that recorded one passed Gate 3
  only with it matching, so it is normally already set; if not, search the sentinel again now: the
  `memory_search` response echoes the workspace among its applied filters. It is the value the
  `post-operation` handler checks
- `knowledge_seed_version`: the version label Stage 3a passed to `sdlc_seed` (the Inventory's
  **The seed's label**: `source_version`, the first 7 characters of `source_version_sha` for an
  untagged install, or `CURRENT_SDLC_VERSION` when the manifest has neither (a re-port keeps the one it records); a re-port that skipped
  Stage 3a keeps the value it has). Gate 3 compares it with the label rule to refuse a re-port after
  a migration.
- `adapter`: this plugin's block, the one `sdlc-initialize` writes. `sdlc-migrate` decides adapter
  mode from this block alone, so without it the next migration runs in file mode, untransformed. It
  names the plugin by its id and records no path (z-sdlc contract 0025): `sdlc-initialize` and
  `sdlc-migrate` find the enabled install on every run with `claude plugin list --json`, so the block
  holds on every machine and across plugin upgrades. Remove any `plugin_root` the manifest already has
  unless it is a relative path to a copy vendored inside the project:
  ```json
  "adapter": {
    "plugin": "neuroloom-sdlc@endless-galaxy-studios",
    "supported_zsdlc_version": "{adapter.json → supported_zsdlc_version}",
    "phase_handlers": "{adapter.json → phase_handlers}"
  }
  ```
- `installed_files`, if the manifest has it: the sha256 of every file the port wrote that the map
  lists (each such file this run edited or created, `ops/sdlc/process/knowledge-routing.md` included, but each only when the run created it or its copy under `<undo>/files/`, its text before this run's edit, matched its hash in `.sdlc-manifest.json.pre-port`; a file that already held the project's own edits, or an earlier run's transform, keeps its hash, so a later migration asks about it rather than taking those edits as the port's), the way
  `sdlc-migrate` §4.5 rehashes the files it writes. `CLAUDE.md` isn't in it: don't add it. Leave every
  other entry as it is.
- `source_repo`, only if it is absent: `https://github.com/endless-galaxy-studios/z-sdlc`

Do not touch `source_version` or `source_version_sha`. The port changes no file's z-sdlc release,
and `sdlc-migrate` diffs from the release these name. If the manifest has neither, leave them unset:
the next migration's `knowledge-update` then has no baseline, and halts and asks CD for the release
the knowledge came from. Earlier versions set them to the latest
release, so the next migration reported "already on" a release the files were never on.

Do NOT create or update the sentinel — the sentinel is managed server-side by `seed()`.
This skill triggers ingestion; the server manages the sentinel lifecycle. Only READ the sentinel
for detection purposes.

### Verification Checklist

Run these checks after writing the manifest:

| Check | MCP Call | Pass Condition |
|-------|----------|----------------|
| Sentinel exists | `memory_get_index(tags=["sdlc:sentinel"], limit=1)` (by exact tag: the seed reset its embedding, so a relevance search may miss it) | One row returned |
| Knowledge entries seeded | `memory_get_index(tags=["sdlc:knowledge"], limit=1)` | One row returned |
| Provenance records stored | `memory_get_index(tags=["sdlc:provenance"], limit=500)` | At least the Stage 1 entry count less the ids Stage 3c left alone or failed, or 500 rows when the log had more (the index returns at most 500; then count by status tag as well); 0 when the project never had one; on a re-port with no log on disk (an earlier cleanup removed it), skip this row |
| Discipline entries seeded | `memory_get_index(tags=["sdlc:discipline"], limit=1)` (by exact tag, like the rows above) | One row returned (every discipline entry carries the bare `sdlc:discipline` tag) |
| Deliverable docs synced | `memory_get_index(tags=["sdlc:deliverable", "sdlc:type:<type>"], limit=1)` for each frontmatter `type` the Stage 1 dry run found | Each returns a row |
| No stale path references | Grep transformed files for `ops/sdlc/knowledge/`, `ops/sdlc/disciplines/`, `[sdlc-root]/knowledge/` and `[sdlc-root]/disciplines/` (rows 1 to 7 of the post-operation audit's Check 2 exemption table apply, as in Stage 4a and `references/transform-targets.md`), for relative links into `knowledge/`, `disciplines/` or `bundles/` with or without a `./` or `../` prefix whose target the cleanup removes or that doesn't exist (a target that exists and stays is fine), and for `provenance_log` (the link check exempts only the changelog; the `provenance_log` check exempts the changelog and row 6's lines). Skip `ops/sdlc/process/knowledge-routing.md` | Zero matches |
| No stale YAML references | Grep transformed files for `agent-context-map.yaml` and `agent-communication-protocol.yaml` (rows 1 to 7 of the audit's Check 2 exemption table apply, as in Stage 4a and `references/transform-targets.md`, and so does the closed list of `sdlc-migrate` map lines in post-operation Check 6 step 4, which 0.7.2 keeps as upstream has them; skip `ops/sdlc/process/knowledge-routing.md`, the plugin's copy) | Zero matches |
| Operational directories still at the SDLC root | `ls ops/sdlc/` | `process/` and `templates/` present, plus whichever of `playbooks/`, `examples/`, `plugins/` and `improvement-ideas/` the install had. The port moves nothing |
| Manifest present | Read `.sdlc-manifest.json` | `neuroloom_backend: true`, `sdlc_root: "ops/sdlc"`, and an `adapter` block with `"plugin": "neuroloom-sdlc@endless-galaxy-studios"` and no absolute `plugin_root` |
| No stale `ops/sdlc/knowledge/` refs in agent memory | `grep -rn "ops/sdlc/knowledge/" .claude/agent-memory/` | Zero matches outside the historical records Stage 4g left as they were |
| No stale `ops/sdlc/disciplines/` refs in agent memory | `grep -rn "ops/sdlc/disciplines/" .claude/agent-memory/` | Zero matches outside the historical records Stage 4g left as they were |

Exclusion rules for the grep checks above:
- Exclude `sdlc_changelog.md` historical entries, and the archived ones in `process/changelog-archive/*.md`
- Exclude lines matching `~/src/ops/sdlc/` (upstream z-sdlc source path)

If any check fails, report the specific failure and its recovery path (`${CLAUDE_SKILL_DIR}/references/recovery-procedures.md` § Stage 5), and undo the run as an audit failure does (§ Post-Operation Audit, every step: files from `<undo>/files/` with the created ones removed, `CLAUDE.md`'s region, agent memory, and `.sdlc-manifest.json.pre-port` back over the manifest, then `<undo>` deleted, and the report says the run was undone): left as written, the manifest says ported, so the re-run would be a re-port, which never offers Post-Port Cleanup. Name Stage 4c's set-aside copies, and on a continued port any other run's `<undo>`, in the report too, as the audit-failure halt does.

**Count verification:**

Compare what Neuroloom holds with the Stage 1 inventory, per category. `memory_search` returns at
most 100 results whatever `limit` asks for, so count with `memory_get_index`, which returns up to
500 rows:
```
memory_get_index(tags=["sdlc:knowledge", "sdlc:domain:<domain>"], limit=500)   # once per domain
memory_get_index(tags=["sdlc:discipline"], limit=500)
```
Each count should be at least the extractor's count for that category from the Stage 1 dry run
(the workspace may hold more: entries from earlier runs). A count of exactly 500 is indicative only.

If a category is materially short of the Stage 1 count:
1. Note which category is short, and which seed file holds its entries
2. Send that file again with `skip_deprecation: true`; repeats are safe, since entries already
   written come back `unchanged`
3. Re-run the count check

Do not mark the port complete if a material discrepancy cannot be explained: undo the run as a checklist failure does (§ Post-Operation Audit's recovery, every step, `.sdlc-manifest.json.pre-port` back over the manifest and deleting `<undo>` included), so the re-run doesn't take the failed run as finished.

### Post-Operation Audit

**Run the shared post-operation audit** at `${CLAUDE_PLUGIN_ROOT}/references/post-operation-audit.md`. Execute the shared checks AND the `/sdlc-port`-specific subset.

The audit verifies the bulk transformation landed correctly — every file-based reference that should have become a `memory_search`/`memory_store` call actually did, across all targeted files. The port touches a much larger surface than a typical migration (it converts an entire file-based install), so aggregate checks are essential:
- Every file the phrasing-contract runtime scan (`${CLAUDE_PLUGIN_ROOT}/agents/neuroloom-transformer.md` § "Step 1: Runtime Scan") flagged for a path anchor contains at least one MCP call. A file flagged only for concept terms ("discipline parking lots") needs its wording translated, not a call: Check 2b covers it
- No residual z-sdlc standard phrases (they should all be transformed)
- No inline adapter conditionals (contract violations)
- Knowledge YAMLs fully ingested with correct domain tags
- Original file-based knowledge files listed for Post-Port Cleanup, which runs after the audit

**If the audit fails:** Halt. Do NOT proceed to Post-Port Cleanup. Follow the audit's recovery instructions. For port failures: copy every file under this run's `<undo>/files/` back to its path and remove each one `<undo>/created` lists (never a `git checkout`, which would also discard uncommitted edits in them and in files the port never touched, such as a crashed earlier run's transforms a re-port built on), and, if the copy still exists (Stage 4d may have used and removed it), restore only `CLAUDE.md`'s SDLC region from `CLAUDE.md.pre-port` as Stage 4d does, first copying (not moving) the current file to `CLAUDE.md.pre-port.before-restore-<timestamp>` (between the copy's markers, or with `CLAUDE.md.pre-port.region` when the copy had none), then delete both (so edits outside the region survive), and restore the manifest too, by copying `.sdlc-manifest.json.pre-port` back over it, whether or not git tracks the file: that copy was taken in Stage 5, so on a fresh port it still holds Stage 3's `port_in_progress`, and Gate 3 then lets the re-run carry on over the records Neuroloom already holds (a `git checkout` would drop the key, and Gate 3 would refuse those records as unaccounted for). Removing keys by hand would erase a re-port's earlier values. Agent memory comes back with the rest of `<undo>/files/` (Stage 4g copies each file it changes there; git ignores them, so no checkout brings them back), and the files 4g didn't change, which may hold notes another session added since, are left alone. A manifest that still says ported, with an `adapter` block, over untransformed files makes the next migration transform only the files that release touches; knowledge ingestion is idempotent so re-running port after a plugin fix is safe. Once every restore above is done, delete this run's `<undo>`, so no later recovery applies it again. In the halt report, say the run was undone and its `<undo>` deleted, without naming it as a recovery path, and name every `CLAUDE.md.pre-port*` file other than `CLAUDE.md.pre-port` and `CLAUDE.md.pre-port.region` (Stage 4c's set-aside copies: one may hold the only untransformed original). On a continued port (Gate 3 case 1), also name every other directory under `$(git rev-parse --git-path sdlc-port-undo)/` (or `.sdlc-port-undo/` outside git): an earlier run this one continued, still unrestored, which abandoning the port undoes as well.

### Post-Port Cleanup

Skip this section, removing nothing, on every re-port and on a continued port (Gate 3 case 1): its
earlier run already seeded the files, and a row tagged `sdlc:project-specific` is never updated, so a
file edited on disk since then may hold text Neuroloom doesn't have; deleting it would lose that
text. Say so in the summary: the files can be compared with Neuroloom and removed by hand, with the
same bookkeeping option 1 does (record the map in `declined_files`, drop the removed files'
`installed_files` entries and lower `file_count`); otherwise a later migration's `knowledge-update` takes the ones whose every entry it confirms Neuroloom holds and lists the rest of upstream's text as likely redundant. Only a first port
Gate 3 didn't continue asks the question below, including one finished in the same session after a
failed knowledge-routing move.

Otherwise use `AskUserQuestion` to ask the user whether to remove the local files Neuroloom now
holds. Remove only what was ingested. Stage 3a's seed files name each entry's `source_path`,
relative to `ops/sdlc/knowledge/` for an entry tagged `sdlc:knowledge` and to `ops/sdlc/disciplines/`
for one tagged `sdlc:discipline`. A file under either directory that no entry names (one the Stage 1
dry run listed as producing no entries, or one `declined_files` excluded) is the only copy of its
content, or one the project declined, and stays. The knowledge READMEs stay too: Neuroloom doesn't hold
their text, and z-sdlc, which treats a file off disk as one this plugin took, would never restore them
(contract 0026). Keep `provenance_log.md` unless every Stage 3c entry was stored, updated or skipped as
current: only then does Neuroloom hold the project's record.

Question text:
```
These local files are now redundant: Neuroloom holds their content.

  Knowledge files the seed ingested:   {N} (YAML and Markdown)
  Discipline files the seed ingested:  {M}
  The context map, and the provenance
  log when Stage 3c stored every entry ({R} files) — not needed in a Neuroloom project

These stay, because Neuroloom doesn't hold their text: the knowledge READMEs, and
{any other file nothing ingested, and the provenance log if an entry wasn't stored, or "nothing else"}
Everything else under ops/sdlc/ is the project's live SDLC (process docs,
templates, playbooks) and stays. If you keep the redundant files, a later
/sdlc-migrate takes the ones it can confirm Neuroloom holds and lists the rest as likely redundant.

Remove the redundant files now?
```

Options:
1. Remove the redundant files (the files listed as staying stay)
2. Keep them (I'll remove them manually)

If the user selects option 1:
  - delete each file the question listed as redundant, by path, then any directory left empty
    (`find ops/sdlc/knowledge ops/sdlc/disciplines -type d -empty -delete`). Never `rm -rf` the two
    directories: they may hold the files that stay;
  - record `ops/sdlc/knowledge/agent-context-map.yaml` in `.sdlc-manifest.json` → `declined_files`
    (`{"why": "Neuroloom project: agents reach knowledge through memory_search, no map", "decided": "sdlc-port, <date>"}`),
    as `knowledge-seed` step 8 does: z-sdlc keys its map handling on that record (contract 0024).
    Record nothing else. With an adapter that declares `knowledge-update`, `sdlc-migrate` treats a file
    under `knowledge/` or `disciplines/` that is off disk, has no `installed_files` entry and isn't declined
    and was upstream's at `source_version` as one the adapter took: it never copies it, asks about it or
    records it as declined (contracts 0024 and 0026). A declined knowledge file is
    also one `knowledge-update` never seeds again, so recording the deleted ones would freeze them;
  - drop the deleted files' `installed_files` entries and lower `file_count` by the number dropped.
If the user selects option 2: do nothing.

Never remove `ops/sdlc/` itself, or anything in it the question did not list as redundant. It is the
project's SDLC root.

Always keep:
- `ops/sdlc/process/`, `ops/sdlc/templates/`, `ops/sdlc/playbooks/`, `ops/sdlc/examples/`,
  `ops/sdlc/plugins/`, `ops/sdlc/improvement-ideas/`, and the root files (`CLAUDE-SDLC.md`,
  `README.md`, the external-review scripts): the live SDLC
- Knowledge and discipline files nothing ingested
- `docs/_index.md` — deliverable catalog remains filesystem-local

### Final Summary

Output a completion summary:

```
Neuroloom SDLC Port Complete — {N} knowledge + {M} discipline entries seeded (or "knowledge not re-sent: Neuroloom's copy is live"), {J} files transformed

Ported local z-sdlc installation to Neuroloom backend. {N} knowledge entries and {M} discipline entries are now searchable via memory_search; {K} deliverable docs synced; {J} agent/skill files transformed from file-path to MCP references.

  Knowledge entries seeded:  {N, or "skipped: Neuroloom's copy is live" when Stage 3a was skipped}
  Discipline entries seeded: {M, or "skipped"}
  Deliverable docs synced:   {K}
  Agent/skill files updated: {J}
  Provenance records stored: {P} (updated: {U}; failed, re-run to retry: {ids, or none})
  CLAUDE.md copies set aside: {every CLAUDE.md.pre-port* file on disk other than CLAUDE.md.pre-port and CLAUDE.md.pre-port.region, from this run or an earlier one, or none: compare and delete by hand}
  Replaced knowledge-routing.md: {its pre-port copy under sdlc-port-kept/ (in the git directory, or .sdlc-port-kept/ outside git): stock z-sdlc's or the project's own text; compare and delete by hand, or none}
  Edits that failed:          {each file an edit failed on, with the tools to add by hand for an agent's tools line, or none}
  Earlier runs' file copies:  {every directory under $(git rev-parse --git-path sdlc-port-undo)/ (or .sdlc-port-undo/) other than this run's, or none: an earlier run's may hold the originals; delete by hand once not needed}

Next step: Run /sdlc-migrate to check for upstream z-sdlc updates.
```

If the user chose **Stop after ingestion** at Stage 4b, the run ended there (Stage 4b), so this
summary is not printed; that stage says what to report instead.

---

