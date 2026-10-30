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

    def test_five_rows_and_no_whole_tree_or_whole_file_exemption(self) -> None:
        rows = self._rows()
        assert len(rows) == 5, "provenance_log.md is no longer exempt: provenance lives in memories"
        assert not rows[0].startswith("| 1 | Everything under"), "sdlc-migrate must be exempt line by line"
        assert "LINE BY LINE" in rows[0]
        assert "Only the span is exempt" in rows[1]
        assert not any("provenance_log" in r for r in rows), "no exemption row may name the provenance log"

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
        assert ("memory_update(memory_id=<id>, tags=[<the record's full tag list, status tag swapped>], "
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
        assert "grep -rn --include='*.md' 'provenance_log' .claude/skills .claude/agents .claude/sdlc" in audit
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
        assert "project's ingestion/research lineage log; relocate but never" not in port
        assert "project-specific append-only record; relocate with" not in port
        assert "It is NOT relocated" in port
        assert 'tags=["sdlc:provenance", "sdlc:source-type:<type>", "sdlc:prov:<prov-id>", "sdlc:prov-status:<status>"]' in port

    def test_the_readme_documents_the_three_tags(self) -> None:
        readme = (_ROOT / "README.md").read_text()
        for tag in ("`sdlc:provenance`", "`sdlc:source-type:{type}`", "`sdlc:prov:{id}`", "`sdlc:prov-status:{status}`"):
            assert tag in readme, tag


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
