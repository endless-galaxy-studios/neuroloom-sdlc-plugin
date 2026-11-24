# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.7.0] - 2026-11-23

### Breaking Changes

- **The SDLC root is `ops/sdlc` again, and `.claude/sdlc` is no longer supported.** CD's decision, 2026-11-23. z-sdlc's factory treats `.claude/` as protected agent configuration: its implement guard refuses any path with a `.claude` segment, and its tool policy denies edits there, so a `.claude/sdlc` root can't take part in the factory. The move to `.claude/sdlc` came from Neuroloom D26 (2026-03-28) and was about co-location only. There is no compatibility path.
- **A project whose root is still `.claude/sdlc` must move it before running `/sdlc-migrate` or `/sdlc-port` on this version.** Move the contents of `.claude/sdlc/` into `ops/sdlc/` with `git mv` (or stage the move); in `.sdlc-manifest.json` set `"sdlc_root": "ops/sdlc"` and re-key the `installed_files` and `declined_files` entries to `ops/sdlc/` paths and update the `bundle_fragments` target paths; commit the move; and update the live references that name `.claude/sdlc/` (`CLAUDE.md`, `.claude/agents/`, `.claude/skills/`, `.claude/agent-memory/`). Until then the new root check halts both skills (below).
- **After installing 0.7.0, point `adapter.plugin_root` in each project's `.sdlc-manifest.json` at the new install** (for a marketplace install, `~/.claude/plugins/cache/endless-galaxy-studios/neuroloom-sdlc/0.7.0`, as an absolute path). `sdlc-migrate` reads the handler doc from that path, and the plugin cache keeps the 0.6.1 directory beside the new one, so a manifest that still names 0.6.1 runs 0.6.1's handlers, root check missing. Nothing in 0.7.0 can catch that, because 0.7.0's handlers are the ones not being read.

### Changed

- **`/sdlc-port` transforms the SDLC root's own Markdown.** Stage 4a now scans every `*.md` under `ops/sdlc/` outside `knowledge/` and `disciplines/`, as the post-operation audit does, and looks for the `[sdlc-root]/knowledge/` and `[sdlc-root]/disciplines/` forms and relative links that z-sdlc's files use, not only the written-out `ops/sdlc/knowledge/` path. Before, Stage 4a scanned `.claude/agents/`, `.claude/skills/` and the agent template for written-out paths and named process docs only by example, while the audit scanned every file in the moved directories for the `[sdlc-root]/` form, so a correct port could fail its own audit. The files and spans the audit exempts on purpose are left alone, except `process/knowledge-routing.md`, which the port now replaces whole with the plugin's Neuroloom variant, as migrations do.
- **`/sdlc-port` no longer moves anything.** Stage 4f, which moved `process/`, `templates/`, `playbooks/`, `examples/`, `plugins/` and `improvement-ideas/` from `ops/sdlc/` to `.claude/sdlc/` and rewrote paths to match, is gone. Stage 4g still rewrites agent-memory references to `ops/sdlc/knowledge/` and `ops/sdlc/disciplines/` into `memory_search` calls; it no longer touches other `ops/sdlc/` paths, which are now correct. The verification checklist drops the rows that demanded the six directories be gone from `ops/sdlc/` and checks they are still there.
- **Post-Port Cleanup removes only `ops/sdlc/knowledge/` and `ops/sdlc/disciplines/`.** Its old "remove all remaining `ops/sdlc/` content" option ran `rm -rf ops/sdlc/`, which was safe only because Stage 4f had emptied the directory. Without 4f it would have deleted the live process docs, templates and playbooks. The option is gone, and the skill now says never to remove `ops/sdlc/` itself.
- **Every post-operation scan reads `ops/sdlc`** (Checks 1, 2, 2a, 2b, 2d, the provenance scan, the exemption paths) and skips `ops/sdlc/knowledge/` and `ops/sdlc/disciplines/`. Those two hold file-mode data the transformer never rewrites, and on a port they are still on disk when the audit runs, before Post-Port Cleanup. Check 6 now covers both directories: an `agent-context-map.yaml` a migration created is a regression; any other file there, and the map on an initialize (z-sdlc's skeleton includes it), is a warning, whether upstream wrote it in file mode (z-sdlc's `sdlc-initialize` copies discipline files into the root) or a port left it behind. Check 4 requires `sdlc_root` to be `ops/sdlc`.
- **Recovery commands restore the SDLC root.** The migrate and port recoveries said `git checkout -- .claude/`, which covered the root only while it sat inside `.claude/`. They now say `git checkout -- .claude/ ops/sdlc/`.

