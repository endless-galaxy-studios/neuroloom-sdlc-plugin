"""Tests for skills/sdlc-port/scripts/decide_port_gate.py (``/sdlc-port`` Gate 3).

The table mirrors the architect's replay grid (r11/r12 ``gate3``), one row per
situation, plus the rows added for the gaps the grid did not cover.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = Path(__file__).parent.parent / "skills" / "sdlc-port" / "scripts" / "decide_port_gate.py"


def _decide(facts: dict[str, Any]) -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("decide_port_gate", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result: dict[str, Any] = module.decide(facts)
    return result


def _obs(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"search_ok": True, "index_ok": True, "workspace_id": "W_A",
                            "sentinel": False,
                            "sentinel_label": None, "sdlc_rows": False,
                            "current_sdlc_version": "v2.12.2"}
    base.update(kw)
    return base


def _ported(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"ported_at": "2026-11-20", "neuroloom_backend": True,
                            "knowledge_id_scheme": 2, "workspace_id": "W_A",
                            "knowledge_seed_version": "v2.4.1", "source_version": "v2.4.1"}
    base.update(kw)
    return base


# (name, manifest, observed, case, action, reason)
ROWS: list[tuple[str, dict[str, Any], dict[str, Any], int, str, str]] = [
    # --- case 0
    ("search failed", {}, _obs(search_ok=False), 0, "stop", "search_failed"),
    ("search failed beats a stopped port", {"port_in_progress": True, "workspace_id": "W_A"},
     _obs(search_ok=False), 0, "stop", "search_failed"),
    # --- case 5
    ("1a fresh port, empty ws", {"source_version": "v2.4.1"}, _obs(), 5, "fresh", "nothing_there"),
    ("no manifest at all", {}, _obs(), 5, "fresh", "nothing_there"),
    ("N real Neuroloom manifest, empty ws", {"source_version": "v2.4.1", "source_version_sha": "5d78406"},
     _obs(), 5, "fresh", "nothing_there"),
    ("untagged install, empty ws", {"source_version": "unknown", "source_version_sha": "e1be9744abc"},
     _obs(), 5, "fresh", "nothing_there"),
    ("no version keys, empty ws", {"install_date": "x"}, _obs(), 5, "fresh", "nothing_there"),
    # --- case 1
    ("1b' stopped port, same ws, sentinel", {"port_in_progress": True, "workspace_id": "W_A"},
     _obs(sentinel=True, sentinel_label="v2.4.1"), 1, "continue_fresh", "same_workspace"),
    ("1d' stopped port, same ws, no sentinel yet", {"port_in_progress": True, "workspace_id": "W_A"},
     _obs(), 1, "continue_fresh", "same_workspace"),
    ("1b'' stopped port, key on another project's ws", {"port_in_progress": True, "workspace_id": "W_A"},
     _obs(workspace_id="W_B", sentinel=True), 1, "stop", "different_workspace"),
    ("S3 stopped manifest copied to project B", {"port_in_progress": True, "workspace_id": "W_A"},
     _obs(workspace_id="W_D"), 1, "stop", "different_workspace"),
    ("S5 marker without workspace_id", {"port_in_progress": True, "knowledge_id_scheme": 2},
     _obs(sentinel=True), 1, "stop", "no_workspace_id"),
    # --- case 2 (three kinds, told apart by what the manifest shows)
    ("I finished initialize", {"adapter_names_plugin": True, "neuroloom_backend": True,
                                "knowledge_id_scheme": 2, "workspace_id": "W_A"},
     _obs(sentinel=True), 2, "stop", "initialized_project"),
    ("I' half-failed initialize (adapter, no backend)", {"adapter_names_plugin": True,
                                                         "workspace_id": "W_A"},
     _obs(sentinel=True), 2, "stop", "unfinished_initialize"),
    ("I'' half-failed initialize, no sentinel", {"adapter_names_plugin": True},
     _obs(), 2, "stop", "unfinished_initialize"),
    ("half-seeded initialize, adapter block removed by hand", {"knowledge_seed_in_progress": True,
                                                              "neuroloom_backend": True,
                                                              "knowledge_id_scheme": 2},
     _obs(sentinel=True), 2, "stop", "unfinished_initialize"),
    ("knowledge_seed_in_progress alone", {"knowledge_seed_in_progress": True}, _obs(), 2, "stop",
     "unfinished_initialize"),
    # A re-seed that stopped after step 5 removed the scheme marker: an unfinished initialize,
    # not one from before 0.7.0 (the in-progress key is checked first).
    ("re-seed stopped: in progress and backend, no scheme", {"knowledge_seed_in_progress": True,
                                                            "neuroloom_backend": True,
                                                            "workspace_id": "W_A"},
     _obs(sentinel=True), 2, "stop", "unfinished_initialize"),
    ("initialize from before 0.7.0 (backend, no scheme)", {"neuroloom_backend": True}, _obs(), 2,
     "stop", "pre_0_7_0_initialize"),
    ("port_in_progress plus an adapter block", {"port_in_progress": True, "adapter_names_plugin": True,
                                                 "workspace_id": "W_A"}, _obs(), 2, "stop",
     "unfinished_initialize"),
    ("port_in_progress plus neuroloom_backend, no scheme", {"port_in_progress": True,
                                                              "neuroloom_backend": True,
                                                              "workspace_id": "W_A"},
     _obs(), 2, "stop", "pre_0_7_0_initialize"),
    ("port_in_progress plus a finished initialize", {"port_in_progress": True,
                                                       "neuroloom_backend": True,
                                                       "knowledge_id_scheme": 2,
                                                       "workspace_id": "W_A"},
     _obs(sentinel=True), 2, "stop", "initialized_project"),
    # --- case 3
    ("4a re-port, files on disk", _ported(), _obs(sentinel=True, sentinel_label="v2.4.1"),
     3, "ask", "reported"),
    ("4c' untagged re-port", _ported(source_version="unknown", source_version_sha="e1be9744abc",
                                      knowledge_seed_version="e1be974"),
     _obs(sentinel=True, sentinel_label="e1be974"), 3, "ask", "reported"),
    ("leading v ignored in the label rule", _ported(source_version="2.4.1"),
     _obs(sentinel=True, sentinel_label="v2.4.1"), 3, "ask", "reported"),
    ("4d' no version keys, a new release since", _ported(source_version=None, knowledge_seed_version="v2.4.1"),
     _obs(sentinel=True, sentinel_label="v2.4.1", current_sdlc_version="v2.12.3"), 3, "ask", "reported"),
    ("4z ported plus leftover port_in_progress", _ported(port_in_progress=True),
     _obs(sentinel=True, sentinel_label="v2.4.1"), 3, "ask", "reported"),
    ("re-port, manifest records no knowledge_seed_version", _ported(knowledge_seed_version=None),
     _obs(sentinel=True, sentinel_label="v2.4.1"), 3, "stop", "no_seed_version"),
    ("pre-0.7.0 port (no scheme 2)", _ported(knowledge_id_scheme=None),
     _obs(sentinel=True, sentinel_label="v2.4.1"), 3, "stop", "pre_0_7_0_port"),
    ("ported_at without neuroloom_backend (hand edit)",
     {k: v for k, v in _ported().items() if k != "neuroloom_backend"},
     _obs(sentinel=True, sentinel_label="v2.4.1"), 3, "stop", "incomplete_port_record"),
    ("ported_at with neuroloom_backend false", _ported(neuroloom_backend=False),
     _obs(sentinel=True, sentinel_label="v2.4.1"), 3, "stop", "incomplete_port_record"),
    ("re-port with no workspace_id", _ported(workspace_id=None),
     _obs(sentinel=True, sentinel_label="v2.4.1"), 3, "stop", "no_workspace_id"),
    ("4x re-port, key on another ws", _ported(), _obs(workspace_id="W_B", sentinel=True,
                                                     sentinel_label="v2.4.1"), 3, "stop",
     "different_workspace"),
    ("legacy rows with no sentinel", _ported(), _obs(sentinel=False, sdlc_rows=True), 3, "stop",
     "no_sentinel"),
    ("4y re-port after migrate (source_version moved)", _ported(source_version="v2.12.3"),
     _obs(sentinel=True, sentinel_label="v2.12.3"), 3, "stop", "label_differs"),
    ("sentinel label moved after a migration, source_version stayed", _ported(),
     _obs(sentinel=True, sentinel_label="v2.12.3"), 3, "stop", "sentinel_moved"),
    ("4z' leftover marker after a migrate", _ported(port_in_progress=True, source_version="v2.12.3"),
     _obs(sentinel=True, sentinel_label="v2.12.3"), 3, "stop", "label_differs"),
    # --- case 4
    ("L1 stopped, git checkout dropped the marker, sentinel", {"source_version": "v2.4.1"},
     _obs(sentinel=True, sentinel_label="v2.4.1"), 4, "stop", "unaccounted_rows"),
    ("N' real manifest, ws holds a 0.6.x seed", {"source_version": "v2.4.1"},
     _obs(sentinel=True, sentinel_label="v2.4.0"), 4, "stop", "unaccounted_rows"),
    ("U1 unmarked, another project's sentinel", {"source_version": "v2.4.1"},
     _obs(workspace_id="W_B", sentinel=True, sentinel_label="v2.12.2"), 4, "stop", "unaccounted_rows"),
    ("rows but no sentinel", {}, _obs(sdlc_rows=True), 4, "stop", "unaccounted_rows"),
    ("no version keys, sentinel at the latest release", {"install_date": "x"},
     _obs(sentinel=True, sentinel_label="v2.12.2"), 4, "stop", "unaccounted_rows"),
]


@pytest.mark.parametrize(("name", "manifest", "observed", "case", "action", "reason"), ROWS,
                         ids=[r[0] for r in ROWS])
def test_the_decision_table(name: str, manifest: dict[str, Any], observed: dict[str, Any],
                            case: int, action: str, reason: str) -> None:
    got = _decide({"manifest": manifest, "observed": observed})
    assert (got["case"], got["action"], got["reason"]) == (case, action, reason), name
    assert isinstance(got["message"], str) and got["message"]
    assert "recovery" in got


def test_case_4_reports_whether_the_label_matches() -> None:
    m = {"source_version": "v2.4.1"}
    hit = _decide({"manifest": m, "observed": _obs(sentinel=True, sentinel_label="2.4.1")})
    miss = _decide({"manifest": m, "observed": _obs(sentinel=True, sentinel_label="v2.12.2")})
    assert hit["label_matches"] is True and miss["label_matches"] is False
    assert "label_matches" not in _decide({"manifest": m, "observed": _obs()})


def test_the_label_prefers_source_version_then_the_sha_then_the_current_version() -> None:
    def lab(m: dict[str, Any], o: dict[str, Any] | None = None) -> bool:
        obs = _obs(sentinel=True, **(o or {}))
        return bool(_decide({"manifest": m, "observed": obs})["label_matches"])

    assert lab({"source_version": "v2.4.1"}, {"sentinel_label": "2.4.1"})
    assert lab({"source_version": "unknown", "source_version_sha": "5d78406042b"}, {"sentinel_label": "5d78406"})
    assert lab({"source_version_sha": "5d78406042b"}, {"sentinel_label": "5d78406"})
    # No version key: the label falls back to the latest release, which proves nothing.
    assert not lab({}, {"sentinel_label": "v2.12.2"})
    assert not lab({"source_version": "unknown"}, {"sentinel_label": "v2.4.1"})


def test_a_reported_decision_never_depends_on_the_current_version_when_keys_exist() -> None:
    m = _ported()
    a = _decide({"manifest": m, "observed": _obs(sentinel=True, sentinel_label="v2.4.1",
                                                  current_sdlc_version="v9.9.9")})
    assert a["action"] == "ask"


def _cli_facts(tmp_path: Path, facts: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "facts.json"
    path.write_text(json.dumps(facts))
    return subprocess.run([sys.executable, "-I", str(_SCRIPT), "--facts", str(path)],
                          capture_output=True, text=True, check=False)


def test_a_search_that_failed_needs_no_other_facts() -> None:
    assert _decide({"observed": {"search_ok": False}})["action"] == "stop"
    assert _decide({"observed": {"search_ok": False}})["case"] == 0


@pytest.mark.parametrize("search_ok", ["false", "true", 0, 1, None, "", []],
                         ids=["string false", "string true", "zero", "one", "null", "empty", "list"])
def test_search_ok_must_be_a_bool(tmp_path: Path, search_ok: Any) -> None:
    r = _cli_facts(tmp_path, {"manifest": {}, "observed": {"search_ok": search_ok}})
    assert r.returncode == 2 and r.stdout == "" and "search_ok" in r.stderr
    assert "Traceback" not in r.stderr
    with pytest.raises(ValueError, match="search_ok"):
        _decide({"manifest": {}, "observed": {"search_ok": search_ok}})


def test_a_missing_search_ok_is_not_a_failed_search() -> None:
    with pytest.raises(ValueError, match="search_ok"):
        _decide({})
    with pytest.raises(ValueError, match="search_ok"):
        _decide({"manifest": {}, "observed": {}})


@pytest.mark.parametrize("index_ok", [False, None, "true", 1],
                         ids=["false", "null", "string", "number"])
def test_a_successful_search_needs_index_ok_true(tmp_path: Path, index_ok: Any) -> None:
    observed = _obs()
    if index_ok is None:
        del observed["index_ok"]
    else:
        observed["index_ok"] = index_ok
    r = _cli_facts(tmp_path, {"manifest": {}, "observed": observed})
    assert r.returncode == 2 and r.stdout == "" and "index_ok" in r.stderr
    assert "re-gathered" in r.stderr and "no row" in r.stderr
    with pytest.raises(ValueError, match="re-gathered"):
        _decide({"manifest": {}, "observed": observed})


def test_index_ok_is_not_needed_when_the_search_failed() -> None:
    assert _decide({"observed": {"search_ok": False, "index_ok": False}})["case"] == 0


@pytest.mark.parametrize("observed", [
    {"search_ok": True, "index_ok": True},
    {"search_ok": True, "index_ok": True, "sentinel": False, "sdlc_rows": False},
    {"search_ok": True, "index_ok": True, "workspace_id": "W_A", "sdlc_rows": False},
    {"search_ok": True, "index_ok": True, "workspace_id": "W_A", "sentinel": False},
    {"search_ok": True, "index_ok": True, "workspace_id": None, "sentinel": False, "sdlc_rows": False},
    {"search_ok": True, "index_ok": True, "workspace_id": "W_A", "sentinel": "yes", "sdlc_rows": False},
    {"search_ok": True, "index_ok": True, "workspace_id": "W_A", "sentinel": False, "sdlc_rows": None},
], ids=["only search_ok", "no workspace_id", "no sentinel", "no sdlc_rows", "null workspace_id",
        "sentinel not a bool", "sdlc_rows null"])
def test_missing_or_malformed_observed_facts_exit_2_and_say_which(
    tmp_path: Path, observed: dict[str, Any]
) -> None:
    r = _cli_facts(tmp_path, {"manifest": {}, "observed": observed})
    assert r.returncode == 2 and r.stdout == "" and "Traceback" not in r.stderr
    missing = [k for k in ("workspace_id", "sentinel", "sdlc_rows")
               if k not in observed or observed[k] is None
               or (k != "workspace_id" and not isinstance(observed[k], bool))]
    assert missing and all(k in r.stderr for k in missing)
    with pytest.raises(ValueError, match=missing[0]):
        _decide({"manifest": {}, "observed": observed})


def test_a_complete_observed_block_is_accepted(tmp_path: Path) -> None:
    r = _cli_facts(tmp_path, {"manifest": {}, "observed": _obs()})
    assert r.returncode == 0 and json.loads(r.stdout)["action"] == "fresh"


def test_no_recovery_sends_the_user_to_a_command_that_halts_on_the_same_state() -> None:
    old = _decide({"manifest": _ported(knowledge_id_scheme=None),
                   "observed": _obs(sentinel=True, sentinel_label="v2.4.1")})
    assert old["reason"] == "pre_0_7_0_port"
    for text in (old["message"], old["recovery"]):
        assert "/sdlc-migrate" not in text and "/sdlc-port" not in text
    assert "conversion" in old["recovery"] and "does not" in old["recovery"]
    case4 = _decide({"manifest": {}, "observed": _obs(sentinel=True)})
    for text in (case4["message"], case4["recovery"]):
        assert "/sdlc-port" not in text
    kinds = {
        "pre_0_7_0_initialize": {"neuroloom_backend": True},
        "unfinished_initialize": {"adapter_names_plugin": True},
        "unfinished_initialize (seed marker)": {"knowledge_seed_in_progress": True,
                                                 "neuroloom_backend": True,
                                                 "knowledge_id_scheme": 2},
        "initialized_project": {"neuroloom_backend": True, "knowledge_id_scheme": 2},
    }
    for name, manifest in kinds.items():
        d = _decide({"manifest": manifest, "observed": _obs()})
        assert d["case"] == 2 and d["reason"] == name.split(" ")[0]
        for text in (d["message"], d["recovery"]):
            assert "/sdlc-migrate" not in text and "/sdlc-port" not in text, name


def test_an_unfinished_initialize_points_to_initializes_own_recovery() -> None:
    for manifest in ({"adapter_names_plugin": True}, {"knowledge_seed_in_progress": True}):
        d = _decide({"manifest": manifest, "observed": _obs()})
        assert "references/adapter-lifecycle.md" in d["recovery"]
        assert "Halts and their recoveries" in d["recovery"]
        assert "do not port" in d["recovery"].lower() or "not port" in d["recovery"].lower()


def test_a_pre_0_7_0_initialize_says_to_neither_port_nor_migrate() -> None:
    d = _decide({"manifest": {"neuroloom_backend": True}, "observed": _obs()})
    assert d["reason"] == "pre_0_7_0_initialize"
    assert "conversion" in d["recovery"] and "does not" in d["recovery"]
    assert "port" in d["recovery"] and "migrate" in d["recovery"]


def test_a_finished_initialize_has_no_file_mode_install_to_port() -> None:
    d = _decide({"manifest": {"neuroloom_backend": True, "knowledge_id_scheme": 2}, "observed": _obs()})
    assert d["reason"] == "initialized_project"
    assert "no file-mode install to port" in (d["message"] + d["recovery"])


def test_a_report_without_a_seed_version_is_refused_with_its_own_reason() -> None:
    d = _decide({"manifest": _ported(knowledge_seed_version=None),
                 "observed": _obs(sentinel=True, sentinel_label="v2.4.1")})
    assert (d["case"], d["action"], d["reason"]) == (3, "stop", "no_seed_version")
    assert d["message"] == (
        "the manifest records no knowledge_seed_version, so the sentinel can't be checked "
        "against it")
    assert "moved" not in d["message"]
    assert d["recovery"] == (
        "re-port is refused; a port that finished always records it, so the manifest was edited")
    # Also when the manifest names no version of its own.
    d2 = _decide({"manifest": _ported(knowledge_seed_version=None, source_version=None),
                  "observed": _obs(sentinel=True, sentinel_label="v2.4.1")})
    assert d2["reason"] == "no_seed_version"


def test_case_4_still_lists_its_three_possibilities() -> None:
    msg = _decide({"manifest": {}, "observed": _obs(sentinel=True)})["message"]
    assert "before 0.7.0" in msg and "another project" in msg and "stopped port" in msg


def test_label_matches_is_false_when_the_label_is_the_fallback() -> None:
    row = _decide({"manifest": {"install_date": "x"},
                   "observed": _obs(sentinel=True, sentinel_label="v2.12.2",
                                    current_sdlc_version="v2.12.2")})
    assert row["case"] == 4 and row["label_matches"] is False
    own = _decide({"manifest": {"source_version": "v2.12.2"},
                   "observed": _obs(sentinel=True, sentinel_label="v2.12.2")})
    assert own["label_matches"] is True


def test_the_cli_reads_a_facts_file_and_prints_the_decision_as_json(tmp_path: Path) -> None:
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps({"manifest": _ported(), "observed": _obs(sentinel=True,
                                                                          sentinel_label="v2.4.1")}))
    r = subprocess.run([sys.executable, "-I", str(_SCRIPT), "--facts", str(facts)],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert set(out) == {"case", "action", "reason", "message", "recovery"}
    assert (out["case"], out["action"]) == (3, "ask")


def test_the_cli_exits_2_on_unreadable_facts(tmp_path: Path) -> None:
    r = subprocess.run([sys.executable, "-I", str(_SCRIPT), "--facts", str(tmp_path / "nope.json")],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 2 and "Traceback" not in r.stderr


@pytest.mark.parametrize(("key", "value"), [
    ("port_in_progress", "false"), ("port_in_progress", "true"), ("port_in_progress", 1),
    ("port_in_progress", None), ("neuroloom_backend", "false"), ("neuroloom_backend", 0),
    ("knowledge_seed_in_progress", "true"), ("knowledge_seed_in_progress", []),
])
def test_manifest_booleans_must_be_json_booleans(tmp_path: Path, key: str, value: Any) -> None:
    facts = {"manifest": {key: value, "workspace_id": "W_A"}, "observed": _obs()}
    r = _cli_facts(tmp_path, facts)
    assert r.returncode == 2 and r.stdout == "" and key in r.stderr
    assert "Traceback" not in r.stderr
    with pytest.raises(ValueError, match=key):
        _decide(facts)


def test_a_stringly_false_cannot_authorise_continue_fresh() -> None:
    with pytest.raises(ValueError, match="port_in_progress"):
        _decide({"manifest": {"port_in_progress": "false", "workspace_id": "W_A"},
                 "observed": _obs(sdlc_rows=True)})


def test_real_booleans_and_absent_keys_are_accepted() -> None:
    for manifest in ({}, {"port_in_progress": False}, {"neuroloom_backend": False},
                     {"knowledge_seed_in_progress": False, "port_in_progress": True,
                      "workspace_id": "W_A"}):
        assert "case" in _decide({"manifest": manifest, "observed": _obs()})


def test_an_incomplete_port_record_says_the_manifest_was_edited() -> None:
    d = _decide({"manifest": {k: v for k, v in _ported().items() if k != "neuroloom_backend"},
                 "observed": _obs(sentinel=True, sentinel_label="v2.4.1")})
    assert d["recovery"].startswith("the manifest was edited; if this project was ported")
    assert "ported_at" in d["message"] and "neuroloom_backend" in d["message"]


def test_case_4_carries_the_workspace_id_and_label_matches_in_its_text() -> None:
    for label, expected in (("v2.4.1", "true"), ("v2.12.2", "false")):
        d = _decide({"manifest": {"source_version": "v2.4.1"},
                     "observed": _obs(workspace_id="W_XYZ", sentinel=True, sentinel_label=label)})
        text = d["message"] + " " + d["recovery"]
        assert "W_XYZ" in text and f"label_matches={expected}" in text
        assert d["label_matches"] is (expected == "true")
        assert "/sdlc-port" not in text
