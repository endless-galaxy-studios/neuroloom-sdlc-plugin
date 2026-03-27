#!/usr/bin/env python3
"""Extracts deliverable documents from the docs/ tree and writes them as a
flat JSON array — to stdout by default, or to a file with --output.

The output is a raw JSON array suitable for direct use with the
document_ingest_batch API endpoint.

Usage:
    python scripts/extract_deliverable_docs.py > docs.json
    python scripts/extract_deliverable_docs.py --output docs.json
    python scripts/extract_deliverable_docs.py --dry-run
    python scripts/extract_deliverable_docs.py --docs-dir /path/to/docs --output docs.json

# requires: pyyaml
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
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

BATCH_SIZE = 50


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------


def _parse_frontmatter(content: str) -> dict[str, Any] | None:
    """Extract YAML frontmatter from markdown content.

    Returns parsed dict if valid frontmatter exists, None otherwise.
    Frontmatter must be between --- delimiters at the start of the file.
    """
    if not content.startswith("---"):
        return None
    end = content.find("---", 3)
    if end == -1:
        return None
    try:
        return yaml.safe_load(content[3:end])
    except yaml.YAMLError:
        return None


# ---------------------------------------------------------------------------
# Document extraction helpers
# ---------------------------------------------------------------------------


def _extract_doc(
    path: Path,
    docs_dir: Path,
) -> tuple[dict[str, Any] | None, int]:
    """Parse a single markdown file into an API-ready document dict.

    Args:
        path: Absolute path to the markdown file.
        docs_dir: Root docs directory (used to derive relative source paths).

    Returns:
        A tuple of ``(doc, skipped_count)`` where ``skipped_count`` is 1 if
        the file could not be read due to an OSError and 0 otherwise. When the
        file has no valid frontmatter, returns ``(None, 0)`` — the file is
        silently excluded.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Skipping %s — cannot read file: %s", path, exc)
        return None, 1

    frontmatter = _parse_frontmatter(content)
    if frontmatter is None:
        # No valid frontmatter — silently skip, do not count as error.
        return None, 0

    stem = path.stem
    source_path = str(path.relative_to(docs_dir.parent))
    source_type = "sdlc_chronicle" if "/chronicle/" in source_path else "sdlc_deliverable"

    # Build classification tags from frontmatter fields.
    tags: list[str] = ["sdlc:deliverable"]
    tier = frontmatter.get("tier")
    if tier is not None:
        tags.append(f"sdlc:tier:{tier}")
    doc_type = frontmatter.get("type")
    if doc_type is not None:
        tags.append(f"sdlc:type:{doc_type}")
    status = frontmatter.get("status")
    if status is not None:
        tags.append(f"sdlc:status:{status}")

    return {
        "title": stem,
        "content": content,
        "source_type": source_type,
        "source_path": source_path,
        "tags": tags,
        "format": "markdown",
        "knowledge_id": f"deliverable:{stem}",
    }, 0


