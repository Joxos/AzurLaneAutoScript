"""FlowEngine tests: mechanics + scripted dry-runs of the P1 samples.

The engine is verified against a scripted fake owner/device (no game
screenshots), following the design's separation: the engine is pure
logic, real recognition stays in the unchanged CV2/ModuleBase code
(design §3.6).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from module.flow.engine import FlowEngine, FlowTimeoutError
from module.flow.model import FlowCtx, validate_flow


class FakeTimer:
    def __init__(self, *a, **k):
        pass

    def reached(self):
        return False

    def reset(self):
        return self


class FakeDevice:
    def __init__(self):
        self.calls: list[tuple] = []
        self.tick = 0
        self.image = None

    def screenshot(self):
        self.tick += 1
        self.calls.append(("screenshot",))

    def click(self, button, control_check=True):
        self.calls.append(("click", getattr(button, "name", button), control_check))

    def sleep(self, v):
        self.calls.append(("sleep", v))

    def click_record_add(self, button):
        self.calls.append(("record_add", getattr(button, "name", button)))

    def click_record_check(self):
        self.calls.append(("record_check",))

    def get_orientation(self):
        self.calls.append(("get_orientation",))


class ScriptedOwner:
    """Scripts per-tick appearance: plan[i] = {"present": {names...}}."""

    def __init__(self, device: FakeDevice, plan: list[dict]):
        self.device = device
        self.plan = plan
        self.config = SimpleNamespace(SERVER="cn")
        self._flow_orientation_timer = FakeTimer()

    def _state(self) -> dict:
        return self.plan[min(self.device.tick - 1, len(self.plan) - 1)]

    def appear(self, button, offset=0, interval=0, similarity=0.85, threshold=10):
        return getattr(button, "name", str(button)) in self._state().get("present", ())

    def match_template_color(self, button, offset=(20, 20), interval=0, similarity=0.85, threshold=30):
        return getattr(button, "name", str(button)) in self._state().get("present", ())

    def ui_page_appear(self, page, offset=(30, 30)):
        present = self._state().get("present", ())
        return getattr(page, "name", str(page)) in present or (
            hasattr(page, "check_button") and getattr(page.check_button, "name", None) in present
        )

    def image_crop(self, *a, **k):
        return None

    def image_color_button(self, *a, **k):
        return None

    def interval_reset(self, *a, **k):
        self.device.calls.append(("interval_reset",))

    # --- login-specific method stubs (scripted) ---
    def handle_popup_confirm(self, name=""):
        return "POPUP_CONFIRM" in self._state().get("present", ())

    def handle_urgent_commission(self):
        return False

    def ui_page_main_popups(self, get_ship=True):
        return False

    def handle_cn_user_agreement(self):
        return False


# ---------------------------------------------------------------------------
# engine mechanics
# ---------------------------------------------------------------------------


def _flow(states, groups=None, entry="entry"):
    return {"name": "t", "entry": entry, "groups": groups or [], "states": states}


def _always(ctx: FlowCtx, args=None):
    return True


def _never(ctx: FlowCtx, args=None):
    return False


def test_priority_and_stop_false():
    device = FakeDevice()
    owner = ScriptedOwner(device, [{"present": ()}] * 30)
    seen = []

    def act_a(ctx, args=None):
        seen.append("A")
        return True

    def act_b(ctx, args=None):
        seen.append("B")
        return True

    flow = _flow({
        "entry": {
            "exit": {"check": {"custom": lambda ctx, args: ctx.device.tick > 20}, "on_success": {"exit": "done"}},
            "rules": [
                {"check": {"custom": _always}, "action": {"call": act_a}, "stop": False},
                {"check": {"custom": _always}, "action": {"call": act_b}},
            ],
        },
    })
    result = FlowEngine(owner=owner, device=device).run(flow)
    assert result == "done"
    # stop=False: both rules evaluated on the same tick
    assert seen[0] == "A"
    assert seen[1] == "B"


def test_exit_confirm_counts_ticks():
    device = FakeDevice()
    owner = ScriptedOwner(device, [{"present": ()}] * 20)
    flow = _flow({
        "entry": {
            "exit": {"check": {"custom": _always}, "on_success": {"exit": True}},
            "rules": [],
        },
    })
    # no confirm -> first match exits
    assert FlowEngine(owner=owner, device=device).run(flow) is True


def test_attempts_limit_exits_false():
    device = FakeDevice()
    owner = ScriptedOwner(device, [{"present": ()}] * 30)
    calls = []

    def click_helper(ctx, args=None):
        calls.append("click")
        return False  # never active -> attempt until exceeded

    flow = _flow({
        "entry": {
            "exit": {"check": {"custom": _never}, "on_success": {"exit": True}},
            "rules": [
                {"action": {"call_if": click_helper}, "attempts": {"limit": 3, "on_exceed": {"exit": False}}},
            ],
        },
    })
    result = FlowEngine(owner=owner, device=device).run(flow)
    assert result is False
    assert len(calls) == 3


def test_call_if_handled_then_exit():
    device = FakeDevice()
    owner = ScriptedOwner(device, [{"present": ()}] * 10)

    def handled_first(ctx, args=None):
        return True

    flow = _flow({
        "entry": {"rules": [{"action": {"call_if": handled_first}, "then": {"exit": 42}}]},
    })
    assert FlowEngine(owner=owner, device=device).run(flow) == 42


def test_call_if_unhandled_does_not_stop():
    device = FakeDevice()
    owner = ScriptedOwner(device, [{"present": ()}] * 10)
    seen = []

    def popup(ctx, args=None):
        return False

    def other(ctx, args=None):
        seen.append("other")
        return True

    flow = _flow({
        "entry": {
            "exit": {"check": {"custom": _always}, "on_success": {"exit": "x"}},
            "rules": [
                {"action": {"call_if": popup}},
                {"check": {"always": True}, "action": {"call": other}},
            ],
        },
    })
    FlowEngine(owner=owner, device=device).run(flow)
    assert seen == ["other"]


def test_groups_run_before_state_rules():
    device = FakeDevice()
    owner = ScriptedOwner(device, [{"present": ()}] * 10)
    seen = []

    def group_popup(ctx, args=None):
        seen.append("group")
        return True

    flow = _flow({
        "entry": {
            "exit": {"check": {"custom": lambda ctx, args: ctx.device.tick > 5}, "on_success": {"exit": "x"}},
            "rules": [{"check": {"always": True}, "action": {"call": lambda ctx, args: seen.append("state")}}],
        },
    }, groups=[{"action": {"call_if": group_popup}}])
    FlowEngine(owner=owner, device=device).run(flow)
    assert "group" in seen
    assert "state" not in seen


def test_goto_switch_state():
    device = FakeDevice()
    owner = ScriptedOwner(device, [{"present": ()}] * 10)
    flow = _flow({
        "a": {
            "rules": [
                {"check": {"custom": _always}, "then": {"goto": "b"}},
            ],
        },
        "b": {"exit": {"check": {"custom": _always}, "on_success": {"exit": 7}}},
    }, entry="a")
    assert FlowEngine(owner=owner, device=device).run(flow) == 7


def test_validate_flow_rejects_bad_goto():
    flow = _flow({
        "a": {"rules": [{"check": {"custom": _always}, "then": {"goto": "missing"}}]},
    })
    with pytest.raises(ValueError, match="not in states"):
        FlowEngine(owner=object(), device=FakeDevice()).run(flow)


def test_timeout_raise():
    device = FakeDevice()
    owner = ScriptedOwner(device, [{"present": ()}] * 200)
    flow = _flow({
        "entry": {"rules": [], "on_timeout": {"seconds": 0.05, "count": 2, "mode": "raise"}},
    })
    with pytest.raises(FlowTimeoutError):
        FlowEngine(owner=owner, device=device).run(flow)


def test_skip_if_skips_frame():
    device = FakeDevice()
    owner = ScriptedOwner(device, [{"present": ()}] * 10)
    checks = []

    def skip_check(ctx, args=None):
        checks.append(device.tick)
        return device.tick <= 2  # skip only the first two frames

    flow = _flow({
        "entry": {
            "skip_if": {"custom": skip_check},
            "exit": {"check": {"custom": lambda ctx, args: device.tick > 3}, "on_success": {"exit": "x"}},
            "rules": [],
        },
    })
    FlowEngine(owner=owner, device=device).run(flow)
    # skipped at tick 1-2; exit check matches at 4 (immediate) + confirm needs one more access
    assert checks == [1, 2, 3, 4, 5]


def test_run_group_single_shot_semantics():
    device = FakeDevice()
    owner = ScriptedOwner(device, [{"present": ("GAME_TIPS",)}] * 5)
    seen = []

    def popup(ctx, args=None):
        seen.append("popup")
        return False

    group = [
        {"action": {"call_if": popup}},
        {"check": {"button": "GAME_TIPS", "interval": 2}, "action": {"click": "GAME_TIPS"}},
    ]
    # one pass, no screenshot; first handled rule wins
    result = FlowEngine(owner=owner, device=device).run_group(group)
    assert result is True
    assert seen == ["popup"]
    assert device.tick == 0  # run_group never screenshots


# ---------------------------------------------------------------------------
# samples: app_login + auto_search_setting_ensure
# ---------------------------------------------------------------------------


def test_app_login_flow_valid_and_dry_run():
    from module.handler.login import make_app_login

    flow = make_app_login(get_ship=False)
    assert validate_flow(flow) == []

    device = FakeDevice()
    # tick1-2: LOGIN_CHECK present; tick3+: page_main present -> exit confirm (1.5s timer)
    plan = [{"present": ("LOGIN_CHECK",)}, {"present": ("LOGIN_CHECK",)}, {"present": ("page_main",)}] + [
        {"present": ("page_main",)} for _ in range(20)
    ]
    owner = ScriptedOwner(device, plan)
    result = FlowEngine(owner=owner, device=device).run(flow)
    assert result is True
    clicks = [c for c in device.calls if c[0] == "click"]
    assert any("LOGIN_CHECK" in c for c in clicks)


def test_app_login_timeout_raises_without_main():
    from module.handler.login import make_app_login

    flow = make_app_login()
    device = FakeDevice()
    owner = ScriptedOwner(device, [{"present": ()}] * 300)
    flow["states"]["login"]["on_timeout"] = {"seconds": 0.05, "count": 2, "mode": "raise"}
    with pytest.raises(FlowTimeoutError):
        FlowEngine(owner=owner, device=device).run(flow)


def test_popups_group_valid_and_structure():
    from module.ui.ui import popups_main

    group = popups_main(get_ship=True)
    assert group
    assert isinstance(group, list)
    # the group is a list of rule dicts with either check or call_if
    for rule in group:
        assert ("check" in rule) ^ ("call_if" in rule.get("action", {}))


def test_auto_search_setting_ensure_exits_false_after_attempts():
    from module.handler.auto_search import make_auto_search_setting_ensure

    device = FakeDevice()

    class Owner(ScriptedOwner):
        def _auto_search_active_settings(self):
            return []

        def _auto_search_set_click(self, setting):
            return False

    owner = Owner(device, [{"present": ()}])
    result = FlowEngine(owner=owner, device=device).run(make_auto_search_setting_ensure("fleet1_mob_fleet2_boss"))
    assert result is False


def test_auto_search_setting_ensure_exits_true_when_active():
    from module.handler.auto_search import dic_setting_name_to_index, make_auto_search_setting_ensure

    setting = "fleet1_mob_fleet2_boss"
    target = dic_setting_name_to_index[setting]
    device = FakeDevice()

    class Owner(ScriptedOwner):
        def _auto_search_active_settings(self):
            return [target]  # already correct -> exit True first tick

        def _auto_search_set_click(self, setting):
            return True

    owner = Owner(device, [{"present": ()}])
    result = FlowEngine(owner=owner, device=device).run(make_auto_search_setting_ensure(setting))
    assert result is True
    sleeps = [c for c in device.calls if c[0] == "sleep"]
    assert sleeps == []


# ---------------------------------------------------------------------------
# B1 samples: ambush + enemy_searching
# ---------------------------------------------------------------------------


class AmbushOwner(ScriptedOwner):
    def combat_appear(self):
        return self._state().get("combat_appear", False)

    def handle_combat_low_emotion(self):
        return False

    def handle_retirement(self):
        return False

    def _handle_air_raid(self):
        pass


def test_ambush_attack_flow_valid_and_dry_run():
    from module.handler.ambush import _ambush_attack_flow

    flow = _ambush_attack_flow()
    assert validate_flow(flow) == []
    device = FakeDevice()
    plan = [{"present": ("MAP_AMBUSH_ATTACK",)}, {"present": ("MAP_AMBUSH_ATTACK",)},
            {"present": (), "combat_appear": True}]
    owner = AmbushOwner(device, plan)
    result = FlowEngine(owner=owner, device=device).run(flow)
    assert result is None  # original returns None (break on combat_appear)
    clicks = [c for c in device.calls if c[0] == "click"]
    assert any("MAP_AMBUSH_ATTACK" in c for c in clicks)


def test_air_raid_flow_valid():
    from module.handler.ambush import _air_raid_flow

    assert validate_flow(_air_raid_flow()) == []


class EnemyOwner(ScriptedOwner):
    def is_event_animation(self):
        return False

    def is_in_map(self):
        return True

    def handle_in_stage(self):
        return False

    def enemy_searching_appear(self):
        return "ENEMY_SEARCH" in self._state().get("present", ())

    def enemy_searching_color_initial(self):
        return None

    def handle_auto_search_exit(self, drop=None):
        return False

    def handle_vote_popup(self):
        return False

    def handle_story_skip(self):
        return False

    def handle_guild_popup_cancel(self):
        return False

    def handle_urgent_commission(self, drop=None):
        return False

    def handle_enemy_flashing(self):
        self.device.sleep(1.2)


def test_enemy_searching_flow_valid_and_dry_run():
    from module.handler.enemy_searching import _enemy_searching_flow

    flow = _enemy_searching_flow()
    assert validate_flow(flow) == []
    device = FakeDevice()
    # t1: nothing; t2: searching appears (waiting -> confirm); t3+: gone -> exit
    plan = [{"present": ()}, {"present": ("ENEMY_SEARCH",)}] + [{"present": ()} for _ in range(6)]
    owner = EnemyOwner(device, plan)
    result = FlowEngine(owner=owner, device=device).run(flow)
    assert result is True
