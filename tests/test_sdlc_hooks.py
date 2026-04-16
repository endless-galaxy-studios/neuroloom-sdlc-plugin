"""
pytest test suite for neuroloom-sdlc-plugin Python hooks.

Replaces tests/test_hooks.sh with function-level unit tests that patch all
network interactions. No real HTTP calls are made.
"""

import io
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Import path setup — both plugin roots must be importable.
# ---------------------------------------------------------------------------

_SDLC_ROOT = Path(__file__).resolve().parent.parent
_BASE_ROOT = _SDLC_ROOT.parent / "neuroloom-claude-plugin"
sys.path.insert(0, str(_SDLC_ROOT))
sys.path.insert(0, str(_BASE_ROOT))

# ---------------------------------------------------------------------------
# Suite 1: PostToolUse path matching
# ---------------------------------------------------------------------------

_PATH_RE = re.compile(r"docs/current_work/.*\.md$")


class TestPostToolUsePathMatching:
    def test_spec_file_matches(self) -> None:
        assert _PATH_RE.search("docs/current_work/specs/d17_test_spec.md")

    def test_plan_file_matches(self) -> None:
        assert _PATH_RE.search("docs/current_work/planning/d17_test_plan.md")

    def test_result_file_matches(self) -> None:
        assert _PATH_RE.search("docs/current_work/results/d17_test_result.md")

    def test_chronicle_does_not_match(self) -> None:
        assert not _PATH_RE.search("docs/chronicle/d5_graph_api_COMPLETE.md")

    def test_source_file_does_not_match(self) -> None:
        assert not _PATH_RE.search("api/neuroloom_api/routers/sessions.py")

    def test_yaml_extension_does_not_match(self) -> None:
        assert not _PATH_RE.search("docs/current_work/specs/d17_test_spec.yaml")

    def test_index_md_does_not_match(self) -> None:
        assert not _PATH_RE.search("docs/_index.md")

    def test_absolute_path_spec_matches(self) -> None:
        assert _PATH_RE.search(
            "/home/user/projects/neuroloom/docs/current_work/d107_foo_spec.md"
        )

    def test_absolute_path_chronicle_does_not_match(self) -> None:
        assert not _PATH_RE.search(
            "/home/user/projects/neuroloom/docs/chronicle/d100_bar_COMPLETE.md"
        )

    def test_sdlc_lite_subdir_matches(self) -> None:
        assert _PATH_RE.search("docs/current_work/sdlc-lite/d107_foo_plan.md")


# ---------------------------------------------------------------------------
# Suite 2: PostToolUse deliverable ID extraction
# ---------------------------------------------------------------------------

_ID_RE = re.compile(r"^d(\d+[a-z]?)_")


def _extract_id(filename: str) -> str:
    m = _ID_RE.match(filename)
    return m.group(1) if m else ""


class TestPostToolUseDeliverableIdExtraction:
    def test_single_digit_id(self) -> None:
        assert _extract_id("d5_graph_api_spec.md") == "5"

    def test_two_digit_id(self) -> None:
        assert _extract_id("d17_neuroloom_sdlc_plugin_spec.md") == "17"

    def test_id_with_letter_suffix(self) -> None:
        assert _extract_id("d1a_subdeliverable_plan.md") == "1a"

    def test_readme_no_match(self) -> None:
        assert _extract_id("README.md") == ""

    def test_underscore_prefix_no_match(self) -> None:
        assert _extract_id("_index.md") == ""


# ---------------------------------------------------------------------------
# Suite 3: PostToolUse doc type derivation
# ---------------------------------------------------------------------------

def _derive_doc_type(filename: str) -> str:
    if filename.endswith("_spec.md"):
        return "spec"
    elif filename.endswith("_plan.md"):
        return "plan"
    elif filename.endswith("_result.md"):
        return "result"
    elif filename.endswith("_COMPLETE.md"):
        return "chronicle"
    return ""


class TestPostToolUseDocType:
    def test_spec_suffix(self) -> None:
        assert _derive_doc_type("d17_foo_spec.md") == "spec"

    def test_plan_suffix(self) -> None:
        assert _derive_doc_type("d17_foo_plan.md") == "plan"

    def test_result_suffix(self) -> None:
        assert _derive_doc_type("d17_foo_result.md") == "result"

    def test_complete_suffix_is_chronicle(self) -> None:
        assert _derive_doc_type("d5_bar_COMPLETE.md") == "chronicle"

    def test_unknown_suffix_is_empty(self) -> None:
        assert _derive_doc_type("d17_something_notes.md") == ""

    def test_blocked_suffix_is_empty(self) -> None:
        assert _derive_doc_type("d17_test_BLOCKED.md") == ""


