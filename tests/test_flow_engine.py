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
        # skip_first flows evaluate before the first screenshot (tick 0): treat as tick 1
        tick = max(self.device.tick, 1)
        return self.plan[min(tick - 1, len(self.plan) - 1)]

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


def test_info_handler_wait_flows_valid():
    from module.handler.info_handler import (
        _ensure_no_info_bar_flow,
        _ensure_no_story_flow,
        _info_bar_count_g,
        _simple_wait_flow,
        _wait_until_manjuu_disappear_flow,
    )

    flows = [
        _simple_wait_flow("t", {"not": {"custom": _info_bar_count_g}}),
        _ensure_no_info_bar_flow(0.6),
        _ensure_no_story_flow(),
        _wait_until_manjuu_disappear_flow(),
    ]
    for flow in flows:
        assert validate_flow(flow) == []


# ---------------------------------------------------------------------------
# B2b: ui drives (Switch/Setting/Navbar/Scroll)
# ---------------------------------------------------------------------------


class _Btn:
    def __init__(self, name):
        self.name = name


class DriveOwner(ScriptedOwner):
    def image_color_count(self, button, color=None, threshold=221, count=50):
        return getattr(button, "name", str(button)) in self._state().get("present", ())

    def swipe(self, p1, p2, name=None, distance_check=True):
        self.device.calls.append(("swipe", name))


def test_switch_set_flow_dry_run():
    from module.ui.switch import Switch

    on, off = _Btn("SW_ON"), _Btn("SW_OFF")
    sw = Switch("test")
    sw.add_state("on", on)
    sw.add_state("off", off)

    device = FakeDevice()
    plan = [{"present": ("SW_ON",)}, {"present": ("SW_OFF",)}]
    owner = DriveOwner(device, plan)
    assert sw.set("off", main=owner) is True  # clicked to toggle, then reached 'off'
    clicks = [c for c in device.calls if c[0] == "click"]
    assert any("SW_ON" in c for c in clicks)


def test_switch_wait_flow_dry_run():
    from module.ui.switch import Switch

    on = _Btn("SW_ON2")
    sw = Switch("test2")
    sw.add_state("on", on)
    device = FakeDevice()
    plan = [{"present": ()}, {"present": ("SW_ON2",)}]
    owner = DriveOwner(device, plan)
    assert sw.wait(main=owner) is True


def test_setting_flow_dry_run():
    from module.ui.setting import Setting

    a, b = _Btn("OPT_A"), _Btn("OPT_B")
    s = Setting("test")
    s.add_setting("sort", [a, b], ["a", "b"], "a")
    s.reset_first = False
    device = FakeDevice()
    owner = DriveOwner(device, [{"present": ("OPT_A",)}, {"present": ("OPT_B",)}])
    s.main = owner
    # target "b": tick1 active is a -> click b; tick2 active b -> True
    # (original Setting.set itself returned None; _set_execute is the bool source)
    assert s._set_execute(sort="b") is True
    clicks = [c for c in device.calls if c[0] == "click"]
    assert any("OPT_B" in c for c in clicks)


def test_drive_flows_valid():
    from module.ui.navbar import Navbar, _nav_set_flow
    from module.ui.scroll import Scroll, _scroll_set_flow
    from module.ui.setting import Setting, _setting_flow
    from module.ui.switch import Switch, _sw_set_flow, _sw_wait_flow

    sw = Switch("t")
    sw.add_state("on", _Btn("N1"))
    assert validate_flow(_sw_set_flow(sw, "on")) == []
    assert validate_flow(_sw_wait_flow(sw)) == []

    s = Setting("t")
    s.add_setting("sort", [_Btn("N2")], ["a"], "a")
    assert validate_flow(_setting_flow(s, {"sort": "a"})) == []

    grids = type("G", (), {"buttons": [_Btn("N3")], "_name": "g"})
    nav = Navbar(grids)
    assert validate_flow(_nav_set_flow(nav, 1, None)) == []

    scroll = Scroll((0, 0, 10, 10), (255, 255, 255))
    assert validate_flow(_scroll_set_flow(scroll, 0.5, (-0.05, 0.05), True)) == []


# ---------------------------------------------------------------------------
# Task-level execution (run_task: steps / if / sub-flow / stop)
# ---------------------------------------------------------------------------


def test_run_task_sequence_and_if():
    calls = []
    flags = {"a": True, "b": False}

    def _fa(ctx, args=None, **kw):
        calls.append("a")

    def _fb(ctx, args=None, **kw):
        calls.append("b")

    def _cond_a(ctx, args=None, **kw):
        return flags["a"]

    def _cond_b(ctx, args=None, **kw):
        return flags["b"]

    task = {
        "name": "seq",
        "steps": [
            {"if": {"check": _cond_a, "then": [{"call": _fa}]}},
            {"if": {"check": _cond_b, "then": [{"call": _fb}], "else": [{"call": _fb}]}},
            {"call": _fb},
        ],
    }
    owner = DriveOwner(FakeDevice(), [])
    result = FlowEngine(owner=owner, device=owner.device).run_task(task)
    assert result is None
    assert calls == ["a", "b", "b"]


def test_run_task_stop_value():
    def _cond(ctx, args=None, **kw):
        return True

    task = {
        "name": "stop",
        "steps": [
            {"if": {"check": _cond, "then": [{"stop": 42}]}},
            {"call": lambda ctx, args=None, **kw: None},
        ],
    }
    owner = DriveOwner(FakeDevice(), [])
    result = FlowEngine(owner=owner, device=owner.device).run_task(task)
    assert result == 42


