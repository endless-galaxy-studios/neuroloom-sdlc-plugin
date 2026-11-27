"""Local gate: the residue scans pass on the z-sdlc release this plugin supports.

0.7.0 requires z-sdlc 3.0.0, but the upstream coverage gate in test_transform_rules_lint.py
reads a v2.2.0 checkout, so nothing ran the post-file-write residue scans over 3.0.0's own
text. Sleeved's migration to 3.0.0 then halted (2026-11-26) on six lines contract 0026 added
or extended: they decide whether a knowledge or discipline file is on disk because the adapter
took it, and neither a rewrite rule nor a Check 2 exemption row covered them.

This gate exports the supported release's skills, process docs, templates and agents with
`git archive` (never a checkout of the shared clone). It checks that every knowledge-layer path
and `provenance_log` mention there has a rewrite rule or an exemption row, pins the exempt lines'
text, and flags any other line that looks like a file-presence rule. That last check is a keyword
tripwire (`_LOOKS_LIKE_PRESENCE`): a line worded outside its keywords passes, so read the release's
contract-change entries too. It doesn't scan `CLAUDE-SDLC.md`, `playbooks/` or `bundles/` yet.

CI never runs it: it needs ~/Projects/cc-sdlc with the release tag. Run it before releasing the
plugin or bumping `supported_zsdlc_version`, with REQUIRE_ZSDLC_TAG=1 so a missing tag fails
instead of skipping.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
from collections.abc import Iterable, Iterator
from pathlib import Path

import pytest

import test_transform_rules_lint as lint

_ROOT = Path(__file__).resolve().parent.parent
_UPSTREAM = Path.home() / "Projects" / "cc-sdlc"
_TAG = "v" + json.loads((_ROOT / "adapter.json").read_text())["supported_zsdlc_version"]

# Contract 0026's file-presence lines: upstream path, opening words, and the first 16 hex digits
# of the sha256 of the whole line at the supported tag. They are the closed list post-operation
# Check 2 exempts; each must start exactly one line upstream. Row 6 exempts the WHOLE line, so the
# hash pins the text it was reviewed at: when upstream changes a line (or the plugin moves to a new
# release), re-read it, check it still only tests what is on disk and doesn't tell an agent to read
# or write a knowledge file or the provenance log, then update the hash here.
FILE_PRESENCE = [
    ("skills/sdlc-migrate/SKILL.md", "**The knowledge layer is the adapter's** when", "ab2e65853bd8f547"),
    ("skills/sdlc-migrate/SKILL.md", "- **Every other file there**", "7a66e2f00e6c5cfb"),
    ("skills/sdlc-migrate/SKILL.md", "- **In a full migration** (no `source_version`)", "b3a80e3fd33f2b1a"),
    (
        "skills/sdlc-migrate/SKILL.md",
        "When the knowledge layer is the adapter's (Pre-Flight Check, Step 2, The knowledge layer is the"
        " adapter's), skip the discipline files the adapter took.",
        "dc683191995b1af2",
    ),
    ("skills/sdlc-migrate/SKILL.md", "> - Dimension 7 (Migration Integrity):", "d71082a21a5985c7"),
    ("agents/sdlc-compliance-auditor.md", "7. **Migration integrity**", "93c7727e98744f07"),
    ("skills/sdlc-audit/references/compliance-methodology.md", "- **7b. File completeness:**", "dae3afd2e1fa8915"),
    ("process/adapter-lifecycle-protocol.md", "**The knowledge layer is the adapter's** when", "5f7482086b25da3f"),
]

# A line that something rewrites or flags (a knowledge-layer path, the provenance log, or a Pass 2
# concept term) AND says a file is the adapter's, off disk or not missing looks like a file-presence
# rule. The path classifier puts such a line in an ordinary rewrite family, so without this check a
# new one would pass the gate unseen. It is a keyword list, not a proof (see the module docstring).
_LOOKS_LIKE_PRESENCE = re.compile(
    r"is the adapter's|the adapter took|files it took|aren't missing|not missing|belongs to the adapter"
    r"|no `installed_files` entry|no copy on disk|off disk|absent from disk|isn't on disk"
)
_CHECK2_PATH = re.compile(r"(\[sdlc-root\]|ops/sdlc)/(knowledge|disciplines)/")
_PASS2_TERMS = re.compile(
    r"\bknowledge stores?\b|\bknowledge files?\b|\bdiscipline files?\b|\bparking[- ]lot entr|\bknowledge-store entr"
    r"|\bdiscipline parking[- ]lots?\b|\bknowledge YAMLs?\b|\bYAML knowledge files?\b|\bagent-context-map\b",
    re.IGNORECASE,
)
_RESIDUE = re.compile(_CHECK2_PATH.pattern + r"|provenance_log|" + _PASS2_TERMS.pattern, re.IGNORECASE)
# z-sdlc runs sdlc-initialize from its source and never installs it, so no project carries its text.
_NOT_INSTALLED = ("skills/sdlc-initialize/",)
# Lines that look like one but that the rules rewrite, reviewed, with the same hash pin. A line with a
# path must still land in a family whose rule row exists.
REVIEWED_REWRITES = [
    # Impact-analysis rows: reads of the parking lots and project knowledge, with "(Not for a file the
    # adapter took.)" added.
    ("skills/sdlc-migrate/SKILL.md", "| Discipline parking lots |", "a4a4642776b7ac34"),
    ("skills/sdlc-migrate/SKILL.md", "| Project knowledge |", "8be218e8e98ea06a"),
    # Drift detection's scope, older than contract 0026: earlier migrations have always rewritten its
    # "knowledge YAMLs", and it isn't one of the lines contract 0026 depends on.
    ("skills/sdlc-migrate/SKILL.md", "**Runs in Phase 1** (§1.2a), before the point of no return", "3c26d5d76408b533"),
]
_INSTALLED = {"skills/": ".claude/skills/", "agents/": ".claude/agents/", "process/": "ops/sdlc/process/"}


def _installed(rel: str) -> str:
    top = next(t for t in _INSTALLED if rel.startswith(t))
    path = _INSTALLED[top] + rel[len(top):]
    # The plugin's docs name the migrate skill by its folder: the literal `sdlc-migrate/SKILL.md`
    # is reserved for the override the plugin no longer ships (test_transform_rules_lint).
    return path.removesuffix("SKILL.md") if rel == "skills/sdlc-migrate/SKILL.md" else path


def _has_tag() -> bool:
    try:
        return subprocess.run(
            ["git", "-C", str(_UPSTREAM), "rev-parse", "--verify", "--quiet", f"{_TAG}^{{commit}}"],
            capture_output=True, timeout=10,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


if os.environ.get("REQUIRE_ZSDLC_TAG") == "1" and not _has_tag():
    raise RuntimeError(f"REQUIRE_ZSDLC_TAG=1, but ~/Projects/cc-sdlc has no {_TAG} tag")
pytestmark = pytest.mark.skipif(not _has_tag(), reason=f"needs ~/Projects/cc-sdlc with the {_TAG} tag")


@pytest.fixture(scope="module")
def release(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    out = tmp_path_factory.mktemp("zsdlc")
    tar = subprocess.run(
        ["git", "-C", str(_UPSTREAM), "archive", _TAG, "skills", "process", "templates", "agents", "playbooks", "CLAUDE-SDLC.md",
         "skeleton/manifest.json"],
        capture_output=True, check=True, timeout=60,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(out, filter="data")
    saved = lint._UPSTREAM
    lint._UPSTREAM = out  # the coverage helpers read this module global
    try:
        yield out
    finally:
        lint._UPSTREAM = saved


def _sha(line: str) -> str:
    return hashlib.sha256(line.encode()).hexdigest()[:16]


def _presence_line(release: Path, rel: str, opening: str) -> tuple[int, str]:
    lines = (release / rel).read_text().split("\n")
    hits = [(n, ln) for n, ln in enumerate(lines, start=1) if ln.strip().startswith(opening)]
    assert len(hits) == 1, f"{rel}: {len(hits)} lines start {opening!r}; revisit Check 2's file-presence row"
    return hits[0]


def _is_presence_line(release: Path, rel: str, n: int) -> bool:
    return any(rel == r and _presence_line(release, r, o)[0] == n for r, o, _h in FILE_PRESENCE)


def _audit() -> str:
    return (_ROOT / "references" / "post-operation-audit.md").read_text()


def _check2_rows() -> list[str]:
    check2 = _audit().split("### Check 2 ", 1)[1].split("\n### Check 2a", 1)[0]
    return [ln for ln in check2.splitlines() if re.match(r"\| \d+ \|", ln)]


def _presence_row() -> str:
    rows = [r for r in _check2_rows() if "contract 0026" in r.lower()]
    assert len(rows) == 1, "Check 2's table needs exactly one row for contract 0026's file-presence lines"
    return rows[0]


class TestContract0026FilePresenceLines:
    def test_each_line_is_still_upstream_unchanged_and_still_trips_a_residue_scan(self, release: Path) -> None:
        for rel, opening, sha in FILE_PRESENCE:
            _n, line = _presence_line(release, rel, opening)
            assert _RESIDUE.search(line), (rel, opening)  # a path, the provenance log or a Pass 2 term
            assert _sha(line) == sha, (
                f"{rel} line {opening!r} changed upstream ({_sha(line)}): re-review it before exempting it again"
            )

    def test_every_line_that_looks_like_one_is_listed_or_reviewed(self, release: Path) -> None:
        rules = lint._rules()
        exempt_files = tuple(f for f in lint._EXEMPT_FILES)
        unreviewed = []
        for f in sorted(release.rglob("*.md")):
            rel = str(f.relative_to(release))
            if rel.startswith(_NOT_INSTALLED):
                continue
            for n, line in enumerate(f.read_text().split("\n"), start=1):
                if not (_RESIDUE.search(line) and _LOOKS_LIKE_PRESENCE.search(line)):
                    continue
                if _is_presence_line(release, rel, n):
                    continue
                if rel.startswith(lint._BARE_EXEMPT_FILES):
                    continue  # row 4: the changelog and its archive are exempt from every scan
                if rel.startswith(exempt_files) and "provenance_log" not in line:
                    continue  # row 3: the process docs are exempt from the path scan
                reviewed = next((h for r, o, h in REVIEWED_REWRITES if r == rel and line.strip().startswith(o)), None)
                if reviewed is not None:
                    assert _sha(line) == reviewed, f"{rel}:{n} changed upstream ({_sha(line)}): re-review it"
                    if _CHECK2_PATH.search(line):
                        fams = {fam for rr, nn, fam, _ in lint._upstream_occurrences() if rr == rel and nn == n}
                        assert fams and all(lint._FAMILY_MARKERS.get(fam, "\0") in rules for fam in fams), (rel, n, fams)
                    continue
                unreviewed.append(f"{rel}:{n}: {line.strip()[:120]}")
        assert not unreviewed, f"lines that look like contract 0026 file-presence rules, neither listed nor reviewed: {unreviewed}"

    def test_check_2_exempts_exactly_these_lines_by_installed_file_and_opening_words(self) -> None:
        row = _presence_row()
        for rel, opening, _sha_pin in FILE_PRESENCE:
            assert f"`{_installed(rel)}`" in row, _installed(rel)
            assert opening in row, opening
        # Only these lines, one "starting" span each, so the row can't gain a line the gate doesn't pin.
        assert row.count(" starting `") == len(FILE_PRESENCE), row.count(" starting `")
        assert "any other line in these files is checked as usual" in row
        # At run time row 6 matches by opening words alone, so a read added upstream must void it.
        assert "it is not exempt but a **REGRESSION**" in row
        # A backslash inside a code span is literal in Markdown: an agent would look for it.
        assert "\\`" not in row

    def test_the_provenance_scan_exempts_them_too(self) -> None:
        m = re.match(r"\| (\d+) \|", _presence_row())
        assert m
        row_no = m.group(1)
        prov = _audit().split("**Second scan: the on-disk provenance log.**", 1)[1].split("**Action on hit:**", 1)[0]
        assert f"row {row_no}" in prov, f"the provenance scan must exempt Check 2 row {row_no}"

    def test_the_contract_residue_audit_uses_the_same_row(self) -> None:
        cma = (_ROOT / "references" / "content-merge-audits.md").read_text()
        listed = cma.split("exactly the rows of the table in `post-operation-audit.md` Check 2", 1)[1].split(")", 1)[0]
        assert "contract 0026's file-presence lines" in listed
        # The transformer's own Audit 5 summary named fenced demos as the only exemption and halted on these.
        agent = (_ROOT / "agents" / "neuroloom-transformer.md").read_text()
        audit5 = agent.split("### Audit 5: Contract Residue", 1)[1].split("\n### ", 1)[0]
        assert "contract 0026's file-presence lines (row 6) are exempt line by line" in audit5

    def test_the_transformer_keeps_them_verbatim(self) -> None:
        agent = " ".join((_ROOT / "agents" / "neuroloom-transformer.md").read_text().split())
        # Pass 1's exclusion zones, Pass 2's prose regions and the Constraints all name the row, and no
        # warning is raised for these lines (Audit 6 halts on an unresolved one).
        assert "Contract 0026's file-presence lines, the closed list in `post-operation-audit.md` Check 2 row 6" in agent
        assert "and contract 0026's file-presence lines, `post-operation-audit.md` Check 2 row 6," in agent
        assert "Never transform contract 0026's file-presence lines" in agent
        # Pass 2 keeps them, so Audit 7 must not warn on the concept terms they carry.
        audit7 = agent.split("### Audit 7: Concept-Terminology Residue", 1)[1].split("### ", 1)[0]
        assert "Contract 0026's file-presence lines (`post-operation-audit.md` Check 2 row 6)" in audit7
        assert agent.count("emit no `transformation_warning` for them") >= 2
        assert "every mention of the file is rewritten (§ \"Provenance records\" in `pattern-mapping-rules.md`) except on the changelog's lines and the lines in the next bullet" in agent
        rules = (_ROOT / "references" / "pattern-mapping-rules.md").read_text()
        assert "**Contract 0026's file-presence lines are exempt from Pass 1 and Pass 2 — HARD EXCLUSION:**" in rules
        hard = rules.split("**Contract 0026's file-presence lines are exempt from Pass 1 and Pass 2", 1)[1].split("\n**", 1)[0]
        assert "`post-operation-audit.md` Check 2" in hard  # the one list; no second copy here


# The factory's access-control lines: they name the discipline and knowledge files a factory agent may commit, which
# the project's CODEOWNERS leaves without an owner and implement_guard.py's check_commits then lets through (it refuses
# what CODEOWNERS owns and GOVERNING_KNOWLEDGE), plus the two lines that act on that grant in words a row rewrites
# (sdlc-revise's hygiene paragraph, sdlc-audit's `hygiene` route). Post-operation Check 2 row 8 keeps them; (upstream
# path, opening words, sha16 of the whole item at the supported tag). An item runs from its opening line through every
# following line indented deeper than it, so factory.md's wrapped CODEOWNERS items are pinned with their continuation
# and nested lines.
FACTORY_ACCESS = [
    ("skills/sdlc-implement/SKILL.md", "- **Off-limits paths:**", "2e297ad679085bee"),
    ("skills/sdlc-revise/SKILL.md", "- **Off-limits paths:**", "2e297ad679085bee"),
    ("skills/sdlc-reproduce/SKILL.md", "- **Off-limits paths:**", "2e297ad679085bee"),
    ("skills/sdlc-revise/SKILL.md", "SDLC hygiene is part of the work:", "9d1c779a5ca2d359"),
    ("process/factory.md", "- CODEOWNERS on", "c26bacea39619c29"),
    ("process/factory.md", "- **Off-limits paths:**", "2e297ad679085bee"),
    ("process/factory.md", "- **Owner-less lines, after the owned ones,**", "c970aa9af1ef01eb"),
    ("process/factory.md", "- **Then owned again, after the owner-less lines**", "4d030a3cf0a7e55c"),
    ("process/factory.md", "- **The other knowledge YAMLs are agent-writable on purpose**", "9de3596be6b0f73f"),
    ("process/factory-runbook.md", "| E2 |", "67a3a4bacb2a5ac6"),
    ("skills/sdlc-audit/SKILL.md", "- `hygiene`: SDLC hygiene an agent may write", "e793ecd02d8a9663"),
]
# The other instructions that act on the grant, in words no scan or row matches, so they stay as upstream has them
# without a place on row 8.
UNTOUCHED_HYGIENE = [
    ("skills/sdlc-implement/SKILL.md", "**Fix what the issue names, and finish small related fixes here.**"),
    ("skills/sdlc-execute/SKILL.md", "**Add-ons and follow-ups.**"),
]


def _concept_row_phrases() -> list[str]:
    """The literal z-sdlc phrases the concept-term rows of pattern-mapping-rules.md match: each row's first cell, from
    the concept-terminology table through the heading-label table, before its parenthetical, without placeholders."""
    rules = lint._rules()
    start, end = "**Knowledge-layer concept terminology", "**Label-prefix-before-parenthetical"
    assert start in rules and end in rules, f"pattern-mapping-rules.md lost a heading the phrase list is cut by: {start!r} or {end!r}"
    body = rules.split(start, 1)[1].split(end, 1)[0]
    phrases = set()
    for ln in body.splitlines():
        if ln.startswith("| `"):
            cell = ln.split(" | ", 1)[0].split(" (", 1)[0]
            phrases |= {p for p in re.findall(r"`([^`]+)`", cell) if not re.search(r"[<\[]|\bN\b", p)}
    # A phrase with no word in it (punctuation from a malformed row) would match nearly every line.
    return sorted((p for p in phrases if re.search(r"[A-Za-z]{3}", p)), key=len, reverse=True)


# What a residue scan's pattern or a concept-term row's phrase matches: Check 2's path scan, the terms of Check 2b,
# Audit 5, Audit 7 and Pass 2's residue scan, the map's name in any case (Check 6 step 4), the provenance log, Check
# 2d's links, an unprefixed knowledge-layer path, the communication protocol's name (the port's named-YAML check), and
# every concept-term row's phrase. Path rows all name a `[sdlc-root]/` path, which the first pattern covers.
_ANY_SCAN = re.compile(
    "|".join([
        _RESIDUE.pattern, r"\bknowledge index\b|\bknowledge store gaps?\b|\bknowledge area\b",
        r"\]\((\./|\.\./)*(knowledge|disciplines|bundles)/", r"(?<![\w\]/.-])(knowledge|disciplines)/",
        r"\bagent-communication-protocol\b", *(r"(?<!\w)" + re.escape(p) + r"(?!\w)" for p in _concept_row_phrases()),
    ]),
    re.IGNORECASE,
)
# A line that hits _ANY_SCAN and says who may write what looks like an access-control line wherever it is, as the
# `hygiene` route in sdlc-audit, a core skill, does. A keyword tripwire, like _LOOKS_LIKE_PRESENCE.
_GRANT_VERBS = ("write", "edit", "commit", "change", "correct", "update", "modify", "touch", "append", "add")
_LOOKS_LIKE_GRANT = re.compile(
    r"(?i)CODEOWNERS|implement_guard|publish guard|write guard|owner-less|agent-writable|off-limits"
    r"|\b(?:an? agent|the agent|agents|you|it|they|a stage|this stage|the stage) (?:may|can) (?:" + "|".join(_GRANT_VERBS) + r")\b"
)


def _grant_lines_outside_row_8(release: Path, lines: Iterable[tuple[str, int, str]]) -> list[str]:
    return [f"{rel}:{n}: {line.strip()[:100]}" for rel, n, line in lines
            if _ANY_SCAN.search(line) and _LOOKS_LIKE_GRANT.search(line) and not _is_factory_access_line(release, rel, n)]


def _left_cell_patterns() -> list[re.Pattern[str]]:
    """Every phrase a row of pattern-mapping-rules.md matches, from its first cell before the cell's parenthetical notes,
    as a pattern: an exact-line row quotes its line there. `<X>` and bracketed placeholders other than `[sdlc-root]`
    match any text; a phrase whose literal text has no three-letter word (`<X>`, `, <section>`) is left out."""
    pats = []
    for ln in lint._rules().splitlines():
        if not ln.startswith("| ") or re.match(r"^\|[\s:|-]+\|\s*$", ln):
            continue
        cell = ln.replace("\\`", "\0").split(" | ", 1)[0].split(" (", 1)[0]
        for a, b in re.findall(r"``\s?(.+?)\s?``|`([^`]+)`", cell):
            parts = re.split(r"(<[^>]+>|\[(?!sdlc-root\])[^\]]+\])", (a or b).replace("\0", "`"))
            if not re.search(r"[A-Za-z]{3}", "".join(parts[0::2])):
                continue
            pats.append(re.compile("".join(".+?" if i % 2 else re.escape(s) for i, s in enumerate(parts)), re.IGNORECASE))
    return pats


_BUNDLE_MARKDOWN = ("skills", "process", "agents", "playbooks")
_BUNDLE_KEYS = {"description", "pilot", "fragments", "tree", "seed", "render", "requires", *_BUNDLE_MARKDOWN}


def _factory_files(release: Path) -> list[str]:
    """The skills and process docs of the factory bundle and of every bundle that requires it, per the release's manifest."""
    manifest = json.loads((release / "skeleton" / "manifest.json").read_text())
    bundles = {k: v for k, v in manifest["bundles"].items() if isinstance(v, dict)}
    names = {k for k, v in bundles.items() if k == "factory" or "factory" in (v.get("requires") or {}).get("bundles", [])}
    for k in names:
        unknown = set(bundles[k]) - _BUNDLE_KEYS
        assert not unknown, f"bundle {k} gained {unknown}: decide whether its files need the scan below"
        # A fragment's text lands in a framework file, which the completeness scan doesn't read.
        assert not bundles[k].get("fragments"), f"bundle {k} now injects fragments: scan their text too"
    return sorted({p for k in names for key in _BUNDLE_MARKDOWN for p in bundles[k].get(key, [])})


