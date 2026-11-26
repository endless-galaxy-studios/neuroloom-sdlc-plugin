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

import json
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
        # Both forms: a file the transformer missed may name the resolved path.
        assert r"(\[sdlc-root\]|ops/sdlc)/(knowledge|disciplines)/" in audit
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

    def test_project_knowledge_lookup_uses_the_project_specific_tag(self) -> None:
        # 0.7.0: the port, sdlc-ingest and project-knowledge all set sdlc:project-specific.
        rules = _rules()
        assert "Do not search `sdlc:project-specific`" not in rules
        assert "`/sdlc-port` tags every entry upstream didn't have at the project's release" in rules

    def test_legacy_repair_drops_agent_tags_and_warns_on_mixed_families(self) -> None:
        rules = _rules()
        assert "drop `sdlc:agent:<a>`" in rules
        assert "tags of mixed families that match none of the rows above" in rules
        assert "`memory_get_index(...)` call (its `tags` filter is AND by design)" in rules

    def test_resolved_verification_checks_both_tags(self) -> None:
        lifecycle = (_ROOT / "references" / "adapter-lifecycle.md").read_text()
        # By exact tag: the framework entry's id and the new release, an AND with no ranking.
        assert 'memory_get_index(tags=["sdlc:knowledge-id:{framework_id}", "sdlc:seed-version:{target_tag}"], limit=1)' in lifecycle
        assert "the delta file's `framework_ids`" in lifecycle
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

    def test_project_added_knowledge_is_found_by_its_project_specific_tag(self) -> None:
        # Every path now seeds through sdlc_seed, so sdlc:seed no longer separates project knowledge.
        rules = _rules()
        # One call per domain: a single call over all project knowledge can pass the 500-row cap.
        assert 'memory_get_index(tags=["sdlc:knowledge", "sdlc:project-specific", "sdlc:domain:<domain>"], limit=500)` once per domain' in rules
        assert "`sdlc:seed` no longer separates project knowledge from upstream's" in rules
        assert "no offset" in rules and "treat a `count` equal to `limit` as truncated" in rules

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
        assert len(rows) == 6, rows
        assert not rows[0].startswith("| 1 | Everything under"), "sdlc-migrate must be exempt line by line"
        assert "LINE BY LINE" in rows[0]
        assert "Only the span is exempt" in rows[1]
        # Provenance lives in memories (CD, 2026-10-29): no row exempts a read of the log. Only row 6's
        # contract 0026 lines name it, as the project's own file upstream never copies or removes.
        assert [n for n, r in enumerate(rows, start=1) if "provenance_log" in r] == [6]
        assert "which a migration never copies and nothing reads or writes" in rows[5]
        assert "any other line in these files is checked as usual" in rows[5]

    def test_fenced_format_demos_are_exempt_but_dispatch_prompts_are_not(self) -> None:
        row = self._rows()[4]
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


class TestProvenanceRecords:
    """CD's decision (2026-10-29): provenance is memories tagged `sdlc:provenance`, not an on-disk file."""

    def test_the_no_transformation_rows_are_gone(self) -> None:
        rules = _rules()
        for line in rules.splitlines():
            if "provenance_log.md" in line and line.startswith("|"):
                assert "**No transformation**" not in line, line[:100]
        assert "file lives on disk in Neuroloom projects too" not in rules
        assert "project-specific on-disk file" not in rules

    def test_record_shape_and_the_parameter_that_is_easy_to_get_wrong(self) -> None:
        rules = _rules()
        assert 'tags=["sdlc:provenance", "sdlc:source-type:<type>", "sdlc:prov:<prov-id>", "sdlc:prov-status:<status>"]' in rules
        assert 'memory_type="general")' in rules
        assert "**`content=`, not `narrative=`.**" in rules  # memory_store takes content; memory_update takes narrative
        assert "`sdlc_knowledge` and `wiki` are system-only" in rules
        assert "`prov-YYYY-MM-DD-NNN` for ingest and research, `audit-sweep-YYYY-MM-DD-NNN` for Deep Verify sweeps" in rules

    def test_next_id_lookup_and_the_cap(self) -> None:
        rules = _rules()
        assert '`memory_get_index(tags=["sdlc:provenance"], limit=500)`. The index rows carry titles but no tags' in rules
        assert "the highest `prov-<today>-NNN` at the start of a title" in rules
        assert "use `001` when there is none" in rules
        assert "If `count` equals 500 the list is truncated: do not guess an id; say so and ask CD to choose it." in rules
        assert 'memory_get_index(tags=["sdlc:prov:<id>"])' in rules

    def test_status_is_a_tag_selected_exactly_and_changed_with_the_whole_tag_list(self) -> None:
        rules = _rules()
        assert "**Status is a tag as well as a line.**" in rules
        assert ('memory_get_index(tags=["sdlc:provenance", "sdlc:source-type:reference-doc", '
                '"sdlc:prov-status:approved-for-ingest"], limit=500)') in rules
        assert "`memory_get_detail` is called on those rows only" in rules
        assert ("memory_update(id=<id>, tags=[<the record's full tag list, status tag swapped>], "
                "narrative=<the whole record, status line updated>)") in rules
        assert "`memory_update` REPLACES `tags`" in rules and "Always send every tag and every field." in rules
        assert "A sweep record has no status" in rules

    def test_the_status_transition_rows_exist(self) -> None:
        rules = _rules()
        for marker in (
            "`the user approves them to \\`approved-for-ingest\\``",
            "`update that entry's status to \\`ingested\\` and populate the ingestion fields`",
            "sdlc:prov-status:approved-for-ingest swapped for sdlc:prov-status:ingested",
            "the same call with `sdlc:prov-status:rejected` rejects it",
        ):
            assert marker in rules, marker

    def test_the_files_created_match_is_an_exhaustive_scan_not_a_ranked_search(self) -> None:
        rules = _rules()
        row = next(ln for ln in rules.splitlines() if ln.startswith("| `read [sdlc-root]/knowledge/provenance_log.md and find entries with matching"))
        assert "an exhaustive scan: every knowledge entry is matched against every record" in row
        assert 'memory_get_index(tags=["sdlc:provenance"], limit=500) once, then memory_get_detail on each record once' in row
        assert "build a map from every path in its" in row
        assert "If count is 500 the list is truncated: say so and stop" in row
        assert "Do NOT emit a per-entry `memory_search` for this" in row
        assert "memory_search(query=\"<the file or topic>\"" not in rules  # the earlier ranked form is gone

    def test_both_status_change_rows_read_the_current_tags_first(self) -> None:
        """`memory_update` replaces `tags`; an agent that never read them could send only the status tag."""
        rules = _rules()
        consume = next(ln for ln in rules.splitlines() if ln.startswith("| `update that entry's status to"))
        approve = next(ln for ln in rules.splitlines() if ln.startswith("| `the user approves them to"))
        assert "Call memory_get_detail(id=<the record's id>) for its current tags, then memory_update(" in consume
        assert "calls memory_get_detail(id=<id>) for its current tags, then memory_update(" in approve
        for row in (consume, approve):
            assert "drops `sdlc:provenance` and `sdlc:prov:<id>`" in row

    def test_the_reference_doc_selection_is_explained(self) -> None:
        rules = _rules()
        assert rules.count("only `sdlc-research` writes approval handoffs today") >= 1
        assert "a new source type that can be approved must be added to that selection" in rules
        assert "a new source type that can be approved needs adding here" in rules

    def test_scans_that_must_see_every_entry_list_by_index_not_by_ranked_search(self) -> None:
        rules = _rules()
        row = next(ln for ln in rules.splitlines() if ln.startswith("| `List all knowledge YAML files across [sdlc-root]/knowledge/`"))
        assert 'Call memory_get_index(tags=["sdlc:knowledge"], limit=500) to list every knowledge entry.' in row
        assert "If count is 500 the list is truncated: say so and stop" in row
        assert "Not a ranked `memory_search`" in row

    def test_a_sweep_id_is_allocated_at_the_start_and_never_renumbered(self) -> None:
        rules = _rules()
        assert "**Allocate the sweep id now.**" in rules
        assert 'memory_get_index(tags=["sdlc:prov:<S>"]): it must return no row' in rules
        assert "**A sweep is the exception:**" in rules
        assert "a duplicate at store time means STOP and ask CD; never renumber" in rules
        assert "allocate it ONCE at the start of the sweep, before anything uses it" in rules

    def test_several_records_in_one_run_take_consecutive_ids_and_each_is_checked(self) -> None:
        rules = _rules()
        assert "take consecutive ids, the next id, then +1, +2 and so on, and the duplicate check below runs per record" in rules
        assert "with consecutive ids when one run stores several" in rules
        assert "**Then, per record,** call" in rules

    def test_the_two_limits_are_disclosed_next_to_the_store_shape(self) -> None:
        rules = _rules()
        assert "**Two limits to know before relying on the store.**" in rules
        # 1. the index is cut by importance, then age
        assert "ordered by `importance_score` descending, then `created_at` descending" in rules
        assert "falls off before newer, higher-scored ones" in rules
        # 2. free-tier retention (read from api/neuroloom_api/jobs/pruning.py)
        for marker in (
            "`prune_stale_memories`", "no exemption by memory type, tag or importance",
            "NO active superuser member", "with no subscription row the window is 30 days",
            "`retention_days` NULL (paid, unlimited)", "a `pending-review` handoff older than the window is gone",
            "an inference from the record, not a check of its subscription",
        ):
            assert marker in rules, marker

    def test_race_recovery_reaches_the_emitted_text(self) -> None:
        rules = _rules()
        assert "**Then, per record,** call `memory_get_index(tags=[\"sdlc:prov:<prov-id>\"])`: one row is expected." in rules
        assert "the one with the later `created_at` takes the next free id with `memory_update(" in rules

    def test_the_double_rewrite_is_a_single_combined_row_listed_first(self) -> None:
        rules = _rules()
        combined = rules.index("The provenance log (\\`[sdlc-root]/knowledge/provenance_log.md\\`) is the prepared handoff mechanism")
        single = rules.index("| `[sdlc-root]/knowledge/provenance_log.md` named in an Integration list")
        concept = rules.index("| the concept `provenance log` / `provenance entries`")
        assert combined < single and combined < concept, "the combined row must be listed before the two single rows"
        assert "first match wins" in rules and "ONE parenthetical, not two" in rules

    def test_the_rows_cover_the_phrasings_upstream_uses(self) -> None:
        rules = _rules()
        for marker in (
            "to determine the next",
            "Append one entry (or entries) to [sdlc-root]/knowledge/provenance_log.md",
            "The sweep is logged to [sdlc-root]/knowledge/provenance_log.md",
            "update the selected provenance entry's status",
            "(projects can override via [sdlc-root]/knowledge/provenance_log.md header)",
            "event records (\\`provenance_log.md\\` itself, ledgers)",
            "provenance records themselves",
            "named in an Integration list",
            "the concept `provenance log`",
            "list of project-specific files",
            "**Provenance log** \\| knowledge/provenance_log.md",
            "`process/path-mappings.md` row",
        ):
            assert marker in rules, marker
        assert "NOT inside text about the `github-provenance` bundle" in rules

    def test_the_audit_no_longer_exempts_the_log_and_scans_for_the_string(self) -> None:
        audit = _audit()
        assert "Hits whose path is `[sdlc-root]/knowledge/provenance_log.md`" not in audit
        assert "grep -rn --include='*.md' 'provenance_log' .claude/skills .claude/agents ops/sdlc" in audit
        cma = (_ROOT / "references" / "content-merge-audits.md").read_text()
        assert "grep -vE 'provenance_log" not in cma

    def test_the_transformer_no_longer_special_cases_the_log(self) -> None:
        agent = (_ROOT / "agents" / "neuroloom-transformer.md").read_text()
        assert "(not followed by `provenance_log.md`)" not in agent
        assert "other than `provenance_log.md`" not in agent
        assert "ONE exception: its `knowledge/provenance_log.md` row is rewritten" in agent

    def test_the_handlers_and_the_port_skill_stop_creating_or_relocating_the_file(self) -> None:
        lifecycle = (_ROOT / "references" / "adapter-lifecycle.md").read_text()
        assert "create empty template on filesystem only" not in lifecycle
        assert "(except `provenance_log.md`, which is project-specific and lives on disk)" not in lifecycle
        port = (_ROOT / "skills" / "sdlc-port" / "SKILL.md").read_text()
        port += (_ROOT / "skills" / "sdlc-port" / "references" / "provenance-records.md").read_text()
        assert "project's ingestion/research lineage log; relocate but never" not in port
        assert "project-specific append-only record; relocate with" not in port
        assert "### Stage 3c — Provenance Records" in port
        assert 'tags=["sdlc:provenance", "sdlc:source-type:<type>", "sdlc:prov:<prov-id>", "sdlc:prov-status:<status>"]' in port

    def test_the_readme_documents_the_three_tags(self) -> None:
        readme = (_ROOT / "README.md").read_text()
        for tag in ("`sdlc:provenance`", "`sdlc:source-type:{type}`", "`sdlc:prov:{id}`", "`sdlc:prov-status:{status}`"):
            assert tag in readme, tag


