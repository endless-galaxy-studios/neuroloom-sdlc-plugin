"""The four NEUROLOOM_MODE parsers must agree on every input.

``pyhooks.config.parse_mode`` is canonical; the two launchers and
``sdlc_pyhooks.parse_mode`` are deliberate copies (the launchers run before any
plugin package can be imported). Each copy is tested against the mode table in its
own file; this test closes the gap between the tables: one corpus, every parser,
same answer.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_SDLC_ROOT = Path(__file__).resolve().parent.parent
_BASE_ROOT = _SDLC_ROOT.parent / "neuroloom-claude-plugin"

# The documented table rows, plus inputs it does not name: other whitespace kinds
# (tab, newline, no-break space, ideographic space, zero-width space), mixed case, and
# Unicode that str.lower()/strip() treat specially (dotless i, dotted capital I,
# fullwidth letters, Kelvin sign). NUL is excluded: os.environ cannot hold it.
CORPUS: list[str | None] = [
    None, "", " ", "   ", "\t", "\n", " \r\n\t ", "\u00a0", "\u2003", "\u200b",
    "ci", "CI", "Ci", "cI", " ci ", "\tci\n", "ci\n", "\u2003ci\u2003", "\u00a0ci",
    "prod", "ci2", "cii", "off", "false", "0", "none", "normal", "true", "ci ci",
    "c i", "c\u0131", "C\u0130", "\uff23\uff29", "\u212a", "x" * 10_000,
]


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def parsers() -> dict[str, ModuleType]:
    import sdlc_pyhooks
    from pyhooks import config

    return {
        "config": config,
        "sdlc_helper": sdlc_pyhooks,
        "base_launcher": _load(_BASE_ROOT / "run_hook.py", "run_hook_base_agree"),
        "sdlc_launcher": _load(_SDLC_ROOT / "run_hook.py", "run_hook_sdlc_agree"),
    }


def _label(raw: str | None) -> str:
    return "unset" if raw is None else ascii(raw)[:24]


@pytest.mark.parametrize("raw", CORPUS, ids=[_label(r) for r in CORPUS])
def test_all_parsers_agree(
    raw: str | None, parsers: dict[str, ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    if raw is None:
        monkeypatch.delenv("NEUROLOOM_MODE", raising=False)
    else:
        monkeypatch.setenv("NEUROLOOM_MODE", raw)
    canonical = parsers["config"].parse_mode(raw)
    helper = parsers["sdlc_helper"].parse_mode(raw)
    ci_votes = {
        "config.parse_mode": canonical.ci,
        "sdlc_pyhooks.parse_mode": helper.ci,
        "base launcher _ci_mode": parsers["base_launcher"]._ci_mode(),
        "sdlc launcher _ci_mode": parsers["sdlc_launcher"]._ci_mode(),
        "config.load().ci_mode": parsers["config"].load().ci_mode,
    }
    # The launchers only know "CI or not": compare `ci` everywhere, and `recognised`
    # between the two parse_mode implementations.
    where = f"mode-parser disagreement on input #{CORPUS.index(raw)} {_label(raw)}: {ci_votes}"
    assert len(set(ci_votes.values())) == 1, where
    assert (helper.ci, helper.recognised) == (canonical.ci, canonical.recognised), where
