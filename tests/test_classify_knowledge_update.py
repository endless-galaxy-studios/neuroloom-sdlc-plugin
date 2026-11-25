"""Tests for skills/sdlc-port/scripts/classify_knowledge_update.py.

The classifier decides, per id in a ``.delta.json``, whether a ``knowledge-update``
may overwrite what the workspace holds, and which probe entry the server will
answer ``unchanged`` for. The script runs as a subprocess, the way the handler
runs it.

The server's rule (``DocumentIngestionService.seed_workspace``): a row tagged
``sdlc:project-specific`` is never modified; otherwise the entry is ``unchanged``
exactly when sha256(entry content) equals sha256(stored narrative). The title is
not part of that hash, and nothing is normalised before hashing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_SCRIPT = (
    Path(__file__).parent.parent / "skills" / "sdlc-port" / "scripts" / "classify_knowledge_update.py"
)
PS = "sdlc:project-specific"


def _row(content: str, *tags: str, title: str = "t") -> dict[str, Any]:
    return {"title": title, "content": content, "tags": list(tags)}


def _delta(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "new": [],
        "new_content": {},
        "changed": [],
        "removed": [],
        "unchanged_count": 0,
        "probe_ids": [],
        "noop_entry": None,
        "probe_entries": [],
    }
    base.update(overrides)
    return base


def _changed(entry_id: str, baseline: str, target: str) -> dict[str, str]:
    return {"id": entry_id, "baseline_content": baseline, "target_content": target}


def _entry(entry_id: str, content: str) -> dict[str, Any]:
    return {"title": "t", "content": content, "knowledge_id": entry_id, "tags": ["sdlc:knowledge"]}


def _run(
    tmp_path: Path, delta: dict[str, Any], workspace: dict[str, Any]
) -> tuple[subprocess.CompletedProcess[str], Path]:
    d = tmp_path / "delta.json"
    w = tmp_path / "workspace.json"
    out = tmp_path / "out"
    d.write_text(json.dumps(delta), encoding="utf-8")
    w.write_text(json.dumps(workspace), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, "-I", str(_SCRIPT), "--delta", str(d), "--workspace", str(w),
         "--output-dir", str(out)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    return r, out


def _report(out: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((out / "report.json").read_text(encoding="utf-8"))
    return data


class TestChangedIds:
    def test_workspace_equal_to_baseline_is_sent(self, tmp_path: Path) -> None:
        r, out = _run(tmp_path, _delta(changed=[_changed("c", "old", "new")]), {"c": _row("old")})
        assert r.returncode == 0, r.stderr
        assert _report(out)["send"] == ["c"]
        assert (out / "send_ids.txt").read_text() == "c\n"

    def test_workspace_equal_to_target_is_already_current(self, tmp_path: Path) -> None:
        _, out = _run(tmp_path, _delta(changed=[_changed("c", "old", "new")]), {"c": _row("new")})
        assert _report(out)["already_current"] == ["c"]
        assert (out / "send_ids.txt").read_text() == ""

    def test_workspace_differing_from_both_is_a_conflict_with_all_three_texts(
        self, tmp_path: Path
    ) -> None:
        _, out = _run(
            tmp_path, _delta(changed=[_changed("c", "old", "new")]), {"c": _row("project edit")}
        )
        assert _report(out)["conflict"] == [
            {"id": "c", "baseline": "old", "target": "new", "workspace": "project edit"}
        ]
        assert (out / "send_ids.txt").read_text() == ""

    def test_changed_id_absent_from_the_workspace_was_removed_by_the_project(
        self, tmp_path: Path
    ) -> None:
        _, out = _run(tmp_path, _delta(changed=[_changed("c", "old", "new")]), {"c": None})
        assert _report(out)["removed_by_project"] == ["c"]
        assert (out / "send_ids.txt").read_text() == ""


class TestTitles:
    """A seed upsert replaces title and narrative together, so a project's title edit is a conflict."""

    def _changed_titled(self, base_title: str = "Old title", target_title: str = "Old title") -> dict[str, str]:
        return {**_changed("c", "old", "new"), "baseline_title": base_title, "target_title": target_title}

    def test_a_project_title_edit_on_a_baseline_body_is_a_conflict_not_a_send(self, tmp_path: Path) -> None:
        r, out = _run(tmp_path, _delta(changed=[self._changed_titled()]), {"c": _row("old", title="Project title")})
        assert r.returncode == 0, r.stderr
        report = _report(out)
        assert report["send"] == []
        assert report["conflict"] == [{"id": "c", "baseline": "old", "target": "new", "workspace": "old",
                                       "baseline_title": "Old title", "target_title": "Old title",
                                       "workspace_title": "Project title"}]
        assert (out / "send_ids.txt").read_text() == ""

    def test_a_row_with_the_baseline_or_target_title_is_still_sent(self, tmp_path: Path) -> None:
        for title in ("Old title", "New title"):
            sub = tmp_path / title.replace(" ", "_")
            sub.mkdir()
            _, out = _run(sub, _delta(changed=[self._changed_titled(target_title="New title")]),
                          {"c": _row("old", title=title)})
            assert _report(out)["send"] == ["c"], title

    def test_a_project_specific_row_with_its_own_title_is_protected(self, tmp_path: Path) -> None:
        _, out = _run(tmp_path, _delta(changed=[self._changed_titled()]), {"c": _row("old", PS, title="Mine")})
        report = _report(out)
        assert report["protected"] == ["c"] and report["conflict"] == []

    def test_target_text_under_the_projects_own_title_is_already_current(self, tmp_path: Path) -> None:
        _, out = _run(tmp_path, _delta(changed=[self._changed_titled()]), {"c": _row("new", title="Mine")})
        assert _report(out)["already_current"] == ["c"]

    def test_a_delta_with_only_one_title_keeps_the_body_only_rule(self, tmp_path: Path) -> None:
        item = {**_changed("c", "old", "new"), "baseline_title": "Old title"}
        _, out = _run(tmp_path, _delta(changed=[item]), {"c": _row("old", title="Mine")})
        assert _report(out)["send"] == ["c"]

    def test_titles_compare_after_normalising_line_endings_and_trailing_space(self, tmp_path: Path) -> None:
        _, out = _run(tmp_path, _delta(changed=[self._changed_titled()]), {"c": _row("old", title="Old title \r\n")})
        assert _report(out)["send"] == ["c"]

    def test_a_row_without_a_string_title_exits_2(self, tmp_path: Path) -> None:
        r, _ = _run(tmp_path, _delta(changed=[self._changed_titled()]),
                    {"c": {"content": "old", "tags": []}})
        assert r.returncode == 2

    def test_a_delta_without_titles_keeps_the_body_only_rule(self, tmp_path: Path) -> None:
        _, out = _run(tmp_path, _delta(changed=[_changed("c", "old", "new")]), {"c": _row("old", title="Anything")})
        assert _report(out)["send"] == ["c"]


