"""
Standing check: the SDLC suite must exercise the sibling base worktree.

If ``pyhooks`` resolves anywhere else (typically the main checkout, via the base
venv's editable install) every SDLC test that touches base-plugin code would be
testing the wrong code while still passing.  See ``tests/conftest.py``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pyhooks

_BASE_ROOT = Path(__file__).resolve().parent.parent.parent / "neuroloom-claude-plugin"


def test_pyhooks_is_imported_from_the_sibling_base_worktree() -> None:
    origin = Path(pyhooks.__file__).resolve()
    assert _BASE_ROOT.resolve() in origin.parents, "pyhooks was imported from outside the sibling base plugin"


def test_base_root_is_on_sys_path() -> None:
    assert str(_BASE_ROOT) in sys.path


def test_child_process_with_conftest_path_setup_imports_the_same_origin() -> None:
    probe = (
        "import sys; sys.path.insert(0, sys.argv[1]); import pyhooks; "
        "sys.stdout.write(pyhooks.__file__)"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe, str(_BASE_ROOT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0
    assert _BASE_ROOT.resolve() in Path(done.stdout.strip()).resolve().parents
