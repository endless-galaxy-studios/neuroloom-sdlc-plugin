#!/usr/bin/env python3
"""Extracts SDLC knowledge entries from a z-sdlc ``knowledge/`` and
``disciplines/`` tree and writes them as seed JSON for the Neuroloom API.

Sources:
    knowledge/**/*.yaml   one entry per list item or top-level section, nothing dropped
    knowledge/**/*.md     one entry per document (README.md and provenance_log.md skipped)
    disciplines/*.md      split as z-sdlc's sdlc-migrate §2.3 defines: a framework
                          entry, one entry per Parking Lot bullet, and, in port
                          mode only, the project's Active Questions, Project
                          Context and maturity tracker

Output:
    Seed files shaped ``{"entries": [...], "version": V}``. Every file stays within
    --max-per-file (alias --max-entries) entries and --max-bytes serialized bytes (the seed API takes at
    most 500 entries and 1 MiB); entries of one source file stay together unless
    that file alone is over a limit.

    With --output PATH the files are PATH itself when everything fits, else
    <stem>_001<suffix>, <stem>_002<suffix>, ... Each written path is printed to
    stdout, one per line, seed files first. In delta mode the last line is
    <stem>.delta.json. With no --output the JSON goes to stdout instead. When
    there are no entries no seed file is written, stdout stays empty, and the run
    says so on stderr and exits 0.

Baseline flags (--baseline-knowledge-dir and --baseline-disciplines-dir): the same
upstream tree at the project's source_version. Both must exist and yield entries,
else exit 2. In delta mode the target trees (--knowledge-dir, --disciplines-dir) are
held to the same rule, so a mistyped tag cannot make every baseline entry "removed".
What the baseline flags do depends on the mode:

    --upstream (delta mode, needs --output): the seed files hold only entries that are
        new or changed against the baseline. <stem>.delta.json holds
        {"new": [ids], "new_content": {id: text}, "changed": [{"id",
         "baseline_content", "target_content", "baseline_title", "target_title"}],
         "removed": [ids absent from the
         target], "unchanged_count": N, "probe_ids": [up to 10 unchanged ids from
         different source files, only ids the pre-0.7.0 ``knowledge-seed`` handler,
         which keyed entries {stem}:{key}, never produced; empty when no unchanged id
         qualifies],
         "framework_ids": {stem: the id the extractor gave that discipline's framework
         entry} (it differs from discipline:<stem>:framework when the stem is sanitized
         or too long), "noop_entry": one whole unchanged entry, or null,
         "probe_entries": the full entries for noop_entry and every probe id}.
        Probes tell a workspace seeded by that handler from one seeded by the extractor;
        they cannot tell a 0.6.x port from a 0.7.0 one (same {dir}:{stem}:{key} ids),
        which only the manifest marker does. noop_entry lets a caller advance the
        workspace's version marker when nothing else changed: classify_knowledge_update.py
        picks which of probe_entries the server will answer "unchanged" for. probe_entries
        holds up to 50 candidates from any unchanged entry; a release whose unchanged ids
        are all root-level still produces a delta (probe_ids is then empty).
    port mode: every entry is still written and no delta file is produced; the baseline
        only serves --tag-new.

A target file that fails to parse or read (YAML error, unparsed items, an unreadable or
undecodable Markdown document or discipline, a dangling symlink) exits 2 in every --upstream
mode, with or without the baseline flags, and is named; port mode only warns; a malformed baseline file stays a warning. The discipline status line, the
Parking Lot structure entry and the other fixed-id project data never appear in a delta.
classify_knowledge_update.py reads the delta file; --only-ids rebuilds seed files
from the ids it decides to send.

Selecting and tagging:
    --tag TAG        add TAG to every entry (repeatable; the tags the server adds itself
                     are refused: sdlc:knowledge-id:*, sdlc:seed-version:*, sdlc:seed,
                     sdlc:sentinel, sdlc:deprecated). A run given --tag or --tag-new that
                     produces no entries exits 1.
    --tag-new TAG    port mode with baseline flags: add TAG to every entry whose id the
                     baseline lacks (the project's own knowledge), except the fixed-id
                     project-data entries.
    --exclude-kinds K  port mode only: leave the named discipline kinds (framework, status,
                     parking-lot-structure, active-questions, project-context,
                     maturity-tracker) out of every seed file; bullets and knowledge are
                     kept. Unknown kinds, or use with --upstream, exit 2.
    --only-ids FILE  write only the listed ids (one per line); an empty list writes
                     nothing and exits 0; an id the run does not produce exits 2.
    --no-manifest    apply no manifest even if .sdlc-manifest.json is in the cwd.

The discipline: id namespace belongs to discipline files. A knowledge entry (a YAML item
setting its own knowledge_id or rule_id, or a file path that spells such an id) whose final id
starts with discipline: exits 1 in every mode, naming the file and id; --allow-duplicates does
not override it. The baseline is held to the same rule. Likewise an entry whose own tags include one the
server adds itself (sdlc:knowledge-id:*, sdlc:seed-version:*, sdlc:seed, sdlc:sentinel,
sdlc:deprecated) exits 1, naming file, id and tag; --tag and --tag-new refuse the same tags
at argument parsing (exit 2). An entries, rules or gotchas item that the extractor turns into
an entry, whose tags key holds a present, non-null value that is not a list of strings (a
scalar, a mapping, or a list holding a non-string such as an unquoted on), exits 1 the same
way, naming file and item; an absent key, a bare tags: and an empty list keep the default
tags. Those are the only places a source tags value is applied as an entry's tags; any other
tags key (nested in a section, in a list rendered as content, in an item the parser skips,
in a document describing a schema) is rendered as text and never refused.

Exit status:
    0 success; 2 bad arguments or a failed baseline/target check; 1 when an entry alone
    exceeds --max-bytes (it is named), when an id needed a
    ``:dupN`` or ``:document`` suffix to stay unique (every collision is reported on
    stderr; nothing is written) unless --allow-duplicates is given, or when --tag
    found nothing to tag.

Usage:
    python extract_sdlc_knowledge.py --output seed.json
    python extract_sdlc_knowledge.py --dry-run
    python extract_sdlc_knowledge.py --upstream --knowledge-dir Z/knowledge \
        --disciplines-dir Z/disciplines --output seed.json
    python extract_sdlc_knowledge.py --upstream --knowledge-dir NEW/knowledge \
        --disciplines-dir NEW/disciplines --baseline-knowledge-dir OLD/knowledge \
        --baseline-disciplines-dir OLD/disciplines --output seed.json
    python extract_sdlc_knowledge.py --tag sdlc:project-specific --output seed.json
    python extract_sdlc_knowledge.py --baseline-knowledge-dir OLD/knowledge \
        --baseline-disciplines-dir OLD/disciplines --tag-new sdlc:project-specific \
        --output seed.json
    python extract_sdlc_knowledge.py --only-ids send_ids.txt --output seed.json

# requires: pyyaml
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    format="%(levelname)s: %(message)s",
    level=logging.WARNING,
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Top-level YAML keys that carry document metadata, not content entries.
_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "id",
        "name",
        "description",
        "pattern",
        "category",
        "spec_relevant",
        "project_applicability",
        "last_updated",
    }
)

# Patterns whose content is a list of items under a key of the same name.
_LIST_PATTERNS: frozenset[str] = frozenset({"entries", "gotchas", "rules"})

# Markdown files under knowledge/ that are indexes or logs, not knowledge.
_SKIPPED_DOC_NAMES: frozenset[str] = frozenset({"readme.md", "provenance_log.md"})

_MANIFEST_NAME = ".sdlc-manifest.json"

# What the seed API accepts as a knowledge_id (document_ingestion_service.py):
# one bad id rejects the whole request.
_ID_BODY = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._:-]{0,99}")
_ID_MAX_LEN = 100
_DEFAULT_MAX_PER_FILE = 500  # the seed API refuses more than 500 entries per request
# The upload endpoint takes at most 1 MiB (routers/sdlc.py); stay clear of it.
_DEFAULT_MAX_BYTES = 900_000
# Kinds --exclude-kinds may name: the fixed-id discipline entries plus the framework.
_EXCLUDABLE_KINDS = frozenset({"framework", "status", "parking-lot-structure", "active-questions",
                               "project-context", "maturity-tracker"})
# Fixed-id discipline entries of the project's own data. --tag-new must not mark them
# project-specific: sdlc-migrate's impact analysis finds the project's knowledge by that tag,
# and these are discipline data, not knowledge the project added.
_FIXED_ID_PROJECT_DATA = (":active-questions", ":project-context", ":maturity-tracker",
                          ":parking-lot-structure", ":status")
# The same kinds by name, as recorded when a discipline entry is built.
_FIXED_KINDS = frozenset(k.lstrip(":") for k in _FIXED_ID_PROJECT_DATA)
# Probe entries the delta offers as no-op candidates (noop_entry first).
_MAX_PROBE_ENTRIES = 50
# A discipline file's status line, either ``**Status**:`` or ``**Status:**``.
_STATUS_LINE = re.compile(r"\*\*Status(?:\*\*\s*:|:\*\*)")


def _is_fixed_project_data(entry: dict[str, Any], kinds: dict[int, str]) -> bool:
    """True for a discipline's fixed-id project-data entry (status, structure, ...).

    Keyed on where the entry came from and what kind it is, recorded when it was built,
    not on how its final id is spelled: a long stem gets a hashed id that no longer ends
    in ``:status``. (A knowledge entry spelling a ``discipline:`` id is refused outright,
    see ``_reserved_namespace_claims``, so id shape never decides this.) ``kinds`` maps
    ``id()`` of each discipline entry object to its kind (``framework``, ``status``,
    ``parking-lot``, ...).
    """
    return kinds.get(id(entry)) in _FIXED_KINDS


# Tags the seed API gives a meaning of its own; --tag may not set them.
# Tags the seed API adds to rows itself: it finds an existing row by its first
# ``sdlc:knowledge-id:`` tag and versions rows with ``sdlc:seed-version:``. A source item
# or a --tag/--tag-new value carrying one could make the server mistake one entry's row
# for another's.
_SERVER_TAG_PREFIXES = ("sdlc:knowledge-id:", "sdlc:seed-version:")
_SERVER_TAGS = frozenset({"sdlc:seed", "sdlc:sentinel", "sdlc:deprecated"})


def _is_server_owned_tag(tag: str) -> bool:
    return tag in _SERVER_TAGS or tag.startswith(_SERVER_TAG_PREFIXES)


# ---------------------------------------------------------------------------
# YAML extraction helpers
# ---------------------------------------------------------------------------


def _infer_pattern(data: dict[str, Any]) -> str:
    """Infer the YAML knowledge pattern from top-level keys.

    Only matches when the key's value is a list — a top-level ``rules:``
    key that maps to a dict (e.g. a content section) is not a rules pattern.

    Returns one of: ``"entries"``, ``"gotchas"``, ``"rules"``, or
    ``"methodology"`` (the default for dicts without a distinguishing key).
    """
    if isinstance(data.get("gotchas"), list):
        return "gotchas"
    if isinstance(data.get("rules"), list):
        return "rules"
    if isinstance(data.get("entries"), list):
        return "entries"
    return "methodology"


def _importance_from_severity(severity: str | None) -> float:
    """Map a severity string to an importance score."""
    if severity is None:
        return 0.55
    match severity.lower():
        case "high":
            return 0.75
        case "medium":
            return 0.65
        case _:
            return 0.55


def _importance_from_spec_relevant(spec_relevant: Any) -> float:
    """Return 0.75 when spec_relevant is truthy, else the default 0.55."""
    return 0.75 if spec_relevant else 0.55


def _render_value(key: str, value: Any) -> str:
    """Render a YAML value as a human-readable content string."""
    if isinstance(value, (dict, list)):
        return f"### {key}\n" + _dump_yaml(value)
    return f"### {key}\n{value}"


def _tags_are_valid(raw: Any) -> bool:
    return isinstance(raw, list) and all(isinstance(t, str) for t in raw)


def _item_label(list_name: str, index: int, item: dict[str, Any]) -> str:
    """Name an item by its place in the file (``rules[2]``), with its own name when it has one."""
    hint = next(
        (str(item[k]) for k in ("knowledge_id", "rule_id", "id", "topic", "title", "name")
         if isinstance(item.get(k), str) and item[k]),
        None,
    )
    where = f"{list_name}[{index}]"
    return f"{where} ({hint})" if hint else where


def _item_tags(
    item: dict[str, Any],
    default: list[str],
    label: str,
    bad_tags: list[tuple[str, Any]] | None,
) -> list[str]:
    """The tags the extractor applies to the entry built from ``item``.

    This is the one place a source item's own ``tags`` is read as an entry's tags, so the
    one place a malformed value does harm: a scalar would become one-character tags, a
    falsy value would silently fall back to the defaults, and a server-owned tag could make
    one row stand in for another. A value that is present, non-null and not a list of
    strings (``off``, ``0``, ``""``, ``{}``, ``[on]``, which YAML reads as ``[True]``) is
    recorded in ``bad_tags`` for the run to refuse; it is never copied through. Absent,
    ``tags:`` with nothing after it, and an empty list keep ``default``.

    Any other ``tags`` key in a file (nested under a section, in a list that is rendered as
    content, in an item the parser skips, in a document describing a schema) is just text.
    """
    raw = item.get("tags")
    if raw is None:
        return default
    if _tags_are_valid(raw):
        return raw or default  # type: ignore[no-any-return]
    if bad_tags is not None:
        bad_tags.append((label, raw))
    return default


def _record_unparsed(unparsed: list[Any] | None, item: Any) -> None:
    """Keep a list item the parser skipped, so the file still loses nothing."""
    if unparsed is not None:
        unparsed.append(item)


def _parse_entries_pattern(
    data: dict[str, Any],
    filename: str,
    source_path: str,
    unparsed: list[Any] | None = None,
    field_ids: set[int] | None = None,
    bad_tags: list[tuple[str, Any]] | None = None,
    list_name: str = "entries",
) -> list[dict[str, Any]]:
    """One entry per item in the ``entries`` list.

    Each item is expected to have ``topic`` and ``guidance`` fields.  Falls
    back to ``title``/``content`` if present.  Skips malformed items, appending
    each one to ``unparsed`` when the caller passes a list.
    """
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, list):
        return []

    spec_relevant = data.get("spec_relevant")
    base_importance = _importance_from_spec_relevant(spec_relevant)

    results: list[dict[str, Any]] = []
    for i, item in enumerate(raw_entries):
        if not isinstance(item, dict):
            logger.warning("Skipping non-dict entry #%d in %s", i, filename)
            _record_unparsed(unparsed, item)
            continue

        # Accept topic/guidance (the standard knowledge-store pattern) OR
        # title/content (the schema-level field names).
        title: str | None = item.get("topic") or item.get("title")
        content_raw: Any = item.get("guidance") or item.get("content")

        if not title or content_raw is None:
            logger.warning(
                "Skipping entry #%d in %s: missing topic/title or guidance/content",
                i,
                filename,
            )
            _record_unparsed(unparsed, item)
            continue

        content = (
            _dump_yaml(content_raw)
            if isinstance(content_raw, (dict, list))
            else str(content_raw)
        )

        # Append any extra fields (rationale, examples, etc.) to content.
        # Only the two fields actually used are excluded, so a second title or
        # content field on the same item is kept as an extra.
        used = {
            "topic" if item.get("topic") else "title",
            "guidance" if item.get("guidance") else "content",
        }
        extra_keys = [k for k in item if k not in used]
        for key in extra_keys:
            val = item[key]
            if isinstance(val, (dict, list)):
                content += "\n\n**" + key.title() + ":**\n" + _dump_yaml(val)
            else:
                content += f"\n\n**{key.title()}:** {val}"

        knowledge_id = (
            item.get("knowledge_id")
            or f"{filename}:{title.lower().replace(' ', '_')}"
        )
        tags: list[str] = _item_tags(
            item, ["sdlc:knowledge", "sdlc:pattern:entries"], _item_label(list_name, i, item), bad_tags
        )

        built = {
            "title": title,
            "content": content,
            "knowledge_id": knowledge_id,
            "tags": tags,
            "importance": item.get("importance", base_importance),
            "confidence": item.get("confidence", 0.9),
            "concepts": item.get("concepts") or [],
            "source_path": source_path,
        }
        results.append(built)
        # Recorded by entry identity: did the file write this id, or did the path build it?
        if item.get("knowledge_id") and field_ids is not None:
            field_ids.add(id(built))

    return results


def _parse_gotchas_pattern(
    data: dict[str, Any],
    filename: str,
    source_path: str,
    unparsed: list[Any] | None = None,
    field_ids: set[int] | None = None,
    bad_tags: list[tuple[str, Any]] | None = None,
    list_name: str = "gotchas",
) -> list[dict[str, Any]]:
    """One entry per item in the ``gotchas`` list."""
    raw_gotchas = data.get("gotchas")
    if not isinstance(raw_gotchas, list):
        return []

    results: list[dict[str, Any]] = []
    for i, item in enumerate(raw_gotchas):
        if not isinstance(item, dict):
            logger.warning("Skipping non-dict gotcha #%d in %s", i, filename)
            _record_unparsed(unparsed, item)
            continue

        if "id" not in item:
            logger.warning(
                "Skipping gotcha #%d in %s: missing 'id' field",
                i,
                filename,
            )
            _record_unparsed(unparsed, item)
            continue

        gotcha_id = str(item["id"])
        severity = str(item.get("severity", ""))
        title = str(item.get("title", gotcha_id))

        # Support two gotcha schemas:
        # Schema A (Neuroloom): severity, symptom, cause, resolution
        # Schema B (z-sdlc): pattern, example, risk, correct_approach
        content_lines: list[str] = []
        if "symptom" in item:
            if severity:
                content_lines.append(f"Severity: {severity}")
            content_lines.append(f"Symptom: {item['symptom']}")
            content_lines.append(f"Cause: {item.get('cause', '')}")
            content_lines.append(f"Resolution: {item.get('resolution', '')}")
        elif "pattern" in item:
            content_lines.append(f"Pattern: {item['pattern']}")
            if "example" in item:
                content_lines.append(f"Example: {item['example']}")
            if "risk" in item:
                content_lines.append(f"Risk: {item['risk']}")
            if "correct_approach" in item:
                content_lines.append(f"Correct approach: {item['correct_approach']}")
        else:
            # Fallback: serialize all non-id fields
            for k, v in item.items():
                if k != "id":
                    content_lines.append(f"{k}: {v}")

        if "prevention" in item:
            content_lines.append(f"Prevention: {item['prevention']}")

        if "symptom" in item:
            rendered_keys = {"severity", "symptom", "cause", "resolution"}
        elif "pattern" in item:
            rendered_keys = {"pattern", "example", "risk", "correct_approach"}
        else:
            rendered_keys = {k for k in item if k != "id"}
        content = "\n".join(content_lines) + _render_unrendered(
            item,
            skip=frozenset({"id", "tags", "concepts", "title"}),
            rendered=frozenset(rendered_keys | {"prevention"}),
        )

        tags = _item_tags(
            item,
            ["sdlc:knowledge", "sdlc:pattern:gotchas", "sdlc:type:gotcha",
             f"sdlc:severity:{severity.lower()}"],
            _item_label(list_name, i, item),
            bad_tags,
        )

        built = {
            "title": title,
            "content": content,
            "knowledge_id": gotcha_id,
            "tags": tags,
            "importance": _importance_from_severity(severity),
            "confidence": 0.9,
            "concepts": item.get("concepts") or [],
            "source_path": source_path,
        }
        results.append(built)
        if field_ids is not None:
            field_ids.add(id(built))  # a gotcha's id is always written in the file

    return results


def _parse_rules_pattern(
    data: dict[str, Any],
    filename: str,
    source_path: str,
    unparsed: list[Any] | None = None,
    field_ids: set[int] | None = None,
    bad_tags: list[tuple[str, Any]] | None = None,
    list_name: str = "rules",
) -> list[dict[str, Any]]:
    """One entry per item in the ``rules`` list."""
    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list):
        return []

    results: list[dict[str, Any]] = []
    for i, item in enumerate(raw_rules):
        if not isinstance(item, dict):
            logger.warning("Skipping non-dict rule #%d in %s", i, filename)
            _record_unparsed(unparsed, item)
            continue

        # Resolve ID — accept rule_id or id.
        rule_id = str(item.get("rule_id") or item.get("id") or "")
        if not rule_id:
            logger.warning("Skipping rule #%d in %s: no rule_id or id", i, filename)
            _record_unparsed(unparsed, item)
            continue

        # Resolve title — accept title, name, or derive from id.
        rule_title = str(
            item.get("title") or item.get("name") or rule_id.replace("-", " ").title()
        )

        # Resolve content — accept description or rule (simple format).
        description = item.get("description") or item.get("rule") or ""
        severity = item.get("severity")

        content_parts = [f"### {rule_title}", str(description)]
        for extra in ("rationale", "examples", "exceptions", "checklist"):
            if extra in item:
                val = item[extra]
                if isinstance(val, (dict, list)):
                    content_parts.append(f"\n**{extra.title()}:**\n" + _dump_yaml(val))
                else:
                    content_parts.append(f"\n**{extra.title()}:** {val}")

        id_key = "rule_id" if item.get("rule_id") else "id"
        title_key = "title" if item.get("title") else "name"
        text_key = "description" if item.get("description") else "rule"
        content = "\n".join(content_parts) + _render_unrendered(
            item,
            skip=frozenset(
                {id_key, "tags", "concepts", "rationale", "examples", "exceptions", "checklist"}
            ),
            rendered=frozenset({title_key, text_key}),
        )

        tags = _item_tags(
            item, ["sdlc:knowledge", "sdlc:pattern:rules", "sdlc:type:rule"],
            _item_label(list_name, i, item), bad_tags,
        )
        if severity:
            tags = list(tags) + [f"sdlc:severity:{severity.lower()}"]

        built = {
            "title": rule_title,
            "content": content,
            "knowledge_id": rule_id,
            "tags": tags,
            "importance": _importance_from_severity(severity),
            "confidence": 0.9,
            "concepts": item.get("concepts") or [],
            "source_path": source_path,
        }
        results.append(built)
        if field_ids is not None:
            field_ids.add(id(built))  # a rule's id is always written in the file

    return results


def _parse_methodology_pattern(
    data: dict[str, Any],
    filename: str,
    source_path: str,
    exclude: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """One entry per non-metadata top-level key, except those in ``exclude``."""
    spec_relevant = data.get("spec_relevant")
    base_importance = _importance_from_spec_relevant(spec_relevant)

    results: list[dict[str, Any]] = []
    for key, value in data.items():
        if key in _METADATA_KEYS or key in exclude:
            continue

        content = _render_value(key, value)
        knowledge_id = f"{filename}:{key}"
        title = key.replace("_", " ").title()

        results.append(
            {
                "title": title,
                "content": content,
                "knowledge_id": knowledge_id,
                "tags": ["sdlc:knowledge", "sdlc:pattern:methodology"],
                "importance": base_importance,
                "confidence": 0.9,
                "concepts": [],
                "source_path": source_path,
            }
        )

    return results


def _extract_yaml_entries(
    path: Path,
    knowledge_dir: Path,
    sanitized: list[dict[str, Any]] | None = None,
    unparsed_files: list[Path] | None = None,
    malformed_tags: list[tuple[str, str, Any]] | None = None,
    field_ids: set[int] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Parse a single YAML knowledge file into a list of API-ready entry dicts.

    Args:
        path: Absolute path to the YAML file.
        knowledge_dir: Root knowledge directory (used to derive relative paths
            and knowledge_id prefixes).
        sanitized: When given, receives each entry whose id had to be changed to
            pass the API's id pattern.
        unparsed_files: When given, receives ``path`` if some list items could not
            be parsed (they are kept in a ``:unparsed`` entry).
        malformed_tags: When given, receives ``(source_path, item label, value)`` for
            each item whose ``tags`` is not a list of strings.
        field_ids: When given, receives ``id(entry)`` for each entry whose id the file
            itself wrote (``knowledge_id``, a rule id, a gotcha id), as opposed to one
            built from the path or a section key.

    Returns:
        A tuple of ``(entries, skipped_count)`` where ``skipped_count`` is 1
        if the file could not be parsed and 0 otherwise.
    """
    try:
        raw = path.read_text(encoding="utf-8")
        data: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        logger.warning("Skipping %s — YAML parse error: %s", path, exc)
        return [], 1
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("Skipping %s — cannot read file: %s", path, exc)
        return [], 1

    if data is None:
        logger.warning("Skipping %s — empty file", path)
        return [], 0

    if not isinstance(data, dict):
        logger.warning(
            "Skipping %s — expected a top-level mapping, got %s",
            path,
            type(data).__name__,
        )
        return [], 1

    # Derive stable identifiers relative to knowledge_dir root.
    rel = path.relative_to(knowledge_dir)
    source_path = str(rel)
    # knowledge_id prefix: replace path separators with colons, strip extension.
    # e.g. "architecture/fastapi-patterns.yaml" -> "architecture:fastapi-patterns"
    filename = str(rel.with_suffix("")).replace("/", ":").replace("\\", ":")

    pattern: str | None = data.get("pattern")
    if pattern is None:
        pattern = _infer_pattern(data)

    # A file may declare a list pattern while its list sits under another
    # recognised list key (``pattern: rules`` holding ``entries`` whose items are
    # rule items). The declared pattern says what the items look like, so its
    # parser reads that list. With no recognised list the file is plain
    # methodology content.
    list_key: str | None = None
    if isinstance(pattern, str) and pattern in _LIST_PATTERNS:
        candidates = [pattern, "gotchas", "rules", "entries"]
        list_key = next(
            (k for k in candidates if isinstance(data.get(k), list)), None
        )

    if list_key is None or not isinstance(pattern, str):
        entries = _parse_methodology_pattern(data, filename, source_path)
    else:
        unparsed: list[Any] = []
        bad_tags: list[tuple[str, Any]] = []
        # The parsers read the list under their own pattern's name.
        view = {**data, pattern: data[list_key]}
        match pattern:
            case "entries":
                entries = _parse_entries_pattern(
                    view, filename, source_path, unparsed, field_ids, bad_tags, list_key
                )
            case "gotchas":
                entries = _parse_gotchas_pattern(
                    view, filename, source_path, unparsed, field_ids, bad_tags, list_key
                )
            case _:
                entries = _parse_rules_pattern(
                    view, filename, source_path, unparsed, field_ids, bad_tags, list_key
                )
        if malformed_tags is not None:
            malformed_tags.extend((source_path, label, value) for label, value in bad_tags)
        if unparsed and unparsed_files is not None:
            unparsed_files.append(path)
        if unparsed:
            entries.append(
                _unparsed_entry(list_key, unparsed, filename, source_path, pattern)
            )
        # Every other top-level section is content too.
        entries.extend(
            _parse_methodology_pattern(
                data, filename, source_path, exclude=frozenset({list_key})
            )
        )

    if not entries and data:
        entries = [_whole_file_entry(data, filename, source_path)]

    _add_domain_tag(entries, rel)

    # Ids built from item titles can hold characters the API rejects.
    for entry in entries:
        safe_id = _sanitize_id(entry["knowledge_id"])
        if safe_id != entry["knowledge_id"]:
            entry["knowledge_id"] = safe_id
            if sanitized is not None:
                sanitized.append(entry)

    return entries, 0