# ---------------------------------------------------------------------------
# Suite 4: PostToolUse tag list construction
# ---------------------------------------------------------------------------

def _build_tags(deliverable_id: str, doc_type: str) -> list[str]:
    tags: list[str] = []
    if deliverable_id:
        tags.append(f"sdlc:deliverable:{deliverable_id}")
    if doc_type:
        tags.append(f"sdlc:doc:{doc_type}")
    return tags


class TestPostToolUseTagConstruction:
    def test_id_and_type(self) -> None:
        assert _build_tags("42", "spec") == ["sdlc:deliverable:42", "sdlc:doc:spec"]

    def test_id_without_type(self) -> None:
        assert _build_tags("42", "") == ["sdlc:deliverable:42"]

    def test_type_without_id(self) -> None:
        assert _build_tags("", "plan") == ["sdlc:doc:plan"]

    def test_neither(self) -> None:
        assert _build_tags("", "") == []


# ---------------------------------------------------------------------------
# Suite 5: PostToolUse payload construction
# ---------------------------------------------------------------------------

class TestPostToolUsePayloadConstruction:
    def test_payload_keys(self) -> None:
        payload = {
            "title": "d42_foo_spec.md",
            "content": "# Spec\nSome content.",
            "source_type": "sdlc_deliverable",
            "source_path": "docs/current_work/specs/d42_foo_spec.md",
            "tags": ["sdlc:deliverable:42", "sdlc:doc:spec"],
        }
        assert "title" in payload
        assert "content" in payload
        assert "source_type" in payload
        assert "source_path" in payload
        assert "tags" in payload

    def test_source_type_value(self) -> None:
        payload = {
            "title": "d42_foo_spec.md",
            "content": "content",
            "source_type": "sdlc_deliverable",
            "source_path": "docs/current_work/specs/d42_foo_spec.md",
            "tags": ["sdlc:deliverable:42"],
        }
        assert payload["source_type"] == "sdlc_deliverable"

    def test_tags_content(self) -> None:
        tags = ["sdlc:deliverable:42", "sdlc:doc:spec"]
        assert "sdlc:deliverable:42" in tags
        assert "sdlc:doc:spec" in tags

    def test_json_round_trip(self) -> None:
        payload = {
            "title": "d42_foo_spec.md",
            "content": "# Spec content",
            "source_type": "sdlc_deliverable",
            "source_path": "docs/current_work/specs/d42_foo_spec.md",
            "tags": ["sdlc:deliverable:42", "sdlc:doc:spec"],
        }
        serialised = json.dumps(payload)
        restored = json.loads(serialised)
        assert restored == payload


# ---------------------------------------------------------------------------
# Suite 6: PostToolUse SQLite buffer behaviour
# ---------------------------------------------------------------------------

