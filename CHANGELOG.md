# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

CD renames this heading to the version and date when bumping. Everything here is D178d. This is the first changelog for this plugin; earlier releases are in the git history.

### Breaking Changes

- **The two CI-mode SessionStart lines are a contract, and changing their wording is a breaking change.** Factory workflows and tests match them byte-for-byte. A wording change will be announced here under "Breaking Changes".
- **In CI mode the plugin must be pinned together with `neuroloom-claude-plugin`, at commits that include D178d.** An older SDLC plugin on a newer base plugin fails open: its `post_tool_use` knows nothing about CI mode and still ingests deliverable documents. The reverse pairing is safe (see "Added", version skew).

### Added

- **CI mode** (`NEUROLOOM_MODE=ci`, defined by the base plugin; unset or blank is normal mode and any other non-empty value also means CI). In CI mode:
  - `session_start` still makes its two reads (the latest z-sdlc version, then the workspace sentinel), each with a 10 s timeout, and ends silently on an unreachable API or a non-200 answer. The two messages that tell a person to run `/sdlc-initialize` or `/sdlc-migrate` are replaced by two neutral lines, so an unattended agent is not nudged into running a skill that writes tracked files:
    - `[Neuroloom SDLC] This workspace has no SDLC knowledge seeded. No action is taken in CI mode.`
    - `[Neuroloom SDLC] Workspace SDLC knowledge is at {workspace_version}; latest is {latest_version}. No action is taken in CI mode.`

    Control characters in the two versions are escaped and each version is cut to 64 characters, so the line stays one line.
  - `post_tool_use` returns before it reads the file, opens a database or starts a thread. Nothing is sent and nothing is recorded.
  - `run_hook.py` finds the base plugin **only** through `NEUROLOOM_CLAUDE_PLUGIN_ROOT`, which must be set to an absolute path of a directory holding a `pyhooks/` package with `__init__.py` and `config.py`. It never searches `~/.claude/plugins/cache` and never falls back to the sibling checkout. If the check fails it prints one stderr line and exits 0, so the hooks do nothing.
  - The hook runs under `sys.executable` (no venv lookup, no degraded-venv line) and is started with `python -I`, so a planted `pyhooks/`, `sdlc_pyhooks/` or `json.py` in the checkout is never imported. `PYTHONPATH` from the environment is ignored; the import path is exactly this plugin's root and the base plugin root.
  - If the base plugin cannot be imported, each hook prints `[neuroloom-sdlc] CI mode: base plugin import failed (<ExceptionTypeName>); hooks do nothing` to stderr (the exception type only) and exits 0.
- **Version skew fails closed.** `sdlc_pyhooks.mode_state()` returns `normal`, `ci` or `skew`. It reads `NEUROLOOM_MODE` from the environment and checks that the base plugin's `Config` declares `ci_mode`. When the environment says CI and the base plugin cannot report it (too old, or not importable), both hooks do nothing: no database, no API call.

### Changed

- The README paragraph that told you to leave `NEUROLOOM_CLAUDE_PLUGIN_ROOT` unset is corrected: leaving it unset is still right for attended sessions on a marketplace install, but in CI mode the variable is required.
- Outside CI mode nothing changes in the SDLC hooks, except through the base plugin: they read the key through `config.load()`, so they inherit the base plugin's project-root cutover (the key and state come from `<project root>/.neuroloom.db`, not the directory Claude is in). See the base plugin's changelog.

### Fixed

- The README's endpoint table listed `POST /api/v1/memories/search` for the SessionStart sentinel lookup; the hook calls `GET /api/v1/memories/?tags=sdlc:sentinel&limit=1`.
