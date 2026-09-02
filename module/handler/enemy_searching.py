from typing import Any

from module.base.decorator import del_cached_property
from module.base.timer import Timer
from module.exception import CampaignEnd
from module.handler.assets import *  # noqa: F403  (data-bundle star import)
from module.handler.info_handler import InfoHandler
from module.logger import logger
from module.map.assets import *  # noqa: F403  (data-bundle star import)
from module.ui.assets import CAMPAIGN_CHECK, EVENT_CHECK, SP_CHECK

# ---------------------------------------------------------------------------
# Enemy-searching flows (design §3.4-D): the two `while 1` loops are flow
# data; IN_MAP_POPUPS is the shared popup group (vote/story/guild/urgent +
# auto-search exit, with the original timeout extension semantics).
# ---------------------------------------------------------------------------


def _is_event_animation(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.is_event_animation()


def _is_in_map(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.is_in_map()


def _not_in_map(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return not ctx.owner.is_in_map()


def _in_stage_helper(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    """Original handle_in_stage(): raises CampaignEnd inside when entered."""
    return ctx.owner.handle_in_stage()


def _combat_loading(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    # original `hasattr(self, "is_combat_loading") and self.is_combat_loading()`
    return hasattr(ctx.owner, "is_combat_loading") and ctx.owner.is_combat_loading()


def _enemy_searching_appear(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.enemy_searching_appear()


def _color_initial(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    ctx.owner.enemy_searching_color_initial()
    return True


def _auto_search_exit(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.handle_auto_search_exit(drop=(args or {}).get("drop"))


def _vote_popup(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.handle_vote_popup()


def _story_skip(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    handled = ctx.owner.handle_story_skip()
    if handled:
        ctx.owner.ensure_no_story()
    return handled


def _guild_popup_cancel(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.handle_guild_popup_cancel()


def _urgent_commission(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.handle_urgent_commission(drop=(args or {}).get("drop"))


def _flash_and_finish(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    ctx.owner.handle_enemy_flashing()
    ctx.owner.device.sleep(0.3)
    ctx.owner.device.screenshot()
    logger.info("Enemy searching appeared.")
    return True


def _popups_in_map(drop: Any = None, extend: float = 10.0) -> list[dict[str, Any]]:
    """Shared popup group; extend matches the original `timeout.limit=10` / reset."""
    return [
        {"name": "auto_search_exit", "action": {"call_if": _auto_search_exit, "args": {"drop": drop}},
         "on_handled": {"extend_timeout": extend}},
        {"name": "vote", "action": {"call_if": _vote_popup}, "on_handled": {"extend_timeout": extend}},
        {"name": "story", "action": {"call_if": _story_skip}, "on_handled": {"extend_timeout": extend}},
        {"name": "guild", "action": {"call_if": _guild_popup_cancel}, "on_handled": {"extend_timeout": extend}},
        {"name": "urgent", "action": {"call_if": _urgent_commission, "args": {"drop": drop}},
         "on_handled": {"extend_timeout": extend}},
    ]


def _enemy_searching_flow(drop: Any = None) -> dict[str, Any]:
    """Original handle_in_map_with_enemy_searching (L109-164), two-phase confirm."""
    return {
        "name": "enemy_searching",
        "entry": "waiting",
        "groups": _popups_in_map(drop),
        "states": {
            "waiting": {
                "skip_if": {"custom": _is_event_animation},
                "rules": [
                    {"name": "in_stage", "action": {"call_if": _in_stage_helper}},
                    {"name": "combat_loading", "check": {"custom": _combat_loading},
                     "action": {"goto": "__exit__", "value": True}},
                    {"name": "color_init", "check": {"not": {"custom": _enemy_searching_appear}},
                     "action": {"call": _color_initial}, "stop": False},
                    {"name": "seen_enemy", "check": {"custom": _enemy_searching_appear},
                     "then": {"goto": "confirm"}},
                ],
                # original timeout reached -> `break` -> return True
                "on_timeout": {"seconds": 5, "mode": "exit", "value": True},
            },
            "confirm": {
                "skip_if": {"custom": _is_event_animation},
                "exit": {"check": {"not": {"custom": _enemy_searching_appear}},
                         "confirm": {"seconds": 0.3}, "on_success": {"goto": "finish"}},
                "rules": [],
                "on_timeout": {"seconds": 10, "mode": "exit", "value": True},
            },
            "finish": {
                "rules": [{"name": "flash", "check": {"always": True},
                           "action": {"call": _flash_and_finish}, "then": {"exit": True}}],
            },
        },
    }


def _no_enemy_searching_flow(drop: Any = None) -> dict[str, Any]:
    """Original handle_in_map_no_enemy_searching (L177-210)."""
    return {
        "name": "no_enemy_searching",
        "entry": "wait",
        "groups": _popups_in_map(drop, extend=1.0),
        "states": {
            "wait": {
                "rules": [
                    {"name": "in_stage", "action": {"call_if": _in_stage_helper}},
                    # original: keep waiting while not in map (`timeout.reset()`)
                    {"name": "not_in_map", "check": {"custom": _not_in_map},
                     "action": {"reset_timeout": True}, "stop": False},
                ],
                "on_timeout": {"seconds": 1, "count": 2, "mode": "exit", "value": True},
            },
        },
    }


class EnemySearchingHandler(InfoHandler):
    MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD = 0.5  # Usually (0.70, 0.80).
    MAP_ENEMY_SEARCHING_TIMEOUT_SECOND = 5
    in_stage_timer = Timer(0.5, count=2)
    stage_entrance = None

    map_is_100_percent_clear = False  # Will be override in fast_forward.py

    def enemy_searching_color_initial(self):
        pass

    def enemy_searching_appear(self):
        if not self.is_in_map():
            return False

        if MAP_ENEMY_SEARCHING.match_luma(self.device.image, offset=(5, 5)):
            return True

        return False

    def handle_enemy_flashing(self):
        self.device.sleep(1.2)

    def handle_in_stage(self):
        if self.is_in_stage():
            if self.in_stage_timer.reached():
                logger.info("In stage.")
                self.ensure_no_info_bar(timeout=1.2)
                raise CampaignEnd("In stage.")
            else:
                return False
        else:
            if self.appear(MAP_PREPARATION, offset=(20, 20)) \
                    or self.appear(MAP_PREPARATION_HARD, offset=(20, 20)) \
                    or self.appear(FLEET_PREPARATION, offset=(20, 50)):
                self.device.click(MAP_PREPARATION_CANCEL)
            self.in_stage_timer.reset()
            return False

    def is_in_stage_page(self):
        return any(self.appear(check, offset=(20, 20)) for check in [CAMPAIGN_CHECK, EVENT_CHECK, SP_CHECK])

    def is_stage_page_has_entrance(self):
        """
        Has any stage entrance, which means stage page is fully loaded
        """
        # campaign_extract_name_image in CampaignOcr.
        try:
            if hasattr(self, "campaign_extract_name_image"):
                del_cached_property(self, "_stage_image")
                del_cached_property(self, "_stage_image_gray")
                if not len(self.campaign_extract_name_image(self.device.image)):
                    return False
        except IndexError:
            return False

        return True

    def is_in_stage(self):
        if not self.is_in_stage_page():
            return False
        if not self.is_stage_page_has_entrance():
            return False
        return True

    def is_in_map(self):
        return self.appear(IN_MAP)

    def is_event_animation(self):
        """
        Animation in events after cleared an enemy.

        Returns:
            bool: If animation appearing.
        """
        return False

    def handle_auto_search_exit(self, drop=None):
        """
        A placeholder, will be override in AutoSearchHandler.
        AutoSearchHandler inherits EnemySearchingHandler,
        but handle_in_map_with_enemy_searching() requires handle_auto_search_exit() to handle unexpected situation.
        """
        return False

    def handle_in_map_with_enemy_searching(self, drop=None):
        """
        Args:
            drop (DropImage):

        Returns:
            bool: If handled.
        """
        if not self.is_in_map():
            return False

        from module.flow.runtime import run_flow

        run_flow(_enemy_searching_flow(drop))

        return True

    def handle_in_map_no_enemy_searching(self, drop=None):
        """
        Args:
            drop (DropImage):

        Returns:
            bool: If handled.
        """
        if not self.is_in_map():
            return False

        from module.flow.runtime import run_flow

        run_flow(_no_enemy_searching_flow(drop))

        return True
