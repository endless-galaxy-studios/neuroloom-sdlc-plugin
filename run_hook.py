"""
Platform-agnostic launcher for neuroloom-sdlc-plugin hook modules.

Usage:
    python run_hook.py <module> [args...]

Locates the base plugin's .venv Python interpreter and re-execs the specified
module with all remaining arguments forwarded. On POSIX the current process is
replaced via os.execve; on Windows a subprocess is spawned and its exit code is
forwarded.

PYTHONPATH difference from the base plugin:
    Two roots are injected — SDLC_ROOT first (for `import sdlc_pyhooks.*`),
    then BASE_ROOT (for `import pyhooks.config`, `import pyhooks.http`). The
    SDLC plugin has no venv of its own; it reuses the base plugin's virtualenv.

Base plugin root resolution order:
    1. NEUROLOOM_CLAUDE_PLUGIN_ROOT environment variable (override)
    2. Sibling directory: <this file's parent>/../neuroloom-claude-plugin

If the base plugin root or its venv cannot be found the launcher prints a
diagnostic to stderr and exits 0 so that Claude Code hook failures never block
the user's session.
"""

import os
import sys
from pathlib import Path

SDLC_ROOT = Path(__file__).resolve().parent

_env_override = os.environ.get("NEUROLOOM_CLAUDE_PLUGIN_ROOT")
BASE_ROOT = Path(_env_override).resolve() if _env_override else SDLC_ROOT.parent / "neuroloom-claude-plugin"


def find_python() -> Path:
    if sys.platform == "win32":
        return BASE_ROOT / ".venv" / "Scripts" / "python.exe"
    return BASE_ROOT / ".venv" / "bin" / "python"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(0)

    if not BASE_ROOT.exists():
        print(f"[neuroloom-sdlc] Base plugin not found at {BASE_ROOT}", file=sys.stderr)
        sys.exit(0)

    venv_py = find_python()
    if not venv_py.exists():
        print(
            f"[neuroloom-sdlc] Base plugin venv not found at {venv_py}. "
            f"Run: cd neuroloom-claude-plugin && uv sync",
            file=sys.stderr,
        )
        sys.exit(0)

    module = sys.argv[1]
    args = [str(venv_py), "-m", module] + sys.argv[2:]

    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(SDLC_ROOT)
        + os.pathsep
        + str(BASE_ROOT)
        + (os.pathsep + existing if existing else "")
    )

    if sys.platform == "win32":
        import subprocess

        result = subprocess.run(args, env=env)
        sys.exit(result.returncode or 0)
    else:
        try:
            os.execve(str(venv_py), args, env)
        except OSError:
            print(f"[neuroloom-sdlc] Failed to exec {venv_py}", file=sys.stderr)
            sys.exit(0)
