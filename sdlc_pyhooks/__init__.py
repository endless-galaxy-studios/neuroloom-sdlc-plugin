"""
SDLC plugin hook package: CI-mode state helper.

``NEUROLOOM_MODE`` has one parse rule and four copies (base ``pyhooks.config``, the base
launcher, this plugin's launcher, and this module). This module holds the SDLC plugin's hook-side copy of the parser. It
cannot import the base parser: an old base plugin lacks it, and that is exactly the
version-skew case this helper must detect.

``mode_state()`` is decided from the environment plus the declared fields of
``pyhooks.config.Config``, never from ``load()``. Reading the environment is what
makes an old base fail closed: a hook that only asked ``getattr(config, "ci_mode",
False)`` would fall back to normal mode and upload documents.
"""

from __future__ import annotations

import os
from typing import Literal, NamedTuple


class ModeParse(NamedTuple):
    ci: bool
    recognised: bool


def parse_mode(raw: str | None) -> ModeParse:
    """Parse a NEUROLOOM_MODE value (same table as the base plugin).

    Unset, empty or blank: normal mode. ``ci`` (case-insensitive, trimmed): CI mode.
    Any other value is unrecognised and fails closed into CI mode.
    """
    value = (raw or "").strip().lower()
    if not value:
        return ModeParse(ci=False, recognised=True)
    if value == "ci":
        return ModeParse(ci=True, recognised=True)
    return ModeParse(ci=True, recognised=False)


ModeState = Literal["normal", "ci", "skew"]


def mode_state() -> ModeState:
    """Return ``normal``, ``ci`` or ``skew``. Does not call ``pyhooks.config.load``.

    ``skew``: the environment says CI mode but the imported base plugin cannot
    report it (its ``Config`` has no ``ci_mode`` field, or it cannot be imported).
    """
    if not parse_mode(os.environ.get("NEUROLOOM_MODE")).ci:
        return "normal"
    try:
        import pyhooks.config  # type: ignore[import-untyped]

        # Skew detection relies on Config being a dataclass; anything else reads as no fields -> skew.
        declared = getattr(pyhooks.config.Config, "__dataclass_fields__", {})
        return "ci" if "ci_mode" in declared else "skew"
    except Exception:
        return "skew"