def _collect_all_docs(
    docs_dir: Path,
) -> tuple[list[dict[str, Any]], int, int, int]:
    """Walk the docs tree and collect all extractable document dicts.

    Args:
        docs_dir: Root of the docs markdown tree.

    Returns:
        A tuple of ``(docs, md_file_count, frontmatter_count, skipped_count)``
        where ``md_file_count`` is the total number of .md files found,
        ``frontmatter_count`` is the subset that had valid frontmatter and were
        included, and ``skipped_count`` counts OSError-unreadable files.
    """
    all_docs: list[dict[str, Any]] = []
    md_file_count = 0
    frontmatter_count = 0
    skipped_count = 0

    if not docs_dir.exists():
        logger.warning("Docs directory does not exist: %s", docs_dir)
        return all_docs, md_file_count, frontmatter_count, skipped_count

    md_paths = sorted(
        p for p in docs_dir.rglob("*") if p.suffix.lower() == ".md" and p.is_file()
    )

    for md_path in md_paths:
        md_file_count += 1
        doc, skipped = _extract_doc(md_path, docs_dir)
        skipped_count += skipped
        if doc is not None:
            frontmatter_count += 1
            all_docs.append(doc)

    return all_docs, md_file_count, frontmatter_count, skipped_count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point: parse CLI args, collect documents, write JSON output."""
    project_root = Path.cwd()

    parser = argparse.ArgumentParser(
        description="Extract deliverable docs from docs/ and write them as a flat JSON array.",
    )
    parser.add_argument(
        "--docs-dir",
        type=Path,
        default=project_root / "docs",
        help="Root of the docs tree (default: ./docs/ relative to cwd)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Write output here instead of stdout. When batching, this becomes "
            "the base path; batches are written as <stem>_batch_001<suffix>, "
            "<stem>_batch_002<suffix>, etc."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print a human-readable summary to stderr and exit without writing JSON.",
    )
    args = parser.parse_args()

    # Collect documents.
    all_docs, md_file_count, frontmatter_count, skipped_count = _collect_all_docs(
        args.docs_dir
    )

    # Derive display-friendly path for scan line.
    try:
        docs_display = str(args.docs_dir.relative_to(project_root)) + "/"
    except ValueError:
        docs_display = str(args.docs_dir)

    if args.dry_run:
        batch_count = math.ceil(len(all_docs) / BATCH_SIZE) if all_docs else 0
        print("Dry run — no JSON will be written.", file=sys.stderr)
        print(
            f"Scanned: {docs_display} "
            f"({md_file_count} .md files found, {frontmatter_count} with frontmatter, "
            f"{skipped_count} skipped)",
            file=sys.stderr,
        )
        print(f"Total documents: {frontmatter_count}", file=sys.stderr)
        print(f"Batches: {batch_count} (max {BATCH_SIZE} per batch)", file=sys.stderr)

        # Build breakdowns from tags on each doc.
        tier_counts: dict[str, int] = {}
        type_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        for doc in all_docs:
            for tag in doc["tags"]:
                if tag.startswith("sdlc:tier:"):
                    key = tag[len("sdlc:tier:"):]
                    tier_counts[key] = tier_counts.get(key, 0) + 1
                elif tag.startswith("sdlc:type:"):
                    key = tag[len("sdlc:type:"):]
                    type_counts[key] = type_counts.get(key, 0) + 1
                elif tag.startswith("sdlc:status:"):
                    key = tag[len("sdlc:status:"):]
                    status_counts[key] = status_counts.get(key, 0) + 1

        if tier_counts:
            print(file=sys.stderr)
            print("By tier:", file=sys.stderr)
            for tier, count in sorted(tier_counts.items()):
                print(f"  {tier}: {count}", file=sys.stderr)

        if type_counts:
            print(file=sys.stderr)
            print("By type:", file=sys.stderr)
            max_type_len = max(len(t) for t in type_counts)
            for doc_type, count in sorted(type_counts.items()):
                print(f"  {doc_type:<{max_type_len}}: {count}", file=sys.stderr)

        if status_counts:
            print(file=sys.stderr)
            print("By status:", file=sys.stderr)
            max_status_len = max(len(s) for s in status_counts)
            for status, count in sorted(status_counts.items()):
                print(f"  {status:<{max_status_len}}: {count}", file=sys.stderr)

        print(file=sys.stderr)
        print("Sample titles (first 10):", file=sys.stderr)
        for i, doc in enumerate(all_docs[:10], start=1):
            print(f"  {i}. {doc['title']}", file=sys.stderr)
        remaining = len(all_docs) - 10
        if remaining > 0:
            print(f"  ... and {remaining} more", file=sys.stderr)
        return

    if not all_docs:
        print("No documents found — nothing to write.", file=sys.stderr)
        return

    # Split into batches.
    batches: list[list[dict[str, Any]]] = [
        all_docs[i : i + BATCH_SIZE]
        for i in range(0, len(all_docs), BATCH_SIZE)
    ]

    if args.output is not None:
        if len(all_docs) <= BATCH_SIZE:
            args.output.write_text(json.dumps(batches[0], indent=2), encoding="utf-8")
        else:
            base = args.output.with_suffix("")
            suffix = args.output.suffix
            batch_paths: list[str] = []
            for idx, batch in enumerate(batches, start=1):
                batch_path = Path(f"{base}_batch_{idx:03d}{suffix}")
                batch_path.write_text(json.dumps(batch, indent=2), encoding="utf-8")
                batch_paths.append(batch_path.name)
            print(
                f"Written {len(batches)} batches: {' '.join(batch_paths)}",
                file=sys.stderr,
            )
    else:
        if len(all_docs) > BATCH_SIZE:
            print(
                f"WARNING: output exceeds {BATCH_SIZE} docs — writing {len(batches)} "
                f"batches to stdout, separated by newlines. "
                f"Pipe each separately to document_ingest_batch.",
                file=sys.stderr,
            )
        for batch in batches:
            sys.stdout.write(json.dumps(batch, indent=2))
            sys.stdout.write("\n")


if __name__ == "__main__":
    main()
