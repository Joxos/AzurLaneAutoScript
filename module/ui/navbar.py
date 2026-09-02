from typing import Any

from module.base.timer import Timer
from module.logger import logger
from module.ui.assets_bridge import GET_ITEMS_1, GET_ITEMS_2, GET_SHIP, SHOP_CLICK_SAFE_AREA

# ---------------------------------------------------------------------------
# Navbar drive flow (B2b): `set` loop as flow data.
# ---------------------------------------------------------------------------


def _nav_done(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    nav = (args or {}).get("nav")
    active, minimum, maximum = nav.get_info(main=ctx.owner)
    logger.info(f"Nav item active: {active} from range ({minimum}, {maximum})")
    left = (args or {}).get("left")
    right = (args or {}).get("right")
    if active is None or minimum is None or maximum is None:
        ctx.params["_nav_ok"] = False
        return False
    index = minimum + left - 1 if left is not None else maximum - right + 1
    ctx.params["_nav_index"] = index
    if not minimum <= index <= maximum:
        logger.warning(f"Index to set ({index}) is not within the nav items that appears ({minimum}, {maximum})")
        ctx.params["_nav_ok"] = False
        return False
    ctx.params["_nav_ok"] = True
    return active == index


def _nav_obstruct(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    handled = (args or {}).get("nav")._shop_obstruct_handle(main=ctx.owner)
    if handled:
        # original: interval.reset(); timeout.reset(); continue
        ctx.params["_nav_interval"] = Timer(2, count=4)
    return handled


def _nav_click_ready(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    if not ctx.params.get("_nav_ok"):
        return False
    interval = ctx.params.get("_nav_interval")
    if interval is None:
        interval = Timer(2, count=4)
        ctx.params["_nav_interval"] = interval
    return interval.reached()


def _nav_click(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    nav = (args or {}).get("nav")
    ctx.owner.device.click(nav.grids.buttons[ctx.params["_nav_index"]])
    ctx.params["_nav_interval"].reset()
    return True


def _nav_set_flow(nav: "Navbar", left: int | None, right: int | None) -> dict[str, Any]:
    return {
        "name": "navbar_set",
        "entry": "s",
        "states": {
            "s": {
                "exit": {"check": {"custom": _nav_done, "args": {"nav": nav, "left": left, "right": right}},
                         "on_success": {"exit": True}},
                "rules": [
                    {"name": "obstruct", "action": {"call_if": _nav_obstruct, "args": {"nav": nav}},
                     "on_handled": {"extend_timeout": 10}},
                    {"name": "click", "check": {"custom": _nav_click_ready, "args": {"nav": nav}},
                     "action": {"call": _nav_click, "args": {"nav": nav}}},
                ],
                "on_timeout": {"seconds": 10, "count": 20, "mode": "exit", "value": False},
            },
        },
    }


class Navbar:
    def __init__(
        self,
        grids,
        active_color=(247, 251, 181),
        inactive_color=(140, 162, 181),
        active_threshold=180,
        inactive_threshold=180,
        active_count=100,
        inactive_count=50,
        name=None,
    ):
        """
        Args:
            grids (ButtonGrid):
            active_color (tuple[int, int, int]):
            inactive_color (tuple[int, int, int]):
            active_threshold (int):
            inactive_threshold (int):
            active_count (int):
            inactive_count (int):
            name (str):
        """
        self.grids = grids
        self.active_color = active_color
        self.inactive_color = inactive_color
        self.active_threshold = active_threshold
        self.inactive_threshold = inactive_threshold
        self.active_count = active_count
        self.inactive_count = inactive_count
        self.name = name if name is not None else grids._name

    def is_button_active(self, button, main):
        """
        Args:
            button (Button):
            main (ModuleBase):

        Returns:
            bool:
        """
        return main.image_color_count(
            button, color=self.active_color, threshold=self.active_threshold, count=self.active_count
        )

    def is_button_inactive(self, button, main):
        """
        Args:
            button (Button):
            main (ModuleBase):

        Returns:
            bool:
        """
        return main.image_color_count(
            button, color=self.inactive_color, threshold=self.inactive_threshold, count=self.inactive_count
        )

    def get_info(self, main):
        """
        Args:
            main (ModuleBase):

        Returns:
            int, int, int: Index of the active nav item, leftmost nav item, and rightmost nav item.
        """
        total = []
        active = []
        for index, button in enumerate(self.grids.buttons):
            if self.is_button_active(button, main=main):
                total.append(index)
                active.append(index)
            elif self.is_button_inactive(button, main=main):
                total.append(index)

        if len(active) == 0:
            # logger.warning(f'No active nav item found in {self.name}')
            active = None
        elif len(active) == 1:
            active = active[0]
        else:
            logger.warning(f"Too many active nav items found in {self.name}, items: {active}")
            active = active[0]

        if len(total) < 2:
            logger.warning(f"Too few nav items found in {self.name}, items: {total}")
        if len(total) == 0:
            left, right = None, None
        else:
            left, right = min(total), max(total)

        return active, left, right


    def get_total(self, main):
        """
        Args:
            main (ModuleBase):

        Returns:
            int: Numbers of nav items that appears
        """
        _, left, right = self.get_info(main=main)
        if left is None or right is None:
            return 0
        return right - left + 1

    def _shop_obstruct_handle(self, main):
        """
        IFF in shop, then remove obstructions
        in shop view if any

        Args:
            main (ModuleBase):

        Returns:
            bool:
        """
        # Check name, identifies if NavBar
        # instance belongs to shop module
        if self.name not in ["SHOP_BOTTOM_NAVBAR", "GUILD_SIDE_NAVBAR"]:
            return False

        # Handle shop obstructions
        if main.appear(GET_SHIP, interval=1):
            main.device.click(SHOP_CLICK_SAFE_AREA)
            return True
        if main.appear(GET_ITEMS_1, offset=(30, 30), interval=1):
            main.device.click(SHOP_CLICK_SAFE_AREA)
            return True
        if main.appear(GET_ITEMS_2, offset=(30, 30), interval=1):
            main.device.click(SHOP_CLICK_SAFE_AREA)
            return True

        return False

    def set(self, main, left=None, right=None, upper=None, bottom=None, skip_first_screenshot=True):
        """
        Set nav bar from 1 direction.

        Args:
            main (ModuleBase):
            left (int): Index of nav item counted from left. Start from 1.
            right (int): Index of nav item counted from right. Start from 1.
            upper (int): Index of nav item counted from upper. Start from 1.
            bottom (int): Index of nav item counted from bottom. Start from 1.
            skip_first_screenshot (bool):

        Returns:
            bool: If success
        """
        if left is None and right is None and upper is None and bottom is None:
            logger.warning("Invalid index to set, must set an index from 1 direction")
            return False
        text = ""
        if left is None and upper is not None:
            left = upper
        if right is None and bottom is not None:
            right = bottom
        for k in ["left", "right", "upper", "bottom"]:
            if locals().get(k, None) is not None:
                text += f"{k}={locals().get(k, None)} "
        logger.info(f"{self.name} set to {text.strip()}")

        from module.flow.engine import FlowEngine

        return bool(
            FlowEngine(owner=main, device=main.device, config=main.config, skip_first=skip_first_screenshot).run(
                _nav_set_flow(self, left, right)
            )
        )
