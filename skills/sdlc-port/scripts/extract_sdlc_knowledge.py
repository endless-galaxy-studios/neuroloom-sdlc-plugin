#!/usr/bin/env python3
"""Extracts SDLC knowledge entries from the ops/sdlc/ tree and writes them
as JSON — to stdout by default, or to a file with --output.

The output is suitable for direct use with sdlc_seed_from_file (stdio mode)
or sdlc_seed_get_upload_url (HTTP mode).

Usage:
    python scripts/extract_sdlc_knowledge.py > seed.json
    python scripts/extract_sdlc_knowledge.py --output seed.json
    python scripts/extract_sdlc_knowledge.py --dry-run
    python scripts/extract_sdlc_knowledge.py --version 2026-03-28 --output seed.json

# requires: pyyaml
"""

from __future__ import annotations

import argparse
import json
import logging
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
        return f"### {key}\n" + yaml.dump(value, default_flow_style=False)
    return f"### {key}\n{value}"


def _parse_entries_pattern(
    data: dict[str, Any],
    filename: str,
    source_path: str,
) -> list[dict[str, Any]]:
    """One entry per item in the ``entries`` list.

    Each item is expected to have ``topic`` and ``guidance`` fields.  Falls
    back to ``title``/``content`` if present.  Skips malformed items.
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
            continue

        content = str(content_raw)

        # Append any extra fields (rationale, examples, etc.) to content.
        extra_keys = [
            k for k in item if k not in {"topic", "title", "guidance", "content"}
        ]
        for key in extra_keys:
            val = item[key]
            if isinstance(val, (dict, list)):
                content += "\n\n**" + key.title() + ":**\n" + yaml.dump(
                    val, default_flow_style=False
                )
            else:
                content += f"\n\n**{key.title()}:** {val}"

        knowledge_id = (
            item.get("knowledge_id")
            or f"{filename}:{title.lower().replace(' ', '_')}"
        )
        tags: list[str] = item.get("tags") or ["sdlc:knowledge", "sdlc:pattern:entries"]

        results.append(
            {
                "title": title,
                "content": content,
                "knowledge_id": knowledge_id,
                "tags": tags,
                "importance": item.get("importance", base_importance),
                "confidence": item.get("confidence", 0.9),
                "concepts": item.get("concepts") or [],
                "source_path": source_path,
            }
        )

    return results


def _parse_gotchas_pattern(
    data: dict[str, Any],
    filename: str,
    source_path: str,
) -> list[dict[str, Any]]:
    """One entry per item in the ``gotchas`` list."""
    raw_gotchas = data.get("gotchas")
    if not isinstance(raw_gotchas, list):
        return []

    results: list[dict[str, Any]] = []
    for i, item in enumerate(raw_gotchas):
        if not isinstance(item, dict):
            logger.warning("Skipping non-dict gotcha #%d in %s", i, filename)
            continue

        if "id" not in item:
            logger.warning(
                "Skipping gotcha #%d in %s: missing 'id' field",
                i,
                filename,
            )
            continue

        gotcha_id = str(item["id"])
        severity = str(item.get("severity", ""))
        title = str(item.get("title", gotcha_id))

        # Support two gotcha schemas:
        # Schema A (Neuroloom): severity, symptom, cause, resolution
        # Schema B (cc-sdlc): pattern, example, risk, correct_approach
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

        tags = item.get("tags") or [
            "sdlc:knowledge",
            "sdlc:pattern:gotchas",
            "sdlc:type:gotcha",
            f"sdlc:severity:{severity.lower()}",
        ]

        results.append(
            {
                "title": title,
                "content": "\n".join(content_lines),
                "knowledge_id": gotcha_id,
                "tags": tags,
                "importance": _importance_from_severity(severity),
                "confidence": 0.9,
                "concepts": item.get("concepts") or [],
                "source_path": source_path,
            }
        )

    return results


def _parse_rules_pattern(
    data: dict[str, Any],
    filename: str,
    source_path: str,
) -> list[dict[str, Any]]:
    """One entry per item in the ``rules`` list."""
    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list):
        return []

    results: list[dict[str, Any]] = []
    for i, item in enumerate(raw_rules):
        if not isinstance(item, dict):
            logger.warning("Skipping non-dict rule #%d in %s", i, filename)
            continue

        # Resolve ID — accept rule_id or id.
        rule_id = str(item.get("rule_id") or item.get("id") or "")
        if not rule_id:
            logger.warning("Skipping rule #%d in %s: no rule_id or id", i, filename)
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
                    content_parts.append(
                        f"\n**{extra.title()}:**\n"
                        + yaml.dump(val, default_flow_style=False)
                    )
                else:
                    content_parts.append(f"\n**{extra.title()}:** {val}")

        tags = item.get("tags") or ["sdlc:knowledge", "sdlc:pattern:rules", "sdlc:type:rule"]
        if severity:
            tags = list(tags) + [f"sdlc:severity:{severity.lower()}"]

        results.append(
            {
                "title": rule_title,
                "content": "\n".join(content_parts),
                "knowledge_id": rule_id,
                "tags": tags,
                "importance": _importance_from_severity(severity),
                "confidence": 0.9,
                "concepts": item.get("concepts") or [],
                "source_path": source_path,
            }
        )

    return results


def _parse_methodology_pattern(
    data: dict[str, Any],
    filename: str,
    source_path: str,
) -> list[dict[str, Any]]:
    """One entry per non-metadata top-level key."""
    spec_relevant = data.get("spec_relevant")
    base_importance = _importance_from_spec_relevant(spec_relevant)

    results: list[dict[str, Any]] = []
    for key, value in data.items():
        if key in _METADATA_KEYS:
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
) -> tuple[list[dict[str, Any]], int]:
    """Parse a single YAML knowledge file into a list of API-ready entry dicts.

    Args:
        path: Absolute path to the YAML file.
        knowledge_dir: Root knowledge directory (used to derive relative paths
            and knowledge_id prefixes).

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
    except OSError as exc:
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

    match pattern:
        case "entries":
            entries = _parse_entries_pattern(data, filename, source_path)
        case "gotchas":
            entries = _parse_gotchas_pattern(data, filename, source_path)
        case "rules":
            entries = _parse_rules_pattern(data, filename, source_path)
        case _:
            # Treat unknown/inferred patterns as methodology.
            entries = _parse_methodology_pattern(data, filename, source_path)

    return entries, 0


