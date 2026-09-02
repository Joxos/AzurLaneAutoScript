"""Sample 3 (design §3.4-B): the shared popup rule group (POPUPS_MAIN).

Transcribed from module/ui/ui.py `ui_additional` (L476-601, 35 rules)
plus module/handler/info_handler.py helpers. This Group is injected into
any Flow's state via `"groups": [make_popups_main(...)]`, replacing the
copy-pasted popup handlers in 10+ loops (design D9).
"""

from __future__ import annotations

from typing import Any

from module.handler.flow_actions import popup_confirm, urgent_commission
from module.ui import assets as ua
from module.ui.assets_bridge import (
    AUTO_SEARCH_MENU_EXIT,
    AUTO_SEARCH_REWARD,
    FLEET_PREPARATION,
    GAME_TIPS,
    LOGIN_CHECK,
    MAINTENANCE_ANNOUNCE,
    MAP_PREPARATION,
    MAP_PREPARATION_CANCEL,
    MAP_PREPARATION_HARD,
    RAID_FLEET_PREPARATION,
)
from module.ui.flow_actions import (
    idle_page_gated,
    story_skip_graph,
    ui_page_main_popups,
    ui_page_os_popups,
    withdraw_double_check,
)
from module.ui_white.assets import MAIN_GOTO_MEMORIES_WHITE, MAIN_TAB_SWITCH_WHITE


def make_popups_main(get_ship: bool = True) -> list[dict[str, Any]]:
    """The popup rule group (priority order = ui_additional rule order)."""
    return [
        # original L486-487: page_os popups first (RESET_FLEET_PREPARATION count >= 5
        # raises RequestHumanTakeover inside the call)
        {"action": {"call_if": ui_page_os_popups}},
        # L490-493: research/lost-connection confirm + urgent commission
        {"action": {"call_if": popup_confirm, "args": {"name": "UI_ADDITIONAL"}}},
        {"action": {"call_if": urgent_commission}},
        # L496-497: page_main / page_reward popups (get_ship parameterized)
        {"action": {"call_if": ui_page_main_popups, "args": {"get_ship": get_ship}}},
        # L500-501: story
        {"action": {"call_if": story_skip_graph}},
        # L506-509: game tips -> GOTO_MAIN
        {"check": {"button": GAME_TIPS, "interval": 2}, "action": {"click_and": [ua.GOTO_MAIN]}},
        # L512-518: dorm popups
        {"check": {"button": ua.DORM_INFO, "interval": 3, "similarity": 0.75},
         "action": {"click": ua.DORM_INFO}},
        {"check": {"button": ua.DORM_FEED_CANCEL, "interval": 3}, "action": {"click": ua.DORM_FEED_CANCEL}},
        # L531-538: campaign preparation (any of the four) -> cancel
        {"check": {"or": [{"button": MAP_PREPARATION, "interval": 3},
                          {"button": MAP_PREPARATION_HARD, "interval": 3},
                          {"button": FLEET_PREPARATION, "interval": 3},
                          {"button": RAID_FLEET_PREPARATION, "interval": 3}]},
         "action": {"click": MAP_PREPARATION_CANCEL}},
        # L539-542: auto-search exit/reward popups
        {"check": {"button": AUTO_SEARCH_MENU_EXIT, "offset": (200, 30), "interval": 3},
         "action": {"click": AUTO_SEARCH_MENU_EXIT}},
        {"check": {"button": AUTO_SEARCH_REWARD, "offset": (50, 50), "interval": 3},
         "action": {"click": AUTO_SEARCH_REWARD}},
        # L543-561: WITHDRAW client-bug double check (wrapper keeps its 2s wait)
        {"action": {"call_if": withdraw_double_check}},
        # L563-566: login/maintenance popups
        {"check": {"button": LOGIN_CHECK, "offset": (30, 30), "interval": 3},
         "action": {"click": LOGIN_CHECK}},
        {"check": {"button": MAINTENANCE_ANNOUNCE, "offset": (30, 30), "interval": 3},
         "action": {"click": MAINTENANCE_ANNOUNCE}},
        # L592-599: idle page + white-menu switch
        {"action": {"call_if": idle_page_gated}},
        {"check": {"button": MAIN_GOTO_MEMORIES_WHITE, "interval": 3},
         "action": {"click": MAIN_TAB_SWITCH_WHITE}},
    ]
