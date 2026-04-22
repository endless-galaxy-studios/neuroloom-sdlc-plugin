"""
SDLC session-start hook (Python port of hooks/session-start.sh).

Checks the cc-sdlc framework version against the workspace's seeded version
and prints a notification if an update is available, or if the workspace has
not yet been initialized.

This module is invoked as a script by the hook launcher. It never raises —
any failure is silently swallowed so that Claude Code is never interrupted.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pyhooks.config  # type: ignore[import-untyped]
import pyhooks.http  # type: ignore[import-untyped]


def _debug(msg: str) -> None:
    """Print a debug message to stderr if NEUROLOOM_DEBUG=true."""
    if os.environ.get("NEUROLOOM_DEBUG") == "true":
        print(f"[neuroloom-sdlc] {msg}", file=sys.stderr)


def _plugin_version() -> str:
    """Read plugin version from .claude-plugin/plugin.json. Falls back to 'unknown'."""
    try:
        manifest = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
        return json.loads(manifest.read_text(encoding="utf-8")).get("version", "unknown")
    except Exception:
        return "unknown"


_USER_AGENT = f"neuroloom-sdlc-plugin/{_plugin_version()}"


def _get_json(
    url: str,
    headers: dict[str, str],
    timeout: float,
) -> tuple[int, bytes] | None:
    """GET url, returning (status, body) or None on network failure.

    No Content-Type header — GET requests carry no body.
    """
    req = urllib.request.Request(
        url,
        headers={**headers, "User-Agent": _USER_AGENT},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status), resp.read()
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
        except Exception:
            body = b""
        return exc.code, body
    except Exception:
        return None


def main() -> None:
    # Step 1: Load config. Empty api_key means unconfigured — silent exit.
    config = pyhooks.config.load()
    if not config.api_key:
        return

    _debug(f"Config loaded. api_base={config.api_base}")

    headers: dict[str, str] = {"Authorization": f"Token {config.api_key}"}

    # Step 2: Get latest cc-sdlc version from the Neuroloom version proxy.
    version_url = f"{config.api_base}/api/v1/sdlc/cc-sdlc-version"
    _debug(f"Checking cc-sdlc version via proxy: {version_url}")

    version_result = _get_json(version_url, headers, timeout=10.0)
    if version_result is None:
        return
    version_status, version_body = version_result
    if version_status != 200:
        _debug(f"Version proxy returned {version_status}, skipping")
        return

    _debug(f"Version response body: {version_body!r}")

    try:
        version_data: dict[str, object] = json.loads(version_body)
    except Exception:
        return

    latest_version = version_data.get("version")
    if not latest_version or not isinstance(latest_version, str):
        return

    _debug(f"Latest cc-sdlc version: {latest_version}")

    # Step 3: Search for the sentinel memory that marks workspace initialization.
    sentinel_url = f"{config.api_base}/api/v1/memories/search"
    sentinel_payload = json.dumps({"tags": ["sdlc:sentinel"], "limit": 1}).encode("utf-8")

    _debug("Checking for workspace sentinel...")

    sentinel_result = pyhooks.http.post_json(sentinel_url, headers, sentinel_payload, timeout=10.0)
    if sentinel_result is None:
        return
    sentinel_status, sentinel_body = sentinel_result
    if sentinel_status != 200:
        _debug(f"Sentinel search returned {sentinel_status}, skipping")
        return

    _debug(f"Sentinel response body: {sentinel_body!r}")

    try:
        sentinel_data: dict[str, object] = json.loads(sentinel_body)
    except Exception:
        return

    # Step 4: If no sentinel memory, the workspace is uninitialised.
    results = sentinel_data.get("results")
    if not isinstance(results, list) or len(results) == 0:
        print(
            "Neuroloom SDLC: workspace not initialized."
            " Run /sdlc-initialize to seed SDLC knowledge."
        )
        return

    # Step 5: Extract workspace version from the sentinel's tags.
    # Tags are a flat list of strings; the seed version tag has the form
    # "sdlc:seed-version:<version>".
    workspace_version = ""
    first_result = results[0]
    if isinstance(first_result, dict):
        tags = first_result.get("tags")
        if isinstance(tags, list):
            prefix = "sdlc:seed-version:"
            for tag in tags:
                if isinstance(tag, str) and tag.startswith(prefix):
                    workspace_version = tag[len(prefix):]
                    break

    _debug(f"Workspace version: {workspace_version or '<none>'}")

    # Step 6: Notify if there is a newer version available.
    if workspace_version and workspace_version != latest_version:
        print(
            f"Neuroloom SDLC: update available"
            f" ({workspace_version} -> {latest_version})."
            " Run /sdlc-migrate to update."
        )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
