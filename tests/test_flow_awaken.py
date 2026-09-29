"""The awaken flows must issue exactly the calls the loops used to.

`module/awaken/awaken.py` no longer contains the `while 1:` loop behind
`awaken_popup_close`; it is flow data now. To keep that migration honest, the
*pre-migration* loop lives here verbatim as the reference, and the recorded
scenarios are replayed through both:

    legacy  = the loop as it was on 2026-09-29
    current = module.awaken.awaken (flow data)
    trace   = every device call, per frame

A difference in the trace is a behaviour change - which is how the migration
was proved, and how a later edit that breaks it gets caught.

Both sides are driven by the same stand-in symbols, whose matchers read the
recorded scenario; the production flow takes them as parameters for exactly
this reason (the real assets do real image matching, which a replay cannot
predict).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dev_tools.flow_replay import Frame, Replay
from module.awaken.awaken import Awaken
from module.ui.page import page_dock


class FakeTemplate:
    """Stands in for a Button/Template: its matchers read the scenario."""

    def __init__(self, name: str, replay: Replay) -> None:
        self.name = name
        self._replay = replay

    def match_luma(self, image, offset=30, similarity=0.85) -> bool:
        return self._replay.match_luma(self, offset=offset, similarity=similarity)

    def match_template_color(self, image, offset=(20, 20), similarity=0.85, threshold=30) -> bool:
        return self._replay.appear(self, offset=offset, similarity=similarity, threshold=threshold)

    def match(self, image, offset=30, similarity=0.85) -> bool:
        return self._replay.appear(self, offset=offset, similarity=similarity)

    def match_luma_result(self, image, name=None):
        return None if not self.match_luma(image) else self

    def __repr__(self) -> str:
        return f"<FakeTemplate {self.name}>"


# --- the loop as it was before the migration ------------------------------


def legacy_awaken_popup_close(owner, level_check, cancel, finish, skip_first_screenshot=True):
    """Verbatim pre-migration body (the original L95-L109)."""
    owner.interval_clear(cancel)
    while 1:
        if skip_first_screenshot:
            skip_first_screenshot = False
        else:
            owner.device.screenshot()

        if level_check.match_luma(owner.device.image, similarity=0.7):
            break
        if owner.appear_then_click(cancel, offset=(20, 20), interval=3):
            continue
        if owner.appear_then_click(finish, offset=(20, 20), interval=1):
            continue


def flow_awaken_popup_close(owner, level_check, cancel, finish, skip_first_screenshot=True):
    """The migrated form: the same loop as data, plus the wrapper's bookkeeping.

    `interval_clear` is part of the shipped method (Awaken.awaken_popup_close),
    not of the loop, so both sides do it - otherwise the traces differ by a
    bookkeeping call that was never in question.
    """
    from module.flow.engine import FlowEngine
    from module.flow.runtime import set_runtime

    owner.interval_clear(cancel)
    set_runtime(None)
    flow = Awaken._awaken_popup_close_flow(
        Awaken.__new__(Awaken),
        level_check=level_check,
        cancel=cancel,
        finish=finish,
    )
    return FlowEngine(owner=owner, device=owner.device).run(flow, owner=owner, skip_first=skip_first_screenshot)


# --- scenarios ------------------------------------------------------------

POPUP_SCENARIO = [
    # Not on the awaken page yet: the loop clicks the cancel button.
    {"present": ["AWAKEN_CANCEL"]},
    {"present": ["AWAKEN_CANCEL"]},
    # The finish popup shows up first.
    {"present": ["AWAKEN_FINISH"]},
    {"present": ["AWAKEN_CANCEL"]},
    # Now we are on the page: the loop breaks.
    {"present": [], "luma": ["SHIP_LEVEL_CHECK"]},
    {"present": [], "luma": ["SHIP_LEVEL_CHECK"]},
]

# The same scenario without the interval timer, i.e. what a migration that
# dropped `interval=3` would do: click the cancel button on every frame.
POPUP_SCENARIO_NO_INTERVAL = [
    {"present": ["AWAKEN_CANCEL"]},
    {"present": ["AWAKEN_CANCEL"]},
    {"present": ["AWAKEN_FINISH", "AWAKEN_CANCEL"]},
    {"present": ["AWAKEN_CANCEL"]},
    {"present": [], "luma": ["SHIP_LEVEL_CHECK"]},
    {"present": [], "luma": ["SHIP_LEVEL_CHECK"]},
]


def _differences(old: Replay, new: Replay) -> list[str]:
    problems = []
    for index in range(max(len(old.calls), len(new.calls))):
        left = old.calls[index].as_tuple() if index < len(old.calls) else None
        right = new.calls[index].as_tuple() if index < len(new.calls) else None
        if left != right:
            problems.append(f"call #{index}: legacy {left} != flow {right}")
    return problems


def _run_pair(scenario, max_frames=40, flow_replay=Replay):
    """Replay one scenario through the legacy loop and the migrated flow.

    Both sides run against the same owner (the Replay) so the recognizers and
    the recorded call stream are identical - comparing a replay owner against
    the real ModuleBase would produce differences that are not behaviour.
    `flow_replay` exists so a test can hand the flow side a *broken* replay and
    see whether the comparison notices.
    """
    frames = [Frame.from_dict(f) for f in scenario]

    # Both sides are driven by stand-ins bound to their own replay, so the
    # recognizers and the recorded call stream are identical.
    legacy_owner = Replay(frames, max_frames=max_frames)
    legacy_awaken_popup_close(
        legacy_owner,
        level_check=FakeTemplate("SHIP_LEVEL_CHECK", legacy_owner),
        cancel=FakeTemplate("AWAKEN_CANCEL", legacy_owner),
        finish=FakeTemplate("AWAKEN_FINISH", legacy_owner),
    )

    flow_owner = flow_replay(frames, max_frames=max_frames)
    flow_awaken_popup_close(
        flow_owner,
        level_check=FakeTemplate("SHIP_LEVEL_CHECK", flow_owner),
        cancel=FakeTemplate("AWAKEN_CANCEL", flow_owner),
        finish=FakeTemplate("AWAKEN_FINISH", flow_owner),
    )
    return legacy_owner, flow_owner


def test_popup_close_migration_is_equivalent():
    old, new = _run_pair(POPUP_SCENARIO)
    problems = _differences(old, new)
    assert problems == [], problems
    # A non-empty trace on both sides, or the comparison proves nothing.
    assert [call.as_tuple() for call in old.calls]
    assert [call.as_tuple() for call in new.calls] == [call.as_tuple() for call in old.calls]
    assert any(call.kind == "click" and call.name == "AWAKEN_CANCEL" for call in new.calls)
    assert any(call.kind == "click" and call.name == "AWAKEN_FINISH" for call in new.calls)


def test_harness_detects_a_dropped_interval_guard():
    """The same scenario, but the flow side ignores the interval timer.

    A migration that forgets the 3-second interval is the most likely way to
    break these loops (the button stays visible), so the gate must catch it -
    and the gate is the harness, so the harness is checked here.
    """

    class NoIntervalReplay(Replay):
        def appear(self, button, offset=0, interval=0, similarity=0.85, threshold=10) -> bool:
            return super().appear(button, offset=offset, similarity=similarity, threshold=threshold)

    old, new = _run_pair(POPUP_SCENARIO_NO_INTERVAL, flow_replay=NoIntervalReplay)
    assert _differences(old, new), "the harness accepted a flow that acts on every frame"
    assert len(new.calls) > len(old.calls)


def test_awaken_popup_close_is_data_not_a_loop():
    """The loop must not survive as another imperative loop."""
    source = (ROOT / "module" / "awaken" / "awaken.py").read_text(encoding="utf-8")
    body = source.split("def awaken_popup_close", 1)[1]
    assert "while 1" not in body.split("\n    def ", 1)[0]

    flow = Awaken._awaken_popup_close_flow(Awaken.__new__(Awaken))
    assert set(flow["states"]) == {"wait"}
    assert [rule.get("name") for rule in flow["states"]["wait"]["rules"]] == ["cancel", "finish"]
    assert flow["states"]["wait"]["exit"]["check"]["custom"]


def test_flow_engine_supports_luma_checks():
    """The migration needed a whole-image luminance match; the engine has it."""
    from module.flow.model import CHECK_KEYS, validate_flow

    assert "luma" in CHECK_KEYS
    flow = {
        "name": "luma",
        "entry": "s",
        "states": {
            "s": {
                "exit": {"check": {"luma": "X", "similarity": 0.7}, "on_success": {"exit": True}},
                "rules": [],
            }
        },
    }
    assert validate_flow(flow) == []


def test_awaken_popup_close_runs_the_flow_through_the_production_method():
    """The shipped method is what wires the flow up; keep it covered.

    This goes through the real Awaken.awaken_popup_close (and therefore the
    real ModuleBase.appear / appear_then_click), against a replay device.
    """
    from module.flow.runtime import set_runtime

    set_runtime(None)
    calls: list[str] = []
    awaken = Awaken.__new__(Awaken)  # no Dock/Config wiring needed
    awaken.config = None  # type: ignore[assignment]
    awaken.interval_timer = {}
    awaken.interval_clear = lambda button: calls.append("interval_clear")  # type: ignore[method-assign]
    # The real ModuleBase.appear screenshots before it checks, so the page is
    # only "reached" a few frames in - the loop has to keep going until then.
    # (Frame takes keyword sets; a dict here would be silently ignored - the
    # scenario dicts go through Frame.from_dict.)
    replay = Replay(
        [Frame(), Frame(), Frame(luma={"SHIP_LEVEL_CHECK"})],
        max_frames=10,
    )
    awaken.device = replay.device  # type: ignore[assignment]

    awaken.awaken_popup_close(
        skip_first_screenshot=True,
        level_check=FakeTemplate("SHIP_LEVEL_CHECK", replay),
        cancel=FakeTemplate("AWAKEN_CANCEL", replay),
        finish=FakeTemplate("AWAKEN_FINISH", replay),
    )
    assert calls == ["interval_clear"]
    assert replay.calls == [], "nothing should be clicked once we are on the page"
    assert replay.frame >= 2, "the loop had to wait for the page"


def test_page_dock_stays_importable_for_the_remaining_loop():
    """awaken_exit is still imperative; its symbols must stay in place."""
    assert page_dock is not None