def _unparsed_entry(
    list_key: str,
    items: list[Any],
    filename: str,
    source_path: str,
    pattern: str,
) -> dict[str, Any]:
    """One entry holding the YAML of list items the list parser could not read."""
    return {
        "title": f"{list_key.replace('_', ' ').title()} (unparsed items)",
        "content": f"### {list_key} (items without a usable id or title)\n"
        + _dump_yaml(items),
        "knowledge_id": f"{filename}:{list_key}:unparsed",
        "tags": ["sdlc:knowledge", f"sdlc:pattern:{pattern}", "sdlc:type:unparsed"],
        "importance": 0.55,
        "confidence": 0.9,
        "concepts": [],
        "source_path": source_path,
    }


def _whole_file_entry(
    data: dict[str, Any], filename: str, source_path: str
) -> dict[str, Any]:
    """One entry holding the YAML dump of a mapping that had nothing else to seed."""
    return {
        "title": filename.rsplit(":", 1)[-1].replace("-", " ").replace("_", " ").title(),
        "content": _dump_yaml(data),
        "knowledge_id": filename,
        "tags": ["sdlc:knowledge", "sdlc:pattern:methodology"],
        "importance": _importance_from_spec_relevant(data.get("spec_relevant")),
        "confidence": 0.9,
        "concepts": [],
        "source_path": source_path,
    }