# The old name of memory_update's identifier parameter. The MCP server renamed it to `id` (neuroloom-mcp 0.2.0),
# matching memory_get_detail, memory_get_related, memory_rate and memory_delete.
# The schema requires `id`, so the MCP SDK rejects a `memory_id` call at validation, before the handler runs
# (isError: "Input validation error: 'id' is a required property"). A rule that still emits the old name
# produces a call that fails. The pattern is a regex, not a literal, so this file does not match its own scan.
# It matches `memory_id` as ANY keyword argument inside the call's parentheses (one level of nested parens
# allowed), including a backtick-quoted name and a call split over lines.
_MEMORY_UPDATE_OLD_ID_RE = re.compile(r"memory_update\((?:[^()]|\([^()]*\))*?`?\bmemory_id\b`?\s*=")


class TestMemoryUpdateIdParameter:
    """`memory_update` takes the memory's identifier as `id`; no rule document may tell an agent otherwise."""

    def test_no_rule_document_emits_the_old_parameter_name(self) -> None:
        hits = []
        for path in _rule_documents():
            text = path.read_text()
            for m in _MEMORY_UPDATE_OLD_ID_RE.finditer(text):
                n = text.count("\n", 0, m.start()) + 1
                hits.append(f"{path.relative_to(_ROOT)}:{n}")
        assert not hits, "memory_update called with the old identifier parameter (it takes `id`):\n" + "\n".join(hits)

    def test_the_guard_pattern_catches_the_spellings_it_exists_for(self) -> None:
        for bad in (
            "memory_update(memory_id=<id>, tags=[])",
            "memory_update(memory_id='a1b2')",
            "memory_update( memory_id=x)",
            "memory_update(\n    memory_id=x,\n    tags=[])",
            "memory_update(tags=[], memory_id=x)",
            "memory_update(`memory_id`=x)",
        ):
            assert _MEMORY_UPDATE_OLD_ID_RE.search(bad), bad
        for good in (
            "memory_update(id=<id>, tags=[])",
            "memory_update(narrative=<n>, id=<id>)",
            "memory_get_detail(id=<id>)",
            "memory_delete_batch(memory_ids=[<id>])",
            "`memory_update` takes `narrative=`",
        ):
            assert not _MEMORY_UPDATE_OLD_ID_RE.search(good), good

    def test_every_status_and_renumber_call_names_the_memory_with_id(self) -> None:
        rules = _rules()
        status = rules.split("**Status change**", 1)[1].split("\n", 1)[0]
        consume = next(ln for ln in rules.splitlines() if ln.startswith("| `update that entry's status to"))
        approve = next(ln for ln in rules.splitlines() if ln.startswith("| `the user approves them to"))
        renumber = next(ln for ln in rules.splitlines() if ln.startswith("| `Append one entry (or entries) to [sdlc-root]/knowledge/provenance_log.md`"))
        assert "memory_update(id=<id>, tags=[" in status
        assert "memory_update(id=<the record's id>, tags=[" in consume
        assert "memory_update(id=<id>, tags=[" in approve
        assert "memory_update(id=<its id>, title=" in renumber


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
    "plain:other:list": "`List all knowledge YAML files across [sdlc-root]/knowledge/`",
    "plain:other:search": "`Search [sdlc-root]/knowledge/ YAML files for [X]`",
    "plain:other:append to": "`Cross-project knowledge updates append to [sdlc-root]/knowledge/<domain>/`",
    "plain:other:extract to": "`Extract to [sdlc-root]/process/ or [sdlc-root]/knowledge/`",
    "integration": "Integration-section token",
    "fenced-prompt:other:read": "`Read [sdlc-root]/knowledge/<domain>/<file>.yaml`",
    "fenced-agent-template:map:consult": "`consult [sdlc-root]/knowledge/agent-context-map.yaml`",
    "fenced-output": "**EXCEPTION — Output-template blocks",
    "integration-prov": "named in an Integration list",
    "plain:prov:read": "`Read [sdlc-root]/knowledge/provenance_log.md for each knowledge file's last ingestion or refresh date`",
    "plain:prov:next-id": "Read [sdlc-root]/knowledge/provenance_log.md to determine the next",
    "plain:prov:append": "`Append one entry (or entries) to [sdlc-root]/knowledge/provenance_log.md`",
    "plain:prov:logged": "`The sweep is logged to [sdlc-root]/knowledge/provenance_log.md",
    "plain:prov:override": "`(projects can override via [sdlc-root]/knowledge/provenance_log.md header)`",
    "bare-prov:event-records": "`event records (\\`provenance_log.md\\` itself, ledgers)`",
    "bare-prov:migrate-table-row": "`sdlc-migrate` table row `**Provenance log**",
    "bare-prov:readme-copy-clause": "`sdlc-migrate`: `NOT knowledge/provenance_log.md; that's project-specific`",
    "bare-prov:never-overwrite-list": "`sdlc-migrate`: `provenance_log.md` in the list of project-specific files",
    "bare-prov:exclusion-bullet": "a bare list item `- provenance_log.md` in an exclusion list",
    "bare-prov:path-mappings-row": "`process/path-mappings.md` row",
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
    token = tok.group(0)
    if in_integ:
        return "integration-prov" if token.endswith("provenance_log.md") else "integration"
    before = line[: tok.start()].replace("`", "")
    verbs = re.findall(_VERBS, before[-90:])
    fam = (
        "prov" if token.endswith("provenance_log.md")
        else "map" if "agent-context-map" in token else "acp" if "agent-communication-protocol" in token
        else "disc" if "/disciplines/" in token else "yaml" if token.endswith(".yaml") else "other"
    )
    if fam == "prov":
        # a provenance record read serves three purposes; the phrasing, not the verb, tells them apart
        if "next `prov-" in line:
            return "plain:prov:next-id"
        if "override" in line:
            return "plain:prov:override"
        if not verbs:
            return "plain:prov:logged"
    return f"{kind}:{fam}:{verbs[-1].lower() if verbs else '-'}"


_BARE_PROV = re.compile(r"provenance_log(?:\.md)?")
_BARE_EXEMPT_FILES = ("process/sdlc_changelog", "process/changelog-archive/")


def _classify_bare_provenance(rel: str, line: str) -> str:
    """Family for a `provenance_log` mention that is not a `[sdlc-root]/…` path token.

    The path scan misses `provenance_log.md` written without the `[sdlc-root]/knowledge/` prefix:
    a table cell, a list of project-specific files, a bullet, "event records (`provenance_log.md` itself)".
    The post-operation audit greps the bare string, so each of these needs a rule row too.
    """
    if "event records" in line:
        return "bare-prov:event-records"
    if re.match(r"\|\s*\*\*Provenance log\*\*", line):
        return "bare-prov:migrate-table-row"
    if re.search(r"NOT `?knowledge/provenance_log\.md", line):
        return "bare-prov:readme-copy-clause"
    if "never be overwritten" in line or "Current exclusions" in line:
        return "bare-prov:never-overwrite-list"
    if re.match(r"\s*- `provenance_log\.md`\s*$", line):
        return "bare-prov:exclusion-bullet"
    if rel.endswith("path-mappings.md"):
        return "bare-prov:path-mappings-row"
    return "bare-prov:other"


def _upstream_bare_provenance() -> list[tuple[str, int, str, str]]:
    """(file, line, family, text) for every `provenance_log` mention outside a counted path token."""
    out: list[tuple[str, int, str, str]] = []
    for top in ("skills", "process", "templates", "agents"):
        for f in sorted((_UPSTREAM / top).rglob("*.md")):
            rel = str(f.relative_to(_UPSTREAM))
            if rel.startswith(_BARE_EXEMPT_FILES):
                continue
            for n, ln in enumerate(f.read_text().split("\n"), start=1):
                spans = [m.span() for m in _PATH.finditer(ln)]
                for m in _BARE_PROV.finditer(ln):
                    if any(a <= m.start() < b for a, b in spans):
                        continue  # already counted as a path token
                    out.append((rel, n, _classify_bare_provenance(rel, ln), ln))
    return out


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

    def test_every_bare_provenance_log_mention_has_a_row_too(self) -> None:
        """The audit greps the bare string `provenance_log`, so a mention with no `[sdlc-root]/` prefix needs a row."""
        rules = _rules()
        found = _upstream_bare_provenance()
        assert len(found) >= 6, f"inventory looks wrong: only {len(found)} bare mentions"
        for rel, n, family, _line in found:
            marker = _FAMILY_MARKERS.get(family)
            assert marker is not None, f"bare provenance_log mention with no registered row: {family} at {rel}:{n}"
            assert marker in rules, f"{family} ({rel}:{n}): row text missing from pattern-mapping-rules.md: {marker}"

    def test_the_bare_scan_sees_the_mentions_reviewers_named(self) -> None:
        where = {(r, n) for r, n, _f, _l in _upstream_bare_provenance()}
        files = {r for r, _n in where}
        assert "skills/sdlc-audit/references/deep-verify.md" in files  # :38 "event records (`provenance_log.md` itself"
        assert "skills/sdlc-migrate/SKILL.md" in files  # :145, :254, :352
        assert "skills/sdlc-audit/references/compliance-methodology.md" in files  # :236 bullet
        assert "process/path-mappings.md" in files  # :34 row

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


def _agent() -> str:
    return (_ROOT / "agents" / "neuroloom-transformer.md").read_text()


def _row_cells(row: str) -> list[str]:
    """Cells of a Markdown table row, splitting only on unescaped pipes."""
    parts = re.split(r"(?<!\\)\|", row.strip())
    return [c.strip() for c in parts[1:-1]]


def _first_grep_regex(text: str, flags: str) -> str:
    """The single-quoted regex of the first `grep <flags> '…'` command in `text`."""
    m = re.search(r"grep " + re.escape(flags) + r" (?:--include='\*\.md' )?'([^']+)'", text)
    assert m, f"no `grep {flags}` command found"
    return m.group(1)


class TestConceptTerminologyScan:
    """Pass 2 vocabulary has no path in it, so it needs its own entry scan and its own exit scan."""

    def test_step_1_runs_both_the_path_scan_and_the_concept_scan(self) -> None:
        step1 = _agent().split("### Step 1: Runtime Scan", 1)[1].split("### Step 2.0", 1)[0]
        assert "Run BOTH scans" in step1 and "if EITHER finds a match" in step1
        assert "A file with concept terms and no path anchor is NOT `no_patterns`" in step1
        assert "If BOTH scans find nothing" in step1
        assert "a relative link target such as `knowledge/agent-context-map.yaml` included" in step1
        assert "exactly `knowledge/` or `disciplines/`" in step1

    def test_the_entry_scan_the_exit_scan_and_the_post_op_scan_use_one_regex(self) -> None:
        step1 = _agent().split("### Step 1: Runtime Scan", 1)[1].split("### Step 2.0", 1)[0]
        audit7 = _agent().split("### Audit 7", 1)[1]
        check2b = _audit().split("### Check 2b", 1)[1].split("### Check 3", 1)[0]
        a, b = _first_grep_regex(step1, "-inE"), _first_grep_regex(audit7, "-inE")
        c = _first_grep_regex(check2b, "-rinE")
        assert a == b == c, "the three concept scans must be character-for-character identical"
        assert r"\bknowledge stores?\b" in a and r"\bdiscipline parking[- ]lots?\b" in a

    def test_post_operation_check_2b_exists_and_names_the_gap(self) -> None:
        audit = _audit()
        assert "### Check 2b — Concept-terminology residue (WARN; REGRESSION in one case)" in audit
        assert "the transformer's Step 1 scan used path anchors only" in audit
        assert "each file was logged `no_patterns` and Pass 2 never ran on it" in audit
        assert 'subtype: "no_patterns"' in audit and "Step 1 skipped Pass 2 on a file that needed it" in audit
        assert "[✓] Concept-terminology residue" in audit
        assert "Check 2b adds the concept-terminology scan" in (_ROOT / "references" / "adapter-lifecycle.md").read_text()

    def test_rows_for_the_phrasings_the_audit_found(self) -> None:
        rules = _rules()
        assert "a markdown link whose target is the map" in rules
        assert "Domain tags (\\`sdlc:domain:<name>\\`) route the knowledge memory entries each agent role should read" in rules
        assert "an install-layout table cell that is exactly `knowledge/` or `disciplines/`" in rules
        assert "memory entries tagged \\`sdlc:knowledge\\` \\| Structured knowledge memory entries" in rules

    @pytest.mark.skipif(not _upstream_is_v2_2_0(), reason="needs ~/Projects/cc-sdlc checked out at the v2.2.0 tag")
    def test_upstream_has_files_with_concept_terms_and_no_path_anchor(self) -> None:
        """The case Step 1 used to skip. If upstream had none, the extra scan would be dead weight."""
        concept = re.compile(_first_grep_regex(_agent().split("### Step 1: Runtime Scan", 1)[1], "-inE"), re.I)
        only_concept = []
        for top in ("skills", "process", "templates", "agents"):
            for f in sorted((_UPSTREAM / top).rglob("*.md")):
                rel = str(f.relative_to(_UPSTREAM))
                if rel.startswith(_EXEMPT_FILES):
                    continue
                text = f.read_text()
                if concept.search(text) and not _PATH.search(text) and "agent-context-map" not in text:
                    only_concept.append(rel)
        assert {"process/commands.md", "process/guardrail-lifecycle.md"} <= set(only_concept), only_concept

    @pytest.mark.skipif(not _upstream_is_v2_2_0(), reason="needs ~/Projects/cc-sdlc checked out at the v2.2.0 tag")
    def test_every_concept_term_upstream_uses_has_a_concept_row(self) -> None:
        concept = re.compile(_first_grep_regex(_agent().split("### Step 1: Runtime Scan", 1)[1], "-inE"), re.I)
        # Only the left (input) cell of a table row counts: a term that appears only in a replacement cell,
        # a note or a worked example is not a rule for matching it.
        inputs = "\n".join(
            cells[0].lower()
            for cells in (_row_cells(ln) for ln in _rules().splitlines() if ln.startswith("|"))
            if len(cells) >= 2
        )
        missing: dict[str, str] = {}
        for top in ("skills", "process", "templates", "agents"):
            for f in sorted((_UPSTREAM / top).rglob("*.md")):
                rel = str(f.relative_to(_UPSTREAM))
                if rel.startswith(_EXEMPT_FILES) or rel.startswith("skills/sdlc-migrate/"):
                    continue
                for n, ln in enumerate(f.read_text().split("\n"), start=1):
                    for m in concept.finditer(ln):
                        term = m.group(0).lower()
                        stem = term.rstrip("s")  # a row may list the singular only
                        if term not in inputs and stem not in inputs:
                            missing.setdefault(term, f"{rel}:{n}")
        assert not missing, f"concept terms upstream uses that no concept-terminology row names: {missing}"