def _factory_item(release: Path, rel: str, opening: str) -> tuple[int, int, str]:
    """(first line, last line, text) of the one item that starts with `opening`, 1-based and inclusive."""
    lines = (release / rel).read_text().split("\n")
    hits = [i for i, ln in enumerate(lines) if ln.strip().startswith(opening)]
    assert len(hits) == 1, f"{rel}: {len(hits)} lines start {opening!r}; revisit Check 2 row 8"
    start = end = hits[0]
    depth = len(lines[start]) - len(lines[start].lstrip(" "))
    while end + 1 < len(lines) and lines[end + 1].strip() and len(lines[end + 1]) - len(lines[end + 1].lstrip(" ")) > depth:
        end += 1
    return start + 1, end + 1, "\n".join(lines[start : end + 1])


def _is_factory_access_line(release: Path, rel: str, n: int) -> bool:
    return any(rel == r and a <= n <= b for r, o, _h in FACTORY_ACCESS for a, b, _t in [_factory_item(release, r, o)])


def _row_openings(row: str) -> list[str]:
    """Row 8's items by opening words; a table row is named by its first cell, `| <cell> |` here."""
    spans = re.findall(r" (starting|whose first cell is) (?:`` (.+?) ``|`([^`]+)`)", row)
    return [(a or b) if kind == "starting" else f"| {a or b} |" for kind, a, b in spans]