class _ReadableDumper(yaml.SafeDumper):
    """Dumper that keeps strings readable and searchable in entry content."""


def _needs_quotes(text: str) -> bool:
    """True when PyYAML would write ``text`` quoted (``a: b``, ``it's``, ``# x``)."""
    plain = yaml.dump(text, Dumper=yaml.SafeDumper, allow_unicode=True, width=1_000_000)
    return plain.startswith(("'", '"'))


def _represent_str(dumper: yaml.SafeDumper, text: str) -> yaml.ScalarNode:
    # Text that is multi-line or would need quotes goes out as a literal block, so
    # it stays verbatim instead of gaining ``\n`` escapes or doubled quotes.
    style = "|" if "\n" in text or _needs_quotes(text) else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", text, style=style)


_ReadableDumper.add_representer(str, _represent_str)


def _dump_yaml(value: Any) -> str:
    """Dump YAML for entry content: unicode kept, no line folding, source order."""
    return yaml.dump(
        value,
        Dumper=_ReadableDumper,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=1_000_000,
    )


def _render_unrendered(
    item: dict[str, Any],
    skip: frozenset[str],
    rendered: frozenset[str] = frozenset(),
) -> str:
    """``**Field:**`` blocks for the item fields the entry content doesn't carry yet.

    ``skip`` names fields that never need rendering (they live in the entry's own
    id, tags or concepts, or were already dumped as YAML). ``rendered`` names
    fields printed inline: those count as carried only when they are scalars,
    since an inline f-string turns a list or mapping into a Python repr.
    """
    parts: list[str] = []
    for key, val in item.items():
        if key in skip:
            continue
        is_scalar = not isinstance(val, (dict, list))
        if key in rendered and is_scalar:
            continue
        if is_scalar:
            parts.append(f"\n\n**{str(key).title()}:** {val}")
        else:
            parts.append(f"\n\n**{str(key).title()}:**\n" + _dump_yaml(val))
    return "".join(parts)


def _add_domain_tag(entries: list[dict[str, Any]], rel: Path) -> None:
    """Tag each entry ``sdlc:domain:<subdir>`` from the knowledge file's subdirectory.

    ``knowledge/<domain>/x.yaml`` is the domain the file belongs to. Domain-scoped
    lookups (``tags=["sdlc:knowledge", "sdlc:domain:<d>"], tags_match="all"``) match on
    this tag, so a ported entry without it is invisible to them. A file directly under
    ``knowledge/`` has no domain, and an entry that already carries a ``sdlc:domain:``
    tag keeps it (YAML authors may name a domain that differs from the directory).
    """
    if len(rel.parts) < 2:
        return
    domain_tag = f"sdlc:domain:{rel.parts[0]}"
    for entry in entries:
        tags = list(entry["tags"])
        if not any(t.startswith("sdlc:domain:") for t in tags):
            tags.append(domain_tag)
        entry["tags"] = tags


def _markdown_title(text: str, fallback_stem: str) -> str:
    """First ``# `` heading outside a code fence, else a title from the file name."""
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        elif not in_fence and line.startswith("# ") and line[2:].strip():
            return line[2:].strip()
    return fallback_stem.replace("-", " ").replace("_", " ").title()


def _extract_markdown_entry(
    path: Path, knowledge_dir: Path, unreadable: list[Path] | None = None
) -> dict[str, Any] | None:
    """Turn a knowledge Markdown document into one whole-file entry.

    Returns ``None`` when the file cannot be read or is empty; ``unreadable``, when
    given, receives ``path`` for the first case (I/O or decode error).
    """
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("Skipping %s — cannot read file: %s", path, exc)
        if unreadable is not None:
            unreadable.append(path)
        return None

    if not content.strip():
        logger.warning("Skipping %s — empty file", path)
        return None

    rel = path.relative_to(knowledge_dir)
    entry_tags = ["sdlc:knowledge", "sdlc:pattern:document"]
    entry: dict[str, Any] = {
        "title": _markdown_title(content, path.stem),
        "content": content,
        "knowledge_id": rel.with_suffix("").as_posix().replace("/", ":"),
        "tags": entry_tags,
        "importance": 0.55,
        "confidence": 0.9,
        "concepts": [],
        "source_path": rel.as_posix(),
    }
    _add_domain_tag([entry], rel)
    return entry


_TRACKER_START = "<!-- PROJECT-TRACKER-START"
_TRACKER_END = "<!-- PROJECT-TRACKER-END"
_H2 = re.compile(r"##(?!#)\s+(.*\S)\s*$")
_H3 = re.compile(r"###(?!#)\s+(.*\S)\s*$")
_TRACKER_HEADING = re.compile(r"#{2,6}\s+Process Maturity Tracker\b", re.IGNORECASE)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def _fenced_lines(lines: list[str]) -> list[bool]:
    """Per line: inside a code fence (the fence lines included)."""
    flags: list[bool] = []
    in_fence = False
    for line in lines:
        is_fence = line.lstrip().startswith(("```", "~~~"))
        flags.append(in_fence or is_fence)
        if is_fence:
            in_fence = not in_fence
    return flags


def _tracker_range(lines: list[str], fenced: list[bool]) -> set[int]:
    """Line indexes of the project-assessed maturity tracker (sdlc-migrate §2.3).

    The block from the START to the END marker, inclusive. With no markers, the
    body of a ``Process Maturity Tracker`` heading up to the next heading.
    """
    start = next(
        (i for i, ln in enumerate(lines) if _TRACKER_START in ln and not fenced[i]), None
    )
    if start is not None:
        end = next(
            (j for j in range(start, len(lines)) if _TRACKER_END in lines[j]), None
        )
        if end is None:
            end = next(
                (j - 1 for j in range(start + 1, len(lines)) if lines[j].startswith("#")),
                len(lines) - 1,
            )
        return set(range(start, end + 1))
    for i, ln in enumerate(lines):
        if _TRACKER_HEADING.match(ln) and not fenced[i]:
            body = []
            for j in range(i + 1, len(lines)):
                if lines[j].startswith("#") and not fenced[j]:
                    break
                body.append(j)
            if any(lines[j].strip() for j in body):
                return set(body)
    return set()


