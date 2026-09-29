"""Double-run equivalence harness for flow migrations.

Migrating a `while 1:` loop into flow data is only safe if the new form makes
*exactly* the same device calls. This replays one recorded scenario against
both implementations and compares the action streams step by step, so "looks
equivalent" becomes a check.

The recording is a list of frames; each frame says which buttons/templates
are visible and which colour/template checks pass:

    {
      "present": ["LOGIN_CHECK"],            # appear()/match_template_color() hits
      "colors": ["MAP_CLEAR_PERCENTAGE"],    # image_color_count() hits
      "pages": ["page_main"],                # ui_page_appear() hits
      "custom": {"is_event_animation": False},   # by callable __name__
      "capabilities": ["ui_page_main_popups"],    # hasattr(owner, ...)
    }

Usage as a library:

    from dev_tools.flow_replay import Replay, compare
    old_result, new_result, diff = compare(old_flow, new_flow, scenario, owner_factory)

Usage as a CLI (prints the action stream of one implementation):

    python dev_tools/flow_replay.py <flow-factory> [scenario.json]
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass
class Call:
    """One recorded device interaction."""

    frame: int
    kind: str
    name: str = ""

    def as_tuple(self) -> tuple[int, str, str]:
        return (self.frame, self.kind, self.name)

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"f{self.frame} {self.kind}{' ' + self.name if self.name else ''}"


@dataclass
class Frame:
    """What the world looks like during one loop iteration."""

    present: set[str] = field(default_factory=set)
    colors: set[str] = field(default_factory=set)
    pages: set[str] = field(default_factory=set)
    luma: set[str] = field(default_factory=set)
    custom: dict[str, bool] = field(default_factory=dict)
    capabilities: set[str] = field(default_factory=set)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Frame:
        return cls(
            present=set(data.get("present", ())),
            colors=set(data.get("colors", ())),
            pages=set(data.get("pages", ())),
            luma=set(data.get("luma", ())),
            custom=dict(data.get("custom", {})),
            capabilities=set(data.get("capabilities", ())),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "present": sorted(self.present),
            "colors": sorted(self.colors),
            "pages": sorted(self.pages),
            "luma": sorted(self.luma),
            "custom": dict(sorted(self.custom.items())),
            "capabilities": sorted(self.capabilities),
        }


def name_of(symbol: Any) -> str:
    """The name a recording uses for a Button/Template/Page/str."""
    if isinstance(symbol, str):
        return symbol
    return getattr(symbol, "name", None) or type(symbol).__name__


class Replay:
    """A fake device + owner that replays a scenario and records every call.

    It implements the recognition surface the flow engine and the legacy loops
    use (appear / match_template_color / image_color_count / ui_page_appear /
    interval / click / swipe / sleep / image_color_button), so the *same*
    scenario drives both implementations.
    """

    # The engine's per-state timeout must not fire mid-replay; a migrated loop
    # that differs only in timeout handling still compares equal.
    def __init__(self, scenario: list[Frame], config: Any = None, max_frames: int = 200) -> None:
        self.scenario = scenario
        self.config = config
        self.max_frames = max_frames
        self.frame = 0
        self.calls: list[Call] = []
        self.ended = False
        self.intervals: dict[str, float] = {}
        self.result: Any = None

    # --- the world --------------------------------------------------------

    @property
    def current(self) -> Frame:
        index = min(self.frame, len(self.scenario) - 1)
        return self.scenario[index]

    def _record(self, kind: str, name: str = "") -> None:
        self.calls.append(Call(self.frame, kind, name))

    # --- device surface ---------------------------------------------------

    class _Device:
        def __init__(self, replay: Replay) -> None:
            self._replay = replay
            # A real (blank) frame: code that matches a template directly must
            # not crash on None, even though the replay intercepts the
            # recognizers it drives.
            import numpy as np

            self.image = np.zeros((8, 8, 3), dtype="uint8")

        def screenshot(self) -> None:
            self._replay.frame += 1
            if self._replay.frame > self._replay.max_frames:
                raise RuntimeError(f"replay exceeded {self._replay.max_frames} frames - the loop does not end")

        def click(self, button, control_check: bool = True) -> None:
            self._replay._record("click", name_of(button))

        def swipe(self, *args, **kwargs) -> None:
            self._replay._record("swipe", str(args[0]) if args else "")

        def swipe_vector(self, *args, **kwargs) -> None:
            self._replay._record("swipe_vector", str(kwargs.get("name", "")))

        def swipe_random(self, *args, **kwargs) -> None:
            self._replay._record("swipe_random", str(kwargs.get("name", "")))

        def sleep(self, seconds) -> None:
            self._replay._record("sleep", f"{seconds}")

        def get_orientation(self):
            return 0

        # Stuck detection bookkeeping (ModuleBase.appear calls it on every
        # check). It changes no game state, so it is a no-op here - recorded or
        # not, it would only add asymmetry against a replayed legacy loop that
        # never goes through ModuleBase.
        def stuck_record_add(self, button) -> None:
            pass

        def stuck_record_reset(self) -> None:
            pass

        def stuck_record_set_enabled(self, enabled) -> None:
            pass

    @property
    def device(self):
        if not hasattr(self, "_device"):
            self._device = self._Device(self)
        return self._device

    # --- owner surface ----------------------------------------------------

    def appear(self, button, offset=0, interval=0, similarity=0.85, threshold=10) -> bool:
        # The legacy loops and the flows both gate on the interval timer, so the
        # timer is part of the replayed state and not an accident of timing.
        key = name_of(button)
        if interval and not self._interval_reached(key, interval):
            return False
        return key in self.current.present

    def match_template_color(self, button, offset=(20, 20), interval=0, similarity=0.85, threshold=30) -> bool:
        return self.appear(button, interval=interval)

    def match_luma(self, button, offset=30, similarity=0.85) -> bool:
        """Luminance-only match on the whole frame (Template/Button.match_luma)."""
        return name_of(button) in self.current.luma

    def image_color_count(self, button, color, threshold=30, count=50) -> bool:
        return name_of(button) in self.current.colors

    def image_color_button(self, area, color, threshold=5, encourage=5, name=None):
        return object() if name in self.current.colors else None

    def ui_page_appear(self, page, offset=(30, 30)) -> bool:
        return name_of(page) in self.current.pages

    def image_crop(self, area, copy=True):
        return None

    def interval_reset(self, button) -> None:
        self.intervals.pop(name_of(button), None)
        self._record("interval_reset", name_of(button))

    def interval_clear(self, button) -> None:
        self._record("interval_clear", name_of(button))

    def appear_then_click(self, button, offset=0, interval=0, similarity=0.85, threshold=10, control_check=True) -> bool:
        """ModuleBase's composite: appear (with the interval timer) then click."""
        if not self.appear(button, offset=offset, interval=interval, similarity=similarity, threshold=threshold):
            return False
        self.device.click(button, control_check=control_check)
        return True

    def click_record_clear(self) -> None:
        self._record("click_record_clear")

    def click_record_add(self, button) -> None:
        self._record("click_record_add", name_of(button))

    def loop(self, timeout=None, interval=None):
        """A `for _ in self.loop()` driver.

        One iteration is one frame: the replay drives the clock here, because
        in the real code the screenshot happens inside `appear()` and a legacy
        loop that never calls `appear()` would otherwise never advance (and
        would spin forever inside the harness instead of failing).
        """
        yield
        for _ in range(self.max_frames):
            self.device.screenshot()
            yield
        raise RuntimeError(f"loop() did not finish within {self.max_frames} frames - it never exits")

    # --- plumbing ---------------------------------------------------------

    def _interval_reached(self, key: str, interval: float) -> bool:
        if interval <= 0:
            return True
        last = self.intervals.get(key)
        if last is None or self.frame - last >= max(1, int(interval)):
            self.intervals[key] = self.frame
            return True
        return False

    def __getattr__(self, item: str):
        """Capabilities and custom helpers come from the scenario."""
        if item in self.current.capabilities:
            def _capable(*args, **kwargs):
                self._record("capability", item)
                return True

            return _capable
        name = item[2:] if item.startswith("is_") else item
        if name in self.current.custom:
            def _custom(*args, **kwargs):
                self._record("custom", item)
                return self.current.custom[name]

            return _custom
        raise AttributeError(item)


