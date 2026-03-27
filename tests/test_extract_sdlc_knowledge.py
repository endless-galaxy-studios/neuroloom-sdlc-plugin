"""
Tests for skills/sdlc-port/scripts/extract_sdlc_knowledge.py extraction logic.

These tests exercise the pure extraction functions (_extract_yaml_entries,
_extract_discipline_entry, _collect_all_entries) against both real SDLC
knowledge files and synthetic fixtures.  No API calls are made.

Test categories:
  - Integration: _collect_all_entries against the real ops/sdlc/ tree
  - Unit: pattern parsers (entries, gotchas, rules, methodology) with synthetic data
  - Unit: edge cases (malformed YAML, README skip, empty file, null tags)
  - Subprocess: --dry-run CLI output format
  - Subprocess: --output FILE writes valid JSON
  - Subprocess: stdout output produces valid JSON
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any

import pytest
import yaml

# ---------------------------------------------------------------------------
# Import the script module without executing main().
#
# The script lives at skills/sdlc-port/scripts/extract_sdlc_knowledge.py.
# We locate the plugin root relative to this test file's location
# (tests/ -> parent = plugin root) and load it with importlib.
# ---------------------------------------------------------------------------

_PLUGIN_ROOT = Path(__file__).parent.parent  # tests/ -> plugin root
_SCRIPT_PATH = _PLUGIN_ROOT / "skills" / "sdlc-port" / "scripts" / "extract_sdlc_knowledge.py"

assert _SCRIPT_PATH.exists(), (
    f"Script not found at {_SCRIPT_PATH}. "
    "Tests must be run from the plugin repository root."
)

_spec = importlib.util.spec_from_file_location("extract_sdlc_knowledge", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
_script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_script)  # type: ignore[union-attr]

# Re-export the functions under test for cleaner access.
_collect_all_entries = _script._collect_all_entries
_extract_yaml_entries = _script._extract_yaml_entries
_extract_discipline_entry = _script._extract_discipline_entry

# Integration tests run against a project's ops/sdlc/ tree. The tests expect
# to be run from a project root that has cc-sdlc installed (e.g., neuroloom).
_PROJECT_ROOT = Path.cwd()
_REAL_KNOWLEDGE_DIR = _PROJECT_ROOT / "ops" / "sdlc" / "knowledge"
_REAL_DISCIPLINES_DIR = _PROJECT_ROOT / "ops" / "sdlc" / "disciplines"

_REQUIRED_ENTRY_FIELDS = {"title", "content", "knowledge_id", "tags", "source_path"}


# ===========================================================================
# Integration tests — real SDLC knowledge tree
# ===========================================================================


class TestCollectAllEntriesIntegration:
    """Run _collect_all_entries against the live ops/sdlc/ tree."""

    def setup_method(self) -> None:
        self.entries, self.yaml_count, self.disc_count, self.skipped = (
            _collect_all_entries(_REAL_KNOWLEDGE_DIR, _REAL_DISCIPLINES_DIR)
        )

    def test_nonzero_entry_count(self) -> None:
        assert len(self.entries) > 0, "Expected entries from real knowledge files"

    def test_all_entries_have_required_fields(self) -> None:
        missing = [
            (i, e.get("knowledge_id", "<no id>"), f)
            for i, e in enumerate(self.entries)
            for f in _REQUIRED_ENTRY_FIELDS
            if f not in e
        ]
        assert missing == [], f"Entries missing required fields: {missing[:5]}"

    def test_all_source_paths_are_relative(self) -> None:
        absolute = [
            e["source_path"]
            for e in self.entries
            if e["source_path"].startswith("/")
        ]
        assert absolute == [], (
            f"Found absolute source_paths (first 3): {absolute[:3]}"
        )

    def test_source_paths_have_no_leading_separator(self) -> None:
        leading_sep = [
            e["source_path"]
            for e in self.entries
            if e["source_path"].startswith(("/", "\\"))
        ]
        assert leading_sep == []

    def test_yaml_file_count_is_positive(self) -> None:
        assert self.yaml_count > 0

    def test_discipline_file_count_is_positive(self) -> None:
        assert self.disc_count > 0

    def test_discipline_entries_present(self) -> None:
        disc_entries = [
            e for e in self.entries if "sdlc:discipline" in e.get("tags", [])
        ]
        assert len(disc_entries) > 0, "Expected at least one discipline entry"

    def test_titles_are_non_empty_strings(self) -> None:
        bad = [e for e in self.entries if not isinstance(e["title"], str) or not e["title"]]
        assert bad == [], f"Entries with empty/non-string titles: {bad[:3]}"

    def test_content_is_non_empty_string(self) -> None:
        bad = [e for e in self.entries if not isinstance(e["content"], str) or not e["content"].strip()]
        assert bad == [], f"Entries with empty content: {[e.get('knowledge_id') for e in bad[:3]]}"

    def test_tags_are_lists(self) -> None:
        bad = [e for e in self.entries if not isinstance(e["tags"], list)]
        assert bad == [], f"Entries where tags is not a list: {bad[:3]}"

    def test_knowledge_ids_are_non_empty_strings(self) -> None:
        bad = [e for e in self.entries if not isinstance(e["knowledge_id"], str) or not e["knowledge_id"]]
        assert bad == [], f"Entries with bad knowledge_id: {bad[:3]}"


# ===========================================================================
# Unit tests — _extract_yaml_entries with specific real files
# ===========================================================================


class TestExtractYamlEntriesEntriesPattern:
    """fastapi-patterns.yaml uses the 'entries' pattern."""

    def setup_method(self) -> None:
        path = _REAL_KNOWLEDGE_DIR / "architecture" / "fastapi-patterns.yaml"
        self.entries, self.skipped = _extract_yaml_entries(path, _REAL_KNOWLEDGE_DIR)

    def test_produces_entries(self) -> None:
        assert len(self.entries) > 0

    def test_no_parse_skips(self) -> None:
        assert self.skipped == 0

    def test_entries_have_required_fields(self) -> None:
        for e in self.entries:
            for field in _REQUIRED_ENTRY_FIELDS:
                assert field in e, f"Missing {field!r} in entry {e.get('knowledge_id')}"

    def test_source_path_is_relative(self) -> None:
        for e in self.entries:
            assert not e["source_path"].startswith("/"), (
                f"Absolute source_path: {e['source_path']}"
            )

    def test_source_path_matches_relative_location(self) -> None:
        for e in self.entries:
            assert e["source_path"] == "architecture/fastapi-patterns.yaml"

    def test_knowledge_id_uses_colon_separator(self) -> None:
        """knowledge_id must use ':' not '/' (path separators replaced)."""
        for e in self.entries:
            assert "/" not in e["knowledge_id"], (
                f"Slash in knowledge_id: {e['knowledge_id']}"
            )


class TestExtractYamlEntriesNeuroloomGotchasFile:
    """neuroloom-gotchas.yaml uses the 'entries' pattern (not the broken gotchas pattern).

    This verifies that a file with Neuroloom-specific entries parses correctly.
    """

    def setup_method(self) -> None:
        path = _REAL_KNOWLEDGE_DIR / "testing" / "neuroloom-gotchas.yaml"
        self.entries, self.skipped = _extract_yaml_entries(path, _REAL_KNOWLEDGE_DIR)

    def test_produces_entries(self) -> None:
        assert len(self.entries) > 0

    def test_no_parse_skips(self) -> None:
        assert self.skipped == 0

    def test_source_path_is_relative(self) -> None:
        for e in self.entries:
            assert not e["source_path"].startswith("/")


# ===========================================================================
# Unit tests — _extract_yaml_entries with synthetic YAML
# ===========================================================================


def _yaml_tmp(content: str) -> tuple[Path, Path]:
    """Write YAML content to a temp file and return (file_path, knowledge_dir)."""
    tmp_dir = Path(tempfile.mkdtemp())
    f = tmp_dir / "test-file.yaml"
    f.write_text(textwrap.dedent(content), encoding="utf-8")
    return f, tmp_dir


class TestEntriesPatternSynthetic:
    def test_entries_pattern_parses_topic_guidance(self) -> None:
        f, root = _yaml_tmp("""
            entries:
              - topic: "My Topic"
                guidance: "My guidance text."
        """)
        entries, skipped = _extract_yaml_entries(f, root)
        assert skipped == 0
        assert len(entries) == 1
        assert entries[0]["title"] == "My Topic"
        assert "My guidance text." in entries[0]["content"]

    def test_entries_pattern_falls_back_to_title_content(self) -> None:
        f, root = _yaml_tmp("""
            entries:
              - title: "Alt Title"
                content: "Alt content."
        """)
        entries, skipped = _extract_yaml_entries(f, root)
        assert len(entries) == 1
        assert entries[0]["title"] == "Alt Title"

    def test_entries_pattern_skips_items_missing_both_title_and_topic(self) -> None:
        f, root = _yaml_tmp("""
            entries:
              - guidance: "No title here."
        """)
        entries, skipped = _extract_yaml_entries(f, root)
        assert entries == []

    def test_entries_pattern_appends_extra_fields_to_content(self) -> None:
        f, root = _yaml_tmp("""
            entries:
              - topic: "T"
                guidance: "G"
                rationale: "Because reasons."
        """)
        entries, skipped = _extract_yaml_entries(f, root)
        assert "rationale" in entries[0]["content"].lower() or "Because reasons" in entries[0]["content"]

    def test_entries_pattern_normalises_null_tags(self) -> None:
        """tags: null must produce a non-null default list (not None)."""
        f, root = _yaml_tmp("""
            entries:
              - topic: "T"
                guidance: "G"
                tags: null
        """)
        entries, skipped = _extract_yaml_entries(f, root)
        assert entries[0]["tags"] is not None
        assert isinstance(entries[0]["tags"], list)


class TestGotchasPatternSynthetic:
    def test_gotchas_pattern_parses_well_formed_item(self) -> None:
        f, root = _yaml_tmp("""
            gotchas:
              - id: "g-001"
                severity: high
                title: "Something breaks"
                symptom: "Null pointer"
                cause: "Missing init"
                resolution: "Call init() first"
                prevention: "Add assertion"
        """)
        entries, skipped = _extract_yaml_entries(f, root)
        assert skipped == 0
        assert len(entries) == 1
        e = entries[0]
        assert e["title"] == "Something breaks"
        assert "Severity: high" in e["content"]
        assert "Symptom: Null pointer" in e["content"]
        assert e["knowledge_id"] == "g-001"

    def test_gotchas_pattern_skips_item_missing_required_fields(self) -> None:
        f, root = _yaml_tmp("""
            gotchas:
              - id: "g-bad"
                title: "Missing symptom/cause/resolution"
        """)
        entries, skipped = _extract_yaml_entries(f, root)
        assert entries == []

    def test_gotchas_pattern_includes_prevention_when_present(self) -> None:
        f, root = _yaml_tmp("""
            gotchas:
              - id: "g-002"
                severity: low
                title: "Minor issue"
                symptom: "S"
                cause: "C"
                resolution: "R"
                prevention: "P"
        """)
        entries, skipped = _extract_yaml_entries(f, root)
        assert "Prevention: P" in entries[0]["content"]

    def test_gotchas_importance_maps_high_to_0_75(self) -> None:
        f, root = _yaml_tmp("""
            gotchas:
              - id: "g-hi"
                severity: high
                symptom: "S"
                cause: "C"
                resolution: "R"
        """)
        entries, skipped = _extract_yaml_entries(f, root)
        assert entries[0]["importance"] == 0.75

    def test_gotchas_importance_maps_medium_to_0_65(self) -> None:
        f, root = _yaml_tmp("""
            gotchas:
              - id: "g-med"
                severity: medium
                symptom: "S"
                cause: "C"
                resolution: "R"
        """)
        entries, skipped = _extract_yaml_entries(f, root)
        assert entries[0]["importance"] == 0.65

    def test_gotchas_importance_defaults_for_unknown_severity(self) -> None:
        f, root = _yaml_tmp("""
            gotchas:
              - id: "g-unk"
                severity: unknown
                symptom: "S"
                cause: "C"
                resolution: "R"
        """)
        entries, skipped = _extract_yaml_entries(f, root)
        assert entries[0]["importance"] == 0.55


class TestRulesPatternSynthetic:
    def test_rules_pattern_parses_well_formed_item(self) -> None:
        f, root = _yaml_tmp("""
            rules:
              - rule_id: "r-001"
                title: "Always use async"
                description: "All handlers must be async."
        """)
        entries, skipped = _extract_yaml_entries(f, root)
        assert skipped == 0
        assert len(entries) == 1
        e = entries[0]
        assert e["title"] == "Always use async"
        assert e["knowledge_id"] == "r-001"
        assert "All handlers must be async." in e["content"]

    def test_rules_pattern_skips_item_missing_required_fields(self) -> None:
        f, root = _yaml_tmp("""
            rules:
              - rule_id: "r-bad"
                description: "No title here."
        """)
        entries, skipped = _extract_yaml_entries(f, root)
        assert entries == []

    def test_rules_pattern_appends_rationale_when_present(self) -> None:
        f, root = _yaml_tmp("""
            rules:
              - rule_id: "r-002"
                title: "Rule Two"
                description: "D"
                rationale: "Because correctness."
        """)
        entries, skipped = _extract_yaml_entries(f, root)
        assert "Because correctness." in entries[0]["content"]

    def test_rules_pattern_appends_severity_tag(self) -> None:
        f, root = _yaml_tmp("""
            rules:
              - rule_id: "r-003"
                title: "Rule Three"
                description: "D"
                severity: high
        """)
        entries, skipped = _extract_yaml_entries(f, root)
        assert "sdlc:severity:high" in entries[0]["tags"]


class TestMethodologyPatternSynthetic:
    def test_methodology_pattern_produces_entry_per_non_metadata_key(self) -> None:
        f, root = _yaml_tmp("""
            id: meta-ignored
            name: also-ignored
            approach: "Do things this way."
            rationale: "Because good."
        """)
        entries, skipped = _extract_yaml_entries(f, root)
        assert skipped == 0
        titles = {e["title"] for e in entries}
        assert "Approach" in titles
        assert "Rationale" in titles
        # Metadata keys must not produce entries.
        assert "Id" not in titles
        assert "Name" not in titles

    def test_methodology_source_path_is_relative(self) -> None:
        f, root = _yaml_tmp("""
            key: "value"
        """)
        entries, skipped = _extract_yaml_entries(f, root)
        for e in entries:
            assert not e["source_path"].startswith("/")


# ===========================================================================
# Unit tests — edge cases for _extract_yaml_entries
# ===========================================================================


class TestExtractYamlEntriesEdgeCases:
    def test_malformed_yaml_returns_empty_with_skip_count_one(self) -> None:
        """Invalid YAML must return ([], 1) — not raise."""
        tmp_dir = Path(tempfile.mkdtemp())
        f = tmp_dir / "bad.yaml"
        # Mixed mapping/list YAML that fails to parse (same pattern as gotchas.yaml).
        f.write_text(
            "key: value\n- orphan_list_item\n",
            encoding="utf-8",
        )
        entries, skipped = _extract_yaml_entries(f, tmp_dir)
        assert entries == []
        assert skipped == 1

    def test_empty_yaml_file_returns_empty_with_skip_count_zero(self) -> None:
        """An empty YAML file is valid (None result) — skip count stays 0."""
        tmp_dir = Path(tempfile.mkdtemp())
        f = tmp_dir / "empty.yaml"
        f.write_text("", encoding="utf-8")
        entries, skipped = _extract_yaml_entries(f, tmp_dir)
        assert entries == []
        assert skipped == 0

    def test_yaml_with_non_dict_root_returns_skip_count_one(self) -> None:
        """YAML root that is a list (not a dict) counts as a skip."""
        tmp_dir = Path(tempfile.mkdtemp())
        f = tmp_dir / "list.yaml"
        f.write_text("- item1\n- item2\n", encoding="utf-8")
        entries, skipped = _extract_yaml_entries(f, tmp_dir)
        assert entries == []
        assert skipped == 1

    def test_source_path_uses_forward_slash_separator(self) -> None:
        """source_path must use '/' even on Windows-style relative paths."""
        sub_dir = Path(tempfile.mkdtemp())
        nested = sub_dir / "subdir"
        nested.mkdir()
        f = nested / "file.yaml"
        f.write_text("entries:\n  - topic: T\n    guidance: G\n", encoding="utf-8")
        entries, _ = _extract_yaml_entries(f, sub_dir)
        assert len(entries) == 1
        assert "\\" not in entries[0]["source_path"]
        assert "/" in entries[0]["source_path"]

    def test_pattern_key_takes_precedence_over_inferred_pattern(self) -> None:
        """Explicit pattern: key overrides inference from top-level keys."""
        # The file has a 'gotchas' key but explicitly declares pattern: entries.
        # The entries list wins.
        f, root = _yaml_tmp("""
            pattern: entries
            gotchas:
              - id: ignored
            entries:
              - topic: "Explicit entry"
                guidance: "This one should parse."
        """)
        entries, skipped = _extract_yaml_entries(f, root)
        assert len(entries) == 1
        assert entries[0]["title"] == "Explicit entry"


# ===========================================================================
# Unit tests — _extract_discipline_entry
# ===========================================================================


class TestExtractDisciplineEntry:
    def test_readme_returns_none(self, tmp_path: Path) -> None:
        readme = tmp_path / "README.md"
        readme.write_text("# Disciplines\nSome overview.", encoding="utf-8")
        assert _extract_discipline_entry(readme, tmp_path) is None

    def test_readme_case_insensitive(self, tmp_path: Path) -> None:
        readme = tmp_path / "Readme.md"
        readme.write_text("# Disciplines", encoding="utf-8")
        assert _extract_discipline_entry(readme, tmp_path) is None

    def test_empty_file_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.md"
        f.write_text("   \n  \n", encoding="utf-8")
        assert _extract_discipline_entry(f, tmp_path) is None

    def test_well_formed_file_produces_entry(self, tmp_path: Path) -> None:
        f = tmp_path / "testing.md"
        f.write_text("# Testing discipline\nContent here.", encoding="utf-8")
        entry = _extract_discipline_entry(f, tmp_path)
        assert entry is not None
        assert entry["title"] == "Testing"
        assert entry["knowledge_id"] == "disciplines:testing"
        assert "sdlc:discipline" in entry["tags"]
        assert entry["source_path"] == "testing.md"

    def test_source_path_is_relative(self, tmp_path: Path) -> None:
        f = tmp_path / "architecture.md"
        f.write_text("# Arch\nContent.", encoding="utf-8")
        entry = _extract_discipline_entry(f, tmp_path)
        assert entry is not None
        assert not entry["source_path"].startswith("/")

    def test_hyphenated_stem_becomes_title_case(self, tmp_path: Path) -> None:
        f = tmp_path / "data-modeling.md"
        f.write_text("# Data modeling discipline.", encoding="utf-8")
        entry = _extract_discipline_entry(f, tmp_path)
        assert entry is not None
        assert entry["title"] == "Data Modeling"

    def test_real_testing_discipline_file(self) -> None:
        path = _REAL_DISCIPLINES_DIR / "testing.md"
        entry = _extract_discipline_entry(path, _REAL_DISCIPLINES_DIR)
        assert entry is not None
        assert entry["knowledge_id"] == "disciplines:testing"
        assert not entry["source_path"].startswith("/")

    def test_real_architecture_discipline_file(self) -> None:
        path = _REAL_DISCIPLINES_DIR / "architecture.md"
        entry = _extract_discipline_entry(path, _REAL_DISCIPLINES_DIR)
        assert entry is not None
        assert entry["knowledge_id"] == "disciplines:architecture"


# ===========================================================================
# Unit tests — _collect_all_entries with controlled directories
# ===========================================================================


class TestCollectAllEntriesUnit:
    def test_nonexistent_knowledge_dir_returns_empty_entries(
        self, tmp_path: Path
    ) -> None:
        disciplines = tmp_path / "disciplines"
        disciplines.mkdir()
        (disciplines / "a.md").write_text("# A\nContent.", encoding="utf-8")

        entries, yaml_count, disc_count, skipped = _collect_all_entries(
            tmp_path / "nonexistent_knowledge",
            disciplines,
        )
        assert yaml_count == 0
        assert disc_count == 1
        # Discipline entries still collected even when knowledge dir missing.
        assert len(entries) == 1

    def test_nonexistent_disciplines_dir_still_collects_yaml(
        self, tmp_path: Path
    ) -> None:
        knowledge = tmp_path / "knowledge"
        knowledge.mkdir()
        yaml_file = knowledge / "file.yaml"
        yaml_file.write_text(
            "entries:\n  - topic: T\n    guidance: G\n", encoding="utf-8"
        )

        entries, yaml_count, disc_count, skipped = _collect_all_entries(
            knowledge,
            tmp_path / "nonexistent_disciplines",
        )
        assert yaml_count == 1
        assert disc_count == 0
        assert len(entries) == 1

    def test_readme_excluded_from_discipline_count(self, tmp_path: Path) -> None:
        disciplines = tmp_path / "disciplines"
        disciplines.mkdir()
        (disciplines / "README.md").write_text("# Overview", encoding="utf-8")
        (disciplines / "testing.md").write_text("# Testing\nContent.", encoding="utf-8")

        entries, _, disc_count, _ = _collect_all_entries(
            tmp_path / "no_knowledge",
            disciplines,
        )
        # README counted in disc_count but produces no entry.
        assert disc_count == 2
        assert len(entries) == 1
        assert entries[0]["knowledge_id"] == "disciplines:testing"

    def test_skipped_count_incremented_per_bad_yaml(self, tmp_path: Path) -> None:
        knowledge = tmp_path / "knowledge"
        knowledge.mkdir()
        bad1 = knowledge / "bad1.yaml"
        bad2 = knowledge / "bad2.yaml"
        # Both files are deliberately malformed.
        bad1.write_text("key: value\n- orphan\n", encoding="utf-8")
        bad2.write_text("key: value\n- orphan\n", encoding="utf-8")

        entries, yaml_count, _, skipped = _collect_all_entries(
            knowledge,
            tmp_path / "no_disciplines",
        )
        assert yaml_count == 2
        assert skipped == 2
        assert entries == []


# ===========================================================================
# Subprocess tests — CLI output formats
# ===========================================================================


class TestDryRunCLI:
    """Run the script as a subprocess with --dry-run and verify output format."""

    def _run_dry_run(self, extra_args: list[str] | None = None) -> subprocess.CompletedProcess[str]:
        cmd = [
            sys.executable,
            str(_SCRIPT_PATH),
            "--knowledge-dir", str(_REAL_KNOWLEDGE_DIR),
            "--disciplines-dir", str(_REAL_DISCIPLINES_DIR),
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

    def test_dry_run_output_on_stderr(self) -> None:
        """--dry-run must write the summary to stderr, not stdout."""
        result = self._run_dry_run()
        assert "dry run" in result.stderr.lower()
        assert result.stdout == ""

    def test_dry_run_reports_total_entries(self) -> None:
        result = self._run_dry_run()
        assert "total entries:" in result.stderr.lower()

    def test_dry_run_total_entries_nonzero(self) -> None:
        result = self._run_dry_run()
        for line in result.stderr.splitlines():
            if "total entries:" in line.lower():
                # Extract integer from "Total entries: 272" etc.
                parts = line.split(":")
                count = int(parts[-1].strip())
                assert count > 0
                return
        pytest.fail("Could not find 'total entries' line in dry-run stderr output")

    def test_dry_run_prints_sample_titles(self) -> None:
        result = self._run_dry_run()
        assert "sample titles" in result.stderr.lower()

    def test_dry_run_does_not_require_api_token(self) -> None:
        """--dry-run must not fail when MEMORIES_API_TOKEN is unset."""
        import os
        env = {k: v for k, v in os.environ.items() if k != "MEMORIES_API_TOKEN"}
        cmd = [
            sys.executable,
            str(_SCRIPT_PATH),
            "--knowledge-dir", str(_REAL_KNOWLEDGE_DIR),
            "--disciplines-dir", str(_REAL_DISCIPLINES_DIR),
            "--dry-run",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        assert result.returncode == 0

    def test_dry_run_scanned_line_contains_knowledge_and_disciplines_paths(self) -> None:
        result = self._run_dry_run()
        scanned_lines = [l for l in result.stderr.splitlines() if "scanned" in l.lower()]
        assert scanned_lines, "Expected a 'Scanned:' line in dry-run stderr output"
        scanned_line = scanned_lines[0]
        assert "knowledge" in scanned_line.lower()
        assert "disciplines" in scanned_line.lower()

    def test_dry_run_custom_knowledge_dir(self, tmp_path: Path) -> None:
        """--knowledge-dir pointing to an empty dir produces 0 entries without error."""
        knowledge = tmp_path / "knowledge"
        knowledge.mkdir()
        disciplines = tmp_path / "disciplines"
        disciplines.mkdir()

        import os
        env = {k: v for k, v in os.environ.items() if k != "MEMORIES_API_TOKEN"}
        cmd = [
            sys.executable,
            str(_SCRIPT_PATH),
            "--knowledge-dir", str(knowledge),
            "--disciplines-dir", str(disciplines),
            "--dry-run",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        assert result.returncode == 0
        assert "total entries: 0" in result.stderr.lower()


class TestOutputFileCLI:
    """Run the script with --output FILE and verify JSON output."""

    def test_output_file_writes_valid_json(self, tmp_path: Path) -> None:
        output_file = tmp_path / "seed.json"
        cmd = [
            sys.executable,
            str(_SCRIPT_PATH),
            "--knowledge-dir", str(_REAL_KNOWLEDGE_DIR),
            "--disciplines-dir", str(_REAL_DISCIPLINES_DIR),
            "--output", str(output_file),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert output_file.exists(), "Expected --output file to be created"
        payload = json.loads(output_file.read_text(encoding="utf-8"))
        assert "entries" in payload, "Output JSON must have 'entries' key"
        assert "version" in payload, "Output JSON must have 'version' key"
        assert isinstance(payload["entries"], list)
        assert len(payload["entries"]) > 0

    def test_output_file_nothing_on_stdout(self, tmp_path: Path) -> None:
        """With --output, stdout must be empty."""
        output_file = tmp_path / "seed.json"
        cmd = [
            sys.executable,
            str(_SCRIPT_PATH),
            "--knowledge-dir", str(_REAL_KNOWLEDGE_DIR),
            "--disciplines-dir", str(_REAL_DISCIPLINES_DIR),
            "--output", str(output_file),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0
        assert result.stdout == ""


class TestStdoutCLI:
    """Run the script without --output and verify JSON appears on stdout."""

    def test_stdout_produces_valid_json(self) -> None:
        cmd = [
            sys.executable,
            str(_SCRIPT_PATH),
            "--knowledge-dir", str(_REAL_KNOWLEDGE_DIR),
            "--disciplines-dir", str(_REAL_DISCIPLINES_DIR),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        payload = json.loads(result.stdout)
        assert "entries" in payload, "stdout JSON must have 'entries' key"
        assert "version" in payload, "stdout JSON must have 'version' key"
        assert isinstance(payload["entries"], list)
        assert len(payload["entries"]) > 0

    def test_stdout_json_entries_have_required_fields(self) -> None:
        cmd = [
            sys.executable,
            str(_SCRIPT_PATH),
            "--knowledge-dir", str(_REAL_KNOWLEDGE_DIR),
            "--disciplines-dir", str(_REAL_DISCIPLINES_DIR),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        for entry in payload["entries"]:
            for field in _REQUIRED_ENTRY_FIELDS:
                assert field in entry, f"Missing {field!r} in entry {entry.get('knowledge_id')}"