class TestEscapeSequences:
    """`\n` inside a quoted string or a fence is two characters, never a line break."""

    def test_match_rule_13_and_its_worked_examples(self) -> None:
        rules = _rules()
        assert "13. **Escape sequences are literal text.**" in rules
        assert "does not expand `\\n` into a real newline" in rules
        assert '"0. Identify test targets\\nand verify services" [shape=box];' in rules
        assert "File: src/components/GalleryCarousel.tsx:42\\nCategory: correctness" in rules

    def test_the_post_write_assertion_names_a_baseline_per_region(self) -> None:
        rule13 = _rules().split("13. **Escape sequences are literal text.**", 1)[1].split("\n| ", 1)[0]
        assert "**Post-write assertion:** count the two-character sequence backslash-`n`" in rule13
        assert "the upstream file at the version being installed" in rule13  # outside project blocks
        assert "the project's merged (pre-transform) version of that block or section" in rule13  # inside them
        assert "Upstream is the wrong baseline inside a region" in rule13
        assert "The merged version is the wrong baseline outside a region" in rule13

    def test_step_2b_preserved_sections_are_merged_baseline_regions_like_project_blocks(self) -> None:
        rule13 = _rules().split("13. **Escape sequences are literal text.**", 1)[1].split("\n| ", 1)[0]
        assert "A **preserved region** is either a `PROJECT-SECTION` / `BUNDLE-SECTION` block or a section the Step 2b MCP preservation gate kept" in rule13
        assert "The baseline for the INSIDE of each preserved region is the project's merged (pre-transform) version of that block or section" in rule13
        assert "is paired with its upstream namesake only by a heading match" in rule13
        assert "silently overwrite content the preservation gate deliberately kept" in rule13
        assert "Put the lines back from the region's baseline" in rule13
        assert "restores the lines from its baseline" in _agent() and "a section the Step 2b MCP preservation gate kept" in _agent()

    def test_the_step_2b_gate_the_rule_points_at_still_matches_sections_by_heading(self) -> None:
        gate = _agent().split("**2b. MCP preservation gate:**", 1)[1].split("**Heading fuzzy-match", 1)[0]
        assert "Extract sections containing those calls (delimited by `##`/`###` headings)" in gate
        assert "merge preserved MCP sections back using heading fuzzy-match" in gate

    def test_a_drop_is_restored_and_logged_not_halted_and_the_audit_reports_it(self) -> None:
        rule13 = _rules().split("13. **Escape sequences are literal text.**", 1)[1].split("\n| ", 1)[0]
        assert "**Action on a drop: restore, do not halt.**" in rule13
        assert 'category: "escape_restored"' in rule13 and "halting would stop every remaining file" in rule13
        assert "Halt on a drop" not in rule13  # one action only
        assert "restores the lines from its baseline" in _agent() and "it does not halt" in _agent()
        audit = _audit()
        assert "### Check 2c — Escape preservation (WARN)" in audit and 'category: "escape_restored"' in audit
        assert "[✓] Escape preservation:" in audit

    def test_the_transformer_carries_the_constraint(self) -> None:
        assert "Never change a backslash-n (or any other escape sequence) inside a quoted string or a fenced block" in _agent()

    def test_no_replacement_row_emits_a_backslash_n(self) -> None:
        """The assertion is only sound if no row writes one; the rule prose and its examples are the only places."""
        rules = _rules()
        table_rows = [ln for ln in rules.splitlines() if ln.startswith("|")]
        offenders = [ln[:90] for ln in table_rows if "\\n" in ln.replace("\\n\\", "")]
        assert not offenders, offenders

    @pytest.mark.skipif(not _upstream_is_v2_2_0(), reason="needs ~/Projects/cc-sdlc checked out at the v2.2.0 tag")
    def test_upstream_really_has_escapes_inside_fences_and_quoted_strings(self) -> None:
        """The two files the audit found are real examples, so the rule is not a hypothetical."""
        tests_run = (_UPSTREAM / "skills" / "sdlc-tests-run" / "SKILL.md").read_text()
        protocol = (_UPSTREAM / "process" / "team-communication-protocol.md").read_text()
        assert '"0. Identify test targets\\nand verify services"' in tests_run
        assert "GalleryCarousel.tsx:42\\nCategory: correctness" in protocol


class TestAuthorityStatement:
    def test_readme_and_lifecycle_say_the_adapter_wins(self) -> None:
        for path in (_ROOT / "README.md", _ROOT / "references" / "adapter-lifecycle.md"):
            text = path.read_text()
            assert "Authority in a Neuroloom-backed project: the adapter wins." in text, path.name
            assert "`process/knowledge-routing.md` is this plugin's Neuroloom variant" in text
            assert "`agents/sdlc-reviewer.md` has its phrasing-contract checklist rewritten" in text
            assert "Integration `Uses:`" in text and "are rewritten, not preserved" in text
            assert "not at drift" in text

class TestQuotedTriggerPhrasesInDescriptions:
    """A skill description is prose for Pass 2, except the words a user types: trigger lists and `user:` lines."""

    @staticmethod
    def _scope() -> str:
        return _rules().split("**Pass 2 scope — what counts as \"prose\":**", 1)[1].split("Examples of text Pass 2 CAN transform", 1)[0]

    def test_pass_2_scope_keeps_trigger_lists_and_user_lines_byte_identical(self) -> None:
        scope = self._scope()
        assert "**Exception to the exception: the user's own words.**" in scope
        assert "(a) a quoted phrase in an explicit trigger list" in scope and "`Triggers on`" in scope
        assert '`"verify the knowledge store"`' in scope and "folded/literal-block" in scope
        assert "(b) the quoted text of a `user:" in scope and "line in an `<example>` block" in scope
        assert "outer quotes of a double-quoted YAML value are delimiters, not a phrase" in scope
        assert "The prose around the preserved quotes in the same description is still transformed." in scope

    def test_the_exception_is_not_wider_than_trigger_lists_and_user_lines(self) -> None:
        scope = self._scope()
        assert "Every other quoted span in a description is prose and IS transformed" in scope
        assert "`assistant:" in scope and "the text inside `<commentary>`" in scope
        # the earlier wording covered every escaped quote, user: and assistant: alike
        assert "the escaped quotes of a double-quoted YAML value" in scope  # allowed ONLY inside (a)
        assert "double-quoted trigger phrases" not in scope
        assert "including the `user:" not in scope

    def test_the_must_not_list_and_the_residue_retention_list_agree(self) -> None:
        rules = _rules()
        must_not = rules.split("Examples of text Pass 2 MUST NOT transform:", 1)[1].split("**Pass 2 rules:**", 1)[0]
        assert "A quoted trigger phrase or a `user:` line in a `description:` value" in must_not
        assert "after `Triggers on`" in must_not and "An `assistant:" in must_not and "is prose and is transformed" in must_not
        assert "`already-promoted knowledge-store entries` becomes `already-promoted knowledge memory entries`" in must_not
        retention = rules.split("**Legitimate-retention contexts", 1)[1].split("**Halt condition:**", 1)[0]
        assert "A quoted phrase in a trigger list, or the text of a `user:" in retention
        assert "`assistant:` lines and `<commentary>` are NOT retained" in retention

    def test_post_operation_check_2b_reports_assistant_lines(self) -> None:
        check = _audit().split("### Check 2b", 1)[1].split("### Check 2c", 1)[0]
        assert "a quoted phrase of a trigger list or a `user:" in check
        assert "an `assistant:` line or `<commentary>` text is prose and IS reported" in check

    def test_the_transformer_step_4_says_so(self) -> None:
        step4 = _agent().split("### Step 4: Pass 2", 1)[1].split("Apply concept-terminology rules:", 1)[0]
        assert 'EXCEPT inside a quoted phrase in an explicit trigger list (`Triggers on "verify the knowledge store", …`)' in step4
        assert "or the text of a `user:" in step4 and "stay byte-identical" in step4
        assert "Every other quoted span" in step4 and "is prose and is transformed" in step4

    @pytest.mark.skipif(not _upstream_is_v2_2_0(), reason="needs ~/Projects/cc-sdlc checked out at the v2.2.0 tag")
    def test_upstream_has_a_trigger_list_so_the_rule_is_not_hypothetical(self) -> None:
        frontmatter = (_UPSTREAM / "skills" / "sdlc-audit" / "SKILL.md").read_text().split("---", 2)[1]
        assert 'Triggers on "sdlc audit"' in frontmatter and '"verify the knowledge store"' in frontmatter
        assert re.search(r"knowledge-store entries", frontmatter)  # unquoted prose in the same value

    @pytest.mark.skipif(not _upstream_is_v2_2_0(), reason="needs ~/Projects/cc-sdlc checked out at the v2.2.0 tag")
    def test_upstream_agent_descriptions_carry_user_and_assistant_lines_so_the_split_is_real(self) -> None:
        description = (_UPSTREAM / "agents" / "sdlc-reviewer.md").read_text().split("\n")[2]
        assert 'user: \\"' in description and 'assistant: \\"' in description


class TestCheck2bOwnOutputIsNotAWarn:
    """The replacement strings the plugin writes must not trip the plugin's own residue scan."""

    @staticmethod
    def _hits(line: str) -> list[re.Match[str]]:
        return list(re.compile(_first_grep_regex(_audit().split("### Check 2b", 1)[1], "-rinE"), re.I).finditer(line))

    @staticmethod
    def _followed_by_memory_parenthetical(line: str, m: re.Match[str]) -> bool:
        return re.match(r"\s*\(memory\b", line[m.end():]) is not None

    def test_check_2b_documents_the_memory_parenthetical_exemption(self) -> None:
        check = _audit().split("### Check 2b", 1)[1].split("### Check 2c", 1)[0]
        assert "a hit directly followed by a `(memory …` parenthetical" in check
        assert "Update the knowledge index (memory entries tagged sdlc:knowledge + sdlc:knowledge-index)" in check
        assert "Discipline Parking Lots (memory graph, entries tagged sdlc:discipline:<name>)" in check
        assert "A hit directly followed by a `(memory …` parenthetical" in _rules().split("**Legitimate-retention contexts", 1)[1]

    def test_the_two_strings_the_review_found_match_the_regex_and_are_exempt(self) -> None:
        for line in (
            "Update the knowledge index (memory entries tagged sdlc:knowledge + sdlc:knowledge-index) to list new entries",
            "### 6a. Discipline Parking Lots (memory graph, entries tagged sdlc:discipline:<name>)",
        ):
            hits = self._hits(line)
            assert hits, f"the regex no longer matches {line!r}: the exemption is dead text"
            assert all(self._followed_by_memory_parenthetical(line, m) for m in hits), line

    def test_the_exemption_does_not_swallow_a_real_residue_hit(self) -> None:
        for line in (
            "Update the knowledge index (see the README) to list new entries",
            "Read the discipline parking lots, then (memory notes) follow",
            "Add it to the knowledge store",
        ):
            hits = self._hits(line)
            assert hits and not any(self._followed_by_memory_parenthetical(line, m) for m in hits), line

    def test_both_strings_are_still_in_the_rule_table_they_were_taken_from(self) -> None:
        rules = _rules()
        assert "`Update the knowledge index (memory entries tagged sdlc:knowledge + sdlc:knowledge-index) to list new entries`" in rules
        assert "`### 6a. Discipline Parking Lots (memory graph, entries tagged sdlc:discipline:<name>)`" in rules


