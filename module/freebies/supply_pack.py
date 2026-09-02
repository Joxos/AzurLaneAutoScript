from calendar import day_name
from typing import Any

from module.base.timer import Timer
from module.campaign.campaign_status import CampaignStatus
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2
from module.config.utils import get_server_weekday
from module.freebies.assets import *  # noqa: F403  (data-bundle star import)
from module.logger import logger
from module.ocr.ocr import Digit
from module.shop.assets import SHOP_OCR_OIL, SHOP_OCR_OIL_CHECK
from module.ui.page import page_shop, page_supply_pack

# ---------------------------------------------------------------------------
# supply pack flows (B3a, cluster A + OCR T3).
# ---------------------------------------------------------------------------


def _sp_end(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    owner = ctx.owner
    supply_pack = (args or {}).get("supply_pack")
    condition = owner.appear(page_supply_pack.check_button, offset=(20, 20)) and not owner.appear(
        supply_pack, offset=(20, 20)
    )
    if not condition:
        owner._sp_confirm.reset()
        return False
    return owner._sp_confirm.reached()


def _sp_click(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    ctx.owner.device.click((args or {}).get("supply_pack"))
    ctx.owner._sp_confirm.reset()
    return True


def _sp_buy_confirm(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    owner = ctx.owner
    owner._sp_confirm.reset()
    return owner.appear_then_click(BUY_CONFIRM, offset=(20, 20), interval=3)


def _sp_popup_confirm(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    owner = ctx.owner
    supply_pack = (args or {}).get("supply_pack")
    handled = owner.handle_popup_confirm("BUY_SUPPLY_PACK")
    if handled:
        owner.interval_reset(supply_pack)
        owner.interval_reset(BUY_CONFIRM)
        ctx.params["_sp_executed"] = True
    return handled


def _supply_pack_buy_flow(supply_pack) -> dict[str, Any]:
    reset = {"reset_confirm": "_sp_confirm"}
    return {
        "name": "supply_pack_buy",
        "entry": "s",
        "states": {
            "s": {
                "exit": {"check": {"custom": _sp_end, "args": {"supply_pack": supply_pack}},
                         "on_success": {"exit": {"__var__": "_sp_executed"}}},
                "rules": [
                    {"name": "buy", "check": {"button": supply_pack, "offset": (200, 20), "interval": 3},
                     "action": {"call": _sp_click, "args": {"supply_pack": supply_pack}},
                     "attempts": {"limit": 3, "on_exceed": {"exit": {"__var__": "_sp_executed"}}}, **reset},
                    {"name": "buy_confirm", "action": {"call_if": _sp_buy_confirm}, **reset},
                    {"name": "popup_confirm",
                     "action": {"call_if": _sp_popup_confirm, "args": {"supply_pack": supply_pack}}},
                    {"name": "get_items1",
                     "check": {"button": GET_ITEMS_1, "offset": (30, 30), "interval": 3},
                     "action": {"click": GET_ITEMS_1}, **reset},
                    {"name": "get_items2",
                     "check": {"button": GET_ITEMS_2, "offset": (30, 30), "interval": 3},
                     "action": {"click": GET_ITEMS_2}, **reset},
                ],
                "on_timeout": {"seconds": 120, "mode": "warn"},
            },
        },
    }


def _oil_done(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    owner = ctx.owner
    if not owner.appear(SHOP_OCR_OIL_CHECK, offset=(10, 2)):
        return False
    ocr = Digit(SHOP_OCR_OIL, name="OCR_OIL", letter=(247, 247, 247), threshold=128)
    amount = ocr.ocr(owner.device.image)
    ctx.params["_oil_amount"] = amount
    return amount >= 100


def _get_oil_flow() -> dict[str, Any]:
    return {
        "name": "get_oil",
        "entry": "s",
        "states": {
            "s": {
                "exit": {"check": {"custom": _oil_done}, "on_success": {"exit": {"__var__": "_oil_amount"}}},
                "rules": [],
                "on_timeout": {"seconds": 1, "count": 2, "mode": "exit", "value": {"__var__": "_oil_amount"}},
            },
        },
    }


class SupplyPack(CampaignStatus):
    def supply_pack_buy(self, supply_pack, skip_first_screenshot=True):
        """
        Args:
            supply_pack (Button): Button of supply pack, click to buy.
            skip_first_screenshot (bool):

        Returns:
            bool: If bought.
        """
        from module.flow.engine import FlowEngine

        logger.hr("Supply pack buy")
        [self.interval_clear(asset) for asset in [GET_ITEMS_1, GET_ITEMS_2, supply_pack, BUY_CONFIRM]]

        logger.info(f"Buying {supply_pack}")
        self._sp_confirm = Timer(1, count=3).start()
        executed = bool(
            FlowEngine(owner=self, device=self.device, config=self.config, skip_first=skip_first_screenshot).run(
                _supply_pack_buy_flow(supply_pack), params={"_sp_executed": False}
            )
        )
        logger.info(f"Supply pack buy finished, executed={executed}")
        return executed

    def goto_supply_pack(self, skip_first_screenshot=True):
        """
        Pages:
            in: page_shop
            out: page_supply_pack, supply pack tab
        """
        self.ui_goto(page_supply_pack, skip_first_screenshot=skip_first_screenshot)

    def run(self):
        """
        Pages:
            in: Any page
            out: page_supply_pack, supply pack tab
        """
        self.ui_ensure(page_shop)
        self.goto_supply_pack()
        if self.get_oil() < 21000:
            server_today = get_server_weekday()
            target = self.config.SupplyPack_DayOfWeek
            target_name = day_name[target]
            if server_today >= target:
                self.supply_pack_buy(FREE_SUPPLY_PACK)
            else:
                logger.info(f"Delaying free week supply pack to {target_name}")
        else:
            logger.info("Oil > 21000, unable to buy free weekly supply pack")


class SupplyPack_250814(SupplyPack):
    def get_oil(self, skip_first_screenshot=True):
        """
        Returns:
            int: Oil amount
        """
        from module.flow.engine import FlowEngine

        return int(
            FlowEngine(owner=self, device=self.device, config=self.config, skip_first=skip_first_screenshot).run(
                _get_oil_flow(), params={"_oil_amount": 0}
            )
            or 0
        )

    def goto_supply_pack(self, skip_first_screenshot=True):
        """
        Pages:
            in: page_shop
            out: page_supply_pack, supply pack tab
        """
        logger.info("Goto supply pack")
        for _ in self.loop():
            if self.match_template_color(page_supply_pack.check_button, offset=(20, 20)):
                logger.info("At supply pack")
                break

            elif self.appear_then_click(page_supply_pack.check_button, offset=(20, 20), interval=3):
                continue
