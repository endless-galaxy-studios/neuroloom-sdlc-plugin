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

CI mode (NEUROLOOM_MODE parses as CI, same rule as pyhooks.config):
    The base plugin is found ONLY through NEUROLOOM_CLAUDE_PLUGIN_ROOT, which
    must be an absolute path to an existing directory containing a pyhooks/
    package directory (with __init__.py and config.py). The marketplace cache and the
    dev sibling are never consulted. Otherwise one diagnostic goes to stderr and
    the launcher exits 0 (the hooks do nothing). The hook runs under
    sys.executable and no degraded-venv line is printed. This launcher keeps its
    own tiny parser copy and imports nothing from its own package, so a broken
    package can never break it.

Base plugin root resolution order (outside CI mode):
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


# Runs under `python -I -c`: sys.argv[0] is '-c' and sys.argv[1:] is
# [sdlc_root, base_root, module, *hook_args].
# -I makes the child ignore PYTHON* variables (PYTHONPATH included), so the
# PYTHONPATH set below is inert there; the sys.path insert in this bootstrap is
# the real control.
_CI_BOOTSTRAP = (
    "import sys, runpy\n"
    "sdlc, base, mod = sys.argv[1:4]\n"
    "sys.path[:0] = [sdlc, base]\n"
    "sys.argv = [mod] + sys.argv[4:]\n"
    "runpy.run_module(mod, run_name='__main__', alter_sys=True)\n"
)


def _version_key(p: Path) -> tuple[int, ...]:
    """Return a tuple-of-ints sort key for a semver-named directory."""
    parts = p.name.split(".")
    try:
        return tuple(int(x) for x in parts)
    except ValueError:
        return (0,)  # unparseable versions sort last


def _ci_mode() -> bool:
    """True when NEUROLOOM_MODE parses as CI (unset/blank: normal; "ci": CI;
    any other value fails closed into CI). Tiny copy of the shared parse rule."""
    return (os.environ.get("NEUROLOOM_MODE") or "").strip().lower() != ""


def _resolve_base_root() -> tuple[Path | None, str]:
    """Locate the neuroloom-claude-plugin installation directory."""
    if _ci_mode():
        env_val = os.environ.get("NEUROLOOM_CLAUDE_PLUGIN_ROOT")
        diag = (
            "[neuroloom-sdlc] CI mode: NEUROLOOM_CLAUDE_PLUGIN_ROOT must name an "
            "absolute path to a base plugin directory containing pyhooks/ with "
            "config.py; hooks do nothing"
        )
        if not env_val or not os.path.isabs(env_val):
            return None, diag
        p = Path(env_val).resolve()
        pkg = p / "pyhooks"
        if (
            p.is_dir()
            and pkg.is_dir()
            and (pkg / "__init__.py").is_file()
            and (pkg / "config.py").is_file()
        ):
            return p, ""
        return None, diag

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
    """Return (interpreter_path, is_degraded).

    Venv resolution order:
    1. ${CLAUDE_PLUGIN_DATA}/.venv  — persistent across plugin version bumps (CC v2.1.78+)
    2. base_root / ".venv"          — dev-mode fallback (no CLAUDE_PLUGIN_DATA set)
    3. sys.executable               — degraded, no venv found anywhere

    Note: on first install, CLAUDE_PLUGIN_DATA exists but .venv has not been created
    yet; the venv_py.exists() check handles this by falling through to the next tier.
    """
    if _ci_mode():
        return Path(sys.executable), False  # CI mode never looks for a venv: a planted .venv must not pick the interpreter

    suffix = ".venv/Scripts/python.exe" if sys.platform == "win32" else ".venv/bin/python"

    data_dir = os.environ.get("CLAUDE_PLUGIN_DATA")
    if data_dir:
        venv_py = Path(data_dir) / suffix
        if venv_py.exists():
            return venv_py, False

    venv_py = base_root / suffix
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
        _data_dir = os.environ.get("CLAUDE_PLUGIN_DATA")
        _searched = (
            f"{_data_dir}/.venv, " if _data_dir else ""
        ) + str(base_root / ".venv")
        print(
            f"[neuroloom-sdlc] degraded: base plugin venv not found at "
            f"{_searched} — using system Python",
            file=sys.stderr,
        )

    env = os.environ.copy()
    if _ci_mode():
        # `python -m` would put the working directory (the checkout, which may be
        # attacker-controlled) first on sys.path. `-I` (3.4+, so fine on the 3.10
        # floor) leaves cwd and PYTHONPATH off sys.path; the bootstrap then sets it
        # to exactly the two roots and runs the module as __main__.
        args = [str(py), "-I", "-c", _CI_BOOTSTRAP, str(SDLC_ROOT), str(base_root), module]
        args += sys.argv[2:]
        env["PYTHONPATH"] = str(SDLC_ROOT) + os.pathsep + str(base_root)
    else:
        args = [str(py), "-m", module] + sys.argv[2:]
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
