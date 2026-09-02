"""Alas unified command-line entry (P0).

Console script: ``alas = module.cli:main`` (see pyproject.toml). The legacy
``alas.py`` / ``gui.py`` entry scripts are backward-compatible shims that
delegate here. Design: .qoder/doc/reorg-cli-flow-2026.md §2.
"""

from module.cli.app import app, main

__all__ = ["app", "main"]
