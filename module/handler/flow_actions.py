"""Thin flow-action wrappers over LoginHandler/InfoHandler methods (D13).

One 1-3 line module-level function per custom check/action; the original
handler methods are untouched and the engine binds through ctx.owner.
Custom check/action signature: `(ctx: FlowCtx, args: dict) -> bool`.
"""

from __future__ import annotations

from typing import Any

from module.flow.model import FlowCtx


def click_with_record(ctx: FlowCtx, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    """ANDROID_NO_RESPOND handling: record + verify + click (original login L54-59)."""
    button = (args or {}).get("button")
    ctx.owner.device.click_record_add(button)
    ctx.owner.device.click_record_check()
    ctx.owner.device.click(button, control_check=False)
    return True


def cn_agreement_present(ctx: FlowCtx, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    """Blue confirm button on the right half (original handle_cn_user_agreement detect)."""
    return (
        ctx.owner.image_color_button(
            area=(640, 360, 1280, 720), color=(78, 189, 234), color_threshold=245, encourage=25,
            name="AGREEMENT_CONFIRM",
        )
        is not None
    )


def handle_cn_user_agreement(ctx: FlowCtx, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.handle_cn_user_agreement()


def popup_confirm(ctx: FlowCtx, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.handle_popup_confirm(name=(args or {}).get("name", ""))


def urgent_commission(ctx: FlowCtx, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.handle_urgent_commission()


def login_main_popups(ctx: FlowCtx, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.ui_page_main_popups(get_ship=(args or {}).get("get_ship", True))


def auto_search_setting_is_active(ctx: FlowCtx, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    """Pure detection (no click); setting -> target index in the active list."""
    from module.handler.auto_search import dic_setting_name_to_index

    setting = (args or {}).get("setting")
    if setting is None or setting not in dic_setting_name_to_index:
        return False
    return dic_setting_name_to_index[setting] in ctx.owner._auto_search_active_settings()


def auto_search_setting_click(ctx: FlowCtx, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    """call_if helper: detect+click with backoff (original loop body).

    Returns True when the setting is already correct (no click was needed).
    """
    from module.handler.auto_search import dic_setting_name_to_index

    setting = (args or {}).get("setting")
    if setting is None or setting not in dic_setting_name_to_index:
        return False
    result = ctx.owner._auto_search_set_click(setting)
    if not result:
        ctx.owner.device.sleep((0.3, 0.5))
    return result