def _bullet_title(bullet: str) -> str:
    first = bullet.splitlines()[0][2:].replace("**", "").strip()
    return first if len(first) <= 90 else first[:89].rstrip() + "…"


def _split_discipline(text: str) -> dict[str, Any]:
    """Split a discipline file the way z-sdlc's ``sdlc-migrate`` §2.3 defines.

    Returns ``framework`` (text), ``bullets`` ([(text, section_slug)]),
    ``structure`` (the Parking Lot lines that are neither the heading, its
    instruction line nor a bullet), ``status`` (the ``**Status**:`` line),
    ``active_questions`` and ``project_context`` (every such section, in file order,
    or ``""``), and ``tracker`` (block text or ``""``).
    """
    lines = text.splitlines()
    fenced = _fenced_lines(lines)
    tracker = _tracker_range(lines, fenced)

    # Sections start at a ``## `` heading outside a code fence.
    starts = [
        (i, m.group(1))
        for i, ln in enumerate(lines)
        if not fenced[i] and (m := _H2.fullmatch(ln))
    ]
    bounds = [(0, "", "preamble")] if (not starts or starts[0][0] > 0) else []
    for n, (i, title) in enumerate(starts):
        low = title.lower()
        kind = (
            "parking" if low.startswith("parking lot")
            else "active" if low == "active questions"
            else "context" if low == "project context"
            else "framework"
        )
        bounds.append((i, title, kind))
    ends = [b[0] for b in bounds[1:]] + [len(lines)]

    framework: list[str] = []
    bullets: list[tuple[str, str | None]] = []
    structure: list[str] = []
    status: list[str] = []
    active_sections: list[str] = []
    context_sections: list[str] = []

    def keep(line: str) -> None:
        framework.append(line)

    for (start, _title, kind), end in zip(bounds, ends):
        body = [i for i in range(start, end) if i not in tracker]
        if kind in {"preamble", "framework"}:
            for i in body:
                # The status line is the project's own assessment (§2.3): its own entry.
                if kind == "preamble" and not fenced[i] and _STATUS_LINE.match(lines[i]):
                    status.append(lines[i])
                else:
                    keep(lines[i])
        elif kind in {"active", "context"}:
            section = "\n".join(lines[i] for i in body).strip("\n")
            has_body = any(lines[i].strip() for i in body[1:])
            if has_body:
                (active_sections if kind == "active" else context_sections).append(section)
        else:
            _split_parking_lot(lines, fenced, body, keep, bullets, structure)
        if framework and framework[-1].strip():
            framework.append("")

    return {
        "framework": "\n".join(framework).strip("\n") + "\n" if framework else "",
        "bullets": bullets,
        "structure": structure,
        "status": "\n".join(status) + "\n" if status else "",
        "active_questions": "\n\n".join(active_sections) + "\n" if active_sections else "",
        "project_context": "\n\n".join(context_sections) + "\n" if context_sections else "",
        "tracker": "\n".join(lines[i] for i in sorted(tracker)) + "\n" if tracker else "",
    }


def _split_parking_lot(
    lines: list[str],
    fenced: list[bool],
    body: list[int],
    keep: Any,
    bullets: list[tuple[str, str | None]],
    structure: list[str],
) -> None:
    """Sort one Parking Lot section's lines into framework, bullets and structure."""
    keep(lines[body[0]])  # the ``## Parking Lot`` heading
    rest = body[1:]
    first = next((i for i in rest if lines[i].strip()), None)
    instruction = None
    if first is not None:
        stripped = lines[first].strip()
        if stripped.startswith("*") and stripped.endswith("*") and not stripped.startswith("**"):
            instruction = first
            keep("")
            keep(lines[first])

    section: str | None = None
    current: list[str] | None = None
    blanks: list[str] = []

    def close() -> None:
        nonlocal current, blanks
        if current is not None:
            bullets.append(("\n".join(current), section))
        current, blanks = None, []

    for i in rest:
        line = lines[i]
        if i == instruction:
            continue
        if _TRACKER_HEADING.match(line) and not fenced[i]:
            close()
            keep("")
            keep(line)
            section = None
            continue
        if not line.strip():
            blanks.append(line)
            continue
        is_bullet = line.startswith("- ") and not fenced[i]
        is_heading = line.startswith("#") and not fenced[i]
        if (
            current is not None
            and not is_bullet
            and not is_heading
            and (line[0] in " \t" or not blanks)
        ):
            current.extend(blanks)
            current.append(line)
            blanks = []
            continue
        close()
        if is_bullet:
            current = [line]
        else:
            if (m := _H3.fullmatch(line)) and not fenced[i]:
                section = _slug(m.group(1)) or None
            structure.append(line)
    close()


