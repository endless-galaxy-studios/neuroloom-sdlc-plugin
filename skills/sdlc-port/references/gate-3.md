# Gate 3 — the facts and the cases

Read by `/sdlc-port` Gate 3 (`${CLAUDE_SKILL_DIR}/SKILL.md`), which writes these facts to a file and
runs `${CLAUDE_SKILL_DIR}/scripts/decide_port_gate.py` on them.

## The facts

**Observed**, from Neuroloom:
- `memory_search(query="SDLC workspace sentinel", tags=["sdlc:sentinel"])`: `search_ok` is whether
  it succeeded and carried `filters.workspace_id`; `index_ok` is whether every lookup below succeeded
  (a failed one says nothing, so record it as `false`, never as "no row"); both are JSON booleans.
  `workspace_id` is its `filters.workspace_id`, the workspace the API key reaches (in
  every successful response, even with no results).
- `memory_get_index(tags=["sdlc:sentinel"], limit=1)`: `sentinel` is whether it returns a row (an
  exact-tag lookup: the search ranks by relevance, and a sentinel written moments ago has no
  embedding yet). With a row, `memory_get_detail` on it gives `sentinel_label`, the value of its
  `sdlc:seed-version:` tag.
- `memory_get_index(tags=[<t>], limit=1)` for `sdlc:seed`, `sdlc:knowledge` and `sdlc:discipline`:
  `sdlc_rows` is whether any returns a row (records older ports wrote can exist without a sentinel).
- `current_sdlc_version`: Gate 2's `CURRENT_SDLC_VERSION`.

**Manifest**, from `.sdlc-manifest.json` (absent keys stay absent): `port_in_progress`, `ported_at`,
`neuroloom_backend`, `knowledge_id_scheme`, `knowledge_seed_in_progress`, `workspace_id`, `knowledge_seed_version`,
`source_version`, `source_version_sha`, and `adapter_names_plugin`: true when its `adapter` block
names this plugin (`"plugin": "neuroloom-sdlc@endless-galaxy-studios"`, or a `plugin_root` under a
`neuroloom-sdlc` install).

## The cases, for reading (the script's tests hold the full table)

0. The search failed: nothing is known about the workspace.
2. No `ported_at`, with `neuroloom_backend: true`, an adapter block naming this plugin, or
   `knowledge_seed_in_progress`: `/sdlc-initialize` set the project up with the plugin, so there is no
   file-mode install to port. The script names which: an initialize from before 0.7.0 (it needs the
   conversion), an unfinished one (finish it with initialize's recovery), or a finished one. Checked
   before case 1.
1. `port_in_progress` without `ported_at` or `neuroloom_backend`: a stopped port. It continues only
   into the workspace its marker records.
3. `ported_at`: a re-port. It stops when `neuroloom_backend` isn't true (`incomplete_port_record`: Stage 5
   writes both, so the manifest was edited), when the manifest records no `knowledge_seed_version`
   (`no_seed_version`), when the manifest lacks `"knowledge_id_scheme": 2` (ported
   before 0.7.0: the workspace needs a one-time conversion, which this release doesn't do; see
   `${CLAUDE_PLUGIN_ROOT}/references/adapter-lifecycle.md` § knowledge-update step 1); when the
   manifest records no `workspace_id`, or another than the key reaches, or there is no sentinel;
   when `knowledge_seed_version` differs, ignoring a leading `v`, from the label the Inventory's
   **The seed's label** rule gives (that check is skipped when the manifest has no version key); or
   when the sentinel's own label differs from `knowledge_seed_version`. The last two mean a
   migration since the port has updated Neuroloom past the files on disk (migrate never touches
   those), so re-porting would put older text back; the project's knowledge is edited in Neuroloom
   from here on.
4. None of `port_in_progress`, `ported_at` or `neuroloom_backend` (`install_date`, which every
   z-sdlc install has, doesn't count), but a sentinel or SDLC rows: records this run can't account
   for. This project's from before 0.7.0 (the conversion above), another project's (port into a
   workspace of its own), or this project's own stopped port whose manifest change was discarded:
   only when `label_matches` is true and CD confirms, put back `"port_in_progress": true` and
   `"workspace_id"` set to the id named, then re-run. The records'
   ids can't settle which (the 0.6.x port and stock z-sdlc share most of them), so this gate doesn't
   guess.
5. Nothing: a fresh port.
