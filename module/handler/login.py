
from typing import Any

from module.base.timer import Timer
from module.flow.guards import server_eq
from module.handler.assets import *  # noqa: F403  (data-bundle star import)
from module.logger import logger
from module.map.assets import *  # noqa: F403  (data-bundle star import)
from module.ui.assets import *  # noqa: F403  (data-bundle star import)
from module.ui.page import page_main
from module.ui.ui import UI

# ---------------------------------------------------------------------------
# APP_LOGIN flow data + helpers (design §3.4-A; replaces the `while 1 + if..continue`
# loop transcribed from login.py:31-94). Custom helpers are 1-3 line wrappers
# over the original handler methods via ctx.owner.
# ---------------------------------------------------------------------------


def _orientation_check(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    """Original L33-36: watch device rotation every 5s during login."""
    timer: Timer = ctx.owner._flow_orientation_timer
    if timer.reached():
        ctx.owner.device.get_orientation()
        timer.reset()
    return False  # never handled: always falls through


def _click_with_record(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    """Original L54-59: ANDROID_NO_RESPOND -> record + verify + click."""
    button = (args or {}).get("button")
    ctx.owner.device.click_record_add(button)
    ctx.owner.device.click_record_check()
    ctx.owner.device.click(button, control_check=False)
    return True


def _cn_agreement_present(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    """Original L102-118 detection: blue confirm button on the right half."""
    return (
        ctx.owner.image_color_button(
            area=(640, 360, 1280, 720), color=(78, 189, 234), color_threshold=245, encourage=25,
            name="AGREEMENT_CONFIRM",
        )
        is not None
    )


def _handle_cn_user_agreement(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.handle_cn_user_agreement()


def _popup_confirm(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.handle_popup_confirm(name=(args or {}).get("name", ""))


def _urgent_commission(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.handle_urgent_commission()


def _login_main_popups(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.ui_page_main_popups(get_ship=(args or {}).get("get_ship", True))


def make_app_login(get_ship: bool = True) -> dict[str, Any]:
    """APP_LOGIN: transcribed from the original `_handle_app_login` loop (L31-94)."""
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
                    # L33-36: orientation every 5s (never handles, falls through)
                    {"name": "orientation", "action": {"call_if": _orientation_check}},
                    # L49-53: match template color, click, do not short-circuit
                    {"name": "click_login",
                     "check": {"template": LOGIN_CHECK, "offset": (30, 30), "interval": 5},
                     "action": {"click": LOGIN_CHECK}, "stop": False},
                    # L54-59: ANDROID_NO_RESPOND -> record + click
                    {"name": "no_respond",
                     "check": {"button": ANDROID_NO_RESPOND, "offset": (30, 30), "interval": 5},
                     "action": {"call": _click_with_record, "args": {"button": ANDROID_NO_RESPOND}}},
                    {"name": "announce",
                     "check": {"button": LOGIN_ANNOUNCE, "offset": (30, 30), "interval": 5},
                     "action": {"click": LOGIN_ANNOUNCE}},
                    {"name": "announce2",
                     "check": {"button": LOGIN_ANNOUNCE_2, "offset": (30, 30), "interval": 5},
                     "action": {"click": LOGIN_ANNOUNCE_2}},
                    # L64-66: event list -> back arrow
                    {"name": "event_list",
                     "check": {"button": EVENT_LIST_CHECK, "offset": (30, 30), "interval": 5},
                     "action": {"click_and": [BACK_ARROW]}},
                    # L67-71: maintenance/update popups
                    {"name": "maintenance",
                     "check": {"button": MAINTENANCE_ANNOUNCE, "offset": (30, 30), "interval": 5},
                     "action": {"click": MAINTENANCE_ANNOUNCE}},
                    {"name": "game_update",
                     "check": {"button": LOGIN_GAME_UPDATE, "offset": (30, 30), "interval": 5},
                     "action": {"click": LOGIN_GAME_UPDATE}},
                    # L72-74: cn user agreement (wrapper keeps original method & timer)
                    {"name": "cn_agreement", "guard": server_eq("cn"),
                     "check": {"custom": _cn_agreement_present},
                     "action": {"call": _handle_cn_user_agreement}},
                    # L76-81: player-return popups
                    {"name": "return_sign",
                     "check": {"button": LOGIN_RETURN_SIGN, "offset": (30, 30), "interval": 5},
                     "action": {"click": LOGIN_RETURN_SIGN}},
                    {"name": "return_info",
                     "check": {"button": LOGIN_RETURN_INFO, "offset": (30, 30), "interval": 5},
                     "action": {"click": LOGIN_RETURN_INFO}},
                    {"name": "avatar_expired",
                     "check": {"button": AVATAR_EXPIRED, "offset": (30, 30), "interval": 5},
                     "action": {"click": AVATAR_EXPIRED}},
                    # L83-86: generic confirm popup + urgent commission (hot-fix guard inside)
                    # call_if = original `if self.handle_popup_confirm(...): continue` semantics
                    {"name": "popup_confirm", "action": {"call_if": _popup_confirm, "args": {"name": "LOGIN"}}},
                    {"name": "urgent_commission", "action": {"call_if": _urgent_commission}},
                    # L88-89: page_main popups -> handled means login done, exit True
                    {"name": "main_popups",
                     "action": {"call_if": _login_main_popups, "args": {"get_ship": get_ship}},
                     "then": {"exit": True}},
                    # L91-92: last-resort GOTO_MAIN
                    {"name": "goto_main",
                     "check": {"button": GOTO_MAIN, "offset": (30, 30), "interval": 5},
                     "action": {"click": GOTO_MAIN}},
                ],
                # original while-1 had no timeout; engine guard default (safe ceiling)
                "on_timeout": {"seconds": 120, "mode": "raise"},
            },
        },
    }


class LoginHandler(UI):
    _flow_orientation_timer = Timer(5)

    def _handle_app_login(self):
        """
        Pages:
            in: Any page
            out: page_main

        Raises:
            GameStuckError:
            GameTooManyClickError:
            GameNotRunningError:
        """
        logger.hr("App login")

        self.device.stuck_record_clear()
        self.device.click_record_clear()
        _flow_orientation_timer_reset(self)

        from module.flow.engine import FlowEngine

        return bool(
            FlowEngine(owner=self, device=self.device, config=self.config).run(make_app_login())
        )

    _user_agreement_timer = Timer(1, count=2)

    def handle_cn_user_agreement(self):
        if not self._user_agreement_timer.reached():
            return False

        right = self.image_color_button(
            area=(640, 360, 1280, 720),
            color=(78, 189, 234),
            color_threshold=245,
            encourage=25,
            name="AGREEMENT_CONFIRM",
        )
        if right is None:
            return False
        # 2026.04.17 No scroll anymore, just bare swipe before clicking confirm
        # if having blue button at right half of screen, but missing in left, it's a confirm button
        # if having both, it's a blue button at middle confirming login
        left = self.image_color_button(
            area=(0, 360, 640, 720), color=(78, 189, 234), color_threshold=245, encourage=25, name="AGREEMENT_CONFIRM"
        )
        if left is None:
            # User agreement
            # just somewhere at the middle
            box = (350, 230, 920, 430)
            self.device.swipe_vector((0, -150), box, name="AGREEMENT_SCROLL")
            self.device.swipe_vector((0, -150), box, name="AGREEMENT_SCROLL")
            self.device.click(right)
            self._user_agreement_timer.reset()
            return True
        else:
            # User login
            self.device.click(right)
            self._user_agreement_timer.reset()
            return True

    def handle_app_login(self):
        """
        Returns:
            bool: If login success

        Raises:
            GameStuckError:
            GameTooManyClickError:
            GameNotRunningError:
        """
        logger.info("handle_app_login")
        self.device.screenshot_interval_set(1.0)
        try:
            self._handle_app_login()
        finally:
            self.device.screenshot_interval_set()

    def app_stop(self):
        logger.hr("App stop")
        self.device.app_stop()

    def app_start(self):
        logger.hr("App start")
        self.device.app_start()
        self.handle_app_login()

    def app_restart(self):
        logger.hr("App restart")
        self.device.app_stop()
        self.device.app_start()
        self.handle_app_login()
        self.config.task_delay(server_update=True)


def _flow_orientation_timer_reset(owner: LoginHandler) -> None:
    """Start the flow's orientation timer fresh per login attempt."""
    owner._flow_orientation_timer.reset()
