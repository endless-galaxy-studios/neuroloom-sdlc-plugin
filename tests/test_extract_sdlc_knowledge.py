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
def _extract_discipline_entries(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = _script._extract_discipline_entries(*args, **kwargs)
    return result

# Integration tests run against a project's ops/sdlc/ tree. The tests expect
# to be run from a project root that has z-sdlc installed (e.g., neuroloom).
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
        # No parsed entry; the malformed item is kept whole in the unparsed entry.
        assert [e["knowledge_id"] for e in entries] == ["test-file:entries:unparsed"]
        assert "No title here." in entries[0]["content"]

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
        # An item with an id is kept whole: its other fields become the content.
        assert [e["knowledge_id"] for e in entries] == ["g-bad"]
        assert entries[0]["title"] == "Missing symptom/cause/resolution"
        assert "Missing symptom/cause/resolution" in entries[0]["content"]

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
        # A rule without a title takes one from its id; nothing is dropped.
        assert [e["knowledge_id"] for e in entries] == ["r-bad"]
        assert entries[0]["title"] == "R Bad"
        assert "No title here." in entries[0]["content"]

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
# Unit tests — sdlc:domain:<subdir> tag (ported projects need it for domain lookups)
# ===========================================================================


def _yaml_in_subdir(content: str, *subdirs: str) -> tuple[Path, Path]:
    """Write YAML to <tmp>/<subdirs...>/test-file.yaml; return (file_path, knowledge_dir)."""
    root = Path(tempfile.mkdtemp())
    target = root.joinpath(*subdirs)
    target.mkdir(parents=True, exist_ok=True)
    f = target / "test-file.yaml"
    f.write_text(textwrap.dedent(content), encoding="utf-8")
    return f, root


_ENTRIES_YAML = """
    entries:
      - topic: "T"
        guidance: "G"
"""
_GOTCHAS_YAML = """
    gotchas:
      - id: "g-1"
        severity: high
        title: "Breaks"
        symptom: "S"
        cause: "C"
        resolution: "R"
"""
_RULES_YAML = """
    rules:
      - rule_id: "r-1"
        title: "Rule"
        description: "D"
"""
_METHODOLOGY_YAML = """
    approach: "Do things this way."
"""


class TestDomainTag:
    """``knowledge/<domain>/x.yaml`` -> ``sdlc:domain:<domain>`` on every entry.

    Without it a ported entry is invisible to ``tags=["sdlc:knowledge", "sdlc:domain:<d>"],
    tags_match="all"``, the lookup every migrated skill and agent uses.
    """

    @pytest.mark.parametrize(
        "body",
        [_ENTRIES_YAML, _GOTCHAS_YAML, _RULES_YAML, _METHODOLOGY_YAML],
        ids=["entries", "gotchas", "rules", "methodology"],
    )
    def test_every_pattern_gets_the_subdirectory_domain_tag(self, body: str) -> None:
        f, root = _yaml_in_subdir(body, "architecture")
        entries, skipped = _extract_yaml_entries(f, root)
        assert skipped == 0 and entries
        for entry in entries:
            assert "sdlc:domain:architecture" in entry["tags"]
            assert "sdlc:knowledge" in entry["tags"]

    def test_a_file_directly_under_knowledge_has_no_domain(self) -> None:
        f, root = _yaml_tmp(_ENTRIES_YAML)
        entries, _ = _extract_yaml_entries(f, root)
        assert entries
        assert not any(t.startswith("sdlc:domain:") for t in entries[0]["tags"])

    def test_nested_subdirectories_use_the_first_level(self) -> None:
        f, root = _yaml_in_subdir(_ENTRIES_YAML, "testing", "deep", "er")
        entries, _ = _extract_yaml_entries(f, root)
        assert "sdlc:domain:testing" in entries[0]["tags"]
        assert not any(t == "sdlc:domain:deep" for t in entries[0]["tags"])

    def test_an_explicit_domain_tag_in_the_yaml_is_kept_and_not_doubled(self) -> None:
        f, root = _yaml_in_subdir(
            """
            entries:
              - topic: "T"
                guidance: "G"
                tags: ["sdlc:knowledge", "sdlc:domain:custom"]
            """,
            "architecture",
        )
        entries, _ = _extract_yaml_entries(f, root)
        domains = [t for t in entries[0]["tags"] if t.startswith("sdlc:domain:")]
        assert domains == ["sdlc:domain:custom"]

    def test_the_tag_is_not_duplicated_and_other_tags_survive(self) -> None:
        f, root = _yaml_in_subdir(_RULES_YAML, "coding")
        entries, _ = _extract_yaml_entries(f, root)
        tags = entries[0]["tags"]
        assert tags.count("sdlc:domain:coding") == 1
        assert "sdlc:pattern:rules" in tags and "sdlc:type:rule" in tags

    def test_the_domain_and_lookup_matches_a_ported_entry(self) -> None:
        """The AND the migrated skills run: every listed tag must be on the entry."""
        f, root = _yaml_in_subdir(_ENTRIES_YAML, "design")
        entries, _ = _extract_yaml_entries(f, root)
        wanted = {"sdlc:knowledge", "sdlc:domain:design"}
        assert wanted <= set(entries[0]["tags"])


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
        assert entries[0]["title"] == "Explicit entry"
        # The undeclared `gotchas` key is not parsed as gotchas, but it is not dropped.
        assert [e["knowledge_id"] for e in entries] == [
            "test-file:explicit_entry",
            "test-file:gotchas",
        ]


# ===========================================================================
# Unit tests — _extract_discipline_entries (z-sdlc sdlc-migrate section 2.3 split)
# ===========================================================================

_DISCIPLINE_TEXT = """# Testing Discipline

**Status**: Active
**Knowledge store**: `[sdlc-root]/knowledge/testing/`

## Summary

Framework text.

## Active Questions

*(Add per-project)*

- Question one

## Project Context

Project context text.

## Parking Lot

*Add insights here.*

### Seeded Insights

- **A.** [DEFERRED] first bullet
  continuation line

- **B.** second bullet

### Promoted

- **C.** Promoted -> somewhere

### Process Maturity Tracker

<!-- PROJECT-TRACKER-START: do not overwrite -->
| Domain | Level |
|---|---|
| Testing | 1 |
<!-- PROJECT-TRACKER-END -->

## After

Trailing framework text.
"""


def _discipline_entries(
    tmp_path: Path, text: str = _DISCIPLINE_TEXT, name: str = "testing.md",
    *, upstream: bool = False,
) -> list[dict[str, Any]]:
    f = tmp_path / name
    f.write_text(text, encoding="utf-8")
    return _extract_discipline_entries(f, tmp_path, upstream)


def _bullet_id(stem: str, text: str) -> str:
    import hashlib

    return f"discipline:{stem}:parking-lot:{hashlib.sha1(text.encode()).hexdigest()[:12]}"


class TestExtractDisciplineEntries:
    def test_readme_empty_and_blank_files_give_no_entries(self, tmp_path: Path) -> None:
        assert _discipline_entries(tmp_path, "# D\n", "README.md") == []
        assert _discipline_entries(tmp_path, "# D\n", "Readme.md") == []
        assert _discipline_entries(tmp_path, "   \n  \n", "empty.md") == []

    def test_framework_entry_has_the_shared_id_title_tags(self, tmp_path: Path) -> None:
        fw = _discipline_entries(tmp_path)[0]
        assert fw["knowledge_id"] == "discipline:testing:framework"
        assert fw["title"] == "Testing discipline framework"
        assert fw["tags"] == ["sdlc:discipline", "sdlc:discipline:testing"]
        assert fw["source_path"] == "testing.md"
        assert (fw["importance"], fw["confidence"], fw["concepts"]) == (0.55, 0.9, [])

    def test_framework_content_is_identical_in_both_modes(self, tmp_path: Path) -> None:
        port = _discipline_entries(tmp_path)[0]
        up = _discipline_entries(tmp_path, upstream=True)[0]
        assert port == up

    def test_framework_keeps_framework_sections_and_drops_project_data(
        self, tmp_path: Path
    ) -> None:
        body = _discipline_entries(tmp_path)[0]["content"]
        for kept in ("# Testing Discipline", "## Summary",
                     "Framework text.", "## Parking Lot", "*Add insights here.*",
                     "### Process Maturity Tracker", "## After", "Trailing framework text."):
            assert kept in body
        for gone in ("## Active Questions", "Question one", "## Project Context",
                     "Project context text.", "first bullet", "### Seeded Insights",
                     "PROJECT-TRACKER-START", "| Testing | 1 |", "**Status**"):
            assert gone not in body

    def test_parking_lot_bullets_become_entries_with_hashed_ids(self, tmp_path: Path) -> None:
        entries = _discipline_entries(tmp_path)
        text_a = "- **A.** [DEFERRED] first bullet\n  continuation line"
        by_id = {e["knowledge_id"]: e for e in entries}
        a = by_id[_bullet_id("testing", text_a)]
        assert a["content"] == text_a
        assert a["tags"] == [
            "sdlc:discipline", "sdlc:discipline:testing", "sdlc:parking-lot",
            "sdlc:parking-lot-section:seeded-insights", "sdlc:project-specific",
        ]
        c = by_id[_bullet_id("testing", "- **C.** Promoted -> somewhere")]
        assert "sdlc:parking-lot-section:promoted" in c["tags"]
        assert _bullet_id("testing", "- **B.** second bullet") in by_id

    def test_upstream_parking_lot_entries_carry_no_project_tag(self, tmp_path: Path) -> None:
        entries = _discipline_entries(tmp_path, upstream=True)
        bullets = [e for e in entries if ":parking-lot:" in e["knowledge_id"]]
        assert len(bullets) == 3
        assert all("sdlc:project-specific" not in e["tags"] for e in bullets)
        assert bullets[0]["tags"][:3] == [
            "sdlc:discipline", "sdlc:discipline:testing", "sdlc:parking-lot",
        ]

    def test_port_mode_project_data_entries(self, tmp_path: Path) -> None:
        by_id = {e["knowledge_id"]: e for e in _discipline_entries(tmp_path)}
        aq = by_id["discipline:testing:active-questions"]
        assert aq["tags"] == ["sdlc:discipline", "sdlc:discipline:testing"]
        assert "Question one" in aq["content"]
        pc = by_id["discipline:testing:project-context"]
        assert pc["tags"] == [
            "sdlc:discipline", "sdlc:discipline:testing", "sdlc:project-context",
        ]
        assert "Project context text." in pc["content"]
        mt = by_id["discipline:testing:maturity-tracker"]
        assert mt["tags"] == [
            "sdlc:discipline", "sdlc:discipline:testing", "sdlc:maturity-tracker",
        ]
        assert "| Testing | 1 |" in mt["content"]

    def test_upstream_mode_skips_project_data_entries(self, tmp_path: Path) -> None:
        ids = {e["knowledge_id"] for e in _discipline_entries(tmp_path, upstream=True)}
        assert not any(
            i.endswith((":active-questions", ":project-context", ":maturity-tracker"))
            for i in ids
        )

    def test_no_whole_file_disciplines_id_is_produced(self, tmp_path: Path) -> None:
        for upstream in (False, True):
            ids = [e["knowledge_id"] for e in _discipline_entries(tmp_path, upstream=upstream)]
            assert not any(i.startswith("disciplines:") for i in ids)

    def test_headings_inside_code_fences_are_not_sections(self, tmp_path: Path) -> None:
        text = "# D\n\n## Summary\n\n```\n## Parking Lot\n- not a bullet\n```\n\nend\n"
        entries = _discipline_entries(tmp_path, text)
        assert [e["knowledge_id"] for e in entries] == ["discipline:testing:framework"]
        assert "- not a bullet" in entries[0]["content"]

    def test_every_non_blank_line_is_in_some_entry_in_port_mode(self, tmp_path: Path) -> None:
        entries = _discipline_entries(tmp_path)
        have = {ln.rstrip() for e in entries for ln in e["content"].splitlines()}
        missing = [ln for ln in _DISCIPLINE_TEXT.splitlines() if ln.strip() and ln.rstrip() not in have]
        assert missing == []

    def test_real_testing_discipline_file(self) -> None:
        if not _REAL_DISCIPLINES_DIR.exists():
            pytest.skip("real disciplines not present")
        entries = _extract_discipline_entries(_REAL_DISCIPLINES_DIR / "testing.md", _REAL_DISCIPLINES_DIR)
        assert entries[0]["knowledge_id"] == "discipline:testing:framework"
        assert all(not e["source_path"].startswith("/") for e in entries)

    def test_every_line_of_every_real_and_upstream_discipline_is_kept(
        self, tmp_path: Path
    ) -> None:
        trees = [_REAL_DISCIPLINES_DIR]
        upstream = _checkout_zsdlc(tmp_path)
        if upstream is not None:
            trees.append(upstream / "disciplines")
        trees = [t for t in trees if t.exists()]
        if not trees:
            pytest.skip("no discipline trees present")
        lost: list[str] = []
        for tree in trees:
            for path in sorted(tree.glob("*.md")):
                if path.name.lower() == "readme.md":
                    continue
                entries = _extract_discipline_entries(path, tree)
                have = {ln.rstrip() for e in entries for ln in e["content"].splitlines()}
                lost += [
                    f"{path.name}: {ln[:60]}"
                    for ln in path.read_text(encoding="utf-8").splitlines()
                    if ln.strip() and ln.rstrip() not in have
                ]
        assert lost == []


def _checkout_zsdlc(tmp_path: Path, tag: str = "v2.9.10") -> Path | None:
    """Extract z-sdlc's knowledge/ and disciplines/ at ``tag``; None if unavailable."""
    import os
    import pwd

    # conftest points HOME at an empty directory and strips credential-named
    # variables, so give git its own clean environment.
    real_home = pwd.getpwuid(os.getuid()).pw_dir
    git_env = {"PATH": os.environ.get("PATH", ""), "HOME": real_home}
    repo = Path(real_home) / "Projects" / "cc-sdlc"
    target = tmp_path / f"zsdlc-{tag}"
    if (target / "knowledge").exists():
        return target
    target.mkdir(exist_ok=True)
    archive = subprocess.run(
        ["git", "-C", str(repo), "archive", tag, "knowledge", "disciplines"],
        capture_output=True, check=False, env=git_env,
    )
    if archive.returncode != 0:
        return None
    subprocess.run(["tar", "-x", "-C", str(target)], input=archive.stdout, check=True)
    return target


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
        assert entries[0]["knowledge_id"] == "discipline:testing:framework"

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
            "--max-per-file", "100000", "--max-bytes", "100000000",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert output_file.exists(), "Expected --output file to be created"
        payload = json.loads(output_file.read_text(encoding="utf-8"))
        assert "entries" in payload, "Output JSON must have 'entries' key"
        assert "version" in payload, "Output JSON must have 'version' key"
        assert isinstance(payload["entries"], list)
        assert len(payload["entries"]) > 0

    def test_output_file_prints_only_the_written_path(self, tmp_path: Path) -> None:
        """With --output, stdout is the written path and nothing else."""
        if not _REAL_KNOWLEDGE_DIR.exists():
            pytest.skip("needs a project root with ops/sdlc/knowledge (no entries, no file)")
        output_file = tmp_path / "seed.json"
        cmd = [
            sys.executable,
            str(_SCRIPT_PATH),
            "--knowledge-dir", str(_REAL_KNOWLEDGE_DIR),
            "--disciplines-dir", str(_REAL_DISCIPLINES_DIR),
            "--output", str(output_file),
            "--max-per-file", "100000", "--max-bytes", "100000000",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0
        # The written path is the only stdout.
        assert result.stdout.split() == [str(output_file)]


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
        if not _REAL_KNOWLEDGE_DIR.exists():
            pytest.skip("needs a project root with ops/sdlc/knowledge (no entries, no JSON)")
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


# ===========================================================================
# Lossless YAML: no non-metadata top-level key may be dropped
# ===========================================================================

_METADATA_KEYS = _script._METADATA_KEYS


def _ids(entries: list[dict[str, Any]]) -> list[str]:
    return [e["knowledge_id"] for e in entries]


class TestLosslessYaml:
    def test_declared_list_pattern_with_missing_list_falls_back_to_methodology(
        self,
    ) -> None:
        """Cause of the 41 empty files: `pattern: entries` with no `entries` list."""
        f, root = _yaml_tmp("""
            pattern: entries
            alpha: "first"
            beta:
              nested: value
        """)
        entries, _ = _extract_yaml_entries(f, root)
        assert _ids(entries) == ["test-file:alpha", "test-file:beta"]
        assert "first" in entries[0]["content"]
        assert "nested: value" in entries[1]["content"]

    def test_declared_rules_with_dict_value_falls_back_to_methodology(self) -> None:
        f, root = _yaml_tmp("""
            pattern: rules
            rules:
              section_a: "text a"
              section_b: "text b"
        """)
        entries, _ = _extract_yaml_entries(f, root)
        assert _ids(entries) == ["test-file:rules"]
        assert "text a" in entries[0]["content"]
        assert "text b" in entries[0]["content"]

    def test_declared_gotchas_with_scalar_value_falls_back_to_methodology(
        self,
    ) -> None:
        f, root = _yaml_tmp("""
            pattern: gotchas
            gotchas: "none yet"
        """)
        entries, _ = _extract_yaml_entries(f, root)
        assert _ids(entries) == ["test-file:gotchas"]

    def test_rules_pattern_keeps_sibling_sections(self) -> None:
        """model-tier-strategy shape: `rules` list plus other top-level sections."""
        f, root = _yaml_tmp("""
            pattern: rules
            rules:
              - rule_id: "r-1"
                title: "R one"
                description: "D"
            tier_override_decision:
              when: "always"
            maintenance: "review yearly"
        """)
        entries, _ = _extract_yaml_entries(f, root)
        assert _ids(entries) == [
            "r-1",
            "test-file:tier_override_decision",
            "test-file:maintenance",
        ]
        assert "always" in entries[1]["content"]
        assert "review yearly" in entries[2]["content"]

    def test_entries_pattern_keeps_sibling_sections(self) -> None:
        f, root = _yaml_tmp("""
            entries:
              - topic: "T"
                guidance: "G"
            extra_section: "kept"
        """)
        entries, _ = _extract_yaml_entries(f, root)
        assert "test-file:t" in _ids(entries)
        assert "test-file:extra_section" in _ids(entries)

    def test_gotchas_pattern_keeps_sibling_sections(self) -> None:
        f, root = _yaml_tmp("""
            gotchas:
              - id: "g-1"
                symptom: "S"
                cause: "C"
                resolution: "R"
            how_to_use: "read first"
        """)
        entries, _ = _extract_yaml_entries(f, root)
        assert _ids(entries) == ["g-1", "test-file:how_to_use"]

    def test_skipped_list_items_are_kept_in_one_unparsed_entry(self) -> None:
        f, root = _yaml_tmp("""
            rules:
              - rule_id: "r-ok"
                title: "OK"
                description: "fine"
              - description: "no id on this one"
              - "a bare string"
        """)
        entries, _ = _extract_yaml_entries(f, root)
        assert _ids(entries) == ["r-ok", "test-file:rules:unparsed"]
        unparsed = entries[1]["content"]
        assert "no id on this one" in unparsed
        assert "a bare string" in unparsed
        assert "fine" not in unparsed

    def test_gotchas_item_without_id_is_kept(self) -> None:
        f, root = _yaml_tmp("""
            gotchas:
              - title: "no id"
                symptom: "S"
        """)
        entries, _ = _extract_yaml_entries(f, root)
        assert _ids(entries) == ["test-file:gotchas:unparsed"]
        assert "no id" in entries[0]["content"]

    def test_metadata_only_mapping_yields_one_dump_entry(self) -> None:
        f, root = _yaml_tmp("""
            id: some-id
            name: Some Name
            description: only metadata here
        """)
        entries, _ = _extract_yaml_entries(f, root)
        assert _ids(entries) == ["test-file"]
        assert "only metadata here" in entries[0]["content"]
        assert "Some Name" in entries[0]["content"]

    def test_non_string_pattern_value_is_methodology(self) -> None:
        f, root = _yaml_tmp("""
            pattern:
              kind: custom
            body: "kept"
        """)
        entries, _ = _extract_yaml_entries(f, root)
        assert _ids(entries) == ["test-file:body"]

    def test_existing_ids_unchanged_for_methodology(self) -> None:
        f, root = _yaml_tmp("""
            approach: "x"
        """)
        entries, _ = _extract_yaml_entries(f, root)
        assert _ids(entries) == ["test-file:approach"]

    def test_unparsed_and_sibling_entries_get_domain_tag(self) -> None:
        f, root = _yaml_in_subdir(
            "rules:\n  - description: orphan\nother: x\n", "coding"
        )
        entries, _ = _extract_yaml_entries(f, root)
        assert _ids(entries) == ["coding:test-file:rules:unparsed", "coding:test-file:other"]
        for e in entries:
            assert "sdlc:domain:coding" in e["tags"]


# The same real tree the module-level constants name; these checks skip when it is absent.
_REAL_SDLC_TREE = _REAL_KNOWLEDGE_DIR.parent


class TestRealTreeLossless:
    def test_every_non_metadata_key_appears_in_some_entry(self) -> None:
        real = _REAL_SDLC_TREE / "knowledge"
        if not real.exists():
            pytest.skip("real ops/sdlc/knowledge tree not present")
        entries, *_ = _collect_all_entries(real, real / "__no_disciplines__")
        by_source: dict[str, list[dict[str, Any]]] = {}
        for e in entries:
            by_source.setdefault(e["source_path"], []).append(e)

        missing: list[str] = []
        for path in sorted(real.rglob("*.y*ml")):
            if path.name == "agent-context-map.yaml":
                continue
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            rel = str(path.relative_to(real))
            mine = by_source.get(rel, [])
            pattern = data.get("pattern") or _script._infer_pattern(data)
            list_key = None
            if isinstance(pattern, str) and pattern in ("entries", "gotchas", "rules"):
                # The declared pattern's list, else whichever recognised list exists.
                list_key = next(
                    (
                        k
                        for k in (pattern, "gotchas", "rules", "entries")
                        if isinstance(data.get(k), list)
                    ),
                    None,
                )
            for key in data:
                if key in _METADATA_KEYS:
                    continue
                if key == list_key:
                    # Some entry from this file must come from the list itself,
                    # not only from a sibling section.
                    ok = any("sdlc:pattern:methodology" not in e["tags"] for e in mine)
                else:
                    ok = any(f"### {key}\n" in e["content"] for e in mine)
                if not ok:
                    missing.append(f"{rel}:{key}")
        assert missing == []


def _norm(text: str) -> str:
    return " ".join(text.split())


def _strings_in(value: Any) -> list[str]:
    """Every string value (not dict key) anywhere inside ``value``."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [x for v in value.values() for x in _strings_in(v)]
    if isinstance(value, list):
        return [x for v in value for x in _strings_in(v)]
    return []


def _string_is_carried(text: str, entries: list[dict[str, Any]]) -> bool:
    """True when ``text`` is in an entry's content, or is one of its own fields.

    An item's id, title, tags and concepts live in the entry's ``knowledge_id``,
    ``title``, ``tags`` and ``concepts`` fields rather than in its content.
    """
    needle = _norm(text)
    for e in entries:
        if needle in _norm(e["content"]):
            return True
        own = [e["knowledge_id"], e["title"], *e["tags"], *e["concepts"]]
        if needle in (_norm(str(x)) for x in own):
            return True
    return False


class TestRealTreeEveryString:
    def test_every_string_below_the_metadata_keys_is_in_some_entry(self) -> None:
        real = _REAL_SDLC_TREE / "knowledge"
        if not real.exists():
            pytest.skip("real ops/sdlc/knowledge tree not present")
        entries, *_ = _collect_all_entries(real, real / "__no_disciplines__")
        by_source: dict[str, list[dict[str, Any]]] = {}
        for e in entries:
            by_source.setdefault(e["source_path"], []).append(e)

        lost: list[str] = []
        for path in sorted(real.rglob("*.y*ml")):
            if path.name == "agent-context-map.yaml":
                continue
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            rel = str(path.relative_to(real))
            mine = by_source.get(rel, [])
            for key, value in data.items():
                if key in _METADATA_KEYS:
                    continue
                for text in _strings_in(value):
                    if text.strip() and not _string_is_carried(text, mine):
                        lost.append(f"{rel}:{key}: {text[:60]!r}")
        assert lost == [], f"{len(lost)} strings in no entry, first: {lost[:5]}"


class TestItemFieldsAreKept:
    def test_rules_item_keeps_unrendered_fields(self) -> None:
        f, root = _yaml_tmp("""
            rules:
              - rule_id: "r-1"
                title: "T"
                description: "D"
                source: "Some Paper 2024"
                anti_pattern:
                  bad: "do this"
        """)
        entries, _ = _extract_yaml_entries(f, root)
        assert entries[0]["knowledge_id"] == "r-1"
        assert entries[0]["content"].startswith("### T\nD")
        assert "**Source:** Some Paper 2024" in entries[0]["content"]
        assert "do this" in entries[0]["content"]

    def test_rules_item_keeps_unused_alternates_and_severity(self) -> None:
        f, root = _yaml_tmp("""
            rules:
              - rule_id: "r-1"
                id: "other-id"
                title: "T"
                name: "Other name"
                description: "D"
                rule: "other text"
                severity: high
        """)
        entries, _ = _extract_yaml_entries(f, root)
        body = entries[0]["content"]
        for kept in ("other-id", "Other name", "other text", "high"):
            assert kept in body

    def test_gotcha_item_keeps_unrendered_fields_in_both_schemas(self) -> None:
        f, root = _yaml_tmp("""
            gotchas:
              - id: "g-a"
                severity: high
                symptom: "S"
                cause: "C"
                resolution: "R"
                applies_to: "fastapi"
              - id: "g-b"
                pattern: "P"
                example: "E"
                discovered: "2026-01-02 in review"
              - id: "g-c"
                title: "Fallback"
                notes:
                  - "one"
        """)
        entries, _ = _extract_yaml_entries(f, root)
        by_id = {e["knowledge_id"]: e["content"] for e in entries}
        assert by_id["g-a"].startswith("Severity: high\nSymptom: S\nCause: C\nResolution: R")
        assert "fastapi" in by_id["g-a"]
        assert "2026-01-02 in review" in by_id["g-b"]
        assert "one" in by_id["g-c"]

    def test_entries_item_keeps_title_when_topic_also_present(self) -> None:
        f, root = _yaml_tmp("""
            entries:
              - topic: "Topic"
                title: "Second title"
                guidance: "G"
                content: "Second content"
        """)
        entries, _ = _extract_yaml_entries(f, root)
        assert entries[0]["knowledge_id"] == "test-file:topic"
        assert "Second title" in entries[0]["content"]
        assert "Second content" in entries[0]["content"]


class TestListUnderAnotherKey:
    def test_declared_rules_with_entries_list_parses_rule_items(self) -> None:
        f, root = _yaml_tmp("""
            pattern: rules
            entries:
              - rule_id: "r-1"
                name: "First"
                description: "D1"
              - rule_id: "r-2"
                name: "Second"
                description: "D2"
            notes: "sibling"
        """)
        entries, _ = _extract_yaml_entries(f, root)
        assert _ids(entries) == ["r-1", "r-2", "test-file:notes"]
        assert entries[0]["title"] == "First"

    def test_declared_gotchas_with_entries_list_parses_gotcha_items(self) -> None:
        f, root = _yaml_tmp("""
            pattern: gotchas
            entries:
              - id: "g-1"
                symptom: "S"
        """)
        entries, _ = _extract_yaml_entries(f, root)
        assert _ids(entries) == ["g-1"]

    def test_declared_list_missing_with_unparsable_items_keeps_them(self) -> None:
        f, root = _yaml_tmp("""
            pattern: rules
            entries:
              - topic: "no rule id"
        """)
        entries, _ = _extract_yaml_entries(f, root)
        assert _ids(entries) == ["test-file:entries:unparsed"]

    def test_no_recognised_list_still_falls_back_to_methodology(self) -> None:
        f, root = _yaml_tmp("""
            pattern: rules
            rules:
              a: "x"
            other: "y"
        """)
        entries, _ = _extract_yaml_entries(f, root)
        assert _ids(entries) == ["test-file:rules", "test-file:other"]


# ===========================================================================
# Knowledge Markdown documents, declined files, dry-run summary (via the CLI)
# ===========================================================================


def _run_cli(
    knowledge: Path, disciplines: Path, *extra: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-I",
            str(_SCRIPT_PATH),
            "--knowledge-dir", str(knowledge),
            "--disciplines-dir", str(disciplines),
            *extra,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _seed_entries(
    tmp_path: Path, knowledge: Path, *extra: str
) -> list[dict[str, Any]]:
    disciplines = tmp_path / "disciplines"
    disciplines.mkdir(exist_ok=True)
    out = tmp_path / "seed.json"
    result = _run_cli(knowledge, disciplines, "--output", str(out), *extra)
    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    entries: list[dict[str, Any]] = payload["entries"]
    return entries


def _knowledge_tree(tmp_path: Path) -> Path:
    k = tmp_path / "knowledge"
    (k / "search").mkdir(parents=True)
    return k


class TestKnowledgeMarkdown:
    def test_markdown_document_becomes_one_entry(self, tmp_path: Path) -> None:
        k = _knowledge_tree(tmp_path)
        body = "intro\n\n# Score Transform Catalog\n\nBody text.\n"
        (k / "search" / "score-transform-catalog.md").write_text(body, encoding="utf-8")
        entries = _seed_entries(tmp_path, k)
        assert len(entries) == 1
        e = entries[0]
        assert e["knowledge_id"] == "search:score-transform-catalog"
        assert e["title"] == "Score Transform Catalog"
        assert e["content"] == body
        assert e["tags"] == [
            "sdlc:knowledge", "sdlc:pattern:document", "sdlc:domain:search",
        ]
        assert (e["importance"], e["confidence"], e["concepts"]) == (0.55, 0.9, [])
        assert e["source_path"] == "search/score-transform-catalog.md"

    def test_markdown_title_falls_back_to_filename(self, tmp_path: Path) -> None:
        k = _knowledge_tree(tmp_path)
        (k / "top_level_doc.md").write_text("no heading here\n", encoding="utf-8")
        entries = _seed_entries(tmp_path, k)
        assert entries[0]["title"] == "Top Level Doc"
        assert entries[0]["knowledge_id"] == "top_level_doc"
        assert entries[0]["tags"] == ["sdlc:knowledge", "sdlc:pattern:document"]

    def test_readme_and_provenance_log_are_not_read(self, tmp_path: Path) -> None:
        k = _knowledge_tree(tmp_path)
        (k / "README.md").write_text("# Top\n", encoding="utf-8")
        (k / "search" / "ReadMe.md").write_text("# Search\n", encoding="utf-8")
        (k / "provenance_log.md").write_text("# Log\n", encoding="utf-8")
        out = tmp_path / "seed.json"
        d = tmp_path / "disciplines"
        d.mkdir()
        result = _run_cli(k, d, "--output", str(out))
        assert result.returncode == 0 and not out.exists()

    def test_markdown_id_does_not_collide_with_yaml_ids(self, tmp_path: Path) -> None:
        k = _knowledge_tree(tmp_path)
        # YAML with only metadata keys takes the id `search:twin`.
        (k / "search" / "twin.yaml").write_text("name: Twin\n", encoding="utf-8")
        (k / "search" / "twin.md").write_text("# Twin doc\n", encoding="utf-8")
        # YAML key entry `search:dir:key` vs a markdown file at search/dir/key.md.
        (k / "search" / "dir.yaml").write_text("key: v\n", encoding="utf-8")
        (k / "search" / "dir").mkdir()
        (k / "search" / "dir" / "key.md").write_text("# K\n", encoding="utf-8")
        ids = [e["knowledge_id"] for e in _seed_entries(tmp_path, k, "--allow-duplicates")]
        assert len(ids) == 4
        assert len(set(ids)) == 4
        assert "search:twin" in ids and "search:dir:key" in ids

    def test_markdown_id_spelling_a_discipline_id_is_refused_not_suffixed(
        self, tmp_path: Path
    ) -> None:
        k = _knowledge_tree(tmp_path)
        (k / "discipline" / "testing").mkdir(parents=True)
        (k / "discipline" / "testing" / "framework.md").write_text("# T\n", encoding="utf-8")
        d = tmp_path / "disciplines"
        d.mkdir()
        (d / "testing.md").write_text("# Testing\n", encoding="utf-8")
        out = tmp_path / "seed.json"
        result = _run_cli(k, d, "--output", str(out), "--allow-duplicates")
        # The discipline: namespace is reserved (round 18); a document may not take it.
        assert result.returncode == 1 and "discipline:testing:framework" in result.stderr
        assert not out.exists()


def _write_manifest(path: Path, declined: Any) -> Path:
    path.write_text(json.dumps({"declined_files": declined}), encoding="utf-8")
    return path


class TestDeclinedFiles:
    def _tree(self, tmp_path: Path) -> Path:
        k = _knowledge_tree(tmp_path)
        (k / "search" / "keep.yaml").write_text("a: 1\n", encoding="utf-8")
        (k / "search" / "gone.yaml").write_text("b: 2\n", encoding="utf-8")
        (k / "search" / "gone-doc.md").write_text("# Gone\n", encoding="utf-8")
        (k / "search" / "other-doc.md").write_text("# Other\n", encoding="utf-8")
        return k

    def test_declined_files_are_skipped_in_both_path_forms(self, tmp_path: Path) -> None:
        k = self._tree(tmp_path)
        manifest = _write_manifest(
            tmp_path / "m.json",
            {
                "ops/sdlc/knowledge/search/gone.yaml": {"why": "no"},
                "[sdlc-root]/knowledge/search/gone-doc.md": {"why": "no"},
            },
        )
        entries = _seed_entries(tmp_path, k, "--manifest", str(manifest))
        assert sorted(e["knowledge_id"] for e in entries) == [
            "search:keep:a", "search:other-doc",
        ]

    def test_declined_does_not_apply_to_disciplines(self, tmp_path: Path) -> None:
        k = self._tree(tmp_path)
        d = tmp_path / "disciplines"
        d.mkdir()
        (d / "testing.md").write_text("# Testing\n", encoding="utf-8")
        manifest = _write_manifest(
            tmp_path / "m.json",
            {"ops/sdlc/disciplines/testing.md": {}, "[sdlc-root]/knowledge/testing.md": {}},
        )
        out = tmp_path / "seed.json"
        result = _run_cli(k, d, "--output", str(out), "--manifest", str(manifest))
        assert result.returncode == 0, result.stderr
        ids = [e["knowledge_id"] for e in json.loads(out.read_text())["entries"]]
        assert "discipline:testing:framework" in ids

    def test_missing_manifest_declines_nothing_and_warns_once(self, tmp_path: Path) -> None:
        k = self._tree(tmp_path)
        d = tmp_path / "disciplines"
        d.mkdir()
        result = _run_cli(
            k, d, "--dry-run", "--manifest", str(tmp_path / "nope.json")
        )
        assert result.returncode == 0, result.stderr
        assert result.stderr.lower().count("manifest") >= 1
        warnings = [ln for ln in result.stderr.splitlines() if ln.startswith("WARNING")]
        assert len(warnings) == 1
        assert "Total entries: 4" in result.stderr

    def test_unreadable_manifest_declines_nothing(self, tmp_path: Path) -> None:
        k = self._tree(tmp_path)
        bad = tmp_path / "m.json"
        bad.write_text("{not json", encoding="utf-8")
        entries = _seed_entries(tmp_path, k, "--manifest", str(bad))
        assert len(entries) == 4

    def test_default_manifest_is_project_root_file(self, tmp_path: Path) -> None:
        k = self._tree(tmp_path)
        _write_manifest(tmp_path / ".sdlc-manifest.json", {"ops/sdlc/knowledge/search/gone.yaml": {}})
        d = tmp_path / "disciplines"
        d.mkdir()
        result = subprocess.run(
            [sys.executable, "-I", str(_SCRIPT_PATH), "--knowledge-dir", str(k),
             "--disciplines-dir", str(d), "--dry-run"],
            capture_output=True, text=True, timeout=30, cwd=tmp_path, check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "Total entries: 3" in result.stderr
        assert "Declined: 1" in result.stderr


class TestDryRunSummary:
    def test_lists_zero_entry_files_and_declined_count(self, tmp_path: Path) -> None:
        k = _knowledge_tree(tmp_path)
        (k / "search" / "empty.yaml").write_text("", encoding="utf-8")
        (k / "search" / "empty-doc.md").write_text("", encoding="utf-8")
        (k / "search" / "ok.yaml").write_text("a: 1\n", encoding="utf-8")
        (k / "search" / "dec.yaml").write_text("a: 1\n", encoding="utf-8")
        manifest = _write_manifest(
            tmp_path / "m.json", {"ops/sdlc/knowledge/search/dec.yaml": {}}
        )
        d = tmp_path / "disciplines"
        d.mkdir()
        result = _run_cli(k, d, "--dry-run", "--manifest", str(manifest))
        assert result.returncode == 0, result.stderr
        err = result.stderr
        assert "Declined: 1" in err
        assert "Files with zero entries (2)" in err
        assert "search/empty.yaml" in err
        assert "search/empty-doc.md" in err
        assert "search/ok.yaml" not in err


# ===========================================================================
# Round 3: chunking, API-safe ids, --upstream, repr leak, dry-run report, dumper
# ===========================================================================

import re

_API_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._:-]{0,99}")


def _write_yaml_files(root: Path, counts: dict[str, int]) -> Path:
    """knowledge/<name>.yaml with ``count`` well-formed entries each."""
    k = root / "knowledge"
    k.mkdir(parents=True, exist_ok=True)
    for name, count in counts.items():
        body = "entries:\n" + "".join(
            f"  - topic: {name} item {i}\n    guidance: g\n" for i in range(count)
        )
        (k / f"{name}.yaml").write_text(body, encoding="utf-8")
    return k


def _cli(
    knowledge: Path,
    disciplines: Path,
    *extra: str,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(_SCRIPT_PATH), "--knowledge-dir", str(knowledge),
         "--disciplines-dir", str(disciplines), *extra],
        capture_output=True, text=True, timeout=60, cwd=cwd, check=False,
    )


class TestChunking:
    def _empty_disc(self, tmp_path: Path) -> Path:
        d = tmp_path / "disciplines"
        d.mkdir(exist_ok=True)
        return d

    def test_over_the_limit_writes_numbered_files_without_splitting_sources(
        self, tmp_path: Path
    ) -> None:
        k = _write_yaml_files(tmp_path, {"a": 2, "b": 2, "c": 2})
        out = tmp_path / "out" / "seed.json"
        out.parent.mkdir()
        r = _cli(k, self._empty_disc(tmp_path), "--output", str(out),
                 "--max-per-file", "3", "--version", "v1")
        assert r.returncode == 0, r.stderr
        paths = r.stdout.split()
        assert paths == [str(out.parent / f"seed_{i:03d}.json") for i in (1, 2, 3)]
        assert not out.exists()
        sources_seen: list[set[str]] = []
        total = 0
        for p in paths:
            payload = json.loads(Path(p).read_text(encoding="utf-8"))
            assert set(payload) == {"entries", "version"} and payload["version"] == "v1"
            assert 0 < len(payload["entries"]) <= 3
            total += len(payload["entries"])
            sources_seen.append({e["source_path"] for e in payload["entries"]})
        assert total == 6
        assert sum(len(x) for x in sources_seen) == len(set().union(*sources_seen))

    def test_one_source_larger_than_the_limit_is_the_only_split(
        self, tmp_path: Path
    ) -> None:
        k = _write_yaml_files(tmp_path, {"big": 5})
        out = tmp_path / "seed.json"
        r = _cli(k, self._empty_disc(tmp_path), "--output", str(out), "--max-per-file", "2")
        sizes = [len(json.loads(Path(p).read_text())["entries"]) for p in r.stdout.split()]
        assert sizes == [2, 2, 1]

    def test_fits_in_one_file_written_as_given_and_path_printed(
        self, tmp_path: Path
    ) -> None:
        k = _write_yaml_files(tmp_path, {"a": 2})
        out = tmp_path / "seed.json"
        r = _cli(k, self._empty_disc(tmp_path), "--output", str(out))
        assert r.stdout.split() == [str(out)]
        assert len(json.loads(out.read_text())["entries"]) == 2

    def test_default_limit_is_500(self, tmp_path: Path) -> None:
        k = _write_yaml_files(tmp_path, {"a": 300, "b": 300})
        out = tmp_path / "seed.json"
        r = _cli(k, self._empty_disc(tmp_path), "--output", str(out))
        assert len(r.stdout.split()) == 2

    def test_dry_run_reports_file_count(self, tmp_path: Path) -> None:
        k = _write_yaml_files(tmp_path, {"a": 2, "b": 2, "c": 2})
        r = _cli(k, self._empty_disc(tmp_path), "--dry-run", "--max-per-file", "3")
        assert "Output files: 3 (at most 3 entries and 900000 bytes each)" in r.stderr


class TestApiSafeIds:
    def _ids(self, yaml_text: str, name: str = "x.yaml") -> list[str]:
        root = Path(tempfile.mkdtemp())
        (root / name).write_text(textwrap.dedent(yaml_text), encoding="utf-8")
        entries, *_ = _collect_all_entries(root, root / "none")
        return [e["knowledge_id"] for e in entries]

    def test_valid_ids_are_byte_identical(self) -> None:
        ids = self._ids("""
            gotchas:
              - id: "Keep_me.v1:ok-2"
                symptom: s
        """)
        assert ids == ["Keep_me.v1:ok-2"]

    def test_disallowed_characters_become_dashes_and_collapse(self) -> None:
        ids = self._ids("""
            entries:
              - topic: "a/b (c)"
                guidance: g
        """)
        assert ids == ["x:a-b_-c-"]

    def test_leading_non_alphanumerics_are_stripped(self) -> None:
        ids = self._ids("""
            gotchas:
              - id: "_-foo bar"
                symptom: s
        """)
        assert ids == ["foo-bar"]

    def test_over_long_id_is_truncated_with_stable_hash(self) -> None:
        text = """
            gotchas:
              - id: "%s"
                symptom: s
        """
        first = self._ids(text % ("a" * 150 + "1"))[0]
        again = self._ids(text % ("a" * 150 + "1"))[0]
        other = self._ids(text % ("a" * 150 + "2"))[0]
        assert first == again != other
        assert len(first) == 100 and _API_ID.fullmatch(first)
        assert first.startswith("a" * 91 + "-")

    def test_duplicate_ids_get_dup_suffixes_and_a_warning(self, tmp_path: Path) -> None:
        k = tmp_path / "knowledge"
        k.mkdir()
        for name in ("a", "b", "c"):
            (k / f"{name}.yaml").write_text(
                "gotchas:\n  - id: same-id\n    symptom: s\n", encoding="utf-8"
            )
        d = tmp_path / "d"
        d.mkdir()
        out = tmp_path / "seed.json"
        r = _cli(k, d, "--output", str(out), "--allow-duplicates")
        ids = [e["knowledge_id"] for e in json.loads(out.read_text())["entries"]]
        assert ids == ["same-id", "same-id:dup2", "same-id:dup3"]
        assert "a.yaml" in r.stderr and "b.yaml" in r.stderr
        dry = _cli(k, d, "--dry-run", "--allow-duplicates")
        assert "IDs sanitized: 0; de-duplicated: 2" in dry.stderr

    def test_a_sanitized_id_never_displaces_a_valid_id(self) -> None:
        ids = self._ids("""
            gotchas:
              - id: "foo bar"
                symptom: s
              - id: "foo-bar"
                symptom: s
        """)
        assert ids == ["foo-bar:dup2", "foo-bar"]

    def test_dry_run_counts_sanitized_ids(self, tmp_path: Path) -> None:
        k = tmp_path / "knowledge"
        k.mkdir()
        (k / "a.yaml").write_text(
            "gotchas:\n  - id: 'bad id'\n    symptom: s\n", encoding="utf-8"
        )
        r = _cli(k, tmp_path / "d", "--dry-run")
        assert "IDs sanitized: 1; de-duplicated: 0" in r.stderr

    def test_every_real_tree_id_is_api_safe_and_unique(self) -> None:
        real = _REAL_SDLC_TREE
        if not (real / "knowledge").exists():
            pytest.skip("real ops/sdlc tree not present")
        entries, *_ = _collect_all_entries(real / "knowledge", real / "disciplines")
        ids = [e["knowledge_id"] for e in entries]
        assert [i for i in ids if not _API_ID.fullmatch(i)] == []
        assert len(ids) == len(set(ids))

    def test_every_upstream_v2_9_10_id_is_api_safe_and_unique(self, tmp_path: Path) -> None:
        import os
        import pwd

        # conftest points HOME at an empty directory, so ask the account database.
        real_home = pwd.getpwuid(os.getuid()).pw_dir
        repo = Path(real_home) / "Projects" / "cc-sdlc"
        # The hermetic fixture strips credential-shaped variables, which leaves a
        # dangling GIT_CONFIG_COUNT; give git a clean environment.
        git_env = {"PATH": os.environ.get("PATH", ""), "HOME": real_home}
        tag = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "-q", "--verify", "refs/tags/v2.9.10"],
            capture_output=True, text=True, check=False, env=git_env,
        )
        if tag.returncode != 0:
            pytest.skip("cc-sdlc tag v2.9.10 not available")
        archive = subprocess.run(
            ["git", "-C", str(repo), "archive", "v2.9.10", "knowledge", "disciplines"],
            capture_output=True, check=False, env=git_env,
        )
        if archive.returncode != 0:
            pytest.skip("cc-sdlc v2.9.10 has no knowledge/disciplines to archive")
        subprocess.run(["tar", "-x", "-C", str(tmp_path)], input=archive.stdout, check=True)
        entries, *_ = _collect_all_entries(
            tmp_path / "knowledge", tmp_path / "disciplines"
        )
        ids = [e["knowledge_id"] for e in entries]
        assert len(ids) > 400
        assert [i for i in ids if not _API_ID.fullmatch(i)] == []
        assert len(ids) == len(set(ids))
        upstream = _script._collect(
            tmp_path / "knowledge", tmp_path / "disciplines", upstream=True
        )
        up_ids = [e["knowledge_id"] for e in upstream.entries]
        assert [i for i in up_ids if not _API_ID.fullmatch(i)] == []
        assert len(up_ids) == len(set(up_ids))
        assert "discipline:testing:framework" in up_ids


class TestUpstreamMode:
    def _tree(self, tmp_path: Path) -> tuple[Path, Path]:
        k = _write_yaml_files(tmp_path, {"a": 1})
        d = tmp_path / "disciplines"
        d.mkdir()
        (d / "testing.md").write_text("# Testing\nBody", encoding="utf-8")
        (d / "code-review.md").write_text("# Code Review\nBody", encoding="utf-8")
        return k, d

    def _entries(self, r: subprocess.CompletedProcess[str], out: Path) -> list[dict[str, Any]]:
        assert r.returncode == 0, r.stderr
        entries: list[dict[str, Any]] = json.loads(out.read_text())["entries"]
        return entries

    def test_both_modes_use_the_shared_framework_id(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        outs = {}
        for mode, extra in (("port", []), ("up", ["--upstream"])):
            out = tmp_path / f"{mode}.json"
            outs[mode] = self._entries(_cli(k, d, *extra, "--output", str(out)), out)
        for es in outs.values():
            ids = {e["knowledge_id"] for e in es if "sdlc:discipline" in e["tags"]}
            assert ids == {"discipline:testing:framework", "discipline:code-review:framework"}
        fw = next(e for e in outs["up"] if e["knowledge_id"] == "discipline:code-review:framework")
        assert fw["title"] == "Code Review discipline framework"
        assert fw["tags"] == ["sdlc:discipline", "sdlc:discipline:code-review"]
        assert fw["content"].startswith("# Code Review\nBody")
        assert fw["source_path"] == "code-review.md"

    def test_upstream_knowledge_entries_match_port_mode(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        a, b = tmp_path / "a.json", tmp_path / "b.json"
        port = self._entries(_cli(k, d, "--output", str(a)), a)
        up = self._entries(_cli(k, d, "--upstream", "--output", str(b)), b)
        pick = lambda es: [e for e in es if "sdlc:discipline" not in e["tags"]]
        assert pick(port) == pick(up) and pick(port)

    def test_upstream_works_on_a_checkout_from_any_cwd_and_ignores_cwd_manifest(
        self, tmp_path: Path
    ) -> None:
        k, d = self._tree(tmp_path / "checkout")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / ".sdlc-manifest.json").write_text(
            json.dumps({"declined_files": {"ops/sdlc/knowledge/a.yaml": {}}}),
            encoding="utf-8",
        )
        out = tmp_path / "s.json"
        up = self._entries(
            _cli(k, d, "--upstream", "--output", str(out), cwd=elsewhere), out
        )
        assert any(e["source_path"] == "a.yaml" for e in up)
        port = self._entries(_cli(k, d, "--output", str(out), cwd=elsewhere), out)
        assert not any(e["source_path"] == "a.yaml" for e in port)


class TestReprLeakAndDumper:
    def test_entries_guidance_list_and_mapping_render_as_yaml(self) -> None:
        f, root = _yaml_tmp("""
            entries:
              - topic: "L"
                guidance:
                  - "first it's: here"
                  - second
              - topic: "M"
                content:
                  key: value
        """)
        entries, _ = _extract_yaml_entries(f, root)
        assert "['" not in entries[0]["content"] and "- second" in entries[0]["content"]
        assert "{'" not in entries[1]["content"] and "key: value" in entries[1]["content"]

    def test_dump_keeps_source_key_order_and_unicode(self) -> None:
        assert _script._dump_yaml({"b": 1, "a": "\u2014 caf\u00e9"}) == "b: 1\na: \u2014 caf\u00e9\n"

    def test_dump_does_not_fold_long_lines(self) -> None:
        text = "word " * 60
        assert text.strip() in _script._dump_yaml({"k": text.strip()})

    def test_methodology_entry_keeps_key_order_and_unicode(self) -> None:
        f, root = _yaml_tmp("""
            section:
              zebra: "one \u2014 two"
              apple: "x"
        """)
        entries, _ = _extract_yaml_entries(f, root)
        body = entries[0]["content"]
        assert body.index("zebra") < body.index("apple")
        assert "\u2014" in body and "\\u2014" not in body


class TestDryRunReport:
    def test_per_category_counts_and_unseeded_files(self, tmp_path: Path) -> None:
        k = _write_yaml_files(tmp_path, {"a": 2})
        (k / "doc.md").write_text("# Doc\n", encoding="utf-8")
        (k / "README.md").write_text("# R\n", encoding="utf-8")
        (k / "sub" / "diagrams").mkdir(parents=True)
        (k / "sub" / "diagrams" / "erd.d2").write_text("x", encoding="utf-8")
        (k / ".DS_Store").write_text("x", encoding="utf-8")
        d = tmp_path / "disciplines"
        (d / "nested").mkdir(parents=True)
        (d / "ok.md").write_text("# ok\n", encoding="utf-8")
        (d / "README.md").write_text("# R\n", encoding="utf-8")
        (d / "empty.md").write_text("", encoding="utf-8")
        (d / "nested" / "deep.md").write_text("# d\n", encoding="utf-8")
        err = _cli(k, d, "--dry-run").stderr
        assert "YAML: 1 files, 2 entries" in err
        assert "Markdown documents: 1 files, 1 entries" in err
        assert "Disciplines: 3 files, 1 entries" in err
        assert "sub/diagrams/erd.d2" in err and "DS_Store" not in err
        assert "README.md (README)" in err
        assert "empty.md (empty or unreadable)" in err
        assert "nested/deep.md (nested, not read)" in err


# ===========================================================================
# Round 4: delta mode for knowledge-update, and port/upstream fitness
# ===========================================================================


def _yaml_file(root: Path, name: str, topics: dict[str, str]) -> None:
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    body = "entries:\n" + "".join(
        f"  - topic: {t}\n    guidance: {g}\n" for t, g in topics.items()
    )
    (root / name).write_text(body, encoding="utf-8")


class TestDeltaMode:
    def _trees(self, tmp_path: Path) -> tuple[Path, Path, Path, Path]:
        base_k, tgt_k = tmp_path / "base" / "knowledge", tmp_path / "tgt" / "knowledge"
        base_d, tgt_d = tmp_path / "base" / "d", tmp_path / "tgt" / "d"
        _stub_disciplines(base_d)
        _stub_disciplines(tgt_d)
        _yaml_file(base_k, "sub/a.yaml", {"keep": "same", "edit": "old text", "drop": "gone"})
        _yaml_file(tgt_k, "sub/a.yaml", {"keep": "same", "edit": "new text", "add": "fresh"})
        for i in range(12):
            _yaml_file(base_k, f"sub/u{i:02d}.yaml", {"u": f"stable {i}"})
            _yaml_file(tgt_k, f"sub/u{i:02d}.yaml", {"u": f"stable {i}"})
        return base_k, base_d, tgt_k, tgt_d

    def _run(self, tmp_path: Path, *extra: str) -> tuple[subprocess.CompletedProcess[str], Path]:
        base_k, base_d, tgt_k, tgt_d = self._trees(tmp_path)
        out = tmp_path / "out" / "seed.json"
        out.parent.mkdir()
        r = _cli(tgt_k, tgt_d, "--upstream", "--output", str(out),
                 "--baseline-knowledge-dir", str(base_k),
                 "--baseline-disciplines-dir", str(base_d), *extra)
        return r, out

    def test_seed_holds_only_new_and_changed_entries(self, tmp_path: Path) -> None:
        r, out = self._run(tmp_path)
        assert r.returncode == 0, r.stderr
        ids = sorted(e["knowledge_id"] for e in json.loads(out.read_text())["entries"])
        assert ids == ["sub:a:add", "sub:a:edit"]

    def test_delta_file_lists_new_changed_removed_unchanged_and_probes(
        self, tmp_path: Path
    ) -> None:
        r, out = self._run(tmp_path)
        delta_path = out.with_name("seed.delta.json")
        assert r.stdout.split() == [str(out), str(delta_path)]
        delta = json.loads(delta_path.read_text())
        assert set(delta) == {"new", "new_content", "changed", "removed", "unchanged_count",
                              "probe_ids", "noop_entry", "probe_entries", "framework_ids"}
        assert delta["new"] == ["sub:a:add"]
        assert "fresh" in delta["new_content"]["sub:a:add"]
        assert delta["removed"] == ["sub:a:drop"]
        assert [c["id"] for c in delta["changed"]] == ["sub:a:edit"]
        assert "old text" in delta["changed"][0]["baseline_content"]
        assert "new text" in delta["changed"][0]["target_content"]
        # The classifier compares titles too: a seed upsert replaces both.
        edit = delta["changed"][0]
        assert {"baseline_title", "target_title"} <= set(edit)
        assert isinstance(edit["baseline_title"], str) and isinstance(edit["target_title"], str)
        assert delta["unchanged_count"] == 14
        probes = delta["probe_ids"]
        assert len(probes) == 10 and len(set(probes)) == 10
        assert all(p in {"sub:a:keep", *(f"sub:u{i:02d}:u" for i in range(12))} for p in probes)
        files = {p.split(":")[1] for p in probes}
        assert len(files) == 10

    def test_chunked_seed_files_still_precede_the_delta_path(self, tmp_path: Path) -> None:
        r, out = self._run(tmp_path, "--max-per-file", "1")
        paths = r.stdout.split()
        assert paths[-1] == str(out.with_name("seed.delta.json"))
        assert paths[:-1] == [str(out.with_name(f"seed_{i:03d}.json")) for i in (1, 2)]

    def test_dry_run_reports_the_delta_and_writes_nothing(self, tmp_path: Path) -> None:
        base_k, base_d, tgt_k, tgt_d = self._trees(tmp_path)
        r = _cli(tgt_k, tgt_d, "--upstream", "--dry-run", "--baseline-knowledge-dir", str(base_k),
                 "--baseline-disciplines-dir", str(base_d))
        assert "Delta: 1 new, 1 changed, 1 removed, 14 unchanged" in r.stderr

    def test_baseline_flags_come_as_a_pair_and_need_output(self, tmp_path: Path) -> None:
        base_k, base_d, tgt_k, tgt_d = self._trees(tmp_path)
        one = _cli(tgt_k, tgt_d, "--output", str(tmp_path / "s.json"),
                   "--baseline-knowledge-dir", str(base_k))
        assert one.returncode == 2 and "must be given together" in one.stderr
        no_out = _cli(tgt_k, tgt_d, "--upstream", "--baseline-knowledge-dir", str(base_k),
                      "--baseline-disciplines-dir", str(base_d))
        assert no_out.returncode == 2 and "needs --output" in no_out.stderr

    def test_without_baseline_flags_nothing_changes(self, tmp_path: Path) -> None:
        _, _, tgt_k, tgt_d = self._trees(tmp_path)
        out = tmp_path / "plain.json"
        r = _cli(tgt_k, tgt_d, "--output", str(out))
        assert r.stdout.split() == [str(out)]
        assert not out.with_name("plain.delta.json").exists()

    def test_discipline_changes_are_detected_per_entry(self, tmp_path: Path) -> None:
        base_d, tgt_d = tmp_path / "bd", tmp_path / "td"
        for d, extra in ((base_d, ""), (tgt_d, "- **New seeded.** [DEFERRED] x\n")):
            _stub_disciplines(d)
            (d / "testing.md").write_text(
                "# T\n\n## Parking Lot\n\n*note*\n\n- **Old.** y\n" + extra, encoding="utf-8"
            )
        k = tmp_path / "k"
        _nested(k, "a", {"x": "1"})
        out = tmp_path / "s.json"
        r = _cli(k, tgt_d, "--upstream", "--output", str(out),
                 "--baseline-knowledge-dir", str(k), "--baseline-disciplines-dir", str(base_d))
        assert r.returncode == 0, r.stderr
        es = json.loads(out.read_text())["entries"]
        assert [e["content"] for e in es] == ["- **New seeded.** [DEFERRED] x"]


class TestPortUpstreamFitness:
    """Port mode on a z-sdlc tree must agree with --upstream on knowledge and framework."""

    @staticmethod
    def _both(k: Path, d: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        port = {e["knowledge_id"]: e for e in _script._collect(k, d, upstream=False).entries}
        up = {e["knowledge_id"]: e for e in _script._collect(k, d, upstream=True).entries}
        return port, up

    @staticmethod
    def _shared(entry_id: str, entry: dict[str, Any]) -> bool:
        return entry_id.endswith(":framework") or "sdlc:discipline" not in entry["tags"]

    def _assert_agree(self, k: Path, d: Path) -> None:
        port, up = self._both(k, d)
        shared_up = {i: e for i, e in up.items() if self._shared(i, e)}
        assert shared_up
        assert {i: port.get(i) for i in shared_up} == shared_up
        assert {i for i, e in port.items() if self._shared(i, e)} == set(shared_up)
        # Only project-data entries are port-only.
        extra = set(port) - set(up)
        assert all(
            i.endswith((":active-questions", ":project-context", ":maturity-tracker"))
            for i in extra
        )

    def test_synthetic_tree(self, tmp_path: Path) -> None:
        k = _write_yaml_files(tmp_path, {"a": 2})
        (k / "doc.md").write_text("# Doc\n", encoding="utf-8")
        d = tmp_path / "disciplines"
        d.mkdir()
        (d / "testing.md").write_text(_DISCIPLINE_TEXT, encoding="utf-8")
        self._assert_agree(k, d)

    def test_zsdlc_v2_9_10(self, tmp_path: Path) -> None:
        root = _checkout_zsdlc(tmp_path)
        if root is None:
            pytest.skip("cc-sdlc tag v2.9.10 not available")
        self._assert_agree(root / "knowledge", root / "disciplines")

    def test_real_tree(self) -> None:
        if not _REAL_KNOWLEDGE_DIR.exists():
            pytest.skip("real ops/sdlc tree not present")
        self._assert_agree(_REAL_KNOWLEDGE_DIR, _REAL_DISCIPLINES_DIR)


# ===========================================================================
# Round 4 addendum: byte limit, --tag, empty output, duplicate ids, --help
# ===========================================================================


def _fat_yaml(root: Path, name: str, count: int, size: int) -> None:
    root.mkdir(parents=True, exist_ok=True)
    body = "entries:\n" + "".join(
        f"  - topic: {name} item {i}\n    guidance: {'x' * size}\n" for i in range(count)
    )
    (root / f"{name}.yaml").write_text(body, encoding="utf-8")


class TestByteLimit:
    def _written(self, r: subprocess.CompletedProcess[str]) -> list[Path]:
        return [Path(p) for p in r.stdout.split()]

    def test_files_stay_within_the_byte_limit_without_splitting_sources(
        self, tmp_path: Path
    ) -> None:
        k = tmp_path / "knowledge"
        for name in ("a", "b", "c"):
            _fat_yaml(k, name, 2, 400)
        d = tmp_path / "d"
        d.mkdir()
        out = tmp_path / "seed.json"
        r = _cli(k, d, "--output", str(out), "--max-bytes", "2200")
        files = self._written(r)
        assert len(files) == 3
        for f in files:
            assert f.stat().st_size <= 2200
            assert len({e["source_path"] for e in json.loads(f.read_text())["entries"]}) == 1

    def test_one_file_when_everything_fits_both_limits(self, tmp_path: Path) -> None:
        k = tmp_path / "knowledge"
        _fat_yaml(k, "a", 2, 100)
        d = tmp_path / "d"
        d.mkdir()
        out = tmp_path / "seed.json"
        r = _cli(k, d, "--output", str(out))
        assert self._written(r) == [out]

    def test_a_source_over_the_byte_limit_is_split_by_entries_with_a_warning(
        self, tmp_path: Path
    ) -> None:
        k = tmp_path / "knowledge"
        _fat_yaml(k, "big", 5, 400)
        d = tmp_path / "d"
        d.mkdir()
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"), "--max-bytes", "1500")
        files = self._written(r)
        assert len(files) >= 2
        assert all(f.stat().st_size <= 1500 for f in files)
        assert sum(len(json.loads(f.read_text())["entries"]) for f in files) == 5
        assert "splitting it by entries" in r.stderr

    def test_a_single_entry_over_the_limit_exits_nonzero_and_names_it(
        self, tmp_path: Path
    ) -> None:
        k = tmp_path / "knowledge"
        _fat_yaml(k, "a", 1, 3000)
        _fat_yaml(k, "b", 1, 50)
        d = tmp_path / "d"
        d.mkdir()
        out = tmp_path / "seed.json"
        r = _cli(k, d, "--output", str(out), "--max-bytes", "1000")
        assert r.returncode == 1 and r.stdout == ""
        assert "a:a_item_0" in r.stderr and "--max-bytes" in r.stderr
        assert not list(tmp_path.glob("seed*.json"))
        assert _cli(k, d, "--dry-run", "--max-bytes", "1000").returncode == 1

    def test_both_limits_apply_together(self, tmp_path: Path) -> None:
        k = tmp_path / "knowledge"
        for name in ("a", "b"):
            _fat_yaml(k, name, 3, 10)
        d = tmp_path / "d"
        d.mkdir()
        r = _cli(k, d, "--output", str(tmp_path / "s.json"), "--max-per-file", "4",
                 "--max-bytes", "100000")
        assert [len(json.loads(f.read_text())["entries"]) for f in self._written(r)] == [3, 3]

    def test_dry_run_lists_each_file_size(self, tmp_path: Path) -> None:
        k = tmp_path / "knowledge"
        _fat_yaml(k, "a", 2, 400)
        _fat_yaml(k, "b", 2, 400)
        d = tmp_path / "d"
        d.mkdir()
        err = _cli(k, d, "--dry-run", "--max-bytes", "1800").stderr
        assert "Output files: 2 (at most 500 entries and 1800 bytes each)" in err
        assert "file 1: 2 entries," in err and "file 2: 2 entries," in err


class TestTagOption:
    def _tree(self, tmp_path: Path) -> tuple[Path, Path]:
        k = _write_yaml_files(tmp_path, {"a": 1})
        d = tmp_path / "d"
        d.mkdir()
        (d / "testing.md").write_text("# T\n\n## Parking Lot\n\n- **x.** y\n", encoding="utf-8")
        return k, d

    def test_tags_are_added_to_every_entry_once(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        out = tmp_path / "s.json"
        r = _cli(k, d, "--output", str(out), "--tag", "sdlc:project-specific",
                 "--tag", "extra:one", "--tag", "sdlc:project-specific")
        assert r.returncode == 0, r.stderr
        for e in json.loads(out.read_text())["entries"]:
            assert e["tags"].count("sdlc:project-specific") == 1
            assert "extra:one" in e["tags"]

    def test_reserved_tags_are_refused(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        for tag in ("sdlc:sentinel", "sdlc:deprecated"):
            r = _cli(k, d, "--output", str(tmp_path / "s.json"), "--tag", tag)
            assert r.returncode == 2 and "reserved" in r.stderr and tag in r.stderr
        assert not (tmp_path / "s.json").exists()


class TestEmptyOutput:
    def test_no_entries_writes_no_file_prints_nothing_and_exits_zero(
        self, tmp_path: Path
    ) -> None:
        k = tmp_path / "knowledge"
        k.mkdir()
        d = tmp_path / "d"
        d.mkdir()
        out = tmp_path / "seed.json"
        r = _cli(k, d, "--output", str(out))
        assert r.returncode == 0 and r.stdout == "" and not out.exists()
        assert "No entries" in r.stderr

    def test_no_entries_to_stdout_prints_nothing(self, tmp_path: Path) -> None:
        k = tmp_path / "knowledge"
        k.mkdir()
        d = tmp_path / "d"
        d.mkdir()
        r = _cli(k, d)
        assert r.returncode == 0 and r.stdout == "" and "No entries" in r.stderr

    def test_empty_delta_writes_the_delta_file_but_no_seed(self, tmp_path: Path) -> None:
        k = tmp_path / "knowledge"
        _nested(k, "a", {"x": "1"})
        d = _stub_disciplines(tmp_path / "d")
        out = tmp_path / "seed.json"
        r = _cli(k, d, "--upstream", "--output", str(out), "--baseline-knowledge-dir", str(k),
                 "--baseline-disciplines-dir", str(d))
        assert r.returncode == 0, r.stderr
        assert r.stdout.split() == [str(tmp_path / "seed.delta.json")]
        assert not out.exists()
        assert json.loads((tmp_path / "seed.delta.json").read_text())["unchanged_count"] == 2


class TestDuplicateIdsFail:
    def _tree(self, tmp_path: Path) -> tuple[Path, Path]:
        k = tmp_path / "knowledge"
        k.mkdir()
        for name in ("a", "b", "c"):
            (k / f"{name}.yaml").write_text(
                "gotchas:\n  - id: same-id\n    symptom: s\n", encoding="utf-8"
            )
        (k / "twin.yaml").write_text("name: Twin\n", encoding="utf-8")
        (k / "twin.md").write_text("# Twin\n", encoding="utf-8")
        d = tmp_path / "d"
        d.mkdir()
        return k, d

    def test_a_write_fails_and_names_every_collision(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        out = tmp_path / "seed.json"
        r = _cli(k, d, "--output", str(out))
        assert r.returncode == 1
        assert not out.exists() and r.stdout == ""
        assert "Duplicate ids (3)" in r.stderr
        assert "same-id:dup2" in r.stderr and "same-id:dup3" in r.stderr
        assert "twin:document" in r.stderr

    def test_a_dry_run_fails_too(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        r = _cli(k, d, "--dry-run")
        assert r.returncode == 1 and "Duplicate ids (3)" in r.stderr

    def test_allow_duplicates_keeps_the_suffixes_and_exits_zero(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        out = tmp_path / "seed.json"
        r = _cli(k, d, "--output", str(out), "--allow-duplicates")
        assert r.returncode == 0, r.stderr
        ids = [e["knowledge_id"] for e in json.loads(out.read_text())["entries"]]
        assert "same-id:dup2" in ids and "twin:document" in ids

    def test_a_clean_run_is_unaffected(self, tmp_path: Path) -> None:
        k = _write_yaml_files(tmp_path, {"a": 1})
        d = tmp_path / "d"
        d.mkdir()
        assert _cli(k, d, "--dry-run").returncode == 0


class TestHelpText:
    def test_help_and_docstring_cover_every_flag(self) -> None:
        r = subprocess.run([sys.executable, "-I", str(_SCRIPT_PATH), "--help"],
                           capture_output=True, text=True, check=False)
        flags = ["--knowledge-dir", "--disciplines-dir", "--version", "--output",
                 "--max-per-file", "--max-bytes", "--tag", "--allow-duplicates",
                 "--dry-run", "--manifest", "--baseline-knowledge-dir",
                 "--baseline-disciplines-dir", "--upstream", "--tag-new", "--only-ids",
                 "--no-manifest", "--max-entries"]
        assert [f for f in flags if f not in r.stdout] == []
        doc = _script.__doc__ or ""
        assert [f for f in flags if f not in doc and f not in ("--version", "--manifest")] == []
        for phrase in ("stdout", ".delta.json", "probe_ids", "exit", "noop_entry", "new_content"):
            assert phrase in doc.lower() or phrase in doc


# ===========================================================================
# Round 5: fail-closed baseline, noop entry, probes, --only-ids, --tag-new,
# --tag honesty, golden output
# ===========================================================================


def _nested(root: Path, name: str, topics: dict[str, str]) -> None:
    _yaml_file(root, f"sub/{name}.yaml", topics)


class TestBaselineFailsClosed:
    def _args(self, tmp_path: Path) -> tuple[Path, Path, Path, Path]:
        tgt_k, tgt_d = tmp_path / "tgt" / "k", tmp_path / "tgt" / "d"
        _stub_disciplines(tgt_d)
        _nested(tgt_k, "a", {"x": "1"})
        return tgt_k, tgt_d, tmp_path / "base" / "k", tmp_path / "base" / "d"

    def test_missing_baseline_directories_exit_2(self, tmp_path: Path) -> None:
        tgt_k, tgt_d, base_k, base_d = self._args(tmp_path)
        out = tmp_path / "seed.json"
        r = _cli(tgt_k, tgt_d, "--upstream", "--output", str(out),
                 "--baseline-knowledge-dir", str(base_k),
                 "--baseline-disciplines-dir", str(base_d))
        assert r.returncode == 2 and "does not exist" in r.stderr
        assert not out.exists() and r.stdout == ""
        base_k.mkdir(parents=True)
        r = _cli(tgt_k, tgt_d, "--upstream", "--output", str(out),
                 "--baseline-knowledge-dir", str(base_k),
                 "--baseline-disciplines-dir", str(base_d))
        assert r.returncode == 2 and "does not exist" in r.stderr

    def test_a_baseline_that_yields_no_entries_exits_2(self, tmp_path: Path) -> None:
        tgt_k, tgt_d, base_k, base_d = self._args(tmp_path)
        base_k.mkdir(parents=True)
        base_d.mkdir(parents=True)
        out = tmp_path / "seed.json"
        r = _cli(tgt_k, tgt_d, "--upstream", "--output", str(out),
                 "--baseline-knowledge-dir", str(base_k),
                 "--baseline-disciplines-dir", str(base_d))
        assert r.returncode == 2 and "no entries" in r.stderr
        assert not out.exists() and r.stdout == ""

    def test_unchanged_entries_without_a_qualifying_probe_still_produce_a_delta(
        self, tmp_path: Path
    ) -> None:
        # Root-level files give one-colon ids, which the pre-0.7.0 handler also produced.
        k = _write_yaml_files(tmp_path, {"a": 3})
        d = _stub_disciplines(tmp_path / "d")
        out = tmp_path / "s.json"
        r = _cli(k, d, "--upstream", "--output", str(out),
                 "--baseline-knowledge-dir", str(k), "--baseline-disciplines-dir", str(d))
        assert r.returncode == 0, r.stderr
        delta = json.loads(out.with_name("s.delta.json").read_text())
        assert delta["probe_ids"] == [] and delta["unchanged_count"] == 4
        assert len(delta["probe_entries"]) == 4
        assert delta["noop_entry"] is not None


class TestNoopEntryAndProbes:
    def _run(self, tmp_path: Path, extra_target: dict[str, str] | None = None,
             *flags: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]], Path]:
        base_k, tgt_k = tmp_path / "bk", tmp_path / "tk"
        base_d, tgt_d = tmp_path / "bd", tmp_path / "td"
        _stub_disciplines(base_d)
        _stub_disciplines(tgt_d)
        _nested(base_k, "changing", {"keep": "same", "edit": "old"})
        _nested(tgt_k, "changing", {"keep": "same", "edit": "new", **(extra_target or {})})
        for name in ("zeta", "alpha", "mid"):
            _nested(base_k, name, {"item": f"stable {name}"})
            _nested(tgt_k, name, {"item": f"stable {name}"})
        out = tmp_path / "o" / "seed.json"
        out.parent.mkdir()
        r = _cli(tgt_k, tgt_d, "--upstream", "--output", str(out),
                 "--baseline-knowledge-dir", str(base_k),
                 "--baseline-disciplines-dir", str(base_d), *flags)
        assert r.returncode == 0, r.stderr
        delta = json.loads(out.with_name("seed.delta.json").read_text())
        full = {e["knowledge_id"]: e for e in _script._collect(tgt_k, tgt_d, upstream=True).entries}
        return delta, full, out

    def test_noop_entry_is_a_full_unchanged_entry_from_an_untouched_file(
        self, tmp_path: Path
    ) -> None:
        delta, full, _ = self._run(tmp_path)
        noop = delta["noop_entry"]
        assert noop["knowledge_id"] == "sub:alpha:item"
        assert noop == full["sub:alpha:item"]
        assert set(noop) >= {"title", "content", "knowledge_id", "tags", "source_path"}

    def test_noop_entry_prefers_knowledge_over_discipline(self, tmp_path: Path) -> None:
        delta, _, _ = self._run(tmp_path)
        assert not delta["noop_entry"]["knowledge_id"].startswith("discipline:")

    def test_noop_entry_is_null_without_unchanged_entries(self, tmp_path: Path) -> None:
        base_k, tgt_k = tmp_path / "bk", tmp_path / "tk"
        bd, td = tmp_path / "bd", tmp_path / "td"
        _stub_disciplines(bd)
        _stub_disciplines(td)
        (td / "stub.md").write_text("# Stub\n\n## Summary\n\nchanged\n", encoding="utf-8")
        _nested(base_k, "a", {"x": "old"})
        _nested(tgt_k, "a", {"x": "new"})
        out = tmp_path / "seed.json"
        r = _cli(tgt_k, td, "--upstream", "--output", str(out),
                 "--baseline-knowledge-dir", str(base_k), "--baseline-disciplines-dir", str(bd))
        assert r.returncode == 0, r.stderr
        assert json.loads(out.with_name("seed.delta.json").read_text())["noop_entry"] is None

    def test_tags_given_with_tag_reach_the_noop_entry(self, tmp_path: Path) -> None:
        delta, _, _ = self._run(tmp_path, None, "--tag", "extra:x")
        assert "extra:x" in delta["noop_entry"]["tags"]

    def test_probe_ids_are_only_ids_the_old_scheme_never_produced(self, tmp_path: Path) -> None:
        base_k, tgt_k = tmp_path / "bk", tmp_path / "tk"
        base_d, tgt_d = tmp_path / "bd", tmp_path / "td"
        _stub_disciplines(base_d)
        _stub_disciplines(tgt_d)
        for root in (base_k, tgt_k):
            _yaml_file(root, "rootfile.yaml", {"one": "x"})          # rootfile:one
            _nested(root, "nested", {"two": "y"})                    # sub:nested:two
            (root / "g.yaml").write_text(
                "gotchas:\n  - id: bare-id\n    symptom: s\n", encoding="utf-8"
            )
        for d in (base_d, tgt_d):
            (d / "testing.md").write_text(
                "# T\n\n## Summary\n\nx\n\n## Parking Lot\n\n*n*\n\n- **b.** bullet\n",
                encoding="utf-8",
            )
        out = tmp_path / "seed.json"
        r = _cli(tgt_k, tgt_d, "--upstream", "--output", str(out),
                 "--baseline-knowledge-dir", str(base_k), "--baseline-disciplines-dir", str(base_d))
        assert r.returncode == 0, r.stderr
        probes = json.loads(out.with_name("seed.delta.json").read_text())["probe_ids"]
        assert "sub:nested:two" in probes
        assert any(":parking-lot:" in p for p in probes)
        assert not {"rootfile:one", "bare-id", "discipline:testing:framework"} & set(probes)


class TestOnlyIds:
    def _tree(self, tmp_path: Path) -> tuple[Path, Path]:
        k = tmp_path / "k"
        _yaml_file(k, "a.yaml", {"one": "1", "two": "2", "three": "3"})
        d = tmp_path / "d"
        d.mkdir()
        return k, d

    def test_only_the_listed_ids_are_written(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        ids = tmp_path / "ids.txt"
        ids.write_text("a:one\n\na:three\n", encoding="utf-8")
        out = tmp_path / "s.json"
        r = _cli(k, d, "--output", str(out), "--only-ids", str(ids))
        assert r.returncode == 0, r.stderr
        got = [e["knowledge_id"] for e in json.loads(out.read_text())["entries"]]
        assert got == ["a:one", "a:three"]

    def test_the_listed_ids_are_still_packed_by_the_limits(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        ids = tmp_path / "ids.txt"
        ids.write_text("a:one\na:two\na:three\n", encoding="utf-8")
        r = _cli(k, d, "--output", str(tmp_path / "s.json"), "--only-ids", str(ids),
                 "--max-entries", "2")
        assert len(r.stdout.split()) == 2

    def test_an_empty_list_writes_nothing_and_exits_zero(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        ids = tmp_path / "ids.txt"
        ids.write_text("\n", encoding="utf-8")
        out = tmp_path / "s.json"
        r = _cli(k, d, "--output", str(out), "--only-ids", str(ids), "--tag", "x:y")
        assert r.returncode == 0 and r.stdout == "" and not out.exists()

    def test_an_id_the_run_does_not_produce_exits_2(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        ids = tmp_path / "ids.txt"
        ids.write_text("a:one\na:typo\n", encoding="utf-8")
        r = _cli(k, d, "--output", str(tmp_path / "s.json"), "--only-ids", str(ids))
        assert r.returncode == 2 and "a:typo" in r.stderr

    def test_only_ids_cannot_combine_with_baseline_flags(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        ids = tmp_path / "ids.txt"
        ids.write_text("a:one\n", encoding="utf-8")
        r = _cli(k, d, "--upstream", "--output", str(tmp_path / "s.json"), "--only-ids", str(ids),
                 "--baseline-knowledge-dir", str(k), "--baseline-disciplines-dir", str(d))
        assert r.returncode == 2 and "--only-ids" in r.stderr


class TestFixedIdProjectDataTags:
    def test_fixed_id_project_data_is_not_project_specific(self, tmp_path: Path) -> None:
        by_id = {e["knowledge_id"]: e for e in _discipline_entries(tmp_path)}
        base = ["sdlc:discipline", "sdlc:discipline:testing"]
        assert by_id["discipline:testing:active-questions"]["tags"] == base
        assert by_id["discipline:testing:project-context"]["tags"] == [*base, "sdlc:project-context"]
        assert by_id["discipline:testing:maturity-tracker"]["tags"] == [*base, "sdlc:maturity-tracker"]
        assert by_id["discipline:testing:parking-lot-structure"]["tags"] == [
            *base, "sdlc:parking-lot-structure",
        ]
        bullet = next(e for k, e in by_id.items() if ":parking-lot:" in k)
        assert "sdlc:project-specific" in bullet["tags"]


class TestTagHonesty:
    def test_tag_with_zero_entries_exits_nonzero_and_writes_nothing(self, tmp_path: Path) -> None:
        k = tmp_path / "k"
        k.mkdir()
        (k / "bad.yaml").write_text("key: value\n- orphan\n", encoding="utf-8")
        d = tmp_path / "d"
        d.mkdir()
        out = tmp_path / "s.json"
        r = _cli(k, d, "--output", str(out), "--tag", "sdlc:project-specific")
        assert r.returncode == 1 and not out.exists() and r.stdout == ""
        assert "--tag" in r.stderr
        plain = _cli(k, d, "--output", str(out))
        assert plain.returncode == 0

    def test_tag_with_a_declined_only_tree_exits_nonzero(self, tmp_path: Path) -> None:
        k = _write_yaml_files(tmp_path, {"a": 1})
        d = tmp_path / "d"
        d.mkdir()
        manifest = _write_manifest(tmp_path / "m.json", {"ops/sdlc/knowledge/a.yaml": {}})
        r = _cli(k, d, "--output", str(tmp_path / "s.json"), "--tag", "x:y",
                 "--manifest", str(manifest))
        assert r.returncode == 1

    def test_no_manifest_ignores_the_cwd_manifest(self, tmp_path: Path) -> None:
        k = _write_yaml_files(tmp_path, {"a": 1})
        d = tmp_path / "d"
        d.mkdir()
        _write_manifest(tmp_path / ".sdlc-manifest.json", {"ops/sdlc/knowledge/a.yaml": {}})
        with_manifest = _cli(k, d, "--dry-run", cwd=tmp_path)
        without = _cli(k, d, "--dry-run", "--no-manifest", cwd=tmp_path)
        assert "Total entries: 0" in with_manifest.stderr
        assert "Total entries: 1" in without.stderr

    def test_no_manifest_conflicts_with_manifest(self, tmp_path: Path) -> None:
        k = _write_yaml_files(tmp_path, {"a": 1})
        d = tmp_path / "d"
        d.mkdir()
        r = _cli(k, d, "--dry-run", "--no-manifest", "--manifest", str(tmp_path / "m.json"))
        assert r.returncode == 2


class TestPortModeTagNew:
    def _trees(self, tmp_path: Path) -> tuple[Path, Path, Path, Path]:
        base_k, tgt_k = tmp_path / "bk", tmp_path / "tk"
        base_d, tgt_d = tmp_path / "bd", tmp_path / "td"
        base_d.mkdir(parents=True)
        tgt_d.mkdir(parents=True)
        _nested(base_k, "a", {"upstream": "u", "edited": "old"})
        _nested(tgt_k, "a", {"upstream": "u", "edited": "project edit", "mine": "added by project"})
        return base_k, base_d, tgt_k, tgt_d

    def _run(self, tmp_path: Path, *extra: str) -> tuple[subprocess.CompletedProcess[str], Path]:
        base_k, base_d, tgt_k, tgt_d = self._trees(tmp_path)
        out = tmp_path / "seed.json"
        r = _cli(tgt_k, tgt_d, "--output", str(out), "--baseline-knowledge-dir", str(base_k),
                 "--baseline-disciplines-dir", str(base_d), *extra)
        return r, out

    def test_tag_new_tags_exactly_the_ids_the_baseline_lacks(self, tmp_path: Path) -> None:
        r, out = self._run(tmp_path, "--tag-new", "sdlc:project-specific")
        assert r.returncode == 0, r.stderr
        es = {e["knowledge_id"]: e for e in json.loads(out.read_text())["entries"]}
        assert set(es) == {"sub:a:upstream", "sub:a:edited", "sub:a:mine"}
        tagged = {i for i, e in es.items() if "sdlc:project-specific" in e["tags"]}
        assert tagged == {"sub:a:mine"}

    def test_port_mode_writes_every_entry_and_no_delta_file(self, tmp_path: Path) -> None:
        r, out = self._run(tmp_path, "--tag-new", "sdlc:project-specific")
        assert r.stdout.split() == [str(out)]
        assert not out.with_name("seed.delta.json").exists()

    def test_tag_new_is_repeatable_and_reserved_tags_are_refused(self, tmp_path: Path) -> None:
        _, out = self._run(tmp_path, "--tag-new", "x:one", "--tag-new", "x:two")
        e = next(e for e in json.loads(out.read_text())["entries"] if e["knowledge_id"] == "sub:a:mine")
        assert {"x:one", "x:two"} <= set(e["tags"])
        bad, _ = self._run(tmp_path / "again", "--tag-new", "sdlc:deprecated")
        assert bad.returncode == 2 and "reserved" in bad.stderr

    def test_tag_new_skips_fixed_id_project_data(self, tmp_path: Path) -> None:
        base_k, base_d, tgt_k, tgt_d = self._trees(tmp_path)
        (base_d / "testing.md").write_text("# T\n\n## Summary\n\nx\n", encoding="utf-8")
        (tgt_d / "testing.md").write_text(
            "# T\n\n## Summary\n\nx\n\n## Active Questions\n\n- q\n\n## Parking Lot\n\n"
            "*n*\n\n- **mine.** bullet\n", encoding="utf-8")
        out = tmp_path / "s.json"
        r = _cli(tgt_k, tgt_d, "--output", str(out), "--baseline-knowledge-dir", str(base_k),
                 "--baseline-disciplines-dir", str(base_d), "--tag-new", "x:new")
        assert r.returncode == 0, r.stderr
        es = {e["knowledge_id"]: e for e in json.loads(out.read_text())["entries"]}
        assert "x:new" not in es["discipline:testing:active-questions"]["tags"]
        assert "x:new" in next(e for k, e in es.items() if ":parking-lot:" in k)["tags"]
        assert "x:new" in es["sub:a:mine"]["tags"]

    def test_baseline_flags_in_port_mode_need_tag_new(self, tmp_path: Path) -> None:
        r, _ = self._run(tmp_path)
        assert r.returncode == 2 and "--tag-new" in r.stderr

    def test_tag_new_needs_the_baseline_flags_and_refuses_upstream(self, tmp_path: Path) -> None:
        k = _write_yaml_files(tmp_path, {"a": 1})
        d = tmp_path / "d"
        d.mkdir()
        no_base = _cli(k, d, "--output", str(tmp_path / "s.json"), "--tag-new", "x:y")
        assert no_base.returncode == 2 and "--baseline" in no_base.stderr
        base_k, base_d, tgt_k, tgt_d = self._trees(tmp_path / "t")
        up = _cli(tgt_k, tgt_d, "--upstream", "--output", str(tmp_path / "u.json"),
                  "--baseline-knowledge-dir", str(base_k),
                  "--baseline-disciplines-dir", str(base_d), "--tag-new", "x:y")
        assert up.returncode == 2 and "--upstream" in up.stderr

    def test_tag_new_fails_closed_on_a_missing_or_empty_baseline(self, tmp_path: Path) -> None:
        _, base_d, tgt_k, tgt_d = self._trees(tmp_path)
        out = tmp_path / "s.json"
        empty_k, empty_d = tmp_path / "ek", tmp_path / "ed"
        empty_k.mkdir()
        empty_d.mkdir()
        for bk, bd, text in ((tmp_path / "nope", base_d, "does not exist"),
                             (empty_k, empty_d, "no entries")):
            r = _cli(tgt_k, tgt_d, "--output", str(out), "--baseline-knowledge-dir", str(bk),
                     "--baseline-disciplines-dir", str(bd), "--tag-new", "x:y")
            assert r.returncode == 2 and text in r.stderr
            assert not out.exists()


# Rendering is a stored-data contract. The classifier decides "the project edited
# this entry" by comparing the stored text with the text a previous upstream
# version rendered, so any change here makes every later upstream change look like
# a conflict. Change these strings only together with a plan for that migration.
class TestGoldenOutput:
    def _entries(self, tmp_path: Path) -> dict[str, dict[str, Any]]:
        k = tmp_path / "k"
        (k / "search").mkdir(parents=True)
        (k / "a-entries.yaml").write_text(
            'entries:\n  - topic: "Entry topic"\n    guidance: "Entry guidance."\n'
            '    rationale: "Because."\n    examples:\n      - one\n      - two\n',
            encoding="utf-8")
        (k / "b-gotchas.yaml").write_text(
            'gotchas:\n  - id: gotcha-1\n    severity: high\n    title: "Gotcha title"\n'
            '    symptom: "It breaks"\n    cause: "Bad init"\n    resolution: "Call init"\n'
            '    prevention: "Assert"\n    applies_to: "api"\n', encoding="utf-8")
        (k / "c-rules.yaml").write_text(
            'rules:\n  - rule_id: rule-1\n    title: "Rule title"\n    description: "Do the thing."\n'
            '    rationale: "Why."\n    checklist:\n      - "check a"\n    severity: high\n'
            '    source: "A paper"\n', encoding="utf-8")
        (k / "d-method.yaml").write_text(
            'approach:\n  step: "do \u2014 this"\n  list:\n    - alpha\n    - "it\'s: tricky"\n',
            encoding="utf-8")
        (k / "search" / "e-doc.md").write_text("# Doc Title\n\nBody line.\n", encoding="utf-8")
        d = tmp_path / "d"
        d.mkdir()
        (d / "testing.md").write_text(
            "# Testing\n\n## Summary\n\nFramework text.\n\n## Parking Lot\n\n*Instruction.*\n\n"
            "### Seeded\n\n- **A.** bullet\n  more\n", encoding="utf-8")
        return {e["knowledge_id"]: e for e in _script._collect(k, d, upstream=True).entries}

    def test_entries_pattern(self, tmp_path: Path) -> None:
        e = self._entries(tmp_path)["a-entries:entry_topic"]
        assert e["content"] == "Entry guidance.\n\n**Rationale:** Because.\n\n**Examples:**\n- one\n- two\n"
        assert e["tags"] == ["sdlc:knowledge", "sdlc:pattern:entries"]

    def test_gotchas_pattern(self, tmp_path: Path) -> None:
        e = self._entries(tmp_path)["gotcha-1"]
        assert e["content"] == (
            "Severity: high\nSymptom: It breaks\nCause: Bad init\nResolution: Call init\n"
            "Prevention: Assert\n\n**Applies_To:** api"
        )

    def test_rules_pattern(self, tmp_path: Path) -> None:
        e = self._entries(tmp_path)["rule-1"]
        assert e["content"] == (
            "### Rule title\nDo the thing.\n\n**Rationale:** Why.\n\n**Checklist:**\n- check a\n"
            "\n\n**Severity:** high\n\n**Source:** A paper"
        )

    def test_methodology_pattern(self, tmp_path: Path) -> None:
        e = self._entries(tmp_path)["d-method:approach"]
        assert e["content"] == (
            "### approach\nstep: do \u2014 this\nlist:\n- alpha\n- |-\n  it's: tricky\n"
        )

    def test_document(self, tmp_path: Path) -> None:
        e = self._entries(tmp_path)["search:e-doc"]
        assert e["content"] == "# Doc Title\n\nBody line.\n"

    def test_discipline_framework(self, tmp_path: Path) -> None:
        e = self._entries(tmp_path)["discipline:testing:framework"]
        assert e["content"] == (
            "# Testing\n\n## Summary\n\nFramework text.\n\n## Parking Lot\n\n*Instruction.*\n"
        )

    def test_parking_lot_entry(self, tmp_path: Path) -> None:
        e = self._entries(tmp_path)["discipline:testing:parking-lot:7d8d1e54da14"]
        assert e["content"] == "- **A.** bullet\n  more"
        assert e["tags"][-2:] == ["sdlc:parking-lot", "sdlc:parking-lot-section:seeded"]


# ===========================================================================
# Round 6: target-side fail-closed, probe_entries
# ===========================================================================


class TestTargetFailsClosed:
    def _base(self, tmp_path: Path) -> tuple[Path, Path]:
        bk, bd = tmp_path / "bk", tmp_path / "bd"
        bd.mkdir(parents=True)
        _nested(bk, "a", {"x": "1"})
        return bk, bd

    def _run(self, tmp_path: Path, tk: Path, td: Path) -> subprocess.CompletedProcess[str]:
        bk, bd = self._base(tmp_path)
        return _cli(tk, td, "--upstream", "--output", str(tmp_path / "seed.json"),
                    "--baseline-knowledge-dir", str(bk), "--baseline-disciplines-dir", str(bd))

    def test_a_missing_target_directory_exits_2_and_writes_nothing(self, tmp_path: Path) -> None:
        td = tmp_path / "td"
        td.mkdir()
        r = self._run(tmp_path, tmp_path / "typo-tag" / "knowledge", td)
        assert r.returncode == 2 and "does not exist" in r.stderr and "removed" in r.stderr
        assert r.stdout == "" and not list(tmp_path.glob("seed*.json"))
        tk = tmp_path / "tk"
        _nested(tk, "a", {"x": "1"})
        r = self._run(tmp_path / "again", tk, tmp_path / "missing-disciplines")
        assert r.returncode == 2 and "does not exist" in r.stderr

    def test_a_target_that_yields_no_entries_exits_2(self, tmp_path: Path) -> None:
        tk, td = tmp_path / "tk", tmp_path / "td"
        tk.mkdir()
        td.mkdir()
        r = self._run(tmp_path, tk, td)
        assert r.returncode == 2 and "no entries" in r.stderr and "removed" in r.stderr
        assert r.stdout == "" and not list(tmp_path.glob("seed*.json"))


class TestProbeEntries:
    def test_probe_entries_are_the_full_entries_for_the_noop_and_every_probe(
        self, tmp_path: Path
    ) -> None:
        bk, tk = tmp_path / "bk", tmp_path / "tk"
        bd, td = tmp_path / "bd", tmp_path / "td"
        _stub_disciplines(bd)
        _stub_disciplines(td)
        _nested(bk, "changing", {"edit": "old"})
        _nested(tk, "changing", {"edit": "new"})
        for name in ("alpha", "beta", "gamma"):
            _nested(bk, name, {"item": name})
            _nested(tk, name, {"item": name})
        out = tmp_path / "seed.json"
        r = _cli(tk, td, "--upstream", "--output", str(out), "--tag", "x:y",
                 "--baseline-knowledge-dir", str(bk), "--baseline-disciplines-dir", str(bd))
        assert r.returncode == 0, r.stderr
        delta = json.loads(out.with_name("seed.delta.json").read_text())
        pe = delta["probe_entries"]
        ids = [e["knowledge_id"] for e in pe]
        assert ids[0] == delta["noop_entry"]["knowledge_id"]
        assert {delta["noop_entry"]["knowledge_id"], *delta["probe_ids"]} <= set(ids)
        assert len(ids) == len(set(ids))
        full = {e["knowledge_id"]: e for e in _script._collect(tk, td, upstream=True).entries}
        for e in pe:
            expected = dict(full[e["knowledge_id"]])
            expected["tags"] = [*expected["tags"], "x:y"]
            assert e == expected
        assert pe[0] == delta["noop_entry"]

    def test_probe_entries_is_empty_without_unchanged_entries(self, tmp_path: Path) -> None:
        bk, tk = tmp_path / "bk", tmp_path / "tk"
        bd, td = tmp_path / "bd", tmp_path / "td"
        _stub_disciplines(bd)
        _stub_disciplines(td)
        (td / "stub.md").write_text("# Stub\n\n## Summary\n\nchanged\n", encoding="utf-8")
        _nested(bk, "a", {"x": "old"})
        _nested(tk, "a", {"x": "new"})
        out = tmp_path / "seed.json"
        r = _cli(tk, td, "--upstream", "--output", str(out),
                 "--baseline-knowledge-dir", str(bk), "--baseline-disciplines-dir", str(bd))
        assert r.returncode == 0, r.stderr
        assert json.loads(out.with_name("seed.delta.json").read_text())["probe_entries"] == []

    def test_the_probe_premise_is_documented_honestly(self) -> None:
        doc = _script.__doc__ or ""
        assert "0.7.0" in doc and "knowledge-seed" in doc and "{stem}:{key}" in doc
        assert "manifest" in doc.lower()


# ===========================================================================
# Round 11: target parse errors, discipline-only fixed ids, status entry,
# repeated sections, oversize entry, 50 no-op candidates
# ===========================================================================


class TestTargetParseErrorsAreFatalInDeltaMode:
    def _trees(self, tmp_path: Path, bad_in: str) -> tuple[Path, Path, Path, Path]:
        bk, tk = tmp_path / "bk", tmp_path / "tk"
        bd, td = tmp_path / "bd", tmp_path / "td"
        _stub_disciplines(bd)
        _stub_disciplines(td)
        for root in (bk, tk):
            _nested(root, "good", {"x": "1"})
            _nested(root, "other", {"y": "2"})
        _nested(bk, "bad", {"z": "3"})
        _nested(tk, "bad", {"z": "3"})
        broken = (tk if bad_in == "target" else bk) / "sub" / "bad.yaml"
        broken.write_text("key: value\n- orphan\n", encoding="utf-8")
        return bk, bd, tk, td

    def _run(self, tmp_path: Path, bad_in: str, *extra: str) -> subprocess.CompletedProcess[str]:
        bk, bd, tk, td = self._trees(tmp_path, bad_in)
        return _cli(tk, td, "--upstream", "--output", str(tmp_path / "seed.json"),
                    "--baseline-knowledge-dir", str(bk), "--baseline-disciplines-dir", str(bd), *extra)

    def test_a_target_yaml_error_exits_2_and_names_the_file(self, tmp_path: Path) -> None:
        r = self._run(tmp_path, "target")
        assert r.returncode == 2 and "sub/bad.yaml" in r.stderr
        assert r.stdout == "" and not list(tmp_path.glob("seed*.json"))

    def test_an_unparsed_pattern_in_the_target_exits_2(self, tmp_path: Path) -> None:
        bk, bd, tk, td = self._trees(tmp_path, "baseline")
        (bk / "sub" / "bad.yaml").write_text("entries:\n  - topic: t\n    guidance: g\n", encoding="utf-8")
        (tk / "sub" / "bad.yaml").write_text("rules:\n  - description: no id\n", encoding="utf-8")
        r = _cli(tk, td, "--upstream", "--output", str(tmp_path / "seed.json"),
                 "--baseline-knowledge-dir", str(bk), "--baseline-disciplines-dir", str(bd))
        assert r.returncode == 2 and "sub/bad.yaml" in r.stderr

    def test_a_malformed_baseline_file_stays_a_warning(self, tmp_path: Path) -> None:
        r = self._run(tmp_path, "baseline")
        assert r.returncode == 0, r.stderr
        assert "WARNING" in r.stderr

    def test_port_mode_keeps_a_bad_file_as_a_warning(self, tmp_path: Path) -> None:
        _, _, tk, td = self._trees(tmp_path, "target")
        r = _cli(tk, td, "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 0, r.stderr


class TestFixedIdExceptionIsDisciplineOnly:
    def test_a_knowledge_document_named_like_fixed_data_is_still_tagged(
        self, tmp_path: Path
    ) -> None:
        bk, tk = tmp_path / "bk", tmp_path / "tk"
        bd, td = tmp_path / "bd", tmp_path / "td"
        bd.mkdir()
        td.mkdir()
        _nested(bk, "a", {"x": "1"})
        _nested(tk, "a", {"x": "1"})
        for root in (tk,):
            (root / "design").mkdir()
            (root / "design" / "project-context.md").write_text("# Mine\n", encoding="utf-8")
            (root / "design" / "status.md").write_text("# Mine\n", encoding="utf-8")
        (td / "testing.md").write_text(
            "# T\n\n**Status**: Active\n\n## Active Questions\n\n- q\n", encoding="utf-8")
        out = tmp_path / "seed.json"
        r = _cli(tk, td, "--output", str(out), "--baseline-knowledge-dir", str(bk),
                 "--baseline-disciplines-dir", str(bd), "--tag-new", "x:new")
        assert r.returncode == 0, r.stderr
        es = {e["knowledge_id"]: e for e in json.loads(out.read_text())["entries"]}
        assert "x:new" in es["design:project-context"]["tags"]
        assert "x:new" in es["design:status"]["tags"]
        assert "x:new" not in es["discipline:testing:active-questions"]["tags"]
        assert "x:new" not in es["discipline:testing:status"]["tags"]


_STATUS_TEXT = """# Testing Discipline

**Status**: Active - assessed by the project

## Summary

Framework text.

## Parking Lot

*Instruction.*

### Seeded

- **A.** bullet
"""


class TestStatusEntry:
    def test_the_status_line_leaves_the_framework_for_its_own_entry(self, tmp_path: Path) -> None:
        for upstream in (False, True):
            es = {e["knowledge_id"]: e for e in
                  _discipline_entries(tmp_path, _STATUS_TEXT, upstream=upstream)}
            assert "**Status**" not in es["discipline:testing:framework"]["content"]
            assert "Framework text." in es["discipline:testing:framework"]["content"]
            st = es["discipline:testing:status"]
            assert st["content"] == "**Status**: Active - assessed by the project\n"
            assert st["tags"] == ["sdlc:discipline", "sdlc:discipline:testing"]
            assert st["title"] == "Testing status"

    def test_the_bold_colon_variant_is_recognised(self, tmp_path: Path) -> None:
        text = "# D\n\n**Status:** Active parking lot\n\n## Summary\n\nx\n"
        es = {e["knowledge_id"]: e for e in _discipline_entries(tmp_path, text)}
        assert es["discipline:testing:status"]["content"] == "**Status:** Active parking lot\n"
        assert "Status" not in es["discipline:testing:framework"]["content"]

    def test_a_file_without_a_status_line_has_no_status_entry(self, tmp_path: Path) -> None:
        ids = [e["knowledge_id"] for e in _discipline_entries(tmp_path, "# D\n\n## Summary\n\nx\n")]
        assert "discipline:testing:status" not in ids

    def test_every_line_is_still_kept(self, tmp_path: Path) -> None:
        entries = _discipline_entries(tmp_path, _STATUS_TEXT)
        have = {ln.rstrip() for e in entries for ln in e["content"].splitlines()}
        assert [ln for ln in _STATUS_TEXT.splitlines() if ln.strip() and ln.rstrip() not in have] == []

    def _delta(self, tmp_path: Path, base_text: str, target_text: str) -> dict[str, Any]:
        bk, tk = tmp_path / "bk", tmp_path / "tk"
        bd, td = tmp_path / "bd", tmp_path / "td"
        bd.mkdir()
        td.mkdir()
        for root in (bk, tk):
            _nested(root, "a", {"x": "1"})
            _nested(root, "b", {"y": "2"})
        (bd / "testing.md").write_text(base_text, encoding="utf-8")
        (td / "testing.md").write_text(target_text, encoding="utf-8")
        out = tmp_path / "seed.json"
        r = _cli(tk, td, "--upstream", "--output", str(out), "--baseline-knowledge-dir", str(bk),
                 "--baseline-disciplines-dir", str(bd))
        assert r.returncode == 0, r.stderr
        delta: dict[str, Any] = json.loads(out.with_name("seed.delta.json").read_text())
        return delta

    def test_a_changed_status_line_never_appears_in_the_delta(self, tmp_path: Path) -> None:
        delta = self._delta(tmp_path, _STATUS_TEXT,
                            _STATUS_TEXT.replace("Active - assessed", "Done - assessed")
                            .replace("Framework text.", "Framework text, revised."))
        changed = [c["id"] for c in delta["changed"]]
        assert changed == ["discipline:testing:framework"]
        assert "discipline:testing:status" not in delta["new"] + changed + delta["removed"]

    def test_a_new_status_line_is_not_new_and_the_structure_entry_is_excluded(
        self, tmp_path: Path
    ) -> None:
        base = "# D\n\n## Parking Lot\n\n*n*\n\n- **A.** one\n"
        target = "# D\n\n**Status**: Active\n\n## Parking Lot\n\n*n*\n\n### New heading\n\n- **A.** one\n"
        delta = self._delta(tmp_path, base, target)
        for key in ("new", "removed"):
            assert not any(i.endswith((":status", ":parking-lot-structure")) for i in delta[key])
        assert not any(c["id"].endswith((":status", ":parking-lot-structure")) for c in delta["changed"])
        every = delta["new"] + [c["id"] for c in delta["changed"]] + [
            e["knowledge_id"] for e in delta["probe_entries"]]
        assert not any(i.endswith((":status", ":parking-lot-structure")) for i in every)


class TestRepeatedProjectSections:
    def test_two_project_context_sections_are_both_kept_in_file_order(self, tmp_path: Path) -> None:
        text = ("# D\n\n## Project Context\n\nfirst context\n\n## Summary\n\nx\n\n"
                "## Project Context\n\nsecond context\n")
        pc = next(e for e in _discipline_entries(tmp_path, text)
                  if e["knowledge_id"].endswith(":project-context"))
        assert pc["content"].index("first context") < pc["content"].index("second context")
        assert pc["content"].count("## Project Context") == 2

    def test_two_active_questions_sections_are_both_kept(self, tmp_path: Path) -> None:
        text = "# D\n\n## Active Questions\n\n- q1\n\n## Summary\n\nx\n\n## Active Questions\n\n- q2\n"
        aq = next(e for e in _discipline_entries(tmp_path, text)
                  if e["knowledge_id"].endswith(":active-questions"))
        assert "- q1" in aq["content"] and "- q2" in aq["content"]


class TestFiftyNoopCandidates:
    def test_probe_entries_hold_up_to_fifty_unchanged_entries_noop_first(
        self, tmp_path: Path
    ) -> None:
        bk, tk = tmp_path / "bk", tmp_path / "tk"
        bd, td = tmp_path / "bd", tmp_path / "td"
        _stub_disciplines(bd)
        _stub_disciplines(td)
        _nested(bk, "changing", {"edit": "old"})
        _nested(tk, "changing", {"edit": "new"})
        for root in (bk, tk):
            for i in range(60):
                _nested(root, f"u{i:02d}", {"item": f"stable {i}"})
        out = tmp_path / "seed.json"
        r = _cli(tk, td, "--upstream", "--output", str(out), "--baseline-knowledge-dir", str(bk),
                 "--baseline-disciplines-dir", str(bd))
        assert r.returncode == 0, r.stderr
        delta = json.loads(out.with_name("seed.delta.json").read_text())
        ids = [e["knowledge_id"] for e in delta["probe_entries"]]
        assert len(ids) == 50 and len(set(ids)) == 50
        assert ids[0] == delta["noop_entry"]["knowledge_id"]
        assert set(delta["probe_ids"]) <= set(ids)
        assert len(delta["probe_ids"]) == 10


# ===========================================================================
# Round 14: origin-based project data, unparsed ids, unreadable documents
# ===========================================================================


class TestProjectDataIsKeyedOnOrigin:
    def _trees(self, tmp_path: Path, doc_old: str, doc_new: str) -> tuple[Path, Path, Path, Path]:
        bk, tk = tmp_path / "bk", tmp_path / "tk"
        bd, td = tmp_path / "bd", tmp_path / "td"
        bd.mkdir()
        td.mkdir()
        for root in (bk, tk):
            _nested(root, "keep", {"x": "1"})
        (bk / "discipline" / "gate").mkdir(parents=True)
        (tk / "discipline" / "gate").mkdir(parents=True)
        (bk / "discipline" / "gate" / "status.md").write_text(doc_old, encoding="utf-8")
        (tk / "discipline" / "gate" / "status.md").write_text(doc_new, encoding="utf-8")
        (bd / "other.md").write_text("# O\n\n**Status**: Active\n\n## Summary\n\nx\n", encoding="utf-8")
        (td / "other.md").write_text("# O\n\n**Status**: Done\n\n## Summary\n\nx\n", encoding="utf-8")
        return bk, bd, tk, td

    # The discipline: id namespace is reserved (round 18): a knowledge document whose
    # path spells such an id is refused, not treated as ordinary knowledge.
    def test_a_knowledge_document_spelled_like_project_data_is_refused_in_a_delta(
        self, tmp_path: Path
    ) -> None:
        bk, bd, tk, td = self._trees(tmp_path, "# old\n", "# new\n")
        out = tmp_path / "seed.json"
        r = _cli(tk, td, "--upstream", "--output", str(out), "--baseline-knowledge-dir", str(bk),
                 "--baseline-disciplines-dir", str(bd))
        assert r.returncode == 1 and "discipline:gate:status" in r.stderr
        assert not out.exists()

    def test_tag_new_in_port_mode_refuses_it_too(self, tmp_path: Path) -> None:
        bk, bd, tk, td = self._trees(tmp_path, "# x\n", "# x\n")
        out = tmp_path / "s.json"
        r = _cli(tk, td, "--output", str(out), "--baseline-knowledge-dir", str(bk),
                 "--baseline-disciplines-dir", str(bd), "--tag-new", "x:new")
        assert r.returncode == 1 and "discipline/gate/status.md" in r.stderr
        assert not out.exists()


class TestUnparsedIdsAreNotMalformedFiles:
    def test_a_valid_explicit_rule_id_ending_in_unparsed_is_not_fatal(self, tmp_path: Path) -> None:
        bk, tk = tmp_path / "bk", tmp_path / "tk"
        bd, td = tmp_path / "bd", tmp_path / "td"
        _stub_disciplines(bd)
        _stub_disciplines(td)
        for root, text in ((bk, "old"), (tk, "new")):
            (root / "sub").mkdir(parents=True)
            (root / "sub" / "r.yaml").write_text(
                f"rules:\n  - rule_id: parser:unparsed\n    title: T\n    description: {text}\n",
                encoding="utf-8")
            _nested(root, "keep", {"x": "1"})
        out = tmp_path / "seed.json"
        r = _cli(tk, td, "--upstream", "--output", str(out), "--baseline-knowledge-dir", str(bk),
                 "--baseline-disciplines-dir", str(bd))
        assert r.returncode == 0, r.stderr
        assert "parser:unparsed" in [c["id"] for c in
                                     json.loads(out.with_name("seed.delta.json").read_text())["changed"]]

    def test_real_unparsed_items_are_still_fatal(self, tmp_path: Path) -> None:
        bk, tk = tmp_path / "bk", tmp_path / "tk"
        bd, td = tmp_path / "bd", tmp_path / "td"
        _stub_disciplines(bd)
        _stub_disciplines(td)
        for root in (bk, tk):
            _nested(root, "keep", {"x": "1"})
        (bk / "sub" / "r.yaml").write_text("rules:\n  - rule_id: ok\n    title: T\n    description: d\n")
        (tk / "sub" / "r.yaml").write_text("rules:\n  - description: no id\n")
        r = _cli(tk, td, "--upstream", "--output", str(tmp_path / "s.json"),
                 "--baseline-knowledge-dir", str(bk), "--baseline-disciplines-dir", str(bd))
        assert r.returncode == 2 and "sub/r.yaml" in r.stderr


class TestUnreadableTargetDocumentsAreFatalInDeltaMode:
    def _trees(self, tmp_path: Path, bad_side: str, name: str) -> tuple[Path, Path, Path, Path]:
        bk, tk = tmp_path / "bk", tmp_path / "tk"
        bd, td = tmp_path / "bd", tmp_path / "td"
        bd.mkdir()
        td.mkdir()
        for root in (bk, tk):
            _nested(root, "keep", {"x": "1"})
            (root / "doc.md").write_text("# fine\n", encoding="utf-8")
        (bd / "d.md").write_text("# D\n\n## Summary\n\nx\n", encoding="utf-8")
        (td / "d.md").write_text("# D\n\n## Summary\n\nx\n", encoding="utf-8")
        bad_root = tk if bad_side == "target" else bk
        (bad_root / name).write_bytes(b"\xff\xfe not utf-8 \x80")
        return bk, bd, tk, td

    def _run(self, tmp_path: Path, bad_side: str, name: str, *extra: str) -> subprocess.CompletedProcess[str]:
        bk, bd, tk, td = self._trees(tmp_path, bad_side, name)
        return _cli(tk, td, "--upstream", "--output", str(tmp_path / "seed.json"),
                    "--baseline-knowledge-dir", str(bk), "--baseline-disciplines-dir", str(bd), *extra)

    def test_an_undecodable_target_markdown_document_exits_2_and_names_it(self, tmp_path: Path) -> None:
        for bad_name in ("doc.md", "sub/other.md"):
            (tmp_path / bad_name.replace("/", "_")).mkdir(exist_ok=True)
            r = self._run(tmp_path / bad_name.replace("/", "_"), "target", bad_name)
            assert r.returncode == 2 and bad_name in r.stderr and "Traceback" not in r.stderr
            assert r.stdout == ""

    def test_an_undecodable_target_yaml_file_exits_2_without_a_traceback(self, tmp_path: Path) -> None:
        r = self._run(tmp_path, "target", "sub/bad.yaml")
        assert r.returncode == 2 and "sub/bad.yaml" in r.stderr and "Traceback" not in r.stderr

    def test_an_undecodable_target_discipline_file_exits_2(self, tmp_path: Path) -> None:
        bk, bd, tk, td = self._trees(tmp_path, "baseline", "unused.md")
        (td / "bad.md").write_bytes(b"\xff\xfe broken")
        r = _cli(tk, td, "--upstream", "--output", str(tmp_path / "s.json"),
                 "--baseline-knowledge-dir", str(bk), "--baseline-disciplines-dir", str(bd))
        assert r.returncode == 2 and "bad.md" in r.stderr

    def test_an_undecodable_baseline_document_stays_a_warning(self, tmp_path: Path) -> None:
        r = self._run(tmp_path, "baseline", "doc.md")
        assert r.returncode == 0, r.stderr
        assert "WARNING" in r.stderr and "Traceback" not in r.stderr

    def test_port_mode_keeps_an_undecodable_file_as_a_warning_not_a_crash(
        self, tmp_path: Path
    ) -> None:
        _, _, tk, td = self._trees(tmp_path, "target", "doc.md")
        r = _cli(tk, td, "--output", str(tmp_path / "s.json"))
        assert r.returncode == 0 and "Traceback" not in r.stderr and "WARNING" in r.stderr


# ===========================================================================
# Round 15: fatal in every upstream mode, dangling symlinks, kind-keyed exclusion,
# framework_ids
# ===========================================================================


class TestUpstreamAlwaysFailsOnUnreadableTrees:
    def _tree(self, tmp_path: Path) -> tuple[Path, Path]:
        k, d = tmp_path / "k", tmp_path / "d"
        _nested(k, "good", {"x": "1"})
        (k / "doc.md").write_text("# fine\n", encoding="utf-8")
        d.mkdir()
        (d / "ok.md").write_text("# D\n\n## Summary\n\nx\n", encoding="utf-8")
        return k, d

    def test_plain_upstream_exits_2_on_an_undecodable_document_and_writes_nothing(
        self, tmp_path: Path
    ) -> None:
        for name in ("sub/doc2.md", "sub/bad.yaml"):
            case = tmp_path / name.replace("/", "_")
            k, d = self._tree(case)
            (k / name).write_bytes(b"\xff\xfe not utf-8 \x80")
            r = _cli(k, d, "--upstream", "--output", str(case / "seed.json"))
            assert r.returncode == 2 and name in r.stderr and "Traceback" not in r.stderr
            assert r.stdout == "" and not list(case.glob("seed*.json"))

    def test_plain_upstream_exits_2_on_an_undecodable_discipline_file(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        (d / "broken.md").write_bytes(b"\xff\xfe broken")
        r = _cli(k, d, "--upstream", "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 2 and "broken.md" in r.stderr and not (tmp_path / "seed.json").exists()

    def test_port_mode_still_only_warns(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        (k / "sub" / "doc2.md").write_bytes(b"\xff\xfe not utf-8 \x80")
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 0, r.stderr
        assert "WARNING" in r.stderr and (tmp_path / "seed.json").exists()

    def test_a_dry_run_in_upstream_mode_fails_too(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        (k / "doc.md").write_bytes(b"\xff\xfe")
        assert _cli(k, d, "--upstream", "--dry-run").returncode == 2


class TestDanglingSymlinks:
    def _tree(self, tmp_path: Path) -> tuple[Path, Path]:
        k, d = tmp_path / "k", tmp_path / "d"
        _nested(k, "good", {"x": "1"})
        d.mkdir()
        (d / "ok.md").write_text("# D\n\n## Summary\n\nx\n", encoding="utf-8")
        return k, d

    def test_a_dangling_knowledge_symlink_is_fatal_in_upstream_mode(self, tmp_path: Path) -> None:
        import os

        k, d = self._tree(tmp_path)
        os.symlink(k / "does-not-exist.md", k / "link.md")
        r = _cli(k, d, "--upstream", "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 2 and "link.md" in r.stderr and "symlink" in r.stderr
        assert not (tmp_path / "seed.json").exists()

    def test_a_dangling_discipline_symlink_is_fatal_in_upstream_mode(self, tmp_path: Path) -> None:
        import os

        k, d = self._tree(tmp_path)
        os.symlink(d / "gone.md", d / "linked.md")
        r = _cli(k, d, "--upstream", "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 2 and "linked.md" in r.stderr

    def test_a_delta_never_reports_a_dangling_file_as_removed(self, tmp_path: Path) -> None:
        import os

        bk, tk = tmp_path / "bk", tmp_path / "tk"
        bd, td = tmp_path / "bd", tmp_path / "td"
        bd.mkdir()
        td.mkdir()
        for root in (bk, tk):
            _nested(root, "good", {"x": "1"})
        (bk / "doc.md").write_text("# there\n", encoding="utf-8")
        os.symlink(tk / "missing-target.md", tk / "doc.md")
        r = _cli(tk, td, "--upstream", "--output", str(tmp_path / "seed.json"),
                 "--baseline-knowledge-dir", str(bk), "--baseline-disciplines-dir", str(bd))
        assert r.returncode == 2 and "doc.md" in r.stderr

    def test_port_mode_only_warns_about_a_dangling_symlink(self, tmp_path: Path) -> None:
        import os

        k, d = self._tree(tmp_path)
        os.symlink(k / "nope.md", k / "link.md")
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 0, r.stderr

    def test_a_working_symlink_is_not_a_problem(self, tmp_path: Path) -> None:
        import os

        k, d = self._tree(tmp_path)
        (k / "real.md").write_text("# real\n", encoding="utf-8")
        os.symlink(k / "real.md", k / "alias.md")
        assert _cli(k, d, "--upstream", "--output", str(tmp_path / "seed.json")).returncode == 0


_LONG_STEM = "s" * 90


class TestExclusionFollowsKindNotIdShape:
    def _delta_trees(self, tmp_path: Path) -> tuple[Path, Path, Path, Path]:
        bk, tk = tmp_path / "bk", tmp_path / "tk"
        bd, td = tmp_path / "bd", tmp_path / "td"
        bd.mkdir()
        td.mkdir()
        for root in (bk, tk):
            _nested(root, "keep", {"x": "1"})
        body = "# T\n\n**Status**: {}\n\n## Summary\n\n{}\n\n## Parking Lot\n\n*n*\n\n### S\n\n- **a.** one\n"
        (bd / f"{_LONG_STEM}.md").write_text(body.format("Active", "x"), encoding="utf-8")
        (td / f"{_LONG_STEM}.md").write_text(body.format("Done", "y"), encoding="utf-8")
        return bk, bd, tk, td

    def test_a_hashed_discipline_id_is_really_hashed_here(self, tmp_path: Path) -> None:
        _, _, tk, td = self._delta_trees(tmp_path)
        ids = [e["knowledge_id"] for e in _script._collect(tk, td, upstream=True).entries]
        assert not any(i.endswith(":status") for i in ids)
        assert all(len(i) <= 100 for i in ids)

    def test_the_status_of_a_long_stem_never_enters_the_delta(self, tmp_path: Path) -> None:
        bk, bd, tk, td = self._delta_trees(tmp_path)
        entries = _script._collect(tk, td, upstream=True).entries
        status_id = next(e["knowledge_id"] for e in entries if e["content"].startswith("**Status**"))
        structure_id = next(e["knowledge_id"] for e in entries if e["content"].startswith("### S"))
        out = tmp_path / "seed.json"
        r = _cli(tk, td, "--upstream", "--output", str(out), "--baseline-knowledge-dir", str(bk),
                 "--baseline-disciplines-dir", str(bd))
        assert r.returncode == 0, r.stderr
        delta = json.loads(out.with_name("seed.delta.json").read_text())
        everything = (delta["new"] + [c["id"] for c in delta["changed"]] + delta["removed"]
                      + [e["knowledge_id"] for e in delta["probe_entries"]])
        assert status_id not in everything and structure_id not in everything
        assert [c["id"] for c in delta["changed"]] == [
            next(e["knowledge_id"] for e in entries if e["content"].startswith("# T"))]

    def test_tag_new_skips_the_hashed_status_entry(self, tmp_path: Path) -> None:
        bk, bd, tk, td = self._delta_trees(tmp_path)
        (bd / f"{_LONG_STEM}.md").unlink()
        out = tmp_path / "s.json"
        r = _cli(tk, td, "--output", str(out), "--baseline-knowledge-dir", str(bk),
                 "--baseline-disciplines-dir", str(bd), "--tag-new", "x:new")
        assert r.returncode == 0, r.stderr
        es = json.loads(out.read_text())["entries"]
        status = next(e for e in es if e["content"].startswith("**Status**"))
        assert "x:new" not in status["tags"]
        assert any("x:new" in e["tags"] for e in es if e["content"].startswith("- **a.**"))


class TestFrameworkIds:
    def _run(self, tmp_path: Path, stems: list[str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        bk, tk = tmp_path / "bk", tmp_path / "tk"
        bd, td = tmp_path / "bd", tmp_path / "td"
        _stub_disciplines(bd)
        _stub_disciplines(td)
        for root in (bk, tk):
            _nested(root, "keep", {"x": "1"})
        for stem in stems:
            (bd / f"{stem}.md").write_text("# T\n\n## Summary\n\nold\n", encoding="utf-8")
            (td / f"{stem}.md").write_text("# T\n\n## Summary\n\nnew\n", encoding="utf-8")
        out = tmp_path / "seed.json"
        r = _cli(tk, td, "--upstream", "--output", str(out), "--baseline-knowledge-dir", str(bk),
                 "--baseline-disciplines-dir", str(bd))
        assert r.returncode == 0, r.stderr
        delta = json.loads(out.with_name("seed.delta.json").read_text())
        return delta, _script._collect(tk, td, upstream=True).entries

    def test_framework_ids_maps_each_stem_to_the_id_the_extractor_produced(
        self, tmp_path: Path
    ) -> None:
        delta, entries = self._run(tmp_path, ["testing", "team+tools", _LONG_STEM])
        ids = delta["framework_ids"]
        assert set(ids) == {"stub", "testing", "team+tools", _LONG_STEM}
        assert ids["testing"] == "discipline:testing:framework"
        assert ids["team+tools"] == "discipline:team-tools:framework"
        fw = {e["source_path"]: e["knowledge_id"] for e in entries if e["content"].startswith("# T")}
        assert ids[_LONG_STEM] == fw[f"{_LONG_STEM}.md"] and len(ids[_LONG_STEM]) <= 100
        assert ids[_LONG_STEM] != f"discipline:{_LONG_STEM}:framework"
        assert ids["team+tools"] in [c["id"] for c in delta["changed"]]

    def test_framework_ids_lists_only_the_disciplines_present(self, tmp_path: Path) -> None:
        delta, _ = self._run(tmp_path, [])
        assert delta["framework_ids"] == {"stub": "discipline:stub:framework"}


# ===========================================================================
# Round 16: target directories in every upstream mode, baseline symlinks, scan scope
# ===========================================================================


def _stub_disciplines(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "stub.md").write_text("# Stub\n\n## Summary\n\nx\n", encoding="utf-8")
    return root


class TestUpstreamTargetDirectories:
    def _tree(self, tmp_path: Path) -> tuple[Path, Path]:
        k = tmp_path / "k"
        _nested(k, "good", {"x": "1"})
        return k, _stub_disciplines(tmp_path / "d")

    def _plain(self, k: Path, d: Path, out: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return _cli(k, d, "--upstream", "--output", str(out), *extra)

    def test_a_dangling_disciplines_symlink_exits_2_in_plain_upstream(self, tmp_path: Path) -> None:
        import os

        k, _ = self._tree(tmp_path)
        broken = tmp_path / "broken-disciplines"
        os.symlink(tmp_path / "nowhere", broken)
        out = tmp_path / "seed.json"
        r = self._plain(k, broken, out)
        assert r.returncode == 2 and "--disciplines-dir" in r.stderr and "Traceback" not in r.stderr
        assert r.stdout == "" and not out.exists()

    def test_a_missing_knowledge_dir_exits_2_in_plain_upstream(self, tmp_path: Path) -> None:
        _, d = self._tree(tmp_path)
        r = self._plain(tmp_path / "no-knowledge", d, tmp_path / "seed.json")
        assert r.returncode == 2 and "--knowledge-dir" in r.stderr and "does not exist" in r.stderr

    def test_a_symlink_resolving_outside_the_tree_counts_as_not_a_real_directory(
        self, tmp_path: Path
    ) -> None:
        import os

        k, _ = self._tree(tmp_path)
        outside = _stub_disciplines(tmp_path / "elsewhere" / "real-disciplines")
        tree = tmp_path / "checkout"
        tree.mkdir()
        os.symlink(outside, tree / "disciplines")
        r = self._plain(k, tree / "disciplines", tmp_path / "seed.json")
        assert r.returncode == 2 and "--disciplines-dir" in r.stderr and "outside" in r.stderr

    def test_a_symlink_that_stays_inside_the_tree_is_accepted(self, tmp_path: Path) -> None:
        import os

        k, _ = self._tree(tmp_path)
        tree = tmp_path / "checkout"
        _stub_disciplines(tree / "real")
        os.symlink(tree / "real", tree / "disciplines")
        r = self._plain(k, tree / "disciplines", tmp_path / "seed.json")
        assert r.returncode == 0, r.stderr

    def test_a_target_directory_that_yields_no_entries_exits_2_and_is_named(
        self, tmp_path: Path
    ) -> None:
        k, d = self._tree(tmp_path)
        empty_d = tmp_path / "empty-d"
        empty_d.mkdir()
        r = self._plain(k, empty_d, tmp_path / "s1.json")
        assert r.returncode == 2 and "--disciplines-dir" in r.stderr and "no entries" in r.stderr
        empty_k = tmp_path / "empty-k"
        empty_k.mkdir()
        r = self._plain(empty_k, d, tmp_path / "s2.json")
        assert r.returncode == 2 and "--knowledge-dir" in r.stderr and "no entries" in r.stderr
        assert not list(tmp_path.glob("s?.json"))

    def test_a_dry_run_in_upstream_mode_fails_the_same_way(self, tmp_path: Path) -> None:
        k, _ = self._tree(tmp_path)
        empty_d = tmp_path / "empty-d"
        empty_d.mkdir()
        assert _cli(k, empty_d, "--upstream", "--dry-run").returncode == 2

    def test_port_mode_is_unchanged(self, tmp_path: Path) -> None:
        k, _ = self._tree(tmp_path)
        r = _cli(k, tmp_path / "missing", "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 0, r.stderr


class TestBaselineDanglingSymlinks:
    def _trees(self, tmp_path: Path) -> tuple[Path, Path, Path, Path]:
        bk, tk = tmp_path / "bk", tmp_path / "tk"
        bd, td = _stub_disciplines(tmp_path / "bd"), _stub_disciplines(tmp_path / "td")
        for root in (bk, tk):
            _nested(root, "good", {"x": "1"})
        return bk, bd, tk, td

    def _run(self, tmp_path: Path, bk: Path, bd: Path, tk: Path, td: Path) -> subprocess.CompletedProcess[str]:
        return _cli(tk, td, "--upstream", "--output", str(tmp_path / "seed.json"),
                    "--baseline-knowledge-dir", str(bk), "--baseline-disciplines-dir", str(bd))

    def test_a_dangling_baseline_symlink_is_fatal(self, tmp_path: Path) -> None:
        import os

        bk, bd, tk, td = self._trees(tmp_path)
        (tk / "doc.md").write_text("# real\n", encoding="utf-8")
        os.symlink(bk / "gone.md", bk / "doc.md")
        r = self._run(tmp_path, bk, bd, tk, td)
        assert r.returncode == 2 and "doc.md" in r.stderr and "baseline" in r.stderr
        assert not (tmp_path / "seed.json").exists()

    def test_a_dangling_baseline_discipline_symlink_is_fatal(self, tmp_path: Path) -> None:
        import os

        bk, bd, tk, td = self._trees(tmp_path)
        os.symlink(bd / "gone.md", bd / "linked.md")
        r = self._run(tmp_path, bk, bd, tk, td)
        assert r.returncode == 2 and "linked.md" in r.stderr

    def test_an_unparseable_but_readable_baseline_file_stays_a_warning(self, tmp_path: Path) -> None:
        bk, bd, tk, td = self._trees(tmp_path)
        (bk / "sub" / "bad.yaml").write_text("key: value\n- orphan\n", encoding="utf-8")
        r = self._run(tmp_path, bk, bd, tk, td)
        assert r.returncode == 0, r.stderr
        assert "WARNING" in r.stderr

    def test_a_dangling_baseline_readme_link_is_not_fatal(self, tmp_path: Path) -> None:
        import os

        bk, bd, tk, td = self._trees(tmp_path)
        os.symlink(bk.parent / "missing-README.md", bk / "README.md")
        assert self._run(tmp_path, bk, bd, tk, td).returncode == 0


class TestDanglingScanOnlyCoversReadFiles:
    def _tree(self, tmp_path: Path) -> tuple[Path, Path]:
        k = tmp_path / "k"
        _nested(k, "good", {"x": "1"})
        return k, _stub_disciplines(tmp_path / "d")

    def _run(self, k: Path, d: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
        return _cli(k, d, "--upstream", "--output", str(tmp_path / "seed.json"))

    def test_links_the_extractor_never_reads_do_not_fail_the_run(self, tmp_path: Path) -> None:
        import os

        k, d = self._tree(tmp_path)
        gone = tmp_path / "does-not-exist"
        for name in ("README.md", "provenance_log.md", "agent-context-map.yaml",
                     "diagram.d2", "notes.txt"):
            os.symlink(gone, k / name)
        (k / "sub" / "deeper").mkdir(parents=True)
        os.symlink(gone, k / "sub" / "deeper" / "README.md")
        os.symlink(gone, d / "README.md")
        os.symlink(gone, d / "data.json")
        r = self._run(k, d, tmp_path)
        assert r.returncode == 0, r.stderr

    def test_dangling_yaml_and_markdown_links_still_fail(self, tmp_path: Path) -> None:
        import os

        for name in ("a.yaml", "b.yml", "c.md", "D.MD"):
            case = tmp_path / name
            k, d = self._tree(case)
            os.symlink(case / "gone", k / name)
            r = self._run(k, d, case)
            assert r.returncode == 2 and name in r.stderr, name


# ===========================================================================
# Round 17: --exclude-kinds (port mode)
# ===========================================================================

_STUB_WITH_BULLET = (
    "# Stub\n\n**Status**: Active\n\n## Summary\n\nstub framework text\n\n"
    "## Parking Lot\n\n*Instruction.*\n\n### Mine\n\n- **a.** the project's own bullet\n"
)


class TestExcludeKinds:
    def _tree(self, tmp_path: Path, stem: str = "stub") -> tuple[Path, Path]:
        k = tmp_path / "k"
        _nested(k, "good", {"x": "1"})
        d = tmp_path / "d"
        d.mkdir()
        (d / f"{stem}.md").write_text(_STUB_WITH_BULLET, encoding="utf-8")
        return k, d

    def _entries(self, tmp_path: Path, k: Path, d: Path, *extra: str) -> list[dict[str, Any]]:
        out = tmp_path / "seed.json"
        r = _cli(k, d, "--output", str(out), *extra)
        assert r.returncode == 0, r.stderr
        entries: list[dict[str, Any]] = json.loads(out.read_text())["entries"]
        return entries

    def test_the_bullet_is_sent_and_framework_and_structure_are_not(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        es = self._entries(tmp_path, k, d, "--exclude-kinds", "framework,parking-lot-structure")
        ids = [e["knowledge_id"] for e in es]
        assert any(":parking-lot:" in i for i in ids)
        assert "discipline:stub:framework" not in ids
        assert "discipline:stub:parking-lot-structure" not in ids
        assert "discipline:stub:status" in ids and "sub:good:x" in ids
        bullet = next(e for e in es if ":parking-lot:" in e["knowledge_id"])
        assert bullet["content"] == "- **a.** the project's own bullet"
        assert "sdlc:project-specific" in bullet["tags"]

    def test_without_the_flag_nothing_is_left_out(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        ids = [e["knowledge_id"] for e in self._entries(tmp_path, k, d)]
        assert "discipline:stub:framework" in ids and "discipline:stub:parking-lot-structure" in ids

    def test_a_hashed_long_stem_is_caught_by_kind_not_by_id(self, tmp_path: Path) -> None:
        stem = "s" * 90
        k, d = self._tree(tmp_path, stem)
        plain = self._entries(tmp_path, k, d)
        framework_id = next(e["knowledge_id"] for e in plain if e["content"].startswith("# Stub"))
        structure_id = next(e["knowledge_id"] for e in plain if e["content"].startswith("### Mine"))
        assert not framework_id.endswith(":framework") and not structure_id.endswith(":parking-lot-structure")
        (tmp_path / "seed.json").unlink()
        kept = self._entries(tmp_path, k, d, "--exclude-kinds", "framework,parking-lot-structure")
        ids = [e["knowledge_id"] for e in kept]
        assert framework_id not in ids and structure_id not in ids
        # The bullet's id is hashed too (too long), so find it by its content.
        assert any(e["content"].startswith("- **a.**") for e in kept)

    def test_every_kind_can_be_named(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        every = "framework,status,parking-lot-structure,active-questions,project-context,maturity-tracker"
        ids = [e["knowledge_id"] for e in self._entries(tmp_path, k, d, "--exclude-kinds", every)]
        assert not any(i.startswith("discipline:stub:") and ":parking-lot:" not in i for i in ids)
        assert any(":parking-lot:" in i for i in ids)

    def test_combined_with_upstream_it_exits_2_and_says_why(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        r = _cli(k, d, "--upstream", "--output", str(tmp_path / "s.json"),
                 "--exclude-kinds", "framework")
        assert r.returncode == 2 and "port mode" in r.stderr and "--upstream" in r.stderr
        assert not (tmp_path / "s.json").exists()

    def test_an_unknown_or_empty_kind_exits_2_and_names_it(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        r = _cli(k, d, "--output", str(tmp_path / "s.json"), "--exclude-kinds", "framework,bullets")
        assert r.returncode == 2 and "bullets" in r.stderr
        for bad in ("", ",", "parking-lot"):
            assert _cli(k, d, "--output", str(tmp_path / "s.json"),
                        "--exclude-kinds", bad).returncode == 2, bad

    def test_the_dry_run_reports_how_many_entries_were_left_out(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        r = _cli(k, d, "--dry-run", "--exclude-kinds", "framework,parking-lot-structure")
        assert r.returncode == 0, r.stderr
        assert "left out by --exclude-kinds" in r.stderr and ": 2 entries" in r.stderr
        assert "Total entries: 3" in r.stderr

    def test_the_real_tree_loses_only_framework_and_structure_entries(self, tmp_path: Path) -> None:
        real = _REAL_KNOWLEDGE_DIR.parent
        if not (real / "knowledge").exists():
            pytest.skip("real ops/sdlc tree not present")
        big = ["--max-per-file", "100000", "--max-bytes", "100000000", "--no-manifest"]

        def ids(name: str, *extra: str) -> list[str]:
            out = tmp_path / name
            r = _cli(real / "knowledge", real / "disciplines", "--output", str(out), *big, *extra)
            assert r.returncode == 0, r.stderr
            return [e["knowledge_id"] for e in json.loads(out.read_text())["entries"]]

        full = ids("full.json")
        trimmed = ids("trimmed.json", "--exclude-kinds", "framework,parking-lot-structure")
        gone = set(full) - set(trimmed)
        expected = {i for i in full if i.startswith("discipline:")
                    and i.endswith((":framework", ":parking-lot-structure"))}
        assert gone == expected and len(gone) >= 20
        assert set(trimmed) <= set(full) and len(trimmed) == len(full) - len(gone)


# ===========================================================================
# Round 18: the discipline: id namespace belongs to discipline files
# ===========================================================================

_ALL_KINDS = "framework,status,parking-lot-structure,active-questions,project-context,maturity-tracker"
_FRAMEWORK = "discipline:testing:framework"


class TestReservedDisciplineNamespace:
    def _trees(self, tmp_path: Path, with_testing: bool, claim: str = "entries") -> tuple[Path, Path]:
        k, d = tmp_path / "k", tmp_path / "d"
        k.mkdir(parents=True)
        _nested(k, "good", {"x": "1"})
        if claim == "entries":
            (k / "evil.yaml").write_text(
                "entries:\n  - topic: Looks ordinary\n    guidance: overwrites the framework\n"
                f"    knowledge_id: {_FRAMEWORK}\n", encoding="utf-8")
        elif claim == "rules":
            (k / "evil.yaml").write_text(
                f"rules:\n  - rule_id: {_FRAMEWORK}\n    title: T\n    description: d\n",
                encoding="utf-8")
        d.mkdir()
        (d / "other.md").write_text("# Other\n\n## Summary\n\nx\n", encoding="utf-8")
        if with_testing:
            (d / "testing.md").write_text("# Testing\n\n## Summary\n\nreal framework\n", encoding="utf-8")
        return k, d

    def test_a_yaml_entry_claiming_a_framework_id_is_fatal_on_a_re_port(self, tmp_path: Path) -> None:
        for claim in ("entries", "rules"):
            case = tmp_path / claim
            k, d = self._trees(case, with_testing=False, claim=claim)
            out = case / "seed.json"
            r = _cli(k, d, "--output", str(out), "--exclude-kinds", _ALL_KINDS)
            assert r.returncode == 1, (claim, r.stderr)
            assert _FRAMEWORK in r.stderr and "evil.yaml" in r.stderr
            assert r.stdout == "" and not out.exists()

    def test_the_same_claim_is_fatal_on_a_first_port_even_with_allow_duplicates(
        self, tmp_path: Path
    ) -> None:
        k, d = self._trees(tmp_path, with_testing=True)
        out = tmp_path / "seed.json"
        r = _cli(k, d, "--output", str(out), "--allow-duplicates")
        assert r.returncode == 1 and _FRAMEWORK in r.stderr and "evil.yaml" in r.stderr
        assert not out.exists()

    def test_the_dry_run_fails_too(self, tmp_path: Path) -> None:
        k, d = self._trees(tmp_path, with_testing=False)
        r = _cli(k, d, "--dry-run")
        assert r.returncode == 1 and _FRAMEWORK in r.stderr

    def test_every_mode_refuses_it(self, tmp_path: Path) -> None:
        k, d = self._trees(tmp_path, with_testing=False)
        assert _cli(k, d, "--upstream", "--output", str(tmp_path / "u.json")).returncode == 1
        ids = tmp_path / "ids.txt"
        ids.write_text("sub:good:x\n", encoding="utf-8")
        assert _cli(k, d, "--output", str(tmp_path / "o.json"), "--only-ids", str(ids)).returncode == 1
        assert not list(tmp_path.glob("?.json"))

    def test_a_markdown_document_whose_path_spells_a_discipline_id_is_fatal(
        self, tmp_path: Path
    ) -> None:
        k, d = self._trees(tmp_path, with_testing=False, claim="none")
        (k / "discipline" / "testing").mkdir(parents=True)
        (k / "discipline" / "testing" / "framework.md").write_text("# Mine\n", encoding="utf-8")
        r = _cli(k, d, "--output", str(tmp_path / "s.json"))
        assert r.returncode == 1 and _FRAMEWORK in r.stderr
        assert "discipline/testing/framework.md" in r.stderr

    def test_a_root_level_discipline_yaml_key_is_fatal(self, tmp_path: Path) -> None:
        k, d = self._trees(tmp_path, with_testing=False, claim="none")
        (k / "discipline.yaml").write_text("framework: text\n", encoding="utf-8")
        r = _cli(k, d, "--output", str(tmp_path / "s.json"))
        assert r.returncode == 1 and "discipline:framework" in r.stderr

    def test_a_hashed_long_claim_is_caught_after_sanitising(self, tmp_path: Path) -> None:
        k, d = self._trees(tmp_path, with_testing=False, claim="none")
        long_id = "discipline:" + "s" * 120 + ":framework"
        (k / "evil.yaml").write_text(
            f"entries:\n  - topic: t\n    guidance: g\n    knowledge_id: {long_id}\n",
            encoding="utf-8")
        r = _cli(k, d, "--output", str(tmp_path / "s.json"))
        assert r.returncode == 1 and "evil.yaml" in r.stderr

    def test_a_baseline_holding_such_an_id_is_fatal(self, tmp_path: Path) -> None:
        k, d = self._trees(tmp_path, with_testing=True, claim="none")
        bk = tmp_path / "bk"
        _nested(bk, "good", {"x": "1"})
        (bk / "evil.yaml").write_text(
            f"rules:\n  - rule_id: {_FRAMEWORK}\n    title: T\n    description: d\n", encoding="utf-8")
        bd = _stub_disciplines(tmp_path / "bd")
        r = _cli(k, d, "--upstream", "--output", str(tmp_path / "s.json"),
                 "--baseline-knowledge-dir", str(bk), "--baseline-disciplines-dir", str(bd))
        assert r.returncode == 1 and "baseline" in r.stderr and _FRAMEWORK in r.stderr

    def test_real_discipline_entries_and_lookalike_ids_are_not_flagged(self, tmp_path: Path) -> None:
        k, d = self._trees(tmp_path, with_testing=True, claim="none")
        (k / "ok.yaml").write_text(
            "entries:\n  - topic: a\n    guidance: g\n    knowledge_id: disciplines:testing:framework\n"
            "  - topic: b\n    guidance: g\n    knowledge_id: discipline-testing:framework\n"
            "  - topic: c\n    guidance: g\n    knowledge_id: Discipline:testing:x\n",
            encoding="utf-8")
        out = tmp_path / "seed.json"
        r = _cli(k, d, "--output", str(out))
        assert r.returncode == 0, r.stderr
        ids = [e["knowledge_id"] for e in json.loads(out.read_text())["entries"]]
        assert _FRAMEWORK in ids and "disciplines:testing:framework" in ids
        # A long stem's hashed discipline id is a discipline entry, not a claim.
        long_stem = "s" * 90
        (d / f"{long_stem}.md").write_text("# L\n\n## Summary\n\nx\n", encoding="utf-8")
        assert _cli(k, d, "--output", str(tmp_path / "again.json")).returncode == 0


class TestReservedNamespaceRefusalMessages:
    """The advice depends on whose id it is, and nothing is reported as renamed."""

    def _claim_tree(self, root: Path, *, with_testing: bool) -> tuple[Path, Path]:
        k, d = root / "k", root / "d"
        k.mkdir(parents=True)
        _nested(k, "good", {"x": "1"})
        (k / "evil.yaml").write_text(
            f"entries:\n  - topic: t\n    guidance: g\n    knowledge_id: {_FRAMEWORK}\n",
            encoding="utf-8")
        d.mkdir()
        (d / "other.md").write_text("# Other\n\n## Summary\n\nx\n", encoding="utf-8")
        if with_testing:
            (d / "testing.md").write_text("# Testing\n\n## Summary\n\nx\n", encoding="utf-8")
        return k, d

    def _clean_tree(self, root: Path) -> tuple[Path, Path]:
        k, d = root / "k", root / "d"
        k.mkdir(parents=True)
        _nested(k, "good", {"x": "1"})
        d.mkdir()
        (d / "other.md").write_text("# Other\n\n## Summary\n\nx\n", encoding="utf-8")
        return k, d

    def test_project_mode_says_to_rename_the_id_in_the_named_file(self, tmp_path: Path) -> None:
        k, d = self._claim_tree(tmp_path, with_testing=False)
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 1
        assert "Rename the id in evil.yaml" in r.stderr and "re-run" in r.stderr
        assert "plugin bug" not in r.stderr and "nothing was written" in r.stderr.lower()

    def test_an_upstream_target_says_it_is_upstreams_and_a_plugin_bug(self, tmp_path: Path) -> None:
        k, d = self._claim_tree(tmp_path, with_testing=False)
        r = _cli(k, d, "--upstream", "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 1
        assert "upstream's release" in r.stderr and "plugin bug" in r.stderr
        assert "do not edit" in r.stderr.lower() and "Rename the id" not in r.stderr
        assert "nothing was sent" in r.stderr.lower() and "nothing was written" in r.stderr.lower()

    def test_a_baseline_claim_says_the_same(self, tmp_path: Path) -> None:
        k, d = self._clean_tree(tmp_path / "target")
        bk, bd = self._claim_tree(tmp_path / "base", with_testing=False)
        for extra in (["--upstream"], ["--tag-new", "x:y"]):
            r = _cli(k, d, "--output", str(tmp_path / "seed.json"), *extra,
                     "--baseline-knowledge-dir", str(bk), "--baseline-disciplines-dir", str(bd))
            assert r.returncode == 1, extra
            assert "baseline" in r.stderr and "upstream's release" in r.stderr
            assert "plugin bug" in r.stderr and "Rename the id" not in r.stderr
            assert "nothing was written" in r.stderr.lower()

    def test_a_refused_first_port_logs_no_rename_warning(self, tmp_path: Path) -> None:
        k, d = self._claim_tree(tmp_path, with_testing=True)
        for extra in ([], ["--allow-duplicates"], ["--dry-run"]):
            r = _cli(k, d, "--output", str(tmp_path / "seed.json"), *extra)
            assert r.returncode == 1, extra
            assert "renamed" not in r.stderr and "Duplicate knowledge_id" not in r.stderr, extra
            assert _FRAMEWORK in r.stderr

    def test_an_ordinary_duplicate_still_logs_its_warning(self, tmp_path: Path) -> None:
        k = tmp_path / "k"
        k.mkdir()
        for name in ("a", "b"):
            (k / f"{name}.yaml").write_text(
                "gotchas:\n  - id: same-id\n    symptom: s\n", encoding="utf-8")
        d = _stub_disciplines(tmp_path / "d")
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"), "--allow-duplicates")
        assert r.returncode == 0, r.stderr
        assert "Duplicate knowledge_id" in r.stderr and "renamed to" in r.stderr

    def test_the_fixed_data_docstring_no_longer_says_a_document_can_spell_the_id(self) -> None:
        doc = _script._is_fixed_project_data.__doc__ or ""
        assert "can spell" not in doc and "refused" in doc


# ===========================================================================
# Round 20: server-owned tags on source items; path-derived claim wording
# ===========================================================================

_SERVER_TAGS = [
    "sdlc:knowledge-id:discipline:testing:framework",
    "sdlc:knowledge-id:anything",
    "sdlc:seed-version:v9.9.9",
    "sdlc:seed",
    "sdlc:sentinel",
    "sdlc:deprecated",
]


def _tagged_tree(root: Path, tag: str, kind: str) -> tuple[Path, Path]:
    k, d = root / "k", root / "d"
    k.mkdir(parents=True)
    _nested(k, "good", {"x": "1"})
    if kind == "entries":
        body = (f"entries:\n  - topic: Tagged\n    guidance: g\n    tags: [sdlc:knowledge, '{tag}']\n")
    elif kind == "rules":
        body = (f"rules:\n  - rule_id: tagged-rule\n    title: T\n    description: d\n"
                f"    tags: ['{tag}', sdlc:knowledge]\n")
    else:
        body = (f"gotchas:\n  - id: tagged-gotcha\n    symptom: s\n    tags: ['{tag}']\n")
    (k / "evil.yaml").write_text(body, encoding="utf-8")
    d.mkdir()
    (d / "other.md").write_text("# Other\n\n## Summary\n\nx\n", encoding="utf-8")
    return k, d


class TestServerOwnedTagsOnSourceItems:
    @pytest.mark.parametrize("kind", ["entries", "rules", "gotchas"])
    @pytest.mark.parametrize("tag", _SERVER_TAGS)
    def test_an_item_carrying_a_server_owned_tag_is_fatal(
        self, tmp_path: Path, kind: str, tag: str
    ) -> None:
        k, d = _tagged_tree(tmp_path, tag, kind)
        out = tmp_path / "seed.json"
        r = _cli(k, d, "--output", str(out))
        assert r.returncode == 1, r.stderr
        assert tag in r.stderr and "evil.yaml" in r.stderr
        assert "Remove the tag" in r.stderr and "plugin bug" not in r.stderr
        assert r.stdout == "" and not out.exists()

    def test_the_id_of_the_offending_entry_is_named(self, tmp_path: Path) -> None:
        k, d = _tagged_tree(tmp_path, "sdlc:seed", "rules")
        assert "tagged-rule" in _cli(k, d, "--dry-run").stderr

    def test_every_mode_refuses_before_any_output(self, tmp_path: Path) -> None:
        k, d = _tagged_tree(tmp_path, "sdlc:knowledge-id:discipline:testing:framework", "entries")
        assert _cli(k, d, "--dry-run").returncode == 1
        ids = tmp_path / "ids.txt"
        ids.write_text("sub:good:x\n", encoding="utf-8")
        assert _cli(k, d, "--output", str(tmp_path / "o.json"), "--only-ids", str(ids)).returncode == 1
        assert _cli(k, d, "--output", str(tmp_path / "a.json"), "--allow-duplicates").returncode == 1
        assert not list(tmp_path.glob("?.json"))

    def test_an_upstream_target_says_it_is_a_plugin_bug(self, tmp_path: Path) -> None:
        k, d = _tagged_tree(tmp_path, "sdlc:seed-version:v1", "entries")
        r = _cli(k, d, "--upstream", "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 1 and "sdlc:seed-version:v1" in r.stderr
        assert "upstream's release" in r.stderr and "plugin bug" in r.stderr
        assert "do not edit" in r.stderr.lower() and "Remove the tag" not in r.stderr
        assert "nothing was written" in r.stderr.lower()

    def test_a_baseline_carrying_one_says_the_same(self, tmp_path: Path) -> None:
        tk = tmp_path / "t" / "k"
        _nested(tk, "good", {"x": "1"})
        td = _stub_disciplines(tmp_path / "t" / "d")
        bk, bd = _tagged_tree(tmp_path / "b", "sdlc:sentinel", "rules")
        for extra in (["--upstream"], ["--tag-new", "x:y"]):
            r = _cli(tk, td, "--output", str(tmp_path / "seed.json"), *extra,
                     "--baseline-knowledge-dir", str(bk), "--baseline-disciplines-dir", str(bd))
            assert r.returncode == 1, extra
            assert "baseline" in r.stderr and "sdlc:sentinel" in r.stderr
            assert "plugin bug" in r.stderr and "Remove the tag" not in r.stderr

    def test_other_sdlc_tags_on_items_are_fine(self, tmp_path: Path) -> None:
        k, d = _tagged_tree(tmp_path, "sdlc:project-specific", "entries")
        (k / "also.yaml").write_text(
            "entries:\n  - topic: A\n    guidance: g\n"
            "    tags: [sdlc:knowledge, 'sdlc:seeded', 'sdlc:knowledge-ids', 'sdlc:sentinels']\n",
            encoding="utf-8")
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 0, r.stderr

    @pytest.mark.parametrize("tag", ["sdlc:seed", "sdlc:knowledge-id:x", "sdlc:seed-version:1",
                                     "sdlc:sentinel", "sdlc:deprecated"])
    def test_tag_and_tag_new_refuse_them_at_argument_parsing(self, tmp_path: Path, tag: str) -> None:
        k, d = self._clean(tmp_path)
        out = tmp_path / "seed.json"
        r = _cli(k, d, "--output", str(out), "--tag", tag)
        assert r.returncode == 2 and tag in r.stderr and "reserved" in r.stderr and not out.exists()
        bk, bd = self._clean(tmp_path / "base")
        r = _cli(k, d, "--output", str(out), "--baseline-knowledge-dir", str(bk),
                 "--baseline-disciplines-dir", str(bd), "--tag-new", tag)
        assert r.returncode == 2 and tag in r.stderr and "reserved" in r.stderr

    def test_the_runs_own_tags_do_not_trip_the_check(self, tmp_path: Path) -> None:
        k, d = self._clean(tmp_path)
        out = tmp_path / "seed.json"
        r = _cli(k, d, "--output", str(out), "--tag", "sdlc:project-specific", "--tag", "x:y")
        assert r.returncode == 0, r.stderr
        assert all("sdlc:project-specific" in e["tags"] for e in json.loads(out.read_text())["entries"])

    @staticmethod
    def _clean(root: Path) -> tuple[Path, Path]:
        k, d = root / "k", root / "d"
        k.mkdir(parents=True)
        _nested(k, "good", {"x": "1"})
        return k, _stub_disciplines(d)


class TestPathDerivedClaimMessage:
    def _tree(self, root: Path) -> tuple[Path, Path]:
        k, d = root / "k", root / "d"
        (k / "discipline" / "testing").mkdir(parents=True)
        _nested(k, "good", {"x": "1"})
        (k / "discipline" / "testing" / "framework.md").write_text("# Mine\n", encoding="utf-8")
        return k, _stub_disciplines(d)

    def test_a_markdown_path_claim_says_to_move_the_file_out_of_knowledge_discipline(
        self, tmp_path: Path
    ) -> None:
        k, d = self._tree(tmp_path)
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 1 and "discipline/testing/framework.md" in r.stderr
        assert "move or rename the file out of knowledge/discipline/" in r.stderr
        assert "Rename the id in" not in r.stderr and "nothing was written" in r.stderr.lower()

    def test_a_field_claim_still_says_to_rename_the_id(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        (k / "discipline" / "testing" / "framework.md").unlink()
        (k / "evil.yaml").write_text(
            "entries:\n  - topic: t\n    guidance: g\n    knowledge_id: discipline:testing:framework\n",
            encoding="utf-8")
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert "Rename the id in evil.yaml" in r.stderr and "move or rename the file" not in r.stderr

    def test_both_kinds_at_once_give_both_pieces_of_advice(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        (k / "evil.yaml").write_text(
            "entries:\n  - topic: t\n    guidance: g\n    knowledge_id: discipline:other:framework\n",
            encoding="utf-8")
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert "Rename the id in evil.yaml" in r.stderr
        assert "move or rename the file out of knowledge/discipline/" in r.stderr

    def test_the_upstream_wording_is_unchanged(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        r = _cli(k, d, "--upstream", "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 1 and "plugin bug" in r.stderr and "upstream's release" in r.stderr
        assert "move or rename" not in r.stderr and "Rename the id" not in r.stderr


# ===========================================================================
# Round 21: malformed tags, path-derived YAML claims, wording
# ===========================================================================


def _tags_tree(root: Path, tags_line: str, kind: str = "entries", name: str = "kb.yaml") -> tuple[Path, Path]:
    k, d = root / "k", root / "d"
    k.mkdir(parents=True)
    _nested(k, "good", {"x": "1"})
    if kind == "entries":
        body = f"entries:\n  - topic: Tagged\n    guidance: g\n    tags: {tags_line}\n"
    elif kind == "rules":
        body = f"rules:\n  - rule_id: tagged-rule\n    title: T\n    description: d\n    tags: {tags_line}\n"
    else:
        body = f"gotchas:\n  - id: tagged-gotcha\n    symptom: s\n    tags: {tags_line}\n"
    (k / name).write_text(body, encoding="utf-8")
    return k, _stub_disciplines(d)


class TestMalformedTags:
    @pytest.mark.parametrize("kind", ["entries", "rules", "gotchas"])
    @pytest.mark.parametrize("tags_line", ["[on]", "[1]", "[a, 2]", "x", "5", "{a: b}", "[[a]]"])
    def test_a_malformed_tags_value_is_refused_with_exit_1_naming_the_file(
        self, tmp_path: Path, kind: str, tags_line: str
    ) -> None:
        k, d = _tags_tree(tmp_path, tags_line, kind)
        out = tmp_path / "seed.json"
        r = _cli(k, d, "--output", str(out))
        assert r.returncode == 1, (r.returncode, r.stderr)
        assert "Traceback" not in r.stderr and "kb.yaml" in r.stderr and "tags" in r.stderr
        assert "Remove" not in r.stderr and "nothing was written" in r.stderr.lower()
        assert r.stdout == "" and not out.exists()

    def test_the_id_of_the_item_is_named(self, tmp_path: Path) -> None:
        k, d = _tags_tree(tmp_path, "[on]", "rules")
        assert "tagged-rule" in _cli(k, d, "--dry-run").stderr

    @pytest.mark.parametrize("tags_line", ["[]", "null", "[a, b]", "['sdlc:knowledge', x]"])
    def test_absent_empty_null_and_string_lists_are_fine(self, tmp_path: Path, tags_line: str) -> None:
        k, d = _tags_tree(tmp_path, tags_line)
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 0, r.stderr

    def test_a_string_list_keeps_its_tags_in_order(self, tmp_path: Path) -> None:
        k, d = _tags_tree(tmp_path, "[b, a]")
        out = tmp_path / "seed.json"
        assert _cli(k, d, "--output", str(out)).returncode == 0
        e = next(e for e in json.loads(out.read_text())["entries"] if e["title"] == "Tagged")
        assert e["tags"][:2] == ["b", "a"]

    def test_the_same_in_an_upstream_target_says_plugin_bug(self, tmp_path: Path) -> None:
        k, d = _tags_tree(tmp_path, "[on]")
        r = _cli(k, d, "--upstream", "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 1 and "Traceback" not in r.stderr
        assert "plugin bug" in r.stderr and "upstream's release" in r.stderr

    def test_a_root_level_baseline_entry_with_tags_on_is_refused_not_a_crash(self, tmp_path: Path) -> None:
        tk = tmp_path / "t" / "k"
        _nested(tk, "good", {"x": "1"})
        td = _stub_disciplines(tmp_path / "t" / "d")
        bk, bd = _tags_tree(tmp_path / "b", "[on]")
        for extra in (["--upstream"], ["--tag-new", "x:y"]):
            r = _cli(tk, td, "--output", str(tmp_path / "seed.json"), *extra,
                     "--baseline-knowledge-dir", str(bk), "--baseline-disciplines-dir", str(bd))
            assert r.returncode == 1, extra
            assert "Traceback" not in r.stderr and "baseline" in r.stderr and "kb.yaml" in r.stderr
            assert "plugin bug" in r.stderr

    def test_the_reserved_tag_check_ignores_non_string_tags(self) -> None:
        entry = {"knowledge_id": "a", "source_path": "a.yaml", "tags": [True, 1, "sdlc:seed", None]}
        result = _script.CollectResult()
        result.entries = [entry]
        assert _script._server_tag_claims(result) == [("a", "a.yaml", "sdlc:seed")]


class TestPathDerivedYamlClaims:
    def _tree(self, root: Path) -> tuple[Path, Path]:
        k, d = root / "k", root / "d"
        (k / "discipline").mkdir(parents=True)
        _nested(k, "good", {"x": "1"})
        return k, _stub_disciplines(d)

    def test_a_yaml_key_under_knowledge_discipline_says_to_move_the_file(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        (k / "discipline" / "testing.yaml").write_text("framework: text\n", encoding="utf-8")
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 1 and "discipline:testing:framework" in r.stderr
        assert "comes from its path" in r.stderr
        assert "move or rename the file out of knowledge/discipline/" in r.stderr
        assert "Rename the id in" not in r.stderr

    def test_a_yaml_item_with_no_id_under_knowledge_discipline_is_path_derived(
        self, tmp_path: Path
    ) -> None:
        k, d = self._tree(tmp_path)
        (k / "discipline" / "notes.yaml").write_text(
            "entries:\n  - topic: Foo\n    guidance: g\n", encoding="utf-8")
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 1 and "discipline:notes:foo" in r.stderr
        assert "move or rename the file out of knowledge/discipline/" in r.stderr

    def test_an_id_the_file_does_contain_still_says_rename_the_id(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        (k / "evil.yaml").write_text(
            "entries:\n  - topic: t\n    guidance: g\n    knowledge_id: discipline:testing:framework\n",
            encoding="utf-8")
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert "Rename the id in evil.yaml" in r.stderr and "move or rename" not in r.stderr

    def test_an_explicit_id_inside_a_discipline_folder_is_still_a_field_claim(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        (k / "discipline" / "x.yaml").write_text(
            "rules:\n  - rule_id: discipline:testing:framework\n    title: T\n    description: d\n",
            encoding="utf-8")
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert "Rename the id in discipline/x.yaml" in r.stderr

    def test_joined_advice_reads_as_one_sentence(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        (k / "discipline" / "testing.yaml").write_text("framework: text\n", encoding="utf-8")
        (k / "evil.yaml").write_text(
            "entries:\n  - topic: t\n    guidance: g\n    knowledge_id: discipline:other:framework\n",
            encoding="utf-8")
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert "; The id of" not in r.stderr and "; the id of" in r.stderr
        assert "Rename the id in evil.yaml; the id of discipline/testing.yaml comes from its path" in r.stderr
        assert r.stderr.count("then re-run") == 1


class TestTagHelpAndConstants:
    def test_the_tag_help_names_the_full_set_of_refused_tags(self) -> None:
        r = subprocess.run([sys.executable, "-I", str(_SCRIPT_PATH), "--help"],
                           capture_output=True, text=True, check=False)
        text = " ".join(r.stdout.split())
        for name in ("sdlc:knowledge-id:", "sdlc:seed-version:", "sdlc:seed,", "sdlc:sentinel", "sdlc:deprecated"):
            assert name in text, name

    def test_the_unused_reserved_tags_constant_is_gone(self) -> None:
        assert not hasattr(_script, "_RESERVED_TAGS")


# ===========================================================================
# Round 22: advice follows how the id was built; every refusal in one run
# ===========================================================================

_MOVE = "move or rename the file out of knowledge/discipline/"


class TestAdviceFollowsHowTheIdWasBuilt:
    def _tree(self, root: Path) -> tuple[Path, Path]:
        k, d = root / "k", root / "d"
        (k / "discipline").mkdir(parents=True)
        _nested(k, "good", {"x": "1"})
        return k, _stub_disciplines(d)

    def test_a_sanitised_path_built_id_still_says_move_the_file(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        (k / "discipline" / "My File.yaml").write_text(
            "entries:\n  - topic: Foo\n    guidance: g\n", encoding="utf-8")
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 1 and "discipline:My-File:foo" in r.stderr
        assert _MOVE in r.stderr and "Rename the id in" not in r.stderr

    @pytest.mark.parametrize("written", ["discipline:testing:foo", "discipline:testing"])
    def test_a_written_id_that_matches_the_path_still_says_rename_the_id(
        self, tmp_path: Path, written: str
    ) -> None:
        k, d = self._tree(tmp_path)
        (k / "discipline" / "testing.yaml").write_text(
            f"entries:\n  - topic: Foo\n    guidance: g\n    knowledge_id: {written}\n",
            encoding="utf-8")
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 1 and written in r.stderr
        assert "Rename the id in discipline/testing.yaml" in r.stderr
        assert "move or rename" not in r.stderr

    def test_a_written_rule_or_gotcha_id_that_matches_the_path_says_rename(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        (k / "discipline" / "testing.yaml").write_text(
            "rules:\n  - rule_id: discipline:testing:r1\n    title: T\n    description: d\n",
            encoding="utf-8")
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert "Rename the id in discipline/testing.yaml" in r.stderr and "move or rename" not in r.stderr
        (k / "discipline" / "testing.yaml").write_text(
            "gotchas:\n  - id: discipline:testing:g1\n    symptom: s\n", encoding="utf-8")
        r = _cli(k, d, "--output", str(tmp_path / "seed2.json"))
        assert "Rename the id in discipline/testing.yaml" in r.stderr and "move or rename" not in r.stderr

    def test_one_file_with_a_written_claim_and_a_path_built_claim_gets_both_pieces(
        self, tmp_path: Path
    ) -> None:
        k, d = self._tree(tmp_path)
        (k / "discipline" / "testing.yaml").write_text(
            "entries:\n  - topic: Written\n    guidance: g\n    knowledge_id: discipline:testing:written\n"
            "  - topic: Built\n    guidance: g\n", encoding="utf-8")
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 1
        assert "discipline:testing:written" in r.stderr and "discipline:testing:built" in r.stderr
        assert "Rename the id in discipline/testing.yaml; the id of discipline/testing.yaml comes from its path" in r.stderr
        assert _MOVE in r.stderr

    def test_a_markdown_document_is_always_path_built(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        (k / "discipline" / "testing.md").write_text("# T\n", encoding="utf-8")
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert _MOVE in r.stderr and "Rename the id in" not in r.stderr

    def test_the_record_survives_dup_renames_and_is_keyed_by_entry(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        (k / "discipline" / "testing.yaml").write_text(
            "entries:\n  - topic: Foo\n    guidance: g\n    knowledge_id: discipline:testing:foo\n",
            encoding="utf-8")
        result = _script._collect(k, d)
        written = [e for e in result.entries if e["knowledge_id"] == "discipline:testing:foo"]
        assert len(written) == 1 and id(written[0]) in result.field_ids
        built = [e for e in result.entries if e["knowledge_id"] == "sub:good:x"]
        assert built and id(built[0]) not in result.field_ids


class TestEveryRefusalInOneRun:
    def _tree(self, root: Path, body: str) -> tuple[Path, Path]:
        k, d = root / "k", root / "d"
        k.mkdir(parents=True)
        _nested(k, "good", {"x": "1"})
        (k / "evil.yaml").write_text(body, encoding="utf-8")
        return k, _stub_disciplines(d)

    def test_a_malformed_list_holding_a_server_tag_names_both_problems(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path, 'entries:\n  - topic: T\n    guidance: g\n    tags: [on, "sdlc:seed"]\n')
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 1
        assert "malformed tags" in r.stderr and "sdlc:seed" in r.stderr
        assert "tags the server adds itself" in r.stderr
        assert not (tmp_path / "seed.json").exists()

    def test_an_id_claim_and_a_bad_tag_in_one_file_are_both_reported(self, tmp_path: Path) -> None:
        k, d = self._tree(
            tmp_path,
            "entries:\n  - topic: T\n    guidance: g\n    knowledge_id: discipline:x:y\n"
            "  - topic: U\n    guidance: g\n    tags: [on]\n"
            "  - topic: V\n    guidance: g\n    tags: [sdlc:sentinel]\n")
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 1
        assert "discipline: id namespace" in r.stderr and "malformed tags" in r.stderr
        assert "tags the server adds itself" in r.stderr and "sdlc:sentinel" in r.stderr
        assert r.stderr.count("ERROR:") == 3

    def test_a_single_problem_still_prints_a_single_error(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path, "entries:\n  - topic: T\n    guidance: g\n    tags: [on]\n")
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 1 and r.stderr.count("ERROR:") == 1

    def test_the_baseline_reports_everything_too(self, tmp_path: Path) -> None:
        tk = tmp_path / "t" / "k"
        _nested(tk, "good", {"x": "1"})
        td = _stub_disciplines(tmp_path / "t" / "d")
        bk, bd = self._tree(tmp_path / "b", 'entries:\n  - topic: T\n    guidance: g\n    tags: [on, "sdlc:seed"]\n')
        r = _cli(tk, td, "--upstream", "--output", str(tmp_path / "seed.json"),
                 "--baseline-knowledge-dir", str(bk), "--baseline-disciplines-dir", str(bd))
        assert r.returncode == 1 and r.stderr.count("ERROR:") == 2
        assert "plugin bug" in r.stderr and "baseline" in r.stderr


# ===========================================================================
# Round 23: every present tags value validated on every branch; component advice
# ===========================================================================


class TestEveryPresentTagsValueIsValidated:
    @pytest.mark.parametrize("kind", ["entries", "rules", "gotchas"])
    @pytest.mark.parametrize("tags_line", ["off", "0", '""', "{}", "5", "false", "no"])
    def test_a_falsy_or_non_list_value_is_refused(self, tmp_path: Path, kind: str, tags_line: str) -> None:
        k, d = _tags_tree(tmp_path, tags_line, kind)
        out = tmp_path / "seed.json"
        r = _cli(k, d, "--output", str(out))
        assert r.returncode == 1, (tags_line, r.stderr)
        assert "malformed tags" in r.stderr and "kb.yaml" in r.stderr and "Traceback" not in r.stderr
        assert r.stdout == "" and not out.exists()

    @pytest.mark.parametrize("kind", ["entries", "rules", "gotchas"])
    @pytest.mark.parametrize("tags_line", ["null", "[]", "[a]"])
    def test_none_and_empty_and_string_lists_stay_accepted(
        self, tmp_path: Path, kind: str, tags_line: str
    ) -> None:
        k, d = _tags_tree(tmp_path, tags_line, kind)
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 0, r.stderr

    def test_an_absent_key_and_a_bare_key_keep_the_default_tags(self, tmp_path: Path) -> None:
        k, d = _tags_tree(tmp_path, "null")
        (k / "kb.yaml").write_text(
            "entries:\n  - topic: A\n    guidance: g\n  - topic: B\n    guidance: g\n    tags:\n"
            "  - topic: C\n    guidance: g\n    tags: []\n", encoding="utf-8")
        out = tmp_path / "seed.json"
        assert _cli(k, d, "--output", str(out)).returncode == 0
        es = {e["title"]: e for e in json.loads(out.read_text())["entries"]}
        for title in "ABC":
            assert es[title]["tags"][:2] == ["sdlc:knowledge", "sdlc:pattern:entries"]


    @pytest.mark.parametrize("tags_line", ["off", "0", '""', "{}", "5", "[on]"])
    def test_the_same_values_in_the_baseline_are_refused(self, tmp_path: Path, tags_line: str) -> None:
        tk = tmp_path / "t" / "k"
        _nested(tk, "good", {"x": "1"})
        td = _stub_disciplines(tmp_path / "t" / "d")
        for kind in ("entries", "rules", "gotchas"):
            bk, bd = _tags_tree(tmp_path / f"b_{kind}", tags_line, kind)
            for extra in (["--upstream"], ["--tag-new", "x:y"]):
                r = _cli(tk, td, "--output", str(tmp_path / "seed.json"), *extra,
                         "--baseline-knowledge-dir", str(bk), "--baseline-disciplines-dir", str(bd))
                assert r.returncode == 1, (kind, tags_line, extra, r.stderr)
                assert "baseline" in r.stderr and "plugin bug" in r.stderr


    def test_the_message_says_the_fix_that_applies(self, tmp_path: Path) -> None:
        k, d = _tags_tree(tmp_path / "a", "x")
        scalar = _cli(k, d, "--output", str(tmp_path / "a.json")).stderr
        assert "put it in a list" in scalar and "quote" not in scalar
        k, d = _tags_tree(tmp_path / "b", "[on]")
        element = _cli(k, d, "--output", str(tmp_path / "b.json")).stderr
        assert "quote" in element and "put it in a list" not in element
        k, d = _tags_tree(tmp_path / "c", "5")
        assert "put it in a list" in _cli(k, d, "--output", str(tmp_path / "c.json")).stderr

    def test_a_mixed_run_gives_both_fixes(self, tmp_path: Path) -> None:
        k, d = _tags_tree(tmp_path, "null")
        (k / "kb.yaml").write_text(
            "entries:\n  - topic: A\n    guidance: g\n    tags: x\n"
            "  - topic: B\n    guidance: g\n    tags: [on]\n", encoding="utf-8")
        err = _cli(k, d, "--output", str(tmp_path / "s.json")).stderr
        assert "put it in a list" in err and "quote" in err


class TestPathCauseNamedInTheAdvice:
    def _tree(self, root: Path) -> tuple[Path, Path]:
        k, d = root / "k", root / "d"
        k.mkdir(parents=True)
        _nested(k, "good", {"x": "1"})
        return k, _stub_disciplines(d)

    def test_a_sanitised_directory_is_named_not_knowledge_discipline(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        (k / "_discipline").mkdir()
        (k / "_discipline" / "notes.yaml").write_text(
            "entries:\n  - topic: Foo\n    guidance: g\n", encoding="utf-8")
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 1 and "discipline:notes:foo" in r.stderr
        err = r.stderr.lower()
        assert "the directory `_discipline` under knowledge/ makes the id of _discipline/notes.yaml" in err
        assert "start with discipline:; rename the file or its directory so its path no longer begins `discipline`" in err
        assert "out of knowledge/discipline/" not in r.stderr

    def test_the_plain_discipline_directory_keeps_its_wording(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        (k / "discipline").mkdir()
        (k / "discipline" / "notes.yaml").write_text("framework: text\n", encoding="utf-8")
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert "move or rename the file out of knowledge/discipline/" in r.stderr

    def test_a_root_level_file_is_named_as_a_file(self, tmp_path: Path) -> None:
        k, d = self._tree(tmp_path)
        (k / "discipline.yaml").write_text("framework: text\n", encoding="utf-8")
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 1
        assert ("the file name of discipline.yaml makes its id start with discipline:; rename the file "
                "so its path no longer begins `discipline`") in r.stderr.lower()
        assert "out of knowledge/discipline/" not in r.stderr


class TestScalarServerTagAndLabels:
    def test_a_scalar_server_tag_is_reported_with_the_malformed_value(self, tmp_path: Path) -> None:
        k, d = _tags_tree(tmp_path, '"sdlc:seed"')
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 1
        assert "malformed tags" in r.stderr and "tags the server adds itself" in r.stderr
        assert "carries 'sdlc:seed'" in r.stderr and r.stderr.count("ERROR:") == 2
        assert not (tmp_path / "seed.json").exists()

    def test_an_ordinary_scalar_is_only_malformed(self, tmp_path: Path) -> None:
        k, d = _tags_tree(tmp_path, "just-a-word")
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        assert r.returncode == 1 and r.stderr.count("ERROR:") == 1

    def test_claims_from_a_malformed_list_are_labelled_as_items_not_ids(self, tmp_path: Path) -> None:
        k, d = _tags_tree(tmp_path, '[on, "sdlc:seed"]')
        (k / "kb.yaml").write_text(
            'entries:\n  - topic: Tagged\n    guidance: g\n    tags: [on, "sdlc:seed"]\n'
            "  - topic: Plain\n    guidance: g\n    tags: [sdlc:sentinel]\n", encoding="utf-8")
        r = _cli(k, d, "--output", str(tmp_path / "seed.json"))
        # Labelled by item path (with its name), not by an entry id.
        assert "item 'entries[0] (Tagged)' in kb.yaml carries 'sdlc:seed'" in r.stderr
        assert "'kb:plain' in kb.yaml carries 'sdlc:sentinel'" in r.stderr
        assert "'entries[0] (Tagged)' in kb.yaml carries" not in r.stderr.replace("item 'entries[0] (Tagged)'", "")

    def test_the_baseline_reports_a_scalar_server_tag_too(self, tmp_path: Path) -> None:
        tk = tmp_path / "t" / "k"
        _nested(tk, "good", {"x": "1"})
        td = _stub_disciplines(tmp_path / "t" / "d")
        bk, bd = _tags_tree(tmp_path / "b", '"sdlc:knowledge-id:x"')
        r = _cli(tk, td, "--upstream", "--output", str(tmp_path / "seed.json"),
                 "--baseline-knowledge-dir", str(bk), "--baseline-disciplines-dir", str(bd))
        assert r.returncode == 1 and r.stderr.count("ERROR:") == 2 and "plugin bug" in r.stderr

    def test_the_reserved_ids_docstring_describes_a_message_not_an_exit(self) -> None:
        doc = _script._reserved_ids_message.__doc__ or ""
        assert "Exit 1" not in doc and "refusal" in doc.lower()


# ===========================================================================
# Round 25: every list in a file is validated, not just the one the parser reads first
# ===========================================================================


def _list_block(kind: str, tags_line: str | None, n: int = 0) -> str:
    """A YAML list of one item of ``kind``; ``tags_line`` None leaves the key out."""
    extra = f"    tags: {tags_line}\n" if tags_line is not None else ""
    if kind == "entries":
        return f"entries:\n  - topic: E{n}\n    guidance: g\n{extra}"
    if kind == "rules":
        return f"rules:\n  - rule_id: r{n}\n    title: T\n    description: d\n{extra}"
    if kind == "gotchas":
        return f"gotchas:\n  - id: g{n}\n    symptom: s\n{extra}"
    return f"{kind}:\n  - name: x{n}\n    note: n\n{extra}"


def _two_list_tree(root: Path, first: str, second: str, bad_tags: str | None) -> tuple[Path, Path]:
    k, d = root / "k", root / "d"
    k.mkdir(parents=True)
    _nested(k, "good", {"x": "1"})
    (k / "kb.yaml").write_text(
        _list_block(first, None) + _list_block(second, bad_tags, 1), encoding="utf-8")
    return k, _stub_disciplines(d)


_LISTS = ["entries", "rules", "gotchas"]
_PAIRS = [(a, b) for a in _LISTS for b in _LISTS if a != b]


class TestFalsyScalarAdviceAndDocstring:
    @pytest.mark.parametrize("tags_line", ["off", "no", "false", "0", '""', "{}"])
    def test_a_falsy_value_is_told_to_remove_the_key_write_empty_or_quote(
        self, tmp_path: Path, tags_line: str
    ) -> None:
        k, d = _tags_tree(tmp_path, tags_line)
        err = _cli(k, d, "--output", str(tmp_path / "seed.json")).stderr
        assert "remove the `tags` key or write `tags: []` for the defaults" in err
        assert "or quote the value inside a list" in err
        assert "put it in a list" not in err and "tags: [name]" not in err

    def test_a_truthy_scalar_keeps_the_put_it_in_a_list_advice(self, tmp_path: Path) -> None:
        for n, tags_line in enumerate(("x", "5", "yes-please")):
            k, d = _tags_tree(tmp_path / str(n), tags_line)
            err = _cli(k, d, "--output", str(tmp_path / f"{n}.json")).stderr
            assert "put it in a list" in err and "remove the `tags` key" not in err

    def test_a_run_with_a_falsy_value_and_a_bad_element_gives_both(self, tmp_path: Path) -> None:
        k, d = _tags_tree(tmp_path, "null")
        (k / "kb.yaml").write_text(
            "entries:\n  - topic: A\n    guidance: g\n    tags: off\n"
            "  - topic: B\n    guidance: g\n    tags: [on]\n", encoding="utf-8")
        err = _cli(k, d, "--output", str(tmp_path / "s.json")).stderr
        assert "remove the `tags` key" in err and "quote each non-string list element" in err

    def test_the_upstream_wording_is_not_changed(self, tmp_path: Path) -> None:
        k, d = _tags_tree(tmp_path, "off")
        err = _cli(k, d, "--upstream", "--output", str(tmp_path / "s.json")).stderr
        assert "plugin bug" in err and "remove the `tags` key" not in err

    def test_the_module_docstring_says_a_present_non_null_value(self) -> None:
        doc = " ".join((_script.__doc__ or "").split())
        assert "a present, non-null value that is not a list of strings" in doc
        assert "whose tags is not a list of strings" not in doc


# ===========================================================================
# Round 27: every tags key at any depth of a YAML file is validated
# ===========================================================================


def _yaml_tree(root: Path, body: str) -> tuple[Path, Path]:
    k, d = root / "k", root / "d"
    k.mkdir(parents=True)
    _nested(k, "good", {"x": "1"})
    (k / "deep.yaml").write_text(body, encoding="utf-8")
    return k, _stub_disciplines(d)


_NESTED_RULES = (
    "pattern: methodology\n"
    "policy:\n"
    "  rules:\n"
    "    - rule_id: a\n      tags: [ok]\n"
    "    - rule_id: b\n"
    "    - rule_id: c\n      tags: off\n"
)


_CYCLE = "section: &a\n  name: loop\n  self: *a\n"

# which list a parser reads when a file holds several (see _infer_pattern)
_PRIORITY = {"gotchas": 3, "rules": 2, "entries": 1}


def _entry_content(out: Path, entry_id: str) -> str:
    entries = json.loads(out.read_text())["entries"]
    return next(e["content"] for e in entries if e["knowledge_id"] == entry_id)


class TestOnlySiblingListsThatAreParsedAreRefused:
    """A malformed tags value matters only where the extractor applies it as an entry's tags.

    When a file holds several lists, one parser reads one of them; the others are rendered
    as methodology content, where a ``tags`` key is just text.
    """

    @pytest.mark.parametrize(("first", "second"), _PAIRS)
    def test_the_malformed_list_is_refused_only_if_it_is_the_one_parsed(
        self, tmp_path: Path, first: str, second: str
    ) -> None:
        k, d = _two_list_tree(tmp_path, first, second, "off")
        parsed = max((first, second), key=_PRIORITY.__getitem__)
        for extra in ([], ["--upstream"], ["--dry-run"]):
            out = tmp_path / "seed.json"
            r = _cli(k, d, "--output", str(out), *extra)
            if parsed == second:
                assert r.returncode == 1 and "malformed tags" in r.stderr, (first, second, extra)
            else:
                assert r.returncode == 0, (first, second, extra, r.stderr)
        assert _entry_content(out, f"kb:{second}") .count("tags: false") == 1 if parsed != second else True

    @pytest.mark.parametrize(("first", "second"), _PAIRS)
    def test_the_same_in_the_baseline(self, tmp_path: Path, first: str, second: str) -> None:
        tk = tmp_path / "t" / "k"
        _nested(tk, "good", {"x": "1"})
        td = _stub_disciplines(tmp_path / "t" / "d")
        bk, bd = _two_list_tree(tmp_path / "b", first, second, "off")
        parsed = max((first, second), key=_PRIORITY.__getitem__)
        for extra in (["--upstream"], ["--tag-new", "x:y"]):
            r = _cli(tk, td, "--output", str(tmp_path / "seed.json"), *extra,
                     "--baseline-knowledge-dir", str(bk), "--baseline-disciplines-dir", str(bd))
            if parsed == second:
                assert r.returncode == 1 and "baseline" in r.stderr, (first, second, extra)
            else:
                assert r.returncode == 0, (first, second, extra, r.stderr)

    @pytest.mark.parametrize("first", _LISTS)
    def test_any_other_list_key_is_content(self, tmp_path: Path, first: str) -> None:
        k, d = _two_list_tree(tmp_path, first, "extras", "off")
        out = tmp_path / "seed.json"
        r = _cli(k, d, "--output", str(out))
        assert r.returncode == 0, r.stderr
        assert "tags: false" in _entry_content(out, "kb:extras")

    def test_a_methodology_only_file_renders_its_lists_as_text(self, tmp_path: Path) -> None:
        k, d = _two_list_tree(tmp_path, "entries", "rules", None)
        (k / "kb.yaml").write_text("pattern: methodology\n" + _list_block("rules", "off"), encoding="utf-8")
        out = tmp_path / "seed.json"
        assert _cli(k, d, "--output", str(out)).returncode == 0
        assert "tags: false" in _entry_content(out, "kb:rules")

    def test_the_parsed_list_names_the_item_by_its_position_and_id(self, tmp_path: Path) -> None:
        k, d = _two_list_tree(tmp_path, "entries", "rules", "off")
        err = _cli(k, d, "--output", str(tmp_path / "seed.json")).stderr
        assert "rules[0] (r1)" in err and "kb.yaml" in err
        assert err.count("rules[0]") == 1

    @pytest.mark.parametrize("ok", ["[a, b]", "[]", "null", "~"])
    def test_valid_sibling_lists_are_still_accepted(self, tmp_path: Path, ok: str) -> None:
        k, d = _two_list_tree(tmp_path, "entries", "rules", ok)
        assert _cli(k, d, "--output", str(tmp_path / "seed.json")).returncode == 0

    def test_a_server_tag_in_a_sibling_that_is_only_content_is_not_a_claim(self, tmp_path: Path) -> None:
        k, d = _two_list_tree(tmp_path, "rules", "entries", '[on, "sdlc:seed"]')
        assert _cli(k, d, "--output", str(tmp_path / "seed.json")).returncode == 0


class TestContentLevelTagsKeysAreJustText:
    """A ``tags`` key the extractor does not apply as tags renders into the entry like any key."""

    @pytest.mark.parametrize(("body", "needle"), [
        (_NESTED_RULES, "tags: false"),
        ("a:\n  b:\n    c:\n      d:\n        tags: off\n", "tags: false"),
        ("a:\n  b:\n    tags: {x: 1}\n", "tags:"),
        ("a:\n  - - name: x\n    - name: y\n      tags: 5\n", "tags: 5"),
        ("tags: off\nother: x\n", "### tags\nFalse"),
        ("section:\n  tags: ''\n", "tags:"),
        ("policy: !!omap\n  - rule:\n      tags: off\n", "tags: false"),
        ("policy: !!pairs\n  - rule:\n      tags: [on]\n", "tags:"),
        ("policy: !!omap [{rule: {tags: off}}]\n", "tags: false"),
        ("memory:\n  properties:\n    tags: free-form labels\n    title: text\n", "free-form labels"),
        ('policy:\n  rules:\n    - rule_id: a\n      tags: [on, "sdlc:seed"]\n', "sdlc:seed"),
    ], ids=["nested rule", "deep mapping", "mapping value", "list in list", "top level",
            "empty string", "omap", "pairs", "omap flow", "schema document", "server tag text"])
    def test_it_is_accepted_and_rendered_as_text_in_the_target(
        self, tmp_path: Path, body: str, needle: str
    ) -> None:
        k, d = _yaml_tree(tmp_path, body)
        for extra in ([], ["--upstream"], ["--dry-run"]):
            out = tmp_path / "seed.json"
            r = _cli(k, d, "--output", str(out), *extra)
            assert r.returncode == 0, (body, extra, r.stderr)
            assert "malformed tags" not in r.stderr and "Traceback" not in r.stderr
        entries = json.loads(out.read_text())["entries"]
        assert any(needle in e["content"] for e in entries if e["source_path"] == "deep.yaml")

    @pytest.mark.parametrize("body", [
        _NESTED_RULES,
        "a:\n  b:\n    c:\n      d:\n        tags: off\n",
        "policy: !!omap\n  - rule:\n      tags: off\n",
        "memory:\n  properties:\n    tags: free-form labels\n",
    ], ids=["nested rule", "deep mapping", "omap", "schema document"])
    def test_and_in_the_baseline(self, tmp_path: Path, body: str) -> None:
        tk = tmp_path / "t" / "k"
        _nested(tk, "good", {"x": "1"})
        td = _stub_disciplines(tmp_path / "t" / "d")
        bk, bd = _yaml_tree(tmp_path / "b", body)
        for extra in (["--upstream"], ["--tag-new", "x:y"]):
            r = _cli(tk, td, "--output", str(tmp_path / "seed.json"), *extra,
                     "--baseline-knowledge-dir", str(bk), "--baseline-disciplines-dir", str(bd))
            assert r.returncode == 0, (extra, r.stderr)

    def test_the_content_is_exactly_what_it_was_before_any_tags_check(self, tmp_path: Path) -> None:
        k, d = _yaml_tree(tmp_path, _NESTED_RULES)
        out = tmp_path / "seed.json"
        assert _cli(k, d, "--output", str(out)).returncode == 0
        assert _entry_content(out, "deep:policy") == (
            "### policy\nrules:\n- rule_id: a\n  tags:\n  - ok\n- rule_id: b\n- rule_id: c\n  tags: false\n"
        )

    def test_a_self_referencing_anchor_still_gives_its_one_entry(self, tmp_path: Path) -> None:
        k, d = _yaml_tree(tmp_path, _CYCLE)
        out = tmp_path / "seed.json"
        r = _cli(k, d, "--output", str(out))
        assert r.returncode == 0 and "Recursion" not in r.stderr and "Traceback" not in r.stderr
        assert _entry_content(out, "deep:section").startswith("### section\n")

    def test_a_cycle_through_a_list_and_a_shared_alias_are_content_too(self, tmp_path: Path) -> None:
        for n, body in enumerate(("items: &l\n  - name: a\n  - *l\n",
                                  "first: &x\n  tags: off\nsecond: *x\n")):
            k, d = _yaml_tree(tmp_path / str(n), body)
            assert _cli(k, d, "--output", str(tmp_path / f"{n}.json")).returncode == 0

    def test_sets_and_binary_values_are_left_alone(self, tmp_path: Path) -> None:
        k, d = _yaml_tree(tmp_path, "b: !!binary aGk=\n")
        assert _cli(k, d, "--output", str(tmp_path / "seed.json")).returncode == 0


class TestTopLevelSequencesAreNotEntries:
    def _tree(self, root: Path, body: str) -> tuple[Path, Path]:
        k, d = root / "k", root / "d"
        (k / "sub").mkdir(parents=True)
        (k / "sub" / "good.yaml").write_text("entries:\n  - topic: Good\n    guidance: g\n", encoding="utf-8")
        (k / "sub" / "seq.yaml").write_text(body, encoding="utf-8")
        return k, _stub_disciplines(d)

    @pytest.mark.parametrize("body", ["- tags: off\n- name: x\n", "- name: x\n  nested:\n    - tags: [on]\n"])
    def test_a_sequence_file_is_skipped_as_before_its_tags_are_never_applied(
        self, tmp_path: Path, body: str
    ) -> None:
        k, d = self._tree(tmp_path, body)
        port = _cli(k, d, "--output", str(tmp_path / "p.json"))
        assert port.returncode == 0 and "expected a top-level mapping" in port.stderr
        assert "malformed tags" not in port.stderr
        assert _cli(k, d, "--upstream", "--output", str(tmp_path / "u.json")).returncode == 2

    def test_a_baseline_sequence_file_is_only_a_warning(self, tmp_path: Path) -> None:
        tk = tmp_path / "t" / "k"
        _nested(tk, "good", {"x": "1"})
        td = _stub_disciplines(tmp_path / "t" / "d")
        bk, bd = self._tree(tmp_path / "b", "- tags: off\n")
        r = _cli(tk, td, "--upstream", "--output", str(tmp_path / "s.json"),
                 "--baseline-knowledge-dir", str(bk), "--baseline-disciplines-dir", str(bd))
        assert r.returncode == 0, r.stderr


class TestUnparsedItemsAreContentNotTags:
    """An item the parser skips is kept whole as ``:unparsed`` content; its tags are not applied."""

    @pytest.mark.parametrize("body", [
        "rules:\n  - title: No id\n    description: d\n    tags: [on]\n",
        "rules:\n  - description: no id at all\n    tags: off\n",
        "entries:\n  - guidance: no topic\n    tags: [on]\n",
        "gotchas:\n  - symptom: no id\n    tags: [on]\n",
    ], ids=["rule no id", "rule no id tags off", "entry no topic", "gotcha no id"])
    def test_an_unparsed_item_keeps_its_tags_text_and_is_not_refused_for_them(
        self, tmp_path: Path, body: str
    ) -> None:
        k, d = _tags_tree(tmp_path, "null")
        (k / "kb.yaml").write_text(body, encoding="utf-8")
        out = tmp_path / "seed.json"
        r = _cli(k, d, "--output", str(out))
        assert r.returncode == 0, r.stderr
        assert "malformed tags" not in r.stderr
        content = _entry_content(out, next(
            e["knowledge_id"] for e in json.loads(out.read_text())["entries"]
            if e["knowledge_id"].endswith(":unparsed")))
        assert "tags" in content
        # --upstream still refuses the file, as it always has, for the unparsed item itself.
        assert _cli(k, d, "--upstream", "--output", str(tmp_path / "u.json")).returncode == 2


