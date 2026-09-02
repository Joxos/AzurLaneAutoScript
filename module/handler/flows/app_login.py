"""Sample 1 (design §3.4-A): the app login loop as flow data.

Transcribed line-by-line from module/handler/login.py `_handle_app_login`
(L31-94); the legacy method stays in place. Parameters are factory
arguments (D14): get_ship replaces the cross-state `login_success` flag.
"""

from __future__ import annotations

from typing import Any

from module.flow.guards import server_eq
from module.handler.assets import (
    ANDROID_NO_RESPOND,
    AVATAR_EXPIRED,
    LOGIN_ANNOUNCE,
    LOGIN_ANNOUNCE_2,
    LOGIN_CHECK,
    LOGIN_GAME_UPDATE,
    LOGIN_RETURN_INFO,
    LOGIN_RETURN_SIGN,
    MAINTENANCE_ANNOUNCE,
)
from module.handler.flow_actions import (
    click_with_record,
    cn_agreement_present,
    handle_cn_user_agreement,
    login_main_popups,
    popup_confirm,
    urgent_commission,
)
from module.ui.assets import BACK_ARROW, EVENT_LIST_CHECK, GOTO_MAIN  # same source as login.py (ui.assets star)
from module.ui.page import page_main


def make_app_login(get_ship: bool = True) -> dict[str, Any]:
    return {
        "name": "app_login",
        "entry": "login",
        "states": {
            "login": {
                "exit": {  # original L41-46: is_in_main + confirm_timer
                    "check": {"page": page_main},
                    "confirm": {"seconds": 1.5, "count": 4},
                    "on_success": {"exit": True},
                },
                "rules": [
                    # L49-53: match template color, click, do not short-circuit
                    {"check": {"template": LOGIN_CHECK, "offset": (30, 30), "interval": 5},
                     "action": {"click": LOGIN_CHECK}, "stop": False},
                    # L54-59: ANDROID_NO_RESPOND -> record + click
                    {"check": {"button": ANDROID_NO_RESPOND, "offset": (30, 30), "interval": 5},
                     "action": {"call": click_with_record, "args": {"button": ANDROID_NO_RESPOND}}},
                    {"check": {"button": LOGIN_ANNOUNCE, "offset": (30, 30), "interval": 5},
                     "action": {"click": LOGIN_ANNOUNCE}},
                    {"check": {"button": LOGIN_ANNOUNCE_2, "offset": (30, 30), "interval": 5},
                     "action": {"click": LOGIN_ANNOUNCE_2}},
                    # L64-66: event list -> back arrow
                    {"check": {"button": EVENT_LIST_CHECK, "offset": (30, 30), "interval": 5},
                     "action": {"click_and": [BACK_ARROW]}},
                    # L67-71: maintenance/update popups
                    {"check": {"button": MAINTENANCE_ANNOUNCE, "offset": (30, 30), "interval": 5},
                     "action": {"click": MAINTENANCE_ANNOUNCE}},
                    {"check": {"button": LOGIN_GAME_UPDATE, "offset": (30, 30), "interval": 5},
                     "action": {"click": LOGIN_GAME_UPDATE}},
                    # L72-74: cn user agreement (custom wrapper, original method unchanged)
                    {"guard": server_eq("cn"),
                     "check": {"custom": cn_agreement_present},
                     "action": {"call": handle_cn_user_agreement}},
                    # L76-81: player-return popups
                    {"check": {"button": LOGIN_RETURN_SIGN, "offset": (30, 30), "interval": 5},
                     "action": {"click": LOGIN_RETURN_SIGN}},
                    {"check": {"button": LOGIN_RETURN_INFO, "offset": (30, 30), "interval": 5},
                     "action": {"click": LOGIN_RETURN_INFO}},
                    {"check": {"button": AVATAR_EXPIRED, "offset": (30, 30), "interval": 5},
                     "action": {"click": AVATAR_EXPIRED}},
                    # L83-86: generic confirm popup + urgent commission (hot-fix guard inside)
                    # call_if = original `if self.handle_popup_confirm(...): continue` semantics
                    {"action": {"call_if": popup_confirm, "args": {"name": "LOGIN"}}},
                    {"action": {"call_if": urgent_commission}},
                    # L88-89: page_main popups -> handled means login done, exit True
                    {"action": {"call_if": login_main_popups, "args": {"get_ship": get_ship}},
                     "then": {"exit": True}},
                    # L91-92: last-resort GOTO_MAIN
                    {"check": {"button": GOTO_MAIN, "offset": (30, 30), "interval": 5},
                     "action": {"click": GOTO_MAIN}},
                ],
                # original while-1 had no timeout; engine guard default (safe ceiling)
                "on_timeout": {"seconds": 120, "mode": "raise"},
            },
        },
    }
