# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
