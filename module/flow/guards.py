"""Typed guard factories (D14: guards are objects, not strings)."""

from __future__ import annotations

from typing import Any

from module.flow.model import FlowCtx


def server_eq(server: str):
    """Guard: `config.SERVER == server`."""

    def _guard(ctx: FlowCtx, args: dict[str, Any] | None = None) -> bool:
        return server == ctx.config.SERVER

    return _guard


def config_eq(attr: str, expected: Any):
    """Guard: `getattr(config, attr) == expected` (attr stays a string by design)."""

    def _guard(ctx: FlowCtx, args: dict[str, Any] | None = None) -> bool:
        return getattr(ctx.config, attr) == expected

    return _guard


def capability(attr: str):
    """Guard: `hasattr(owner, attr)` (original `hasattr(self, ...)` semantics)."""

    def _guard(ctx: FlowCtx, args: dict[str, Any] | None = None) -> bool:
        return hasattr(ctx.owner, attr)

    return _guard