class TestPostToolUseSqliteBuffer:
    def _make_db(self, tmp_path: Path) -> Path:
        """Create a temporary SQLite state DB with the event_buffer table."""
        db_path = tmp_path / ".neuroloom.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS event_buffer (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        conn.commit()
        conn.close()
        return db_path

    def _make_test_config(self, db_path: Path) -> "pyhooks.config.Config":  # type: ignore[name-defined]
        import pyhooks.config

        return pyhooks.config.Config(
            api_key="test-key",
            api_base="http://localhost:8000",
            state_db_path=db_path,
        )

    def _setup_doc_file(self, tmp_path: Path) -> tuple[str, str]:
        """Create a matching deliverable file and return (file_path, stdin_json)."""
        doc_dir = tmp_path / "docs" / "current_work" / "specs"
        doc_dir.mkdir(parents=True)
        doc_file = doc_dir / "d42_foo_spec.md"
        doc_file.write_text("# Test spec content")
        file_path = str(doc_file)
        stdin_data = json.dumps({"tool_input": {"file_path": file_path}})
        return file_path, stdin_data

    def test_buffer_row_created_on_api_failure(self, tmp_path: Path) -> None:
        import sdlc_pyhooks.post_tool_use as ptu

        db_path = self._make_db(tmp_path)
        test_config = self._make_test_config(db_path)
        _, stdin_data = self._setup_doc_file(tmp_path)

        with (
            patch("pyhooks.config.load", return_value=test_config),
            patch("pyhooks.http.post_json", return_value=(500, b"error")),
            patch(
                "sdlc_pyhooks.post_tool_use.open_db",
                return_value=sqlite3.connect(str(db_path), check_same_thread=False),
            ),
            patch("sys.stdin", io.StringIO(stdin_data)),
        ):
            ptu.main()
            # Give the background thread time to complete while patches are active
            time.sleep(0.3)

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT payload FROM event_buffer").fetchall()
        conn.close()
        assert len(rows) >= 1
        payload = json.loads(rows[0][0])
        assert payload["source_type"] == "sdlc_deliverable"

    def test_buffer_row_contains_correct_payload_keys(self, tmp_path: Path) -> None:
        import sdlc_pyhooks.post_tool_use as ptu

        db_path = self._make_db(tmp_path)
        test_config = self._make_test_config(db_path)
        _, stdin_data = self._setup_doc_file(tmp_path)

        with (
            patch("pyhooks.config.load", return_value=test_config),
            patch("pyhooks.http.post_json", return_value=(500, b"error")),
            patch(
                "sdlc_pyhooks.post_tool_use.open_db",
                return_value=sqlite3.connect(str(db_path), check_same_thread=False),
            ),
            patch("sys.stdin", io.StringIO(stdin_data)),
        ):
            ptu.main()
            time.sleep(0.3)

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT payload FROM event_buffer").fetchall()
        conn.close()
        assert len(rows) >= 1
        payload = json.loads(rows[0][0])
        for key in ("title", "content", "source_type", "source_path", "tags"):
            assert key in payload, f"Missing key in buffered payload: {key}"

    def test_no_buffer_row_on_success(self, tmp_path: Path) -> None:
        import sdlc_pyhooks.post_tool_use as ptu

        db_path = self._make_db(tmp_path)
        test_config = self._make_test_config(db_path)
        _, stdin_data = self._setup_doc_file(tmp_path)

        with (
            patch("pyhooks.config.load", return_value=test_config),
            patch("pyhooks.http.post_json", return_value=(200, b"ok")),
            patch(
                "sdlc_pyhooks.post_tool_use.open_db",
                return_value=sqlite3.connect(str(db_path), check_same_thread=False),
            ),
            patch("sys.stdin", io.StringIO(stdin_data)),
        ):
            ptu.main()
            time.sleep(0.3)

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT payload FROM event_buffer").fetchall()
        conn.close()
        assert len(rows) == 0

    def test_buffer_row_created_on_network_failure(self, tmp_path: Path) -> None:
        import sdlc_pyhooks.post_tool_use as ptu

        db_path = self._make_db(tmp_path)
        test_config = self._make_test_config(db_path)
        _, stdin_data = self._setup_doc_file(tmp_path)

        with (
            patch("pyhooks.config.load", return_value=test_config),
            patch("pyhooks.http.post_json", return_value=None),
            patch(
                "sdlc_pyhooks.post_tool_use.open_db",
                return_value=sqlite3.connect(str(db_path), check_same_thread=False),
            ),
            patch("sys.stdin", io.StringIO(stdin_data)),
        ):
            ptu.main()
            time.sleep(0.3)

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT payload FROM event_buffer").fetchall()
        conn.close()
        assert len(rows) >= 1


# ---------------------------------------------------------------------------
# Suite 7: SessionStart sentinel absent output
# ---------------------------------------------------------------------------

def _make_config() -> "pyhooks.config.Config":  # type: ignore[name-defined]
    import pyhooks.config

    return pyhooks.config.Config(
        api_key="test-key",
        api_base="http://localhost:8000",
        state_db_path=Path("/tmp/test.db"),
    )


class TestSessionStartSentinelAbsent:
    def test_empty_results_prints_init_prompt(self, capsys: "pytest.CaptureFixture[str]") -> None:  # type: ignore[name-defined]
        import sdlc_pyhooks.session_start as ss

        with (
            patch("pyhooks.config.load", return_value=_make_config()),
            patch.object(
                ss,
                "_get_json",
                return_value=(200, json.dumps({"version": "v1.0.0"}).encode()),
            ),
            patch(
                "pyhooks.http.post_json",
                return_value=(200, json.dumps({"results": []}).encode()),
            ),
        ):
            ss.main()

        captured = capsys.readouterr()
        assert "Run /sdlc-initialize" in captured.out

    def test_missing_results_key_prints_init_prompt(self, capsys: "pytest.CaptureFixture[str]") -> None:  # type: ignore[name-defined]
        import sdlc_pyhooks.session_start as ss

        with (
            patch("pyhooks.config.load", return_value=_make_config()),
            patch.object(
                ss,
                "_get_json",
                return_value=(200, json.dumps({"version": "v1.0.0"}).encode()),
            ),
            patch(
                "pyhooks.http.post_json",
                return_value=(200, json.dumps({}).encode()),
            ),
        ):
            ss.main()

        captured = capsys.readouterr()
        assert "Run /sdlc-initialize" in captured.out


