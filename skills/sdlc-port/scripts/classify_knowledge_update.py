#!/usr/bin/env python3
"""Decides, id by id, what a ``knowledge-update`` may send to a workspace, and which
entry to send alone when nothing else changed.

The extractor's delta mode writes ``<stem>.delta.json`` (see
``extract_sdlc_knowledge.py``). The handler fetches what the workspace holds for
every new and changed id, and for the ids of the delta's ``probe_entries``, and
writes it as ``workspace.json``: ``{"<id>": {"title": ..., "content": ...,
"tags": [...]} | null}``. ``content`` is the stored narrative.

Per new and changed id, comparing after normalising only line endings (CRLF to LF) and
trailing whitespace at the end of the whole text (internal whitespace and indentation
stay significant):

    send                a changed id whose workspace text equals the baseline text,
                        or a new id the workspace does not hold
    already_current     the workspace already equals the target text
    conflict            a changed id whose workspace text differs from both, or a
                        new id the workspace holds with different text; each carries
                        the baseline, target and workspace texts. Also a changed id
                        whose workspace text equals the baseline but whose title is
                        neither release's: the server refreshes the title with the
                        text, so sending would erase the project's title. That row
                        also carries the three titles.
    removed_by_project  a changed id the workspace does not hold
    protected           a send or already_current candidate whose row carries
                        ``sdlc:project-specific``: the server never updates such a
                        row, so sending it would silently do nothing

``noop_ids.txt`` names the first ``probe_entries`` id the server will answer
``unchanged`` for, so the handler can send that entry alone (``--only-ids``) to
advance the workspace's version marker. The server's rule
(``DocumentIngestionService.seed_workspace``): it compares
sha256(entry content) with sha256(stored narrative), nothing else. The title is not
part of the hash and no whitespace is normalised, so the match here is exact string
equality of the content, not the normalised comparison above.

Usage:
    python classify_knowledge_update.py --delta seed.delta.json \\
        --workspace workspace.json --output-dir DIR

Writes ``DIR/send_ids.txt`` and ``DIR/noop_ids.txt`` (one id per line; empty when
none) and ``DIR/report.json`` (``{"send", "already_current", "conflict",
"removed_by_project", "protected"}``), prints the three paths to stdout and a count
line to stderr. Exit status: 0 on success; 2 when an input is unreadable or
malformed (the workspace lacks an id the delta lists, a value is neither null nor a
{"title", "content", "tags"} object, or the delta lacks the target text of a new id).
Nothing is written then.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_PROJECT_SPECIFIC = "sdlc:project-specific"


def _normalise(text: str) -> str:
    """Line endings to ``\\n`` and no trailing whitespace at the end of the whole text.

    Internal whitespace and indentation stay significant: a re-indented list is a
    different text.
    """
    return text.replace("\r\n", "\n").rstrip()


def _fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(2)


def _load(path: Path, what: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _fail(f"cannot read {what} {path}: {exc}")


def _row(workspace: dict[str, Any], kid: str) -> dict[str, Any] | None:
    """The workspace row for ``kid``: ``None`` when absent, else a validated object."""
    if kid not in workspace:
        _fail(f"workspace.json has no entry for id {kid!r} (use null for an id it lacks)")
    value = workspace[kid]
    if value is None:
        return None
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("title"), str)
        or not isinstance(value.get("content"), str)
        or not isinstance(value.get("tags"), list)
        or not all(isinstance(t, str) for t in value["tags"])
    ):
        _fail(
            f'workspace.json value for id {kid!r} must be null or {{"title", "content": '
            f'str, "tags": [str]}}, got {json.dumps(value)[:80]}'
        )
    return value  # type: ignore[no-any-return]


def _retitled(item: dict[str, str], row: dict[str, Any]) -> bool:
    """Whether the project gave a changed entry a title of its own (neither release's).

    A delta from before titles were recorded carries none, and keeps the body-only rule.
    """
    titles = (item.get("baseline_title"), item.get("target_title"))
    stored = row["title"]
    if not all(isinstance(t, str) for t in titles):
        return False
    return _normalise(stored) not in {_normalise(t) for t in titles}  # type: ignore[arg-type]


def classify(delta: dict[str, Any], workspace: dict[str, Any]) -> dict[str, list[Any]]:
    """Sort the delta's new and changed ids into the decision lists."""
    new_ids: list[str] = list(delta.get("new", []))
    changed: list[dict[str, str]] = list(delta.get("changed", []))
    new_content: dict[str, str] = delta.get("new_content") or {}

    no_text = [i for i in new_ids if i not in new_content]
    if no_text:
        _fail(f"the delta has no new_content for new id(s): {', '.join(no_text[:10])}")

    report: dict[str, list[Any]] = {
        "send": [], "already_current": [], "conflict": [], "removed_by_project": [],
        "protected": [],
    }

    def settle(kid: str, bucket: str, row: dict[str, Any]) -> None:
        protected = _PROJECT_SPECIFIC in row["tags"]
        report["protected" if protected else bucket].append(kid)

    for kid in new_ids:
        row, target = _row(workspace, kid), new_content[kid]
        if row is None:
            report["send"].append(kid)
        elif _normalise(row["content"]) == _normalise(target):
            settle(kid, "already_current", row)
        else:
            report["conflict"].append(
                {"id": kid, "baseline": None, "target": target, "workspace": row["content"]}
            )
    for item in changed:
        kid, baseline, target = item["id"], item["baseline_content"], item["target_content"]
        row = _row(workspace, kid)
        if row is None:
            report["removed_by_project"].append(kid)
        elif (
            _normalise(row["content"]) == _normalise(baseline)
            and _PROJECT_SPECIFIC not in row["tags"]
            and _retitled(item, row)
        ):
            # The server refreshes the title with the narrative, so sending would erase the edit.
            report["conflict"].append({
                "id": kid, "baseline": baseline, "target": target, "workspace": row["content"],
                "baseline_title": item["baseline_title"], "target_title": item["target_title"],
                "workspace_title": row["title"],
            })
        elif _normalise(row["content"]) == _normalise(baseline):
            settle(kid, "send", row)
        elif _normalise(row["content"]) == _normalise(target):
            settle(kid, "already_current", row)
        else:
            report["conflict"].append(
                {"id": kid, "baseline": baseline, "target": target, "workspace": row["content"]}
            )
    return report


def pick_noop(delta: dict[str, Any], workspace: dict[str, Any]) -> list[str]:
    """The first probe entry whose stored content equals the entry's, byte for byte.

    A candidate the workspace file does not mention was not looked up and is skipped;
    a present value that is malformed still exits 2.
    """
    for entry in delta.get("probe_entries") or []:
        if entry["knowledge_id"] not in workspace:
            continue  # the handler may look up only some candidates; the rest are skipped
        row = _row(workspace, entry["knowledge_id"])
        if row is not None and row["content"] == entry["content"]:
            return [entry["knowledge_id"]]
    return []


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Classify a knowledge-update delta against what the workspace holds."
    )
    parser.add_argument("--delta", type=Path, required=True, help="The extractor's .delta.json.")
    parser.add_argument(
        "--workspace",
        type=Path,
        required=True,
        help=(
            '{"<id>": {"title", "content", "tags"} | null} for every new and changed id '
            "and every probe_entries id."
        ),
    )
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="Directory for send_ids.txt, noop_ids.txt and report.json."
    )
    args = parser.parse_args()

    delta = _load(args.delta, "delta")
    workspace = _load(args.workspace, "workspace")
    if not isinstance(delta, dict) or not isinstance(workspace, dict):
        _fail("both inputs must be JSON objects")
    try:
        report = classify(delta, workspace)
        noop = pick_noop(delta, workspace)
    except (KeyError, TypeError, AttributeError) as exc:
        _fail(f"the delta file is malformed ({type(exc).__name__}: {exc})")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    send_path = args.output_dir / "send_ids.txt"
    noop_path = args.output_dir / "noop_ids.txt"
    report_path = args.output_dir / "report.json"
    send_path.write_text("".join(f"{i}\n" for i in report["send"]), encoding="utf-8")
    noop_path.write_text("".join(f"{i}\n" for i in noop), encoding="utf-8")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(send_path)
    print(noop_path)
    print(report_path)
    print(
        "send {send} | already current {already_current} | conflict {conflict} | "
        "removed by project {removed_by_project} | protected {protected}".format(
            **{k: len(v) for k, v in report.items()}
        )
        + f" | noop {noop[0] if noop else 'none'}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