def _extract_discipline_entries(
    path: Path,
    disciplines_dir: Path,
    upstream: bool = False,
    unreadable: list[Path] | None = None,
    kinds: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    """Turn one discipline file into entries, split as z-sdlc ``sdlc-migrate`` §2.3 does.

    Both modes produce the framework entry and one entry per Parking Lot bullet
    from the same function. Port mode adds the project's own data (Active
    Questions, Project Context, the maturity tracker, the Parking Lot structure)
    and tags the parking-lot entries ``sdlc:project-specific``.

    ``kinds``, when given, receives ``id(entry) -> kind`` for every entry built.

    Returns ``[]`` for README.md, an unreadable file or an empty one.
    """
    if path.name.lower() == "readme.md":
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("Skipping %s — cannot read file: %s", path, exc)
        if unreadable is not None:
            unreadable.append(path)
        return []
    if not text.strip():
        logger.warning("Skipping %s — empty file", path)
        return []

    stem = path.stem
    name = stem.replace("-", " ").replace("_", " ").title()
    source_path = str(path.relative_to(disciplines_dir))
    base_tags = ["sdlc:discipline", f"sdlc:discipline:{stem}"]
    # Parking-lot bullets are content-addressed, so a project's edit is a new id and
    # the tag protects it. The fixed-id entries below stay untagged: they are discipline
    # data, not knowledge the project added, which the tag marks for sdlc-migrate.
    project_tag = [] if upstream else ["sdlc:project-specific"]
    parts = _split_discipline(text)

    def entry(title: str, content: str, suffix: str, tags: list[str]) -> dict[str, Any]:
        built = {
            "title": title,
            "content": content,
            "knowledge_id": f"discipline:{stem}:{suffix}",
            "tags": tags,
            "importance": 0.55,
            "confidence": 0.9,
            "concepts": [],
            "source_path": source_path,
        }
        if kinds is not None:
            kinds[id(built)] = suffix.split(":", 1)[0]
        return built

    entries: list[dict[str, Any]] = []
    if parts["framework"].strip():
        entries.append(
            entry(f"{name} discipline framework", parts["framework"], "framework", list(base_tags))
        )
    if parts["status"]:
        entries.append(entry(f"{name} status", parts["status"], "status", list(base_tags)))
    for bullet, section in parts["bullets"]:
        digest = hashlib.sha1(bullet.encode("utf-8")).hexdigest()[:12]
        tags = [*base_tags, "sdlc:parking-lot"]
        if section:
            tags.append(f"sdlc:parking-lot-section:{section}")
        entries.append(
            entry(_bullet_title(bullet), bullet, f"parking-lot:{digest}", [*tags, *project_tag])
        )
    if parts["structure"]:
        entries.append(
            entry(
                f"{name} parking lot structure",
                "\n".join(parts["structure"]) + "\n",
                "parking-lot-structure",
                [*base_tags, "sdlc:parking-lot-structure"],
            )
        )
    if not upstream:
        if parts["active_questions"]:
            entries.append(
                entry(f"{name} active questions", parts["active_questions"],
                      "active-questions", list(base_tags))
            )
        if parts["project_context"]:
            entries.append(
                entry(f"{name} project context", parts["project_context"],
                      "project-context",
                      [*base_tags, "sdlc:project-context"])
            )
        if parts["tracker"]:
            entries.append(
                entry(f"{name} maturity tracker", parts["tracker"], "maturity-tracker",
                      [*base_tags, "sdlc:maturity-tracker"])
            )
    return entries


class CollectResult:
    """Everything one walk over the knowledge and discipline trees found.

    A plain class, not a dataclass: the tests load this file by path without
    registering the module, which ``dataclasses`` cannot resolve under
    ``from __future__ import annotations``.
    """

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        # The same entries grouped by source file, so chunking never splits a file.
        self.groups: list[list[dict[str, Any]]] = []
        self.yaml_entry_count = 0
        self.markdown_entry_count = 0
        self.discipline_entry_count = 0
        self.sanitized_id_count = 0
        self.duplicate_id_count = 0
        # One line per id that needed a :dupN or :document suffix to stay unique.
        self.collisions: list[str] = []
        # The same collisions as log lines, emitted by _emit_duplicate_warnings.
        self.duplicate_warnings: list[str] = []
        # Entries tagged by --tag-new (port mode: ids the baseline lacks).
        self.tag_new_count = 0
        # Knowledge files that failed to parse (YAML error, bad root, unparsed items).
        self.failed_files: list[str] = []
        # Dangling symlinks among the files the extractor would read (a subset of failed_files).
        self.dangling_symlinks: list[str] = []
        # (file, item, value) for each item whose tags is not a list of strings.
        self.malformed_tags: list[tuple[str, str, Any]] = []
        # id() of each YAML entry whose id the file wrote itself (not built from the path).
        self.field_ids: set[int] = set()
        # id() of every discipline entry object -> its kind (see _is_fixed_project_data).
        self.discipline_kinds: dict[int, str] = {}
        # Entries --exclude-kinds left out of the run.
        self.excluded_kind_count = 0
        # Files under knowledge/ that are neither YAML nor Markdown.
        self.other_files: list[str] = []
        # Markdown under knowledge/ that is an index or log, never seeded.
        self.skipped_markdown: list[str] = []
        # "path (reason)" for discipline files not turned into entries.
        self.skipped_disciplines: list[str] = []
        self.yaml_file_count = 0
        self.markdown_file_count = 0
        self.discipline_file_count = 0
        self.skipped_count = 0
        self.declined_count = 0
        # Knowledge files (relative paths) that produced no entry.
        self.zero_entry_files: list[str] = []


def _load_declined(manifest_path: Path | None, *, explicit: bool) -> frozenset[str]:
    """Installed paths the project declined, from ``.sdlc-manifest.json``.

    A missing or unreadable manifest declines nothing and logs one warning. A
    missing default manifest (``explicit`` false) is not worth a warning.
    """
    if manifest_path is None:
        return frozenset()
    if not manifest_path.is_file():
        if explicit:
            logger.warning("Manifest not found: %s — nothing is declined", manifest_path)
        return frozenset()
    try:
        manifest: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
        declined: Any = manifest.get("declined_files")
        if declined is None:
            return frozenset()
        if isinstance(declined, dict):
            return frozenset(str(k) for k in declined)
        if isinstance(declined, list):
            return frozenset(str(k) for k in declined)
        raise ValueError(f"declined_files is a {type(declined).__name__}")
    except (OSError, ValueError, AttributeError) as exc:
        logger.warning("Cannot use manifest %s (%s) — nothing is declined", manifest_path, exc)
        return frozenset()


def _is_declined(rel: Path, declined: frozenset[str]) -> bool:
    """True when the knowledge file's installed path is in ``declined_files``."""
    if not declined:
        return False
    rel_posix = rel.as_posix()
    return (
        f"ops/sdlc/knowledge/{rel_posix}" in declined
        or f"[sdlc-root]/knowledge/{rel_posix}" in declined
    )


def _unique_id(knowledge_id: str, used: set[str]) -> str:
    """Suffix ``:document`` until the id differs from every id already emitted."""
    while knowledge_id in used:
        knowledge_id = f"{knowledge_id}:document"
    return knowledge_id


def _is_valid_id(knowledge_id: str) -> bool:
    return _ID_BODY.fullmatch(knowledge_id) is not None


def _sanitize_id(knowledge_id: str) -> str:
    """Make an id API-safe; a valid id comes back byte-identical.

    Disallowed characters become ``-``, runs of ``-`` collapse, leading
    non-alphanumerics go, and an id still over 100 characters is cut and given a
    short hash of the original, so the result is deterministic.
    """
    if _is_valid_id(knowledge_id):
        return knowledge_id
    cleaned = re.sub(r"[^a-zA-Z0-9._:-]", "-", knowledge_id)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    cleaned = re.sub(r"^[^a-zA-Z0-9]+", "", cleaned)
    if cleaned and len(cleaned) <= _ID_MAX_LEN:
        return cleaned
    digest = hashlib.sha1(knowledge_id.encode("utf-8")).hexdigest()[:8]
    if not cleaned:
        return f"entry-{digest}"
    return f"{cleaned[: _ID_MAX_LEN - len(digest) - 1]}-{digest}"


def _dup_id(base: str, n: int, taken: set[str]) -> str:
    """``base:dupN`` (``N`` raised until unused), cut to stay within 100 characters."""
    while True:
        suffix = f":dup{n}"
        candidate = base[: _ID_MAX_LEN - len(suffix)] + suffix
        if candidate not in taken:
            return candidate
        n += 1


def _finalize_ids(
    entries: list[dict[str, Any]],
    result: CollectResult,
    pre_sanitized: frozenset[int] = frozenset(),
) -> None:
    """Make every ``knowledge_id`` API-safe and unique, in place.

    Valid ids are upsert keys in production and never change, except a later
    duplicate of one, which gets ``:dup2``, ``:dup3``, ... A sanitized id that
    would land on any valid id takes a ``:dupN`` suffix itself. ``pre_sanitized``
    holds ``id()`` of entries whose id was already sanitized at parse time.
    """
    originally_valid = [
        _is_valid_id(e["knowledge_id"]) and id(e) not in pre_sanitized for e in entries
    ]
    taken = {e["knowledge_id"] for e, ok in zip(entries, originally_valid) if ok}
    seen: dict[str, int] = {}
    first_source: dict[str, str] = {}

    def settle(entry: dict[str, Any], new_id: str, *, reserved: bool) -> None:
        seen[new_id] = seen.get(new_id, 0) + 1
        if seen[new_id] == 1 and (reserved or new_id not in taken):
            taken.add(new_id)
            first_source[new_id] = entry["source_path"]
            entry["knowledge_id"] = new_id
            return
        renamed = _dup_id(new_id, max(seen[new_id], 2), taken)
        # Logged by the caller once the reserved-namespace check has passed, so a run that
        # is about to refuse never reads as if a rename happened.
        result.duplicate_warnings.append(
            f"Duplicate knowledge_id {new_id!r} in {entry['source_path']} "
            f"(first seen in {first_source.get(new_id, 'another file')}): renamed to {renamed!r}"
        )
        taken.add(renamed)
        entry["knowledge_id"] = renamed
        result.duplicate_id_count += 1
        result.collisions.append(
            f"{new_id!r} in {entry['source_path']} also used by "
            f"{first_source.get(new_id, 'another file')}: renamed to {renamed!r}"
        )

    for entry, ok in zip(entries, originally_valid):
        if ok:
            settle(entry, entry["knowledge_id"], reserved=True)
    for entry, ok in zip(entries, originally_valid):
        if not ok:
            result.sanitized_id_count += 1
            settle(entry, _sanitize_id(entry["knowledge_id"]), reserved=False)


def _is_read_knowledge_name(path: Path) -> bool:
    """True for a knowledge file name the extractor would read (not README, a log, the map)."""
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        return path.name != "agent-context-map.yaml"
    return suffix == ".md" and path.name.lower() not in _SKIPPED_DOC_NAMES


def _target_dir_problem(directory: Path) -> str | None:
    """Why ``directory`` is not a usable real directory, or ``None`` when it is."""
    if directory.is_symlink():
        if not directory.exists():
            return "is a dangling symlink and does not exist"
        resolved = directory.resolve()
        if not resolved.is_relative_to(directory.parent.resolve()):
            return f"is a symlink resolving outside the tree (to {resolved})"
        return None
    if not directory.is_dir():
        return "does not exist (or is not a directory)"
    return None


def _collect(
    knowledge_dir: Path,
    disciplines_dir: Path,
    declined: frozenset[str] = frozenset(),
    upstream: bool = False,
) -> CollectResult:
    """Walk both source trees and collect all extractable entries."""
    result = CollectResult()
    yaml_groups: list[list[dict[str, Any]]] = []
    unreadable_disciplines: list[Path] = []
    discipline_kinds: dict[int, str] = {}
    unparsed_paths: list[Path] = []
    pre_sanitized: list[dict[str, Any]] = []
    markdown_groups: list[list[dict[str, Any]]] = []

    # Exclude agent-context-map.yaml — it's a configuration file that maps agent
    # roles to knowledge file paths. In Neuroloom, agents use memory_search with
    # tags instead, so this file is not knowledge content and should not be ingested.
    discipline_groups, result.discipline_file_count, result.skipped_disciplines = (
        _collect_disciplines(disciplines_dir, upstream, unreadable_disciplines, discipline_kinds)
    )
    result.failed_files.extend(
        f"disciplines/{p.relative_to(disciplines_dir).as_posix()}" for p in unreadable_disciplines
    )
    if disciplines_dir.is_dir():
        for link in sorted(disciplines_dir.iterdir()):
            if (
                link.is_symlink()
                and not link.exists()
                and link.suffix.lower() == ".md"
                and link.name.lower() != "readme.md"
            ):
                logger.warning("Dangling symlink %s", link)
                named = f"disciplines/{link.name} (dangling symlink)"
                result.failed_files.append(named)
                result.dangling_symlinks.append(named)
    if knowledge_dir.exists():
        knowledge_files = sorted(
            p
            for p in knowledge_dir.rglob("*")
            if p.is_file() and p.name != "agent-context-map.yaml"
        )
        for link in sorted(knowledge_dir.rglob("*")):
            if link.is_symlink() and not link.exists() and _is_read_knowledge_name(link):
                logger.warning("Dangling symlink %s", link)
                named = f"{link.relative_to(knowledge_dir).as_posix()} (dangling symlink)"
                result.failed_files.append(named)
                result.dangling_symlinks.append(named)
        yaml_paths = [p for p in knowledge_files if p.suffix.lower() in {".yaml", ".yml"}]
        md_paths = [
            p
            for p in knowledge_files
            if p.suffix.lower() == ".md" and p.name.lower() not in _SKIPPED_DOC_NAMES
        ]
        result.skipped_markdown = [
            p.relative_to(knowledge_dir).as_posix()
            for p in knowledge_files
            if p.suffix.lower() == ".md" and p.name.lower() in _SKIPPED_DOC_NAMES
        ]
        result.other_files = [
            p.relative_to(knowledge_dir).as_posix()
            for p in knowledge_files
            if p.suffix.lower() not in {".yaml", ".yml", ".md"} and p.name != ".DS_Store"
        ]

        for yaml_path in yaml_paths:
            rel = yaml_path.relative_to(knowledge_dir)
            if _is_declined(rel, declined):
                result.declined_count += 1
                continue
            result.yaml_file_count += 1
            entries, skipped = _extract_yaml_entries(
                yaml_path, knowledge_dir, pre_sanitized, unparsed_paths, result.malformed_tags,
                result.field_ids,
            )
            if entries:
                yaml_groups.append(entries)
            result.yaml_entry_count += len(entries)
            result.skipped_count += skipped
            if skipped or yaml_path in unparsed_paths:
                result.failed_files.append(rel.as_posix())
            if not entries:
                result.zero_entry_files.append(rel.as_posix())

        # Document ids are settled against every id already emitted, so a
        # document cannot take a YAML or discipline id.
        used_ids = {e["knowledge_id"] for g in yaml_groups for e in g}
        used_ids.update(e["knowledge_id"] for g in discipline_groups for e in g)

        for md_path in md_paths:
            rel = md_path.relative_to(knowledge_dir)
            if _is_declined(rel, declined):
                result.declined_count += 1
                continue
            result.markdown_file_count += 1
            unreadable_md: list[Path] = []
            md_entry = _extract_markdown_entry(md_path, knowledge_dir, unreadable_md)
            if md_entry is None:
                result.zero_entry_files.append(rel.as_posix())
                if unreadable_md:
                    result.failed_files.append(rel.as_posix())
                continue
            wanted_id = md_entry["knowledge_id"]
            md_entry["knowledge_id"] = _unique_id(wanted_id, used_ids)
            if md_entry["knowledge_id"] != wanted_id:
                result.duplicate_id_count += 1
                result.collisions.append(
                    f"{wanted_id!r} of document {rel.as_posix()} is already used: "
                    f"renamed to {md_entry['knowledge_id']!r}"
                )
            used_ids.add(md_entry["knowledge_id"])
            markdown_groups.append([md_entry])
            result.markdown_entry_count += 1
    else:
        logger.warning("Knowledge directory does not exist: %s", knowledge_dir)

    result.discipline_kinds = discipline_kinds
    result.discipline_entry_count = sum(len(g) for g in discipline_groups)
    result.groups = yaml_groups + markdown_groups + discipline_groups
    result.entries = [e for g in result.groups for e in g]
    _finalize_ids(result.entries, result, frozenset(id(e) for e in pre_sanitized))
    return result


def _collect_disciplines(
    disciplines_dir: Path,
    upstream: bool = False,
    unreadable: list[Path] | None = None,
    kinds: dict[int, str] | None = None,
) -> tuple[list[list[dict[str, Any]]], int, list[str]]:
    """Discipline markdown files — top-level only (non-recursive).

    Returns ``(groups, file_count, skipped)``: one group of entries per file;
    ``skipped`` lists ``"path (reason)"`` for each Markdown file with no entry.
    """
    groups: list[list[dict[str, Any]]] = []
    skipped: list[str] = []
    count = 0
    if disciplines_dir.exists():
        md_paths = sorted(
            p
            for p in disciplines_dir.iterdir()
            if p.suffix.lower() == ".md" and p.is_file()
        )
        for md_path in md_paths:
            count += 1
            entries = _extract_discipline_entries(
                md_path, disciplines_dir, upstream, unreadable, kinds
            )
            if entries:
                groups.append(entries)
            elif md_path.name.lower() == "readme.md":
                skipped.append(f"{md_path.name} (README)")
            else:
                skipped.append(f"{md_path.name} (empty or unreadable)")
        skipped.extend(
            f"{p.relative_to(disciplines_dir).as_posix()} (nested, not read)"
            for p in sorted(disciplines_dir.rglob("*.md"))
            if p.is_file() and p.parent != disciplines_dir
        )
    else:
        logger.warning("Disciplines directory does not exist: %s", disciplines_dir)
    return groups, count, skipped


def _collect_all_entries(
    knowledge_dir: Path,
    disciplines_dir: Path,
    declined: frozenset[str] = frozenset(),
) -> tuple[list[dict[str, Any]], int, int, int]:
    """Walk both source trees and collect all extractable entries.

    Args:
        knowledge_dir: Root of the SDLC knowledge tree (YAML and Markdown).
        disciplines_dir: Root of the SDLC discipline markdown tree.
        declined: Installed paths of knowledge files the project declined.

    Returns:
        A tuple of ``(entries, yaml_file_count, discipline_file_count, skipped_count)``.
    """
    result = _collect(knowledge_dir, disciplines_dir, declined)
    _emit_duplicate_warnings(result)
    return (
        result.entries,
        result.yaml_file_count,
        result.discipline_file_count,
        result.skipped_count,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point: parse CLI args, collect entries, write JSON output."""
    # Default to cwd — the script is bundled with the plugin but runs
    # against the target project's ops/sdlc/ tree.
    project_root = Path.cwd()

    parser = argparse.ArgumentParser(
        description="Extract SDLC knowledge entries and write them as JSON.",
    )
    parser.add_argument(
        "--knowledge-dir",
        type=Path,
        default=project_root / "ops/sdlc/knowledge",
        help="Path to SDLC knowledge directory (default: ./ops/sdlc/knowledge/)",
    )
    parser.add_argument(
        "--disciplines-dir",
        type=Path,
        default=project_root / "ops/sdlc/disciplines",
        help="Path to SDLC disciplines directory (default: ./ops/sdlc/disciplines/)",
    )
    parser.add_argument(
        "--version",
        default=date.today().strftime("%Y-%m-%d"),
        help="Seed version string (default: today's date)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Write JSON to this file path instead of stdout. The written paths are "
            "printed to stdout, one per line (seed files, then the delta file in "
            "delta mode). Over --max-per-file or --max-bytes the output is split "
            "into <stem>_001<suffix>, <stem>_002<suffix>, ... No file is written "
            "when there are no entries."
        ),
    )
    parser.add_argument(
        "--max-per-file",
        "--max-entries",
        dest="max_per_file",
        type=int,
        default=_DEFAULT_MAX_PER_FILE,
        help=(
            "Most entries in one output file (default: 500, the seed API's limit). "
            "Entries of one source file stay together unless that file alone is larger."
        ),
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=_DEFAULT_MAX_BYTES,
        help=(
            "Most serialized bytes in one output file (default: 900000; the upload "
            "endpoint takes at most 1 MiB). Entries of one source file stay together "
            "unless that file alone is larger."
        ),
    )
    parser.add_argument(
        "--tag",
        action="append",
        default=[],
        metavar="TAG",
        help=(
            "Add TAG to every entry this run produces (repeatable). "
            "The tags the server adds itself are reserved and refused: sdlc:knowledge-id:*, "
            "sdlc:seed-version:*, sdlc:seed, sdlc:sentinel, sdlc:deprecated."
        ),
    )
    parser.add_argument(
        "--tag-new",
        action="append",
        default=[],
        metavar="TAG",
        help=(
            "Port mode only: add TAG (repeatable) to every entry whose id the baseline "
            "tree lacks, i.e. knowledge the project added itself. Needs the --baseline-* "
            "flags (pointing at upstream at the project's source_version). Every entry "
            "is still written; the baseline does not switch on delta output in port mode."
        ),
    )
    parser.add_argument(
        "--exclude-kinds",
        default=None,
        metavar="KINDS",
        help=(
            "Port mode only: comma-separated discipline entry kinds to leave out of every "
            "seed file (framework, status, parking-lot-structure, active-questions, "
            "project-context, maturity-tracker). Parking-lot bullets and all knowledge "
            "entries are unaffected. A re-port passes every fixed kind (all six) so a stub "
            "left on disk cannot overwrite a discipline's framework or project data."
        ),
    )
    parser.add_argument(
        "--only-ids",
        type=Path,
        default=None,
        metavar="FILE",
        help=(
            "Write only the entries whose id is listed in FILE (one per line), packed "
            "by --max-entries and --max-bytes. An empty list writes nothing and exits 0; "
            "an id the run does not produce exits 2. Cannot combine with --baseline-*."
        ),
    )
    parser.add_argument(
        "--allow-duplicates",
        action="store_true",
        help=(
            "Keep going when an id needed a :dupN or :document suffix to stay "
            "unique. Without it such a run reports every collision and exits 1, "
            "because the suffix winner depends on file order."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print a human-readable summary to stderr and exit without writing JSON.",
    )
    parser.add_argument(
        "--no-manifest",
        action="store_true",
        help="Apply no manifest, even when .sdlc-manifest.json exists in the cwd.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help=(
            "Path to .sdlc-manifest.json; knowledge files listed in its "
            "declined_files are skipped (default: ./.sdlc-manifest.json if it "
            "exists; with --upstream the default is no manifest)."
        ),
    )
    parser.add_argument(
        "--baseline-knowledge-dir",
        type=Path,
        default=None,
        help=(
            "The same upstream knowledge tree at the project's source_version, "
            "extracted with the same flags; it must exist and yield entries (exit 2 "
            "otherwise). With --upstream (delta mode) the seed files hold only entries "
            "that are new or changed against it, and <output stem>.delta.json describes "
            "the difference. In port mode it only serves --tag-new. Needs "
            "--baseline-disciplines-dir (and, in delta mode, --output or --dry-run)."
        ),
    )
    parser.add_argument(
        "--baseline-disciplines-dir",
        type=Path,
        default=None,
        help="Delta mode: the disciplines directory matching --baseline-knowledge-dir.",
    )
    parser.add_argument(
        "--upstream",
        action="store_true",
        help=(
            "Read a z-sdlc source checkout: disciplines get the ids, titles and tags "
            "the seed handlers use (discipline:<stem>:framework); knowledge entries "
            "are unchanged. The cwd's manifest is not applied."
        ),
    )
    args = parser.parse_args()
    if args.max_per_file < 1:
        parser.error("--max-per-file must be at least 1")
    if args.max_bytes < 1:
        parser.error("--max-bytes must be at least 1")
    reserved = sorted(t for t in {*args.tag, *args.tag_new} if _is_server_owned_tag(t))
    if reserved:
        parser.error(f"--tag/--tag-new may not set the reserved tag(s): {', '.join(reserved)}")
    excluded_kinds: frozenset[str] = frozenset()
    if args.exclude_kinds is not None:
        if args.upstream:
            parser.error(
                "--exclude-kinds is port mode only: --upstream seeds upstream's own framework "
                "and must not leave kinds out"
            )
        named = [k.strip() for k in args.exclude_kinds.split(",")]
        unknown = sorted({k for k in named if k not in _EXCLUDABLE_KINDS})
        if unknown:
            parser.error(
                f"--exclude-kinds: unknown kind(s) {', '.join(repr(u) for u in unknown)}; "
                f"choose from {', '.join(sorted(_EXCLUDABLE_KINDS))}"
            )
        excluded_kinds = frozenset(named)
    if args.no_manifest and args.manifest is not None:
        parser.error("--no-manifest and --manifest are mutually exclusive")
    has_baseline = args.baseline_knowledge_dir is not None
    if has_baseline != (args.baseline_disciplines_dir is not None):
        parser.error(
            "--baseline-knowledge-dir and --baseline-disciplines-dir must be given together"
        )
    delta_mode = has_baseline and args.upstream
    if args.tag_new and args.upstream:
        parser.error(
            "--tag-new is port-mode only: with --upstream the baseline flags produce a "
            "delta, and upstream's own new entries are not project knowledge"
        )
    if args.tag_new and not has_baseline:
        parser.error("--tag-new needs --baseline-knowledge-dir and --baseline-disciplines-dir")
    if has_baseline and not args.upstream and not args.tag_new:
        parser.error(
            "in port mode the --baseline-* flags only serve --tag-new (port mode always "
            "writes every entry); pass --tag-new, or --upstream for delta output"
        )
    if args.only_ids is not None and has_baseline:
        parser.error("--only-ids cannot combine with --baseline-*: it picks ids explicitly")
    if delta_mode and args.output is None and not args.dry_run:
        parser.error("delta mode (--baseline-*) needs --output to write the delta file")
    wanted_ids: set[str] | None = None
    if args.only_ids is not None:
        try:
            wanted_ids = {
                ln.strip()
                for ln in args.only_ids.read_text(encoding="utf-8").splitlines()
                if ln.strip()
            }
        except OSError as exc:
            parser.error(f"cannot read --only-ids file: {exc}")
    for flag, directory in (
        ("--baseline-knowledge-dir", args.baseline_knowledge_dir),
        ("--baseline-disciplines-dir", args.baseline_disciplines_dir),
    ):
        if directory is not None and not directory.is_dir():
            parser.error(f"{flag} {directory} does not exist; refusing to treat everything as new")

    manifest_path: Path | None = args.manifest
    explicit_manifest = manifest_path is not None
    if args.no_manifest:
        manifest_path = None
    elif manifest_path is None and not args.upstream:
        manifest_path = project_root / _MANIFEST_NAME
    declined = _load_declined(manifest_path, explicit=explicit_manifest)

    refusal = (
        "refusing to report every baseline entry as removed"
        if delta_mode
        else "refusing to seed an incomplete tree"
    )
    if args.upstream:
        for flag, directory in (
            ("--knowledge-dir", args.knowledge_dir),
            ("--disciplines-dir", args.disciplines_dir),
        ):
            problem = _target_dir_problem(directory)
            if problem:
                parser.error(f"{flag} {directory} {problem}; {refusal}")

    # Collect entries.
    result = _collect(args.knowledge_dir, args.disciplines_dir, declined, args.upstream)
    _refuse_if_any(result, "the target", upstream_owned=args.upstream)
    _emit_duplicate_warnings(result)
    if args.upstream:
        for flag, directory, count in (
            ("--knowledge-dir", args.knowledge_dir,
             result.yaml_entry_count + result.markdown_entry_count),
            ("--disciplines-dir", args.disciplines_dir, result.discipline_entry_count),
        ):
            if count == 0:
                parser.error(f"{flag} {directory} yields no entries; {refusal}")
    if args.upstream and result.failed_files:
        parser.error(
            "target file(s) failed to parse or read: " + ", ".join(result.failed_files)
            + "; refusing, since the rest would be seeded, their entries would be reported "
            "as removed, and the version marker would advance past a release that was not "
            "fully ingested"
        )
    if excluded_kinds:
        _apply_exclude_kinds(result, excluded_kinds)
    if (args.tag or args.tag_new) and not result.entries:
        print(
            "ERROR: --tag/--tag-new given but the run produced no entries (a parse error "
            "or a declined path?); refusing, so a caller that deletes its source after a "
            "successful seed keeps it",
            file=sys.stderr,
        )
        sys.exit(1)
    groups = result.groups
    delta: dict[str, Any] | None = None
    baseline_ids: set[str] | None = None
    if has_baseline:
        baseline = _collect(
            args.baseline_knowledge_dir,
            args.baseline_disciplines_dir,
            declined if delta_mode else frozenset(),
            upstream=True,
        )
        _refuse_if_any(baseline, "the baseline", upstream_owned=True)
        _emit_duplicate_warnings(baseline)
        if not baseline.entries:
            parser.error(
                "the baseline trees yield no entries; refusing to treat everything as new"
            )
        if baseline.dangling_symlinks:
            parser.error(
                "baseline tree has dangling symlink(s): " + ", ".join(baseline.dangling_symlinks)
                + "; refusing, since their entries would look new and the project's "
                "deletions would be recreated"
            )
        if delta_mode:
            groups, delta = _compute_delta(result, baseline)
        else:
            baseline_ids = {e["knowledge_id"] for e in baseline.entries}
    if wanted_ids is not None:
        unknown = sorted(wanted_ids - {e["knowledge_id"] for e in result.entries})
        if unknown:
            parser.error(f"--only-ids lists ids this run does not produce: {', '.join(unknown)}")
        groups = [[e for e in g if e["knowledge_id"] in wanted_ids] for g in result.groups]
        groups = [g for g in groups if g]
    all_entries = [e for g in groups for e in g]
    extra_tags = list(dict.fromkeys(args.tag))
    new_tags = list(dict.fromkeys(args.tag_new))
    tagged = list(all_entries)
    if delta is not None:
        tagged.extend(delta["probe_entries"])
    for entry in tagged:
        add = [t for t in extra_tags if t not in entry["tags"]]
        kid = entry["knowledge_id"]
        if (
            baseline_ids is not None
            and kid not in baseline_ids
            and not _is_fixed_project_data(entry, result.discipline_kinds)
        ):
            fresh = [t for t in new_tags if t not in entry["tags"] and t not in add]
            result.tag_new_count += bool(fresh)
            add += fresh
        entry["tags"] = [*entry["tags"], *add]
    try:
        chunks = _chunk_groups(groups, args.max_per_file, args.max_bytes, args.version)
    except _OversizeEntryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    # Derive display-friendly relative paths.
    try:
        knowledge_display = str(args.knowledge_dir.relative_to(project_root)) + "/"
    except ValueError:
        knowledge_display = str(args.knowledge_dir)

    try:
        disciplines_display = str(args.disciplines_dir.relative_to(project_root)) + "/"
    except ValueError:
        disciplines_display = str(args.disciplines_dir)

    if args.dry_run:
        _print_dry_run(
            result, chunks, args, knowledge_display, disciplines_display, delta, all_entries
        )
        _report_collisions(result, args.allow_duplicates)
        sys.exit(1 if result.collisions and not args.allow_duplicates else 0)

    if result.collisions and not args.allow_duplicates:
        _report_collisions(result, args.allow_duplicates)
        sys.exit(1)

    if not all_entries:
        logger.warning("No entries to write: no seed file written")
        if delta is not None and args.output is not None:
            _write_delta(args.output, delta)
        return

    if args.output is None:
        if len(chunks) > 1:
            logger.warning(
                "%d entries exceed the seed API's limits (--max-per-file %d, "
                "--max-bytes %d); pass --output to write several files",
                len(all_entries),
                args.max_per_file,
                args.max_bytes,
            )
        sys.stdout.write(json.dumps({"entries": all_entries, "version": args.version}))
        sys.stdout.write("\n")
        return

    for path, chunk in zip(_output_paths(args.output, len(chunks)), chunks):
        path.write_text(
            json.dumps({"entries": chunk, "version": args.version}), encoding="utf-8"
        )
        print(path)
    if delta is not None:
        _write_delta(args.output, delta)


def _emit_duplicate_warnings(result: CollectResult) -> None:
    for message in result.duplicate_warnings:
        logger.warning("%s", message)
    result.duplicate_warnings = []


def _reserved_namespace_claims(result: CollectResult) -> list[tuple[str, str, bool]]:
    """Entries that are not built from a discipline file but carry a ``discipline:`` id.

    The server matches by id alone, so such an entry (a YAML item setting its own
    ``knowledge_id`` or ``rule_id``, or a file path that spells one) would overwrite the
    discipline's own entry. Judged on the final id, so a sanitised or hashed one counts.
    """
    return [
        # The last field: the extractor built the id from the path or a section key, not
        # from a field the file wrote. Recorded when the entry was built, never guessed
        # from the id's shape (sanitising changes the shape; a written id can look like one).
        (e["knowledge_id"], e["source_path"], id(e) not in result.field_ids)
        for e in result.entries
        if id(e) not in result.discipline_kinds and e["knowledge_id"].startswith("discipline:")
    ]


def _server_tag_claims(result: CollectResult) -> list[tuple[str, str, str]]:
    """``(id, file, tag)`` for each entry whose own tags include one the server adds.

    Checked on the tags as built, so the run's own ``--tag``/``--tag-new`` (applied later,
    and refused at argument parsing if they name such a tag) never trip it.
    """
    return [
        (e["knowledge_id"], e["source_path"], t)
        for e in result.entries
        for t in e["tags"]
        if isinstance(t, str) and _is_server_owned_tag(t)
    ]


def _malformed_server_tag_claims(result: CollectResult) -> list[tuple[str, str, str]]:
    """``(item label, file, tag)`` for server-owned tags inside a malformed ``tags`` value.

    A malformed value's own tags were replaced by defaults, so the entry never carries
    them, but the file still names what it tried to set. A bare string counts as a
    one-element list. Reported in the same run as the malformed value, labelled by item
    because no entry id was built from them.
    """
    claims: list[tuple[str, str, str]] = []
    for path, label, value in result.malformed_tags:
        members = [value] if isinstance(value, str) else value if isinstance(value, list) else []
        claims += [(label, path, t) for t in members if isinstance(t, str) and _is_server_owned_tag(t)]
    return claims


def _server_tags_message(
    claims: list[tuple[str, str, str]],
    item_claims: list[tuple[str, str, str]],
    tree: str,
    *,
    upstream_owned: bool,
) -> str | None:
    """The refusal naming each entry's id (or item) with its file and tag; advice by whose
    file it is. ``claims`` are listed by entry id, ``item_claims`` by item label."""
    if not claims and not item_claims:
        return None
    listed = "; ".join(
        [f"{kid!r} in {path} carries {tag!r}" for kid, path, tag in claims]
        + [f"item {label!r} in {path} carries {tag!r}" for label, path, tag in item_claims]
    )
    head = (
        f"ERROR: {tree} knowledge entries carry tags the server adds itself: {listed}. The "
        "server finds an existing row by its sdlc:knowledge-id: tag, so such a tag could make "
        "one entry's row stand in for another's. "
    )
    if upstream_owned:
        tail = (
            "The tag is in upstream's release, so the project cannot remove it. Nothing was "
            "sent and nothing was written. Report it as a plugin bug; do not edit the file."
        )
    else:
        files = ", ".join(dict.fromkeys(path for _, path, _ in [*claims, *item_claims]))
        tail = f"Remove the tag from the item in {files}, then re-run. Nothing was written."
    return head + tail


def _malformed_tags_message(
    claims: list[tuple[str, str, Any]], tree: str, *, upstream_owned: bool
) -> str | None:
    """The refusal for items whose ``tags`` is not a list of strings, naming file and item.

    YAML reads an unquoted ``on``, ``off``, ``yes`` and ``no`` as booleans, so ``tags: [on]``
    is ``[True]`` and ``tags: off`` is ``False``. The advice says the fix that applies: put a
    lone value in a list, or quote a non-string list element.
    """
    if not claims:
        return None
    listed = "; ".join(f"{label!r} in {path} has tags {value!r}" for path, label, value in claims)
    head = (
        f"ERROR: {tree} knowledge items carry a malformed tags value (tags must be a list of "
        f"strings): {listed}. "
    )
    if upstream_owned:
        tail = (
            "The item is in upstream's release, so the project cannot fix it. Nothing was sent "
            "and nothing was written. Report it as a plugin bug; do not edit the file."
        )
    else:
        files = ", ".join(dict.fromkeys(path for path, _, _ in claims))
        fixes = []
        if any(not isinstance(value, list) and value for _, _, value in claims):
            fixes.append("put it in a list of strings, as tags: [name] (a lone value is not "
                         "a list)")
        if any(not isinstance(value, list) and not value for _, _, value in claims):
            fixes.append("remove the `tags` key or write `tags: []` for the defaults, or quote "
                         "the value inside a list (YAML reads an unquoted off/no/false as a "
                         "boolean, and `[off]` is refused too)")
        if any(isinstance(value, list) for _, _, value in claims):
            fixes.append("quote each non-string list element (YAML reads an unquoted "
                         "on/off/yes/no as a boolean)")
        tail = f"Fix the tags in {files}: {'; '.join(fixes)}. Then re-run. Nothing was written."
    return head + tail


def _path_cause_advice(source_path: str) -> str:
    """What to change when an id was built from this path and starts with ``discipline:``.

    Names the path component that produced it: sanitising strips a leading ``_`` or other
    non-alphanumerics, so ``_discipline/notes.yaml`` builds a ``discipline:`` id although
    the directory is not ``knowledge/discipline/``.
    """
    parts = Path(source_path).parts
    if len(parts) == 1:
        return (
            f"the file name of {source_path} makes its id start with discipline:; rename the "
            "file so its path no longer begins `discipline`"
        )
    if parts[0] == "discipline":
        return (
            f"the id of {source_path} comes from its path: move or rename the file out of "
            "knowledge/discipline/"
        )
    return (
        f"the directory `{parts[0]}` under knowledge/ makes the id of {source_path} start "
        "with discipline:; rename the file or its directory so its path no longer begins "
        "`discipline`"
    )


def _reserved_ids_message(
    claims: list[tuple[str, str, bool]], tree: str, *, upstream_owned: bool
) -> str | None:
    """The refusal naming the claims, or ``None`` when there are none. The advice depends on
    whose id it is: a project's own id can be renamed; an id in upstream's release (an
    --upstream target or any baseline) cannot, and re-running would hit the same error."""
    if not claims:
        return None
    listed = "; ".join(f"{kid!r} from {path}" for kid, path, _ in claims)
    field_files = ", ".join(dict.fromkeys(path for _, path, from_path in claims if not from_path))
    head = (
        f"ERROR: the discipline: id namespace belongs to discipline files; {tree} "
        f"knowledge entries claim it: {listed}. Such an entry would overwrite a "
        "discipline's own entry (the server matches by id alone). "
    )
    if upstream_owned:
        tail = (
            "The id is in upstream's release, so the project cannot rename it. Nothing was "
            "sent and nothing was written. Report it as a plugin bug; do not edit the file."
        )
    else:
        advice = []
        if field_files:
            advice.append(f"Rename the id in {field_files}")
        for path in dict.fromkeys(p for _, p, from_path in claims if from_path):
            advice.append(_path_cause_advice(path))
        advice[0] = advice[0][0].upper() + advice[0][1:]
        tail = "; ".join(advice) + ", then re-run. Nothing was written."
    return head + tail


def _refuse_if_any(result: CollectResult, tree: str, *, upstream_owned: bool) -> None:
    """Print every kind of refusal this tree earns, then exit 1 (nothing was written).

    All of them in one run, so ``tags: [on, "sdlc:seed"]`` names both problems at once.
    """
    messages = [
        m
        for m in (
            _reserved_ids_message(
                _reserved_namespace_claims(result), tree, upstream_owned=upstream_owned
            ),
            _malformed_tags_message(result.malformed_tags, tree, upstream_owned=upstream_owned),
            _server_tags_message(
                _server_tag_claims(result), _malformed_server_tag_claims(result), tree,
                upstream_owned=upstream_owned,
            ),
        )
        if m
    ]
    if messages:
        print("\n".join(messages), file=sys.stderr)
        sys.exit(1)


def _apply_exclude_kinds(result: CollectResult, kinds: frozenset[str]) -> None:
    """Drop the discipline entries of ``kinds`` from the run, judged by the kind each was
    built with and never by its id string (a long stem gets a hashed id)."""
    before = len(result.entries)
    groups = [
        [e for e in g if result.discipline_kinds.get(id(e)) not in kinds] for g in result.groups
    ]
    result.groups = [g for g in groups if g]
    result.entries = [e for g in result.groups for e in g]
    result.excluded_kind_count = before - len(result.entries)
    result.discipline_entry_count = sum(
        1 for e in result.entries if id(e) in result.discipline_kinds
    )


def _write_delta(output: Path, delta: dict[str, Any]) -> None:
    """Write ``<output stem>.delta.json`` next to the seed file and print its path."""
    delta_path = output.with_name(f"{output.stem}.delta.json")
    delta_path.write_text(json.dumps(delta), encoding="utf-8")
    print(delta_path)


def _report_collisions(result: CollectResult, allowed: bool) -> None:
    """Name every id that needed a suffix to stay unique."""
    if not result.collisions:
        return
    verdict = "kept (--allow-duplicates)" if allowed else "the run fails"
    print(f"Duplicate ids ({len(result.collisions)}), {verdict}:", file=sys.stderr)
    for line in result.collisions:
        print(f"  - {line}", file=sys.stderr)


def _probe_eligible(knowledge_id: str) -> bool:
    """True for ids a workspace seeded by the pre-0.7.0 ``knowledge-seed`` handler lacks.

    That handler keyed entries ``{stem}:{key}`` (one colon, no directory). An id with
    two colons that is not a discipline id, or a parking-lot hash id, is not one it
    produced. Probes therefore separate such a handler-seeded workspace from one
    seeded by the extractor. They cannot separate a 0.6.x port from a 0.7.0 one: the
    0.6.x port extractor already made ``{dir}:{stem}:{key}`` ids, the same as today.
    Only the manifest marker tells those apart.
    """
    if ":parking-lot:" in knowledge_id:
        return True
    return knowledge_id.count(":") >= 2 and not knowledge_id.startswith("discipline:")


def _compute_delta(
    target: CollectResult, baseline: CollectResult
) -> tuple[list[list[dict[str, Any]]], dict[str, Any]]:
    """Entries new or changed against the baseline, plus the delta report.

    ``probe_ids`` are up to 10 unchanged, new-scheme ids, one per source file and
    spread across the files, for the caller to look up in the workspace.
    ``noop_entry`` is one whole unchanged entry (a knowledge entry from a file the
    delta does not touch, lowest id) that the caller can seed alone to advance the
    workspace's version marker when nothing else changed.
    """
    # Project data a migration must never overwrite (the status line, the Parking Lot
    # structure with the project's own subsections, ...): not part of any delta.
    base = {
        e["knowledge_id"]: e
        for e in baseline.entries
        if not _is_fixed_project_data(e, baseline.discipline_kinds)
    }
    target_entries = [
        e for e in target.entries if not _is_fixed_project_data(e, target.discipline_kinds)
    ]
    target_ids = {e["knowledge_id"] for e in target_entries}
    new: list[str] = []
    new_content: dict[str, str] = {}
    changed: list[dict[str, str]] = []
    unchanged: list[dict[str, Any]] = []
    send: set[str] = set()
    touched: set[str] = set()
    for entry in target_entries:
        kid = entry["knowledge_id"]
        old = base.get(kid)
        if old is None:
            new.append(kid)
            new_content[kid] = entry["content"]
            send.add(kid)
            touched.add(entry["source_path"])
        elif old["content"] != entry["content"]:
            # Titles too: the server refreshes title and narrative together on an update.
            changed.append({
                "id": kid, "baseline_content": old["content"], "target_content": entry["content"],
                "baseline_title": old["title"], "target_title": entry["title"],
            })
            send.add(kid)
            touched.add(entry["source_path"])
        else:
            unchanged.append(entry)
    removed = [kid for kid in base if kid not in target_ids]
    touched.update(base[kid]["source_path"] for kid in removed)

    eligible_by_file: dict[str, str] = {}
    for entry in unchanged:
        if _probe_eligible(entry["knowledge_id"]):
            eligible_by_file.setdefault(entry["source_path"], entry["knowledge_id"])
    firsts = list(eligible_by_file.values())
    step = max(len(firsts) / 10, 1)
    probes = [firsts[int(i * step)] for i in range(min(10, len(firsts)))]

    def noop_rank(entry: dict[str, Any]) -> tuple[int, str]:
        is_discipline = "sdlc:discipline" in entry["tags"]
        rank = 2 if is_discipline else (1 if entry["source_path"] in touched else 0)
        return rank, entry["knowledge_id"]

    ranked = sorted(unchanged, key=noop_rank)
    noop = ranked[0] if ranked else None
    by_id = {e["knowledge_id"]: e for e in unchanged}
    # noop first, then the probes, then more unchanged entries by rank, up to 50: the
    # caller sends the first one the server answers "unchanged" for.
    probe_entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for entry in [*ranked[:1], *(by_id[k] for k in probes), *ranked[1:]]:
        if entry["knowledge_id"] not in seen_ids and len(probe_entries) < _MAX_PROBE_ENTRIES:
            seen_ids.add(entry["knowledge_id"])
            probe_entries.append(entry)
    framework_ids = {
        Path(e["source_path"]).stem: e["knowledge_id"]
        for e in target.entries
        if target.discipline_kinds.get(id(e)) == "framework"
    }
    delta = {
        "new": new,
        "new_content": new_content,
        "changed": changed,
        "removed": removed,
        "unchanged_count": len(unchanged),
        "probe_ids": probes,
        "noop_entry": noop,
        "probe_entries": probe_entries,
        "framework_ids": framework_ids,
    }
    groups = [[e for e in g if e["knowledge_id"] in send] for g in target.groups]
    return [g for g in groups if g], delta
class _OversizeEntryError(Exception):
    """A single entry that cannot fit in any file within --max-bytes."""

    def __init__(self, knowledge_id: str, size: int, limit: int) -> None:
        super().__init__(
            f"entry {knowledge_id!r} alone is {size} bytes as a seed file, over "
            f"--max-bytes {limit}; the API would reject it"
        )


def _entry_bytes(entry: dict[str, Any]) -> int:
    return len(json.dumps(entry).encode("utf-8"))


def _payload_bytes(entries: list[dict[str, Any]], version: str) -> int:
    """Size of the serialized seed file holding ``entries``."""
    return len(json.dumps({"entries": entries, "version": version}).encode("utf-8"))


def _chunk_groups(
    groups: list[list[dict[str, Any]]],
    max_per_file: int,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    version: str = "",
) -> list[list[dict[str, Any]]]:
    """Pack per-source groups into files within both limits.

    A file holds at most ``max_per_file`` entries and serializes to at most
    ``max_bytes`` bytes. A group is never split across files unless it alone
    exceeds a limit; then it is split by entries and a warning says so. One
    entry that alone exceeds ``max_bytes`` gets a file to itself, with a warning.
    """
    base = _payload_bytes([], version)
    files: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    total = 0  # summed entry bytes of ``current``

    def size_with(count: int, entry_bytes: int) -> int:
        return base + entry_bytes + 2 * max(count - 1, 0)

    def fits(extra: list[dict[str, Any]], extra_bytes: int) -> bool:
        count = len(current) + len(extra)
        return count <= max_per_file and size_with(count, total + extra_bytes) <= max_bytes

    def flush() -> None:
        nonlocal current, total
        if current:
            files.append(current)
        current, total = [], 0

    for group in groups:
        group_bytes = sum(_entry_bytes(e) for e in group)
        if len(group) <= max_per_file and size_with(len(group), group_bytes) <= max_bytes:
            if current and not fits(group, group_bytes):
                flush()
            current.extend(group)
            total += group_bytes
            continue
        logger.warning(
            "%s alone has %d entries / %d bytes, over the limit (%d entries, %d bytes): "
            "splitting it by entries",
            group[0]["source_path"], len(group), size_with(len(group), group_bytes),
            max_per_file, max_bytes,
        )
        flush()
        for entry in group:
            entry_bytes = _entry_bytes(entry)
            if size_with(1, entry_bytes) > max_bytes:
                raise _OversizeEntryError(
                    entry["knowledge_id"], size_with(1, entry_bytes), max_bytes
                )
            if current and not fits([entry], entry_bytes):
                flush()
            current.append(entry)
            total += entry_bytes
    flush()
    return files


def _output_paths(output: Path, count: int) -> list[Path]:
    """``output`` itself for one file, else ``<stem>_001<suffix>``, ``_002``, ..."""
    if count == 1:
        return [output]
    return [output.with_name(f"{output.stem}_{i:03d}{output.suffix}") for i in range(1, count + 1)]


def _print_dry_run(
    result: CollectResult,
    chunks: list[list[dict[str, Any]]],
    args: argparse.Namespace,
    knowledge_display: str,
    disciplines_display: str,
    delta: dict[str, Any] | None = None,
    seed_entries: list[dict[str, Any]] | None = None,
) -> None:
    """Human-readable summary on stderr."""

    def out(line: str = "") -> None:
        print(line, file=sys.stderr)

    all_entries = result.entries if seed_entries is None else seed_entries
    out("Dry run — no JSON will be written.")
    out(
        f"Scanned: {knowledge_display} ({result.yaml_file_count} YAML + "
        f"{result.markdown_file_count} Markdown files), "
        f"{disciplines_display} ({result.discipline_file_count} files)"
    )
    out(f"Total entries: {len(result.entries)}")
    out(f"  YAML: {result.yaml_file_count} files, {result.yaml_entry_count} entries")
    out(
        f"  Markdown documents: {result.markdown_file_count} files, "
        f"{result.markdown_entry_count} entries"
    )
    out(
        f"  Disciplines: {result.discipline_file_count} files, "
        f"{result.discipline_entry_count} entries"
    )
    out(
        f"Declined: {result.declined_count} knowledge file(s) skipped "
        "(manifest declined_files)"
    )
    out(
        f"IDs sanitized: {result.sanitized_id_count}; "
        f"de-duplicated: {result.duplicate_id_count}"
    )
    if delta is not None:
        out(
            f"Delta: {len(delta['new'])} new, {len(delta['changed'])} changed, "
            f"{len(delta['removed'])} removed, {delta['unchanged_count']} unchanged "
            f"(seed files hold {len(all_entries)} entries)"
        )
    out(
        f"Output files: {len(chunks)} (at most {args.max_per_file} entries and "
        f"{args.max_bytes} bytes each)"
    )
    for i, chunk in enumerate(chunks, start=1):
        out(f"  file {i}: {len(chunk)} entries, {_payload_bytes(chunk, args.version)} bytes")
    if args.exclude_kinds is not None:
        out(
            f"Entries left out by --exclude-kinds ({args.exclude_kinds}): "
            f"{result.excluded_kind_count} entries"
        )
    if args.tag:
        out(f"Extra tags on every entry: {', '.join(args.tag)}")
    if args.tag_new:
        out(
            f"Baseline-absent entries newly tagged {', '.join(args.tag_new)}: "
            f"{result.tag_new_count}"
        )
    if result.zero_entry_files:
        out(f"Files with zero entries ({len(result.zero_entry_files)}):")
        for name in result.zero_entry_files:
            out(f"  - {name}")
    else:
        out("Files with zero entries: none")
    for label, names in (
        ("Knowledge files that are neither YAML nor Markdown (not seeded)", result.other_files),
        ("Knowledge Markdown files not seeded (README, provenance log)", result.skipped_markdown),
        ("Discipline files not seeded", result.skipped_disciplines),
    ):
        if names:
            out(f"{label} ({len(names)}):")
            for name in names:
                out(f"  - {name}")
    out()
    out("Sample titles (first 10):")
    for i, entry in enumerate(all_entries[:10], start=1):
        out(f"  {i}. {entry['title']}")
    remaining = len(all_entries) - 10
    if remaining > 0:
        out(f"  ... and {remaining} more")


if __name__ == "__main__":
    main()