### Fixed

- **The `/sdlc-initialize` recovery deleted the project's agents.** It ran `rm -rf .claude/sdlc/ .claude/agents/`, which removed every agent the project already had. On an `ops/sdlc` project it also left the SDLC tree in place. It now undoes what initialization wrote with `git checkout` and `git clean`, file by file. Found by the Sleeved migration's reviewers.
- **An audit over a missing root could pass.** grep over a path that does not exist finds nothing, so a scan of the wrong root reported clean. Check 4 now fails when `ops/sdlc/` is missing, and a grep error on it counts as a regression.

### Added

- **An SDLC root check** (`references/preflight.md` check 0). It fails when `.claude/sdlc/` holds any tracked or new, unignored file, even beside `ops/sdlc/` (ignored leftovers such as `.local/` don't count, so an old worktree's local state doesn't trip it), when the manifest or the migration names another root, or when the manifest still keys files by `.claude/sdlc/` paths (a stale `declined_files` key would re-seed knowledge CD declined). Its message says how to move. Without it, an unmoved install would get audits that scan a directory that isn't there and pass. `/sdlc-port` runs it in Stage 1. z-sdlc doesn't run `preflight.md` itself, so the `knowledge-seed`, `knowledge-update` and `post-file-write` handlers each run it as step 0 and halt the operation if it fails, whichever of them fires first.

## [0.6.1] - 2026-11-23

### Changed

- **The content-merge audits read z-sdlc's replacement and removal marks** (z-sdlc contract 0021). A section a `PROJECT-SECTION-START: <label> replaces` block stands in for, or a `PROJECT-SECTION-REMOVED` line names, is absent by the project's marked choice: neither the structural count nor the mandatory-step check reports it as a regression. The marker audit counts removal lines with the blocks, so a lost removal mark halts like a lost block.
- **Knowledge files a project declines stay declined** (z-sdlc contract 0022, `.sdlc-manifest.json` → `declined_files`). `knowledge-seed` skips a declined path and records each file its applicability check removes. `knowledge-update` leaves declined files out, and no longer re-seeds a file the project removed from the workspace (absent there, present upstream at the project's `source_version`): it reports it for CD to decline or re-seed.
- **The compliance auditor's new sections are transformed and checked** (z-sdlc 2.9.6 gave `sdlc-compliance-auditor` a Knowledge Context and a Communication Protocol section). The Knowledge Context line matched an existing row. A new mapping row covers the Communication Protocol line's "…and follow the handoff contract it defines". The post-operation audit's minimum-MCP list now expects a call in each of the two sections, not one anywhere in the file.
- **`knowledge-seed`'s spec-relevance question has a path for a run with no ask tool** (headless, or `sdlc-initialize` run inside a subagent, z-sdlc `process/headless-mode.md` § Subagents): it boosts nothing and lists the question in the run's result with a proposed set. Nothing later depends on it, so the run doesn't stop.
- **`knowledge-update` tells the migration to skip `sdlc-migrate` §3.3's map updates and never create the map.** z-sdlc 2.9.6 added an `sdlc-reviewer` role and a new mapping, which would send a migration to edit, or create, a map a Neuroloom project doesn't have. z-sdlc's §3.3 now says the same, but a project runs the `sdlc-migrate` it has installed, so the handler gives the instruction until the project has a copy with z-sdlc's line.
- **Supports z-sdlc 2.9.10** (`adapter.json`, both keys, and `.claude-plugin/plugin.json`, whose `supported_zsdlc_version` had drifted to 2.2.0). The `[contract-change]` entries since 2.2.0 are covered: 2026-11-14's knowledge-store glob, which the mapping table already transformed, and 2026-11-20's marks and declined files, above. No release from 2.9.1 to 2.9.10 adds one; the entries above cover the adapter-facing changes those releases made.

### Fixed

- **The post-operation audit's manifest check would report false regressions on a migration.** z-sdlc runs the adapter's `post-operation` phase before its manifest update (`sdlc-migrate` §4.4a, then §4.5), but the audit assumed the manifest was written: it expected the target `source_version`, a `last_migration` timestamp z-sdlc never writes, and the new hashes of the files the run wrote. Found by reading the two docs side by side, not in a run's report. On a migration it now compares the run's target tag with the version `knowledge-update` re-seeded at (a difference is a WARN), skips the hashes of every file the run touched, and lists a mismatch on an untouched file as pre-run drift (WARN).

## [0.6.0] - 2026-10-30

This is the first changelog for this plugin; earlier releases are in the git history.

### Breaking Changes

- **The two CI-mode SessionStart lines are a contract, and changing their wording is a breaking change.** Factory workflows and tests match them byte-for-byte. A wording change will be announced here under "Breaking Changes".
- **In CI mode the plugin must be pinned together with `neuroloom-claude-plugin`, at versions that list CI mode in their changelog.** An older SDLC plugin on a newer base plugin fails open: its `post_tool_use` knows nothing about CI mode and still ingests deliverable documents. The reverse pairing is safe (see "Added", version skew).

### Added

- **CI mode** (`NEUROLOOM_MODE=ci`, defined by the base plugin; unset or blank is normal mode and any other non-empty value also means CI). In CI mode:
  - `session_start` still makes its two reads (the latest z-sdlc version, then the workspace sentinel), each with a 10 s timeout, and ends silently on an unreachable API or a non-200 answer. Up to date is silent, as is a sentinel with no `sdlc:seed-version:` tag. The two messages that tell a person to run `/sdlc-initialize` or `/sdlc-migrate` are replaced by two neutral lines, so an unattended agent is not nudged into running a skill that writes tracked files:
    - `[Neuroloom SDLC] This workspace has no SDLC knowledge seeded. No action is taken in CI mode.`
    - `[Neuroloom SDLC] Workspace SDLC knowledge is at {workspace_version}; latest is {latest_version}. No action is taken in CI mode.`

    Control characters in the two versions are escaped and each version is cut to 64 characters, so the line stays one line.
  - The SDLC hooks need the key already seeded into `<project root>/.neuroloom.db` by the **base** plugin's `scripts/seed_project_key.py`; this plugin has no seed step.
  - `post_tool_use` returns before it reads the file, opens a database or starts a thread. Nothing is sent and nothing is recorded.
  - `run_hook.py` finds the base plugin **only** through `NEUROLOOM_CLAUDE_PLUGIN_ROOT`, which must be set to an absolute path of a directory holding a `pyhooks/` package with `__init__.py` and `config.py`. It never searches `~/.claude/plugins/cache` and never falls back to the sibling checkout. If the check fails it prints one stderr line and exits 0, so the hooks do nothing.
  - The hook runs under `sys.executable` (no venv lookup, no degraded-venv line) and is started with `python -I`, so a planted `pyhooks/`, `sdlc_pyhooks/` or `json.py` in the checkout is never imported. `PYTHONPATH` from the environment is ignored; the import path is exactly this plugin's root and the base plugin root.
  - If the base plugin cannot be imported, each hook prints `[neuroloom-sdlc] CI mode: base plugin import failed (<ExceptionTypeName>); hooks do nothing` to stderr (the exception type only) and exits 0.
- **Version skew fails closed.** `sdlc_pyhooks.mode_state()` returns `normal`, `ci` or `skew`. It reads `NEUROLOOM_MODE` from the environment and checks that the base plugin's `Config` declares `ci_mode`. When the environment says CI and the base plugin cannot report it (too old, or not importable), both hooks do nothing: no database, no API call.

### Changed

- CI mode has been developed and checked on macOS with Claude Code 2.1.314; the z-sdlc smoke job in GitHub Actions has not run yet, and Windows is untested.
- Four copies of the `NEUROLOOM_MODE` parse rule exist (base `config.py`, base launcher, this launcher, `sdlc_pyhooks`); `tests/test_mode_parser_agreement.py` keeps them in agreement.
- The README paragraph that told you to leave `NEUROLOOM_CLAUDE_PLUGIN_ROOT` unset is corrected: leaving it unset is still right for attended sessions on a marketplace install, but in CI mode the variable is required.
- Outside CI mode nothing changes in the SDLC hooks, except through the base plugin: they read the key through `config.load()`, so they inherit the base plugin's project-root cutover (the key and state come from `<project root>/.neuroloom.db`, not the directory Claude is in). See the base plugin's changelog.

### Fixed

- The README's endpoint table listed `POST /api/v1/memories/search` for the SessionStart sentinel lookup; the hook calls `GET /api/v1/memories/?tags=sdlc:sentinel&limit=1`.
