"""FlowEngine: the shared execution core for UI/business loops.

Implements the §3.0 evaluation cycle (skip_if → exit guard → group rules →
state rules → timeout) over declarative Flow data. Builtin checks/actions
resolve to ModuleBase/Device APIs so existing behavior maps 1:1; custom
checks/actions are callable objects bound through `FlowCtx` (D13/D14).
"""

from __future__ import annotations

from typing import Any

from module.base.timer import Timer
from module.flow.model import FlowCtx, validate_flow
from module.logger import logger

EXIT = "__exit__"


class FlowTimeoutError(RuntimeError):
    """Raised by a state whose `on_timeout` mode is "raise"."""


# Defaults for state timeout when on_timeout is a bare mode string.
_DEFAULT_TIMEOUT = (60.0, 120)
# Timer count approximation for timeout seconds (screenshot ~0.5s; Timer.from_seconds convention).
_SPEED = 0.5


def _timer(seconds: float, count: int | None = None) -> Timer:
    if count is None:
        count = max(1, int(seconds / _SPEED))
    return Timer(seconds, count=count)


class FlowEngine:
    """Runs one Flow against a domain `owner` (handler instance)."""

    def __init__(
        self,
        owner: Any,
        device: Any = None,
        config: Any = None,
        *,
        skip_first: bool = False,
    ) -> None:
        self.owner = owner
        self.device: Any = (
            device if device is not None else getattr(owner, "device", None)
        )
        self.config: Any = config if config is not None else getattr(owner, "config", None)
        self.skip_first = skip_first
        # per-state exit-confirm timers (inactive until the exit check matches)
        self._exit_timers: dict[str, Timer | None] = {}

    # ------------------------------------------------------------- running --

    def run(self, flow: dict[str, Any], params: dict[str, Any] | None = None, entry: str | None = None) -> Any:
        errors = validate_flow(flow)
        if errors:
            raise ValueError(f"invalid flow {flow.get('name')!r}: " + "; ".join(errors))

        states = flow["states"]
        ctx = FlowCtx(device=self.device, config=self.config, owner=self.owner, params=params or {})
        groups: list[dict[str, Any]] = flow.get("groups", [])
        attempts: dict[int, Any] = {}  # rule-id -> {"spec", "count", "exceeded"}
        self._exit_timers.clear()

        state_holder = [entry or flow.get("entry") or next(iter(states))]
        timeout_holder = [self._make_timeout(states[state_holder[0]])]

        def apply(control: Any) -> Any:
            """Return a flow exit value, or None to keep looping (switches included)."""
            routed = self._route(control)
            if routed is None:
                return None
            kind, value = routed
            if kind == "exit":
                return value
            if value == EXIT:
                return None
            # state switch
            state_holder[0] = value
            timeout_holder[0] = self._make_timeout(states[value])
            self._exit_timers.clear()
            self._log(f"state switch -> {value}")
            return None

        tick = 0
        while True:
            tick += 1
            if not (self.skip_first and tick == 1):
                self.device.screenshot()

            state = states[state_holder[0]]

            # 1. whole-frame skip (original `is_event_animation(): continue`)
            if state.get("skip_if") and self._check(state["skip_if"], ctx):
                continue

            # 2. exit guard (original "End" block at the top of the loop)
            if state.get("exit") is not None:
                result = apply(self._tick_exit(state_holder[0], state["exit"], ctx))
                if result is not None:
                    return result

            # 3-4. group rules then state rules, in priority order
            for rule in [*groups, *state.get("rules", [])]:
                if not self._guard_ok(rule.get("guard"), ctx):
                    continue
                key = id(rule)
                att_spec = rule.get("attempts")
                att = attempts.get(key)
                if att_spec is not None:
                    att = att or {"spec": att_spec, "count": 0, "exceeded": False}
                    attempts[key] = att
                    if att["count"] >= att_spec.get("limit", 1):
                        if not att["exceeded"]:
                            att["exceeded"] = True
                            self._log(f"state={state_holder[0]} attempts exceeded ({att_spec.get('limit')})")
                            result = apply(self._apply_control(att_spec.get("on_exceed"), ctx))
                            if result is not None:
                                return result
                        continue

                matched = False
                action = rule.get("action")
                auto_done = False
                auto_handled = False
                if action and "call_if" in action:
                    # Side-effecting helper semantics (original `if handler(): continue`):
                    # the call both detects and acts; it always "runs" (attempts count),
                    # its truthiness decides stop/then (original `continue` vs fall-through).
                    auto_handled = bool(action["call_if"](ctx, action.get("args") or {}))
                    matched = True
                    auto_done = True
                else:
                    matched = self._check(rule.get("check"), ctx) if rule.get("check") is not None else True
                if not matched:
                    continue
                if att_spec is not None:
                    if att is None:
                        att = {"spec": att_spec, "count": 0, "exceeded": False}
                        attempts[key] = att
                    att["count"] += 1

                self._log(f"state={state_holder[0]} hit rule={rule.get('name') or ('attempts' if att_spec else '#')}")
                result = None
                if not auto_done:
                    result = self._action(action, ctx)
                if auto_done:
                    control = self._apply_control(rule.get("then"), ctx) if auto_handled else None
                else:
                    control = result if result is not None else self._apply_control(rule.get("then"), ctx)
                self._reset_intervals(action, ctx)
                if rule.get("on_handled", {}).get("extend_timeout"):
                    timeout_holder[0] = _timer(rule["on_handled"]["extend_timeout"]).start()

                result = apply(control)
                if result is not None:
                    return result
                effective_stop = rule.get("stop", True)
                if auto_done:
                    effective_stop = effective_stop and auto_handled
                if effective_stop:
                    break
                # stop=False (or call_if unhandled): keep evaluating lower-priority rules

            # 5. state timeout
            if timeout_holder[0] is not None and timeout_holder[0].reached():
                result = apply(self._apply_timeout(state_holder[0], state.get("on_timeout"), ctx))
                if result is not None:
                    return result
                timeout_holder[0] = timeout_holder[0].reset()

    def run_group(self, group: list[dict[str, Any]], params: dict[str, Any] | None = None) -> bool:
        """Single-shot group evaluation (original `ui_additional` semantics).

        One pass over the rules against the current image (no screenshot):
        the first rule that handles/executes wins and returns True, exactly
        like the original `if ...: return True` chain.
        """
        ctx = FlowCtx(device=self.device, config=self.config, owner=self.owner, params=params or {})
        for rule in group:
            if not self._guard_ok(rule.get("guard"), ctx):
                continue
            action = rule.get("action")
            if action and "call_if" in action:
                if action["call_if"](ctx, action.get("args") or {}):
                    self._reset_intervals(action, ctx)
                    return True
                continue
            if rule.get("check") is None or self._check(rule.get("check"), ctx):
                if action:
                    self._action(action, ctx)
                    self._reset_intervals(action, ctx)
                return True
        return False

    # ------------------------------------------------------------- routing --

    def _route(self, result: Any) -> tuple[str, Any] | None:
        """Normalize an exit/goto control value. Bare values exit the flow."""
        if result is None:
            return None
        if isinstance(result, tuple) and len(result) == 2 and result[0] in ("exit", "goto"):
            if result[0] == "goto" and result[1] == EXIT:
                return ("exit", None)
            return result
        return ("exit", result)

    # ------------------------------------------------------------- helpers --

    def _log(self, message: str) -> None:
        logger.info(f"[flow] {message}")

    def _make_timeout(self, state: dict[str, Any]) -> Timer | None:
        spec = state.get("on_timeout")
        if spec is None:
            return None
        if isinstance(spec, dict):
            seconds = spec.get("seconds") or _DEFAULT_TIMEOUT[0]
            count = spec.get("count")
            if spec.get("mode") == "warn_proceed":
                return _timer(seconds, count)
            return _timer(seconds, count).start()
        return _timer(*_DEFAULT_TIMEOUT).start()

    def _tick_exit(self, state_name: str, exit_spec: dict[str, Any], ctx: FlowCtx) -> Any:
        confirm = exit_spec.get("confirm") or {}
        if not self._check(exit_spec["check"], ctx):
            self._exit_timers[state_name] = None
            return None
        timer = self._exit_timers.get(state_name)
        if timer is None:
            timer = _timer(confirm.get("seconds", 0.0), confirm.get("count")).start()
            self._exit_timers[state_name] = timer
        if timer.reached():
            self._log(f"state={state_name} exit ✓")
            return self._apply_control(exit_spec.get("on_success"), ctx) or True
        return None

    def _guard_ok(self, guard: Any, ctx: FlowCtx) -> bool:
        if guard is None:
            return True
        if isinstance(guard, (list, tuple)):
            return all(self._guard_ok(g, ctx) for g in guard)
        return bool(guard(ctx, {}))

    def _apply_control(self, control: Any, ctx: FlowCtx) -> Any:
        if control is None:
            return None
        if isinstance(control, str):
            return ("exit", control)
        if isinstance(control, dict):
            if "goto" in control:
                return ("goto", control["goto"])
            if "exit" in control or "value" in control:
                return ("exit", control.get("value", control.get("exit")))
        raise ValueError(f"bad control spec: {control!r}")

    def _apply_timeout(self, state_name: str, spec: Any, ctx: FlowCtx) -> Any:
        mode = spec if isinstance(spec, str) else (spec or {}).get("mode") or "raise"
        spec_dict = spec if isinstance(spec, dict) else {}
        self._log(f"state={state_name} timeout ({mode})")
        if mode == "warn":
            return ("exit", None)
        if mode == "warn_proceed":
            return ("goto", state_name)
        if mode == "goto":
            return ("goto", spec_dict.get("goto"))
        if mode == "exit":
            return ("exit", spec_dict.get("value"))
        raise FlowTimeoutError(f"flow timeout at state {state_name}")

    # ------------------------------------------------------------- checks --

    def _check(self, spec: Any, ctx: FlowCtx) -> bool:
        if spec is None:
            return False
        if "always" in spec:
            return bool(spec["always"])
        if "not" in spec:
            return not self._check(spec["not"], ctx)
        if "and" in spec:
            return all(self._check(s, ctx) for s in spec["and"])
        if "or" in spec:
            return any(self._check(s, ctx) for s in spec["or"])
        if "custom" in spec:
            return bool(spec["custom"](ctx, spec.get("args") or {}))
        if "capability" in spec:
            return hasattr(self.owner, spec["capability"])
        if "page" in spec:
            return self._check_page(spec["page"], spec.get("offset"), ctx)
        if "button" in spec:
            return self.owner.appear(
                spec["button"],
                offset=spec.get("offset", 0),
                interval=spec.get("interval", 0),
                similarity=spec.get("similarity", 0.85),
                threshold=spec.get("threshold", 10),
            )
        if "template" in spec:
            return self._check_template(spec, ctx)
        if "color" in spec:
            return self._check_color(spec["color"], ctx)
        raise ValueError(f"unknown check spec: {sorted(spec)}")

    def _check_page(self, page: Any, offset: Any, ctx: FlowCtx) -> bool:
        if isinstance(page, dict):
            return any(self._check_page(p, offset, ctx) for p in page.get("any", []))
        pages = page if isinstance(page, (list, tuple)) else [page]
        for p in pages:
            if hasattr(self.owner, "ui_page_appear"):
                if self.owner.ui_page_appear(p, offset=offset if offset is not None else (30, 30)):
                    return True
            elif self.owner.appear(p.check_button, offset=offset if offset is not None else (30, 30)):
                return True
        return False

    def _check_template(self, spec: dict[str, Any], ctx: FlowCtx) -> bool:
        button = spec["template"]
        if spec.get("crop") is not None:
            image = self.owner.image_crop(spec["crop"], copy=False)
            if spec.get("pre"):
                image = spec["pre"](image)
            return button.match(image, offset=spec.get("offset", 0), similarity=spec.get("similarity", 0.85))
        return self.owner.match_template_color(
            button,
            offset=spec.get("offset", (20, 20)),
            interval=spec.get("interval", 0),
            similarity=spec.get("similarity", 0.85),
            threshold=spec.get("threshold", 30),
        )

    def _check_color(self, spec: dict[str, Any], ctx: FlowCtx) -> bool:
        if "area" in spec:
            return self.owner.image_color_count(
                spec["area"], color=spec["color"], threshold=spec.get("threshold", 221), count=spec.get("count", 50)
            )
        return self.owner.image_color_count(
            spec["button"], color=spec["color"], threshold=spec.get("threshold", 221), count=spec.get("count", 50)
        )

    # ------------------------------------------------------------ actions --

    def _action(self, spec: Any, ctx: FlowCtx) -> Any:
        if spec is None:
            return None
        if "click" in spec:
            self.owner.device.click(spec["click"], control_check=spec.get("control_check", True))
            return None
        if "click_and" in spec:
            for b in spec["click_and"]:
                self.owner.device.click(b)
            return None
        if "ensure_click" in spec:
            self._ensure_click(spec["ensure_click"], ctx)
            return None
        if "sleep" in spec:
            self.owner.device.sleep(spec["sleep"])
            return None
        if "wait_appear" in spec:
            self._wait(spec["wait_appear"], expect=True, ctx=ctx)
            return None
        if "wait_disappear" in spec:
            self._wait(spec["wait_disappear"], expect=False, ctx=ctx)
        if "call" in spec:
            spec["call"](ctx, spec.get("args") or {})
            return None
        if "goto" in spec:
            if spec["goto"] == EXIT:
                return ("exit", spec.get("value"))
            return ("goto", spec["goto"])
        if "raise" in spec:
            raise spec["raise"]
        raise ValueError(f"unknown action spec: {sorted(spec)}")

    def _reset_intervals(self, spec: Any, ctx: FlowCtx) -> None:
        if spec and spec.get("reset_interval"):
            for button in spec["reset_interval"]:
                self.owner.interval_reset(button)

    def _ensure_click(self, spec: dict[str, Any], ctx: FlowCtx) -> None:
        """ui_click semantics: click until confirmed, with retry/confirm timers."""
        click_button = spec["click"]
        check = spec["check"]
        appear = spec.get("appear") or click_button
        confirm_wait = spec.get("confirm_wait", 1)
        retry_wait = spec.get("retry_wait", 10)
        additional = spec.get("additional")
        confirm_timer = Timer(confirm_wait).start()
        click_timer = Timer(retry_wait)
        while True:
            self.device.screenshot()
            checked = bool(check(ctx, {})) if callable(check) else self._check({"button": check}, ctx)
            if checked:
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()
            if click_timer.reached():
                appear_ok = bool(appear(ctx, {})) if callable(appear) else self._check({"button": appear}, ctx)
                if appear_ok:
                    self.owner.device.click(click_button)
                    click_timer.reset()
            if additional is not None:
                if bool(additional(ctx, {})) if callable(additional) else self._check(additional, ctx):
                    continue

    def _wait(self, check_spec: dict[str, Any], expect: bool, ctx: FlowCtx) -> None:
        """Block until `check` matches (appear) or stops matching (disappear)."""
        confirm = check_spec.get("confirm") or {}
        timeout_spec = check_spec.get("timeout") or {}
        timeout = None
        if timeout_spec.get("seconds"):
            timeout = _timer(timeout_spec["seconds"], timeout_spec.get("count")).start()
        active: Timer | None = None
        while timeout is None or not timeout.reached():
            self.device.screenshot()
            value = self._check(check_spec.get("check", check_spec), ctx)
            if value == expect:
                if active is None:
                    active = _timer(confirm.get("seconds", 0.0), confirm.get("count")).start()
                if active.reached():
                    return
            else:
                active = None
        logger.warning(f"[flow] wait_{'appear' if expect else 'disappear'} timeout, proceeding")