def _row_pairs(row: str) -> set[tuple[str, str]]:
    """(installed file, opening) for each item row 8 lists: its list reads `in <files>, <items>; in <files>, <items>`."""
    listed = row.split("each item found by its opening words: ", 1)[1].split(". An item is", 1)[0]
    pairs = set()
    for clause in re.split(r"; (?=in `)", listed):
        files = re.findall(r"`((?:\.claude|ops/sdlc)/[^`]+)`", clause)
        pairs |= {(f, o) for f in files for o in _row_openings(clause)}
    return pairs


def _factory_row() -> str:
    rows = [r for r in _check2_rows() if "factory's access-control lines" in r]
    assert len(rows) == 1, "Check 2's table needs exactly one row for the factory's access-control lines"
    return rows[0]


class TestFactoryAccessControlLines074:
    """z-sdlc's factory bundle names `[sdlc-root]/disciplines/` and `[sdlc-root]/knowledge/` as repository paths for its
    write guard and CODEOWNERS. 0.7.3's generic rows rewrote those lines into memory-graph wording, so an installed
    factory doc said agents may write memory entries while the guard and CODEOWNERS govern files."""

    def test_each_item_is_still_upstream_unchanged(self, release: Path) -> None:
        for rel, opening, sha in FACTORY_ACCESS:
            _a, _b, text = _factory_item(release, rel, opening)
            assert _sha(text) == sha, f"{rel} item {opening!r} changed upstream ({_sha(text)}): re-review it before keeping it again"
            assert "provenance_log" not in text, (rel, opening)  # row 8 is not a provenance-scan exemption

    def test_the_bundle_files_come_from_the_manifest(self, release: Path) -> None:
        files = _factory_files(release)
        # The `hygiene` route is a core skill's; the write-grant tripwire, not the bundle scan, sees it.
        assert {rel for rel, _o, _h in FACTORY_ACCESS} - set(files) == {"skills/sdlc-audit/SKILL.md"}, files
        assert {"skills/sdlc-triage/SKILL.md", "process/factory-broker.md"} <= set(files), files

    def test_the_scan_regex_sees_the_concept_rows_phrases(self) -> None:
        for text in ("a parking lot candidate", "the rule file", "the agent's mapped files", "new YAML files",
                     "project-specific files", "see knowledge/testing/", "`agent-communication-protocol.yaml`",
                     "### Cross-File Contradiction", "per-file staleness"):
            assert _ANY_SCAN.search(text), text
        assert len(_concept_row_phrases()) > 50

    def test_every_line_a_scan_or_concept_row_matches_in_the_bundle_is_on_the_list(self, release: Path) -> None:
        outside = []
        for rel in _factory_files(release):
            for n, line in enumerate((release / rel).read_text().split("\n"), start=1):
                if _ANY_SCAN.search(line) and not _is_factory_access_line(release, rel, n):
                    outside.append(f"{rel}:{n}: {line.strip()[:100]}")
        assert not outside, f"factory bundle lines no Check 2 row 8 item covers (review each; keep it there, or give it a rule): {outside}"

    def _release_lines(self, release: Path) -> list[tuple[str, int, str]]:
        out = []
        for f in sorted(release.rglob("*.md")):
            rel = str(f.relative_to(release))
            if not (rel.startswith(_NOT_INSTALLED) or rel.startswith(lint._BARE_EXEMPT_FILES)):
                out += [(rel, n, line) for n, line in enumerate(f.read_text().split("\n"), start=1)]
        return out

    def test_every_line_elsewhere_that_looks_like_a_write_grant_is_on_the_list(self, release: Path) -> None:
        outside = _grant_lines_outside_row_8(release, self._release_lines(release))
        assert not outside, f"lines that say what an agent may write, on no Check 2 row 8 item: {outside}"

    def test_the_write_grant_tripwire_sees_each_grant_verb(self, release: Path) -> None:
        for verb in _GRANT_VERBS:
            for text in (f"Agents may {verb} discipline files.", f"An agent can {verb} the knowledge YAMLs."):
                assert _grant_lines_outside_row_8(release, [("skills/sdlc-plan/SKILL.md", 9999, text)]) == [
                    f"skills/sdlc-plan/SKILL.md:9999: {text}"], text

    def test_the_other_hygiene_instructions_match_no_scan_or_row(self, release: Path) -> None:
        for rel, opening in UNTOUCHED_HYGIENE:
            _n, line = _one_line(release, rel, opening)
            assert "knowledge entry" in line, (rel, opening)  # still an instruction that acts on the grant
            assert not _ANY_SCAN.search(line), f"{rel} {opening!r} now matches {_ANY_SCAN.search(line).group(0)!r}: put it on row 8"
            # An exact-line Pass 1 row quotes its line in its first cell; none may reach these paragraphs.
            hits = [pat.pattern[:60] for pat in _left_cell_patterns() if pat.search(line)]
            assert not hits, f"{rel} {opening!r}: a row of pattern-mapping-rules.md matches it: {hits}"
        row = _factory_row()
        assert "`sdlc-implement`" in row and "`sdlc-execute`" in row and "no row matches" in row

    def test_their_path_tokens_are_exempt_through_row_8_not_a_rule_family(self, release: Path) -> None:
        files = set(_factory_files(release))
        occ = [(rel, n) for rel, n, _fam, _l in lint._upstream_occurrences() if rel in files]
        assert len(occ) >= 20, occ  # 4 on each Off-limits bullet, 1 on `- CODEOWNERS on`, 3 in Enablement step 9
        _factory_row()  # exempt only once the row exists
        assert all(_is_factory_access_line(release, rel, n) for rel, n in occ), occ

    def test_check_2_row_8_names_exactly_these_items_by_installed_file_and_opening_words(self) -> None:
        row = _factory_row()
        assert row.startswith("| 8 |"), row[:20]
        # Each listed file with its own item's opening words, so naming an item under the wrong file fails.
        assert _row_pairs(row) == {(_installed(rel), opening) for rel, opening, _h in FACTORY_ACCESS}, _row_pairs(row)
        # A raw `|` would split the row into extra table cells; the runbook row is named by its first cell.
        assert "`| E2 |`" not in row and " whose first cell is `E2`" in row
        assert "any other line in these files is checked as usual" in row
        # Matched by opening words at run time, so a read added upstream must void it, as row 6's does.
        assert "it is not exempt but a **REGRESSION**" in row
        assert "/implement_guard.py`" in row and "/test_codeowners.py`" in row
        # check_commits refuses what CODEOWNERS owns and GOVERNING_KNOWLEDGE; SDLC_HYGIENE only labels the PR.
        assert "`check_commits`" in row and "`GOVERNING_KNOWLEDGE`" in row and "`SDLC_HYGIENE`" not in row
        assert "the one instruction" not in row
        assert "indented deeper" in row  # the extent rule for the wrapped items
        assert "\\`" not in row


