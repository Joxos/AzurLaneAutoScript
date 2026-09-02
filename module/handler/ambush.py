from typing import Any

from module.base.utils import get_color, red_overlay_transparency
from module.combat.combat import Combat
from module.handler.assets import *  # noqa: F403  (data-bundle star import)
from module.handler.info_handler import info_letter_preprocess
from module.logger import logger
from module.template.assets import *  # noqa: F403  (data-bundle star import)

TEMPLATE_AMBUSH_EVADE_SUCCESS.pre_process = info_letter_preprocess
TEMPLATE_AMBUSH_EVADE_FAILED.pre_process = info_letter_preprocess
TEMPLATE_MAP_WALK_OUT_OF_STEP.pre_process = info_letter_preprocess


# ---------------------------------------------------------------------------
# Ambush flows (design §3.4-C): the three loops from the original class are
# flow data here; helpers are 1-3 line wrappers over the original methods
# (ctx.owner). Original constants/logic kept in the class below.
# ---------------------------------------------------------------------------


def _air_raid_appear(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner._air_raid_appear()


def _ambush_appear(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner._ambush_appear()


def _combat_appear(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.combat_appear()


def _info_bar(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return bool(ctx.owner.info_bar_count())


def _combat_low_emotion(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.handle_combat_low_emotion()


def _retirement(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.handle_retirement()


def _attr(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    logger.attr((args or {}).get("name", ""), (args or {}).get("value"))
    return True


def _evade_failed(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    ctx.owner.combat(expected_end="no_searching", fleet_index=ctx.owner.fleet_show_index)
    return True


def _evade_unrecognized(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    ctx.owner.ensure_no_info_bar()
    if ctx.owner.combat_appear():
        ctx.owner.combat(fleet_index=ctx.owner.fleet_show_index)
    return True


def _run_air_raid(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    ctx.owner._handle_air_raid()
    return True


def _run_ambush(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    ctx.owner._handle_ambush()
    return True


def _air_raid_flow() -> dict[str, Any]:
    """T2 negative wait (original L35-54): wait until air raid disappears."""
    return {
        "name": "air_raid",
        "entry": "wait",
        "states": {
            "wait": {
                "exit": {"check": {"not": {"custom": _air_raid_appear}}, "confirm": {"seconds": 0.5},
                         "on_success": {"exit": None}},
                "rules": [],
                "on_timeout": {"seconds": 2.5, "count": 2, "mode": "warn"},
            },
        },
    }


def _ambush_evade_flow() -> dict[str, Any]:
    """Original L56-88: click evade until info bar disappears, then OCR result."""
    return {
        "name": "ambush_evade",
        "entry": "evade",
        "states": {
            "evade": {
                "exit": {"check": {"custom": _info_bar}, "on_success": {"goto": "result"}},
                "rules": [
                    {"name": "click_evade",
                     "check": {"button": MAP_AMBUSH_EVADE, "offset": (30, 30), "interval": 3},
                     "action": {"click": MAP_AMBUSH_EVADE}},
                ],
                "on_timeout": {"seconds": 30, "mode": "warn"},
            },
            "result": {
                "rules": [
                    {"name": "success",
                     "check": {"template": TEMPLATE_AMBUSH_EVADE_SUCCESS, "crop": INFO_BAR_DETECT, "pre": info_letter_preprocess},
                     "action": {"call": _attr, "args": {"name": "Ambush_evade", "value": "success"}}},
                    {"name": "failed",
                     "check": {"template": TEMPLATE_AMBUSH_EVADE_FAILED, "crop": INFO_BAR_DETECT, "pre": info_letter_preprocess},
                     "action": {"call": _evade_failed}},
                    {"name": "unrecognized", "check": {"always": True}, "action": {"call": _evade_unrecognized}},
                ],
                "on_timeout": {"seconds": 10, "mode": "warn"},
            },
        },
    }


def _ambush_attack_flow() -> dict[str, Any]:
    """Original L90-116: click attack until combat appears."""
    return {
        "name": "ambush_attack",
        "entry": "attack",
        "states": {
            "attack": {
                "exit": {"check": {"custom": _combat_appear}, "on_success": {"exit": None}},
                "rules": [
                    {"name": "click_attack",
                     "check": {"button": MAP_AMBUSH_ATTACK, "offset": (30, 30), "interval": 3},
                     "action": {"click": MAP_AMBUSH_ATTACK}},
                    {"name": "low_emotion", "action": {"call_if": _combat_low_emotion}},
                    {"name": "retirement", "action": {"call_if": _retirement}},
                ],
                "on_timeout": {"seconds": 30, "mode": "warn"},
            },
        },
    }


class AmbushHandler(Combat):
    MAP_AMBUSH_OVERLAY_TRANSPARENCY_THRESHOLD = 0.40
    MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD = 0.35  # Usually (0.50, 0.53)
    MAP_AIR_RAID_CONFIRM_SECOND = 0.5

    def ambush_color_initial(self):
        MAP_AMBUSH.load_color(self.device.image)
        MAP_AIR_RAID.load_color(self.device.image)

    def _ambush_appear(self):
        return (
            red_overlay_transparency(MAP_AMBUSH.color, get_color(self.device.image, MAP_AMBUSH.area))
            > self.MAP_AMBUSH_OVERLAY_TRANSPARENCY_THRESHOLD
        )

    def _air_raid_appear(self):
        return (
            red_overlay_transparency(MAP_AIR_RAID.color, get_color(self.device.image, MAP_AIR_RAID.area))
            > self.MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD
        )

    def _handle_air_raid(self):
        """
        Wait until air raid disappeared
        """
        from module.flow.engine import FlowEngine

        logger.info("Map air raid")
        FlowEngine(owner=self, device=self.device, config=self.config).run(_air_raid_flow())

    def _handle_ambush_evade(self):
        from module.flow.engine import FlowEngine

        logger.info("Map ambushed")
        # Wait MAP_AMBUSH_EVADE
        self.wait_until_appear(MAP_AMBUSH_EVADE, offset=(30, 30))
        self.handle_info_bar()

        # Click MAP_AMBUSH_EVADE, then OCR the result (success/failed/unrecognized)
        FlowEngine(owner=self, device=self.device, config=self.config).run(_ambush_evade_flow())

    def _handle_ambush_attack(self):
        from module.flow.engine import FlowEngine

        logger.info("Map ambushed")
        # Wait MAP_AMBUSH_ATTACK
        self.wait_until_appear(MAP_AMBUSH_ATTACK, offset=(30, 30))

        # Click MAP_AMBUSH_ATTACK
        FlowEngine(owner=self, device=self.device, config=self.config).run(_ambush_attack_flow())

        # In battle
        logger.attr("Ambush_evade", "attack")
        self.combat(expected_end="no_searching", fleet_index=self.fleet_show_index)

    def _handle_ambush(self):
        if self.config.Campaign_AmbushEvade:
            return self._handle_ambush_evade()
        else:
            return self._handle_ambush_attack()

    def handle_ambush(self):
        from module.flow.engine import FlowEngine

        if not self.config.MAP_HAS_AMBUSH:
            return False

        # Dispatch as a single-shot group (original if-chain semantics)
        return bool(
            FlowEngine(owner=self, device=self.device, config=self.config).run_group(
                [
                    {"name": "air_raid", "check": {"custom": _air_raid_appear}, "action": {"call": _run_air_raid}},
                    {"name": "ambush", "check": {"custom": _ambush_appear}, "action": {"call": _run_ambush}},
                    {"name": "evade_shown", "check": {"button": MAP_AMBUSH_EVADE, "offset": (30, 30)},
                     "action": {"call": _run_ambush}},
                ]
            )
        )

    def handle_walk_out_of_step(self):
        if not self.config.MAP_HAS_FLEET_STEP:
            return False
        if not self.info_bar_count():
            return False

        image = info_letter_preprocess(self.image_crop(INFO_BAR_DETECT, copy=False))
        if TEMPLATE_MAP_WALK_OUT_OF_STEP.match(image):
            logger.warning("Map walk out of step.")
            self.handle_info_bar()
            return True

        return False
