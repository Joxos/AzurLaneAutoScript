from typing import Any

from module.base.button import Button
from module.base.decorator import run_once
from module.base.timer import Timer
from module.exception import GameNotRunningError, GamePageUnknownError, RequestHumanTakeover
from module.flow.runtime import run_group
from module.handler.info_handler import InfoHandler
from module.logger import logger
from module.ocr.ocr import Ocr
from module.ui.assets import *  # noqa: F403  (data-bundle star import)
from module.ui.assets_bridge import (
    AUTO_SEARCH_MENU_EXIT,
    AUTO_SEARCH_REWARD,
    BATTLE_PASS_NEW_SEASON,
    BATTLE_PASS_NOTICE,
    EXCHANGE_CHECK,
    EXERCISE_PREPARATION,
    FLEET_PREPARATION,
    GAME_TIPS,
    GET_ITEMS_1,
    GET_ITEMS_2,
    GET_SHIP,
    LOGIN_ANNOUNCE,
    LOGIN_ANNOUNCE_2,
    LOGIN_CHECK,
    LOGIN_RETURN_SIGN,
    MAINTENANCE_ANNOUNCE,
    MAP_PREPARATION,
    MAP_PREPARATION_CANCEL,
    MAP_PREPARATION_HARD,
    MEOWFFICER_BUY,
    MONTHLY_PASS_NOTICE,
    RAID_FLEET_PREPARATION,
    RESET_FLEET_PREPARATION,
    RESET_TICKET_POPUP,
    RPG_GOTO_STAGE,
    RPG_GOTO_STORY,
    RPG_HOME,
    RPG_LEAVE_CITY,
    WITHDRAW,
)
from module.ui.page import Page, page_academy, page_campaign, page_event, page_main, page_main_white, page_sp
from module.ui_white.assets import *  # noqa: F403  (data-bundle star import)

# ---------------------------------------------------------------------------
# Popup rule group (design §3.4-B / D9): the full ui_additional rule list as
# flow data. `popups_main(get_ship)` is injected into any flow via groups, or
# evaluated single-shot by ui_additional() below (original semantics).
# ---------------------------------------------------------------------------