def _extract_discipline_entry(
    path: Path,
    disciplines_dir: Path,
) -> dict[str, Any] | None:
    """Parse a single discipline markdown file into an API-ready entry dict.

    Returns ``None`` if the file should be skipped (e.g. README.md or empty).
    """
    if path.name.lower() == "readme.md":
        return None

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Skipping %s — cannot read file: %s", path, exc)
        return None

    if not content.strip():
        logger.warning("Skipping %s — empty file", path)
        return None

    stem = path.stem
    rel = path.relative_to(disciplines_dir)
    source_path = str(rel)

    return {
        "title": stem.replace("-", " ").replace("_", " ").title(),
        "content": content,
        "knowledge_id": f"disciplines:{stem}",
        "tags": ["sdlc:discipline"],
        "importance": 0.55,
        "confidence": 0.9,
        "concepts": [],
        "source_path": source_path,
    }


def _collect_all_entries(
    knowledge_dir: Path,
    disciplines_dir: Path,
) -> tuple[list[dict[str, Any]], int, int, int]:
    """Walk both source trees and collect all extractable entries.

    Args:
        knowledge_dir: Root of the SDLC knowledge YAML tree.
        disciplines_dir: Root of the SDLC discipline markdown tree.

    Returns:
        A tuple of ``(entries, yaml_file_count, discipline_file_count, skipped_count)``.
    """
    all_entries: list[dict[str, Any]] = []
    yaml_file_count = 0
    discipline_file_count = 0
    skipped_count = 0

    # YAML knowledge files — recurse into subdirectories.
    if knowledge_dir.exists():
        yaml_paths = sorted(
            p
            for p in knowledge_dir.rglob("*")
            if p.suffix.lower() in {".yaml", ".yml"} and p.is_file()
        )
        for yaml_path in yaml_paths:
            yaml_file_count += 1
            entries, skipped = _extract_yaml_entries(yaml_path, knowledge_dir)
            all_entries.extend(entries)
            skipped_count += skipped
    else:
        logger.warning("Knowledge directory does not exist: %s", knowledge_dir)

    # Discipline markdown files — top-level only (non-recursive).
    if disciplines_dir.exists():
        md_paths = sorted(
            p
            for p in disciplines_dir.iterdir()
            if p.suffix.lower() == ".md" and p.is_file()
        )
        for md_path in md_paths:
            discipline_file_count += 1
            entry = _extract_discipline_entry(md_path, disciplines_dir)
            if entry is not None:
                all_entries.append(entry)
    else:
        logger.warning("Disciplines directory does not exist: %s", disciplines_dir)

    return all_entries, yaml_file_count, discipline_file_count, skipped_count


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
        help="Write JSON to this file path instead of stdout.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print a human-readable summary to stderr and exit without writing JSON.",
    )
    args = parser.parse_args()

    # Collect entries.
    all_entries, yaml_file_count, discipline_file_count, skipped_count = (
        _collect_all_entries(args.knowledge_dir, args.disciplines_dir)
    )

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
        print("Dry run — no JSON will be written.", file=sys.stderr)
        print(
            f"Scanned: {knowledge_display} ({yaml_file_count} files), "
            f"{disciplines_display} ({discipline_file_count} files)",
            file=sys.stderr,
        )
        print(f"Total entries: {len(all_entries)}", file=sys.stderr)
        print(file=sys.stderr)
        print("Sample titles (first 10):", file=sys.stderr)
        for i, entry in enumerate(all_entries[:10], start=1):
            print(f"  {i}. {entry['title']}", file=sys.stderr)
        remaining = len(all_entries) - 10
        if remaining > 0:
            print(f"  ... and {remaining} more", file=sys.stderr)
        return

    # Build output payload.
    payload = {"entries": all_entries, "version": args.version}
    json_output = json.dumps(payload)

    if args.output is not None:
        args.output.write_text(json_output, encoding="utf-8")
    else:
        sys.stdout.write(json_output)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
