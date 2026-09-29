from module.combat.assets import GET_ITEMS_1
from module.handler.assets import *  # noqa: F403  (data-bundle star import)
from module.handler.info_handler import InfoHandler
from module.logger import logger
from module.template.assets import TEMPLATE_FORMATION_1, TEMPLATE_FORMATION_2, TEMPLATE_FORMATION_3
from module.ui.switch import Switch

# 2023.10.19, icons on one row increased from 2 to 3
FORMATION = Switch("Formation", offset=(100, 200))
FORMATION.add_state("line_ahead", check_button=FORMATION_1)
FORMATION.add_state("double_line", check_button=FORMATION_2)
FORMATION.add_state("diamond", check_button=FORMATION_3)

SUBMARINE_HUNT = Switch("Submarine_hunt", offset=(200, 200))
SUBMARINE_HUNT.add_state("on", check_button=SUBMARINE_HUNT_ON)
SUBMARINE_HUNT.add_state("off", check_button=SUBMARINE_HUNT_OFF)

SUBMARINE_VIEW = Switch("Submarine_view", offset=(100, 200))
SUBMARINE_VIEW.add_state("on", check_button=SUBMARINE_VIEW_ON)
SUBMARINE_VIEW.add_state("off", check_button=SUBMARINE_VIEW_OFF)

MOB_MOVE_OFFSET = (120, 200)
AIR_STRIKE_OFFSET = (120, 200)


def _make_wait_flow(name: str, exit_check: dict, rules: list) -> dict:
    """Shared builder for strategy "wait until page/condition" loops."""
    return {
        "name": name,
        "entry": "s",
        "states": {
            "s": {
                "exit": {"check": exit_check, "on_success": {"exit": True}},
                "rules": rules,
            },
        },
    }


