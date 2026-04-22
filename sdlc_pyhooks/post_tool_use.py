"""
SDLC post-tool-use hook (Python port of hooks/post-tool-use.sh).

Watches for Write/Edit tool events that touch SDLC deliverable documents
under ``docs/current_work/**/*.md`` and syncs them to the Neuroloom
documents ingest endpoint. Failed syncs are buffered to the local SQLite
``event_buffer`` table for later retry.

This module is invoked as a script by the hook launcher. It never raises —
any failure is silently swallowed so that Claude Code is never interrupted.

Matcher contract (hooks/hooks.json):
    The PostToolUse matcher is narrowed to ``Write|Edit|MultiEdit|NotebookEdit``
    so the harness only cold-starts Python when a file-modifying tool runs.
    This is a perf optimization that trades forward compatibility for speed:
    if Claude Code adds a new file-writing tool (e.g., StreamingWrite), the
    hook will NOT fire for it and deliverable docs created via that tool
    will not sync until this matcher is updated. Keep this list in sync with
    the PostToolUse matcher in hooks/hooks.json when Claude Code ships new
    file-modifying tool types.
"""

import json
import os
import re
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pyhooks.config  # type: ignore[import-untyped]
import pyhooks.http  # type: ignore[import-untyped]
from pyhooks.db import open_db  # type: ignore[import-untyped]


def _debug(msg: str) -> None:
    """Print a debug message to stderr if NEUROLOOM_DEBUG=true."""
    if os.environ.get("NEUROLOOM_DEBUG") == "true":
        print(f"[neuroloom-sdlc] {msg}", file=sys.stderr)


def main() -> None:
    # Step 1: Read and parse the tool event from stdin.
    try:
        raw = sys.stdin.read()
        event: dict[str, object] = json.loads(raw)
    except Exception:
        return

    # Step 2: Extract file_path from tool_input.path or tool_input.file_path.
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return

    file_path: str = (
        tool_input.get("path")
        or tool_input.get("file_path")
        or ""
    )
    if not isinstance(file_path, str) or not file_path:
        return

    _debug(f"PostToolUse triggered for: {file_path}")

    # Step 3: Fast path — only process docs/current_work/**/*.md
    if not re.search(r"docs/current_work/.*\.md$", file_path):
        _debug("Path does not match docs/current_work/**/*.md — skipping")
        return

    _debug("Path matched SDLC deliverable pattern")

    # Step 4: Load config. Empty api_key means unconfigured — silent exit.
    config = pyhooks.config.load()
    if not config.api_key:
        return

    # Step 5: Read file content. Missing or empty file → skip.
    try:
        content = Path(file_path).read_text(encoding="utf-8")
    except Exception:
        return
    if not content:
        return

    # Step 6: Extract deliverable ID from filename (e.g. d42_foo_spec.md → "42").
    filename = Path(file_path).name
    deliverable_id = ""
    id_match = re.match(r"^d(\d+[a-z]?)_", filename)
    if id_match:
        deliverable_id = id_match.group(1)

    # Step 7: Derive doc type from filename suffix.
    doc_type = ""
    if filename.endswith("_spec.md"):
        doc_type = "spec"
    elif filename.endswith("_plan.md"):
        doc_type = "plan"
    elif filename.endswith("_result.md"):
        doc_type = "result"
    elif filename.endswith("_COMPLETE.md"):
        doc_type = "chronicle"

    _debug(f"Deliverable ID: {deliverable_id or '<none>'}, Doc type: {doc_type or '<none>'}")

    # Step 8: Build tags list.
    tags: list[str] = []
    if deliverable_id:
        tags.append(f"sdlc:deliverable:{deliverable_id}")
    if doc_type:
        tags.append(f"sdlc:doc:{doc_type}")

    # Step 9: Build ingest payload.
    payload_dict = {
        "title": filename,
        "content": content,
        "source_type": "sdlc_deliverable",
        "source_path": file_path,
        "tags": tags,
    }
    payload_bytes = json.dumps(payload_dict).encode("utf-8")

    headers: dict[str, str] = {"Authorization": f"Token {config.api_key}"}
    ingest_url = f"{config.api_base}/api/v1/documents/ingest"

    # Step 10 + 11: Run sync in a background thread; join with a short timeout
    # so we don't block Claude Code longer than ~90 ms.
    def _sync() -> None:
        conn: sqlite3.Connection | None = None
        try:
            _debug(f"Syncing {file_path} to Neuroloom...")
            conn = open_db(config.state_db_path)

            result = pyhooks.http.post_json(ingest_url, headers, payload_bytes, timeout=10.0)

            if result is not None and 200 <= result[0] < 300:
                _debug(f"Sync successful for {file_path}")
                return

            # Network failure or non-2xx: buffer in SQLite for replay
            status_detail = f"HTTP {result[0]}" if result is not None else "network error"
            _debug(f"Sync failed ({status_detail}) for {file_path} — buffering in state DB")

            if conn is not None:
                conn.execute(
                    "INSERT INTO event_buffer (payload, created_at) VALUES (?, ?)",
                    (json.dumps(payload_dict), time.time()),
                )
                conn.commit()
        except Exception:
            pass
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    t = threading.Thread(target=_sync, daemon=False)
    t.start()
    t.join(timeout=0.090)

    # Step 12: Return after the join — hook exits regardless of whether the
    # thread has finished. If it outlives the join, it completes in the
    # background (daemon=False ensures the process waits for it on exit).


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