# ---------------------------------------------------------------------------
# Suite 8: SessionStart version comparison output
# ---------------------------------------------------------------------------

class TestSessionStartVersionComparison:
    def _run_with_versions(
        self,
        latest: str,
        sentinel_tags: list[str],
        capsys: "pytest.CaptureFixture[str]",  # type: ignore[name-defined]
    ) -> str:
        import sdlc_pyhooks.session_start as ss

        sentinel_results = [{"tags": sentinel_tags}]
        with (
            patch("pyhooks.config.load", return_value=_make_config()),
            patch.object(
                ss,
                "_get_json",
                return_value=(200, json.dumps({"version": latest}).encode()),
            ),
            patch(
                "pyhooks.http.post_json",
                return_value=(
                    200,
                    json.dumps({"results": sentinel_results}).encode(),
                ),
            ),
        ):
            ss.main()

        return capsys.readouterr().out

    def test_newer_version_prints_update_notice(
        self, capsys: "pytest.CaptureFixture[str]"  # type: ignore[name-defined]
    ) -> None:
        out = self._run_with_versions(
            "v1.1.0",
            ["sdlc:sentinel", "sdlc:seed-version:v1.0.0"],
            capsys,
        )
        assert "update available" in out
        assert "v1.0.0 -> v1.1.0" in out

    def test_same_version_produces_no_output(
        self, capsys: "pytest.CaptureFixture[str]"  # type: ignore[name-defined]
    ) -> None:
        out = self._run_with_versions(
            "v1.1.0",
            ["sdlc:sentinel", "sdlc:seed-version:v1.1.0"],
            capsys,
        )
        assert out == ""

    def test_missing_seed_version_tag_produces_no_output(
        self, capsys: "pytest.CaptureFixture[str]"  # type: ignore[name-defined]
    ) -> None:
        # No sdlc:seed-version: tag → workspace_version stays ""
        out = self._run_with_versions(
            "v1.1.0",
            ["sdlc:sentinel"],
            capsys,
        )
        assert out == ""


# ---------------------------------------------------------------------------
# Suite 9: SessionStart _get_json network failure
# ---------------------------------------------------------------------------

class TestGetJsonNetworkFailure:
    def test_url_error_returns_none(self) -> None:
        import urllib.error

        from sdlc_pyhooks.session_start import _get_json

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("test"),
        ):
            result = _get_json("http://localhost/test", {}, timeout=5.0)

        assert result is None


# ---------------------------------------------------------------------------
# Suite 10: SessionStart _get_json HTTP error
# ---------------------------------------------------------------------------

class TestGetJsonHttpError:
    def test_http_error_returns_status_and_body(self) -> None:
        import urllib.error

        from sdlc_pyhooks.session_start import _get_json

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                url="",
                code=403,
                msg="",
                hdrs=None,  # type: ignore[arg-type]
                fp=io.BytesIO(b"forbidden"),
            ),
        ):
            result = _get_json("http://localhost/test", {}, timeout=5.0)

        assert result is not None
        status, body = result
        assert status == 403
        assert body == b"forbidden"


# ---------------------------------------------------------------------------
# Suite 11: SessionStart missing sdlc:seed-version: tag
# ---------------------------------------------------------------------------

class TestSessionStartMissingSeedVersionTag:
    def test_workspace_version_is_empty_when_tag_absent(
        self, capsys: "pytest.CaptureFixture[str]"  # type: ignore[name-defined]
    ) -> None:
        import sdlc_pyhooks.session_start as ss

        sentinel_tags = ["sdlc:sentinel", "sdlc:other-tag"]
        sentinel_results = [{"tags": sentinel_tags}]

        with (
            patch("pyhooks.config.load", return_value=_make_config()),
            patch.object(
                ss,
                "_get_json",
                return_value=(200, json.dumps({"version": "v1.1.0"}).encode()),
            ),
            patch(
                "pyhooks.http.post_json",
                return_value=(
                    200,
                    json.dumps({"results": sentinel_results}).encode(),
                ),
            ),
        ):
            ss.main()

        captured = capsys.readouterr()
        # workspace_version="" → no update notice, no init prompt
        assert captured.out == ""
