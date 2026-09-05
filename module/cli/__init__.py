"""Alas unified command-line entry (P0).

Console script: ``alas = module.cli:main`` (see pyproject.toml). It is the
only runtime entry point — the legacy ``alas.py`` / ``gui.py`` scripts have
been removed. Design: .qoder/doc/reorg-cli-flow-2026.md §2.
"""

from module.cli.app import app, main

__all__ = ["app", "main"]