class TestReleaseResidueHasAHome:
    def test_every_path_token_falls_in_a_family_with_a_rule_row(self, release: Path) -> None:
        rules = lint._rules()
        unregistered: dict[str, str] = {}
        missing: dict[str, str] = {}
        occ = lint._upstream_occurrences()
        assert len(occ) > 150, f"inventory looks wrong: only {len(occ)} occurrences"
        for rel, n, family, _line in occ:
            if family == "EXEMPT" or _is_presence_line(release, rel, n):
                continue
            if _is_factory_access_line(release, rel, n):
                _factory_row()  # exempt only once the row exists
                continue
            marker = lint._FAMILY_MARKERS.get(family)
            if marker is None:
                unregistered.setdefault(family, f"{rel}:{n}")
            elif marker not in rules:
                missing.setdefault(family, marker)
        assert not unregistered, f"{_TAG} phrasings with no registered rule family: {unregistered}"
        assert not missing, f"families whose rule row is gone from pattern-mapping-rules.md: {missing}"

    def test_every_bare_provenance_mention_has_a_row_or_is_a_file_presence_line(self, release: Path) -> None:
        rules = lint._rules()
        homeless = []
        for rel, n, family, line in lint._upstream_bare_provenance():
            if _is_presence_line(release, rel, n):
                _presence_row()  # exempt only once the row exists
                continue
            marker = lint._FAMILY_MARKERS.get(family)
            if marker is None or marker not in rules:
                homeless.append(f"{family} at {rel}:{n}: {line.strip()[:100]}")
        assert not homeless, homeless


def _one_line(release: Path, rel: str, opening: str) -> tuple[int, str]:
    lines = (release / rel).read_text().split("\n")
    hits = [(n, ln) for n, ln in enumerate(lines, start=1) if ln.strip().startswith(opening)]
    assert len(hits) == 1, f"{rel}: {len(hits)} lines start {opening!r}; re-review the 0.7.2 lists"
    return hits[0]


_MIGRATE = "skills/sdlc-migrate/SKILL.md"
# sdlc-migrate's lines that name the agent-context-map and stay as upstream has them: post-operation
# Check 6 step 4's closed list (opening words, sha16 of the line at the supported tag). §3.3 is kept
# as a region, from its adapter-delegation line (pinned below) to the next heading.
MAP_LINES_KEPT = [
    ("Source-to-project path mappings", "47a96489beddac46"),
    ("| **Context map** |", "bd415513d285500f"),
    ("Read and follow `[sdlc-root]/process/project-section-markers.md`", "3901f4dd0ee4a04f"),
    ("**Step 0 — Load exclusion list before any writes.**", "3d2ca31e877f2e62"),
    ("- `knowledge/**/*.yaml` the project doesn't have yet", "387f9b76a669a1b6"),
    ("3. For each moved/renamed file:", "65e6e64c70b8df7d"),
    ("# Verify all agent-context-map paths resolve", "b3f7333095ff1e66"),
    ("- All agent-context-map paths resolve:", "fa7e1171415c2e60"),
    # 0.7.3: the lines that capitalise the name, which the case-sensitive scans never saw.
    ("### 3.3 Update Agent-Context-Map (if needed)", "d49ebc51f87ba4ec"),
    ("> - Agent-context-map paths all resolve", "14203e27bbec3ced"),
    ("- Agent-context-map paths updated:", "78462cbcb14a039c"),
    ("- Agent-context-map agent names and project-specific mappings", "7a0e19ed78d5fa68"),
]
# §3.3's output in the report, which says "context-map" only and so is on no map-line list; the
# knowledge-update handler has it written as n/a when no map is on disk.
_NEW_ROLES_LINE = ("- New agent roles added to context-map: N [list roles]", "d93fe23126805e72")
_LOOP_LINE = ("for path in $(grep -E '^\\s+- ' [sdlc-root]/knowledge/agent-context-map.yaml", "20c506f437718dc8")
_MAP_ADAPTER_SKIP = ("**Adapter delegation:** If the adapter declares a `knowledge-update` phase and the project has no `agent-context-map.yaml`", "c8eb53d09c7e63bc")
_RECOVERY_LINE = "3. Manually re-apply project customizations from the backup"
_RECOVERY_SHA = "d0195705507fe214"
# §3.4's two lines that would have an agent edit the map: pattern-mapping-rules.md rewrites each by exact line.
MAP_LINES_REWRITTEN = [
    ("→ Suggest: add to agent-context-map.yaml", "8863b9a287ad2125"),
    ("- Agent knowledge wiring → edit `agent-context-map.yaml`", "11c3852a0c84a9df"),
]


class TestAgentContextMapLines:
    """Sleeved's 3.0.0 migration (plugin 0.7.1) kept §3.4's map-editing lines by Check 2b's reporting
    list, and post-operation Check 6 step 4 then called two lines regressions. Every line of the
    supported sdlc-migrate that names the map must now be on Check 6 step 4's closed list or have a
    rewrite row."""

    def _step4(self) -> str:
        return " ".join(_audit().split("4. All operations:", 1)[1].split("**Action on failure:**", 1)[0].split())

    def test_every_map_line_is_kept_by_the_list_or_rewritten_by_a_row(self, release: Path) -> None:
        lines = (release / _MIGRATE).read_text().split("\n")
        start, skip = _one_line(release, _MIGRATE, _MAP_ADAPTER_SKIP[0])
        assert _sha(skip) == _MAP_ADAPTER_SKIP[1], "§3.3's adapter line changed upstream: re-review the §3.3 region"
        end = next(n for n in range(start + 1, len(lines) + 1) if lines[n - 1].startswith("### "))
        kept = {_one_line(release, _MIGRATE, o)[0]: (o, h) for o, h in MAP_LINES_KEPT + [_LOOP_LINE]}
        rewritten = {_one_line(release, _MIGRATE, o)[0]: (o, h) for o, h in MAP_LINES_REWRITTEN}
        unlisted, scanned = [], set()
        for n, line in enumerate(lines, start=1):
            # Any case: Audit 5 greps with -i, and halted on `> - Agent-context-map paths all resolve` (Sleeved, 0.7.2).
            if "agent-context-map" not in line.lower():
                continue
            scanned.add(n)
            if _is_presence_line(release, _MIGRATE, n) or start <= n < end:
                continue
            entry = kept.get(n) or rewritten.get(n)
            if entry is None:
                unlisted.append(f"{n}: {line.strip()[:100]}")
                continue
            assert _sha(line) == entry[1], f"sdlc-migrate:{n} changed upstream ({_sha(line)}): re-review it"
        assert not unlisted, f"sdlc-migrate lines naming the map on neither list: {unlisted}"
        assert {817, 1019, 1151, 1179} <= scanned, "the scan no longer sees the lines that capitalise the name"

    def test_no_other_file_of_sdlc_migrate_names_the_map_unlisted(self, release: Path) -> None:
        listed = {"skills/sdlc-migrate/references/recovery-procedures.md": [(_RECOVERY_LINE, _RECOVERY_SHA)]}
        unlisted = []
        for f in sorted((release / "skills" / "sdlc-migrate").rglob("*.md")):
            rel = str(f.relative_to(release))
            if rel == _MIGRATE:
                continue
            for n, line in enumerate(f.read_text().split("\n"), start=1):
                if "agent-context-map" not in line.lower():
                    continue
                hit = next((sha for o, sha in listed.get(rel, []) if line.strip().startswith(o)), None)
                if hit is None:
                    unlisted.append(f"{rel}:{n}: {line.strip()[:100]}")
                else:
                    assert _sha(line) == hit, f"{rel}:{n} changed upstream ({_sha(line)}): re-review it"
        assert not unlisted, unlisted
        assert _RECOVERY_LINE in self._step4()

    def test_check_6_step_4_lists_the_kept_lines(self) -> None:
        step4 = self._step4()
        for opening, _h in MAP_LINES_KEPT:
            assert opening in step4, opening
        assert "`**Adapter delegation:**` up to the next heading" in step4

    def test_the_new_roles_report_line_is_upstreams(self, release: Path) -> None:
        n, line = _one_line(release, _MIGRATE, _NEW_ROLES_LINE[0])
        assert _sha(line) == _NEW_ROLES_LINE[1], f"sdlc-migrate:{n} changed upstream ({_sha(line)}): re-review knowledge-update's n/a line"
        lifecycle = " ".join((_ROOT / "references" / "adapter-lifecycle.md").read_text().split())
        assert "`New agent roles added to context-map: n/a (no map: Neuroloom holds the knowledge layer)`" in lifecycle

    def test_the_rules_rewrite_the_two_wiring_lines(self) -> None:
        rules = lint._rules()
        for opening, _h in MAP_LINES_REWRITTEN:
            assert opening in rules, opening


class TestInlineConditionalScan:
    def test_the_only_upstream_hits_are_the_auditors_detector_list(self, release: Path) -> None:
        patterns = ("(Neuroloom projects:", "(skip for Neuroloom", "(Neuroloom projects use")
        hits = []
        for f in sorted(release.rglob("*.md")):
            rel = str(f.relative_to(release))
            if rel.startswith(_NOT_INSTALLED) or rel.startswith(lint._BARE_EXEMPT_FILES):
                continue
            for n, line in enumerate(f.read_text().split("\n"), start=1):
                if any(p in line for p in patterns):
                    hits.append((rel, line.strip()))
        assert hits and all(rel == "agents/sdlc-compliance-auditor.md" for rel, _ in hits), hits
        # Check 3's exemption: a list item that opens with the pattern in backticks.
        assert all(re.match(r"- `\((Neuroloom projects:|skip for Neuroloom|Neuroloom projects use)`( — |$)", ln) for _, ln in hits), hits
        assert len(hits) == 3