class TestNewIds:
    def test_a_new_id_absent_from_the_workspace_is_sent(self, tmp_path: Path) -> None:
        _, out = _run(tmp_path, _delta(new=["n"], new_content={"n": "text"}), {"n": None})
        assert _report(out)["send"] == ["n"]

    def test_a_new_id_the_workspace_holds_with_the_target_text_is_already_current(
        self, tmp_path: Path
    ) -> None:
        _, out = _run(tmp_path, _delta(new=["n"], new_content={"n": "text"}), {"n": _row("text")})
        assert _report(out)["already_current"] == ["n"]

    def test_a_new_id_the_workspace_holds_with_other_text_is_a_conflict(
        self, tmp_path: Path
    ) -> None:
        _, out = _run(tmp_path, _delta(new=["n"], new_content={"n": "text"}), {"n": _row("mine")})
        assert _report(out)["conflict"] == [
            {"id": "n", "baseline": None, "target": "text", "workspace": "mine"}
        ]


class TestProtectedRows:
    def test_a_send_candidate_with_the_project_specific_tag_is_protected(
        self, tmp_path: Path
    ) -> None:
        delta = _delta(changed=[_changed("c", "old", "new")])
        _, out = _run(tmp_path, delta, {"c": _row("old", "sdlc:knowledge", PS)})
        rep = _report(out)
        assert rep["protected"] == ["c"] and rep["send"] == []
        assert (out / "send_ids.txt").read_text() == ""

    def test_an_already_current_candidate_with_the_tag_is_protected(self, tmp_path: Path) -> None:
        delta = _delta(new=["n"], new_content={"n": "text"}, changed=[_changed("c", "o", "t")])
        _, out = _run(tmp_path, delta, {"n": _row("text", PS), "c": _row("t", PS)})
        rep = _report(out)
        assert rep["protected"] == ["n", "c"] and rep["already_current"] == []

    def test_a_conflict_stays_a_conflict_even_when_the_row_is_protected(
        self, tmp_path: Path
    ) -> None:
        _, out = _run(tmp_path, _delta(changed=[_changed("c", "o", "t")]), {"c": _row("mine", PS)})
        rep = _report(out)
        assert [c["id"] for c in rep["conflict"]] == ["c"] and rep["protected"] == []

    def test_an_untagged_row_is_not_protected(self, tmp_path: Path) -> None:
        _, out = _run(tmp_path, _delta(changed=[_changed("c", "o", "t")]), {"c": _row("o", "other")})
        assert _report(out)["send"] == ["c"] and _report(out)["protected"] == []