def _ui_page_os_popups(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.ui_page_os_popups()


def _ui_page_main_popups(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.ui_page_main_popups(get_ship=(args or {}).get("get_ship", True))


def _story_skip(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.handle_story_skip()


def _withdraw_double_check(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    """Original L543-561: WITHDRAW double check with the 2s client-bug wait."""
    owner = ctx.owner
    if not owner.appear(WITHDRAW, offset=(30, 30), interval=3):
        return False
    owner.device.sleep(2)
    owner.device.screenshot()
    if owner.appear_then_click(WITHDRAW, offset=(30, 30)):
        owner.interval_reset(WITHDRAW)
        return True
    owner.interval_reset(WITHDRAW)
    return False


def _idle_page(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.handle_idle_page()


def popups_main(get_ship: bool = True) -> list[dict[str, Any]]:
    """The popup rule group (priority order = original ui_additional)."""
    return [
        # L486-487: page_os popups first (RESET_FLEET_PREPARATION >= 5 raises inside)
        {"name": "os_popups", "action": {"call_if": _ui_page_os_popups}},
        # L490-493
        {"name": "popup_confirm", "action": {"call_if": _popup_confirm, "args": {"name": "UI_ADDITIONAL"}}},
        {"name": "urgent_commission", "action": {"call_if": _urgent_commission}},
        # L496-497
        {"name": "main_popups", "action": {"call_if": _ui_page_main_popups, "args": {"get_ship": get_ship}}},
        # L500-501
        {"name": "story", "action": {"call_if": _story_skip}},
        # L506-509: game tips -> GOTO_MAIN
        {"name": "game_tips", "check": {"button": GAME_TIPS, "interval": 2},
         "action": {"click_and": [GOTO_MAIN]}},
        # L512-518: dorm popups
        {"name": "dorm_info", "check": {"button": DORM_INFO, "interval": 3, "similarity": 0.75},
         "action": {"click": DORM_INFO}},
        {"name": "dorm_feed_cancel", "check": {"button": DORM_FEED_CANCEL, "interval": 3},
         "action": {"click": DORM_FEED_CANCEL}},
        {"name": "dorm_trophy_confirm", "check": {"button": DORM_TROPHY_CONFIRM, "interval": 3},
         "action": {"click": DORM_TROPHY_CONFIRM}},
        # L521-528: meowfficer popups (both reset GET_SHIP interval after click)
        {"name": "meowfficer_info", "check": {"button": MEOWFFICER_INFO, "interval": 3},
         "action": {"click": MEOWFFICER_INFO, "reset_interval": [GET_SHIP]}},
        {"name": "meowfficer_buy", "check": {"button": MEOWFFICER_BUY, "interval": 3},
         "action": {"click_and": [BACK_ARROW], "reset_interval": [GET_SHIP]}},
        # L531-538: campaign preparation (any of the four) -> cancel
        {"name": "campaign_preparation",
         "check": {"or": [{"button": MAP_PREPARATION, "interval": 3},
                          {"button": MAP_PREPARATION_HARD, "interval": 3},
                          {"button": FLEET_PREPARATION, "interval": 3},
                          {"button": RAID_FLEET_PREPARATION, "interval": 3}]},
         "action": {"click": MAP_PREPARATION_CANCEL}},
        # L539-542: auto-search exit/reward popups
        {"name": "auto_search_exit", "check": {"button": AUTO_SEARCH_MENU_EXIT, "offset": (200, 30), "interval": 3},
         "action": {"click": AUTO_SEARCH_MENU_EXIT}},
        {"name": "auto_search_reward", "check": {"button": AUTO_SEARCH_REWARD, "offset": (50, 50), "interval": 3},
         "action": {"click": AUTO_SEARCH_REWARD}},
        # L543-561: WITHDRAW client-bug double check (wrapper keeps its 2s wait)
        {"name": "withdraw", "action": {"call_if": _withdraw_double_check}},
        # L563-566: login/maintenance popups
        {"name": "login_check", "check": {"button": LOGIN_CHECK, "offset": (30, 30), "interval": 3},
         "action": {"click": LOGIN_CHECK}},
        {"name": "maintenance", "check": {"button": MAINTENANCE_ANNOUNCE, "offset": (30, 30), "interval": 3},
         "action": {"click": MAINTENANCE_ANNOUNCE}},
        # L569-572: mistaken click into exercise preparation -> GOTO_MAIN
        {"name": "exercise_preparation", "check": {"button": EXERCISE_PREPARATION, "interval": 3},
         "action": {"click_and": [GOTO_MAIN]}},
        # L592-594: idle page
        {"name": "idle", "action": {"call_if": _idle_page}},
        # L596-599: white-menu switch
        {"name": "white_menu", "check": {"button": MAIN_GOTO_MEMORIES_WHITE, "interval": 3},
         "action": {"click": MAIN_TAB_SWITCH_WHITE}},
    ]


def _popup_confirm(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.handle_popup_confirm(name=(args or {}).get("name", ""))


def _urgent_commission(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return ctx.owner.handle_urgent_commission()


class UI(InfoHandler):
    ui_current: Page

    def ui_page_appear(self, page, offset=(30, 30), interval=0):
        """
        Args:
            page (Page):
            offset:
            interval:
        """
        if page == page_main:
            if self.appear(page_main_white.check_button, offset=offset, interval=interval):
                return True
            if self.appear(page_main.check_button, offset=(5, 5), interval=interval):
                return True
            return False
        # shitty EN localization changing font width of ACADEMY title,
        # check other buttons also
        if self.config.SERVER == "en" and page == page_academy:
            if self.appear(ACADEMY_GOTO_MUNITIONS, offset=offset, interval=interval):
                return True
        return self.appear(page.check_button, offset=offset, interval=interval)

    def is_in_main(self, offset=(30, 30), interval=0):
        return self.ui_page_appear(page_main, offset=offset, interval=interval)

    def ui_main_appear_then_click(self, page, offset=(30, 30), interval=3):
        """
        Args:
            page: Destination page
            offset:
            interval:

        Returns:
            bool: If clicked
        """
        if self.appear(page_main.check_button, offset=offset, interval=interval):
            button = page_main.links[page]
            self.device.click(button)
            return True
        if self.appear(page_main_white.check_button, offset=(5, 5), interval=interval):
            button = page_main_white.links[page]
            self.device.click(button)
            return True
        return False


    def ui_click(
        self,
        click_button,
        check_button,
        appear_button=None,
        additional=None,
        confirm_wait=1,
        offset=(30, 30),
        retry_wait=10,
        skip_first_screenshot=False,
    ):
        """
        Args:
            click_button (Button):
            check_button (Button, callable):
            appear_button (Button, callable):
            additional (callable):
            confirm_wait (int, float):
            offset (bool, int, tuple):
            retry_wait (int, float):
            skip_first_screenshot (bool):
        """
        logger.hr("UI click")
        if appear_button is None:
            appear_button = click_button

        click_timer = Timer(retry_wait, count=retry_wait // 0.5)
        confirm_wait = confirm_wait if additional is not None else 0
        confirm_timer = Timer(confirm_wait, count=confirm_wait // 0.5).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.ui_process_check_button(check_button, offset=offset):
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

            if click_timer.reached():
                if (isinstance(appear_button, Button) and self.appear(appear_button, offset=offset)) or (
                    callable(appear_button) and appear_button()
                ):
                    self.device.click(click_button)
                    click_timer.reset()
                    continue

            if additional is not None:
                if additional():
                    continue

    def ui_process_check_button(self, check_button, offset=(30, 30)):
        """
        Args:
            check_button (Button, callable, list[Button], tuple[Button]):
            offset:

        Returns:
            bool:
        """
        if isinstance(check_button, Button):
            return self.appear(check_button, offset=offset)
        elif callable(check_button):
            return check_button()
        elif isinstance(check_button, (list, tuple)):
            return any(self.appear(button, offset=offset) for button in check_button)
        else:
            return self.appear(check_button, offset=offset)

    def ui_get_current_page(self, skip_first_screenshot=True):
        """
        Args:
            skip_first_screenshot:

        Returns:
            Page:
        """
        logger.info("UI get current page")

        @run_once
        def app_check():
            if not self.device.app_is_running():
                raise GameNotRunningError("Game not running")

        @run_once
        def minicap_check():
            if self.config.Emulator_ControlMethod == "uiautomator2":
                self.device.uninstall_minicap()

        orientation_timer = Timer(5)

        timeout = Timer(10, count=20).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
                if not self.device.has_cached_image:
                    self.device.screenshot()
            else:
                self.device.screenshot()

            # End
            if timeout.reached():
                break

            # Known pages
            for page in Page.iter_pages():
                if page.check_button is None:
                    continue
                if self.ui_page_appear(page=page):
                    logger.attr("UI", page.name)
                    self.ui_current = page
                    return page

            # Unknown page but able to handle
            logger.info("Unknown ui page")
            if self.appear_then_click(GOTO_MAIN, offset=(30, 30), interval=2):
                timeout.reset()
                continue
            if self.appear_then_click(GOTO_MAIN_WHITE, offset=(30, 30), interval=2):
                timeout.reset()
                continue
            if self.appear_then_click(RPG_HOME, offset=(30, 30), interval=2):
                timeout.reset()
                continue
            if self.ui_additional():
                timeout.reset()
                continue

            app_check()
            minicap_check()
            # continuously check rotation
            if orientation_timer.reached():
                self.device.get_orientation()
                orientation_timer.reset()

        # Unknown page, need manual switching
        logger.warning("Unknown ui page")
        logger.attr("EMULATOR__SCREENSHOT_METHOD", self.config.Emulator_ScreenshotMethod)
        logger.attr("EMULATOR__CONTROL_METHOD", self.config.Emulator_ControlMethod)
        logger.attr("SERVER", self.config.SERVER)
        logger.warning("Starting from current page is not supported")
        logger.warning(f"Supported page: {[str(page) for page in Page.iter_pages()]}")
        logger.warning('Supported page: Any page with a "HOME" button on the upper-right')
        logger.critical("Please switch to a supported page before starting Alas")
        raise GamePageUnknownError

    def ui_goto(self, destination, get_ship=True, offset=(30, 30), skip_first_screenshot=True):
        """
        Args:
            destination (Page):
            get_ship:
            offset:
            skip_first_screenshot:
        """
        # Create connection
        Page.init_connection(destination)
        self.interval_clear(list(Page.iter_check_buttons()))

        logger.hr(f"UI goto {destination}")
        island_page_detected = False
        while 1:
            GOTO_MAIN.clear_offset()
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # Destination page
            if self.ui_page_appear(page=destination, offset=offset):
                logger.info(f"Page arrive: {destination}")
                self.ui_current = destination
                break

            # Other pages
            clicked = False
            for page in Page.iter_pages():
                if page.parent is None or page.check_button is None:
                    continue
                if self.appear(page.check_button, offset=offset, interval=5):
                    self.ui_current = page
                    island_page_detected = page.is_island() or page.parent.is_island()
                    logger.info(f"Page switch: {page} -> {page.parent}")
                    button = page.links[page.parent]
                    self.device.click(button)
                    self.ui_button_interval_reset(button)
                    clicked = True
                    break
            if clicked:
                continue

            # Additional
            if self.ui_additional(get_ship=get_ship and not island_page_detected):
                continue

        # Reset connection
        Page.clear_connection()

    def ui_ensure(self, destination, skip_first_screenshot=True):
        """
        Args:
            destination (Page):
            skip_first_screenshot:

        Returns:
            bool: If UI switched.
        """
        logger.hr("UI ensure")
        self.ui_get_current_page(skip_first_screenshot=skip_first_screenshot)
        if self.ui_current == destination:
            logger.info("Already at %s" % destination)
            return False
        else:
            logger.info("Goto %s" % destination)
            self.ui_goto(destination, skip_first_screenshot=True)
            return True

    def ui_goto_main(self):
        return self.ui_ensure(destination=page_main)

    def ui_goto_campaign(self):
        return self.ui_ensure(destination=page_campaign)

    def ui_goto_event(self):
        return self.ui_ensure(destination=page_event)

    def ui_goto_sp(self):
        return self.ui_ensure(destination=page_sp)

    def ui_ensure_index(
        self,
        index,
        letter,
        next_button,
        prev_button,
        skip_first_screenshot=False,
        fast=True,
        interval=(0.2, 0.3),
    ):
        """
        Args:
            index (int):
            letter (Ocr, callable): OCR button.
            next_button (Button):
            prev_button (Button):
            skip_first_screenshot (bool):
            fast (bool): Default true. False when index is not continuous.
            interval (tuple, int, float): Seconds between two click.
        """
        logger.hr("UI ensure index")
        retry = Timer(1, count=2)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if isinstance(letter, Ocr):
                current = letter.ocr(self.device.image)
            else:
                current = letter(self.device.image)

            logger.attr("Index", current)
            diff = index - current
            if diff == 0:
                break

            if retry.reached():
                button = next_button if diff > 0 else prev_button
                if fast:
                    self.device.multi_click(button, n=abs(diff), interval=interval)
                else:
                    self.device.click(button)
                retry.reset()

    def ui_back(self, check_button, appear_button=None, offset=(30, 30), retry_wait=10, skip_first_screenshot=False):
        return self.ui_click(
            click_button=BACK_ARROW,
            check_button=check_button,
            appear_button=appear_button,
            offset=offset,
            retry_wait=retry_wait,
            skip_first_screenshot=skip_first_screenshot,
        )

    _opsi_reset_fleet_preparation_click = 0

    def ui_page_main_popups(self, get_ship=True):
        """
        Handle popups appear at page_main, page_reward
        """
        # Guild popup
        if self.handle_guild_popup_cancel():
            return True

        # Daily reset
        if self.appear_then_click(LOGIN_ANNOUNCE, offset=(30, 30), interval=3):
            return True
        if self.appear_then_click(LOGIN_ANNOUNCE_2, offset=(30, 30), interval=3):
            return True
        if self.appear_then_click(GET_ITEMS_1, offset=True, interval=3):
            return True
        if self.appear_then_click(GET_ITEMS_2, offset=True, interval=3):
            return True
        if get_ship:
            if self.appear_then_click(GET_SHIP, offset=(20, 20), interval=5):
                return True
        if self.appear_then_click(LOGIN_RETURN_SIGN, offset=(30, 30), interval=3):
            return True
        if self.appear(EVENT_LIST_CHECK, offset=(30, 30), interval=5):
            logger.info(f"UI additional: {EVENT_LIST_CHECK} -> {GOTO_MAIN}")
            if self.appear_then_click(GOTO_MAIN, offset=(30, 30)):
                return True
        # Monthly pass is about to expire
        if self.appear_then_click(MONTHLY_PASS_NOTICE, offset=(30, 30), interval=3):
            return True
        # Battle pass is about to expire and player has uncollected battle pass rewards
        if self.appear_then_click(BATTLE_PASS_NOTICE, offset=(30, 30), interval=3):
            return True
        # Popup that advertise you to buy battle pass
        # 2024.12.19, PURCHASE_POPUP at main page becomes BATTLE_PASS_NEW_SEASON
        # if self.appear_then_click(PURCHASE_POPUP, offset=(44, -77, 84, -37), interval=3):
        #     return True
        # Popup that tells you new battle pass season is aired
        if self.appear(BATTLE_PASS_NEW_SEASON, offset=(30, 30), interval=3):
            logger.info(f"UI additional: {BATTLE_PASS_NEW_SEASON} -> {BACK_ARROW}")
            self.device.click(BACK_ARROW)
            return True
        # Item expired offset=(37, 72), skin expired, offset=(24, 68)
        if self.handle_popup_single(offset=(-6, 48, 54, 88), name="ITEM_EXPIRED"):
            return True
        # Mail full popup
        if self.handle_popup_single_white():
            return True
        # Routed from confirm click
        if self.appear(SHIPYARD_CHECK, offset=(30, 30), interval=5):
            logger.info(f"UI additional: {SHIPYARD_CHECK} -> {GOTO_MAIN}")
            if self.appear_then_click(GOTO_MAIN, offset=(30, 30)):
                return True
        if self.appear(META_CHECK, offset=(30, 30), interval=5):
            logger.info(f"UI additional: {META_CHECK} -> {GOTO_MAIN}")
            if self.appear_then_click(GOTO_MAIN, offset=(30, 30)):
                return True
        # Mistaken click
        if self.appear(PLAYER_CHECK, offset=(30, 30), interval=3):
            logger.info(f"UI additional: {PLAYER_CHECK} -> {GOTO_MAIN}")
            if self.appear_then_click(GOTO_MAIN, offset=(30, 30)):
                return True
            if self.appear_then_click(BACK_ARROW, offset=(30, 30)):
                return True

        return False

    def ui_page_os_popups(self):
        """
        Handle popups appear at page_os
        """
        # Opsi reset
        # - Opsi has reset, handle_story_skip() clicks confirm
        # - RESET_TICKET_POPUP
        # - Open exchange shop? handle_popup_confirm() click confirm
        # - EXCHANGE_CHECK, click BACK_ARROW
        if self._opsi_reset_fleet_preparation_click >= 5:
            logger.critical("Failed to confirm OpSi fleets, too many click on RESET_FLEET_PREPARATION")
            logger.critical("Possible reason #1: You haven't set any fleets in operation siren")
            logger.critical(
                "Possible reason #2: Your fleets haven't satisfied the level restrictions in operation siren"
            )
            raise RequestHumanTakeover
        if self.appear_then_click(RESET_TICKET_POPUP, offset=(30, 30), interval=3):
            return True
        if self.appear_then_click(RESET_FLEET_PREPARATION, offset=(30, 30), interval=3):
            self._opsi_reset_fleet_preparation_click += 1
            self.interval_reset(FLEET_PREPARATION)
            self.interval_reset(RESET_TICKET_POPUP)
            return True
        if self.appear(EXCHANGE_CHECK, offset=(30, 30), interval=3):
            logger.info(f"UI additional: {EXCHANGE_CHECK} -> {GOTO_MAIN}")
            GOTO_MAIN.clear_offset()
            self.device.click(GOTO_MAIN)
            return True

        return False

    def ui_additional(self, get_ship=True):
        """
        Handle all annoying popups during UI switching.

        Args:
            get_ship:
        """
        # Single-shot evaluation of the popup rule group (design D9): same
        # first-match-wins semantics as the original if-chain, now data.
        return bool(run_group(popups_main(get_ship), owner=self))

    def handle_idle_page(self):
        """
        Returns:
            bool: If handled
        """
        timer = self.get_interval_timer(IDLE, interval=3)
        if not timer.reached():
            return False
        if IDLE.match_luma(self.device.image, offset=(5, 5)):
            logger.info(f"UI additional: {IDLE} -> {REWARD_GOTO_MAIN}")
            self.device.click(REWARD_GOTO_MAIN)
            timer.reset()
            return True
        if IDLE_2.match_luma(self.device.image, offset=(5, 5)):
            logger.info(f"UI additional: {IDLE_2} -> {REWARD_GOTO_MAIN}")
            self.device.click(REWARD_GOTO_MAIN)
            timer.reset()
            return True
        if IDLE_3.match_luma(self.device.image, offset=(5, 5)):
            logger.info(f"UI additional: {IDLE_3} -> {REWARD_GOTO_MAIN}")
            self.device.click(REWARD_GOTO_MAIN)
            timer.reset()
            return True
        return False

    def ui_button_interval_reset(self, button):
        """
        Reset interval of some button to avoid mistaken clicks

        Args:
            button (Button):
        """
        if button == MEOWFFICER_GOTO_DORMMENU:
            self.interval_reset(GET_SHIP)
        if button == DORMMENU_GOTO_DORM:
            self.interval_reset(GET_SHIP)
        if button == DORMMENU_GOTO_MEOWFFICER:
            self.interval_reset(GET_SHIP)
        for switch_button in page_main.links.values():
            if button == switch_button:
                self.interval_reset(GET_SHIP)
        if button in [MAIN_GOTO_REWARD, MAIN_GOTO_REWARD_WHITE]:
            self.interval_reset(GET_SHIP)
        if button == REWARD_GOTO_TACTICAL:
            self.interval_reset(REWARD_GOTO_TACTICAL_WHITE)
        if button == REWARD_GOTO_TACTICAL_WHITE:
            self.interval_reset(REWARD_GOTO_TACTICAL)
        if button in [MAIN_GOTO_CAMPAIGN, MAIN_GOTO_CAMPAIGN_WHITE]:
            self.interval_reset(GET_SHIP)
            # Shinano event has the same title as raid
            self.interval_reset(RAID_CHECK)
        if button == SHOP_GOTO_SUPPLY_PACK:
            self.interval_reset(EXCHANGE_CHECK)
        if button in [RPG_GOTO_STAGE, RPG_GOTO_STORY, RPG_LEAVE_CITY]:
            self.interval_timer[GET_SHIP.name] = Timer(5).reset()