_INGEST = "skills/sdlc-ingest/SKILL.md"
INGEST_KEPT = [
    ("| Validated, testable rules |", "90c062c710db64c9"),
    ("| Promising but unvalidated insights |", "51bbf6f2e8addb42"),
    ("| Cross-discipline insights |", "4cf0142f050e5340"),
    ("**Parking lot entry format:**", "89aee91d1ee1f4a4"),
    ("**Knowledge file placement:**", "7392adf79cc2b63e"),
    ("- `files-created`:", "7347d2c5e6cb1e55"),
    ("- `files-updated`:", "8e103932d24c15f1"),
    ("SUMMARY: [total new rules] rules extracted across [count] knowledge files,", "ce2eb58bd09792b0"),
    ("KNOWLEDGE FILES", "933bba56847da6d3"),
    ("Created: [list of new YAML files with rule count]", "d3e7a968c8b93d00"),
    ("Updated: [list of existing files with new rule count]", "000fa2e1b79ecbd2"),
    # Kept except its one README read (F5): `[sdlc-root]/knowledge/README.md` § "spec_relevant Field"
    # becomes `[sdlc-root]/process/knowledge-routing.md` § "spec_relevant Field".
    ("**`spec_relevant` tagging:**", "ac1cd31b5d672717"),
]
INGEST_REPLACED = [
    ("- Write new YAML files or append to existing ones", "ac615dea967c6fa6"),
    ("- Update the knowledge store's `README.md` to list new files", "2fdb515d7837268f"),
    ("- If new files are created, add them to the README's structure listing", "107591a06dea8ece"),
    ("### 6. Wire to Agents", "2d6ede173123eaed"),
    ("### 7. Provenance", "70d985194016566d"),
    ("AGENT WIRING", "6c512b7a5a0743fc"),
    ("Unmapped discipline: [if no agents map to this discipline] | n/a", "25a2eb236045ecb9"),
    ("wired to [count] agents. [count] items to parking lot", "8e04c90558d40e9d"),
    ("| \"I'll skip wiring since I created the files\" |", "28785041f735d2fc"),
    ("| \"I'll wire to all agents\" |", "e6e376b6e8aeaad4"),
    ("- **Uses:** file reading, existing knowledge stores (for deduplication)", "1d0fd9348513b793"),
    ('- Continue existing rule ID sequences', "f9cdfcce9dc64f7b"),
    ('- **ID** — sequential within its file', "1f5d1faaf1eef889"),
    ("**If the discipline doesn't have YAML conventions yet:**", "ad90c890882f1acd"),
    ('- **Downstream:** after ingestion', "58acaa824b550008"),
    ("**Rule format (follow existing conventions in the target knowledge store):**", "6eeee68bb13804fe"),
    ('| "I\'ll create new YAML conventions for this discipline" |', "244971ccf6cfd356"),
    ("- If the target discipline already has YAML files", "00e244c343b46e51"),
    # Round 4: the last two lines that sent the writer to file-mode conventions or an inert field.
    ("Organize extracted rules into structured YAML files", "99fd7e82e147bc8c"),
    ("- If ingested knowledge is likely spec-relevant", "4c1046d01a1337c3"),
]


class TestSdlcIngestWritesFiles:
    def _section(self) -> str:
        rules = lint._rules()
        head = "**`sdlc-ingest` writes files; its Post-Execution Transform sends them"
        return rules.split(head, 1)[1].split("**Fenced code blocks are structurally exempt", 1)[0]

    def test_kept_and_replaced_lines_are_still_upstreams(self, release: Path) -> None:
        for opening, sha in INGEST_KEPT + INGEST_REPLACED:
            _n, line = _one_line(release, _INGEST, opening)
            assert _sha(line) == sha, f"sdlc-ingest line {opening!r} changed upstream ({_sha(line)}): re-review it"

    def test_the_rules_name_each_line(self) -> None:
        section = self._section()
        for opening, _h in INGEST_KEPT + INGEST_REPLACED:
            assert opening.strip() in section, opening

    def test_check_2_row_7_exempts_the_two_destination_rows(self) -> None:
        row = next(r for r in _check2_rows() if r.startswith("| 7 |"))
        assert "`.claude/skills/sdlc-ingest/`" in row
        assert "`Validated, testable rules`" in row and "`Promising but unvalidated insights`" in row


class TestSdlcAuditWireRows:
    """sdlc-audit's prune triage sends "wire" to sdlc-ingest step 6; Sleeved's 0.7.1 install had the
    transformer improvise memory_store copies tagged sdlc:agent: there. Two exact-line rows replace
    them, so each row's line must still be upstream's, word for word."""

    LINES = [
        ("skills/sdlc-audit/SKILL.md",
         "Wiring uses the same flow as sdlc-ingest step 6 — present candidate agents, update `[sdlc-root]/knowledge/agent-context-map.yaml`."),
        ("skills/sdlc-audit/references/compliance-methodology.md",
         "- **Wire:** Run the wiring flow from sdlc-ingest step 6 — present candidate agents, let CD select, update `[sdlc-root]/knowledge/agent-context-map.yaml`."),
    ]

    def test_each_rows_line_is_upstreams(self, release: Path) -> None:
        rules = lint._rules()
        for rel, text in self.LINES:
            assert (release / rel).read_text().count(text) == 1, rel
            assert f"``{text}``" in rules, text


_METHODOLOGY = "skills/sdlc-audit/references/compliance-methodology.md"


class TestComplianceMethodologyRows073:
    """No row wrote compliance-methodology.md's 6b table or 6k.1 exclusion list, so Sleeved's 3.0.0 migration
    on 0.7.1 left them in file-mode form and Check 2 called the list's map line a REGRESSION. The rows that
    write them are scoped to their section; these pins say the lines they match are still upstream's, once each."""

    # (opening words, sha16 of the line at the supported tag)
    LINES_6K1 = [
        ("- `[sdlc-root]/knowledge/agent-context-map.yaml` itself", "25b6e5d955bd1b00"),
        ("- `README.md` files", "d4c8293ac548f773"),
    ]
    HEADER_6B = ("| Directory | Purpose |", "5628acd9623d90d6")
    HEADING_6B = ("### 6b. Knowledge Stores (`[sdlc-root]/knowledge/`)", "e3afa07604c9207d")

    def _section(self, release: Path, heading: str) -> list[str]:
        lines = (release / _METHODOLOGY).read_text().split("\n")
        start = next(i for i, ln in enumerate(lines) if ln.startswith(heading))
        end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("#"))
        return lines[start:end]

    def test_the_6k1_lines_are_upstreams_and_in_step_6k1(self, release: Path) -> None:
        lines = (release / _METHODOLOGY).read_text().split("\n")
        excl = lines.index("Exclude from orphan detection:")
        for opening, sha in self.LINES_6K1:
            n, line = _one_line(release, _METHODOLOGY, opening)
            assert _sha(line) == sha, f"compliance-methodology.md:{n} changed upstream ({_sha(line)}): re-review its row"
            assert excl < n - 1 <= excl + 3, f"{opening!r} is no longer in 6k.1's exclusion list"

    def test_the_6b_header_is_upstreams_and_every_row_names_a_folder(self, release: Path) -> None:
        n, line = _one_line(release, _METHODOLOGY, self.HEADER_6B[0])
        assert _sha(line) == self.HEADER_6B[1], f"compliance-methodology.md:{n} changed upstream ({_sha(line)})"
        section = self._section(release, "### 6b. ")
        assert line in section
        rows = [ln for ln in section if ln.startswith("|")][2:]  # past the header and the separator
        assert rows and all(re.fullmatch(r"\| `[a-z-]+/` \| [^|]+ \|", ln) for ln in rows), rows

    def test_the_6b_heading_is_upstreams_and_has_its_row(self, release: Path) -> None:
        n, line = _one_line(release, _METHODOLOGY, self.HEADING_6B[0])
        assert line == self.HEADING_6B[0] and _sha(line) == self.HEADING_6B[1], f"compliance-methodology.md:{n} changed upstream"
        assert f"| `` {line} `` " in lint._rules()


class TestSdlcReflectContextAndResearchDryLine073:
    """The rows sdlc-reflect's and sdlc-research's lines reach depend on upstream's wording of them."""

    def test_reflect_still_writes_the_session_context(self, release: Path) -> None:
        _n, line = _one_line(release, "skills/sdlc-reflect/SKILL.md", "**Context format:**")
        assert line.startswith("**Context format:** `[session: {brief-slug}]`"), line
        assert "`[session: {slug}]`" in lint._rules()

    def test_research_dry_note_still_says_ingest_produces_knowledge_yaml(self, release: Path) -> None:
        _n, line = _one_line(release, "skills/sdlc-research/SKILL.md", "- **DRY notes:**")
        assert "`sdlc-ingest` produces knowledge YAML in `[sdlc-root]/knowledge/`." in line, line



def _structure(lines: list[str]) -> tuple[int, int, int]:
    """Audit 1's fenced-block, bullet and table-row counts (bullets outside fences; no header or separator rows)."""
    sep = re.compile(r"^\|[\s:|-]+\|\s*$")
    fence, fences, bullets, rows = False, 0, 0, 0
    for i, ln in enumerate(lines):
        if ln.startswith("```"):
            fences, fence = fences + 1, not fence
            continue
        if fence:
            continue
        bullets += bool(re.match(r"^\s*[-*] ", ln))
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if re.match(r"^\|.*\|.*\|\s*$", ln) and not sep.match(ln) and not sep.match(nxt):
            rows += 1
    return fences // 2, bullets, rows


def _apply_ingest_drops(lines: list[str]) -> list[str]:
    """What pattern-mapping-rules.md § "`sdlc-ingest` writes files" removes, applied to upstream's text."""
    out, i = [], 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith(("- Update the knowledge store's `README.md` to list new files",
                         "- If new files are created, add them to the README's structure listing",
                         "| \"I'll wire to all agents\" |")):
            i += 1
            continue
        if lines[i].startswith("### 6. Wire to Agents"):
            out += ["### 6. Wire to Agents", "", "Nothing to wire in this project.", ""]
            while not lines[i].startswith("### 7. Provenance"):
                i += 1
            continue
        if s == "AGENT WIRING":
            out += ["AGENT WIRING", "  Not needed: agents find a new rule through their Knowledge Context search; parking-lot bullets are found by the discipline search (`tag_prefixes=[\"sdlc:discipline\"]`)"]
            while not lines[i].strip().startswith("Unmapped discipline:"):
                i += 1
            i += 1
            continue
        out.append(lines[i])
        i += 1
    return out


class TestAudit1KnowsSdlcIngestsDrops:
    """Round 3: Audit 1 halts when a file has more than one fewer fence, bullet or row than upstream,
    and 0.7.2's sdlc-ingest drops some on purpose. Both Audit 1 texts must set them aside, with the
    numbers this computes from the supported release."""

    def test_the_stated_drop_matches_the_release(self, release: Path) -> None:
        lines = (release / _INGEST).read_text().split("\n")
        up, post = _structure(lines), _structure(_apply_ingest_drops(lines))
        assert tuple(a - b for a, b in zip(up, post)) == (2, 9, 1), (up, post)
        sentence = "a 0.7.2 output of that skill has two fenced blocks, nine bullets and one table row fewer than upstream"
        assert sentence in " ".join((_ROOT / "references" / "content-merge-audits.md").read_text().split())
        agent = " ".join((_ROOT / "agents" / "neuroloom-transformer.md").read_text().split())
        assert "`content-merge-audits.md` § \"Planned drops\"" in agent.split("### Audit 1: Structural Content-Loss", 1)[1][:1500]


