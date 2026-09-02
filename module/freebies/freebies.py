from typing import Any

from module.base.base import ModuleBase
from module.freebies.battle_pass import BattlePass
from module.freebies.data_key import DataKey
from module.freebies.mail_white import MailWhite
from module.freebies.supply_pack import SupplyPack_250814
from module.logger import logger

# ---------------------------------------------------------------------------
# Freebies task (B4 pilot: task skeleton as data). The legacy `run()` below is
# re-expressed as a TaskSpec — ordered steps with callable checks — executed
# on the session FlowEngine (registry task_flow). Steps bind to domain
# components through ctx (config/device), not strings.
# ---------------------------------------------------------------------------


def _freebies_battle_pass_enabled(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return bool(ctx.config.BattlePass_Collect)


def _freebies_data_key_enabled(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return bool(ctx.config.DataKey_Collect)


def _freebies_supply_pack_enabled(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> bool:
    return bool(ctx.config.SupplyPack_Collect)


def _freebies_battle_pass(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> None:
    logger.hr("Battle pass", level=1)
    BattlePass(ctx.config, ctx.device).run()


def _freebies_data_key(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> None:
    logger.hr("Data key", level=1)
    DataKey(ctx.config, ctx.device).run()


def _freebies_mail(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> None:
    logger.hr("Mail", level=1)
    MailWhite(ctx.config, ctx.device).run()


def _freebies_supply_pack(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> None:
    logger.hr("Supply pack", level=1)
    SupplyPack_250814(ctx.config, ctx.device).run()


def _freebies_task_delay(ctx: Any, args: dict[str, Any] | None = None, **kw: Any) -> None:
    ctx.config.task_delay(server_update=True)


def make_freebies_task() -> dict[str, Any]:
    """TaskSpec for the Freebies scheduler task (data form of `Freebies.run`).

    Composed of ordered steps: conditional sub-task calls, then the
    server-update delay — the exact legacy `run()` skeleton, as data.
    """
    return {
        "name": "freebies",
        "steps": [
            {"if": {"check": _freebies_battle_pass_enabled, "then": [{"call": _freebies_battle_pass}]}},
            {"if": {"check": _freebies_data_key_enabled, "then": [{"call": _freebies_data_key}]}},
            {"call": _freebies_mail},
            {"if": {"check": _freebies_supply_pack_enabled, "then": [{"call": _freebies_supply_pack}]}},
            {"call": _freebies_task_delay},
        ],
    }


class Freebies(ModuleBase):
    def run(self):
        """
        Run all freebie related modules

        Legacy imperative skeleton, kept for direct callers; the scheduler
        executes `make_freebies_task()` via the session engine instead.
        """
        if self.config.BattlePass_Collect:
            logger.hr("Battle pass", level=1)
            BattlePass(self.config, self.device).run()

        if self.config.DataKey_Collect:
            logger.hr("Data key", level=1)
            DataKey(self.config, self.device).run()

        logger.hr("Mail", level=1)
        MailWhite(self.config, self.device).run()

        if self.config.SupplyPack_Collect:
            logger.hr("Supply pack", level=1)
            SupplyPack_250814(self.config, self.device).run()

        self.config.task_delay(server_update=True)
