"""Tests for skills/sdlc-port/scripts/extract_deliverable_docs.py extraction logic.

These tests exercise the pure extraction functions (_parse_frontmatter,
_extract_doc, _collect_all_docs) against both real docs/ files and synthetic
fixtures.  No API calls are made.

Test categories:
  - Integration: _collect_all_docs against the real docs/ tree
  - Unit: _parse_frontmatter (delimiter handling, YAML errors, edge cases)
  - Unit: _extract_doc (tags, source_type, source_path, knowledge_id, format)
  - Unit: _collect_all_docs with controlled directories
  - Subprocess: --dry-run CLI output format
  - Subprocess: --output FILE writes flat JSON array
  - Subprocess: stdout output produces flat JSON array
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Import the script module without executing main().
#
# The script lives at skills/sdlc-port/scripts/extract_deliverable_docs.py.
# We locate the plugin root relative to this test file's location
# (tests/ -> parent = plugin root) and load it with importlib.
# ---------------------------------------------------------------------------

_PLUGIN_ROOT = Path(__file__).parent.parent  # tests/ -> plugin root
_SCRIPT_PATH = (
    _PLUGIN_ROOT / "skills" / "sdlc-port" / "scripts" / "extract_deliverable_docs.py"
)

assert _SCRIPT_PATH.exists(), (
    f"Script not found at {_SCRIPT_PATH}. "
    "Tests must be run from the plugin repository root."
)

_spec = importlib.util.spec_from_file_location("extract_deliverable_docs", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
_script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_script)  # type: ignore[union-attr]

# Re-export the functions under test for cleaner access.
_parse_frontmatter = _script._parse_frontmatter
_extract_doc = _script._extract_doc
_collect_all_docs = _script._collect_all_docs

# Integration tests run against the real docs/ tree in the project root.
# The script resolves docs_dir relative to cwd; here we pin it explicitly.
_PROJECT_ROOT = Path(__file__).parent.parent.parent  # plugin root -> neuroloom root
_REAL_DOCS_DIR = _PROJECT_ROOT / "docs"

_REQUIRED_DOC_FIELDS = {"title", "content", "source_type", "source_path", "tags", "format", "knowledge_id"}


# ===========================================================================
# Integration tests — real docs/ tree
# ===========================================================================


class TestCollectAllDocsIntegration:
    """Run _collect_all_docs against the live docs/ tree."""

    def setup_method(self) -> None:
        self.docs, self.md_count, self.fm_count, self.skipped = _collect_all_docs(
            _REAL_DOCS_DIR
        )

    def test_nonzero_doc_count(self) -> None:
        assert len(self.docs) > 0, "Expected documents from the real docs/ tree"

    def test_md_file_count_matches_tree(self) -> None:
        # The real tree is known to have 70 .md files.
        assert self.md_count == 70

    def test_frontmatter_count_is_subset_of_md_count(self) -> None:
        assert self.fm_count <= self.md_count

    def test_frontmatter_count_nonzero(self) -> None:
        assert self.fm_count > 0

    def test_skipped_count_is_zero(self) -> None:
        # The real tree has no unreadable files.
        assert self.skipped == 0

    def test_all_docs_have_required_fields(self) -> None:
        missing = [
            (i, d.get("knowledge_id", "<no id>"), f)
            for i, d in enumerate(self.docs)
            for f in _REQUIRED_DOC_FIELDS
            if f not in d
        ]
        assert missing == [], f"Docs missing required fields: {missing[:5]}"

    def test_all_source_paths_are_relative(self) -> None:
        absolute = [d["source_path"] for d in self.docs if d["source_path"].startswith("/")]
        assert absolute == [], f"Found absolute source_paths (first 3): {absolute[:3]}"

    def test_source_paths_start_with_docs(self) -> None:
        bad = [d["source_path"] for d in self.docs if not d["source_path"].startswith("docs/")]
        assert bad == [], f"source_path does not start with 'docs/': {bad[:3]}"

    def test_chronicle_docs_have_sdlc_chronicle_source_type(self) -> None:
        chronicle_docs = [d for d in self.docs if "chronicle" in d["source_path"]]
        assert len(chronicle_docs) > 0, "Expected at least one chronicle doc"
        wrong = [d for d in chronicle_docs if d["source_type"] != "sdlc_chronicle"]
        assert wrong == [], f"Chronicle docs with wrong source_type: {wrong[:3]}"

    def test_non_chronicle_docs_have_sdlc_deliverable_source_type(self) -> None:
        non_chronicle = [d for d in self.docs if "chronicle" not in d["source_path"]]
        if not non_chronicle:
            pytest.skip("No non-chronicle docs in real tree")
        wrong = [d for d in non_chronicle if d["source_type"] != "sdlc_deliverable"]
        assert wrong == [], f"Non-chronicle docs with wrong source_type: {wrong[:3]}"

    def test_all_docs_have_sdlc_deliverable_tag(self) -> None:
        bad = [d for d in self.docs if "sdlc:deliverable" not in d.get("tags", [])]
        assert bad == [], f"Docs missing 'sdlc:deliverable' tag: {[d.get('knowledge_id') for d in bad[:3]]}"

    def test_all_knowledge_ids_prefixed_deliverable(self) -> None:
        bad = [d for d in self.docs if not d.get("knowledge_id", "").startswith("deliverable:")]
        assert bad == [], f"Docs with wrong knowledge_id prefix: {[d.get('knowledge_id') for d in bad[:3]]}"

    def test_all_formats_are_markdown(self) -> None:
        bad = [d for d in self.docs if d.get("format") != "markdown"]
        assert bad == [], f"Docs with non-markdown format: {bad[:3]}"

    def test_titles_are_non_empty_strings(self) -> None:
        bad = [d for d in self.docs if not isinstance(d["title"], str) or not d["title"]]
        assert bad == [], f"Docs with empty/non-string titles: {bad[:3]}"

    def test_content_is_non_empty_string(self) -> None:
        bad = [d for d in self.docs if not isinstance(d["content"], str) or not d["content"].strip()]
        assert bad == [], (
            f"Docs with empty content: {[d.get('knowledge_id') for d in bad[:3]]}"
        )

    def test_content_includes_frontmatter_block(self) -> None:
        """content must include the raw frontmatter, not strip it."""
        bad = [d for d in self.docs if not d["content"].startswith("---")]
        assert bad == [], (
            f"Docs whose content does not start with frontmatter '---': "
            f"{[d.get('knowledge_id') for d in bad[:3]]}"
        )

    def test_tags_are_lists(self) -> None:
        bad = [d for d in self.docs if not isinstance(d["tags"], list)]
        assert bad == [], f"Docs where tags is not a list: {bad[:3]}"

    def test_knowledge_ids_use_stem_only(self) -> None:
        """knowledge_id must be 'deliverable:<stem>', not include path separators."""
        bad = [d for d in self.docs if "/" in d.get("knowledge_id", "").split(":", 1)[-1]]
        assert bad == [], f"knowledge_id contains path separators: {bad[:3]}"

    def test_source_paths_use_forward_slashes(self) -> None:
        bad = [d for d in self.docs if "\\" in d.get("source_path", "")]
        assert bad == [], f"source_path uses backslashes: {bad[:3]}"


# ===========================================================================
# Unit tests — _parse_frontmatter
# ===========================================================================


class TestParseFrontmatter:
    """Test the YAML frontmatter parser directly with synthetic content."""

    def test_valid_frontmatter_returns_dict(self) -> None:
        content = "---\ntier: full\nstatus: complete\n---\n# Body"
        result = _parse_frontmatter(content)
        assert result == {"tier": "full", "status": "complete"}

    def test_returns_none_when_no_leading_dashes(self) -> None:
        content = "# Just a heading\nNo frontmatter here."
        assert _parse_frontmatter(content) is None

    def test_returns_none_when_no_closing_dashes(self) -> None:
        content = "---\ntier: full\nstatus: complete\n"
        assert _parse_frontmatter(content) is None

    def test_returns_none_for_empty_string(self) -> None:
        assert _parse_frontmatter("") is None

    def test_returns_none_on_yaml_parse_error(self) -> None:
        """Malformed YAML inside frontmatter must silently return None."""
        content = "---\nkey: value\n- orphan_list_item\n---\n# Body"
        assert _parse_frontmatter(content) is None

    def test_empty_frontmatter_block_returns_none(self) -> None:
        """'---\n---' is valid YAML (None) — function returns None."""
        content = "---\n---\n# Body"
        result = _parse_frontmatter(content)
        assert result is None

    def test_frontmatter_with_all_sdlc_fields(self) -> None:
        content = textwrap.dedent("""\
            ---
            tier: lite
            type: feature
            status: in-progress
            complexity: low
            ---
            # Title
        """)
        result = _parse_frontmatter(content)
        assert result is not None
        assert result["tier"] == "lite"
        assert result["type"] == "feature"
        assert result["status"] == "in-progress"

    def test_frontmatter_multiline_value(self) -> None:
        content = "---\nflavor: \"Close the loop\"\nauthor: CC\n---\nBody"
        result = _parse_frontmatter(content)
        assert result is not None
        assert result["flavor"] == "Close the loop"

    def test_does_not_strip_file_without_dashes_at_position_0(self) -> None:
        """A file with a blank line before --- is NOT frontmatter."""
        content = "\n---\ntier: full\n---\n# Body"
        assert _parse_frontmatter(content) is None

    def test_closing_dashes_must_appear_after_opening(self) -> None:
        """The closing --- must be after the first 3 characters."""
        content = "------\n# Body"
        # Finds closing '---' at position 3 — but YAML slice is empty string -> None.
        result = _parse_frontmatter(content)
        # An empty YAML block parses as None, so the function returns None.
        assert result is None


# ===========================================================================
# Unit tests — _extract_doc with synthetic files
# ===========================================================================


class TestExtractDocTagDerivation:
    """Verify tag construction from frontmatter fields."""

    def _write_doc(self, tmp_path: Path, frontmatter: str, body: str = "# Body") -> Path:
        f = tmp_path / "test_doc.md"
        f.write_text(f"---\n{frontmatter}---\n{body}", encoding="utf-8")
        return f

    def test_always_includes_sdlc_deliverable_tag(self, tmp_path: Path) -> None:
        f = self._write_doc(tmp_path, "tier: full\n")
        doc, skipped = _extract_doc(f, tmp_path)
        assert doc is not None
        assert "sdlc:deliverable" in doc["tags"]

    def test_tier_tag_added_when_present(self, tmp_path: Path) -> None:
        f = self._write_doc(tmp_path, "tier: full\n")
        doc, _ = _extract_doc(f, tmp_path)
        assert doc is not None
        assert "sdlc:tier:full" in doc["tags"]

    def test_type_tag_added_when_present(self, tmp_path: Path) -> None:
        f = self._write_doc(tmp_path, "type: feature\n")
        doc, _ = _extract_doc(f, tmp_path)
        assert doc is not None
        assert "sdlc:type:feature" in doc["tags"]

    def test_status_tag_added_when_present(self, tmp_path: Path) -> None:
        f = self._write_doc(tmp_path, "status: complete\n")
        doc, _ = _extract_doc(f, tmp_path)
        assert doc is not None
        assert "sdlc:status:complete" in doc["tags"]

    def test_all_three_tags_when_all_fields_present(self, tmp_path: Path) -> None:
        f = self._write_doc(tmp_path, "tier: lite\ntype: feature\nstatus: complete\n")
        doc, _ = _extract_doc(f, tmp_path)
        assert doc is not None
        assert "sdlc:deliverable" in doc["tags"]
        assert "sdlc:tier:lite" in doc["tags"]
        assert "sdlc:type:feature" in doc["tags"]
        assert "sdlc:status:complete" in doc["tags"]
        assert len(doc["tags"]) == 4

    def test_only_base_tag_when_no_classification_fields(self, tmp_path: Path) -> None:
        f = self._write_doc(tmp_path, "author: CC\n")
        doc, _ = _extract_doc(f, tmp_path)
        assert doc is not None
        assert doc["tags"] == ["sdlc:deliverable"]

    def test_missing_tier_does_not_produce_tier_tag(self, tmp_path: Path) -> None:
        f = self._write_doc(tmp_path, "type: feature\n")
        doc, _ = _extract_doc(f, tmp_path)
        assert doc is not None
        assert not any(t.startswith("sdlc:tier:") for t in doc["tags"])


class TestExtractDocFields:
    """Verify all required fields are set correctly."""

    def _write_doc(self, tmp_path: Path, frontmatter: str, body: str = "# Doc body") -> Path:
        f = tmp_path / "d5_my_spec.md"
        f.write_text(f"---\n{frontmatter}---\n{body}", encoding="utf-8")
        return f

    def test_title_is_raw_stem(self, tmp_path: Path) -> None:
        """title must be path.stem, not prettified."""
        f = self._write_doc(tmp_path, "tier: full\n")
        doc, _ = _extract_doc(f, tmp_path)
        assert doc is not None
        assert doc["title"] == "d5_my_spec"

    def test_knowledge_id_uses_stem(self, tmp_path: Path) -> None:
        f = self._write_doc(tmp_path, "tier: full\n")
        doc, _ = _extract_doc(f, tmp_path)
        assert doc is not None
        assert doc["knowledge_id"] == "deliverable:d5_my_spec"

    def test_format_is_markdown(self, tmp_path: Path) -> None:
        f = self._write_doc(tmp_path, "tier: full\n")
        doc, _ = _extract_doc(f, tmp_path)
        assert doc is not None
        assert doc["format"] == "markdown"

    def test_content_includes_frontmatter(self, tmp_path: Path) -> None:
        """content must retain the --- delimiters and frontmatter block."""
        f = self._write_doc(tmp_path, "tier: full\n")
        doc, _ = _extract_doc(f, tmp_path)
        assert doc is not None
        assert "---" in doc["content"]
        assert "tier: full" in doc["content"]

    def test_content_includes_body(self, tmp_path: Path) -> None:
        body = "# Doc body\nSome content here."
        f = self._write_doc(tmp_path, "tier: full\n", body)
        doc, _ = _extract_doc(f, tmp_path)
        assert doc is not None
        assert "Some content here." in doc["content"]

    def test_source_path_relative_to_docs_dir_parent(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        f = docs_dir / "my_doc.md"
        f.write_text("---\ntier: full\n---\n# Body", encoding="utf-8")
        doc, _ = _extract_doc(f, docs_dir)
        assert doc is not None
        # source_path is relative to docs_dir.parent (i.e., tmp_path)
        assert doc["source_path"] == "docs/my_doc.md"

    def test_source_path_no_leading_slash(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        f = docs_dir / "my_doc.md"
        f.write_text("---\ntier: full\n---\n# Body", encoding="utf-8")
        doc, _ = _extract_doc(f, docs_dir)
        assert doc is not None
        assert not doc["source_path"].startswith("/")

    def test_skipped_count_zero_on_success(self, tmp_path: Path) -> None:
        f = self._write_doc(tmp_path, "tier: full\n")
        doc, skipped = _extract_doc(f, tmp_path)
        assert skipped == 0

    def test_skipped_count_zero_for_no_frontmatter(self, tmp_path: Path) -> None:
        """Files without frontmatter are silently excluded — not counted as skipped."""
        f = tmp_path / "no_fm.md"
        f.write_text("# Just a heading\nNo frontmatter.", encoding="utf-8")
        doc, skipped = _extract_doc(f, tmp_path)
        assert doc is None
        assert skipped == 0

    def test_returns_none_for_malformed_yaml_frontmatter(self, tmp_path: Path) -> None:
        """Malformed YAML in frontmatter: silently skip, skipped_count stays 0."""
        f = tmp_path / "bad_yaml.md"
        f.write_text("---\nkey: value\n- orphan\n---\n# Body", encoding="utf-8")
        doc, skipped = _extract_doc(f, tmp_path)
        assert doc is None
        assert skipped == 0


class TestExtractDocSourceType:
    """Verify source_type classification based on path content."""

    def _make_doc(self, base: Path, subpath: str) -> Path:
        f = base / subpath
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("---\ntier: full\nstatus: complete\n---\n# Body", encoding="utf-8")
        return f

    def test_chronicle_path_gives_sdlc_chronicle(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        f = self._make_doc(docs_dir, "chronicle/auth/d2_spec.md")
        doc, _ = _extract_doc(f, docs_dir)
        assert doc is not None
        assert doc["source_type"] == "sdlc_chronicle"

    def test_non_chronicle_path_gives_sdlc_deliverable(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        f = self._make_doc(docs_dir, "current_work/specs/d5_spec.md")
        doc, _ = _extract_doc(f, docs_dir)
        assert doc is not None
        assert doc["source_type"] == "sdlc_deliverable"

    def test_deeply_nested_chronicle_is_sdlc_chronicle(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        f = self._make_doc(docs_dir, "chronicle/memory/specs/d14_spec.md")
        doc, _ = _extract_doc(f, docs_dir)
        assert doc is not None
        assert doc["source_type"] == "sdlc_chronicle"

    def test_file_named_chronicle_but_not_in_chronicle_dir(self, tmp_path: Path) -> None:
        """Only the *path* is checked, not the filename."""
        docs_dir = tmp_path / "docs"
        f = self._make_doc(docs_dir, "testing/chronicle_notes.md")
        doc, _ = _extract_doc(f, docs_dir)
        assert doc is not None
        # source_path is 'docs/testing/chronicle_notes.md' — no '/chronicle/' segment
        assert doc["source_type"] == "sdlc_deliverable"


class TestExtractDocOSError:
    """Verify OSError handling increments skipped_count."""

    def test_nonexistent_file_returns_none_and_skipped_one(self, tmp_path: Path) -> None:
        ghost = tmp_path / "does_not_exist.md"
        doc, skipped = _extract_doc(ghost, tmp_path)
        assert doc is None
        assert skipped == 1


# ===========================================================================
# Unit tests — _collect_all_docs with controlled directories
# ===========================================================================


class TestCollectAllDocsUnit:
    def test_nonexistent_docs_dir_returns_empty(self, tmp_path: Path) -> None:
        docs, md_count, fm_count, skipped = _collect_all_docs(tmp_path / "nonexistent")
        assert docs == []
        assert md_count == 0
        assert fm_count == 0
        assert skipped == 0

    def test_empty_docs_dir_returns_zero_counts(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        docs, md_count, fm_count, skipped = _collect_all_docs(docs_dir)
        assert docs == []
        assert md_count == 0
        assert fm_count == 0

    def test_md_file_without_frontmatter_not_counted_in_fm_count(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        f = docs_dir / "no_fm.md"
        f.write_text("# Just a heading\nNo frontmatter here.", encoding="utf-8")
        docs, md_count, fm_count, skipped = _collect_all_docs(docs_dir)
        assert md_count == 1
        assert fm_count == 0
        assert skipped == 0
        assert docs == []

    def test_md_file_with_frontmatter_counted_in_fm_count(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        f = docs_dir / "spec.md"
        f.write_text("---\ntier: full\nstatus: complete\n---\n# Spec", encoding="utf-8")
        docs, md_count, fm_count, skipped = _collect_all_docs(docs_dir)
        assert md_count == 1
        assert fm_count == 1
        assert skipped == 0
        assert len(docs) == 1

    def test_non_md_files_not_counted(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "notes.txt").write_text("some text", encoding="utf-8")
        (docs_dir / "config.yaml").write_text("key: value", encoding="utf-8")
        docs, md_count, fm_count, skipped = _collect_all_docs(docs_dir)
        assert md_count == 0

    def test_walks_subdirectories_recursively(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        sub = docs_dir / "chronicle" / "auth"
        sub.mkdir(parents=True)
        f = sub / "d2_spec.md"
        f.write_text("---\ntier: full\nstatus: complete\n---\n# Spec", encoding="utf-8")
        docs, md_count, fm_count, skipped = _collect_all_docs(docs_dir)
        assert md_count == 1
        assert fm_count == 1
        assert docs[0]["source_type"] == "sdlc_chronicle"

    def test_multiple_files_mix_of_frontmatter_and_not(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "with_fm.md").write_text(
            "---\ntier: lite\n---\n# Has FM", encoding="utf-8"
        )
        (docs_dir / "no_fm.md").write_text("# No FM", encoding="utf-8")
        docs, md_count, fm_count, skipped = _collect_all_docs(docs_dir)
        assert md_count == 2
        assert fm_count == 1
        assert skipped == 0
        assert len(docs) == 1

    def test_malformed_yaml_frontmatter_silently_excluded(self, tmp_path: Path) -> None:
        """YAML errors in frontmatter silently skip — no warning, not in skipped_count."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        f = docs_dir / "bad.md"
        f.write_text("---\nkey: value\n- orphan\n---\n# Body", encoding="utf-8")
        docs, md_count, fm_count, skipped = _collect_all_docs(docs_dir)
        assert md_count == 1
        assert fm_count == 0
        assert skipped == 0
        assert docs == []

    def test_batch_size_constant_is_50(self) -> None:
        assert _script.BATCH_SIZE == 50

    def test_all_docs_in_result_have_required_fields(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        for i in range(3):
            (docs_dir / f"doc{i}.md").write_text(
                f"---\ntier: full\nstatus: complete\ntype: feature\n---\n# Doc {i}",
                encoding="utf-8",
            )
        docs, _, _, _ = _collect_all_docs(docs_dir)
        for doc in docs:
            for field in _REQUIRED_DOC_FIELDS:
                assert field in doc, f"Missing {field!r} in doc {doc.get('knowledge_id')}"


# ===========================================================================
# Subprocess tests — CLI output formats
# ===========================================================================


class TestDryRunCLI:
    """Run the script as a subprocess with --dry-run and verify output format."""

    def _run_dry_run(
        self, extra_args: list[str] | None = None, docs_dir: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        cmd = [
            sys.executable,
            str(_SCRIPT_PATH),
            "--docs-dir", docs_dir or str(_REAL_DOCS_DIR),
            "--dry-run",
        ]
        if extra_args:
            cmd.extend(extra_args)
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_dry_run_exits_zero(self) -> None:
        result = self._run_dry_run()
        assert result.returncode == 0, f"stderr: {result.stderr}"

    def test_dry_run_output_on_stderr_not_stdout(self) -> None:
        """--dry-run must write the summary to stderr, not stdout."""
        result = self._run_dry_run()
        assert "dry run" in result.stderr.lower()
        assert result.stdout == ""

    def test_dry_run_reports_total_documents(self) -> None:
        result = self._run_dry_run()
        assert "total documents:" in result.stderr.lower()

    def test_dry_run_total_documents_nonzero(self) -> None:
        result = self._run_dry_run()
        for line in result.stderr.splitlines():
            if "total documents:" in line.lower():
                parts = line.split(":")
                count = int(parts[-1].strip())
                assert count > 0
                return
        pytest.fail("Could not find 'total documents' line in dry-run stderr output")

    def test_dry_run_reports_batches_line(self) -> None:
        result = self._run_dry_run()
        assert "batches:" in result.stderr.lower()

    def test_dry_run_prints_sample_titles(self) -> None:
        result = self._run_dry_run()
        assert "sample titles" in result.stderr.lower()

    def test_dry_run_reports_scanned_path(self) -> None:
        result = self._run_dry_run()
        scanned_lines = [l for l in result.stderr.splitlines() if "scanned:" in l.lower()]
        assert scanned_lines, "Expected a 'Scanned:' line in dry-run stderr output"

    def test_dry_run_scanned_line_mentions_docs_dir(self) -> None:
        result = self._run_dry_run()
        scanned_lines = [l for l in result.stderr.splitlines() if "scanned:" in l.lower()]
        assert scanned_lines
        # The display path should mention 'docs' somewhere.
        assert "docs" in scanned_lines[0].lower()

    def test_dry_run_zero_docs_for_empty_dir(self, tmp_path: Path) -> None:
        """Empty docs dir produces 0 documents without error."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        result = self._run_dry_run(docs_dir=str(docs_dir))
        assert result.returncode == 0
        assert "total documents: 0" in result.stderr.lower()

    def test_dry_run_zero_batches_for_zero_docs(self, tmp_path: Path) -> None:
        """Empty docs dir must report 0 batches in dry-run output."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        result = self._run_dry_run(docs_dir=str(docs_dir))
        assert result.returncode == 0
        for line in result.stderr.splitlines():
            if "batches:" in line.lower():
                # "Batches: 0 (max 50 per batch)" — extract first integer
                import re
                nums = re.findall(r"\d+", line)
                assert nums[0] == "0", f"Expected 0 batches, got: {line}"
                return
        pytest.fail("Could not find 'batches' line in dry-run output")

    def test_dry_run_does_not_require_api_token(self) -> None:
        """--dry-run must not fail when environment tokens are unset."""
        import os
        env = {k: v for k, v in os.environ.items() if "token" not in k.lower()}
        cmd = [
            sys.executable,
            str(_SCRIPT_PATH),
            "--docs-dir", str(_REAL_DOCS_DIR),
            "--dry-run",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        assert result.returncode == 0


class TestOutputFileCLI:
    """Run the script with --output FILE and verify flat JSON array output."""

    def test_output_file_writes_valid_json(self, tmp_path: Path) -> None:
        output_file = tmp_path / "docs.json"
        cmd = [
            sys.executable,
            str(_SCRIPT_PATH),
            "--docs-dir", str(_REAL_DOCS_DIR),
            "--output", str(output_file),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert output_file.exists(), "Expected --output file to be created"
        payload = json.loads(output_file.read_text(encoding="utf-8"))
        # Output is a flat JSON array, NOT {"entries": [...]}
        assert isinstance(payload, list), (
            f"Expected flat JSON array, got {type(payload).__name__}"
        )
        assert len(payload) > 0

    def test_output_file_is_flat_array_not_entries_wrapper(self, tmp_path: Path) -> None:
        """Verify the output does NOT have a wrapping 'entries' key."""
        output_file = tmp_path / "docs.json"
        cmd = [
            sys.executable,
            str(_SCRIPT_PATH),
            "--docs-dir", str(_REAL_DOCS_DIR),
            "--output", str(output_file),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0
        payload = json.loads(output_file.read_text(encoding="utf-8"))
        assert not isinstance(payload, dict), (
            "Output must be a flat array, not a dict with 'entries'"
        )

    def test_output_entries_have_required_fields(self, tmp_path: Path) -> None:
        output_file = tmp_path / "docs.json"
        cmd = [
            sys.executable,
            str(_SCRIPT_PATH),
            "--docs-dir", str(_REAL_DOCS_DIR),
            "--output", str(output_file),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0
        docs = json.loads(output_file.read_text(encoding="utf-8"))
        for doc in docs:
            for field in _REQUIRED_DOC_FIELDS:
                assert field in doc, f"Missing {field!r} in doc {doc.get('knowledge_id')}"

    def test_output_file_nothing_on_stdout(self, tmp_path: Path) -> None:
        """With --output, stdout must be empty."""
        output_file = tmp_path / "docs.json"
        cmd = [
            sys.executable,
            str(_SCRIPT_PATH),
            "--docs-dir", str(_REAL_DOCS_DIR),
            "--output", str(output_file),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0
        assert result.stdout == ""

    def test_output_single_batch_writes_one_file(self, tmp_path: Path) -> None:
        """<= 50 docs must write a single file, not numbered batch files."""
        # Use a small synthetic docs dir with just a few files.
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        for i in range(5):
            (docs_dir / f"doc{i}.md").write_text(
                f"---\ntier: full\nstatus: complete\n---\n# Doc {i}", encoding="utf-8"
            )
        output_file = tmp_path / "out" / "seed.json"
        output_file.parent.mkdir()
        cmd = [
            sys.executable,
            str(_SCRIPT_PATH),
            "--docs-dir", str(docs_dir),
            "--output", str(output_file),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert output_file.exists(), "Single-batch output file not created"
        # No numbered batch files should exist.
        assert not (output_file.parent / "seed_batch_001.json").exists()

    def test_output_multiple_batches_writes_numbered_files(self, tmp_path: Path) -> None:
        """More than 50 docs must write numbered batch files."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        for i in range(55):
            (docs_dir / f"doc{i:03d}.md").write_text(
                f"---\ntier: full\nstatus: complete\n---\n# Doc {i}", encoding="utf-8"
            )
        output_file = tmp_path / "out" / "seed.json"
        output_file.parent.mkdir()
        cmd = [
            sys.executable,
            str(_SCRIPT_PATH),
            "--docs-dir", str(docs_dir),
            "--output", str(output_file),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        # The original output path should not be written in multi-batch mode.
        batch1 = tmp_path / "out" / "seed_batch_001.json"
        batch2 = tmp_path / "out" / "seed_batch_002.json"
        assert batch1.exists(), "Expected batch_001 file"
        assert batch2.exists(), "Expected batch_002 file"
        # Each batch is a flat array.
        assert isinstance(json.loads(batch1.read_text()), list)
        assert isinstance(json.loads(batch2.read_text()), list)

    def test_empty_docs_dir_exits_zero_no_output_file(self, tmp_path: Path) -> None:
        """Empty docs dir: exits 0, prints message, no file written."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        output_file = tmp_path / "out.json"
        cmd = [
            sys.executable,
            str(_SCRIPT_PATH),
            "--docs-dir", str(docs_dir),
            "--output", str(output_file),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0
        assert not output_file.exists(), "No file should be written when docs dir is empty"
        assert "nothing to write" in result.stderr.lower()


def _parse_stdout_batches(stdout: str) -> list[dict[str, Any]]:
    """Parse stdout from the script into a flat list of docs.

    The script uses json.dumps(batch, indent=2) and writes each batch followed
    by a newline.  With indent=2 the output is multi-line pretty-printed JSON,
    not one-array-per-line.  For the real docs tree (44 docs, < 50 batch size)
    there is exactly one batch, so stdout is one complete JSON array.  For
    larger synthetic trees there may be multiple arrays concatenated with a
    newline separator.

    This helper uses json.JSONDecoder to consume all arrays from the stream.
    """
    decoder = json.JSONDecoder()
    docs: list[dict[str, Any]] = []
    text = stdout.strip()
    idx = 0
    while idx < len(text):
        # Skip whitespace/newlines between arrays.
        while idx < len(text) and text[idx] in " \t\n\r":
            idx += 1
        if idx >= len(text):
            break
        batch, end = decoder.raw_decode(text, idx)
        assert isinstance(batch, list), f"Expected list batch, got {type(batch)}"
        docs.extend(batch)
        idx = end
    return docs


class TestStdoutCLI:
    """Run the script without --output and verify JSON appears on stdout."""

    def test_stdout_produces_valid_json(self) -> None:
        cmd = [
            sys.executable,
            str(_SCRIPT_PATH),
            "--docs-dir", str(_REAL_DOCS_DIR),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        # The script writes a pretty-printed JSON array (indent=2).
        payload = json.loads(result.stdout)
        assert isinstance(payload, list), "stdout must be a flat JSON array"
        assert len(payload) > 0

    def test_stdout_is_flat_array_not_entries_wrapper(self) -> None:
        cmd = [
            sys.executable,
            str(_SCRIPT_PATH),
            "--docs-dir", str(_REAL_DOCS_DIR),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0
        # Strip trailing newline added by the script then parse.
        payload = json.loads(result.stdout.strip())
        assert not isinstance(payload, dict), (
            "stdout output must be a flat array, not a dict with 'entries'"
        )

    def test_stdout_json_docs_have_required_fields(self) -> None:
        cmd = [
            sys.executable,
            str(_SCRIPT_PATH),
            "--docs-dir", str(_REAL_DOCS_DIR),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0
        # Use the batch-aware parser to handle multi-batch output.
        all_docs = _parse_stdout_batches(result.stdout)
        assert len(all_docs) > 0
        for doc in all_docs:
            for field in _REQUIRED_DOC_FIELDS:
                assert field in doc, f"Missing {field!r} in doc {doc.get('knowledge_id')}"

    def test_stdout_empty_docs_exits_zero_with_message(self, tmp_path: Path) -> None:
        """Empty docs dir: exits 0, prints message to stderr, no stdout output."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        cmd = [
            sys.executable,
            str(_SCRIPT_PATH),
            "--docs-dir", str(docs_dir),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0
        assert result.stdout == ""
        assert "nothing to write" in result.stderr.lower()