class TestNoopIds:
    def _probe_delta(self, *entries: dict[str, Any]) -> dict[str, Any]:
        return _delta(noop_entry=entries[0], probe_ids=[e["knowledge_id"] for e in entries[1:]],
                      probe_entries=list(entries))

    def test_the_first_byte_identical_entry_is_chosen(self, tmp_path: Path) -> None:
        delta = self._probe_delta(_entry("n1", "alpha"), _entry("p1", "beta"), _entry("p2", "gamma"))
        ws = {"n1": _row("alpha  "), "p1": _row("beta"), "p2": _row("gamma")}
        _, out = _run(tmp_path, delta, ws)
        assert (out / "noop_ids.txt").read_text() == "p1\n"

    def test_collapsed_whitespace_is_not_enough(self, tmp_path: Path) -> None:
        delta = self._probe_delta(_entry("n1", "a b"))
        _, out = _run(tmp_path, delta, {"n1": _row("a  b")})
        assert (out / "noop_ids.txt").read_text() == ""

    def test_the_title_is_not_part_of_the_match(self, tmp_path: Path) -> None:
        delta = self._probe_delta(_entry("n1", "same"))
        _, out = _run(tmp_path, delta, {"n1": _row("same", title="a different title")})
        assert (out / "noop_ids.txt").read_text() == "n1\n"

    def test_a_row_the_workspace_lacks_is_skipped(self, tmp_path: Path) -> None:
        delta = self._probe_delta(_entry("n1", "x"), _entry("p1", "y"))
        _, out = _run(tmp_path, delta, {"n1": None, "p1": _row("y")})
        assert (out / "noop_ids.txt").read_text() == "p1\n"

    def test_the_file_is_empty_when_nothing_matches_or_there_are_no_probes(
        self, tmp_path: Path
    ) -> None:
        delta = self._probe_delta(_entry("n1", "x"))
        _, out = _run(tmp_path, delta, {"n1": _row("other")})
        assert (out / "noop_ids.txt").read_text() == ""
        (tmp_path / "second").mkdir()
        _, out2 = _run(tmp_path / "second", _delta(), {})
        assert (out2 / "noop_ids.txt").read_text() == ""

    def test_a_candidate_missing_from_the_workspace_file_is_skipped(self, tmp_path: Path) -> None:
        delta = self._probe_delta(_entry("n1", "x"), _entry("p1", "y"))
        r, out = _run(tmp_path, delta, {"p1": _row("y")})
        assert r.returncode == 0, r.stderr
        assert (out / "noop_ids.txt").read_text() == "p1\n"
        (tmp_path / "none").mkdir()
        r, out = _run(tmp_path / "none", delta, {})
        assert r.returncode == 0 and (out / "noop_ids.txt").read_text() == ""

    def test_only_the_first_eleven_of_fifty_looked_up_and_the_first_edited(
        self, tmp_path: Path
    ) -> None:
        entries = [_entry(f"p{i:02d}", f"text {i}") for i in range(50)]
        delta = _delta(noop_entry=entries[0], probe_entries=entries)
        looked_up = {e["knowledge_id"]: _row(e["content"]) for e in entries[:11]}
        looked_up["p00"] = _row("edited by the project")
        r, out = _run(tmp_path, delta, looked_up)
        assert r.returncode == 0, r.stderr
        assert (out / "noop_ids.txt").read_text() == "p01\n"
        for k in looked_up:
            looked_up[k] = _row("edited " + k)
        (tmp_path / "again").mkdir()
        r, out = _run(tmp_path / "again", delta, looked_up)
        assert r.returncode == 0 and (out / "noop_ids.txt").read_text() == ""

    def test_a_present_but_malformed_candidate_row_still_exits_2(self, tmp_path: Path) -> None:
        delta = self._probe_delta(_entry("n1", "x"))
        r, out = _run(tmp_path, delta, {"n1": "not an object"})
        assert r.returncode == 2 and "n1" in r.stderr and not out.exists()