def compare(
    old_run: Callable[[Any], Any],
    new_run: Callable[[Any], Any],
    scenario: list[dict[str, Any]] | list[Frame],
    config: Any = None,
    max_frames: int = 200,
) -> tuple[list[Call], list[Call], list[str]]:
    """Run both implementations over the same scenario.

    Returns (old_calls, new_calls, differences). An empty differences list
    means the two forms issue the same device calls in the same frames - the
    property a flow migration has to preserve.
    """
    frames = [f if isinstance(f, Frame) else Frame.from_dict(f) for f in scenario]

    def run_once(fn: Callable[[Any], Any]) -> tuple[list[Call], Any]:
        replay = Replay(frames, config=config, max_frames=max_frames)
        owner = replay  # the replay *is* the owner (recognition + recording)
        result = fn(owner)
        return replay.calls, result

    old_calls, old_result = run_once(old_run)
    new_calls, new_result = run_once(new_run)

    differences: list[str] = []
    for index in range(max(len(old_calls), len(new_calls))):
        left = old_calls[index].as_tuple() if index < len(old_calls) else None
        right = new_calls[index].as_tuple() if index < len(new_calls) else None
        if left != right:
            differences.append(f"call #{index}: old {left} != new {right}")
    if type(old_result) is not type(new_result) or old_result != new_result:
        differences.append(f"result: old {old_result!r} != new {new_result!r}")
    return old_calls, new_calls, differences


def format_calls(calls: list[Call]) -> str:  # pragma: no cover - display only
    return "\n".join(f"  {i:>3} {call}" for i, call in enumerate(calls))


def load_scenario(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("frames", [])
    return data


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    module_name, _, attribute = argv[1].partition(":")
    module = __import__(module_name, fromlist=["*"])
    factory = getattr(module, attribute or "make_flow")
    scenario = load_scenario(argv[2]) if len(argv) > 2 else [{}]
    frames = [Frame.from_dict(f) for f in scenario]
    replay = Replay(frames)
    result = factory()(replay)
    print(format_calls(replay.calls))
    print(f"result: {result!r} after {replay.frame} frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