class TestDeadRelativeLinks:
    """Links with no `[sdlc-root]/` prefix and no concept term are invisible to Check 2 and Check 2b."""

    def test_step_1_scans_for_relative_link_targets(self) -> None:
        step1 = _agent().split("### Step 1: Runtime Scan", 1)[1].split("### Step 2.0", 1)[0]
        assert "a relative markdown link target under `knowledge/`, `disciplines/` or `bundles/`" in step1
        assert "`](disciplines/README.md)`" in step1 and "`](bundles/README.md)`" in step1 and "`test -d`" in step1

    def test_rows_for_both_links_the_audit_found(self) -> None:
        rules = _rules()
        assert "a markdown link whose target is a relative `disciplines/…` or `knowledge/…` path" in rules
        assert "(see the discipline memory entries tagged \\`sdlc:discipline:<name>\\`)" in rules
        assert "a markdown link or table cell pointing at `bundles/README.md` when the installed tree has no `bundles/` directory" in rules
        assert "The bundle sources are not installed in this project; see \\`bundles/README.md\\` in the upstream z-sdlc repository" in rules
        assert "leave the links alone when `bundles/` is installed" in rules

    def test_check_2d_exists_resolves_targets_and_is_in_the_report(self) -> None:
        audit = _audit()
        check = audit.split("### Check 2d", 1)[1].split("### Check 3", 1)[0]
        assert "(knowledge|disciplines|bundles)/" in check and "`test -e`" in check
        assert "A target that exists is a pass" in check and "**REGRESSION**" in check
        assert "[✓] No dead relative links:" in audit

    @pytest.mark.skipif(not _upstream_is_v2_2_0(), reason="needs ~/Projects/cc-sdlc checked out at the v2.2.0 tag")
    def test_upstream_readme_really_carries_these_links(self) -> None:
        readme = (_UPSTREAM / "README.md").read_text()
        for target in ("](knowledge/agent-context-map.yaml)", "](disciplines/README.md)", "](bundles/README.md)"):
            assert target in readme, target


# Built from parts so this file does not match its own scan.
_OLD_ROOT = ".claude/" + "sdlc"


class TestSdlcRootIsOpsSdlc:
    """0.7.0 moved the SDLC root back to `ops/sdlc` with no `.claude/sdlc` support.

    z-sdlc's factory refuses any path with a `.claude` segment, so a `.claude/sdlc`
    root can never take part in it. The failure these tests pin: an audit scan still
    pointed at the old root greps a directory that is not there and passes without
    having looked, and a cleanup written for the old layout deletes the live root.
    """

    # The guard that refuses the old root, the history line that records what the
    # pre-0.6 audit searched, and the backstop in the manifest check.
    _ALLOWED = frozenset(
        {
            "CHANGELOG.md",
            "references/preflight.md",
            "references/adapter-lifecycle.md",
            "references/post-operation-audit.md",
        }
    )

    def test_only_the_guard_and_history_name_the_old_root(self) -> None:
        found = {
            str(path.relative_to(_ROOT))
            for path in _text_files()
            if path.name != Path(__file__).name and _OLD_ROOT in path.read_text()
        }
        assert found <= self._ALLOWED, sorted(found - self._ALLOWED)

    def test_no_scan_or_recovery_command_targets_the_old_root(self) -> None:
        for path in _text_files():
            if path.name == Path(__file__).name or path.name == "CHANGELOG.md":
                continue
            for n, line in enumerate(path.read_text().splitlines(), 1):
                if _OLD_ROOT in line and re.search(r"\bgrep -r|\brm -rf\b|\brsync\b|\bmv \S", line):
                    pytest.fail(f"{path.relative_to(_ROOT)}:{n} runs a command on the old root: {line.strip()}")

    def test_the_port_moves_nothing(self) -> None:
        port = (_ROOT / "skills" / "sdlc-port" / "SKILL.md").read_text()
        assert "### Stage 4f" not in port
        assert "### Stage 4g — Remap Agent Memory Files" in port

    # The arguments of a recursive `rm`, up to the end of the command.
    _RM_RE = re.compile(r"\brm\s+(?:-[A-Za-z]*[rR][A-Za-z]*|--recursive)(?:\s+-[A-Za-z-]+)*\s+([^`\n;|&]+)")

    @staticmethod
    def _deletes(arg: str) -> str | None:
        path = arg.strip("\"'").removeprefix("./").rstrip("/")
        if path in ("ops", "ops/sdlc", "ops/sdlc/*", ".claude", ".claude/agents", ".claude/agents/*", "[sdlc-root]"):
            return path
        if path.startswith("ops/sdlc/") and path.split("/")[2] not in ("knowledge", "disciplines"):
            return path
        return None

    def test_nothing_deletes_the_root_or_the_agents(self) -> None:
        # `rm -rf ops/sdlc/knowledge/ ops/sdlc/disciplines/` is the one allowed form.
        for path in _text_files():
            if path.name in (Path(__file__).name, "CHANGELOG.md"):
                continue
            for n, line in enumerate(path.read_text().splitlines(), 1):
                for m in self._RM_RE.finditer(line):
                    hits = [p for p in (self._deletes(arg) for arg in m.group(1).split()) if p]
                    assert not hits, f"{path.relative_to(_ROOT)}:{n} deletes {hits}: {line.strip()}"

    def test_the_delete_check_catches_the_shapes_it_must(self) -> None:
        for cmd in ("rm -rf ops/sdlc/", "rm -rf ops/sdlc/knowledge ops/sdlc/", "rm -rf ./ops/sdlc", "rm -r ops/sdlc",
                    'rm -rf "ops/sdlc"', "rm -rf ops/sdlc/*", "rm -rf ops/sdlc/process", "rm -rf .claude/agents/",
                    "rm -Rf ops/sdlc", "rm --recursive ops/sdlc", "rm -rf .claude/", "rm -rf ops", "rm -rf [sdlc-root]/"):
            m = self._RM_RE.search(cmd)
            assert m and any(self._deletes(arg) for arg in m.group(1).split()), cmd
        m = self._RM_RE.search("rm -rf ops/sdlc/knowledge/ ops/sdlc/disciplines/")
        assert m and not any(self._deletes(arg) for arg in m.group(1).split())

    def test_whole_tree_restores_include_the_root(self) -> None:
        for path in _text_files():
            if path.name in (Path(__file__).name, "CHANGELOG.md"):
                continue
            for n, line in enumerate(path.read_text().splitlines(), 1):
                if re.search(r"git checkout -- \.claude/(?=[\s`]|$)", line):
                    assert "ops/sdlc/" in line, f"{path.relative_to(_ROOT)}:{n} restores .claude/ only: {line.strip()}"

    def test_audit_scans_read_ops_sdlc_and_skip_the_data_directories(self) -> None:
        scans = []
        for path in (_ROOT / "references").glob("*.md"):
            for line in path.read_text().splitlines():
                if "grep -r" in line and re.search(r"\sops/sdlc(?=[\s`|]|$)", line):
                    scans.append((path.name, line))
        names = {name for name, _ in scans}
        assert {"post-operation-audit.md", "adapter-lifecycle.md"} <= names, names
        for name, line in scans:
            assert "grep -vE '^ops/sdlc/(knowledge|disciplines)/'" in line, f"{name}: {line.strip()}"

    def test_check_6_rates_only_a_new_map_a_regression(self) -> None:
        check = _audit().split("### Check 6", 1)[1].split("\n---", 1)[0]
        step3 = check.split("\n3. ", 1)[1].split("\n4. ", 1)[0]
        assert "A new `ops/sdlc/knowledge/agent-context-map.yaml`" in step3
        # Contract 0026: what Neuroloom doesn't hold stays on disk and isn't reported.
        assert "are the project's to keep and aren't reported" in step3
        # The map, and on initialize a seeded copy step 9 didn't remove; what step 9 keeps (READMEs, diagrams) isn't reported.
        assert step3.count("**REGRESSION**") == 2
        assert "is a **REGRESSION**: `knowledge-seed` step 9 didn't remove it" in step3
        assert "The files step 9 keeps" in step3
        # Without the flag git names a wholly untracked directory, not the map inside it.
        assert "git status --porcelain --untracked-files=all -- ops/sdlc/knowledge ops/sdlc/disciplines" in check

    def test_the_port_looks_for_the_placeholder_form_the_audit_scans(self) -> None:
        port = (_ROOT / "skills" / "sdlc-port" / "SKILL.md").read_text()
        stage_4a = port.split("### Stage 4a", 1)[1].split("### Stage 4b", 1)[0]
        stage_4a += (_ROOT / "skills" / "sdlc-port" / "references" / "transform-targets.md").read_text()
        assert "`[sdlc-root]/knowledge/` and `[sdlc-root]/disciplines/` forms" in stage_4a
        assert "exemption rows 1 to 6" in stage_4a
        flat = " ".join(stage_4a.split())
        assert "on any of these lines except the changelog's" in flat
        assert "or a `provenance_log` mention on any of them except the changelog's and row 6's, is still rewritten" in flat
        assert "copy `${CLAUDE_PLUGIN_ROOT}/docs/knowledge-routing.md` over" in stage_4a
        # 4d validates what 4a wrote, so it must keep the same exemptions on every check.
        stage_4d = port.split("### Stage 4d", 1)[1].split("### Stage 4g", 1)[0]
        assert "Each check leaves alone exactly what the audit scan" in stage_4d
        assert "`ops/sdlc/process/knowledge-routing.md` is not checked this way" in stage_4d

    def test_the_root_check_runs_in_every_phase_that_can_fire_first(self) -> None:
        lifecycle = (_ROOT / "references" / "adapter-lifecycle.md").read_text()
        for phase in ("knowledge-seed", "knowledge-update", "post-file-write"):
            section = lifecycle.split(f"\n## {phase}\n", 1)[1].split("\n## ", 1)[0]
            assert re.search(r"[Rr]un `preflight.md` check 0", section), phase
        preflight = (_ROOT / "references" / "preflight.md").read_text()
        assert "| 0 | SDLC root is `ops/sdlc`" in preflight
        assert "### Failure 0 — SDLC root is not `ops/sdlc`" in preflight
        port = (_ROOT / "skills" / "sdlc-port" / "SKILL.md").read_text()
        assert "preflight.md` check 0" in port


