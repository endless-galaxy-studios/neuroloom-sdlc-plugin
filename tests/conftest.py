"""
Shared pytest configuration for the neuroloom-sdlc-plugin test suite (D178d).

Two jobs:

1. **Pin the base plugin.**  The SDLC hooks import ``pyhooks`` from the sibling
   ``neuroloom-claude-plugin`` checkout.  The base plugin's virtual environment
   ships an editable install that maps ``pyhooks`` to the *main* checkout, so
   without an explicit path the suite can pass green while testing the wrong
   code.  The sibling's root is therefore put at ``sys.path[0]`` here, at import
   time (collection imports test modules before any fixture runs), and only then
   is the base plugin's shared test-support module loaded by file path -- this
   suite has no ``tests`` package to import it from.

2. **Hermetic environment.**  Every test starts without ``NEUROLOOM_MODE``,
   ``NEUROLOOM_CLAUDE_PLUGIN_ROOT``, ``CLAUDE_PROJECT_DIR`` or any
   credential-shaped variable, and with ``HOME`` pointing at an empty temporary
   directory (a real plugin cache under the developer's home would otherwise be
   found by the launcher's glob).  A test that needs one of them sets it
   explicitly afterwards.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest

_SDLC_ROOT = Path(__file__).resolve().parent.parent
BASE_ROOT = _SDLC_ROOT.parent / "neuroloom-claude-plugin"

if not (BASE_ROOT / "pyhooks").is_dir():
    raise RuntimeError(
        "the sibling neuroloom-claude-plugin checkout was not found next to this "
        "plugin; the SDLC tests would run against the wrong base code"
    )

# Base worktree first, before anything can import pyhooks.
sys.path.insert(0, str(BASE_ROOT))


def _load_ci_support() -> types.ModuleType:
    path = BASE_ROOT / "tests" / "ci_support.py"
    spec = importlib.util.spec_from_file_location("ci_support", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ci_support"] = module
    spec.loader.exec_module(module)
    return module


ci_support = _load_ci_support()


@pytest.fixture(autouse=True)
def _hermetic_environment(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    for name in (
        "NEUROLOOM_MODE",
        "NEUROLOOM_CLAUDE_PLUGIN_ROOT",
        "CLAUDE_PROJECT_DIR",
        *ci_support.credential_env_names(os.environ),
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path_factory.mktemp("home")))
