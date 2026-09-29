from typing import Any

from module.base.timer import Timer
from module.exception import ScriptError
from module.logger import logger

# ---------------------------------------------------------------------------
# Switch drive flows (B2b): `set` / `wait` loops as flow data. Helpers call
# the Switch's original primitives (get/click/handle_additional) via args;
# per-run mutable state (changed/has_unknown/current) lives in ctx.params.
# ---------------------------------------------------------------------------


def _sw_current(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> str:
    sw = (args or {}).get("sw")
    current = sw.get(main=ctx.owner)
    logger.attr(sw.name, current)
    return current


def _sw_set_done(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    """Exit check: detect current state; maintain the unknown/has_unknown logic."""
    sw = (args or {}).get("sw")
    state = (args or {}).get("state")
    current = _sw_current(ctx, args)
    ctx.params["_sw_current"] = current
    if current == state:
        return True
    if current == "unknown":
        if sw.set_unknown_timer.reached():
            logger.warning(
                f"Switch {sw.name} has states evaluated to unknown, asset should be re-verified"
            )
            ctx.params["_sw_has_unknown"] = True
            sw.set_unknown_timer.reset()
    else:
        sw.set_unknown_timer.reset()
    return False


def _sw_wait_done(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return _sw_current(ctx, args) != "unknown"


def _sw_additional(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return (args or {}).get("sw").handle_additional(main=ctx.owner)


def _sw_click_ready(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    """Known state (or unknown after has_unknown) + click timer reached."""
    sw = (args or {}).get("sw")
    current = ctx.params.get("_sw_current")
    if current == "unknown" and not ctx.params.get("_sw_has_unknown"):
        return False
    return sw.set_click_timer.reached()


def _sw_click(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    sw = (args or {}).get("sw")
    state = (args or {}).get("state")
    current = ctx.params.get("_sw_current")
    click_state = state if sw.is_selector or current == "unknown" else current
    sw.click(click_state, main=ctx.owner)
    ctx.params["_sw_changed"] = True
    sw.set_click_timer.reset()
    sw.set_unknown_timer.reset()
    return True


def _sw_set_flow(sw: "Switch", state: str) -> dict[str, Any]:
    return {
        "name": "switch_set",
        "entry": "s",
        "states": {
            "s": {
                "exit": {"check": {"custom": _sw_set_done, "args": {"sw": sw, "state": state}},
                         "on_success": {"exit": {"__var__": "_sw_changed"}}},
                "rules": [
                    {"name": "additional", "action": {"call_if": _sw_additional, "args": {"sw": sw}}},
                    {"name": "click",
                     "check": {"custom": _sw_click_ready, "args": {"sw": sw, "state": state}},
                     "action": {"call": _sw_click, "args": {"sw": sw, "state": state}}},
                ],
                # safety ceiling; original loop had none (click_timer would hang)
                "on_timeout": {"seconds": 120, "mode": "warn"},
            },
        },
    }


def _sw_wait_flow(sw: "Switch") -> dict[str, Any]:
    return {
        "name": "switch_wait",
        "entry": "s",
        "states": {
            "s": {
                "exit": {"check": {"custom": _sw_wait_done, "args": {"sw": sw}}, "on_success": {"exit": True}},
                "rules": [{"name": "additional", "action": {"call_if": _sw_additional, "args": {"sw": sw}}}],
                "on_timeout": {"seconds": 2, "count": 4, "mode": "exit", "value": False},
            },
        },
    }


class Switch:
    """
    A wrapper to handle switches in game, switch among states with retries.

    Examples:
        # Definitions
        submarine_hunt = Switch('Submarine_hunt', offset=120)
        submarine_hunt.add_state('on', check_button=SUBMARINE_HUNT_ON)
        submarine_hunt.add_state('off', check_button=SUBMARINE_HUNT_OFF)

        # Change state to ON
        submarine_view.set('on', main=self)
    """

    def __init__(self, name="Switch", is_selector=False, offset=0):
        """
        Args:
            name (str):
            is_selector (bool): True if this is a multi choice, click to choose one of the switches.
                For example: | [Daily] | Urgent | -> click -> | Daily | [Urgent] |
                False if this is a switch, click the switch itself, and it changed in the same position.
                For example: | [ON] | -> click -> | [OFF] |
        """
        self.name = name
        self.is_selector = is_selector
        self._offset = offset
        self.state_list = []
        self.set_unknown_timer = Timer(5, count=10)
        self.set_click_timer = Timer(1, count=2)
        self.wait_timeout = Timer(2, count=4)

    def add_state(self, state, check_button, click_button=None, offset=0):
        """
        Args:
            state (str): State name but cannot use 'unknown' as state name
            check_button (Button):
            click_button (Button):
            offset (bool, int, tuple):
        """
        if state == "unknown":
            raise ScriptError('Cannot use "unknown" as state name')
        self.state_list.append(
            {
                "state": state,
                "check_button": check_button,
                "click_button": click_button if click_button is not None else check_button,
                "offset": offset if offset else self._offset,
            }
        )

    @property
    def offset(self):
        return self._offset

    @offset.setter
    def offset(self, value):
        self._offset = value
        for data in self.state_list:
            data["offset"] = value

    def appear(self, main):
        """
        Args:
            main (ModuleBase):

        Returns:
            bool:
        """
        return self.get(main=main) != "unknown"

    def get(self, main):
        """
        Args:
            main (ModuleBase):

        Returns:
            str: state name or 'unknown'.
        """
        for data in self.state_list:
            if main.appear(data["check_button"], offset=data["offset"]):
                return data["state"]

        return "unknown"

    def click(self, state, main):
        """
        Args:
            state (str):
            main (ModuleBase):
        """
        button = self.get_data(state)["click_button"]
        main.device.click(button)

    def get_data(self, state):
        """
        Args:
            state (str):

        Returns:
            dict: Dictionary in add_state

        Raises:
            ScriptError: If state invalid
        """
        for row in self.state_list:
            if row["state"] == state:
                return row

        raise ScriptError(f"Switch {self.name} received an invalid state: {state}")

    def handle_additional(self, main):
        """
        Args:
            main (ModuleBase):

        Returns:
            bool: If handled
        """
        return False

    def set(self, state, main, skip_first_screenshot=True):
        """
        Args:
            state:
            main (ModuleBase):
            skip_first_screenshot (bool):

        Returns:
            bool: If clicked
        """
        from module.flow.runtime import run_flow

        logger.info(f"{self.name} set to {state}")
        self.get_data(state)

        # Original pre-loop state (timers + the `changed` return value).
        self.set_unknown_timer.reset()
        self.set_click_timer.clear()
        return bool(
            run_flow(_sw_set_flow(self, state), owner=main, skip_first=skip_first_screenshot,
                     params={"_sw_changed": False})
        )

    def wait(self, main, skip_first_screenshot=True):
        """
        Wait until any state activated

        Args:
            main (ModuleBase):
            skip_first_screenshot:

        Returns:
            bool: If success
        """
        from module.flow.runtime import run_flow

        self.wait_timeout.reset()
        return bool(
            run_flow(_sw_wait_flow(self), owner=main, skip_first=skip_first_screenshot)
        )