class TestOutputsAndGuards:
    def test_every_list_is_present_and_send_ids_keeps_delta_order(self, tmp_path: Path) -> None:
        delta = _delta(new=["n1", "n2"], new_content={"n1": "a", "n2": "b"},
                       changed=[_changed("c1", "x", "y")])
        r, out = _run(tmp_path, delta, {"n1": None, "n2": None, "c1": _row("x")})
        rep = _report(out)
        assert set(rep) == {"send", "already_current", "conflict", "removed_by_project", "protected"}
        assert (out / "send_ids.txt").read_text().split() == ["n1", "n2", "c1"]
        assert r.stdout.split() == [
            str(out / "send_ids.txt"), str(out / "noop_ids.txt"), str(out / "report.json"),
        ]

    def test_a_workspace_missing_an_id_exits_2_and_writes_nothing(self, tmp_path: Path) -> None:
        r, out = _run(tmp_path, _delta(changed=[_changed("c", "o", "n")]), {})
        assert r.returncode == 2 and "c" in r.stderr
        assert not out.exists()

    def test_a_new_id_without_target_text_exits_2(self, tmp_path: Path) -> None:
        r, _ = _run(tmp_path, _delta(new=["n"]), {"n": None})
        assert r.returncode == 2 and "new_content" in r.stderr

    def test_malformed_workspace_values_exit_2_without_a_traceback(self, tmp_path: Path) -> None:
        delta = _delta(changed=[_changed("c", "o", "n")])
        for bad in ("a string", 3, ["x"], {"title": "t", "tags": []},
                    {"content": 5, "tags": []}, {"content": "x", "tags": "not-a-list"}):
            r, out = _run(tmp_path, delta, {"c": bad})
            assert r.returncode == 2, bad
            assert "Traceback" not in r.stderr and "c" in r.stderr
            assert not out.exists()

    def test_unreadable_inputs_exit_2(self, tmp_path: Path) -> None:
        r = subprocess.run(
            [sys.executable, "-I", str(_SCRIPT), "--delta", str(tmp_path / "no.json"),
             "--workspace", str(tmp_path / "no2.json"), "--output-dir", str(tmp_path / "o")],
            capture_output=True, text=True, timeout=30, check=False,
        )
        assert r.returncode == 2 and "Traceback" not in r.stderr

    def test_an_empty_delta_writes_empty_outputs(self, tmp_path: Path) -> None:
        r, out = _run(tmp_path, _delta(), {})
        assert r.returncode == 0
        assert (out / "send_ids.txt").read_text() == ""
        assert _report(out) == {
            "send": [], "already_current": [], "conflict": [], "removed_by_project": [],
            "protected": [],
        }


# ===========================================================================
# Round 11: line-ending / trailing-whitespace normalisation, 50 candidates, replay
# ===========================================================================


class TestNormalisation:
    def test_crlf_and_the_final_newline_do_not_matter(self, tmp_path: Path) -> None:
        delta = _delta(changed=[_changed("a", "line one\nline two\n", "x"),
                                _changed("b", "o", "alpha\nbeta\n")])
        ws = {"a": _row("line one\r\nline two"), "b": _row("alpha\nbeta  \n\n")}
        _, out = _run(tmp_path, delta, ws)
        rep = _report(out)
        assert rep["send"] == ["a"] and rep["already_current"] == ["b"] and rep["conflict"] == []

    def test_a_narrative_missing_only_its_final_newline_is_not_a_conflict(
        self, tmp_path: Path
    ) -> None:
        delta = _delta(changed=[_changed("c", "text\n", "new text\n")])
        _, out = _run(tmp_path, delta, {"c": _row("text")})
        assert _report(out)["send"] == ["c"] and _report(out)["conflict"] == []

    def test_internal_whitespace_and_indentation_stay_significant(self, tmp_path: Path) -> None:
        delta = _delta(changed=[_changed("i", "- item\n  nested\n", "- item\n  nested v2\n"),
                                _changed("s", "one two", "other")])
        ws = {"i": _row("- item\n    nested\n"), "s": _row("one  two")}
        _, out = _run(tmp_path, delta, ws)
        assert sorted(c["id"] for c in _report(out)["conflict"]) == ["i", "s"]
        assert _report(out)["send"] == []


