"""Thin flow-action wrappers over UI(InfoHandler) methods (D13).

One 1-3 line module-level function per custom check/action; original UI
methods stay in place and are bound through ctx.owner.
Custom check/action signature: `(ctx: FlowCtx, args: dict) -> bool`.
"""

from __future__ import annotations

from typing import Any

from module.flow.model import FlowCtx
from module.map.assets import WITHDRAW  # same source as ui.assets_bridge


def ui_page_os_popups(ctx: FlowCtx, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.ui_page_os_popups()


def ui_page_main_popups(ctx: FlowCtx, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.ui_page_main_popups(get_ship=(args or {}).get("get_ship", True))


def story_skip_graph(ctx: FlowCtx, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.handle_story_skip()


def withdraw_double_check(ctx: FlowCtx, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    """Original ui_additional L543-561: WITHDRAW double-check with a client-bug wait."""
    owner = ctx.owner
    if not owner.appear(WITHDRAW, offset=(30, 30), interval=3):
        return False
    owner.device.sleep(2)
    owner.device.screenshot()
    if owner.appear_then_click(WITHDRAW, offset=(30, 30)):
        owner.interval_reset(WITHDRAW)
        return True
    owner.interval_reset(WITHDRAW)
    return False


def idle_page_gated(ctx: FlowCtx, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.handle_idle_page()
