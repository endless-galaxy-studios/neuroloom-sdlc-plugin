"""
D178d Phase 6: SDLC plugin lifecycle proof, with bait and control.

Real hook processes, one per step, started through the SDLC launcher against the
bait repository, in CI mode: SessionStart, then three edits of a deliverable
under ``docs/current_work`` (one of them after a real ``cd sub``).

CI run:   tree hash unchanged, nothing new on disk, and the ONLY requests are the
          two reads (version proxy, sentinel list), both of which must arrive.
          No ``docs/current_work`` edit produces a request.
Control:  the identical sequence without ``NEUROLOOM_MODE``, evaluated by the
          identical predicates, must fire every SDLC bait trigger (a document is
          uploaded, a failed upload is buffered locally, the slash-command
          notice is printed).

Plain-language picture: the bait is a mousetrap, the control is the pencil that
sets it off.  A clean CI run only means "no mouse" if the pencil springs the trap.

The base plugin's plan placed the lifecycle test in one file; it is split across
the two repositories (spec 6.3 deviation, see the plan), and this file is the
SDLC half.  The recorder comes from the base plugin's ``ci_support`` (loaded by
file path in this suite's conftest); both runs use the same one, with the ingest
endpoint answering 500, which is strictly more sensitive than a 200 recorder
(a CI-mode upload regression would also leave a buffered row).
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

import ci_support  # loaded by tests/conftest.py (base plugin's tests/ci_support.py)

_SDLC_ROOT = Path(__file__).resolve().parent.parent
_BASE_ROOT = _SDLC_ROOT.parent / "neuroloom-claude-plugin"

_INTERPRETERS = ci_support.interpreter_params()

VERSION_PATH = "/api/v1/sdlc/cc-sdlc-version"
SENTINEL_PATH = "/api/v1/memories/?tags=sdlc:sentinel&limit=1"
INGEST_PATH = "/api/v1/documents/ingest"
ALLOWLIST = [("GET", VERSION_PATH), ("GET", SENTINEL_PATH)]

# Spec section 5.6, copied literally (a stable contract).
BEHIND_LINE_CI = (
    "[Neuroloom SDLC] Workspace SDLC knowledge is at 1.0.0; latest is 2.0.0. "
    "No action is taken in CI mode."
)
_ALLOWED_NEW_NAMES = {".neuroloom.db", ".neuroloom.db-wal", ".neuroloom.db-shm"}


@pytest.fixture()
def black_hole() -> Iterator[ci_support.BlackHole]:
    """Counts connections; here it only gives pip a dead index (the SDLC conftest has no fixture for it)."""
    hole = ci_support.BlackHole()
    try:
        yield hole
    finally:
        hole.close()


@pytest.fixture()
def recorder() -> Iterator[ci_support.SlimRecorder]:
    """The ingest endpoint answers 500 in BOTH the CI run and the control, so a
    CI-mode upload would also leave a buffered row (strictly more sensitive)."""
    rec = ci_support.SlimRecorder(status_overrides={INGEST_PATH: 500})
    try:
        yield rec
    finally:
        rec.close()


# ---------------------------------------------------------------------------
# The sequence
# ---------------------------------------------------------------------------


@dataclass
class _Sequence:
    runs: list[ci_support.HookRun]
    requests_before_docs: int  # len(requests) once SessionStart has finished


def _doc_event(tool: str, path: Path, cwd: Path) -> str:
    return json.dumps({"tool_name": tool, "tool_input": {"file_path": str(path)}, "cwd": str(cwd)})


def _arm_bait(tmp_path: Path) -> tuple[ci_support.Bait, str, list[str]]:
    bait = ci_support.make_bait_repo(tmp_path / "bait")
    docs = bait.root / "docs" / "current_work"
    docs.mkdir(parents=True)
    (docs / "d9_x_spec.md").write_text("# Spec\n\nDeliverable text.\n", encoding="utf-8")
    (docs / "d9_x_plan.md").write_text("# Plan\n\nPlan text.\n", encoding="utf-8")
    (bait.root / "sub").mkdir()
    return bait, ci_support.tree_hash(bait.root), ci_support.presence_snapshot(bait.root)


def _run_sequence(
    bait: ci_support.Bait,
    rec: ci_support.SlimRecorder,
    hole: ci_support.BlackHole,
    scratch: Path,
    *,
    ci: bool,
    interpreter: str,
) -> _Sequence:
    root = bait.root
    sub = root / "sub"
    spec = root / "docs" / "current_work" / "d9_x_spec.md"
    plan = root / "docs" / "current_work" / "d9_x_plan.md"
    steps: list[tuple[str, str, str, Path]] = [
        ("session_start", "sdlc_pyhooks.session_start", json.dumps({"hook_event_name": "SessionStart", "cwd": str(root)}), root),
        ("write spec", "sdlc_pyhooks.post_tool_use", _doc_event("Write", spec, root), root),
        ("edit spec", "sdlc_pyhooks.post_tool_use", _doc_event("Edit", spec, root), root),
        # After a real chdir into sub: the edit of a deliverable by absolute path.
        ("write plan after cd", "sdlc_pyhooks.post_tool_use", _doc_event("Write", plan, sub), sub),
    ]
    env: dict[str, str] = {
        "CLAUDE_PROJECT_DIR": str(root),
        "NEUROLOOM_API_BASE": rec.url,
        "NEUROLOOM_CLAUDE_PLUGIN_ROOT": str(_BASE_ROOT),
        # The origin probe runs before the launcher builds its own path.
        "PYTHONPATH": f"{_SDLC_ROOT}{os.pathsep}{_BASE_ROOT}",
    }
    if ci:
        env["NEUROLOOM_MODE"] = "ci"
    runs: list[ci_support.HookRun] = []
    before_docs = 0
    for label, module, stdin, cwd in steps:
        if label == "write spec":
            before_docs = len(rec.requests)
        try:
            runs.append(
                ci_support.run_hook(
                    module,
                    stdin=stdin,
                    cwd=cwd,
                    scratch=scratch,
                    black_hole_url=hole.url,
                    env_extra=env,
                    interpreter=interpreter,
                    plugin_root=_SDLC_ROOT,
                    expected_root=_BASE_ROOT,
                    control=not ci,
                    timeout=30.0,
                )
            )
        except Exception as exc:
            pytest.fail(f"SDLC lifecycle step {label!r} failed to run ({type(exc).__name__})")
    return _Sequence(runs, before_docs)


def _document_rows(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        return int(conn.execute("SELECT COUNT(*) FROM event_buffer WHERE payload_type = 'document'").fetchone()[0])
    finally:
        conn.close()


def _report(
    bait: ci_support.Bait,
    rec: ci_support.SlimRecorder,
    seq: _Sequence,
    *,
    before_hash: str,
    before_names: list[str],
    document_rows_before: int,
) -> dict[str, bool]:
    """Booleans only.  CI requires the first group True and the triggers quiet;
    the control must see the triggers fire."""
    after_names = ci_support.presence_snapshot(bait.root)
    paths = rec.paths()
    return {
        "tree_unchanged": ci_support.tree_hash(bait.root) == before_hash,
        "no_new_files_below_root": (set(after_names) - set(before_names)) <= _ALLOWED_NEW_NAMES,
        "no_db_in_sub": not any(n.startswith("sub/") and ".neuroloom.db" in n for n in after_names),
        "allowlist_is_the_two_reads": sorted(paths) == sorted(ALLOWLIST),
        "no_request_from_doc_edits": len(rec.requests) == seq.requests_before_docs,
        "all_hooks_exit_zero": all(r.returncode == 0 for r in seq.runs),
        # Triggers (named like the base bait table: True = the unsafe effect happened).
        "doc_ingest_sent": any(p == INGEST_PATH for _m, p in paths),
        "doc_buffered_on_failure": _document_rows(bait.db_path) > document_rows_before,
        "slash_command_notice": "/sdlc-migrate" in seq.runs[0].stdout,
    }


_TRIGGERS = ("doc_ingest_sent", "doc_buffered_on_failure", "slash_command_notice")


@pytest.mark.parametrize("interpreter", _INTERPRETERS)
class TestSdlcCiLifecycleWithBaitAndControl:
    def test_ci_run_reads_twice_and_changes_nothing(
        self, interpreter: str, tmp_path: Path, black_hole: ci_support.BlackHole, recorder: ci_support.SlimRecorder
    ) -> None:
        bait, before_hash, before_names = _arm_bait(tmp_path)
        rows_before = _document_rows(bait.db_path)

        seq = _run_sequence(bait, recorder, black_hole, tmp_path / "scratch", ci=True, interpreter=interpreter)
        report = _report(
            bait, recorder, seq, before_hash=before_hash, before_names=before_names, document_rows_before=rows_before
        )

        must_hold = (
            "tree_unchanged",
            "no_new_files_below_root",
            "no_db_in_sub",
            "allowlist_is_the_two_reads",
            "no_request_from_doc_edits",
            "all_hooks_exit_zero",
        )
        failed = sorted(name for name in must_hold if not report[name])
        assert not failed, f"SDLC CI lifecycle predicates failed: {failed}"
        fired = sorted(name for name in _TRIGGERS if report[name])
        assert not fired, f"SDLC CI lifecycle: bait triggers fired: {fired}"
        # Positive minimum, stated on its own: BOTH reads arrived.
        assert ("GET", VERSION_PATH) in recorder.paths(), "SDLC CI lifecycle: the version read never arrived"
        assert ("GET", SENTINEL_PATH) in recorder.paths(), "SDLC CI lifecycle: the sentinel read never arrived"
        # The agent's context carries only the neutral line, never a slash command.
        neutral_line = seq.runs[0].stdout.strip() == BEHIND_LINE_CI
        assert neutral_line, "SDLC CI lifecycle: SessionStart stdout is not the CI line"
        # And nothing connected to the dead pip index.
        hole_untouched = black_hole.connection_count() == 0
        assert hole_untouched, "SDLC CI lifecycle: something connected to the black hole"

    def test_non_ci_control_fires_every_sdlc_trigger(
        self,
        interpreter: str,
        tmp_path: Path,
        black_hole: ci_support.BlackHole,
        recorder: ci_support.SlimRecorder,
    ) -> None:
        """Same fixture, same sequence, same predicates, normal mode.

        The ingest endpoint answers 500 (the shared recorder) so the failed-upload
        buffering trigger is reachable too.
        """
        rec = recorder
        bait, before_hash, before_names = _arm_bait(tmp_path)
        rows_before = _document_rows(bait.db_path)

        seq = _run_sequence(bait, rec, black_hole, tmp_path / "scratch", ci=False, interpreter=interpreter)
        report = _report(
            bait, rec, seq, before_hash=before_hash, before_names=before_names, document_rows_before=rows_before
        )

        not_fired = sorted(name for name in _TRIGGERS if not report[name])
        assert not not_fired, f"SDLC control: bait triggers that did NOT fire in normal mode: {not_fired}"
        assert report["allowlist_is_the_two_reads"] is False, "SDLC control: traffic stayed inside the CI allowlist"
        assert report["no_request_from_doc_edits"] is False, "SDLC control: doc edits produced no request"
        assert report["all_hooks_exit_zero"], "SDLC control: a hook exited non-zero, the control is unreliable"
        # The reads still happen in normal mode, so the control differs only by the mode.
        assert ALLOWLIST[0] in rec.paths() and ALLOWLIST[1] in rec.paths(), "SDLC control: the two reads are missing"
        hole_untouched = black_hole.connection_count() == 0
        assert hole_untouched, "SDLC control: something connected to the black hole (the offline shim leaked)"
