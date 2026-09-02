"""Version resolution for the `alas version` command."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

FALLBACK_VERSION = "1.0.0"


def version_string() -> str:
    """Return the installed package version, falling back to pyproject's value."""
    try:
        return version("alas")
    except PackageNotFoundError:
        return FALLBACK_VERSION
