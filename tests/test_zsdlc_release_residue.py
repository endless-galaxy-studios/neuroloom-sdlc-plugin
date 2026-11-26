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
import tarfile
from collections.abc import Iterator
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
        ["git", "-C", str(_UPSTREAM), "archive", _TAG, "skills", "process", "templates", "agents"],
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
        assert "and contract 0026's file-presence lines, `post-operation-audit.md` Check 2 row 6)" in agent
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
