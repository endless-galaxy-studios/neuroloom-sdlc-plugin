"""
SDLC session-start hook (Python port of hooks/session-start.sh).

Checks the z-sdlc framework version against the workspace's seeded version
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

try:
    import pyhooks.config  # type: ignore[import-untyped]
except Exception as _exc:
    # A broken or empty base plugin must not surface a traceback under CI mode.
    from sdlc_pyhooks import parse_mode

    if not parse_mode(os.environ.get("NEUROLOOM_MODE")).ci:
        raise
    # Exception TYPE only: the message may carry paths or attacker-influenced text.
    print(
        f"[neuroloom-sdlc] CI mode: base plugin import failed "
        f"({type(_exc).__name__}); hooks do nothing",
        file=sys.stderr,
    )
    raise SystemExit(0) from None

from sdlc_pyhooks import mode_state

_CI_VERSION_CAP = 64

_CI_NOT_SEEDED = (
    "[Neuroloom SDLC] This workspace has no SDLC knowledge seeded. "
    "No action is taken in CI mode."
)


def _ci_safe_version(value: str) -> str:
    """Escape control characters and cap the length so the line stays one line.

    Versions come from API responses and reach the agent's context under CI mode.
    """
    return json.dumps(value)[1:-1][:_CI_VERSION_CAP]


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


_PIN_PATH_CAP = 300


def _pinned_plugin_root_warning(project_dir: Path) -> str | None:
    """Return a warning when the project's manifest pins adapter.plugin_root elsewhere.

    z-sdlc releases before contract 0025 load the adapter's handlers from that path, so a
    pin left from an earlier install runs that version's handlers, not this one's.
    """
    try:
        manifest = json.loads((project_dir / ".sdlc-manifest.json").read_text(encoding="utf-8"))
        root = manifest["adapter"]["plugin_root"]
        if not isinstance(root, str) or not root:
            return None
        pinned = Path(root).expanduser()
        if not pinned.is_absolute():
            # A relative pin is a copy vendored in the project, which z-sdlc keeps supporting.
            return None
        if pinned.resolve() == Path(__file__).resolve().parent.parent:
            return None
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        return None
    return (
        f"Neuroloom SDLC: .sdlc-manifest.json pins adapter.plugin_root to {root[:_PIN_PATH_CAP]}."
        " z-sdlc releases before contract 0025 run the adapter handlers found there, which may be"
        " an older install of this plugin. Remove adapter.plugin_root from the manifest"
        " before running /sdlc-migrate."
    )


def main() -> None:
    # Step 0: decide the mode before load(). Skew (CI requested, base cannot
    # report it) does nothing at all: no db, no API.
    state = mode_state()
    if state == "skew":
        return

    # Claude Code sets CLAUDE_PROJECT_DIR for hooks; without it there is no project
    # root to read, and these hooks never fall back to the process's directory.
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if state != "ci" and project_dir:
        warning = _pinned_plugin_root_warning(Path(project_dir))
        if warning:
            print(warning)

    # Step 1: Load config. Empty api_key means unconfigured — silent exit.
    config = pyhooks.config.load()
    if not config.api_key:
        return

    ci = state == "ci"
    if ci and not getattr(config, "ci_mode", False):
        return  # the loaded Config disagrees with the environment: skew

    _debug(f"Config loaded. api_base={config.api_base}")

    headers: dict[str, str] = {"Authorization": f"Token {config.api_key}"}

    # Step 2: Get latest z-sdlc version from the Neuroloom version proxy.
    version_url = f"{config.api_base}/api/v1/sdlc/cc-sdlc-version"
    _debug(f"Checking z-sdlc version via proxy: {version_url}")

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

    _debug(f"Latest z-sdlc version: {latest_version}")

    # Step 3: List for the sentinel memory that marks workspace initialization.
    # Uses GET /memories/?tags=... (exact AND-tag semantics, no relevance
    # gating, no query-embedding call) instead of POST /memories/search,
    # which requires a non-empty `query` (it never matches on tags alone —
    # pre-D176-#3, an empty query silently returned zero results; after
    # D176 #3's API-side fix, a missing/blank query 422s instead).
    sentinel_url = f"{config.api_base}/api/v1/memories/?tags=sdlc:sentinel&limit=1"

    _debug("Checking for workspace sentinel...")

    sentinel_result = _get_json(sentinel_url, headers, timeout=10.0)
    if sentinel_result is None:
        return
    sentinel_status, sentinel_body = sentinel_result
    if sentinel_status != 200:
        _debug(f"Sentinel list returned {sentinel_status}, skipping")
        return

    _debug(f"Sentinel response body: {sentinel_body!r}")

    try:
        results: object = json.loads(sentinel_body)
    except Exception:
        return

    # Step 4: If no sentinel memory, the workspace is uninitialised.
    # list_memories returns a bare JSON array, not {"results": [...]}.
    if not isinstance(results, list) or len(results) == 0:
        if ci:
            print(_CI_NOT_SEEDED)
            return
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

    # Step 6: Notify if there is a newer version available. The API strips the
    # tag's leading "v" (routers/sdlc.py) while the knowledge handlers label
    # seeds with the git tag, so compare without it.
    if workspace_version and workspace_version.removeprefix("v") != latest_version.removeprefix("v"):
        if ci:
            print(
                "[Neuroloom SDLC] Workspace SDLC knowledge is at "
                f"{_ci_safe_version(workspace_version)}; "
                f"latest is {_ci_safe_version(latest_version)}. "
                "No action is taken in CI mode."
            )
            return
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
