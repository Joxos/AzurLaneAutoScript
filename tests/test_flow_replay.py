"""The double-run harness must be able to fail.

A gate that cannot detect a difference is worse than no gate: it turns a
migration into a rubber stamp. These tests give the harness two deliberately
different implementations (one correct, one subtly wrong) and assert that it
tells them apart - and that two equivalent implementations compare equal.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dev_tools.flow_replay import Frame, Replay, compare, format_calls, name_of

CLICK_ONCE = [
    # a button appears on frame 2 and stays
    {"present": []},
    {"present": []},
    {"present": ["POPUP"]},
    {"present": ["POPUP"]},
]


def legacy_click_once(owner):
    """The shape being migrated: while 1 + appear + click."""
    for _ in owner.loop(timeout=2):
        if owner.appear("POPUP"):
            owner.device.click("POPUP")
            return True
    return False


def flow_click_once(owner):
    """The same loop as flow data (no engine needed to prove the harness)."""
    from module.flow.engine import FlowEngine
    from module.flow.runtime import set_runtime

    set_runtime(None)
    engine = FlowEngine(owner=owner, device=owner.device)
    # "if appear: click; return True" as data: the rule exits the flow.
    return engine.run(
        {
            "name": "click_once",
            "entry": "s",
            "states": {
                "s": {
                    "rules": [
                        {
                            "name": "popup",
                            "check": {"button": "POPUP"},
                            "action": {"click": "POPUP"},
                            "then": {"exit": True},
                        },
                    ],
                    "on_timeout": {"seconds": 5, "mode": "exit", "value": False},
                }
            },
        }
    )


def test_equivalent_implementations_compare_equal():
    old, new, differences = compare(legacy_click_once, flow_click_once, CLICK_ONCE)
    assert differences == [], differences
    # The scenario has POPUP visible from frame 2 on, and both forms click it in
    # the same frame - a per-frame mismatch is exactly what must be caught.
    assert [call.as_tuple() for call in old] == [(2, "click", "POPUP")]
    assert [call.as_tuple() for call in new] == [(2, "click", "POPUP")]
    assert format_calls(old)


def test_harness_detects_an_extra_click():
    def clicks_twice_then_stops(owner):
        clicks = 0
        for _ in owner.loop(timeout=2):
            if owner.appear("POPUP"):
                owner.device.click("POPUP")
                clicks += 1
                if clicks == 2:
                    return clicks
        return clicks

    _, _, differences = compare(legacy_click_once, clicks_twice_then_stops, CLICK_ONCE)
    assert differences, "the harness must not call these equivalent"
    assert any("click" in d for d in differences)


def test_harness_detects_a_different_result():
    def returns_something_else(owner):
        return legacy_click_once(owner) and "extra"

    _, _, differences = compare(legacy_click_once, returns_something_else, CLICK_ONCE)
    assert any("result:" in d for d in differences)


def test_harness_detects_a_different_order():
    def clicks_other_first(owner):
        for _ in owner.loop(timeout=2):
            if owner.appear("POPUP"):
                owner.device.click("SOMETHING_ELSE")
                owner.device.click("POPUP")
                return True
        return False

    _, _, differences = compare(legacy_click_once, clicks_other_first, CLICK_ONCE)
    assert any("SOMETHING_ELSE" in d for d in differences)


def test_harness_detects_a_different_frame():
    """Same clicks, one frame apart: a timing change is a behaviour change."""

    def clicks_on_the_next_frame(owner):
        for _ in owner.loop(timeout=2):
            if owner.appear("POPUP"):
                owner.device.screenshot()  # burn a frame
                owner.device.click("POPUP")
                return True
        return False

    _, _, differences = compare(legacy_click_once, clicks_on_the_next_frame, CLICK_ONCE)
    assert differences


def test_replay_refuses_to_run_a_loop_that_never_ends():
    """A migration that loses its exit condition must fail loudly."""

    def forever(owner):
        for _ in owner.loop(timeout=99):
            if owner.appear("NEVER"):
                owner.device.click("NEVER")
        return False

    replay = Replay([Frame()], max_frames=25)
    with pytest.raises(RuntimeError, match="never exits"):
        forever(replay)


def test_replay_also_bounds_screenshot_driven_loops():
    """The engine screenshots per frame, so its loops are bounded too."""

    def engine_loop_forever(owner):
        from module.flow.engine import FlowEngine

        engine = FlowEngine(owner=owner, device=owner.device)
        return engine.run(
            {
                "name": "forever",
                "entry": "s",
                "states": {"s": {"rules": [], "on_timeout": {"seconds": 3600, "mode": "warn"}}},
            }
        )

    replay = Replay([Frame()], max_frames=30)
    with pytest.raises(RuntimeError, match="exceeded"):
        engine_loop_forever(replay)


def test_interval_timers_are_part_of_the_replayed_state():
    """A flow that drops an `interval` guard acts every frame instead of every
    other one - the recording has to see that."""

    frames = [{"present": ["POPUP"]} for _ in range(4)]

    def with_interval(owner):
        for _ in owner.loop(timeout=2):
            if owner.appear("POPUP", interval=2):
                owner.device.click("POPUP")
        return False

    def without_interval(owner):
        for _ in owner.loop(timeout=2):
            if owner.appear("POPUP"):
                owner.device.click("POPUP")
        return False

    try:
        old, new, differences = compare(with_interval, without_interval, frames, max_frames=6)
    except RuntimeError:
        # The interval-free version clicked on every frame and never exited;
        # that alone is the difference the harness refused to hide.
        return
    assert differences, "dropping the interval guard must be visible"
    assert len(old) < len(new)


def test_name_of_accepts_strings_and_symbols():
    class Fake:
        name = "SOMETHING"

    assert name_of("PLAIN") == "PLAIN"
    assert name_of(Fake()) == "SOMETHING"