def test_run_task_subflow_runs_on_same_device():
    engine = FlowEngine()
    device = FakeDevice()
    owner = DriveOwner(device, [{"present": ()}])
    seen = []

    def _call(ctx, args=None, **kw):
        seen.append("inner")

    def _check(ctx, args=None, **kw):
        # must run on the same engine/device the task bound
        seen.append(("tick", device.tick))
        return True

    task = {
        "name": "with_flow",
        "steps": [
            {"flow": {
                "name": "inner", "entry": "s",
                "states": {"s": {
                    "exit": {"check": {"custom": _check}, "on_success": {"exit": None}},
                    "rules": [{"name": "r", "check": {"custom": _check}, "action": {"call": _call}}],
                }},
            }},
        ],
    }
    result = engine.run_task(task, owner=owner)
    assert result is None
    assert "inner" in seen


def test_run_task_validation():
    from module.flow.model import validate_task

    assert validate_task({"name": "x", "steps": [{"call": lambda c, a=None, **k: None}]}) == []
    assert "steps" in " ".join(validate_task({"name": "x"}))
    assert validate_task({"name": "x", "steps": [{"unknown": 1}]})
    # if branch with un-callable check
    assert validate_task({"name": "x", "steps": [{"if": {"check": True, "then": []}}]})
    # stop cannot be combined
    assert validate_task({"name": "x", "steps": [{"stop": 1, "call": lambda c, a=None, **k: None}]})


def test_run_task_owner_injection_ctx():
    owner = DriveOwner(FakeDevice(), [])
    captured = {}

    def _call(ctx, args=None, **kw):
        captured["owner"] = ctx.owner

    task = {"name": "ctx", "steps": [{"call": _call}]}
    FlowEngine().run_task(task, owner=owner)
    assert captured["owner"] is owner


# ---------------------------------------------------------------------------
# Session runtime (module.flow.runtime): one engine per process
# ---------------------------------------------------------------------------


def test_runtime_singleton_and_binding():
    from module.flow.runtime import get_runtime, run_flow, set_runtime

    set_runtime(None)
    engine_a = get_runtime()
    engine_b = get_runtime()
    assert engine_a is engine_b

    device = FakeDevice()
    owner = DriveOwner(device, [{"present": ()}])
    run_flow(
        {
            "name": "lazy", "entry": "s",
            "states": {"s": {"exit": {"check": {"custom": lambda c, a=None, **k: True},
                                        "on_success": {"exit": None}},
                              "rules": []}},
        },
        owner=owner,
    )
    assert engine_a.device is device


def test_runtime_task_freebies_wiring(monkeypatch):
    """The pilot: Freebies registry entry resolves to a task flow and the
    app shell binds ONE engine (device/config) as the session runtime."""
    from alas import AzurLaneAutoScript
    from module.tasks.registry import TASK_BY_COMMAND, TASK_REGISTRY

    entry = TASK_REGISTRY["Freebies"]
    assert entry.task_flow == "make_freebies_task"
    assert TASK_BY_COMMAND["freebies"] == "Freebies"

    import module.freebies.freebies as fw

    task = getattr(fw, entry.task_flow)()
    assert task["name"] == "freebies"
    assert all(isinstance(s, dict) for s in task["steps"])
    calls = [s["call"] for s in task["steps"] if "call" in s]
    assert any(getattr(c, "__name__", "") == "_freebies_mail" for c in calls)

    # shell.flow_engine: lazily created on first access, bound to the shell's
    # device/config, and registered as the process-wide runtime.
    fake_device = FakeDevice()
    fake_config = type("C", (), {})()
    monkeypatch.setattr(AzurLaneAutoScript, "device", property(lambda self: fake_device))
    monkeypatch.setattr(AzurLaneAutoScript, "config", property(lambda self: fake_config))

    bot = AzurLaneAutoScript("registry_probe")
    engine = bot.flow_engine
    assert engine.device is fake_device
    assert engine.config is fake_config
    from module.flow.runtime import get_runtime

    assert get_runtime() is engine


def test_resolve_task_task_flow_path(monkeypatch):
    """`_resolve_task` routes a task_flow entry through the session engine
    instead of calling the legacy run() method; the task instance is owner."""
    import module.freebies.freebies as fw
    from alas import AzurLaneAutoScript

    fake_device = FakeDevice()
    fake_config = type("C", (), {"Emulator_ServerName": "probe"})()
    monkeypatch.setattr(AzurLaneAutoScript, "device", property(lambda self: fake_device))
    monkeypatch.setattr(AzurLaneAutoScript, "config", property(lambda self: fake_config))
    # avoid real Freebies.__init__ side effects
    monkeypatch.setattr(fw.Freebies, "__init__", lambda self, config=None, device=None: None)

    calls = []

    def _fake_run_task(task, *, owner=None, params=None):
        calls.append((task["name"], owner))
        return None

    bot = AzurLaneAutoScript("resolve_probe")
    monkeypatch.setattr(bot.flow_engine, "run_task", _fake_run_task)

    fn = bot._resolve_task("freebies")
    assert fn() is None
    assert calls
    assert calls[0][0] == "freebies"
    assert isinstance(calls[0][1], fw.Freebies)
