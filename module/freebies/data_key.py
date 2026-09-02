from module.combat.assets import GET_ITEMS_1
from module.freebies.assets import *  # noqa: F403  (data-bundle star import)
from module.logger import logger
from module.ocr.ocr import DigitCounter
from module.ui.assets import CAMPAIGN_MENU_GOTO_WAR_ARCHIVES, WAR_ARCHIVES_CHECK
from module.ui.page import page_archives, page_campaign_menu
from module.ui.ui import UI

DATA_KEY = DigitCounter(OCR_DATA_KEY, letter=(255, 247, 247), threshold=64)


def _data_key_end(ctx, args=None, **kw):
    if ctx.owner.appear(WAR_ARCHIVES_CHECK, offset=(20, 20)) and ctx.owner.appear(
        DATA_KEY_COLLECTED, offset=(20, 20)
    ):
        logger.info("Data key collect finished")
        return True
    return False


def _data_key_flow():
    return {
        "name": "data_key_collect", "entry": "s",
        "states": {"s": {
            "exit": {"check": {"custom": _data_key_end}, "on_success": {"exit": None}},
            "rules": [
                {"name": "collect", "check": {"button": DATA_KEY_COLLECT, "offset": (20, 20), "interval": 3},
                 "action": {"click": DATA_KEY_COLLECT}},
                {"name": "get_items", "check": {"button": GET_ITEMS_1, "offset": 20, "interval": 3},
                 "action": {"click": DATA_KEY_COLLECT}},
                {"name": "popup_confirm", "action": {"call_if": lambda ctx, args=None, **kw:
                                                     ctx.owner.handle_popup_confirm("DATA_KEY_LIMIT")}},
                {"name": "back_to_archives",
                 "check": {"button": CAMPAIGN_MENU_GOTO_WAR_ARCHIVES, "offset": (20, 20), "interval": 3},
                 "action": {"click": CAMPAIGN_MENU_GOTO_WAR_ARCHIVES}},
            ],
            "on_timeout": {"seconds": 60, "mode": "warn"},
        }},
    }


class DataKey(UI):
    def _data_key_collect(self, skip_first_screenshot=True):
        """
        Pages:
            in: page_archives
            out: page_archives, DATA_KEY_COLLECTED
        """
        from module.flow.runtime import run_flow

        logger.hr("Data Key Collect")
        run_flow(
            _data_key_flow(), owner=self, skip_first=skip_first_screenshot
        )

    def data_key_collect(self):
        """
        Execute data key collection

        Returns:
            bool: If execute a collection.

        Pages:
            in: page_archives
        """
        if self.appear(DATA_KEY_COLLECTED, offset=(20, 20)):
            logger.info("Data key has been collected")
            return False

        current, remain, total = DATA_KEY.ocr(self.device.image)
        logger.info(f"Inventory: {current} / {total}, Remain: {remain}")
        if not self.config.DataKey_ForceCollect and remain <= 0:
            logger.info("No more room for additional data key")
            return False

        self._data_key_collect()
        return True

    def run(self):
        """
        Handle data_key operations if configured to do so.

        Pages:
            in: page_any
            out: page_main
        """
        self.ui_ensure(page_archives)

        self.data_key_collect()

        # clear interval of pages, for faster switching on the next ui_goto()
        self.interval_clear([page_archives.check_button, page_campaign_menu.check_button])
