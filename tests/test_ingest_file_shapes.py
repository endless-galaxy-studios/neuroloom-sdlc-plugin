"""The extractor reads the files `sdlc-ingest` is told to write the way `ingest_to_neuroloom` expects.

0.7.2 has the skill write files that its Post-Execution Transform sends through the extractor.
`ingest_to_neuroloom` step 4 checks a created file's shape before sending anything, because the
extractor reads upstream's own single-rule example (Step 4, "If the discipline doesn't have YAML
conventions yet") as a methodology file and keeps the rule's `name` and `description` as metadata:
sent and then deleted, the rule statement would exist nowhere. These tests run the real extractor
on each shape and apply step 4's test to its output.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_EXTRACTOR = _ROOT / "skills" / "sdlc-port" / "scripts" / "extract_sdlc_knowledge.py"

def _prescribed() -> str:
    """The shape pattern-mapping-rules.md § "`sdlc-ingest` writes files" prescribes, read from its fenced block
    (a quoted replacement, each line prefixed `     > `) with the placeholders filled in."""
    rules = (_ROOT / "references" / "pattern-mapping-rules.md").read_text()
    m = re.search(r"\*\*Write every new file in this shape\*\*.*?\n     > ```yaml\n(.*?)\n     > ```", rules, re.S)
    assert m, "the rules no longer carry the prescribed shape's fenced block"
    block = "\n".join(ln[len("     > "):] for ln in m.group(1).split("\n")) + "\n"
    for placeholder, value in (
        ("P-<discipline>-<file>-1", "P-design-visual-design-rules-1"),
        ("rule-name", "tighten-letter-spacing"),
        ("The testable rule statement.", "Headings above 32px use negative letter-spacing."),
        ("Why this matters.", "Default tracking looks loose at display sizes."),
        ("Question framed for code review", "Does the heading use tightened letter-spacing?"),
        ("source-file-identifier", "art-1"),
    ):
        assert placeholder in block, placeholder
        block = block.replace(placeholder, value)
    assert "<" not in block, block
    return block


PRESCRIBED = _prescribed()

# z-sdlc v3.0.0 sdlc-ingest Step 4's fenced example, filled in.
UPSTREAM_SINGLE_RULE = """rule_id: V17
name: Tighten letter-spacing on large headings
description: |
  Headings above 32px use negative letter-spacing.
rationale: |
  Default tracking looks loose at display sizes.
checklist:
  - "Does the heading use tightened letter-spacing?"
source: art-1
spec_relevant: false
"""

STUB = """## Parking Lot

### Bulk import (2026-11-26, source: test article)

*Bulk import from a test article. Rules promoted to knowledge store; parking lot entries below are principles that need validation against the project's specific context before full adoption.*

- **Prefer contract tests at service seams.** [NEEDS VALIDATION] Contract tests catch drift. (Source: `art-1`)
"""

STUB_WITHOUT_HEADING = STUB.split("\n", 2)[2]


def _extract(tmp: Path, rel: str, text: str) -> list[dict]:
    knowledge, disciplines = tmp / "knowledge", tmp / "disciplines"
    knowledge.mkdir()
    disciplines.mkdir()
    target = tmp / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    out = tmp / "all.json"
    subprocess.run(
        [sys.executable, "-I", str(_EXTRACTOR), "--knowledge-dir", str(knowledge), "--disciplines-dir",
         str(disciplines), "--tag", "sdlc:project-specific", "--version", "v3.0.0", "--output", str(out)],
        check=True, capture_output=True, timeout=60,
    )
    data = json.loads(out.read_text())
    return data["entries"] if isinstance(data, dict) else data


def _rule_ids(text: str) -> set[str]:
    return {ln.split(":", 1)[1].strip() for ln in text.splitlines() if ln.strip().startswith(("- rule_id:", "rule_id:"))}


def _created_yaml_passes_step_4(entries: list[dict], text: str) -> bool:
    ids = _rule_ids(text)
    return bool(entries) and all("sdlc:pattern:rules" in e["tags"] and e["knowledge_id"] in ids for e in entries)


def test_the_prescribed_shape_gives_one_entry_per_rule_under_its_own_id(tmp_path: Path) -> None:
    entries = _extract(tmp_path, "knowledge/design/visual-design-rules.yaml", PRESCRIBED)
    assert [e["knowledge_id"] for e in entries] == ["P-design-visual-design-rules-1"]
    assert all({"sdlc:project-specific", "sdlc:domain:design"} <= set(e["tags"]) for e in entries)
    assert "Headings above 32px use negative letter-spacing." in entries[0]["content"]
    assert _created_yaml_passes_step_4(entries, PRESCRIBED)


def test_upstreams_single_rule_example_fails_step_4(tmp_path: Path) -> None:
    entries = _extract(tmp_path, "knowledge/design/animation-rules.yaml", UPSTREAM_SINGLE_RULE)
    # The rule statement is lost, which is why the handler must not send and delete this file.
    assert not any("Headings above 32px use negative letter-spacing." in e["content"] for e in entries)
    assert not _created_yaml_passes_step_4(entries, UPSTREAM_SINGLE_RULE)


def test_a_stub_gives_only_framework_structure_and_bullets(tmp_path: Path) -> None:
    entries = _extract(tmp_path, "disciplines/testing.md", STUB)
    kinds = sorted(e["knowledge_id"].split(":", 2)[2].split(":", 1)[0] for e in entries)
    assert kinds == ["framework", "parking-lot", "parking-lot-structure"]
    bullet = next(e for e in entries if e["knowledge_id"].startswith("discipline:testing:parking-lot:"))
    assert "Prefer contract tests at service seams." in bullet["content"]


def test_without_the_parking_lot_heading_the_bullet_is_framework_text(tmp_path: Path) -> None:
    entries = _extract(tmp_path, "disciplines/testing.md", STUB_WITHOUT_HEADING)
    assert [e["knowledge_id"] for e in entries] == ["discipline:testing:framework"]


STUB_NO_H2 = """### Bulk import (2026-11-26, source: test article)

- **Prefer contract tests at service seams.** [NEEDS VALIDATION] Contract tests catch drift. (Source: `art-1`)
"""


def _is_a_valid_created_stub(text: str) -> bool:
    """ingest_to_neuroloom step 4: exactly one `## Parking Lot` heading and no other level-2 heading."""
    h2 = [ln.strip() for ln in text.splitlines() if ln.startswith("## ")]
    return h2 == ["## Parking Lot"]


def test_a_created_stub_with_no_level_2_heading_has_no_parking_lot_ids_and_fails_step_4(tmp_path: Path) -> None:
    # With no H2 the extractor files the bullet as framework text, so step 5 would pick zero ids and
    # step 7 would delete the file unsent: step 4 must reject the file, and the bullets must match ids.
    entries = _extract(tmp_path, "disciplines/testing.md", STUB_NO_H2)
    ids = [e["knowledge_id"] for e in entries]
    assert ids == ["discipline:testing:framework"]
    assert not any(":parking-lot:" in i for i in ids)
    assert not _is_a_valid_created_stub(STUB_NO_H2)


def test_a_valid_stub_gives_one_parking_lot_id_per_bullet(tmp_path: Path) -> None:
    assert _is_a_valid_created_stub(STUB)
    entries = _extract(tmp_path, "disciplines/testing.md", STUB)
    assert sum(":parking-lot:" in e["knowledge_id"] and not e["knowledge_id"].endswith("structure") for e in entries) == 1