# Audit 1's planned drops: the upstream lines pattern-mapping-rules.md removes whole on purpose, which
# content-merge-audits.md § "Planned drops" lists (installed path, opening words, sha16 at the supported tag).
# Step 6 of sdlc-ingest is a region, pinned by its heading in INGEST_REPLACED.
PLANNED_DROPS = [
    ("skills/sdlc-ingest/SKILL.md", "- Update the knowledge store's `README.md` to list new files", "2fdb515d7837268f"),
    ("skills/sdlc-ingest/SKILL.md", "- If new files are created, add them to the README's structure listing", "107591a06dea8ece"),
    ("skills/sdlc-ingest/SKILL.md", "| \"I'll wire to all agents\" |", "e6e376b6e8aeaad4"),
    ("skills/sdlc-audit/references/compliance-methodology.md", "- `provenance_log.md`", "30a7522058bf4293"),
]
# Every rule in pattern-mapping-rules.md that removes text, reviewed against the supported release: a table row
# whose replacement mentions dropping, removing, deleting or omitting (or is empty), and a prose line saying
# something "is dropped" or "are dropped". Keyed by the row's left cell, or the prose line up to that phrase,
# matched exactly. Each value is the regex for the upstream lines the rule applies to.
#
# WHOLE_DROPS remove whole lines: what they match upstream must be exactly their Audit 1 planned drops.
WHOLE_DROPS = {
    'a bare list item `- provenance_log.md` in an exclusion list': (r"^\s*- `?provenance_log\.md`?\s*$", {('skills/sdlc-audit/references/compliance-methodology.md', "- `provenance_log.md`")}),
    '`Update the knowledge store\'s README.md to list new files` / `add them to the README\'s structure listing and "Knowledge Categories" table`': (
        r"Update the knowledge store's `?README\.md`? to list new files|add them to the README's structure listing",
        {('skills/sdlc-ingest/SKILL.md', PLANNED_DROPS[0][1]), ('skills/sdlc-ingest/SKILL.md', PLANNED_DROPS[1][1])},
    ),
    "3. **Step 5's README bullets are dropped": (
        r"Update the knowledge store's `?README\.md`? to list new files|add them to the README's structure listing",
        {('skills/sdlc-ingest/SKILL.md', PLANNED_DROPS[0][1]), ('skills/sdlc-ingest/SKILL.md', PLANNED_DROPS[1][1])},
    ),
    '- the Red Flags row starting `| "I\'ll wire to all agents" |` is dropped': (r"^\s*\| \"I'll wire to all agents\" \|", {('skills/sdlc-ingest/SKILL.md', PLANNED_DROPS[2][1])}),
}
# PART_DROPS remove part of a line; REPLACES write a line in place of the one they match. Each pins the upstream
# lines it matches (path, sha16), so an upstream bullet such a rule would consume whole fails the gate.
PART_DROPS = {
    '`sdlc-migrate`: `provenance_log.md` in the list of project-specific files that must never be overwritten (also the `Current exclusions:` list of Step 0)': (r"`agent-context-map\.yaml`, `provenance_log\.md`", {('skills/sdlc-migrate/SKILL.md', "47a96489beddac46"), ('skills/sdlc-migrate/SKILL.md', "3d2ca31e877f2e62")}),
    "`sdlc-migrate`: `NOT knowledge/provenance_log.md; that's project-specific` after the `knowledge/README.md` copy entry": (r"NOT `?knowledge/provenance_log\.md`?; that's project-specific", {('skills/sdlc-migrate/SKILL.md', "81e64025c50bf62c")}),
    '`sdlc:knowledge` together with `sdlc:agent:<a>` (with or without a domain tag)': (r'tags=\[[^\]]*"sdlc:agent:', set()),  # project calls, not upstream text
    'a markdown link whose target is the map: `A map ([\\`knowledge/agent-context-map.yaml\\`](knowledge/agent-context-map.yaml)) names the structured YAML knowledge files each agent role should read before it works` (the link has no `[sdlc-root]/` prefix, and the target does not exist in a Neuroloom project)': (r"\]\(knowledge/agent-context-map\.yaml\)", set()),
    'a markdown link whose target is a relative `disciplines/…` or `knowledge/…` path with no `[sdlc-root]/` prefix (the file does not exist in a Neuroloom project): `([\\`disciplines/README.md\\`](disciplines/README.md))`': (r"\]\((?:\./|\.\./)*(?:disciplines|knowledge)/[^)]*\)", set()),
    "`knowledge store's README.md` (live reference to file-mode index)": (r"(?i)knowledge store's `?README\.md", {('skills/sdlc-ingest/SKILL.md', "2fdb515d7837268f")}),  # whole by WHOLE_DROPS there
    "`knowledge index` (bare, describing the knowledge layer's table of contents)": (r"(?i)\bknowledge index\b", set()),
    '`under the ## Parking Lot heading` / `under the Parking Lot heading` / `in the parking lot section` (markdown-structure reference to discipline file layout)': (r"(?i)under the `?(?:## )?Parking Lot`? heading|in the parking lot section", {("process/discipline_capture.md", "09a8bd662f041553")}),
    "- in the Integration section's line starting `- **Uses:** file reading, existing knowledge stores (for deduplication)`, the item `` `[sdlc-root]/knowledge/agent-context-map.yaml` (for wiring) `` is dropped": (r"`\[sdlc-root\]/knowledge/agent-context-map\.yaml` \(for wiring\)", {('skills/sdlc-ingest/SKILL.md', "1d0fd9348513b793")}),
}
REPLACES = {
    '`1. Read [sdlc-root]/knowledge/provenance_log.md` (select a record by status, e.g. `approved-for-ingest`)': (r"^\s*1\. Read `?\[sdlc-root\]/knowledge/provenance_log\.md`?\s*$", {('skills/sdlc-ingest/SKILL.md', "655661f0fbad64e3")}),
    '`**\\`[sdlc-root]/knowledge/[discipline]/README.md\\`** — updated structure listing`': (r"\*\*`\[sdlc-root\]/knowledge/\[discipline\]/README\.md`\*\* — updated structure listing", {('skills/sdlc-ingest/SKILL.md', "014d147718854c3b")}),
}
# Rows whose replacement names a removal verb only to explain the text it writes (a full tag list,
# or the article a query drops), not to drop upstream text.
NOT_DROPS = {
    "`Consult [sdlc-root]/knowledge/agent-context-map.yaml for where <X> live(s)` (with or without backticks around the path; `<X>` is a noun phrase such as `the project's standing principles`; fires before the generic `for <purpose>` row below)",
    "`update that entry's status to \\`ingested\\` and populate the ingestion fields` (also `update the selected provenance entry's status to \\`ingested\\``)",
    "`the user approves them to \\`approved-for-ingest\\`` (the approval step, which upstream does by editing the file)",
}
_REMOVES = re.compile(r"(?i)\b(drop\w*|remov\w*|delet\w*|omit\w*|strip\w*|leave out|left out|not kept)\b")
_PROSE_DROP = re.compile(r"(?i)\b(is|are|be|been|get|gets|got)\s+(dropped|removed|deleted|omitted|stripped|left out)\b")
_EMPTY_REPLACEMENT = ("", "(nothing)", "(none)", "-", "nothing", "none")


def _rule_line(rules: str, key: str) -> str:
    """The one line of pattern-mapping-rules.md a classified key names: a table row by its exact left cell, or a prose line by its start."""
    hits = [ln for ln in rules.splitlines()
            if (ln.strip().strip("|").split(" | ")[0].strip() == key if ln.startswith("|") else ln.strip().startswith(key))]
    assert len(hits) == 1, f"{len(hits)} lines of pattern-mapping-rules.md match {key[:60]!r}"
    return hits[0]


# sha16 of each classified rule's full line, so an edit to a reviewed row (its replacement included) fails
# until the row is reviewed and its class and pin updated.
RULE_PINS = {
    'a bare list item `- provenance_log.md` in an exclusion list': '8ceabb3fae65b7d8',
    '`Update the knowledge store\'s README.md to list new files` / `add them to the README\'s structure listing and "Knowledge Categories" table`': '23ad58c79c631949',
    "3. **Step 5's README bullets are dropped": '99fa61e382244810',
    '- the Red Flags row starting `| "I\'ll wire to all agents" |` is dropped': 'db99a75de0da9571',
    '`sdlc-migrate`: `provenance_log.md` in the list of project-specific files that must never be overwritten (also the `Current exclusions:` list of Step 0)': 'ac7e5d09e7117700',
    "`sdlc-migrate`: `NOT knowledge/provenance_log.md; that's project-specific` after the `knowledge/README.md` copy entry": '2189368006afe230',
    '`sdlc:knowledge` together with `sdlc:agent:<a>` (with or without a domain tag)': '569887649dcbbf8b',
    'a markdown link whose target is the map: `A map ([\\`knowledge/agent-context-map.yaml\\`](knowledge/agent-context-map.yaml)) names the structured YAML knowledge files each agent role should read before it works` (the link has no `[sdlc-root]/` prefix, and the target does not exist in a Neuroloom project)': 'ebac64517a3f584c',
    'a markdown link whose target is a relative `disciplines/…` or `knowledge/…` path with no `[sdlc-root]/` prefix (the file does not exist in a Neuroloom project): `([\\`disciplines/README.md\\`](disciplines/README.md))`': '9c462fc7969aca9b',
    "`knowledge store's README.md` (live reference to file-mode index)": '3b849fd04662e6af',
    "`knowledge index` (bare, describing the knowledge layer's table of contents)": '2682b95e2ddd70db',
    '`under the ## Parking Lot heading` / `under the Parking Lot heading` / `in the parking lot section` (markdown-structure reference to discipline file layout)': 'e87930a8d66f7bae',
    "- in the Integration section's line starting `- **Uses:** file reading, existing knowledge stores (for deduplication)`, the item `` `[sdlc-root]/knowledge/agent-context-map.yaml` (for wiring) `` is dropped": 'bb81cca0658ccf21',
    '`1. Read [sdlc-root]/knowledge/provenance_log.md` (select a record by status, e.g. `approved-for-ingest`)': '8152dae27ade80a3',
    '`**\\`[sdlc-root]/knowledge/[discipline]/README.md\\`** — updated structure listing`': '8f088c792a2ca284',
    "`Consult [sdlc-root]/knowledge/agent-context-map.yaml for where <X> live(s)` (with or without backticks around the path; `<X>` is a noun phrase such as `the project's standing principles`; fires before the generic `for <purpose>` row below)": '6ef2c53055100e17',
    "`update that entry's status to \\`ingested\\` and populate the ingestion fields` (also `update the selected provenance entry's status to \\`ingested\\``)": '2ee5589cdb4ebdad',
    '`the user approves them to \\`approved-for-ingest\\`` (the approval step, which upstream does by editing the file)': 'ded848bdcd8a1c96',
}