class TestPortBugFixes070:
    """Bugs found while moving the root, fixed in 0.7.0. Each test pins one."""

    def _port(self) -> str:
        return (_ROOT / "skills" / "sdlc-port" / "SKILL.md").read_text()

    def _ref(self, name: str) -> str:
        # Sections moved out of SKILL.md to keep it under the skill word limit.
        return (_ROOT / "skills" / "sdlc-port" / "references" / name).read_text()

    def _manifest_doc(self) -> str:
        return (_ROOT / "skills" / "sdlc-port" / "references" / "verification-manifest.md").read_text()

    def test_the_port_keeps_z_sdlcs_migrate_and_initialize_skills(self) -> None:
        # The plugin stopped shipping its own copies in c9c44c2; deleting z-sdlc's left no /sdlc-migrate.
        port = self._port()
        assert "### Stage 4e" not in port
        assert "rm -rf .claude/skills/sdlc-initialize" not in port
        assert not (_ROOT / "skills" / "sdlc-migrate").exists()
        assert not (_ROOT / "skills" / "sdlc-initialize").exists()

    def _lifecycle(self) -> str:
        return (_ROOT / "references" / "adapter-lifecycle.md").read_text()

    def test_the_seed_label_and_the_recorded_seed_version_agree(self) -> None:
        # Stage 5 once named CURRENT_SDLC_VERSION while Stage 3a labelled the seed source_version,
        # so Check 5 compared the sentinel with the wrong release and failed a correct port.
        doc = self._manifest_doc()
        assert "`knowledge_seed_version`: the version label Stage 3a passed to `sdlc_seed` (the Inventory's\n  **The seed's label**" in doc
        port = self._port()
        assert '--version "<label>"' in port
        assert "the two `--baseline-*` flags and `--tag-new` (only when the manifest has no version key), and keep the\nsame label." in port

    def test_a_re_port_refuses_an_unmarked_or_migrated_workspace(self) -> None:
        # Re-porting over pre-0.7.0 records left them beside the new ones; after a migration it
        # put older on-disk text back over what knowledge-update sent.
        port = self._port()
        assert 'when the manifest lacks `"knowledge_id_scheme": 2` (ported\n   before 0.7.0' in self._ref("gate-3.md")
        assert "`incomplete_port_record`" in self._ref("gate-3.md")
        assert "`knowledge_seed_version` differs, ignoring a leading `v`, from the label the Inventory's" in self._ref("gate-3.md")
        assert "Post-Port Cleanup is skipped on a re-port." in port
        assert "Skip this section, removing nothing, on every re-port" in self._manifest_doc()

    def test_an_old_scheme_workspace_halts_without_a_rebuild_recipe(self) -> None:
        # Replayed on the one such workspace, every files-based rebuild lost upstream entries added
        # since the files and edits made only in Neuroloom; the halt now says a conversion is needed.
        doc = self._lifecycle()
        assert "needs a one-time conversion to the current ids, which this release doesn't do. Don't improvise one." in doc
        assert "memory_delete_batch" not in doc
        assert "paging with `offset`" not in doc
        assert "**Halts and their recoveries.**" in doc

    def test_a_re_port_with_no_files_skips_the_seed_and_the_label_stays_source_version(self) -> None:
        # After the first port's cleanup the extractor finds nothing, and --tag-new then exits 1.
        port = self._port()
        assert "files. Neuroloom's copy is then the live one" in port
        assert "Skip Stage 3a when the Inventory's **Zero entries** rule says to." in port
        # A failed baseline fetch once relabelled the seed CURRENT_SDLC_VERSION while Stage 5
        # recorded source_version, failing Check 5 and Gate 3's re-port check.
        assert "`{CURRENT_SDLC_VERSION}` only when the manifest has\nneither, and then on a re-port the `knowledge_seed_version` it already records" in port
        # An untagged install's source_version is "unknown"; comparing that with the recorded
        # short commit id refused every re-port, so Gate 3 compares with the label rule.
        assert "the first 7 characters of `source_version_sha`" in port
        # With neither version key the label is the latest release, which a re-port can't match.
        assert "(that check is skipped when the manifest has no version key)" in self._ref("gate-3.md")
        # Skipping on zero entries once trusted that Neuroloom held the knowledge; with the key on
        # another workspace, Stage 3b then wrote deliverables there. Gate 3 now checks it.
        assert "(Gate 3 checked that this workspace holds the sentinel)" in port
        inventory = port.split("### Inventory", 1)[1].split("## Stage 2", 1)[0]
        assert 'gh api "repos/endless-galaxy-studios/z-sdlc/tarball/<ref>" > "<SEED>/z.tgz"' in inventory

    def test_gate_3_decides_by_the_manifest_and_checks_the_workspace_on_every_re_port(self) -> None:
        # Id probes couldn't tell a stopped port from 0.6.x or another project's records, and three
        # rounds each found another prose gap, so the decision is a tested script
        # (tests/test_decide_port_gate.py holds its table) and the skill only gathers facts.
        port = self._port()
        gate_3 = port.split("### Gate 3", 1)[1].split("### Inventory", 1)[0]
        assert "sdlc:deliverable:…" not in gate_3
        assert "grep" not in gate_3
        assert 'python3 "${CLAUDE_SKILL_DIR}/scripts/decide_port_gate.py" --facts <file>' in gate_3
        assert "never write a value for one you couldn't observe or\ndecide by hand" in gate_3
        assert "references/gate-3.md` § The facts" in gate_3
        assert '`memory_get_index(tags=["sdlc:sentinel"], limit=1)`: `sentinel` is whether it returns a row' in self._ref("gate-3.md")
        assert (_ROOT / "skills" / "sdlc-port" / "scripts" / "decide_port_gate.py").exists()
        # The marker names its workspace; the scheme marker waits for Stage 5, so it means complete.
        assert 'merge `"port_in_progress": true`\nand `"workspace_id"`' in port
        assert 'Stage 5 removes\n`port_in_progress` and writes `"knowledge_id_scheme": 2`, which means the seed is complete.' in port
        assert "Port: no `port_in_progress` key." in (_ROOT / "references" / "post-operation-audit.md").read_text()
        doc = self._manifest_doc()
        assert "remove `port_in_progress`, which Stage 3 wrote" in doc
        assert "by copying `.sdlc-manifest.json.pre-port` back over it, whether or not git tracks the file" in doc

    def test_knowledge_seed_halts_a_re_initialization_over_old_records(self) -> None:
        doc = self._lifecycle()
        seed = doc.split("## knowledge-seed", 1)[1].split("## project-knowledge", 1)[0]
        assert "If the manifest has neither that nor `\"knowledge_id_scheme\": 2`, nothing says whose those entries are" in seed
        # An in-progress key before the first call, so a re-run after a failed file isn't mistaken
        # for old records; the complete marker only after the last, so a migration of a half-seeded
        # workspace halts instead of sending a delta over the gap.
        assert '5. **Mark the seed as started, then seed every file with `skip_deprecation: true`.** First set `"knowledge_seed_in_progress": true`' in seed
        assert 'When every file succeeded, set `"knowledge_id_scheme": 2` and remove `knowledge_seed_in_progress`.' in seed
        # One recovery per operation, stated once: undoing an initialize deleted the manifest that
        # held the marker, and re-running only steps 1-6 skipped the workspace check and step 8.
        doc_top = doc.split("## knowledge-seed", 1)[0]
        assert "| `/sdlc-initialize` | **Keep, then finish by hand.** Undo nothing" in doc_top
        assert "run its section from this file (the pre-seed check, steps 0 to 9 and the post-seed check)" in doc_top
        # Upstream calls project-knowledge and post-file-write once per item, so a halt mid-phase
        # resumes from the start of that phase, not the one after it.
        assert "go back to the start of the upstream phase that called the halted handler" in doc_top
        assert "Phase 5's adapter check, then Phase 7 onward" in doc_top
        assert "fetch --depth 1 origin tag <source_version>" in doc_top
        assert "exception to the undo recovery" not in doc

    def test_every_phase_that_writes_checks_the_workspace(self) -> None:
        # Migrate never compared workspaces: with the key on another project's workspace,
        # knowledge-update rewrote its rows and moved its sentinel (probe ids matched there too).
        doc = self._lifecycle()
        assert "**The workspace check.** Every phase that writes to Neuroloom first finds out which workspace" in doc
        for section, end in (("## knowledge-seed", "## project-knowledge"), ("## project-knowledge", "## knowledge-update"),
                             ("## knowledge-update", "## post-file-write"), ("## post-file-write", "### Dispatch")):
            assert "**The workspace check**" in doc.split(section, 1)[1].split(end, 1)[0], section

    def test_every_neuroloom_write_outside_the_port_is_behind_the_workspace_check(self) -> None:
        # Rounds 7 to 9 each found one more write site without it; this walks the write actions.
        transformer = (_ROOT / "agents" / "neuroloom-transformer.md").read_text()
        frontmatter = transformer.split("---", 2)[1]
        assert "mcp__neuroloom__memory_search" in frontmatter
        guard = transformer.index("**Before either Neuroloom write below**")
        for action in ("**`ingest_to_neuroloom`:**", "**`sync_archive_status`:**"):
            assert transformer.index(action) > guard, action
        for path in sorted((_ROOT / "references").glob("*.md")) + sorted((_ROOT / "skills" / "sdlc-port").rglob("*.md")):
            for line in path.read_text().splitlines():
                if "sdlc_seed_from_file(" in line or "sdlc_seed_get_upload_url(" in line:
                    assert "skip_deprecation=true" in line, (path.name, line[:120])

    def test_the_no_op_send_keeps_skip_deprecation(self) -> None:
        # Without it a one-entry seed deprecates the rest of the workspace and the Sunday job deletes it.
        assert "and send it with `skip_deprecation=true` like every other file" in self._lifecycle()

    def test_the_discipline_check_queries_a_tag_ported_entries_carry(self) -> None:
        doc = self._manifest_doc()
        assert 'tags=["sdlc:discipline:architecture"]' not in doc
        assert '`memory_get_index(tags=["sdlc:discipline"], limit=1)` (by exact tag' in doc

    def test_a_re_port_skips_cleanup_and_the_manifest_is_merged(self) -> None:
        # The "skip this prompt on future re-ports" option was dropped once every re-port skipped cleanup.
        doc = self._manifest_doc()
        cleanup = doc.split("### Post-Port Cleanup", 1)[1]
        assert "Skip this section, removing nothing, on every re-port" in cleanup.split("Otherwise use `AskUserQuestion`", 1)[0]
        assert "skip_cleanup_prompt" not in doc + self._port()
        write = doc.split("### Write Manifest", 1)[1].split("```json", 1)[0]
        assert "keep every other key" in write

    def test_initialize_removes_the_map(self) -> None:
        lifecycle = (_ROOT / "references" / "adapter-lifecycle.md").read_text()
        seed = lifecycle.split("\n## knowledge-seed\n", 1)[1].split("\n## ", 1)[0]
        assert "8. **No agent-context-map.**" in seed
        assert "rm -f ops/sdlc/knowledge/agent-context-map.yaml" in seed

    def test_provenance_is_stored_after_the_confirmation_not_in_stage_4a(self) -> None:
        port = self._port()
        stage_3c = self._ref("provenance-records.md")
        stage_4a = port.split("### Stage 4a", 1)[1].split("### Stage 4b", 1)[0] + self._ref("transform-targets.md")
        assert "references/provenance-records.md" in port.split("### Stage 3c", 1)[1].split("## Stage 4", 1)[0]
        assert "memory_store(" in stage_3c and "memory_get_index(" in stage_3c
        assert "memory_store(" not in stage_4a
        assert "then delete the file" not in port

    def test_skipping_transformations_ends_the_run_before_the_manifest(self) -> None:
        # A manifest calling an untransformed project ported makes the next migration half-transform it.
        stage_4b = self._port().split("### Stage 4b", 1)[1].split("### Stage 4c", 1)[0]
        # The in-progress marker Stage 3 wrote stays, and says nothing about being ported.
        assert "the run ends here: no 4c, 4d or 4g, no Stage 5 manifest write (on a fresh port, Stage 3's in-progress marker stays)" in stage_4b

    def test_stage_5_writes_the_adapter_block_and_keeps_the_release(self) -> None:
        write = self._manifest_doc().split("### Write Manifest", 1)[1].split("### Verification Checklist", 1)[0]
        # z-sdlc contract 0025: the plugin is named by id, never by one machine's install path.
        assert '"adapter": {' in write and '"plugin": "neuroloom-sdlc@endless-galaxy-studios"' in write
        block = write.split('"adapter": {', 1)[1].split("}", 1)[0]
        assert "plugin_root" not in block
        assert "Do not touch `source_version` or `source_version_sha`" in write
        assert '"source_version": "{version from sdlc_get_version' not in write
        assert "the sha256 of every file the port wrote" in write

    def test_the_map_is_removed_and_recorded(self) -> None:
        lifecycle = (_ROOT / "references" / "adapter-lifecycle.md").read_text()
        seed = lifecycle.split("\n## knowledge-seed\n", 1)[1].split("\n## ", 1)[0]
        assert "`declined_files`" in seed and "drop the file's `installed_files` entry" in seed
        # Upstream now skips Phase 5 and adjusts 9a/10/11 itself (contract 0024): no prose for them.
        assert "contract 0024" in seed and "tell the rest of the run" not in seed
        assert "git rm ops/sdlc/knowledge/agent-context-map.yaml" not in _audit()

    def test_the_port_and_the_audit_name_the_same_exemption_rows(self) -> None:
        table = _audit().split("**Exemptions.**", 1)[1].split("**Second scan", 1)[0]
        rows = {int(m.group(1)): m.group(0) for m in re.finditer(r"^\| (\d) \|.*$", table, re.MULTILINE)}
        assert sorted(rows) == [1, 2, 3, 4, 5, 6], sorted(rows)
        assert "sdlc-migrate" in rows[1] and "- [ ] No" in rows[2] and "path-mappings.md" in rows[3]
        assert "sdlc_changelog.md" in rows[4] and "fenced block" in rows[5] and "Contract 0026" in rows[6]
        doc = self._manifest_doc()
        for name in ("No stale path references", "No stale YAML references"):
            row = next(line for line in doc.splitlines() if line.startswith(f"| {name} |"))
            assert "rows 1 to 6" in row and "knowledge-routing.md" in row, row
        # A port installs z-sdlc's file-presence lines too, so its provenance check exempts them as the audit does.
        assert "the `provenance_log` check exempts the changelog and row 6's lines" in doc
        assert "exempts only the changelog and the contract 0026 file-presence lines" in " ".join(self._port().split())

    def test_nothing_points_at_the_removed_migrate_override(self) -> None:
        for rel in ("README.md", "references/post-operation-audit.md", "docs/knowledge-routing.md",
                    "skills/sdlc-port/references/verification-manifest.md"):
            text = (_ROOT / rel).read_text()
            assert "Detecting Files That Contain Phrasing-Contract Patterns" not in text, rel
            assert "sdlc-migrate/SKILL.md" not in text, rel

    def test_a_re_port_updates_a_provenance_record_whose_status_changed(self) -> None:
        stage_3c = self._ref("provenance-records.md")
        assert "memory_update(" in stage_3c

    def test_4d_exempts_what_each_audit_scan_exempts(self) -> None:
        # Check 2d exempts only the changelog; the provenance scan the changelog and Check 2 row 6's
        # contract 0026 lines. Rows 1 to 5 apply to Check 2's path scan alone.
        stage_4d = self._port().split("### Stage 4d", 1)[1].split("### Stage 4g", 1)[0]
        bullets = [" ".join(b.split()) for b in stage_4d.split("\n- ")]
        prov = next(b for b in bullets if b.startswith("No remaining `provenance_log`"))
        assert "outside `sdlc_changelog.md`, `changelog-archive/*.md` and the contract 0026 file-presence lines of the audit's Check 2 row 6" in prov
        assert "rows 1" not in prov
        link = next(b for b in bullets if b.startswith("No remaining relative markdown link"))
        assert "outside `sdlc_changelog.md` and `changelog-archive/*.md`" in link and "rows" not in link

    def test_the_cleanup_records_only_the_map(self) -> None:
        # z-sdlc contract 0024: the knowledge layer is the adapter's; upstream never asks about a
        # missing file there, and a declined knowledge file would never be seeded again.
        cleanup = self._manifest_doc().split("### Post-Port Cleanup", 1)[1].split("### Final Summary", 1)[0]
        assert "record `ops/sdlc/knowledge/agent-context-map.yaml`" in cleanup
        assert "Record nothing else." in cleanup
        assert "doesn't ask about each one" not in cleanup

    def test_an_audit_failure_restores_the_manifest_too(self) -> None:
        # From the pre-port copy, not git: the copy keeps port_in_progress, which a checkout would drop.
        audit_part = self._manifest_doc().split("### Post-Operation Audit", 1)[1].split("### Post-Port Cleanup", 1)[0]
        assert "by copying `.sdlc-manifest.json.pre-port` back over it" in audit_part

    def test_stage_3c_checks_status_with_a_lookup_that_can_see_it(self) -> None:
        stage_3c = self._ref("provenance-records.md")
        assert 'memory_get_index(tags=["sdlc:provenance", "sdlc:prov:<id>"], limit=1)' in stage_3c
        assert "memory_get_detail(" in stage_3c and "If its `source` differs" in stage_3c
        assert "`rejected` counts as later than all three; a stored `rejected` is never changed" in " ".join(stage_3c.split())

    def test_the_cleanup_deletes_only_what_was_ingested(self) -> None:
        cleanup = self._manifest_doc().split("### Post-Port Cleanup", 1)[1].split("### Final Summary", 1)[0]
        assert "`source_path`" in cleanup and "and stays." in " ".join(cleanup.split())
        assert "rm -rf ops/sdlc/knowledge" not in cleanup

    def test_no_mode_skips_the_root_check(self) -> None:
        # "Partial port" resumed from Stage 3 and skipped Gate 1; a failed port now re-runs from the start.
        mode = self._port().split("## Mode Detection", 1)[1].split("## Stage 1", 1)[0]
        assert "**Partial port**" not in mode
        assert "re-running it from the start finishes it" in mode

    def test_ported_agents_get_the_tools_their_calls_need(self) -> None:
        stage_4c = self._port().split("### Stage 4c", 1)[1].split("### Stage 4d", 1)[0]
        assert "**Agent tools.**" in stage_4c and "Agent tool injection" in stage_4c

    def test_no_recovery_cleans_or_restores_files_the_run_did_not_write(self) -> None:
        # Whole-tree git checkout wiped CD's uncommitted edits, and git clean removed an uncommitted
        # initialize; the undo now saves everything first and restores only a run on a clean tree.
        lifecycle = (_ROOT / "references" / "adapter-lifecycle.md").read_text()
        table = lifecycle.split("**Halts and their recoveries.**", 1)[1].split("**The workspace check.**", 1)[0]
        # Every narrower rule still lost some of CD's edits: git can't tell them from the run's
        # without a snapshot, so the undo saves everything first and restores only a clean run.
        assert "`git diff --binary > <dir>/pre-undo.patch`" in table
        assert "**Not clean, or not sure:** change nothing, with one exception" in table
        for path in _text_files():
            if path.name in (Path(__file__).name, "CHANGELOG.md"):
                continue
            for n, line in enumerate(path.read_text().splitlines(), 1):
                if re.search(r"\bgit\b(\s+-C\s+\S+)?\s+clean\b", line):
                    raise AssertionError(f"{path.relative_to(_ROOT)}:{n}: git clean in a recovery: {line.strip()}")

    def test_no_migrate_recovery_restores_a_file_without_saving_first(self) -> None:
        # A per-file `git checkout` skips the save and throws away uncommitted edits in that file.
        for path in _text_files():
            if path.name in (Path(__file__).name, "CHANGELOG.md"):
                continue
            text = path.read_text()
            for n, line in enumerate(text.splitlines(), 1):
                # The table's own clean-run restore comes after its save step.
                if "**Save, then undo only a clean run, then re-run.**" in line:
                    continue
                if re.search(r"git checkout -- [{<]", line) and "migrat" in line.lower():
                    raise AssertionError(f"{path.relative_to(_ROOT)}:{n}: {line.strip()[:120]}")
        lifecycle = (_ROOT / "references" / "adapter-lifecycle.md").read_text()
        # .git is a file in a worktree or submodule; --git-path finds the real git directory.
        assert "`$(git rev-parse --git-path sdlc-undo)/<timestamp>/`" in lifecycle and "Git overrules a yes" in lifecycle
        assert "If any save step fails, undo nothing" in lifecycle
        assert "put it back alone from the run's **manifest snapshot**" in lifecycle
        assert "**The manifest snapshot (migrate).**" in lifecycle

    def test_both_first_steps_take_the_manifest_snapshot(self) -> None:
        # The snapshot is the only way back for an untracked manifest or uncommitted keys after §4.5;
        # described only in a preamble, an executor following the steps could skip it.
        lifecycle = (_ROOT / "references" / "adapter-lifecycle.md").read_text()
        ku = lifecycle.split("## knowledge-update", 1)[1].split("## post-file-write", 1)[0]
        pfw = lifecycle.split("## post-file-write", 1)[1].split("### Dispatch", 1)[0]
        for step in (ku, pfw):
            assert "**the manifest snapshot** (top of this file) if no earlier phase of this run did" in step
        assert "A failed copy halts the phase before any write." in lifecycle
        # sdlc-ingest carries its report, which the transformer's ingest needs.
        assert "- report: [for `sdlc-ingest`, its INGESTION REPORT" in lifecycle
        assert "- `report` (transform mode, `sdlc-ingest` only)" in (_ROOT / "agents" / "neuroloom-transformer.md").read_text()

    def test_ingest_sends_only_the_entries_the_run_added(self) -> None:
        # A discipline file sdlc-ingest creates is mostly a stub; sending all of it overwrote the
        # discipline's framework text with the stub's (replayed by the round-19 reviewers).
        transformer = (_ROOT / "agents" / "neuroloom-transformer.md").read_text()
        assert "Never send an entry the extractor built from a discipline file's framework, status" in transformer
        # Kept created stubs move out of the extractor's reach on every halt, not only after an attempt.
        assert "A discipline file the report marks as created is never kept at its path, on this or any halt" in transformer
        assert "pass `--only-ids <file>`" in transformer
        # A report entry that matched no id left its bullet unsent while the created file was deleted.
        assert "Each added entry must match exactly one id" in transformer
        assert "every id the extractor produced from the file was sent" in transformer
        port = (_ROOT / "skills" / "sdlc-port" / "SKILL.md").read_text()
        assert "rm -f CLAUDE.md.pre-port CLAUDE.md.pre-port.region" in port
        # A marked CLAUDE.md is restored between the copy's own markers: a heading range drops the
        # text before the first ## and runs past SDLC-END.
        assert "When the copy has markers, write no region file: a restore takes the text between\nthe copy's own markers." in port
        # The range must run past the last recorded heading, or a restore keeps only the first section.
        assert "or `##` heading outside fenced code after the last, each at its recorded line" in port
        # The region file is written before the markers, counting lines in the copy.
        assert "first record the region's first and last `##` headings and their line\nnumbers (1-based) in the copy" in port
        # A re-port never sends a discipline's framework or structure, so an ingest stub on disk,
        # tracked or not, can't overwrite Neuroloom's (an untracked-file stop missed committed stubs).
        assert "On a re-port add\n`--exclude-kinds framework,status,parking-lot-structure,active-questions,project-context,maturity-tracker`" in port
        assert "**Untracked discipline files (re-port).**" not in port
        # A continued port records the region approved in this run until its markers are in.
        assert "a continued port (Gate 3's action was `continue_fresh`) whose `CLAUDE.md` has markers: an earlier run\nof this port made it from the untransformed file." in port
        assert "(kept with a kept copy, else written now from the region approved in this run)" in port
        # A leftover copy may be the only original (a first port that crashed after Stage 5's write).
        assert "Otherwise first move a leftover copy and region file aside, adding\n`.$(date -u +%Y%m%dT%H%M%SZ)` to each name (`mv -n`, with the first suffix, `.<ts>`, `.<ts>-2` …, free for both names; copy afresh only once both are gone): never deleted automatically" in port
        assert "a failed audit's recovery would discard them" not in port
        vm_text = (_ROOT / "skills" / "sdlc-port" / "references" / "verification-manifest.md").read_text()
        # Rehashing an earlier run's transforms would take CD's between-run edits as the port's own.
        assert "but each only when the run created it or its copy under `<undo>/files/`" in vm_text
        assert "undo the run as a checklist failure does" in vm_text
        assert "Agent memory comes back with the rest of `<undo>/files/`" in vm_text
        assert "undo the run as an audit failure does" in vm_text
        assert "Give every agent whose text calls a Neuroloom tool (`memory_search`, `memory_store` or another), whichever run" in port
        assert "add its path to `<undo>/created`" in port
        assert "`CLAUDE.md.pre-port.before-continue-" in port
        assert "Stage 4d restores from `CLAUDE.md.pre-port` (never a set-aside copy)" in port
        assert "Otherwise replace a leftover copy" not in port
        vm = (_ROOT / "skills" / "sdlc-port" / "references" / "verification-manifest.md").read_text()
        assert "CLAUDE.md copies set aside:" in vm
        port_recovery = (_ROOT / "skills" / "sdlc-port" / "references" / "recovery-procedures.md").read_text()
        assert "a tag Neuroloom adds itself (remove it from the item)" in port_recovery
        assert "so its path under `knowledge/` no longer begins `discipline`" in port_recovery
        # Stage 4 undoes from its own pre-edit copies, never from git: a checkout discards uncommitted edits.
        assert "**Every other file.** Fix `<undo>` once, at the start of Stage 4c (4g and Stage 5 keep this run's\nundo state in it too)" in port
        # One directory holds a run's whole undo state, so no crash can split a run from its snapshot.
        assert "to `<undo>/sdlc-manifest.json` (this run's own snapshot" in (_ROOT / "skills" / "sdlc-port" / "references" / "verification-manifest.md").read_text()
        assert "if `<undo>/sdlc-manifest.json` exists (Stage 5 had started), copy it back over the manifest" in (_ROOT / "skills" / "sdlc-port" / "references" / "recovery-procedures.md").read_text()
        remap = (_ROOT / "skills" / "sdlc-port" / "references" / "agent-memory-remap.md").read_text()
        assert "mktemp" not in remap and "copy each file to `<undo>/files/<its path>`" in remap
        assert "its profile's tools plus any other Neuroloom tool its text calls" in port
        tp = yaml.safe_load((_ROOT / "transforms.yaml").read_text())["tool_profiles"]
        for name in ("full", "knowledge_contributor"):
            assert "mcp__neuroloom__memory_update" in tp[name]["tools"], name
        # Bookkeeping (<undo>/created) sits outside the copied tree, so a restore never copies it into the project.
        assert "`<undo>/<its path>`" not in port and "Copy each file to `<undo>/files/<its path>`" in port
        audit_text = (_ROOT / "references" / "post-operation-audit.md").read_text()
        assert "is drift Stage 5 kept on purpose, so a migration asks about it: WARN" in audit_text
        rec = (_ROOT / "skills" / "sdlc-port" / "references" / "recovery-procedures.md").read_text()
        assert "ask CD which run to undo" in rec and "the newest directory" not in rec
        assert "copy it back over the manifest, whether or not the manifest still parses" in rec
        # A spent undo must not be applied again, and the unreadable-manifest row must not pick another run's snapshot.
        assert "the newest `<undo>/sdlc-manifest.json`" not in rec
        assert "Then delete this run's `<undo>`, so no later recovery applies it again" in (_ROOT / "references" / "post-operation-audit.md").read_text()
        assert "delete this run's `<undo>`, so no later recovery applies it again" in (_ROOT / "skills" / "sdlc-port" / "references" / "verification-manifest.md").read_text()
        assert "| Moving a replaced `knowledge-routing.md` into `sdlc-port-kept/` fails after a passing audit |" in rec
        profiles = yaml.safe_load((_ROOT / "transforms.yaml").read_text())["tool_profiles"]
        for name, prof in profiles.items():
            # pattern-mapping-rules rewrites provenance and project-knowledge reads to memory_get_index.
            assert "mcp__neuroloom__memory_get_index" in prof["tools"], name
        assert "once, before its first edit or replacement\n(`mkdir -p`, then `[ -e <copy> ] || cp <file> <copy>`), and before handing it to a subagent" in port
        # "Set aside" read as mv would remove CLAUDE.md itself before a restore.
        assert "copy (not move) the current file to\n`CLAUDE.md.pre-port.before-continue-" in port
        assert "copy (not move) the current\nfile to `CLAUDE.md.pre-port.before-restore-" in port
        vm_doc = (_ROOT / "skills" / "sdlc-port" / "references" / "verification-manifest.md").read_text()
        # The kept directory must exist before the move, and nothing is deleted after a failed move.
        assert "`mkdir -p` the kept directory (`$(git rev-parse --git-path sdlc-port-kept)`, or `.sdlc-port-kept/` outside git)" in vm_doc
        assert "if the move fails, halt and delete nothing" in vm_doc
        assert "differs from the plugin's copy (`cmp -s` fails" in vm_doc
        lifecycle_doc = (_ROOT / "references" / "adapter-lifecycle.md").read_text()
        assert "Separately, append any other Neuroloom tool (`mcp__neuroloom__*`) the agent's text calls that the line lacks, and any tool in `transforms.yaml` → `memory_grant_tools` that its memory" in lifecycle_doc
        assert "give each agent whose memory now calls a Neuroloom tool its tools" in (
            _ROOT / "skills" / "sdlc-port" / "references" / "agent-memory-remap.md").read_text()
        assert "matched its hash in `.sdlc-manifest.json.pre-port`" in vm_doc
        for doc_path in ("skills/sdlc-port/references/verification-manifest.md", "references/post-operation-audit.md"):
            text = (_ROOT / doc_path).read_text()
            assert "every file under this run's `<undo>/files/` back to its path and remove each one `<undo>/created` lists" in text, doc_path
            assert "first copying (not moving) the current file to `CLAUDE.md.pre-port.before-restore-<timestamp>`" in text, doc_path
        assert "| The port is abandoned after Stage 4c" in (_ROOT / "skills" / "sdlc-port" / "references" / "recovery-procedures.md").read_text()
        assert "If validation fails for a file, copy it back from `<undo>/files/<its path>`" in port

        for doc_path in ("skills/sdlc-port/SKILL.md", "skills/sdlc-port/references/verification-manifest.md",
                         "skills/sdlc-port/references/recovery-procedures.md", "references/post-operation-audit.md"):
            text = (_ROOT / doc_path).read_text()
            assert not re.search(r"git checkout (--\s+)?(\.claude/|ops/sdlc/)", text), doc_path
        assert "this run's `<undo>`" in vm and "Earlier runs' file copies:" in vm
        assert "When Gate 3 saw no sentinel and no SDLC records this run (always so when its action was `fresh`), nothing in Neuroloom depends on the marker yet" in port_recovery
        assert "Otherwise keep them: an earlier run's records are in Neuroloom" in port_recovery
        assert "a malformed `tags` value (make it a list of strings, quoting an element YAML would read as a boolean or number)" in port_recovery
        for doc in (vm, (_ROOT / "references" / "post-operation-audit.md").read_text()):
            # A re-port can build on a crashed run's uncommitted transforms: an audit failure restores Stage 4c's copies.
            assert "every file under this run's `<undo>/files/` back to its path" in doc
        audit = (_ROOT / "references" / "post-operation-audit.md").read_text()
        for doc in (vm, audit):
            assert "Stage 4c's set-aside copies: one may hold the only untransformed original" in doc
        assert "A non-zero exit stops the port with its message; nothing has been written." in port
        recovery = (_ROOT / "references" / "recovery-procedures.md").read_text()
        assert "It saves the tree first, so what §4.5 recorded" in recovery
        assert "follow migrate's recovery for the rest" not in recovery
        lifecycle = (_ROOT / "references" / "adapter-lifecycle.md").read_text()
        assert "a copy of `.sdlc-manifest.json` itself at `<dir>/sdlc-manifest.json` whatever git makes of it" in lifecycle
        # The dry run, the question and the gate's ask text all say the same thing.
        assert "(On a re-port, add Stage 3a's `--exclude-kinds`.)" in port
        assert "It never\nre-sends a discipline's framework, status, Active Questions, Project Context\nor tracker" in port
        gate = (_ROOT / "skills" / "sdlc-port" / "scripts" / "decide_port_gate.py").read_text()
        assert "never a discipline's framework or project data" in gate
        # A kept created discipline stub would be read by a later re-port as the framework entry.
        assert "rename it to `<name>.md.unsent-<timestamp>`" in transformer
        assert "rename it back to `<name>.md`" in transformer

    def test_spent_undo_directories_are_retired_and_named_only_while_they_exist(self) -> None:
        rec = self._ref("recovery-procedures.md")
        abandon = next(line for line in rec.splitlines() if line.startswith("| The port is abandoned after Stage 4c"))
        # A used <undo> left on disk is listed again by the next crash recovery and could be applied twice;
        # it goes only after every restore, since it holds the only copy of git-ignored agent memory.
        delete = "Once a run's restores above are done, delete its `<undo>`, so no later recovery applies it again"
        assert delete in abandon
        assert abandon.index("copy it back over the manifest") < abandon.index(delete)
        # Only a whole-run undo retires <undo>; a single-file copy-back in 4d or 4g still needs it.
        assert "a completed whole-run undo deletes its `<undo>`" in abandon
        assert "restore `CLAUDE.md`'s region as Stage 4d does if its copy still exists" in abandon
        # An audit, checklist or count halt undid its own run, but a continued port leaves the earlier run it built on.
        assert "left nothing of that run to undo; on a continued port (Gate 3 case 1), if another run's `<undo>` remains" in abandon
        assert "undo it as after a crash" in abandon
        moved = next(line for line in rec.splitlines() if line.startswith("| Moving a replaced `knowledge-routing.md`"))
        # The halt came before Post-Port Cleanup, and a re-run is a re-port, which never offers it.
        assert "Then, in the same session, finish the run: Post-Port Cleanup" in moved and "and the final summary" in moved
        assert "a first port Gate 3 didn't continue still asks its question" in moved
        assert "take the kept file's name from `sdlc-port-kept/`" in moved
        # The cleanup gate must agree with the row: the move halt doesn't make a first port "interrupted".
        assert re.search(r"Only a first port\s+Gate 3 didn't continue asks the question below", self._manifest_doc())
        assert "uninterrupted first port" not in self._manifest_doc()
        remap = self._ref("agent-memory-remap.md")
        assert "copy the agent file to `<undo>/files/.claude/agents/<name>.md` first (`mkdir -p` its directory, then `[ -e <copy> ] || cp`)" in remap
        g4 = next(line for line in rec.splitlines() if line.startswith("| A remapped agent-memory file is wrong"))
        # 4g also gives agent files their tools, and abandoning after 4g undoes the whole run, not only agent memory.
        assert "`<undo>/files/.claude/agents/`" in g4 and "abandon row" in g4
        assert "or the port is abandoned after 4g |" not in g4
        # Every audit-style undo restores and then deletes <undo>, so its halt must not offer it as a recovery path.
        said = "say the run was undone and its `<undo>` deleted, without naming it as a recovery path"
        audit = (_ROOT / "references" / "post-operation-audit.md").read_text()
        others = "On a continued port (Gate 3 case 1), also name every other directory under `$(git rev-parse --git-path sdlc-port-undo)/` (or `.sdlc-port-undo/` outside git): an earlier run this one continued, still unrestored, which abandoning the port undoes as well"
        for text, restore, delete in (
            (self._manifest_doc(), "copy every file under this run's `<undo>/files/` back", "Once every restore above is done, delete this run's `<undo>`"),
            (audit, "Copy every file under this run's `<undo>/files/` back", "Then delete this run's `<undo>`"),
        ):
            assert said in text and others in text
            assert text.index(restore) < text.index(delete)
        assert "when the audit passes or a whole-run undo completes" in remap
        assert "as the halt named it" not in audit
        vm = self._manifest_doc()
        assert "then `<undo>` deleted, and the report says the run was undone)" in vm  # checklist failure
        assert "back over the manifest and deleting `<undo>` included)" in vm  # count discrepancy
        assert re.search(r"every halt that leaves it\s+names it", self._port())

    def test_tools_survive_a_migration_and_a_failed_grant_is_reported(self) -> None:
        # Stage 4g grants tools for calls in agent memory; a migration that rewrites the frontmatter must keep them.
        assert "that its memory under `.claude/agent-memory/<name>/` calls" in self._lifecycle()
        rec = self._ref("recovery-procedures.md")
        row = next(line for line in rec.splitlines() if line.startswith("| Edit tool fails on a file"))
        # Nothing later checks an agent's tools line, so a failed grant would pass the audit unseen.
        assert "Name it in the final summary" in row and "the tools to add by hand" in row
        assert "Edits that failed:" in self._manifest_doc()

    def test_the_plugin_matches_zsdlc_3_0_0s_knowledge_layer_and_lookup(self) -> None:
        lifecycle = self._lifecycle()
        seed = lifecycle.split("\n## knowledge-seed\n", 1)[1].split("\n## ", 1)[0]
        # Contract 0024: an adapter that keeps no map removes Phase 1's knowledge and discipline copies too,
        # dropping their installed_files entries without declining them, so it keeps them up to date.
        copies = "9. **Phase 1's knowledge and discipline copies.**"
        assert copies in seed
        assert seed.index("7. **Sentinel note.**") < seed.index(copies)
        step9 = seed.split(copies, 1)[1]
        assert "with content that still matches its recorded hash" in step9
        assert "never record them in `declined_files`" in step9
        # Recoveries run this section by hand on ported or migrated projects, whose files are the project's own.
        assert "Only on `/sdlc-initialize`" in step9 and "skip the removal" in step9
        # Only what Neuroloom holds goes: a README or diagram no seed entry names would be lost.
        assert "names as an entry's `source_path`" in step9
        assert "`installed_files[<path>].sha256`" in step9
        audit = (_ROOT / "references" / "post-operation-audit.md").read_text()
        assert "upstream writes nothing under these directories" not in audit
        assert "`knowledge-seed` step 9" in audit
        assert "`knowledge-seed` step 9" in lifecycle.split("7. **No file-mode knowledge layer**", 1)[1].split("\n8. ", 1)[0]
        # Initialize's Phase 1 copies now reach post-file-write before Phase 4 creates the project's agents.
        for doc in ((_ROOT / "agents" / "neuroloom-transformer.md").read_text(), (_ROOT / "references" / "content-merge-audits.md").read_text()):
            assert "On `operation: initialize`, an unresolved name is a WARN, never a HALT" in doc
        # Content injection waits for CLAUDE.md; the initialize audit catches a section that never arrived.
        init_checks = audit.split("### /sdlc-initialize\n", 1)[1].split("\n### ", 1)[0]
        assert "**Neuroloom Tool Usage section**" in init_checks and "REGRESSION" in init_checks
        assert "A `post-file-write` halt during Phase 1's copies" in lifecycle
        assert "never re-run `/sdlc-initialize` plainly after a Phase 1 halt" in lifecycle
        # Contract 0025: enabled alone also reads true for another project's install; a vendored copy is the fallback.
        assert "entry with `\"enabled\": true`)" not in lifecycle
        assert lifecycle.count("else a copy vendored in the project") >= 3
        # Contract 0026: initialize runs post-file-write on CLAUDE.md once Phase 2 saves it, so step 9 no longer does.
        assert "First, `CLAUDE.md`." not in step9
        assert "z-sdlc runs `post-file-write` on it once Phase 2 saves it" in lifecycle
        # The stale-agent scan only warns in Phase 1, so the initialize audit re-runs it on the final roster.
        assert "**Agent names resolve**" in init_checks
        # A skipped step 9 must show as a REGRESSION, not as a pile of WARNs.
        check6 = audit.split("### Check 6", 1)[1].split("\n---", 1)[0]
        assert "is a **REGRESSION**: `knowledge-seed` step 9 didn't remove it" in check6
        summary = lifecycle.split("**After `/sdlc-initialize`:**", 1)[1].split("**After `/sdlc-migrate`:**", 1)[0]
        assert "Neuroloom Tool Usage" in summary and "Agent names resolve" in summary
        # Initialize finds the adapter before Phase 1 now, so post-file-write runs before CLAUDE.md exists.
        assert "If `CLAUDE.md` doesn't exist yet" in lifecycle
        # A halt in any phase ends a headless run failed (protocol § Phase Failure Semantics).
        assert "a headless run ends with status `failed`" in lifecycle
        for name in ("adapter.json", ".claude-plugin/plugin.json"):
            data = json.loads((_ROOT / name).read_text())
            assert data["supported_zsdlc_version"] == "3.0.0", name
        # z-sdlc reads the zsdlc keys; the pre-rename ones are gone (CD, 2026-11-25).
        adapter = json.loads((_ROOT / "adapter.json").read_text())
        assert not [k for k in adapter if "ccsdlc" in k], adapter
        assert "ccsdlc_adapter" not in lifecycle.split("**Contract change version gate:**", 1)[1].split("\n", 1)[0]
        changelog = (_ROOT / "CHANGELOG.md").read_text().split("\n## [0.6.1]", 1)[0]
        for stale in ("copies nothing else under", "what a lite install carries", "once it is tagged"):
            assert stale not in changelog, stale

    def test_the_plugin_matches_contract_0026(self) -> None:
        # z-sdlc 3.0.0 (cd9be39) decides file by file which knowledge files the adapter took.
        lifecycle = self._lifecycle()
        update = lifecycle.split("\n## knowledge-update\n", 1)[1].split("\n## ", 1)[0]
        take = "11. **Take the copies Neuroloom holds**"
        assert take in update and update.index("10. **Error handling.**") < update.index(take)
        step11 = update.split(take, 1)[1]
        # Only unedited upstream text whose every entry Neuroloom now holds; never the project's own record.
        # Codex pass 21: only a copy of the target release can be taken; a baseline copy may hold a moved entry.
        assert "byte for byte that file at `[target_tag]` (`cmp -s` against `$NEW/<path>`;" in step11
        assert "**The workspace check** (top of this file) confirms the API key still reaches" in update
        assert "lower `file_count` by one, and record nothing in `declined_files`" in step11
        assert "never `provenance_log.md`" in step11
        # Off disk and not held (a README an older port removed): listed for CD, never written.
        assert "off disk" in step11 and "list it for CD" in step11
        assert "isn't the map or `provenance_log.md`" in step11 and "mkdir -p" in step11
        # A map on disk means z-sdlc ran its ordinary path this run: take nothing, remove the map for next time.
        assert "no `ops/sdlc/knowledge/agent-context-map.yaml` on disk when the migration began" in step11
        assert step11.index("take nothing") < step11.index("**Take** a file")
        # Codex pass 20: never delete a copy whose entries this run didn't see in Neuroloom.
        assert "every one of whose entries (the entries above that name it) this run checked and found in Neuroloom" in step11
        # A README or diagram has no entries, so "every entry checked" alone would hold for it.
        assert "- **Take** a file on disk there that one of those entries names" in step11
        assert "a discipline file is never taken" in step11 and "record nothing in `declined_files`" in step11
        assert "(not a discipline file, which stays for z-sdlc to update, and not one with an entry the classifier held back" in step11
        # ADR-11: the API refuses any edit to an sdlc_knowledge memory, so no recovery may rely on memory_update.
        assert "memory_update(id=<entry>, narrative=" not in lifecycle and "importance_score=0.9)" not in lifecycle
        assert "by re-sending that entry alone" in update and "(ADR-11)" in update
        assert "`send` list (step 6 sent it) or its `already_current` list" in step11
        # An uncommitted map holds routing nobody saved: only a clean, tracked map is removed.
        assert "`git status --porcelain -- ops/sdlc/knowledge/agent-context-map.yaml` prints nothing" in step11
        assert "which writes nothing unless `git show` succeeds" in step11
        for clause in ("`cmp -s`", "Never record it in `declined_files`", "drop its `installed_files` entry", "`knowledge_id` and `source_path`",
                       "- **Keep** every other file on disk, with its entry", "this plugin doesn't merge files", "a non-zero exit halts"):
            assert clause in step11, clause
        assert "lists any left on disk in its report for CD to delete" not in lifecycle
        seed = lifecycle.split("\n## knowledge-seed\n", 1)[1].split("\n## ", 1)[0]
        step9 = seed.split("9. **Phase 1's knowledge and discipline copies.**", 1)[1]
        assert "that `declined_files` lists" in step9 and "step 3 recorded as declined" not in step9
        assert "a post-operation knowledge-layer regression" not in step9
        vm = self._manifest_doc()
        cleanup = vm.split("### Post-Port Cleanup", 1)[1].split("### Final Summary", 1)[0]
        assert "Knowledge READMEs, the context map" not in cleanup
        assert "The knowledge READMEs stay too" in cleanup
        # The log goes only when Neuroloom holds every record (Stage 3c), as before.
        assert "Keep `provenance_log.md` unless every Stage 3c entry was stored" in cleanup
        assert "or every later migration warns about them" not in cleanup
        audit = (_ROOT / "references" / "post-operation-audit.md").read_text()
        names = next(line for line in audit.splitlines() if line.startswith("- **Agent names resolve**"))
        # A small roster can't hold every agent z-sdlc's skills dispatch: list them, with a fix that works.
        assert "REGRESSION" not in names and "WARN" in names and "agent_renames" in names
        assert "`CLAUDE.md`'s SDLC region" in names
        check6 = audit.split("### Check 6", 1)[1].split("\n---", 1)[0]
        assert "a `.md` under `knowledge/` other than a README or `provenance_log.md`" in check6
        assert "other files in ops/sdlc/knowledge/ or disciplines/: WARN" not in audit
        assert "takes only a copy whose every entry it checked this run" in check6
        # A map step 11 kept because it held uncommitted routing is not one this run created.
        assert "that `knowledge-update` step 11 listed as left in place was there before the run" in check6
        changelog = (_ROOT / "CHANGELOG.md").read_text().split("\n## [0.6.1]", 1)[0]
        assert "contracts 0023 to 0026" in changelog and "for CD to delete" not in changelog
        assert "delete `adapter.plugin_root` if the manifest has one" not in changelog

    def test_agent_memory_grants_only_tools_that_read(self) -> None:
        # Agents write their own memory: a grant from it must never widen an agent past its profile into writes.
        grant = yaml.safe_load((_ROOT / "transforms.yaml").read_text())["memory_grant_tools"]["tools"]
        writes = ("store", "update", "delete", "link", "unlink", "rate", "seed", "ingest", "session_start", "session_end", "upload")
        assert grant and not [t for t in grant if any(w in t for w in writes)], grant
        # Exactly the MCP server's readOnlyHint tools, less the two that hand out upload URLs.
        expected = {"memory_search", "memory_explore", "memory_by_file", "memory_get_detail", "memory_get_index",
                    "memory_get_related", "memory_get_supersession_chain", "memory_get_timeline", "workspace_insight",
                    "session_get_context", "sdlc_get_version", "code_search", "code_context", "code_callers",
                    "code_callees", "code_navigate"}
        assert set(grant) == {f"mcp__neuroloom__{n}" for n in expected}
        assert "Agents get every Neuroloom tool their text or memory calls" not in (_ROOT / "CHANGELOG.md").read_text()
        for text in (self._lifecycle(), self._ref("agent-memory-remap.md")):
            assert "`transforms.yaml` → `memory_grant_tools`" in text

    def test_no_file_names_a_home_directory(self) -> None:
        # Real-tree checks once hard-coded one developer's home path; the plugin ships these files.
        # The shipped files only: .claude/ (agent memory) and caches are local and git-ignored.
        local = {".git", ".claude", "__pycache__", ".pytest_cache", ".venv", ".ruff_cache"}
        for path in sorted(_ROOT.rglob("*")):
            if local & set(path.relative_to(_ROOT).parts):
                continue
            if path.is_file() and path.suffix in {".py", ".md", ".yaml", ".yml", ".json"}:
                text = path.read_text(errors="ignore")
                # Placeholder home directories in examples are fine; a real one isn't.
                found = re.findall(r"/(?:Users|home)/([A-Za-z][\w.-]+)/", text)
                real = [n for n in found if n.lower() not in {"user", "someone", "runner", "you", "me", "example", "dev", "name"}]
                assert not real, path.relative_to(_ROOT)

    def test_an_unfinished_initialize_halts_a_migration_whatever_its_scheme_marker(self) -> None:
        lifecycle = (_ROOT / "references" / "adapter-lifecycle.md").read_text()
        assert "with an `adapter` block and no `neuroloom_backend`, whatever else is set (the scheme marker included)" in lifecycle
        # project-knowledge items get stable keys, so a phase re-run updates each in place.
        assert 'sdlc:item:<first 12 hex characters of sha1("<kind>|<target file>|<section>|<title>")>' in lifecycle

    def test_every_migration_recovery_restores_the_manifest(self) -> None:
        # One recovery per operation, in adapter-lifecycle.md's table: the old four-path recipes
        # missed .github/ and .gitignore, and a git clean removed files the run never wrote.
        lifecycle = (_ROOT / "references" / "adapter-lifecycle.md").read_text()
        table = lifecycle.split("**Halts and their recoveries.**", 1)[1].split("**The workspace check.**", 1)[0]
        assert "with no one to ask, the answer is no" in table and "Nothing is lost on any path" in table
        for path in _text_files():
            if path.name in (Path(__file__).name, "CHANGELOG.md"):
                continue
            for n, line in enumerate(path.read_text().splitlines(), 1):
                if "git checkout -- .claude/ ops/sdlc/ CLAUDE.md .sdlc-manifest.json" in line:
                    raise AssertionError(f"{path.relative_to(_ROOT)}:{n}: a migration recovery outside the table: {line.strip()}")

    def test_claude_md_sdlc_region_is_transformed_and_scanned(self) -> None:
        lifecycle = (_ROOT / "references" / "adapter-lifecycle.md").read_text()
        applies_to = next(ln for ln in lifecycle.splitlines() if ln.startswith("**Applies to:**"))
        assert "`CLAUDE.md` (its SDLC region only)" in applies_to
        agent = (_ROOT / "agents" / "neuroloom-transformer.md").read_text()
        assert "## CLAUDE.md" in agent and "never change a line outside it" in agent
        scans = [ln for ln in _audit().splitlines() if ln.startswith("grep -r") and ".claude/agents" in ln]
        assert scans and all("ops/sdlc CLAUDE.md" in ln for ln in scans), scans

    def test_post_file_write_skips_the_data_directories(self) -> None:
        lifecycle = (_ROOT / "references" / "adapter-lifecycle.md").read_text()
        skip = next(ln for ln in lifecycle.splitlines() if ln.startswith("**Skip:**"))
        assert "`[sdlc-root]/knowledge/**`" in skip and "`[sdlc-root]/disciplines/**`" in skip

    def test_handlers_ingest_knowledge_markdown_with_the_extractors_ids(self) -> None:
        lifecycle = (_ROOT / "references" / "adapter-lifecycle.md").read_text()
        seed = lifecycle.split("\n## knowledge-seed\n", 1)[1].split("\n## ", 1)[0]
        update = lifecycle.split("\n## knowledge-update\n", 1)[1].split("\n## ", 1)[0]
        # One owner of knowledge ids: the port's extractor, in --upstream mode, and sdlc_seed.
        for section in (seed, update):
            assert "--upstream" in section and "skip_deprecation: true" in section
            assert "document_ingest_batch(" not in section
        project = lifecycle.split("\n## project-knowledge\n", 1)[1].split("\n## ", 1)[0]
        for kind in ("discipline-context", "knowledge-entry", "maturity-tracker"):
            assert f"`{kind}`" in project, kind
        # z-sdlc 3.0.0 graduates a lite install without the adapter: there is no lite content to hand over.
        assert "lite-carried" not in lifecycle and "Phase 0-L" not in lifecycle
        assert project.startswith("**On failure:** halt")


