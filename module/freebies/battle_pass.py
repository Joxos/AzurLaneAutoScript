from typing import Any

from module.base.timer import Timer
from module.base.utils import get_color
from module.combat.combat import Combat
from module.freebies.assets import *  # noqa: F403  (data-bundle star import)
from module.logger import logger
from module.ui.assets import BATTLE_PASS_CHECK, REWARD_GOTO_BATTLE_PASS
from module.ui.page import page_reward
from module.ui.ui import UI
from module.ui_white.assets import POPUP_CONFIRM_WHITE_BATTLEPASS

# ---------------------------------------------------------------------------
# battle_pass_receive flow (B3a, cluster A representative). New engine rule
# key: `reset_confirm` resets the owner's confirm timer after a handled
# action, matching the original `confirm_timer.reset()` per rule.
# ---------------------------------------------------------------------------


def _bp_end(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    """Original L113-121 end condition + confirm timer (started in the method)."""
    owner = ctx.owner
    condition = (
        owner.appear(BATTLE_PASS_CHECK, offset=(20, 20))
        and not owner.appear(REWARD_RECEIVE, offset=(20, 20))
        and not owner.appear(REWARD_RECEIVE_WHITE, offset=(20, 20))
    )
    if not condition:
        owner._bp_confirm.reset()
        return False
    return owner._bp_confirm.reached()


def _bp_popup(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.handle_battle_pass_popup()


def _bp_popup_confirm(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.handle_popup_confirm(name="BATTLE_PASS")


def _bp_get(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    kind = (args or {}).get("kind")
    handled = getattr(ctx.owner, f"handle_get_{kind}")()
    if handled:
        ctx.params["_bp_received"] = True
    return handled


def _bp_server_guard(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.config.SERVER in ["cn", "jp", "en"]


def _battle_pass_receive_flow() -> dict[str, Any]:
    reset = {"reset_confirm": "_bp_confirm"}
    return {
        "name": "battle_pass_receive",
        "entry": "s",
        "states": {
            "s": {
                "exit": {"check": {"custom": _bp_end}, "on_success": {"exit": {"__var__": "_bp_received"}}},
                "rules": [
                    {"name": "receive",
                     "check": {"button": REWARD_RECEIVE, "offset": (20, 20), "interval": 3},
                     "action": {"click": REWARD_RECEIVE}, **reset},
                    {"name": "receive_sp",
                     "check": {"template": REWARD_RECEIVE_SP, "offset": (20, 20), "interval": 3, "threshold": 15},
                     "action": {"click": REWARD_RECEIVE_SP}, **reset},
                    {"name": "receive_white",
                     "check": {"button": REWARD_RECEIVE_WHITE, "offset": (20, 20), "interval": 3},
                     "action": {"click": REWARD_RECEIVE_WHITE}, **reset},
                    {"name": "purchase_popup", "action": {"call_if": _bp_popup}, **reset},
                    {"name": "confirm_white", "guard": _bp_server_guard,
                     "check": {"button": POPUP_CONFIRM_WHITE_BATTLEPASS, "offset": (20, 20), "interval": 3},
                     "action": {"click": POPUP_CONFIRM_WHITE_BATTLEPASS}, **reset},
                    {"name": "popup_confirm", "action": {"call_if": _bp_popup_confirm}, **reset},
                    {"name": "get_items", "action": {"call_if": _bp_get, "args": {"kind": "items"}}, **reset},
                    {"name": "get_ship", "action": {"call_if": _bp_get, "args": {"kind": "ship"}}, **reset},
                    {"name": "get_skin", "action": {"call_if": _bp_get, "args": {"kind": "skin"}}, **reset},
                ],
                # safety ceiling (original loop had none)
                "on_timeout": {"seconds": 120, "mode": "warn"},
            },
        },
    }


class BattlePass(Combat, UI):
    def battle_pass_red_dot_appear(self):
        """
        Returns:
            bool: If appear.

        Page:
            in: page_reward
        """
        if self.appear(REWARD_GOTO_BATTLE_PASS, offset=(50, 150)):
            # Load button offset from REWARD_GOTO_BATTLE_PASS,
            # because entrance may not be the top one.
            BATTLE_PASS_RED_DOT.load_offset(REWARD_GOTO_BATTLE_PASS)
            # Not using self.appear() here, because it's transparent,
            # color may be different depending on background.
            r, _, _ = get_color(self.device.image, BATTLE_PASS_RED_DOT.button)
            if r > BATTLE_PASS_RED_DOT.color[0] - 40:
                logger.info("Found battle pass red dot")
                return True
            else:
                logger.info("No battle pass red dot")
                return False
        else:
            logger.warning("No battle pass entrance")
            return False

    def handle_battle_pass_popup(self):
        return self.appear_then_click(PURCHASE_POPUP, offset=(20, 20), interval=2)

    def battle_pass_enter(self):
        """
        Page:
            in: page_reward
            out: page_battle_pass
        """

        def appear_button():
            return self.appear(REWARD_GOTO_BATTLE_PASS, offset=(50, 150))

        self.ui_click(
            REWARD_GOTO_BATTLE_PASS,
            appear_button=appear_button,
            check_button=BATTLE_PASS_CHECK,
            additional=self.handle_battle_pass_popup,
            skip_first_screenshot=True,
        )

    def battle_pass_receive(self, skip_first_screenshot=True):
        """
        Returns:
            bool: If received.

        Pages:
            in: page_battle_pass
            out: page_battle_pass
        """
        from module.flow.engine import FlowEngine

        logger.hr("Battle pass receive", level=1)
        self.battle_status_click_interval = 2
        self._bp_confirm = Timer(1, count=3).start()
        received = bool(
            FlowEngine(owner=self, device=self.device, config=self.config, skip_first=skip_first_screenshot).run(
                _battle_pass_receive_flow(), params={"_bp_received": False}
            )
        )
        logger.info(f"Battle pass receive finished, received={received}")
        return received

    def run(self):
        self.ui_ensure(page_reward)

        if self.battle_pass_red_dot_appear():
            self.battle_pass_enter()
            self.battle_pass_receive()