def _planned_drops_doc() -> str:
    cma = (_ROOT / "references" / "content-merge-audits.md").read_text()
    return " ".join(cma.split("**Planned drops", 1)[1].split("\n\n", 1)[0].split())


def _removing_rules(rules: str) -> list[str]:
    keys = []
    for ln in rules.splitlines():
        if ln.startswith("|"):
            if re.match(r"^\|[\s:|-]+\|\s*$", ln):
                continue
            cells = ln.strip().strip("|").split(" | ")
            rep = " | ".join(cells[1:]).strip()
            if len(cells) < 2 or _REMOVES.search(rep) or rep.strip(" |").lower() in _EMPTY_REPLACEMENT:
                keys.append(cells[0].strip())
        elif (m := _PROSE_DROP.search(ln)):
            keys.append(ln.strip()[: ln.strip().index(m.group(0)) + len(m.group(0))])
    return keys


def _matches(release: Path, rx: str) -> list[tuple[str, str, str]]:
    found = []
    for f in sorted(release.rglob("*.md")):
        rel = str(f.relative_to(release))
        if rel.startswith(_NOT_INSTALLED) or rel.startswith(lint._BARE_EXEMPT_FILES):
            continue
        found += [(rel, ln, _sha(ln)) for ln in f.read_text().split("\n") if re.search(rx, ln)]
    return found


def _planned_opening(rel: str, line: str) -> str:
    """The PLANNED_DROPS opening a line starts with, or the line itself when it is on no list."""
    return next((o for r, o, _h in PLANNED_DROPS if r == rel and line.strip().startswith(o)), line.strip()[:80])


class TestAudit1PlannedDrops073:
    """Round 2: Audit 1 allows one missing bullet for a project's own change, and a drop row used it up
    unseen. Audit 1 now subtracts a closed per-file list of planned drops, and every rule that removes
    text is classified here against the supported release."""

    def test_each_listed_line_is_upstreams_and_named_in_the_list(self, release: Path) -> None:
        doc = _planned_drops_doc()
        for rel, opening, sha in PLANNED_DROPS:
            n, line = _one_line(release, rel, opening)
            assert _sha(line) == sha, f"{rel}:{n} changed upstream ({_sha(line)}): re-review the planned drops"
            assert f"`{_installed(rel)}`" in doc, rel
            assert opening in doc, opening

    def test_every_rule_that_removes_text_is_classified(self) -> None:
        keys = _removing_rules(lint._rules())
        known = {**WHOLE_DROPS, **PART_DROPS, **REPLACES, **dict.fromkeys(NOT_DROPS)}
        unclassified = [k for k in keys if k not in known]
        assert not unclassified, f"rules that remove text, neither a planned drop nor reviewed as partial: {unclassified}"
        stale = [k for k in known if k not in keys]
        assert not stale, f"classified rules no longer in pattern-mapping-rules.md: {stale}"

    def test_each_classified_rule_is_pinned(self) -> None:
        rules = lint._rules()
        known = [*WHOLE_DROPS, *PART_DROPS, *REPLACES, *NOT_DROPS]
        assert sorted(RULE_PINS) == sorted(known), "RULE_PINS and the classified rules differ"
        changed = [k[:60] for k in known if _sha(_rule_line(rules, k)) != RULE_PINS[k]]
        assert not changed, f"classified rules edited since review (re-review each, then its class and pin): {changed}"

    def test_whole_line_drops_are_exactly_the_planned_ones(self, release: Path) -> None:
        planned = {(rel, o) for rel, o, _h in PLANNED_DROPS}
        reached = set()
        for key, (rx, targets) in WHOLE_DROPS.items():
            assert targets <= planned, (key, targets - planned)
            hit = {(rel, _planned_opening(rel, ln)) for rel, ln, _s in _matches(release, rx)}
            assert hit == targets, f"{key[:60]}: upstream lines it drops whole {hit} are not its planned drops {targets}"
            reached |= targets
        assert reached == planned, f"planned drops no rule removes: {planned - reached}"
        # The doc names exactly these lines (a quoted row name is not a listed line).
        doc = _planned_drops_doc()
        for key in WHOLE_DROPS:
            doc = doc.replace(key, "")
        spans = {s.strip() for s in re.findall(r"``(.+?)``|`([^`]+)`", doc) for s in s if s.strip().startswith(("- ", "| "))}
        assert spans == {o for _r, o, _h in PLANNED_DROPS}, spans

    def test_partial_drops_and_replacements_never_take_a_whole_line(self, release: Path) -> None:
        for key, (rx, pins) in {**PART_DROPS, **REPLACES}.items():
            hits = _matches(release, rx)
            assert {(rel, sha) for rel, _ln, sha in hits} == pins, f"{key[:60]}: matched upstream lines changed: {[(r, s, ln[:60]) for r, ln, s in hits]}"
            if key in REPLACES:
                continue
            for rel, ln, _sha16 in hits:
                if re.match(r"^\s*([-*]|\d+\.|\|) ", ln):
                    rest = re.sub(r"[\s\-*|`.,;:()>]", "", re.sub(rx, "", ln))
                    assert rest, f"{rel}: {key[:60]} would remove the whole line {ln.strip()[:80]}"



# ---- F5: the READMEs the extractor never sends ------------------------------------------------------

_EXTRACTOR = _ROOT / "skills" / "sdlc-port" / "scripts" / "extract_sdlc_knowledge.py"
_MAP_AND_LOG = {"knowledge/agent-context-map.yaml", "knowledge/provenance_log.md"}
_NO_READER_RE = re.compile(r"`((?:knowledge|disciplines)/(?:[\w-]+/)*(?:README\.md|[\w-]+\.d2))`")