class TestSkillWiringCoversEveryListedSkill:
    """Sleeved's 2026-11-26 migration logged four skills `verified_only` ("not in this dispatch's
    file list ... not rewritten (dispatch scope)") and left their pre-0.7.0 wiring: no `plugin_dir`
    line, and `sdlc-ingest` without its `report` line, which `ingest_to_neuroloom` needs. Check 8
    only checked that the section existed, so the run would have passed and the next
    `/sdlc-ingest` halted."""

    def _post_batch(self) -> str:
        agent = (_ROOT / "agents" / "neuroloom-transformer.md").read_text()
        return " ".join(agent.split("## Post-Batch: Skill Transform Wiring", 1)[1].split("\n## ", 1)[0].split())

    def _check8(self) -> str:
        lifecycle = (_ROOT / "references" / "adapter-lifecycle.md").read_text()
        return " ".join(lifecycle.split("8. **Skill transform wiring intact**", 1)[1].split("\n9. ", 1)[0].split())

    def test_wiring_covers_every_listed_skill_whatever_this_run_dispatched(self) -> None:
        step = self._post_batch()
        assert "For every skill `transforms.yaml` lists, even one this dispatch's file list doesn't name or upstream didn't write this run" in step
        assert "There is no verify-only mode" in step

    def test_check_8_checks_the_sections_shape_not_just_its_heading(self) -> None:
        check = self._check8()
        for line in ("`operation: \"transform\"`", "`plugin_dir:`", "`actions:`", "`report:`", "`path_pairs:`"):
            assert line in check, line
        assert "an older plugin's section" in check and "REGRESSION" in check
        assert "for a skill listed more than once (`sdlc-develop-agent`), its `actions:` line names every entry's actions" in check

    def test_the_archive_template_syncs_everything_sdlc_archive_moves(self) -> None:
        # z-sdlc 3.0.0's sdlc-archive moves deliverables in Step 5 and idea briefs, bug reports and
        # handoffs in Step 7, from the mapping Step 4 approves. Always-replace would otherwise narrow
        # Sleeved's hand-widened line to Step 5 and leave archived idea briefs' documents stale.
        lifecycle = (_ROOT / "references" / "adapter-lifecycle.md").read_text()
        line = next(ln for ln in lifecycle.splitlines() if ln.startswith("- path_pairs: ["))
        for part in ("idea brief", "bug report", "handoff", "Step 5 (Archive Deliverables)",
                     "Step 7 (Archive Idea Briefs & Resolved Artifacts)", "Step 4's approval table"):
            assert part in line, part
        transforms = (_ROOT / "transforms.yaml").read_text()
        archive = transforms.split("- skill: sdlc-archive", 1)[1].split("\n  - skill:", 1)[0]
        assert "Step 7" in archive and "idea brief" in archive

    def test_one_section_per_skill_with_every_entrys_actions(self) -> None:
        # transforms.yaml lists sdlc-develop-agent twice (default and mode: ENRICH); replacing the
        # section once per entry would leave only the ENRICH actions.
        step = self._post_batch()
        assert "Entries that name the same skill share one section" in step
        lifecycle = " ".join((_ROOT / "references" / "adapter-lifecycle.md").read_text().split())
        assert "One section per skill" in lifecycle and "(ENRICH mode: " in lifecycle
        # The documented line is built from transforms.yaml, so a change to either entry shows here.
        import yaml
        entries = [t for t in yaml.safe_load((_ROOT / "transforms.yaml").read_text())["transforms"] if t["skill"] == "sdlc-develop-agent"]
        default = next(t["actions"] for t in entries if "mode" not in t)
        enrich = next(t["actions"] for t in entries if t.get("mode") == "ENRICH")
        assert f"`actions: {', '.join(default)} (ENRICH mode: {', '.join(enrich)})`" in lifecycle

    def test_the_port_replaces_an_older_section_too(self) -> None:
        port = " ".join((_ROOT / "skills" / "sdlc-port" / "SKILL.md").read_text().split())
        assert "or replace an older plugin's with the current shape" in port