class TestFiftyCandidates:
    def test_the_first_byte_equal_of_fifty_is_chosen(self, tmp_path: Path) -> None:
        entries = [_entry(f"p{i:02d}", f"text {i}") for i in range(50)]
        delta = _delta(noop_entry=entries[0], probe_entries=entries)
        ws: dict[str, Any] = {e["knowledge_id"]: _row(e["content"] + " ") for e in entries}
        ws["p37"] = _row("text 37")
        ws["p41"] = _row("text 41")
        _, out = _run(tmp_path, delta, ws)
        assert (out / "noop_ids.txt").read_text() == "p37\n"


def _zsdlc(tmp_path: Path, tag: str) -> Path | None:
    import os
    import pwd

    home = pwd.getpwuid(os.getuid()).pw_dir
    env = {"PATH": os.environ.get("PATH", ""), "HOME": home}
    target = tmp_path / tag
    target.mkdir()
    archive = subprocess.run(
        ["git", "-C", str(Path(home) / "Projects" / "cc-sdlc"), "archive", tag, "knowledge", "disciplines"],
        capture_output=True, check=False, env=env,
    )
    if archive.returncode != 0:
        return None
    subprocess.run(["tar", "-x", "-C", str(target)], input=archive.stdout, check=True)
    return target


class TestReplayV2_4_1ToV2_12_3:
    def test_the_port_built_workspace_classifies_as_recorded(self, tmp_path: Path) -> None:
        # The real tree under the directory the suite runs from (the monorepo root), as the
        # extractor's real-tree tests find it; skipped elsewhere.
        project = Path.cwd() / "ops" / "sdlc"
        old, new = _zsdlc(tmp_path, "v2.4.1"), _zsdlc(tmp_path, "v2.12.3")
        if old is None or new is None or not (project / "knowledge").exists():
            import pytest

            pytest.skip("needs cc-sdlc v2.4.1 and v2.12.3 and the Neuroloom ops/sdlc tree")
        extractor = _SCRIPT.with_name("extract_sdlc_knowledge.py")
        base = [sys.executable, "-I", str(extractor)]
        delta_out = tmp_path / "d" / "seed.json"
        delta_out.parent.mkdir()
        r = subprocess.run(
            [*base, "--upstream", "--knowledge-dir", str(new / "knowledge"),
             "--disciplines-dir", str(new / "disciplines"),
             "--baseline-knowledge-dir", str(old / "knowledge"),
             "--baseline-disciplines-dir", str(old / "disciplines"), "--output", str(delta_out)],
            capture_output=True, text=True, check=False, cwd=tmp_path,
        )
        assert r.returncode == 0, r.stderr
        delta = json.loads(delta_out.with_name("seed.delta.json").read_text())
        port_out = tmp_path / "port.json"
        r = subprocess.run(
            [*base, "--knowledge-dir", str(project / "knowledge"),
             "--disciplines-dir", str(project / "disciplines"), "--output", str(port_out),
             "--max-per-file", "100000", "--max-bytes", "100000000", "--no-manifest"],
            capture_output=True, text=True, check=False, cwd=tmp_path,
        )
        assert r.returncode == 0, r.stderr
        held = {e["knowledge_id"]: {"title": e["title"], "content": e["content"], "tags": e["tags"]}
                for e in json.loads(port_out.read_text())["entries"]}
        wanted = [*delta["new"], *(c["id"] for c in delta["changed"]),
                  *(e["knowledge_id"] for e in delta["probe_entries"])]
        workspace = {i: held.get(i) for i in wanted}
        (tmp_path / "cls").mkdir()
        _, out = _run(tmp_path / "cls", delta, workspace)
        rep = _report(out)
        assert {k: len(v) for k, v in rep.items()} == {
            "send": 15, "already_current": 0, "conflict": 7, "removed_by_project": 3, "protected": 0,
        }
