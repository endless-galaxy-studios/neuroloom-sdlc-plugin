"""Every command in hooks/hooks.json must go through the launcher with a plain module name."""

from __future__ import annotations

import json
import re
from pathlib import Path

_HOOKS_JSON = Path(__file__).resolve().parent.parent / "hooks" / "hooks.json"
_COMMAND = re.compile(r"python3 \$\{CLAUDE_PLUGIN_ROOT\}/run_hook\.py [a-z_.]+")


def _commands() -> list[str]:
    data = json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))
    return [
        hook["command"]
        for groups in data["hooks"].values()
        for group in groups
        for hook in group["hooks"]
    ]


def test_hooks_json_has_commands() -> None:
    assert len(_commands()) >= 2


def test_every_command_matches_the_launcher_shape_exactly() -> None:
    for command in _commands():
        assert _COMMAND.fullmatch(command), command


def test_pattern_rejects_look_alikes() -> None:
    for bad in (
        "python3 ${CLAUDE_PLUGIN_ROOT}/run_hook.py sdlc_pyhooks.x; rm -rf /",
        "python3 ${CLAUDE_PLUGIN_ROOT}/run_hook.py ../evil",
        "python ${CLAUDE_PLUGIN_ROOT}/run_hook.py sdlc_pyhooks.x",
        "python3 /abs/run_hook.py sdlc_pyhooks.x",
    ):
        assert not _COMMAND.fullmatch(bad), bad
