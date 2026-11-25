#!/usr/bin/env python3
"""Gate 3 of ``/sdlc-port``: what a port may do given the manifest and the workspace.

The skill gathers facts and follows this script's decision; the rules live here.

Usage:
    python decide_port_gate.py --facts facts.json      # "-" reads stdin

``facts`` is ``{"manifest": {...}, "observed": {...}}``. Manifest keys may be absent;
``observed`` must be complete (see Output) whenever search_ok is true.

    manifest: port_in_progress, ported_at, neuroloom_backend, adapter_names_plugin,
              knowledge_seed_in_progress, knowledge_id_scheme, workspace_id, knowledge_seed_version,
              source_version, source_version_sha
    observed: search_ok (bool), index_ok (bool: every memory_get_index/memory_get_detail
              lookup succeeded), workspace_id, sentinel, sentinel_label, sdlc_rows,
              current_sdlc_version
              (``sentinel`` and ``sdlc_rows`` come from exact-tag lookups; ``sdlc_rows``
              is true when any row tagged sdlc:seed, sdlc:knowledge or sdlc:discipline
              exists)

The seed's label is ``source_version`` when set and not "unknown", else the first seven
characters of ``source_version_sha``, else ``current_sdlc_version`` (a fallback, which
the migrated-since-port check ignores). Labels compare with a leading ``v`` ignored.

Decision order:
    0  search failed                                        stop
    2  an initialized project (no ported_at, and neuroloom_backend, the adapter naming
       the plugin, or knowledge_seed_in_progress); checked before case 1   stop. By what
       the manifest shows: neuroloom_backend without knowledge_id_scheme is an initialize
       from before 0.7.0 (needs a conversion this release lacks); knowledge_seed_in_progress
       or an adapter block without neuroloom_backend is an unfinished initialize (finish
       it with initialize's own recovery); anything else is a finished initialize.
    1  a stopped port (port_in_progress, no ported_at, no neuroloom_backend)
         no manifest workspace_id -> stop; a different workspace -> stop;
         the same workspace -> continue_fresh
    3  a re-port (ported_at): stop unless knowledge_id_scheme is 2, the manifest names
       neuroloom_backend is true (ported_at without it means a hand edit), the manifest
       names the observed workspace and a sentinel exists, the seed label (when not a
       fallback) matches knowledge_seed_version, and the sentinel's label matches
       knowledge_seed_version; otherwise ask
    4  none of the port keys but a sentinel or sdlc rows      stop (three possibilities)
    5  otherwise                                              fresh

Output (stdout, JSON): ``{"case", "action", "reason", "message", "recovery"}``; case 4 also
carries ``label_matches``. ``action`` is stop, continue_fresh, ask or fresh. Exit 0 on a
decision, 2 on unreadable facts, a manifest flag (port_in_progress, neuroloom_backend,
knowledge_seed_in_progress) that is present but not a JSON boolean, a non-bool search_ok, or (search_ok true) a missing
observed.workspace_id, observed.sentinel or observed.sdlc_rows (booleans), or an index_ok
that is not true: a failed lookup must be re-gathered, never recorded as "no row".
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _strip_v(label: Any) -> str | None:
    if label is None or label == "":
        return None
    text = str(label)
    return text.removeprefix("v")


def _label(manifest: dict[str, Any], observed: dict[str, Any]) -> tuple[str | None, bool]:
    """``(label, is_fallback)`` for the seed this manifest describes."""
    version = manifest.get("source_version")
    if version and version != "unknown":
        return str(version), False
    sha = manifest.get("source_version_sha")
    if sha:
        return str(sha)[:7], False
    return observed.get("current_sdlc_version"), True


def _out(case: int, action: str, reason: str, message: str, recovery: str, **extra: Any) -> dict[str, Any]:
    return {"case": case, "action": action, "reason": reason, "message": message,
            "recovery": recovery, **extra}


class FactsError(ValueError):
    """The facts are incomplete or mistyped; the CLI turns this into exit 2."""


def _require_observed(o: dict[str, Any]) -> bool:
    """Validate ``observed`` and return ``search_ok``.

    ``search_ok`` must be a real bool. When it is true the other lookups must be
    reported too: a missing key would read as "nothing there" and let a port write
    over another workspace, so it is an error, never a default.
    """
    search_ok = o.get("search_ok")
    if not isinstance(search_ok, bool):
        raise FactsError(
            f"observed.search_ok must be a JSON bool (true or false), got {search_ok!r}"
        )
    if not search_ok:
        return False
    problems = []
    if o.get("index_ok") is not True:
        problems.append(
            "observed.index_ok is not true: a failed lookup must be re-gathered, never "
            'recorded as "no row"'
        )
    missing = [k for k in ("sentinel", "sdlc_rows") if not isinstance(o.get(k), bool)]
    if not o.get("workspace_id"):
        missing.insert(0, "workspace_id")
    if missing:
        problems.append(
            "missing or invalid: " + ", ".join(f"observed.{k}" for k in missing)
        )
    if problems:
        raise FactsError(
            "observed facts incomplete although search_ok is true; " + "; ".join(problems)
        )
    return True


_MANIFEST_BOOLS = ("port_in_progress", "neuroloom_backend", "knowledge_seed_in_progress")


def _require_manifest_bools(m: dict[str, Any]) -> None:
    """Manifest flags must be JSON booleans when present: ``"false"`` is truthy."""
    bad = [k for k in _MANIFEST_BOOLS if k in m and not isinstance(m[k], bool)]
    if bad:
        raise FactsError(
            "manifest flag(s) must be JSON booleans when present: "
            + ", ".join(f"manifest.{k}={m[k]!r}" for k in bad)
        )


def decide(facts: dict[str, Any]) -> dict[str, Any]:
    """Apply Gate 3 to ``facts`` and return the decision.

    Raises ``ValueError`` when ``search_ok`` is not a bool, or is true while
    ``observed`` lacks ``index_ok: true``, the workspace id or the two boolean lookups.
    """
    m: dict[str, Any] = facts.get("manifest") or {}
    o: dict[str, Any] = facts.get("observed") or {}

    if not _require_observed(o):
        return _out(
            0, "stop", "search_failed",
            "The workspace could not be searched, so nothing can be said about what it holds.",
            "Fix the Neuroloom connection (token, backend URL), then run /sdlc-port again.",
        )

    _require_manifest_bools(m)

    ported_at = m.get("ported_at")
    backend = m.get("neuroloom_backend")

    adapter = m.get("adapter_names_plugin")
    if not ported_at and (backend or adapter or m.get("knowledge_seed_in_progress")):
        if m.get("knowledge_seed_in_progress") or (adapter and not backend):
            return _out(
                2, "stop", "unfinished_initialize",
                "An initialize was started here and did not finish (the manifest still "
                "shows its seed in progress, or names the plugin without a Neuroloom "
                "backend).",
                "Finish it with initialize's own recovery in references/adapter-lifecycle.md "
                "§ Halts and their recoveries. Do not port it: the two use different ids.",
            )
        if backend and not m.get("knowledge_id_scheme"):
            return _out(
                2, "stop", "pre_0_7_0_initialize",
                "This project was set up by an initialize from before 0.7.0 (it has a "
                "Neuroloom backend but no knowledge_id_scheme) and has never been ported.",
                "This workspace needs a one-time conversion that this release does not do. "
                "Do not port or migrate it until one exists.",
            )
        return _out(
            2, "stop", "initialized_project",
            "This project was set up by initialize and its seed finished. There is no "
            "file-mode install to port.",
            "Nothing to port. Its knowledge is already in the workspace.",
        )

    seen_workspace = o.get("workspace_id")
    recorded = m.get("workspace_id")

    if m.get("port_in_progress") and not ported_at and not backend:
        if not recorded:
            return _out(
                1, "stop", "no_workspace_id",
                "A port was started here but the manifest does not record which workspace "
                "it wrote to, so it cannot be continued safely.",
                f"If the earlier port wrote to workspace {seen_workspace!r}, add "
                '"workspace_id" with that id to the manifest and run /sdlc-port again.',
            )
        if recorded != seen_workspace:
            return _out(
                1, "stop", "different_workspace",
                f"A stopped port recorded workspace {recorded!r}, but this session reaches "
                f"workspace {seen_workspace!r}.",
                "Point the API key at the workspace the port started in. If that port was "
                "abandoned, remove port_in_progress and workspace_id from the manifest.",
            )
        return _out(
            1, "continue_fresh", "same_workspace",
            "A stopped port is resumed in the same workspace; the seed is idempotent.",
            "Run the port again from the start.",
        )

    label, fallback = _label(m, o)

    if ported_at:
        seed = _strip_v(m.get("knowledge_seed_version"))
        if m.get("knowledge_id_scheme") != 2:
            return _out(
                3, "stop", "pre_0_7_0_port",
                "This project was ported by a version before 0.7.0 (no knowledge_id_scheme 2).",
                "This workspace needs a one-time conversion that this release does not do. "
                "Do not port or migrate it until one exists.",
            )
        if not backend:
            return _out(
                3, "stop", "incomplete_port_record",
                "the manifest records ported_at without neuroloom_backend, but a port "
                "writes both together",
                "the manifest was edited; if this project was ported, put "
                "\"neuroloom_backend\": true back and run the port again",
            )
        if not recorded:
            return _out(
                3, "stop", "no_workspace_id",
                "The manifest records a port but not the workspace it wrote to.",
                f"Add workspace_id {seen_workspace!r} to the manifest if that is the one.",
            )
        if recorded != seen_workspace:
            return _out(
                3, "stop", "different_workspace",
                f"The earlier port wrote to workspace {recorded!r}; this session reaches "
                f"workspace {seen_workspace!r}.",
                "Point the session at the recorded workspace.",
            )
        if not o.get("sentinel"):
            return _out(
                3, "stop", "no_sentinel",
                "The workspace has no seed sentinel, so the earlier port's rows cannot be "
                "accounted for.",
                "Check which workspace this is and whether its rows were deleted; do not "
                "re-port over unaccounted rows.",
            )
        if seed is None:
            return _out(
                3, "stop", "no_seed_version",
                "the manifest records no knowledge_seed_version, so the sentinel can't be "
                "checked against it",
                "re-port is refused; a port that finished always records it, so the manifest "
                "was edited",
            )
        if not fallback and _strip_v(label) != seed:
            return _out(
                3, "stop", "label_differs",
                f"The manifest's seed label {label!r} differs from the recorded "
                f"knowledge_seed_version {m.get('knowledge_seed_version')!r}: the project "
                "moved to another upstream version since the port.",
                "Use /sdlc-migrate; a re-port would re-seed an older version over it.",
            )
        if _strip_v(o.get("sentinel_label")) != seed:
            return _out(
                3, "stop", "sentinel_moved",
                f"The workspace's sentinel is at {o.get('sentinel_label')!r} but the port "
                f"recorded {m.get('knowledge_seed_version')!r}: something seeded it since "
                "(a migration's knowledge-update).",
                "Use /sdlc-migrate; a re-port would overwrite what the update changed.",
            )
        return _out(
            3, "ask", "reported",
            "This project was ported before and the workspace still matches the port.",
            "Ask CD whether to re-port; a re-port re-sends the knowledge files and "
            "parking-lot entries, never a discipline's framework or project data.",
        )

    if o.get("sentinel") or o.get("sdlc_rows"):
        # A match against the latest release (the fallback label) proves nothing about the
        # project's own label.
        matches = not fallback and bool(label) and _strip_v(o.get("sentinel_label")) == _strip_v(label)
        return _out(
            4, "stop", "unaccounted_rows",
            "The workspace already holds SDLC records and the manifest has none of the port "
            "keys. They are this project's from before 0.7.0, another project's, or this "
            "project's own stopped port whose manifest change was discarded; their ids "
            f"can't tell which. Observed workspace: {seen_workspace!r}; "
            f"label_matches={'true' if matches else 'false'}.",
            "Records from before 0.7.0 need a one-time conversion this release doesn't do. "
            "Another project's: port into a workspace of its own. A lost marker: only when "
            "label_matches is true and CD confirms, put back port_in_progress and "
            "workspace_id (this workspace's id), then re-run.",
            label_matches=matches,
        )

    return _out(
        5, "fresh", "nothing_there",
        "Nothing has been ported to this workspace.",
        "Run the port.",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Decide what /sdlc-port Gate 3 allows.")
    parser.add_argument("--facts", required=True, help="JSON facts file, or - for stdin.")
    args = parser.parse_args()
    try:
        raw = sys.stdin.read() if args.facts == "-" else Path(args.facts).read_text(encoding="utf-8")
        facts = json.loads(raw)
        if not isinstance(facts, dict):
            raise TypeError("facts must be a JSON object")
    except (OSError, ValueError, TypeError) as exc:
        print(f"ERROR: cannot read facts: {exc}", file=sys.stderr)
        sys.exit(2)
    try:
        decision = decide(facts)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
    print(json.dumps(decision))


if __name__ == "__main__":
    main()
