from typing import Any

from module.base.decorator import cached_property
from module.base.timer import Timer
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2
from module.freebies.assets import *  # noqa: F403  (data-bundle star import)
from module.logger import logger
from module.ui.page import GOTO_MAIN_WHITE, page_mail, page_main, page_main_white
from module.ui.setting import Setting
from module.ui.ui import UI

# ---------------------------------------------------------------------------
# Mail flow helpers (B3b): the four loops as flow data.
# ---------------------------------------------------------------------------


def _mail_enter_end(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    owner = ctx.owner
    if owner.appear(MAIL_BATCH_CLAIM, offset=(20, 20)):
        logger.info("Mail entered")
        ctx.params["_mail_enter_result"] = True
        return True
    if owner.appear(MAIL_WHITE_EMPTY, offset=(20, 20)):
        logger.info("Mail empty")
        ctx.params["_mail_enter_result"] = False
        return True
    if not ctx.params.get("_mail_has_mail") and owner.appear(GOTO_MAIN_WHITE, offset=(20, 20)):
        owner._mail_enter_timeout = owner._mail_enter_timeout or Timer(0.6, count=1).start()
        if owner._mail_enter_timeout.reached():
            logger.info("Mail empty, wait GOTO_MAIN_WHITE timeout")
            ctx.params["_mail_enter_result"] = False
            return True
    owner._mail_enter_timeout = None
    return False


def _mail_manage_click(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    if ctx.owner.appear_then_click(MAIL_MANAGE, offset=(30, 30), interval=3):
        ctx.params["_mail_has_mail"] = True
    return True


def _mail_goto(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.ui_main_appear_then_click(page_mail, offset=(30, 30), interval=3)


def _mail_reward_h(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    owner = ctx.owner
    if owner.appear(GET_ITEMS_1, offset=(30, 30), interval=3):
        logger.info(f"{GET_ITEMS_1} -> {MAIL_BATCH_CLAIM}")
        owner.device.click(MAIL_BATCH_CLAIM)
        return True
    if owner.appear(GET_ITEMS_2, offset=(30, 30), interval=3):
        logger.info(f"{GET_ITEMS_2} -> {MAIL_BATCH_CLAIM}")
        owner.device.click(MAIL_BATCH_CLAIM)
        return True
    return False


def _mail_quit_end(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.ui_page_appear(page_main)


def _mail_quit_msg(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    owner = ctx.owner
    if owner.appear(MAIL_BATCH_CLAIM, offset=(30, 30), interval=3):
        logger.info(f"{MAIL_BATCH_CLAIM} -> {MAIL_MANAGE}")
        owner.device.click(MAIL_MANAGE)
        return True
    return False


def _mail_claim_done(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return bool(ctx.params.get("_mail_claimed")) and ctx.owner.appear(MAIL_BATCH_CLAIM, offset=(30, 30))


def _mail_claim_click(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    if ctx.params.get("_mail_claimed"):
        return False
    return ctx.owner.appear_then_click(MAIL_BATCH_CLAIM, offset=(30, 30), interval=3)


def _mail_claim_popup(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    handled = ctx.owner.handle_popup_confirm("MAIL_CLAIM")
    if handled:
        ctx.params["_mail_claimed"] = True
    return handled


def _mail_reward_h_claim(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    handled = _mail_reward_h(ctx, args)
    if handled:
        ctx.params["_mail_claimed"] = True
    return handled


def _mail_delete_done(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return bool(ctx.params.get("_mail_deleted")) and ctx.owner.appear(MAIL_BATCH_DELETE, offset=(30, 30))


def _mail_delete_click(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    if ctx.params.get("_mail_deleted"):
        return False
    return ctx.owner.appear_then_click(MAIL_BATCH_DELETE, offset=(30, 30), interval=3)


def _mail_delete_popup(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    handled = ctx.owner.handle_popup_confirm("MAIL_CLAIM")
    if handled:
        ctx.params["_mail_deleted"] = True
    return handled


def _mail_enter_flow() -> dict[str, Any]:
    return {
        "name": "mail_enter", "entry": "s",
        "states": {"s": {
            "exit": {"check": {"custom": _mail_enter_end},
                     "on_success": {"exit": {"__var__": "_mail_enter_result"}}},
            "rules": [
                {"name": "manage", "action": {"call_if": _mail_manage_click}},
                {"name": "goto_mail", "action": {"call_if": _mail_goto}},
                {"name": "reward", "action": {"call_if": _mail_reward_h}},
            ],
            "on_timeout": {"seconds": 60, "mode": "warn"},
        }},
    }


def _mail_quit_flow() -> dict[str, Any]:
    return {
        "name": "mail_quit", "entry": "s",
        "states": {"s": {
            "exit": {"check": {"custom": _mail_quit_end}, "on_success": {"exit": None}},
            "rules": [
                {"name": "popup_confirm", "action": {"call_if": _popup_confirm_mail_quit}},
                {"name": "batch_claim", "action": {"call_if": _mail_quit_msg}},
                {"name": "goto_main_white",
                 "check": {"button": GOTO_MAIN_WHITE, "offset": (30, 30), "interval": 3},
                 "action": {"click": GOTO_MAIN_WHITE}},
                {"name": "reward", "action": {"call_if": _mail_reward_h}},
            ],
            "on_timeout": {"seconds": 60, "mode": "warn"},
        }},
    }


def _mail_claim_flow() -> dict[str, Any]:
    return {
        "name": "mail_claim_execute", "entry": "s",
        "states": {"s": {
            "exit": {"check": {"custom": _mail_claim_done}, "on_success": {"exit": None}},
            "rules": [
                {"name": "claim", "action": {"call_if": _mail_claim_click}},
                {"name": "popup_confirm", "action": {"call_if": _mail_claim_popup}},
                {"name": "reward", "action": {"call_if": _mail_reward_h_claim}},
            ],
            "on_timeout": {"seconds": 60, "mode": "warn"},
        }},
    }


def _mail_delete_flow() -> dict[str, Any]:
    return {
        "name": "mail_delete", "entry": "s",
        "states": {"s": {
            "exit": {"check": {"custom": _mail_delete_done}, "on_success": {"exit": None}},
            "rules": [
                {"name": "delete", "action": {"call_if": _mail_delete_click}},
                {"name": "popup_confirm", "action": {"call_if": _mail_delete_popup}},
                {"name": "reward", "action": {"call_if": _mail_reward_h}},
            ],
            "on_timeout": {"seconds": 60, "mode": "warn"},
        }},
    }


def _popup_confirm_mail_quit(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.handle_popup_confirm("MAIL_QUIT")


class MailSelectSetting(Setting):
    def is_option_active(self, option: Button) -> bool:
        return self.main.image_color_count(option, color=(57, 56, 57), threshold=221, count=50)


class MailWhite(UI):
    @cached_property
    def mail_select_setting(self):
        setting = MailSelectSetting("Mail", main=self)
        setting.reset_first = False
        setting.need_deselect = True
        setting.add_setting(
            setting="contains",
            option_buttons=[MAIL_SELECT_CUBE, MAIL_SELECT_COINS, MAIL_SELECT_OIL, MAIL_SELECT_MERIT, MAIL_SELECT_GEMS],
            option_names=["cube", "coins", "oil", "merit", "gems"],
            option_default="merit",
        )
        return setting

    @cached_property
    def mail_select_all_setting(self):
        setting = MailSelectSetting("MailAll", main=self)
        setting.reset_first = False
        setting.add_setting(setting="all", option_buttons=[MAIL_SELECT_ALL], option_names=["all"], option_default="all")
        return setting

    def _mail_enter(self, skip_first_screenshot=True):
        """
        Returns:
            int: If having mails

        Page:
            in: page_main_white or MAIL_MANAGE
            out: MAIL_BATCH_CLAIM
        """
        from module.flow.engine import FlowEngine

        logger.info("Mail enter")
        self.interval_clear([MAIL_MANAGE])
        self._mail_enter_timeout = None
        return bool(
            FlowEngine(owner=self, device=self.device, config=self.config, skip_first=skip_first_screenshot).run(
                _mail_enter_flow(), params={"_mail_enter_result": False, "_mail_has_mail": False}
            )
        )

    def _mail_quit(self, skip_first_screenshot=True):
        """
        Page:
            in: Any page in page_mail
            out: page_main_white
        """
        from module.flow.engine import FlowEngine

        logger.info("Mail quit")
        self.interval_clear(
            [
                MAIL_BATCH_CLAIM,
                GOTO_MAIN_WHITE,
                GET_ITEMS_1,
                GET_ITEMS_2,
            ]
        )
        self.popup_interval_clear()
        FlowEngine(owner=self, device=self.device, config=self.config, skip_first=skip_first_screenshot).run(
            _mail_quit_flow()
        )

    def _handle_mail_reward(self):
        if self.appear(GET_ITEMS_1, offset=(30, 30), interval=3):
            logger.info(f"{GET_ITEMS_1} -> {MAIL_BATCH_CLAIM}")
            self.device.click(MAIL_BATCH_CLAIM)
            return True
        if self.appear(GET_ITEMS_2, offset=(30, 30), interval=3):
            logger.info(f"{GET_ITEMS_2} -> {MAIL_BATCH_CLAIM}")
            self.device.click(MAIL_BATCH_CLAIM)
            return True
        return False

    def _mail_claim_execute(self, skip_first_screenshot=True):
        """
        Page:
            in: MAIL_BATCH_CLAIM
            out: page_main_white, may have info_bar

        Returns:
            int: If success to claim
        """
        from module.flow.engine import FlowEngine

        self.handle_info_bar()
        self.interval_clear(
            [
                MAIL_BATCH_CLAIM,
                GET_ITEMS_1,
                GET_ITEMS_2,
            ]
        )
        self.popup_interval_clear()

        FlowEngine(owner=self, device=self.device, config=self.config, skip_first=skip_first_screenshot).run(
            _mail_claim_flow(), params={"_mail_claimed": False}
        )

        success = self.info_bar_count() > 0
        logger.info(f"Mail claim success: {success}")
        return success

    def _mail_delete(self, skip_first_screenshot=True):
        """
        Pages:
            in: MAIL_BATCH_DELETE
            out: MAIL_BATCH_DELETE
        """
        from module.flow.engine import FlowEngine

        self.handle_info_bar()
        self.interval_clear([MAIL_BATCH_DELETE])
        self.popup_interval_clear()

        FlowEngine(owner=self, device=self.device, config=self.config, skip_first=skip_first_screenshot).run(
            _mail_delete_flow(), params={"_mail_deleted": False}
        )

        # info_bar appears if mail success to delete and no mail deleted
        return True

    def mail_claim(
        self,
        merit=True,
        maintenance=False,
        trade_license=False,
        delete=True,
    ):
        """
        Pages:
            in: page_main_white or MAIL_MANAGE
            out: MAIL_BATCH_CLAIM
        """
        if not self._mail_enter():
            return

        if merit:
            logger.hr("Mail merit", level=2)
            self._mail_enter()
            self.mail_select_setting.set(contains=["merit"])
            self._mail_claim_execute()
        if maintenance:
            logger.hr("Mail maintenance", level=2)
            self._mail_enter()
            self.mail_select_setting.set(contains=["coins", "oil"])
            self._mail_claim_execute()
            self._mail_enter()
            self.mail_select_setting.set(contains=["coins", "oil", "gems"])
            self._mail_claim_execute()
        if trade_license:
            logger.hr("Mail trade license", level=2)
            self._mail_enter()
            self.mail_select_setting.set(contains=["coins", "oil", "cube"])
            self._mail_claim_execute()
        if delete:
            logger.hr("Mail delete", level=2)
            self._mail_enter()
            self.mail_select_all_setting.set(contains=["all"])
            self._mail_delete()

        self._mail_quit()

    def run(self):
        merit = self.config.Mail_ClaimMerit
        maintenance = self.config.Mail_ClaimMaintenance
        trade_license = self.config.Mail_ClaimTradeLicense
        delete = self.config.Mail_DeleteCollected
        logger.info(
            f"Mail reward: merit={merit}, maintenance={maintenance}, trade_license={trade_license}, delete={delete}"
        )
        if not merit and not maintenance and not trade_license:
            logger.warning("Nothing to claim")
            return False

        # Must using white UI
        self.ui_ensure(page_main)
        if self.appear(page_main_white.check_button, offset=(30, 30)):
            logger.info("At page_main_white")
            pass
        elif self.appear(page_main.check_button, offset=(5, 5)):
            logger.info("At page_main")
            pass
        else:
            logger.warning("Unknown page_main, cannot enter mail page")
            return False

        # Claim
        self.mail_claim(
            merit=merit,
            maintenance=maintenance,
            trade_license=trade_license,
            delete=delete,
        )
        return True