@pytest.fixture(scope="module")
def kd(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """z-sdlc's knowledge/ and disciplines/ at the supported tag, exported with git archive."""
    out = tmp_path_factory.mktemp("zsdlc-kd")
    tar = subprocess.run(
        ["git", "-C", str(_UPSTREAM), "archive", _TAG, "knowledge", "disciplines"],
        capture_output=True, check=True, timeout=60,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(out, filter="data")
    return out


def _lifecycle_step_11_list_bullet() -> str:
    text = (_ROOT / "references" / "adapter-lifecycle.md").read_text()
    step11 = text.split("11. **Take the copies Neuroloom holds**", 1)[1].split("\n---\n", 1)[0]
    return step11.split("- **List**", 1)[1]


def _no_reader_list() -> set[str]:
    return set(_NO_READER_RE.findall(_lifecycle_step_11_list_bullet()))


def _extractor_named(kd: Path, tmp: Path) -> set[str]:
    out = tmp / "seed.json"
    subprocess.run(
        [sys.executable, str(_EXTRACTOR), "--upstream", "--no-manifest", "--knowledge-dir", str(kd / "knowledge"),
         "--disciplines-dir", str(kd / "disciplines"), "--version", _TAG.lstrip("v"), "--output", str(out)],
        capture_output=True, check=True, timeout=120,
    )
    named: set[str] = set()
    for f in sorted(tmp.glob("seed*.json")):
        for e in json.loads(f.read_text())["entries"]:
            root = "knowledge" if "sdlc:knowledge" in e["tags"] else "disciplines"
            named.add(f"{root}/{e['source_path']}")
    return named


def _upstream_files(kd: Path) -> set[str]:
    return {p.relative_to(kd).as_posix() for root in ("knowledge", "disciplines") for p in (kd / root).rglob("*") if p.is_file()}


def _slice(text: str, start: str, level: int) -> str:
    """The text under heading `start` up to the next heading of the same or a higher level."""
    body = text.split(f"\n{start}\n", 1)[1]
    cut = re.search(rf"\n#{{1,{level}}} ", body)
    return (body[: cut.start()] if cut else body).strip()


# Any README under knowledge/ or disciplines/, in any spelling of its path (`[sdlc-root]/`, `ops/sdlc/` or bare, a
# glob or a `[discipline]` placeholder), and the prose forms ("the knowledge store's README", "the README's
# structure listing").
_README_PATH = re.compile(r"(?:knowledge|disciplines)(?:/[\w*.\[\]-]+)*/README\.md")
_README_PROSE = re.compile(r"knowledge store's `?README|README's structure listing", re.IGNORECASE)
_SKILL_TREES = ("skills", "agents", "process", "templates", "playbooks")
_SKILL_FILES = ("CLAUDE-SDLC.md",)

# Every line at the tag that names one of those READMEs, with what it does. "read" lines go through
# docs/knowledge-routing.md (checked below); "other" lines list or copy a file, or are dropped or rewritten by a
# row, and read none. A line in neither list is a new reference: review it, then add it here.
README_LINES = [
    ("skills/sdlc-reflect/SKILL.md", "Read `[sdlc-root]/disciplines/README.md` for the full discipline list", "read"),
    ("skills/sdlc-reflect/SKILL.md", "New disciplines require the criteria in `[sdlc-root]/disciplines/README.md`", "read"),
    ("skills/sdlc-ingest/SKILL.md", "**`spec_relevant` tagging:**", "read"),
    ("skills/sdlc-migrate/SKILL.md", "**First migration introducing `spec_relevant`:**", "read"),
    ("skills/sdlc-initialize/SKILL.md", "**6d. Tag spec-relevant knowledge stores.**", "read"),
    ("skills/sdlc-ingest/SKILL.md", "- Update the knowledge store's `README.md` to list new files", "other"),
    ("skills/sdlc-ingest/SKILL.md", "- If new files are created, add them to the README's structure listing", "other"),
    ("skills/sdlc-ingest/SKILL.md", "4. **`[sdlc-root]/knowledge/[discipline]/README.md`**", "other"),
    ("skills/sdlc-migrate/SKILL.md", "| **Playbooks, examples, READMEs** |", "other"),
    ("skills/sdlc-migrate/SKILL.md", "- `knowledge/README.md` and each `knowledge/**/README.md`", "other"),
    ("skills/sdlc-initialize/SKILL.md", "[ ] ops/sdlc/knowledge/", "other"),
    ("skills/sdlc-initialize/SKILL.md", "[ ] All upstream READMEs copied", "other"),
]


def _upstream_lines(release: Path) -> Iterator[tuple[str, int, str]]:
    paths = [p for tree in _SKILL_TREES for p in sorted((release / tree).rglob("*.md"))]
    paths += [release / f for f in _SKILL_FILES if (release / f).is_file()]
    for p in paths:
        rel = p.relative_to(release).as_posix()
        if rel == "process/sdlc_changelog.md" or rel.startswith("process/changelog-archive/"):
            continue
        for n, line in enumerate(p.read_text().split("\n"), start=1):
            yield rel, n, line


def _readme_hits(lines: Iterable[tuple[str, int, str]]) -> list[tuple[str, int, str, str | None]]:
    """(file, line number, line, "read" | "other" | None) for each line that names a knowledge or discipline README."""
    hits = []
    for rel, n, line in lines:
        if _README_PATH.search(line) or _README_PROSE.search(line):
            kind = next((k for r, snippet, k in README_LINES if r == rel and snippet in line), None)
            hits.append((rel, n, line, kind))
    return hits


def _unaccounted(lines: Iterable[tuple[str, int, str]]) -> list[str]:
    return [f"{rel}:{n}" for rel, n, _l, kind in _readme_hits(lines) if kind is None]


class TestF5ReadmeReleaseGate:
    """The extractor sends no README, so a skill that reads one reads nothing in a Neuroloom project.
    0.7.2 moved the five reads z-sdlc 3.0.0 has to `docs/knowledge-routing.md`; this gate fails when
    z-sdlc adds a read, changes a text the doc copies, or adds a file no one accounts for."""

    # (a) every file is sent, the map or the log, or on the no-reader list.
    def test_every_file_is_sent_or_accounted_for(self, kd: Path, tmp_path: Path) -> None:
        sent = _extractor_named(kd, tmp_path)
        listed = _no_reader_list()
        assert listed, "step 11's List bullet names no file"
        assert not (sent & listed), f"sent and listed as unread: {sorted(sent & listed)}"
        unaccounted = _upstream_files(kd) - sent - listed - _MAP_AND_LOG
        assert not unaccounted, f"files the extractor skips and step 11 doesn't list: {sorted(unaccounted)}"
        gone = (listed | _MAP_AND_LOG) - _upstream_files(kd)
        assert not gone, f"listed but not in {_TAG}: {sorted(gone)}"

    # (b) each README read in the release names a section the doc carries, in any spelling of the path.
    def test_each_readme_read_names_a_section_the_doc_carries(self, release: Path) -> None:
        hits = _readme_hits(_upstream_lines(release))
        assert not [h for h in hits if h[3] is None], f"a README reference no row accounts for: {_unaccounted(_upstream_lines(release))}"
        used = {(rel, snippet) for rel, snippet, _k in README_LINES if any(h[0] == rel and snippet in h[2] for h in hits)}
        assert used == {(r, sn) for r, sn, _k in README_LINES}, "README_LINES names a line the release no longer has"
        reads = [h for h in hits if h[3] == "read"]
        assert len(reads) == 5, [(r, n) for r, n, _l, _k in reads]
        doc = lint._routing_doc()
        for rel, n, line, _k in reads:
            sections = re.findall(r'§\s*"([^"]+)"', line)
            if not sections:  # sdlc-reflect: "Read ... for the full discipline list if needed."
                assert "discipline list" in line, (rel, n)
                sections = ["The discipline list"]
            for name in sections:
                assert re.search(rf"\n#{{2,3}} {re.escape(name)}\n", doc), f"{rel}:{n} reads § {name!r}, which the routing doc lacks"

    def test_a_new_readme_read_in_any_spelling_or_tree_is_caught(self, release: Path) -> None:
        base = list(_upstream_lines(release))
        assert not _unaccounted(base)
        assert {rel.split("/")[0] for rel, _n, _l in base} >= {"skills", "agents", "process", "templates", "playbooks", "CLAUDE-SDLC.md"}
        mutations = (
            'Read `ops/sdlc/knowledge/README.md` § "X".',
            "See knowledge/README.md for X.",
            "Read disciplines/README.md.",
            "Check the knowledge store's README first.",
            "Read `[sdlc-root]/knowledge/architecture/README.md`.",
            "Every `knowledge/*/README.md` lists its files.",
        )
        for rel in ("skills/sdlc-plan/SKILL.md", "playbooks/example-playbook.md", "CLAUDE-SDLC.md", "agents/sdlc-reviewer.md"):
            for text in mutations:
                assert _unaccounted([*base, (rel, 9999, text)]) == [f"{rel}:9999"], (rel, text)

    def test_no_kept_sdlc_ingest_line_says_to_follow_the_targets_conventions(self, release: Path) -> None:
        for opening, _sha_ in INGEST_KEPT:
            _n, line = _one_line(release, _INGEST, opening)
            assert "conventions of the target" not in line and "existing conventions" not in line, opening

    # (c) the upstream text the doc condenses is pinned, whole sections, so a change anywhere in one fails.
    def test_the_upstream_sections_the_doc_carries_are_pinned(self, kd: Path) -> None:
        disc = (kd / "disciplines" / "README.md").read_text()
        creating = _slice(disc, "## Creating a New Discipline", 2)
        assert _sha(creating) == "c093419233db2922", f"'Creating a New Discipline' changed upstream ({_sha(creating)}): update the doc's section, then this hash"
        know = (kd / "knowledge" / "README.md").read_text()
        field = know.split("\n### `spec_relevant` Field\n", 1)[1].split("\n#### Tagging a project's stores", 1)[0].strip()
        assert _sha(field) == "c1d61d0c92b428fb", f"'spec_relevant Field' changed upstream ({_sha(field)}): update the doc's section, then this hash"
        tagging = _slice(know, "#### Tagging a project's stores", 4)
        assert _sha(tagging) == "60dc97833b87de25", f"'Tagging a project's stores' changed upstream ({_sha(tagging)}): update the doc's walkthrough, then this hash"

    # (d) the discipline list is the release's.
    def test_the_discipline_list_is_the_releases(self, kd: Path) -> None:
        upstream = {p.stem for p in (kd / "disciplines").glob("*.md")} - {"README"}
        body = lint._doc_section("## The discipline list")
        listed = set(re.findall(r"`([a-z]+(?:-[a-z]+)*)`", body))
        assert listed == upstream, (sorted(listed - upstream), sorted(upstream - listed))

    # (e) nothing reads the ten other unread files.
    def test_no_upstream_file_reads_the_ten_other_unread_files(self, release: Path, kd: Path) -> None:
        # The ten come from step 11's no-reader list, not from upstream: that is the list a handler acts on.
        others = sorted(_no_reader_list() - {"knowledge/README.md", "disciplines/README.md"})
        assert len(others) == 10, others
        assert set(others) <= _upstream_files(kd), sorted(set(others) - _upstream_files(kd))
        needles = [*others, "party-role-erd", "knowledge/*/README.md", "knowledge/**/README.md"]
        allowed = (  # copy-table and checklist lines: they list files to copy or to find installed, and read none
            ("skills/sdlc-migrate/SKILL.md", "| **Playbooks, examples, READMEs** |"),
            ("skills/sdlc-migrate/SKILL.md", "- `knowledge/README.md` and each `knowledge/**/README.md`"),
            ("skills/sdlc-initialize/SKILL.md", "[ ] ops/sdlc/knowledge/"),
            ("skills/sdlc-initialize/SKILL.md", "[ ] All upstream READMEs copied"),
        )
        hits = [
            f"{rel}:{n}" for rel, n, line in _upstream_lines(release)
            if any(x in line for x in needles) and not any(rel == r and line.lstrip().startswith(o) for r, o in allowed)
        ]
        assert not hits, f"a skill, agent or process doc now names a file that no seed or install path reaches: {hits}"


class TestPortChecksAgreeWithTheKeptSdlcMigrateLines:
    """/sdlc-port Stage 4d rejects `provenance_log` anywhere and a bare `agent-context-map.yaml` outside Check 6 step 4's
    closed list. Two lines on that list also name `provenance_log.md` (v3.0.0 sdlc-migrate :203 and :425), so keeping
    them verbatim failed Stage 4d. The provenance row drops that one item; the map mention stays, and its line is on the list."""

    OPENINGS = ("Source-to-project path mappings", "**Step 0 — Load exclusion list before any writes.**")

    def _kept_list(self) -> str:
        audit = _audit()
        return audit.split("4. All operations:", 1)[1].split("**Action on failure:**", 1)[0]

    def _transform(self, line: str) -> str:
        """The rules' row: drop `provenance_log.md` from the list of project-specific files (and Step 0's exclusions)."""
        return re.sub(r", `provenance_log\.md`", "", line)

    def _port_problems(self, line: str) -> list[str]:
        problems = []
        if "provenance_log" in line:
            problems.append("provenance")
        if "agent-context-map" in line and not any(line.startswith(o) for o in self.OPENINGS):
            problems.append("map")
        return problems

    def test_the_two_lines_pass_the_ports_checks_only_after_the_provenance_row(self, release: Path) -> None:
        kept = self._kept_list()
        rules = lint._rules()
        assert any(ln.startswith("| `sdlc-migrate`: `provenance_log.md` in the list of project-specific files") for ln in rules.splitlines())
        assert "drops the `provenance_log.md` item from the two lines that list it" in _audit()
        for opening in self.OPENINGS:
            assert opening.strip("*") in kept.replace("**", ""), opening  # on Check 6 step 4's list
            _n, line = _one_line(release, _MIGRATE, opening)
            assert "provenance_log.md" in line  # verbatim, Stage 4d's provenance check would reject it
            assert self._port_problems(line) == ["provenance"]
            assert self._port_problems(self._transform(line)) == [], opening
        assert "`provenance_log.md` item" in _flat_text(rules.split("`sdlc-migrate`'s map lines are exempt", 1)[1][:2500]) or "lose that one item" in (_ROOT / "agents" / "neuroloom-transformer.md").read_text()


def _flat_text(text: str) -> str:
    return " ".join(text.split())
