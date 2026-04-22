"""
Platform-agnostic launcher for neuroloom-sdlc-plugin hook modules.

Usage:
    python run_hook.py <module> [args...]

Locates the base plugin's Python interpreter and re-execs the specified
module with all remaining arguments forwarded. On POSIX the current process is
replaced via os.execve; on Windows a subprocess is spawned and its exit code is
forwarded.

PYTHONPATH difference from the base plugin:
    Two roots are injected — SDLC_ROOT first (for `import sdlc_pyhooks.*`),
    then BASE_ROOT (for `import pyhooks.config`, `import pyhooks.http`). The
    SDLC plugin has no venv of its own; it reuses the base plugin's virtualenv
    when present. When the base plugin venv is absent, sys.executable is used
    as a fallback so all stdlib-only hooks continue to run.

Base plugin root resolution order:
    1. NEUROLOOM_CLAUDE_PLUGIN_ROOT environment variable (override)
    2. Marketplace cache: ~/.claude/plugins/cache/endless-galaxy-studios/neuroloom/*/
       (hardcoded to the endless-galaxy-studios org per DECISION-A — forks or
       alternate org installs must use NEUROLOOM_CLAUDE_PLUGIN_ROOT to override)
    3. Dev sibling directory: <this file's parent>/../neuroloom-claude-plugin
    4. Not found — prints diagnostic to stderr and exits 0

If the base plugin root cannot be found the launcher prints a diagnostic to
stderr and exits 0 so that Claude Code hook failures never block the user's
session.
"""

import os
import sys
from pathlib import Path

SDLC_ROOT = Path(__file__).resolve().parent

# Resolution constants
# Org is hardcoded per DECISION-A. Forks or alternate org installs must set
# NEUROLOOM_CLAUDE_PLUGIN_ROOT to override — no fork auto-discovery.
_CLAUDE_PLUGIN_CACHE_GLOB = "endless-galaxy-studios/neuroloom/*/"

# The SDLC session-start equivalent module — stderr warning is gated to this
# module so the degraded message fires at most once per session.
_SESSION_START_MODULE = "sdlc_pyhooks.session_start"


def _version_key(p: Path) -> tuple[int, ...]:
    """Return a tuple-of-ints sort key for a semver-named directory."""
    parts = p.name.split(".")
    try:
        return tuple(int(x) for x in parts)
    except ValueError:
        return (0,)  # unparseable versions sort last


def _resolve_base_root() -> tuple[Path | None, str]:
    """Locate the neuroloom-claude-plugin installation directory."""
    # 1. Env override
    env_val = os.environ.get("NEUROLOOM_CLAUDE_PLUGIN_ROOT")
    if env_val:
        p = Path(env_val).resolve()
        if p.exists():
            return p, ""
        return None, f"NEUROLOOM_CLAUDE_PLUGIN_ROOT set to {p!r} but path does not exist"

    # 2. Marketplace cache — hardcoded to endless-galaxy-studios org (DECISION-A)
    # Trust model: the cache base is under Path.home(). Any file reachable by this
    # glob was written by a process already running as the current user. We trust
    # the cache directory to the same degree as the rest of ~/.claude/.
    cache_base = Path.home() / ".claude" / "plugins" / "cache"
    candidates = list(cache_base.glob(_CLAUDE_PLUGIN_CACHE_GLOB))
    valid = sorted(
        (c for c in candidates if (c / "run_hook.py").exists()),
        key=_version_key,
    )
    if valid:
        return valid[-1], ""  # highest semver version

    # 3. Dev sibling
    sibling = SDLC_ROOT.parent / "neuroloom-claude-plugin"
    if sibling.exists():
        return sibling, ""

    # 4. Not found
    return None, (
        "[neuroloom-sdlc] Cannot locate neuroloom-claude-plugin. "
        "Set NEUROLOOM_CLAUDE_PLUGIN_ROOT or reinstall via the Claude Code marketplace."
    )


def _resolve_python(base_root: Path) -> tuple[Path, bool]:
    """Return (interpreter_path, is_degraded)."""
    venv_py = base_root / (
        ".venv/Scripts/python.exe" if sys.platform == "win32" else ".venv/bin/python"
    )
    if venv_py.exists():
        return venv_py, False
    return Path(sys.executable), True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(0)

    base_root, err = _resolve_base_root()
    if base_root is None:
        print(err, file=sys.stderr)
        sys.exit(0)

    py, degraded = _resolve_python(base_root)
    module = sys.argv[1]
    if degraded and module == _SESSION_START_MODULE:
        print(
            f"[neuroloom-sdlc] degraded: base plugin venv not found at "
            f"{base_root / '.venv'} — using system Python",
            file=sys.stderr,
        )

    args = [str(py), "-m", module] + sys.argv[2:]

    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(SDLC_ROOT)
        + os.pathsep + str(base_root)
        + (os.pathsep + existing if existing else "")
    )

    if sys.platform == "win32":
        import subprocess

        result = subprocess.run(args, env=env)
        sys.exit(result.returncode or 0)
    else:
        try:
            os.execve(str(py), args, env)
        except OSError:
            print(f"[neuroloom-sdlc] Failed to exec {py}", file=sys.stderr)
            sys.exit(0)
