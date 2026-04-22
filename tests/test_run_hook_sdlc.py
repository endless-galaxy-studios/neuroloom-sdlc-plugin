"""
Unit tests for neuroloom-sdlc-plugin/run_hook.py launcher.

Loads the module via importlib.util.spec_from_file_location so that the
__main__ block never executes and sys.path is not permanently polluted.

All tests that touch filesystem-dependent helpers (_resolve_base_root,
_resolve_python) patch the relevant Path methods and os.environ to keep
tests hermetic.
"""

import importlib.util
import os
import sys
import types
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Module loader — imported once and shared across the test session.
# ---------------------------------------------------------------------------

_RUN_HOOK_PATH = Path(__file__).resolve().parent.parent / "run_hook.py"


def _load_run_hook() -> types.ModuleType:
    """Load run_hook.py without executing __main__."""
    spec = importlib.util.spec_from_file_location("run_hook_sdlc", _RUN_HOOK_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Load once — the module is stateless at module level (no __main__ side effects).
_mod = _load_run_hook()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_candidate(tmp_path: Path, version: str, has_run_hook: bool = True) -> Path:
    """Create a fake versioned cache directory optionally containing run_hook.py."""
    d = tmp_path / version
    d.mkdir(parents=True, exist_ok=True)
    if has_run_hook:
        (d / "run_hook.py").touch()
    return d


# ---------------------------------------------------------------------------
# _resolve_base_root — env override tests
# ---------------------------------------------------------------------------


def test_env_override_wins(tmp_path: Path) -> None:
    """Env var pointing to an existing directory is returned immediately."""
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()

    with patch.dict(os.environ, {"NEUROLOOM_CLAUDE_PLUGIN_ROOT": str(plugin_dir)}):
        # Patch glob so it would raise if called — confirms glob is NOT reached.
        with patch.object(Path, "glob", side_effect=AssertionError("glob must not be called")):
            result, err = _mod._resolve_base_root()

    assert result == plugin_dir.resolve()
    assert err == ""


def test_env_override_missing_path_falls_through_to_not_found(tmp_path: Path) -> None:
    """Env var set to a non-existent path returns (None, diagnostic)."""
    missing = tmp_path / "does_not_exist"
    # Do NOT create missing — it must not exist.

    # Suppress marketplace glob and sibling so we reach step 4.
    with patch.dict(os.environ, {"NEUROLOOM_CLAUDE_PLUGIN_ROOT": str(missing)}):
        result, err = _mod._resolve_base_root()

    assert result is None
    assert "NEUROLOOM_CLAUDE_PLUGIN_ROOT" in err
    assert "does not exist" in err


def test_env_override_empty_string_falls_through(tmp_path: Path) -> None:
    """Empty string env var is falsy — treated as unset; falls through to discovery."""
    # Provide a valid sibling so we get a result rather than None.
    sibling = tmp_path / "neuroloom-claude-plugin"
    sibling.mkdir()

    # Patch SDLC_ROOT.parent so that the sibling check resolves to tmp_path.
    with patch.dict(os.environ, {"NEUROLOOM_CLAUDE_PLUGIN_ROOT": ""}):
        with patch.object(_mod, "SDLC_ROOT", tmp_path / "neuroloom-sdlc-plugin"):
            # Also suppress the marketplace cache so the sibling is found at step 3.
            with patch.object(Path, "home", return_value=tmp_path / "nonexistent_home"):
                result, err = _mod._resolve_base_root()

    # The empty string must NOT be used as an override — we must have fallen through.
    assert result is not None
    assert result == sibling
    assert err == ""


# ---------------------------------------------------------------------------
# _resolve_base_root — marketplace cache tests
# ---------------------------------------------------------------------------


def test_marketplace_glob_returns_newest_version(tmp_path: Path) -> None:
    """When two versioned dirs exist, the highest semver wins."""
    cache_base = tmp_path / ".claude" / "plugins" / "cache"
    ns_dir = cache_base / "endless-galaxy-studios" / "neuroloom"
    _fake_candidate(ns_dir, "0.6.1")
    _fake_candidate(ns_dir, "0.7.0")

    with patch.dict(os.environ, {}, clear=False):
        # Remove env override if set in outer environment.
        env = {k: v for k, v in os.environ.items() if k != "NEUROLOOM_CLAUDE_PLUGIN_ROOT"}
        with patch.dict(os.environ, env, clear=True):
            with patch.object(Path, "home", return_value=tmp_path):
                result, err = _mod._resolve_base_root()

    assert result is not None
    assert result.name == "0.7.0"
    assert err == ""


def test_marketplace_glob_sorts_semver_not_lex(tmp_path: Path) -> None:
    """0.10.0 must win over 0.7.0 (tuple-of-ints sort, not lexicographic)."""
    cache_base = tmp_path / ".claude" / "plugins" / "cache"
    ns_dir = cache_base / "endless-galaxy-studios" / "neuroloom"
    _fake_candidate(ns_dir, "0.6.1")
    _fake_candidate(ns_dir, "0.7.0")
    _fake_candidate(ns_dir, "0.10.0")

    env = {k: v for k, v in os.environ.items() if k != "NEUROLOOM_CLAUDE_PLUGIN_ROOT"}
    with patch.dict(os.environ, env, clear=True):
        with patch.object(Path, "home", return_value=tmp_path):
            result, err = _mod._resolve_base_root()

    assert result is not None
    assert result.name == "0.10.0", (
        f"Expected '0.10.0' but got '{result.name}' — "
        "tuple-of-ints sort must be used, not lexicographic"
    )
    assert err == ""


# ---------------------------------------------------------------------------
# _resolve_base_root — dev sibling test
# ---------------------------------------------------------------------------


def test_dev_sibling_layout(tmp_path: Path) -> None:
    """No env var, no cache hits — falls through to sibling directory."""
    sibling = tmp_path / "neuroloom-claude-plugin"
    sibling.mkdir()

    env = {k: v for k, v in os.environ.items() if k != "NEUROLOOM_CLAUDE_PLUGIN_ROOT"}
    with patch.dict(os.environ, env, clear=True):
        # Point home to a location with no cache so step 2 yields nothing.
        with patch.object(Path, "home", return_value=tmp_path / "empty_home"):
            with patch.object(_mod, "SDLC_ROOT", tmp_path / "neuroloom-sdlc-plugin"):
                result, err = _mod._resolve_base_root()

    assert result == sibling
    assert err == ""


# ---------------------------------------------------------------------------
# _resolve_base_root — nothing found
# ---------------------------------------------------------------------------


def test_nothing_found_returns_none_with_diagnostic(tmp_path: Path) -> None:
    """No env var, no cache, no sibling → (None, non-empty diagnostic string)."""
    env = {k: v for k, v in os.environ.items() if k != "NEUROLOOM_CLAUDE_PLUGIN_ROOT"}
    with patch.dict(os.environ, env, clear=True):
        with patch.object(Path, "home", return_value=tmp_path / "empty_home"):
            # SDLC_ROOT parent has no neuroloom-claude-plugin sibling.
            with patch.object(_mod, "SDLC_ROOT", tmp_path / "sdlc" / "neuroloom-sdlc-plugin"):
                result, err = _mod._resolve_base_root()

    assert result is None
    assert len(err) > 0
    assert "neuroloom-claude-plugin" in err


# ---------------------------------------------------------------------------
# _resolve_python
# ---------------------------------------------------------------------------


def test_venv_present_uses_venv_python(tmp_path: Path) -> None:
    """When .venv/bin/python exists, return that path and degraded=False."""
    base_root = tmp_path / "base"
    if sys.platform == "win32":
        venv_py = base_root / ".venv" / "Scripts" / "python.exe"
    else:
        venv_py = base_root / ".venv" / "bin" / "python"
    venv_py.parent.mkdir(parents=True)
    venv_py.touch()

    with patch("sys.platform", "win32" if sys.platform == "win32" else "linux"):
        result_path, degraded = _mod._resolve_python(base_root)

    assert result_path == venv_py
    assert degraded is False


def test_venv_absent_falls_back_to_sys_executable(tmp_path: Path) -> None:
    """When .venv/bin/python is absent, return sys.executable and degraded=True."""
    base_root = tmp_path / "base"
    base_root.mkdir()
    # Do NOT create .venv — it must be absent.

    result_path, degraded = _mod._resolve_python(base_root)

    assert str(result_path) == sys.executable
    assert degraded is True