class StrategyHandler(InfoHandler):
    fleet_1_formation_fixed = False
    fleet_2_formation_fixed = False

    def strategy_open(self, skip_first_screenshot=True):
        logger.info("Strategy open")
        from module.flow.runtime import run_flow

        run_flow(
            _make_wait_flow(
                "strategy_open",
                exit_check={"button": STRATEGY_OPENED, "offset": 200},
                rules=[
                    {"name": "click_open",
                     "check": {"and": [{"button": IN_MAP, "interval": 5},
                                       {"not": {"button": STRATEGY_OPENED, "offset": 200}}]},
                     "action": {"click": STRATEGY_OPEN}},
                    # L46-47: missed mysteries
                    {"name": "get_items", "check": {"button": GET_ITEMS_1, "offset": 5},
                     "action": {"click": GET_ITEMS_1}},
                ],
            )
        )

    def strategy_close(self, skip_first_screenshot=True):
        logger.info("Strategy close")
        from module.flow.runtime import run_flow

        run_flow(
            _make_wait_flow(
                "strategy_close",
                exit_check={"not": {"button": STRATEGY_OPENED, "offset": 200}},
                rules=[
                    {"name": "click_close", "check": {"button": STRATEGY_OPENED, "offset": 200, "interval": 5},
                     "action": {"click": STRATEGY_OPENED}},
                ],
            )
        )

    def strategy_set_execute(self, formation=None, sub_view=None, sub_hunt=None):
        """
        Args:
            formation (str): 'line_ahead', 'double_line', 'diamond', or None for don't change
            sub_view (bool):
            sub_hunt (bool):

        Pages:
            in: STRATEGY_OPENED
        """
        logger.info(f"Strategy set: formation={formation}, submarine_view={sub_view}, submarine_hunt={sub_hunt}")

        if formation is not None:
            FORMATION.set(formation, main=self)
        # Disable this until the icon bug of submarine zone is fixed
        # And don't enable MAP_HAS_DYNAMIC_RED_BORDER when using submarine

        # Submarine view check is back again, see SwitchWithHandler.

        # Don't know when but the game bug was fixed, remove the use of SwitchWithHandler
        if sub_view is not None:
            if SUBMARINE_VIEW.appear(main=self):
                SUBMARINE_VIEW.set("on" if sub_view else "off", main=self)
            else:
                logger.warning("Setting up submarine_view but no icon appears")
        if sub_hunt is not None:
            if SUBMARINE_HUNT.appear(main=self):
                SUBMARINE_HUNT.set("on" if sub_hunt else "off", main=self)
            else:
                logger.warning("Setting up submarine_hunt but no icon appears")

    def handle_strategy(self, index):
        """

        Args:
            index (int): Fleet index.

        Returns:
            bool: If changed.
        """
        if self.__getattribute__(f"fleet_{index}_formation_fixed"):
            return False
        expected_formation = self.config.__getattribute__(f"Fleet_Fleet{index}Formation")
        if self._strategy_get_from_map_buff() == expected_formation and not self.config.Submarine_Fleet:
            logger.info("Skip strategy bar check.")
            self.__setattr__(f"fleet_{index}_formation_fixed", True)
            return False

        self.strategy_open()
        self.strategy_set_execute(
            formation=expected_formation,
            sub_view=False,
            sub_hunt=bool(self.config.Submarine_Fleet) and self.config.Submarine_Mode in ["hunt_only", "hunt_and_boss"],
        )
        self.strategy_close()
        self.__setattr__(f"fleet_{index}_formation_fixed", True)
        return True

    def _strategy_get_from_map_buff(self):
        """
        Returns:
            int: Formation index.
        """
        image = self.image_crop(MAP_BUFF, copy=False)
        if TEMPLATE_FORMATION_2.match(image):
            buff = "double_line"
        elif TEMPLATE_FORMATION_1.match(image):
            buff = "line_ahead"
        elif TEMPLATE_FORMATION_3.match(image):
            buff = "diamond"
        else:
            buff = "unknown"

        logger.attr("Map_buff", buff)
        return buff

    def is_in_strategy_submarine_move(self):
        """
        Returns:
            bool:
        """
        return self.appear(SUBMARINE_MOVE_CONFIRM, offset=(20, 20))

    def strategy_submarine_move_enter(self, skip_first_screenshot=True):
        """
        Pages:
            in: STRATEGY_OPENED, SUBMARINE_MOVE_ENTER
            out: SUBMARINE_MOVE_CONFIRM
        """
        logger.info("Submarine move enter")
        from module.flow.runtime import run_flow

        run_flow(
            _make_wait_flow(
                "submarine_move_enter",
                exit_check={"button": SUBMARINE_MOVE_CONFIRM, "offset": (20, 20)},
                rules=[
                    {"name": "click_enter", "check": {"button": SUBMARINE_MOVE_ENTER, "offset": 200, "interval": 5},
                     "action": {"click": SUBMARINE_MOVE_ENTER}},
                ],
            )
        )

    def strategy_submarine_move_confirm(self, skip_first_screenshot=True):
        """
        Pages:
            in: SUBMARINE_MOVE_CONFIRM
            out: STRATEGY_OPENED, SUBMARINE_MOVE_ENTER
        """
        logger.info("Submarine move confirm")
        from module.flow.runtime import run_flow

        run_flow(
            _make_wait_flow(
                "submarine_move_confirm",
                exit_check={"button": SUBMARINE_MOVE_ENTER, "offset": 200},
                rules=[
                    # original `appear_then_click(...): pass` -> keep evaluating (stop=False)
                    {"name": "click_confirm", "check": {"button": SUBMARINE_MOVE_CONFIRM, "offset": (20, 20), "interval": 5},
                     "action": {"click": SUBMARINE_MOVE_CONFIRM}, "stop": False},
                    {"name": "popup_confirm", "action": {"call_if": _popup, "args": {"name": "SUBMARINE_MOVE"}}},
                ],
            )
        )

    def strategy_submarine_move_cancel(self, skip_first_screenshot=True):
        """
        Pages:
            in: SUBMARINE_MOVE_CONFIRM
            out: STRATEGY_OPENED, SUBMARINE_MOVE_ENTER
        """
        logger.info("Submarine move cancel")
        from module.flow.runtime import run_flow

        run_flow(
            _make_wait_flow(
                "submarine_move_cancel",
                exit_check={"button": SUBMARINE_MOVE_ENTER, "offset": 200},
                rules=[
                    {"name": "click_cancel", "check": {"button": SUBMARINE_MOVE_CANCEL, "offset": (20, 20), "interval": 5},
                     "action": {"click": SUBMARINE_MOVE_CANCEL}, "stop": False},
                    {"name": "popup_confirm", "action": {"call_if": _popup, "args": {"name": "SUBMARINE_MOVE"}}},
                ],
            )
        )

    def is_in_strategy_mob_move(self):
        """
        Returns:
            bool:
        """
        return self.appear(MOB_MOVE_CANCEL, offset=(20, 20))

    def strategy_has_mob_move(self):
        """
        Pages:
            in: STRATEGY_OPENED
            out: STRATEGY_OPENED
        """
        if self.match_template_color(MOB_MOVE_ENTER, offset=MOB_MOVE_OFFSET):
            return True
        else:
            return False

    def strategy_mob_move_enter(self, skip_first_screenshot=True):
        """
        Pages:
            in: STRATEGY_OPENED, MOB_MOVE_ENTER
            out: MOB_MOVE_CANCEL
        """
        logger.info("Mob move enter")
        from module.flow.runtime import run_flow

        run_flow(
            _make_wait_flow(
                "mob_move_enter",
                exit_check={"button": MOB_MOVE_CANCEL, "offset": (20, 20)},
                rules=[
                    {"name": "click_enter", "check": {"button": MOB_MOVE_ENTER, "offset": MOB_MOVE_OFFSET, "interval": 5},
                     "action": {"click": MOB_MOVE_ENTER}},
                ],
            )
        )


    def is_in_strategy_air_strike(self):
        return self.appear(AIR_STRIKE_CONFIRM, offset=(20, 20))

    def strategy_has_air_strike(self):
        """
        Pages:
            in: STRATEGY_OPENED
            out: STRATEGY_OPENED
        """
        if self.match_template_color(AIR_STRIKE_ENTER, offset=(150, 200)):
            return True
        else:
            return False

    def strategy_air_strike_enter(self, skip_first_screenshot=True):
        """
        Pages:
            in: STRATEGY_OPENED, AIR_STRIKE_ENTER
            out: AIR_STRIKE_CONFIRM
        """
        logger.info("Air strike enter")
        from module.flow.runtime import run_flow

        run_flow(
            _make_wait_flow(
                "air_strike_enter",
                exit_check={"button": AIR_STRIKE_CONFIRM, "offset": (20, 20)},
                rules=[
                    {"name": "click_enter", "check": {"button": AIR_STRIKE_ENTER, "offset": (150, 200), "interval": 5},
                     "action": {"click": AIR_STRIKE_ENTER}},
                ],
            )
        )

    def strategy_air_strike_cancel(self, skip_first_screenshot=True):
        """
        Pages:
            in: AIR_STRIKE_CONFIRM
            out: STRATEGY_OPENED, AIR_STRIKE_ENTER
        """
        logger.info("Air strike cancel")
        from module.flow.runtime import run_flow

        run_flow(
            _make_wait_flow(
                "air_strike_cancel",
                exit_check={"button": AIR_STRIKE_ENTER, "offset": (150, 200)},
                rules=[
                    {"name": "click_cancel", "check": {"button": AIR_STRIKE_CANCEL, "offset": (20, 20), "interval": 5},
                     "action": {"click": AIR_STRIKE_CANCEL}},
                ],
            )
        )


def _popup(ctx, args=None, **kw):
    """strategy strategy loop helper: confirm popup with a prefixed name."""

    return ctx.owner.handle_popup_confirm(name=(args or {}).get("name", ""))
