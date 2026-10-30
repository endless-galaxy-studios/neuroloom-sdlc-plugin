"""
Guards for the Pattern Mapping rule documents and transforms.yaml.

These files are prose that a model executes, so a wrong example in them is a bug
that ships into every project the plugin migrates. Each test pins a mistake that
has already happened once:

- a `*` inside a `tags=[...]` / `tag_prefixes=[...]` argument (the rule table
  emitted `sdlc:discipline:` plus a wildcard; the API matches tags literally, so
  the call returned nothing and raised nothing),
- the dead plugin-scoped MCP tool namespace in `tool_profiles` (the base plugin
  ships no MCP server, so those tool names never load),
- skills' `references/` files missing from the transform scope and the audit,
- `tags=["sdlc:knowledge", "sdlc:domain:<d>"]` without `tags_match="all"`, an OR that scoped nothing,
- prefixes used on things that are not tag families (`sdlc:knowledge` also matches `sdlc:knowledge-id:…`;
  a domain tag is a prefix of its siblings; the discipline family prefix has no colon),
- exemptions that were wider than the thing they exempted (a whole tree, a whole line),
- upstream phrasings no rule row covers (the coverage inventory at the bottom).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parent.parent

# Built from parts so this file does not match its own scan.
_DEAD_NAMESPACE = "mcp__plugin_neuroloom_" + "neuroloom__"
_LIVE_PREFIX = "mcp__neuroloom__"

# A wildcard inside a tag argument. `[^\]]*` stops at the closing bracket of the list.
_TAG_WILDCARD_RE = re.compile(r"tag(?:s|_prefixes)=\[[^\]]*\*")

_SKIP_DIRS = {".git", "__pycache__", ".mypy_cache", ".ruff_cache", "node_modules", ".claude"}
_TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".json", ".py", ".txt"}


def _text_files() -> list[Path]:
    files: list[Path] = []
    for path in _ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in _TEXT_SUFFIXES:
            continue
        if any(part in _SKIP_DIRS for part in path.relative_to(_ROOT).parts):
            continue
        files.append(path)
    return files


def _rule_documents() -> list[Path]:
    """Every file whose examples a model may copy into a project."""
    docs = [
        *sorted((_ROOT / "references").glob("*.md")),
        *sorted((_ROOT / "agents").glob("*.md")),
        *sorted((_ROOT / "docs").glob("*.md")),
        *sorted((_ROOT / "skills").rglob("*.md")),
        _ROOT / "README.md",
        _ROOT / "transforms.yaml",
    ]
    return [d for d in docs if d.is_file()]


class TestToolNamespace:
    def test_tool_profiles_use_the_live_namespace(self) -> None:
        config = yaml.safe_load((_ROOT / "transforms.yaml").read_text())
        tools = [t for profile in config["tool_profiles"].values() for t in profile["tools"]]
        assert tools, "tool_profiles is empty"
        wrong = [t for t in tools if not t.startswith(_LIVE_PREFIX)]
        assert not wrong, f"tools outside the {_LIVE_PREFIX}* namespace: {wrong}"

    def test_dead_namespace_appears_nowhere_in_the_repo(self) -> None:
        offenders = [
            str(p.relative_to(_ROOT)) for p in _text_files() if _DEAD_NAMESPACE in p.read_text(errors="replace")
        ]
        assert not offenders, f"dead plugin-scoped tool namespace found in: {offenders}"

    def test_server_name_assumption_is_documented_where_profiles_are_defined(self) -> None:
        text = (_ROOT / "transforms.yaml").read_text()
        head = text.split("tool_profiles:", 1)[0]
        assert "ASSUMPTION" in head and ".mcp.json" in head


class TestTagArguments:
    @pytest.mark.parametrize("path", _rule_documents(), ids=lambda p: str(p.relative_to(_ROOT)))
    def test_no_wildcard_inside_a_tag_argument(self, path: Path) -> None:
        hits = [
            f"{path.relative_to(_ROOT)}:{n}: {line.strip()[:120]}"
            for n, line in enumerate(path.read_text().splitlines(), start=1)
            if _TAG_WILDCARD_RE.search(line)
        ]
        assert not hits, "a `*` inside tags=[...] / tag_prefixes=[...] matches nothing:\n" + "\n".join(hits)

    def test_the_regex_catches_the_bug_it_guards_against(self) -> None:
        bad = 'memory_search(query="discipline entries", ' + 'tags=["sdlc:discipline:' + '*"])'
        good = 'memory_search(query="discipline entries", tag_prefixes=["sdlc:discipline:"])'
        assert _TAG_WILDCARD_RE.search(bad)
        assert not _TAG_WILDCARD_RE.search(good)

    def test_discipline_rows_use_the_family_prefix_without_a_colon(self) -> None:
        rules = (_ROOT / "references" / "pattern-mapping-rules.md").read_text()
        assert 'tag_prefixes=["sdlc:discipline"]' in rules
        assert 'tags=["sdlc:parking-lot"], tag_prefixes=["sdlc:discipline"]' in rules
        assert 'tags=["sdlc:deliverable:<ID>"], tag_prefixes=["sdlc:discipline"]' in rules

    def test_no_colon_form_family_prefix_and_no_knowledge_prefix_anywhere(self) -> None:
        """`sdlc:discipline:` misses the bare tag; `sdlc:knowledge` also matches `sdlc:knowledge-id:…`."""
        bad = re.compile(r'tag_prefixes=\["sdlc:discipline:"|tag_prefixes=\["sdlc:knowledge')
        hits = [
            f"{p.relative_to(_ROOT)}:{n}: {ln.strip()[:100]}"
            for p in _rule_documents()
            for n, ln in enumerate(p.read_text().splitlines(), start=1)
            if bad.search(ln)
        ]
        assert not hits, "\n".join(hits)


class TestScope:
    def test_references_files_are_in_the_skill_transform_scope(self) -> None:
        config = yaml.safe_load((_ROOT / "transforms.yaml").read_text())
        develop_skill = [t for t in config["transforms"] if t["skill"] == "sdlc-develop-skill"]
        assert develop_skill, "sdlc-develop-skill transform missing"
        patterns = develop_skill[0]["target_patterns"]
        assert ".claude/skills/*/references/*.md" in patterns

    def test_post_file_write_scope_includes_references(self) -> None:
        lifecycle = (_ROOT / "references" / "adapter-lifecycle.md").read_text()
        applies_to = [ln for ln in lifecycle.splitlines() if ln.startswith("**Applies to:**")]
        assert applies_to and ".claude/skills/*/references/*.md" in applies_to[0]

    def test_post_operation_audit_scans_the_skills_tree(self) -> None:
        audit = (_ROOT / "references" / "post-operation-audit.md").read_text()
        assert r"\[sdlc-root\]/(knowledge|disciplines)/" in audit
        scan_lines = [ln for ln in audit.splitlines() if ln.startswith("grep -rnE")]
        assert scan_lines, "no grep scan commands in post-operation-audit.md"
        for line in scan_lines:
            assert ".claude/skills" in line, f"scan does not search .claude/skills: {line}"


def _rules() -> str:
    return (_ROOT / "references" / "pattern-mapping-rules.md").read_text()


def _audit() -> str:
    return (_ROOT / "references" / "post-operation-audit.md").read_text()


# A `tags=[...]` list that holds sdlc:knowledge next to another tag.
_TAGS_LIST_RE = re.compile(r"tags=\[([^\]]*)\]")


_CALL_NAMES = re.compile(r"(memory_search|memory_store|memory_explore|memory_get_index|memory_update|document_ingest\w*)\(")
# calls whose `tags` list is an AND by nature (stores apply every tag; the index filter is AND by design)
_TAG_AND_BY_NATURE = {"memory_store", "memory_get_index", "memory_update"}


def _nearest_call(text: str, pos: int) -> str | None:
    """Name of the last call before `pos`, looking back over the same line and the four before it."""
    start = pos
    for _ in range(5):
        start = text.rfind("\n", 0, start - 1) + 1 if start > 0 else 0
    names = [m.group(1) for m in _CALL_NAMES.finditer(text[start:pos])]
    if not names:
        return None
    return "document_ingest" if names[-1].startswith("document_ingest") else names[-1]


class TestMultiTagAnd:
    def test_every_multi_tag_search_spec_carries_tags_match_all(self) -> None:
        """A `tags` list of two or more tags is an OR unless `tags_match="all"` is on the call.

        What the list belongs to is decided by the NEAREST call name before it (same line or the four
        before), the way the repair rules decide: a `memory_store` / `memory_get_index` / `memory_update` /
        `document_ingest*` call is skipped, a `memory_search` (or a bare spec with no call name) is not.
        A line that merely mentions `memory_store` somewhere does not exempt a later search list.
        """
        hits = []
        for path in _rule_documents():
            text = path.read_text()
            for m in _TAGS_LIST_RE.finditer(text):
                items = re.findall(r'"([^"]*)"', m.group(1))
                if len(items) < 2:
                    continue
                if _nearest_call(text, m.start()) in _TAG_AND_BY_NATURE:
                    continue
                # the call may continue on the next line, so look a little past the list
                if 'tags_match="all"' not in text[m.end() : m.end() + 60]:
                    n = text.count("\n", 0, m.start()) + 1
                    line = text[text.rfind("\n", 0, m.start()) + 1 : text.find("\n", m.start())]
                    hits.append(f"{path.relative_to(_ROOT)}:{n}: {line.strip()[:110]}")
        assert not hits, "multi-tag search spec without tags_match=\"all\" (an OR):\n" + "\n".join(hits)

    def test_nearest_call_decides_not_a_mention_elsewhere_on_the_line(self) -> None:
        text = 'See memory_store for writes. memory_search(query="q", tags=["a", "b"])'
        assert _nearest_call(text, text.index("tags=[")) == "memory_search"
        text = 'memory_search(query="q",\n   tags=["a", "b"], tags_match="all")'
        assert _nearest_call(text, text.index("tags=[")) == "memory_search"
        text = 'memory_store(content="c",\n  tags=["a", "b"])'
        assert _nearest_call(text, text.index("tags=[")) == "memory_store"
        assert _nearest_call('| `query="q", tags=["a", "b"]` |', 20) is None

    def test_domain_and_form_is_what_the_rows_emit(self) -> None:
        rules = _rules()
        assert 'tags=["sdlc:knowledge", "sdlc:domain:<domain>"], tags_match="all"' in rules
        assert 'tags=["sdlc:knowledge", "sdlc:domain:architecture"], tags_match="all"' in rules

    def test_multi_domain_and_union_rows_become_one_call_per_family(self) -> None:
        rules = _rules()
        assert 'tags=["sdlc:knowledge", "sdlc:domain:testing"], tags_match="all"' in rules
        assert "one call per domain" in rules
        assert 'memory_search(query="[X]", tags=["sdlc:knowledge"])` and `memory_search(query="[X]", tag_prefixes=["sdlc:discipline"])' in rules

    def test_rule_10_example_is_true_under_the_semantics_note(self) -> None:
        rules = _rules()
        assert 'tags_match="all"` → `tags=["sdlc:knowledge"]` (lost domain scope' in rules

    def test_semantics_note_states_tags_match_as_the_and_and_says_why_it_is_safe_early(self) -> None:
        rules = _rules()
        assert "**AND across exact tags is `tags_match=\"all\"`.**" in rules
        assert "D178a" in rules and "additionalProperties: false" in rules
        assert "NOT deployed" not in rules and "do not emit it" not in rules  # the contradictory sentence is gone
        assert "the prefix is the whole second tag" not in rules

    def test_semantics_note_forbids_the_unsafe_prefixes(self) -> None:
        rules = _rules()
        for marker in (
            "Never use an exact tag as a prefix",
            "Never prefix-match `sdlc:knowledge`",
            "`sdlc:knowledge-id:",
            "has NO colon",
            "Knowledge OR discipline cannot be one call",
            "Agent tags are not emitted",
        ):
            assert marker in rules, marker

    def test_named_discipline_rows_put_the_name_in_the_query_not_in_a_tag(self) -> None:
        rules = _rules()
        assert '`memory_search(query="<name> discipline entries", tag_prefixes=["sdlc:discipline"])`' in rules

    def test_project_specific_lookup_filters_seed_client_side(self) -> None:
        rules = _rules()
        assert "Do not search `sdlc:project-specific`" in rules

    def test_legacy_repair_drops_agent_tags_and_warns_on_mixed_families(self) -> None:
        rules = _rules()
        assert "drop `sdlc:agent:<a>`" in rules
        assert "tags of mixed families that match none of the rows above" in rules
        assert "`memory_get_index(...)` call (its `tags` filter is AND by design)" in rules

    def test_resolved_verification_checks_both_tags(self) -> None:
        lifecycle = (_ROOT / "references" / "adapter-lifecycle.md").read_text()
        assert 'tags=["sdlc:discipline:{name}", "sdlc:seed-version:{LATEST_VERSION}"],\n                 tags_match="all"' in lifecycle
        assert 'tag_prefixes=["sdlc:seed-version' not in lifecycle

    def test_no_domain_wildcard_notation_in_replacement_outputs(self) -> None:
        for path in sorted((_ROOT / "references").glob("*.md")) + [_ROOT / "agents" / "neuroloom-transformer.md"]:
            assert "sdlc:domain:*" not in path.read_text(), path.name


class TestParkingLotRow:
    def _row(self) -> str:
        rows = [ln for ln in _rules().splitlines() if ln.startswith("| `read [sdlc-root]/disciplines/*.md and find parking lot entries")]
        assert len(rows) == 1
        return rows[0]

    def test_no_tags_list_holds_both_parking_lot_and_a_deliverable_tag(self) -> None:
        row = self._row()
        for m in _TAGS_LIST_RE.finditer(row):
            items = re.findall(r'"([^"]*)"', m.group(1))
            assert not ("sdlc:parking-lot" in items and any(i.startswith("sdlc:deliverable:") for i in items)), m.group(0)
        assert "unless the call also sets `tags_match=\"all\"`" in row

    def test_the_filtering_sentence_is_part_of_the_output(self) -> None:
        row = self._row()
        assert "keep only the entries whose context tag names <ID>" in row
        assert "then keep only the entries that match <tag-expr>" in row
        assert "part of the OUTPUT text" in row


class TestRuleStructure:
    def test_match_rule_12_and_its_worked_example(self) -> None:
        rules = _rules()
        assert "12. **Sentence punctuation after a path does not stop a rule from matching.**" in rules
        assert "comment-discipline.yaml. It is the rule." in rules

    def test_integration_terminator_allows_the_leading_bullet(self) -> None:
        rules = _rules()
        assert r"the next `^\s*(- )?\*\*[A-Z]` (a new bold label, bulleted or not)" in rules
        assert "DRY discipline|Knowledge routing" in rules

    def test_integration_post_write_check_compares_with_backticks_stripped(self) -> None:
        rules = _rules()
        assert "strip inline backticks from both the upstream line and the output line" in rules

    def test_integration_carve_out_has_rows_for_the_formerly_uncovered_paths(self) -> None:
        rules = _rules()
        for marker in (
            "`files under [sdlc-root]/knowledge/<domain>/`",
            "bare `[sdlc-root]/knowledge/` or bare `[sdlc-root]/disciplines/` token",
            "`[sdlc-root]/knowledge/{domain}/{topic}.yaml`",
            "`(knowledge wiring)` or `(for wiring)`",
        ):
            assert marker in rules, marker
        assert "Never emit `{domain}` or `{topic}` into a `memory_search` call" in rules

    def test_a_name_capture_never_takes_a_glob_and_glob_rows_come_first(self) -> None:
        rules = _rules()
        assert "A capture never takes a glob (`*`) as its value" in rules
        glob_row = rules.index("| `Read [sdlc-root]/disciplines/*.md` (glob across all disciplines)")
        name_row = rules.index("| `Read [sdlc-root]/disciplines/<name>.md` (a NAMED discipline, never a glob)")
        assert glob_row < name_row

    def test_legacy_repair_rows_run_before_the_gate_and_are_exempt_from_rule_10(self) -> None:
        rules = _rules()
        assert "**Legacy repair" in rules and "BEFORE the preservation gate" in rules
        assert "Exception — legacy-repair rows" in rules
        agent = (_ROOT / "agents" / "neuroloom-transformer.md").read_text()
        assert "### Step 2.0: Legacy repair sweep" in agent and "mcp_repaired" in agent
        assert "whether or not upstream wrote the file" in agent

    def test_legacy_repair_is_idempotent_and_never_overwrites_tags_match(self) -> None:
        rules = _rules()
        assert "**They are idempotent.**" in rules
        assert "and no `tags_match` argument on the call" in rules
        assert 'a deliberate `tags_match="any"` is never overwritten' in rules
        assert "Running the sweep twice changes nothing the second time" in rules

    def test_agent_tag_drop_checks_the_workspace_first(self) -> None:
        rules = _rules()
        assert 'memory_get_index(tags=["sdlc:agent:<a>"], limit=1)' in rules
        for marker in ("**Zero entries**", "**Entries exist**", "**Cannot check**", "once per distinct `<a>`"):
            assert marker in rules, marker
        agent = (_ROOT / "agents" / "neuroloom-transformer.md").read_text()
        assert "mcp__neuroloom__memory_get_index" in agent.split("---", 2)[1], "the transformer needs the tool it checks with"
        assert "Check it live once per distinct `<a>`".lower() in agent.lower() or "check it live once per distinct" in agent.lower()

    def test_bare_discipline_tag_alone_is_repaired_to_the_family(self) -> None:
        rules = _rules()
        assert "**Bare `sdlc:discipline` as the only tag**" in rules
        assert '`["sdlc:discipline", "sdlc:parking-lot"]` is repaired the same way' in rules

    def test_project_added_knowledge_is_a_set_difference_of_two_index_calls(self) -> None:
        rules = _rules()
        assert 'memory_get_index(tags=["sdlc:knowledge"], limit=500)` for every knowledge entry (K)' in rules
        assert 'memory_get_index(tags=["sdlc:knowledge", "sdlc:seed"], limit=500)` for the seeded ones (S)' in rules
        assert "K minus S, matched on `id`" in rules
        assert "no offset" in rules and "treat a `count` equal to `limit` as truncated" in rules
        assert "Document ingestion never adds `sdlc:seed`" in rules
        assert "NOT on `memory_type`" in rules  # ingested knowledge shares the seeds' type, so a type filter would drop it

    def test_dispatch_prompt_rows(self) -> None:
        rules = _rules()
        assert "`Read {the agent's mapped knowledge files}`" in rules
        assert "or untagged block" in rules
        assert "markdown fence holding" not in (_ROOT / "agents" / "neuroloom-transformer.md").read_text()

    def test_sdlc_migrate_live_read_rows(self) -> None:
        rules = _rules()
        for marker in (
            "`Read each [sdlc-root]/disciplines/*.md parking lot`",
            "`Read each [sdlc-root]/knowledge/**/*.yaml that the project has customized",
            "`Verify <X> references [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml`",
            "`read [sdlc-root]/disciplines/<name>.md and <verb> [rest]`",
        ):
            assert marker in rules, marker


class TestCheck2ExemptionTable:
    def _rows(self) -> list[str]:
        audit = _audit()
        section = audit.split("### Check 2 — No residual knowledge-layer references", 1)[1].split("### Check 2a", 1)[0]
        return [ln for ln in section.splitlines() if re.match(r"\| [1-9] \|", ln)]

    def test_six_rows_and_no_whole_tree_or_whole_file_exemption(self) -> None:
        rows = self._rows()
        assert len(rows) == 6
        assert not rows[0].startswith("| 1 | Everything under"), "sdlc-migrate must be exempt line by line"
        assert "LINE BY LINE" in rows[0]
        assert "Only the span is exempt" in rows[1]

    def test_fenced_format_demos_are_exempt_but_dispatch_prompts_are_not(self) -> None:
        row = self._rows()[5]
        assert "fenced block that shows a file format or a command" in row
        assert "NOT a dispatch-prompt template block" in row
        assert "is NOT exempt" in row

    def test_the_scan_is_limited_to_markdown(self) -> None:
        scans = [ln for ln in _audit().splitlines() if ln.startswith("grep -rnE")]
        assert scans and all("--include='*.md'" in ln for ln in scans)

    def test_content_merge_audits_defers_to_the_one_table(self) -> None:
        cma = (_ROOT / "references" / "content-merge-audits.md").read_text()
        assert "That table is the single list for every path-bearing hit" in cma
        assert "**Not exempt — Integration section:**" not in cma


# ---------------------------------------------------------------------------
# Coverage inventory against upstream z-sdlc v2.2.0
# ---------------------------------------------------------------------------
#
# The rule tables are prose that a model executes, so they cannot be run here. What CAN be
# checked mechanically is the inventory: every `[sdlc-root]/(knowledge|disciplines)/` OCCURRENCE
# (one per path token, so a line with three paths counts three) in upstream's skills, process
# docs, templates and agents is put in a family (verb + kind of file + context), and each family
# must name a marker string that exists in the rules. A new upstream phrasing lands in a family
# with no marker and fails here, which is how the 0.5.6 gaps would have shown up. The classifier
# is deliberately simple; it checks that a row EXISTS for the family, not that the row's wording
# is perfect.
#
# CI NEVER RUNS THIS CLASS. It needs a local checkout of upstream (~/Projects/cc-sdlc) at the
# v2.2.0 tag, which no CI runner has, so the `skipif` below skips it everywhere but a developer
# machine. Treat it as a local gate to run before releasing the plugin or bumping
# `supported_zsdlc_version`; a green CI run says nothing about upstream coverage.

_UPSTREAM = Path.home() / "Projects" / "cc-sdlc"
_PATH = re.compile(r"\[sdlc-root\]/(?:knowledge|disciplines)/[^\s`'\")\]]*")
_LABELS = r"(Uses|Depends on|Updates|Feeds into|Complements|Downstream|Does NOT replace|DRY notes|DRY discipline|Knowledge routing)"
_INTEG = re.compile(r"^\s*(- )?\*\*" + _LABELS + r":\*\*")
_NEWLABEL = re.compile(r"^\s*(- )?\*\*[A-Z]")
_EXEMPT_FILES = (
    "process/knowledge-routing.md", "process/project-section-markers.md", "process/path-mappings.md",
    "process/adapter-lifecycle-protocol.md", "process/sdlc_changelog.md", "process/changelog-archive/",
)
_VERBS = r"(?i)\b(read|consult|update|append(?: to)?|scan|look up|load|apply|follow|see|verify|list|grep|search|extract to|write to|add)\b"
_QUOTE_VERB = re.compile(r"(?i)(consult|read|update|append to|look up)\b")
_PROMPT_INTRO = re.compile(r"(?i)\b(prompt|dispatch)")
_OUTPUT_INTRO = re.compile(r"(?i)\b(update|append|write|present|report|output|summary|display)\b")
_PLACEHOLDER = re.compile(r"\[(?:count|date|name|discipline|file|ID range|[a-z][a-z /-]+)\]")

# family -> a substring that must appear in pattern-mapping-rules.md
_FAMILY_MARKERS: dict[str, str] = {
    "plain:yaml:read": "`Read [sdlc-root]/knowledge/<domain>/<file>.yaml`",
    "plain:yaml:consult": "may be `Read`, `read`, `Consult` or `consult`",
    "plain:yaml:follow": "`follow/apply/use … in/from [sdlc-root]/knowledge/<domain>/<file>.yaml § <section>`",
    "plain:yaml:-": "as a prose citation",
    "plain:map:consult": "`consult [sdlc-root]/knowledge/agent-context-map.yaml`",
    "plain:map:update": "`update [sdlc-root]/knowledge/agent-context-map.yaml`",
    "plain:map:look up": "`look up the agent's mapped files from [sdlc-root]/knowledge/agent-context-map.yaml`",
    "plain:map:-": "Validation-checklist items that test whether an agent file wires the knowledge layer",
    "plain:acp:read": "`Read [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml`",
    "plain:acp:-": "Validation-checklist items that test whether an agent file wires the knowledge layer",
    "plain:acp:follow": "as a prose citation",
    "plain:acp:verify": "`Verify <X> references [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml`",
    "plain:disc:read": "`Read [sdlc-root]/disciplines/*.md and find [X]`",
    "plain:disc:append to": "`Append to [sdlc-root]/disciplines/*.md`",
    "plain:disc:append": "`Append to [sdlc-root]/disciplines/*.md`",
    "plain:disc:grep": "`grep [X] across [sdlc-root]/disciplines/*.md`",
    "plain:disc:-": "Table cell containing `[sdlc-root]/disciplines/*.md`",
    "plain:other:-": "bare `[sdlc-root]/knowledge/` or bare `[sdlc-root]/disciplines/` token",
    "plain:other:read": "`Read relevant files under [sdlc-root]/knowledge/ and [sdlc-root]/disciplines/ for [X]`",
    "plain:other:list": "`YAML files under [sdlc-root]/knowledge/`",
    "plain:other:search": "`Search [sdlc-root]/knowledge/ YAML files for [X]`",
    "plain:other:append to": "`Cross-project knowledge updates append to [sdlc-root]/knowledge/<domain>/`",
    "plain:other:extract to": "`Extract to [sdlc-root]/process/ or [sdlc-root]/knowledge/`",
    "integration": "Integration-section token",
    "fenced-prompt:other:read": "`Read [sdlc-root]/knowledge/<domain>/<file>.yaml`",
    "fenced-agent-template:map:consult": "`consult [sdlc-root]/knowledge/agent-context-map.yaml`",
    "fenced-output": "**EXCEPTION — Output-template blocks",
    "checklist-canonical": "Canonical-form checklist items",
}


def _fence_blocks(lines: list[str]) -> list[tuple[int, int, str, str, str]]:
    """(open_index, close_index, language, body, intro) for each fenced block.

    `intro` is the nearest non-blank line before the opening fence: the prose that says what the block is.
    """
    blocks: list[tuple[int, int, str, str, str]] = []
    start: tuple[int, str] | None = None
    for n, ln in enumerate(lines):
        if ln.strip().startswith("```"):
            if start is None:
                start = (n, ln.strip()[3:].strip())
            else:
                intro = next((lines[k] for k in range(start[0] - 1, -1, -1) if lines[k].strip()), "")
                blocks.append((start[0], n, start[1], "\n".join(lines[start[0] + 1 : n]), intro))
                start = None
    return blocks


def _classify(rel: str, line: str, tok: re.Match[str], fence: tuple[str, str, str] | None, in_integ: bool) -> str:
    if tok.group(0).endswith("provenance_log.md"):
        return "EXEMPT"
    if rel == "skills/sdlc-migrate/SKILL.md" and ("→" in line or re.search(r"\(to `\[sdlc-root\]", line)):
        return "EXEMPT"
    kind = "plain"
    if fence is not None:
        lang, body, intro = fence
        prompt = (
            rel.endswith("dispatch-prompts.md")
            or bool(_PROMPT_INTRO.search(intro))
            or ("**Objective:**" in body and "**Constraints:**" in body)
        )
        agent_tpl = "## Knowledge Context" in body or "## Communication Protocol" in body or rel == "templates/agent-template.md"
        output_tpl = lang in ("", "markdown") and bool(_OUTPUT_INTRO.search(intro)) and bool(_PLACEHOLDER.search(body))
        if prompt:
            kind = "fenced-prompt"
        elif agent_tpl:
            kind = "fenced-agent-template"
        elif output_tpl:
            return "fenced-output"
        else:
            return "EXEMPT"
    # Framework-agent checklists. An anti-residue item (`- [ ] No `phrase``) quotes the forbidden phrase:
    # only that first span is exempt. A POSITIVE item (`- [ ] Lookups use `consult …``) states the form the
    # reviewer enforces and must be rewritten, so it is NOT exempt: it gets its own family.
    if rel.startswith("agents/sdlc-") and re.match(r"\s*- \[ \] ", line):
        no_span = re.match(r"\s*- \[ \] No `([^`]*)`", line)
        if no_span and no_span.start(1) <= tok.start() < no_span.end(1):
            return "EXEMPT"
        for span in re.finditer(r"`([^`]*)`", line):
            if span.start() <= tok.start() < span.end() and _QUOTE_VERB.match(span.group(1)):
                return "checklist-canonical"
    if in_integ:
        return "integration"
    before = line[: tok.start()].replace("`", "")
    verbs = re.findall(_VERBS, before[-90:])
    token = tok.group(0)
    fam = (
        "map" if "agent-context-map" in token else "acp" if "agent-communication-protocol" in token
        else "disc" if "/disciplines/" in token else "yaml" if token.endswith(".yaml") else "other"
    )
    return f"{kind}:{fam}:{verbs[-1].lower() if verbs else '-'}"


def _upstream_occurrences() -> list[tuple[str, int, str, str]]:
    """One tuple per PATH TOKEN (not per line): (file, line number, family, line text)."""
    out: list[tuple[str, int, str, str]] = []
    for top in ("skills", "process", "templates", "agents"):
        for f in sorted((_UPSTREAM / top).rglob("*.md")):
            rel = str(f.relative_to(_UPSTREAM))
            if rel.startswith(_EXEMPT_FILES):
                continue
            lines = f.read_text().split("\n")
            fences = _fence_blocks(lines)
            in_integ = False
            for n, ln in enumerate(lines):
                if not ln.strip() or (_NEWLABEL.match(ln) and not _INTEG.match(ln)):
                    in_integ = False
                if _INTEG.match(ln):
                    in_integ = True
                toks = list(_PATH.finditer(ln))
                if not toks:
                    continue
                fence = next(((lang, body, intro) for a, b, lang, body, intro in fences if a < n < b), None)
                for tok in toks:
                    out.append((rel, n + 1, _classify(rel, ln, tok, fence, in_integ), ln))
    return out


def _upstream_is_v2_2_0() -> bool:
    if not (_UPSTREAM / "skills").is_dir():
        return False
    try:
        tag = subprocess.run(
            ["git", "-C", str(_UPSTREAM), "describe", "--tags", "--exact-match"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return False
    return tag == "v2.2.0"


@pytest.mark.skipif(not _upstream_is_v2_2_0(), reason="needs ~/Projects/cc-sdlc checked out at the v2.2.0 tag")
class TestUpstreamCoverageInventory:
    def test_every_upstream_occurrence_falls_in_a_family_with_a_rule_row(self) -> None:
        rules = _rules()
        unregistered: dict[str, str] = {}
        missing_marker: dict[str, str] = {}
        total = exempt = 0
        for rel, n, family, _line in _upstream_occurrences():
            total += 1
            if family == "EXEMPT":
                exempt += 1
                continue
            marker = _FAMILY_MARKERS.get(family)
            if marker is None:
                unregistered.setdefault(family, f"{rel}:{n}")
            elif marker not in rules:
                missing_marker.setdefault(family, marker)
        assert total > 150, f"inventory looks wrong: only {total} occurrences"
        assert not unregistered, f"upstream phrasings with no registered rule family: {unregistered}"
        assert not missing_marker, f"families whose rule row is gone from pattern-mapping-rules.md: {missing_marker}"

    def test_occurrences_are_counted_per_path_not_per_line(self) -> None:
        occ = _upstream_occurrences()
        lines = {(r, n) for r, n, _f, _l in occ}
        assert len(occ) > len(lines), "multi-path lines must contribute one occurrence per path"

    def test_the_inventory_still_sees_the_residue_classes_that_slipped_through_before(self) -> None:
        families = {fam for _r, _n, fam, _l in _upstream_occurrences()}
        assert {"integration", "fenced-prompt:other:read", "plain:yaml:consult", "fenced-output"} <= families

    def test_a_checklist_exempts_only_the_span_after_no_and_never_a_positive_item(self) -> None:
        fam = {}
        for r, n, f, _l in _upstream_occurrences():
            if r == "agents/sdlc-reviewer.md":
                fam.setdefault(n, []).append(f)
        # 119: a backticked BARE path in a checklist item is not a quote
        assert fam[119] == ["plain:other:extract to"]
        # 134-137: the POSITIVE canonical items must be rewritten, so none of them is exempt
        for n in (134, 135, 136, 137):
            assert fam[n] == ["checklist-canonical"], (n, fam[n])
        # 140-144: the `- [ ] No `phrase`` items exempt their quoted span
        no_items = [n for n in fam if n >= 140 and fam[n] == ["EXEMPT"]]
        assert len(no_items) >= 4, no_items

    def test_the_canonical_form_rows_rewrite_all_four_positive_items(self) -> None:
        rules = _rules()
        for old in (
            "- [ ] Lookups use `consult [sdlc-root]/knowledge/agent-context-map.yaml`",
            "- [ ] Wiring instructions use `update [sdlc-root]/knowledge/agent-context-map.yaml`",
            "- [ ] Communication protocol references use `Read [sdlc-root]/knowledge/architecture/agent-communication-protocol.yaml`",
            "- [ ] Parking lot captures use `Append to [sdlc-root]/disciplines/*.md`",
        ):
            assert old.replace("`", "\\`") in rules, old  # the table cell escapes the inner backticks
        assert "Agent self-lookup at session start uses \\`memory_search(" in rules
        assert "Parking lot captures use \\`memory_store(tags=" in rules
