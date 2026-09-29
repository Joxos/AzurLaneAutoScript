"""FlowEngine: the shared execution core for UI/business loops and tasks.

Implements the §3.0 evaluation cycle (skip_if -> exit guard -> group rules ->
state rules -> timeout) over declarative Flow data, plus task-level
orchestration (`run_task`: sequential steps / if-branches / sub-flows).
Builtin checks/actions resolve to ModuleBase/Device APIs so existing
behavior maps 1:1; custom checks/actions are callable objects bound through
`FlowCtx` (D13/D14).

Owner is injected per `run`, never owned by the instance: a bot session
holds ONE FlowEngine (see module/flow/runtime.py) and every flow/task in
that session executes on it, so device/config/state live in one place.

Two rules this engine holds itself to, both learned the hard way:

1. **No duplicated defaults.** Checks and actions pass through only the keys
   the flow spec spells out; everything else falls to the owner's own
   signature default. Copying a default here (`threshold=221`) silently
   diverged from `image_color_count` when upstream changed the threshold
   from a similarity floor to a tolerance: every colour check in every flow
   started matching almost everything, with no error anywhere.
2. **Data errors surface at load time.** `validate_flow` checks payloads
   (check/action/control keys), not just the state graph, so a typo in the
   data raises when the flow is handed to `run()` - not halfway through a
   live loop on a real device.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from module.base.timer import Timer
from module.flow.model import FlowCtx, validate_flow, validate_task
from module.logger import logger

EXIT = "__exit__"

# Default state timeout when `on_timeout` is a bare mode string.
_DEFAULT_TIMEOUT = 60.0
# Approximate screenshot cost, used only to floor a timer with frame counts
# (see _timer). The wall clock is the real bound; the count is the robustness
# bound for slow devices, same convention as Timer.from_seconds.
_FRAME_COST = 0.5


class FlowTimeoutError(RuntimeError):
    """Raised by a state whose `on_timeout` mode is "raise"."""


class FlowSpecError(ValueError):
    """Malformed flow data (unknown or misspelled keys)."""


class _TaskStop(Exception):
    """Internal control flow for a `stop` step inside a task (run_task)."""

    def __init__(self, value: Any) -> None:
        super().__init__(value)
        self.value = value


def _timer(seconds: float, count: int | None = None) -> Timer:
    """A timer for `seconds`, with the frame count as a floor for slow devices.

    `Timer.reached()` needs BOTH the access count and the wall clock past the
    limit, so a zero-second confirm (the default) must still require one
    extra access - otherwise an exit guard fires before the state rules get
    their frame. Hence the `max(1, ...)`: the limit stays exactly as asked.
    """
    if count is None:
        return Timer(seconds, count=max(1, int(seconds / _FRAME_COST)))
    return Timer(seconds, count=count)


def _only(spec: dict[str, Any], *names: str) -> dict[str, Any]:
    """The subset of `names` the spec actually spells out.

    Passing only those through keeps the owner's signature as the single
    source of defaults (see the module docstring).
    """
    return {name: spec[name] for name in names if name in spec}


def make_loop_flow(
    name: str,
    exit_check: dict[str, Any],
    rules: list[dict[str, Any]] | None = None,
    confirm: dict[str, Any] | None = None,
    timeout: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generic "loop until exit_check" flow builder (domain modules reuse this)."""
    state: dict[str, Any] = {"rules": rules or []}
    state["exit"] = {
        "check": exit_check,
        "confirm": confirm or {},
        "on_success": {"exit": True},
    }
    if timeout:
        state["on_timeout"] = timeout
    return {"name": name, "entry": "s", "states": {"s": state}}


@dataclass
class _Control:
    """What a rule or exit guard wants the loop to do next."""

    kind: str  # "exit" | "goto"
    value: Any = None

    @property
    def finished(self) -> bool:
        return self.kind == "exit"


@dataclass
class _Outcome:
    """What evaluating a rule list produced.

    `control` is what the loop should do (goto/exit); `handled` says a rule
    did something. They are separate because a rule can handle work without
    asking for a state change - and `run_group` only cares about `handled`.
    """

    control: _Control | None = None
    handled: bool = False


@dataclass
class _RunState:
    """Per-run loop state (one flow runs at a time per engine)."""

    name: str
    timeout: Timer | None = None
    attempts: dict[int, dict[str, Any]] = field(default_factory=dict)
    exit_timers: dict[str, Timer | None] = field(default_factory=dict)


class FlowEngine:
    """Runs one Flow against a domain `owner` (handler instance)."""

    def __init__(
        self,
        owner: Any = None,
        device: Any = None,
        config: Any = None,
        *,
        skip_first: bool = False,
    ) -> None:
        # `owner` is a per-run binding, kept only as a fallback so direct
        # construction (tests, legacy call sites) keeps working; a session
        # runtime passes owner per run()/run_task() instead.
        self.owner = owner
        self.device: Any = device if device is not None else getattr(owner, "device", None)
        self.config: Any = config if config is not None else getattr(owner, "config", None)
        self.skip_first = skip_first

    # ------------------------------------------------------------- running --

    def run(
        self,
        flow: dict[str, Any],
        params: dict[str, Any] | None = None,
        entry: str | None = None,
        *,
        owner: Any = None,
        skip_first: bool | None = None,
    ) -> Any:
        errors = validate_flow(flow)
        if errors:
            raise FlowSpecError(f"invalid flow {flow.get('name')!r}: " + "; ".join(errors))

        states = flow["states"]
        owner = owner if owner is not None else self.owner
        self._bind(owner)
        ctx = FlowCtx(device=self.device, config=self.config, owner=owner, params=params or {})
        eff_skip = self.skip_first if skip_first is None else skip_first
        groups: list[dict[str, Any]] = flow.get("groups", [])

        state = _RunState(name=entry or flow.get("entry") or next(iter(states)))
        state.timeout = self._make_timeout(states[state.name])
        self._warn_if_naked_loop(flow, state.name, states[state.name])

        tick = 0
        while True:
            tick += 1
            if not (eff_skip and tick == 1):
                self.device.screenshot()

            spec = states[state.name]

            # 1. whole-frame skip (original `is_event_animation(): continue`)
            if spec.get("skip_if") and self._check(spec["skip_if"], ctx):
                continue

            # 2. exit guard (original "End" block at the top of the loop)
            control = self._tick_exit(state, spec, ctx) if spec.get("exit") is not None else None

            # 3-4. group rules then state rules, in priority order
            if control is None:
                control = self._eval_rules([*groups, *(spec.get("rules") or [])], state, ctx, single_pass=False).control

            if control is not None:
                if control.finished:
                    return self._exit_value(control, ctx)
                self._goto(state, states, control.value)
                continue

            # 5. state timeout
            if state.timeout is not None and state.timeout.reached():
                control = self._apply_timeout(state.name, spec.get("on_timeout"), ctx)
                if control is not None and control.finished:
                    return self._exit_value(control, ctx)
                if control is not None:
                    self._goto(state, states, control.value)
                    continue
                state.timeout = state.timeout.reset()

    def run_group(
        self,
        group: list[dict[str, Any]],
        params: dict[str, Any] | None = None,
        *,
        owner: Any = None,
    ) -> bool:
        """Single-shot group evaluation (original `ui_additional` semantics).

        One pass over the rules against the current image (no screenshot):
        the first rule that handles/executes wins and returns True, exactly
        like the original `if ...: return True` chain.
        """
        owner = owner if owner is not None else self.owner
        self._bind(owner)
        ctx = FlowCtx(device=self.device, config=self.config, owner=owner, params=params or {})
        # A throw-away run state: a group has no timeout, no exit guard and no
        # attempts, but sharing the evaluator keeps the two paths honest.
        return self._eval_rules(group, _RunState(name="<group>"), ctx, single_pass=True).handled

    # ------------------------------------------------------- task running --

    def run_task(
        self,
        task: dict[str, Any],
        params: dict[str, Any] | None = None,
        *,
        owner: Any = None,
    ) -> Any:
        """Run a task (ordered steps) against the runtime's device/config.

        TaskSpec (see model.py): sequential steps of `call` / `flow` (sub-flow
        with full loop semantics) / `if` branches / `stop` (terminate). This is
        the data form of a legacy `run()` skeleton, so a scheduler hands the
        SAME engine instance every task of a session.
        """
        errors = validate_task(task)
        if errors:
            raise FlowSpecError(f"invalid task {task.get('name')!r}: " + "; ".join(errors))
        owner = owner if owner is not None else self.owner
        self._bind(owner)
        ctx = FlowCtx(device=self.device, config=self.config, owner=owner, params=params or {})
        self._log(f"task={task['name']} start")
        try:
            self._run_steps(task["steps"], ctx)
        except _TaskStop as e:
            self._log(f"task={task['name']} stop ✓")
            return e.value
        self._log(f"task={task['name']} done")
        return None

    def _run_steps(self, steps: list[dict[str, Any]], ctx: FlowCtx) -> None:
        for idx, step in enumerate(steps):
            if "stop" in step:
                raise _TaskStop(step["stop"])
            if "call" in step:
                fn = step["call"]
                self._log(f"task step={idx} call={getattr(fn, '__name__', fn)!r}")
                fn(ctx, step.get("args") or {})
                continue
            if "flow" in step:
                params = {**ctx.params, **(step.get("params") or {})}
                self._log(f"task step={idx} flow={step['flow'].get('name', '?')}")
                self.run(step["flow"], params=params, owner=ctx.owner)
                continue
            # "if" step: branch on a callable check, then/else are step lists
            spec = step["if"]
            taken = bool(spec["check"](ctx, spec.get("args") or {}))
            branch = spec["then"] if taken else spec.get("else")
            if branch:
                self._log(f"task step={idx} branch={'then' if taken else 'else'}")
                self._run_steps(branch, ctx)

    # ------------------------------------------------------------- routing --

    def _exit_value(self, control: _Control, ctx: FlowCtx) -> Any:
        value = control.value
        if isinstance(value, dict) and set(value) == {"__var__"}:
            # dynamic exit value from the run's params (e.g. Switch.set returns
            # `changed`, Scroll.set returns `dragged`)
            value = ctx.params.get(value["__var__"])
        return value

    def _goto(self, state: _RunState, states: dict[str, Any], target: Any) -> None:
        state.name = target
        state.timeout = self._make_timeout(states[state.name])
        state.exit_timers.clear()
        self._log(f"state switch -> {state.name}")

    # ------------------------------------------------------------- helpers --

    def _bind(self, owner: Any) -> None:
        """Bind device/config from the owner when created lazily (no args).

        A session engine is constructed once with device/config; a lazily
        created one (tests, direct use) picks them up from its first owner
        and keeps them for the session.
        """
        if self.device is None and owner is not None:
            self.device = getattr(owner, "device", None)
        if self.config is None and owner is not None:
            self.config = getattr(owner, "config", None)

    def _log(self, message: str) -> None:
        logger.info(f"[flow] {message}")

    def _warn_if_naked_loop(self, flow: dict[str, Any], name: str, spec: dict[str, Any]) -> None:
        """A state with neither an exit check nor a timeout loops forever.

        Faithful to the original `while 1:`, but this is a new abstraction:
        say so out loud instead of letting it look intentional.
        """
        if spec.get("exit") is None and spec.get("on_timeout") is None:
            logger.warning(
                f"[flow] {flow.get('name')!r} state {name!r} has no exit check and no timeout; it can loop forever"
            )

    def _make_timeout(self, spec: dict[str, Any]) -> Timer | None:
        on_timeout = spec.get("on_timeout")
        if on_timeout is None:
            return None
        if isinstance(on_timeout, dict):
            timer = _timer(on_timeout.get("seconds") or _DEFAULT_TIMEOUT, on_timeout.get("count"))
            # "warn_proceed" restarts the same timer, so it must not start here
            return timer if on_timeout.get("mode") == "warn_proceed" else timer.start()
        return _timer(_DEFAULT_TIMEOUT).start()

    def _tick_exit(self, state: _RunState, spec: dict[str, Any], ctx: FlowCtx) -> _Control | None:
        exit_spec = spec["exit"]
        confirm = exit_spec.get("confirm") or {}
        if not self._check(exit_spec["check"], ctx):
            state.exit_timers[state.name] = None
            return None
        timer = state.exit_timers.get(state.name)
        if timer is None:
            timer = _timer(confirm.get("seconds", 0.0), confirm.get("count")).start()
            state.exit_timers[state.name] = timer
        if timer.reached():
            self._log(f"state={state.name} exit ✓")
            control = self._apply_control(exit_spec.get("on_success"), ctx)
            return control if control is not None else _Control("exit", True)
        return None

    def _guard_ok(self, guard: Any, ctx: FlowCtx) -> bool:
        if guard is None:
            return True
        if isinstance(guard, (list, tuple)):
            return all(self._guard_ok(g, ctx) for g in guard)
        return bool(guard(ctx, {}))

    def _apply_control(self, control: Any, ctx: FlowCtx) -> _Control | None:
        if control is None:
            return None
        if isinstance(control, str):
            return _Control("exit", control)
        if isinstance(control, dict):
            if "goto" in control:
                target = control["goto"]
                return _Control("exit", None) if target == EXIT else _Control("goto", target)
            if "exit" in control or "value" in control:
                return _Control("exit", control.get("value", control.get("exit")))
        raise FlowSpecError(f"bad control spec: {control!r}")

    def _apply_timeout(self, state_name: str, spec: Any, ctx: FlowCtx) -> _Control | None:
        mode = spec if isinstance(spec, str) else (spec or {}).get("mode") or "raise"
        spec_dict = spec if isinstance(spec, dict) else {}
        self._log(f"state={state_name} timeout ({mode})")
        if mode == "warn":
            return _Control("exit", None)
        if mode == "warn_proceed":
            return _Control("goto", state_name)
        if mode == "goto":
            return _Control("goto", spec_dict.get("goto"))
        if mode == "exit":
            return _Control("exit", spec_dict.get("value"))
        raise FlowTimeoutError(f"flow timeout at state {state_name}")

    # --------------------------------------------------------------- rules --

    def _eval_rules(
        self,
        rules: list[dict[str, Any]],
        state: _RunState,
        ctx: FlowCtx,
        *,
        single_pass: bool,
    ) -> _Outcome:
        """Evaluate rules in priority order.

        `single_pass` is the `run_group` semantics: the first rule that does
        anything wins and evaluation stops there; `attempts`/`then`/`stop` do
        not apply (a group has no loop to continue).
        """
        for rule in rules:
            if not self._guard_ok(rule.get("guard"), ctx):
                continue
            key = id(rule)
            att_spec = rule.get("attempts")
            att = state.attempts.get(key)
            if att_spec is not None and not single_pass:
                att = att or {"spec": att_spec, "count": 0, "exceeded": False}
                state.attempts[key] = att
                if att["count"] >= att_spec.get("limit", 1):
                    if not att["exceeded"]:
                        att["exceeded"] = True
                        self._log(f"state={state.name} attempts exceeded ({att_spec.get('limit')})")
                        control = self._apply_control(att_spec.get("on_exceed"), ctx)
                        if control is not None:
                            return _Outcome(control, handled=True)
                    continue

            action = rule.get("action")
            if action and "call_if" in action:
                # Side-effecting helper semantics (original `if handler(): continue`):
                # the call both detects and acts; it always "runs" (attempts
                # count), its truthiness decides stop/then.
                handled = bool(action["call_if"](ctx, action.get("args") or {}))
                if att is not None:
                    att["count"] += 1
                self._after_rule(state, rule, action, ctx)
                self._log(f"state={state.name} hit rule={rule.get('name') or '#'}" + (" ✓" if handled else ""))
                if handled:
                    control = self._apply_control(rule.get("then"), ctx)
                    if control is not None or single_pass or rule.get("stop", True):
                        return _Outcome(control, handled=True)
                continue

            if rule.get("check") is not None and not self._check(rule["check"], ctx):
                continue
            if att is not None:
                att["count"] += 1

            self._log(f"state={state.name} hit rule={rule.get('name') or ('attempts' if att_spec else '#')}")
            control = None
            if not (action and set(action) == {"reset_timeout"}):
                # else: a pure state-timeout reset (original `timeout.reset()`), no device action
                control = self._action(action, ctx)
            self._after_rule(state, rule, action, ctx)
            control = control if control is not None else self._apply_control(rule.get("then"), ctx)
            if control is not None or single_pass or rule.get("stop", True):
                return _Outcome(control, handled=True)
            # stop=False (original `pass`): keep evaluating lower-priority rules
        return _Outcome()

    def _after_rule(self, state: _RunState, rule: dict[str, Any], action: Any, ctx: FlowCtx) -> None:
        """Post-action bookkeeping: intervals, timeouts, confirm timers."""
        self._reset_intervals(action, ctx)
        if action and action.get("reset_timeout") and state.timeout is not None:
            # original `timeout.reset()` semantics (e.g. keep waiting while not in map)
            state.timeout = state.timeout.reset()
        if rule.get("reset_confirm"):
            # original confirm_timer reset on every handled action
            timer = getattr(ctx.owner, rule["reset_confirm"], None)
            if timer is not None:
                timer.reset()
        extend = rule.get("on_handled", {}).get("extend_timeout")
        if extend:
            state.timeout = _timer(extend).start()

    # -------------------------------------------------------------- checks --

    def _check(self, spec: Any, ctx: FlowCtx) -> bool:
        if spec is None:
            return False
        if not isinstance(spec, dict):
            raise FlowSpecError(f"check spec must be a dict, got {type(spec).__name__}")
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
            return hasattr(ctx.owner, spec["capability"])
        if "page" in spec:
            return self._check_page(spec["page"], spec.get("offset"), ctx)
        if "button" in spec:
            return ctx.owner.appear(spec["button"], **_only(spec, "offset", "interval", "similarity", "threshold"))
        if "template" in spec:
            return self._check_template(spec, ctx)
        if "luma" in spec:
            # Luminance-only template match on the whole screenshot - used by
            # pages whose background animation breaks a colour match
            # (awaken's level check). `match_luma` owns its own defaults, so
            # only what the spec spells out is passed.
            return bool(spec["luma"].match_luma(ctx.owner.device.image, **_only(spec, "offset", "similarity")))
        if "color" in spec:
            return self._check_color(spec["color"], ctx)
        raise FlowSpecError(f"unknown check spec: {sorted(spec)}")

    def _check_page(self, page: Any, offset: Any, ctx: FlowCtx) -> bool:
        if isinstance(page, dict):
            return any(self._check_page(p, offset, ctx) for p in page.get("any", []))
        pages = page if isinstance(page, (list, tuple)) else [page]
        for p in pages:
            if hasattr(ctx.owner, "ui_page_appear"):
                if ctx.owner.ui_page_appear(p, offset=offset if offset is not None else (30, 30)):
                    return True
            elif ctx.owner.appear(p.check_button, offset=offset if offset is not None else (30, 30)):
                return True
        return False

    def _check_template(self, spec: dict[str, Any], ctx: FlowCtx) -> bool:
        button = spec["template"]
        if spec.get("crop") is not None:
            image = ctx.owner.image_crop(spec["crop"], copy=False)
            if spec.get("pre"):
                image = spec["pre"](image)
            return button.match(image, **_only(spec, "offset", "similarity"))
        return ctx.owner.match_template_color(button, **_only(spec, "offset", "interval", "similarity", "threshold"))

    def _check_color(self, spec: dict[str, Any], ctx: FlowCtx) -> bool:
        if "area" in spec:
            return ctx.owner.image_color_count(spec["area"], **_only(spec, "color", "threshold", "count"))
        return ctx.owner.image_color_count(spec["button"], **_only(spec, "color", "threshold", "count"))

    # ------------------------------------------------------------- actions --

    def _action(self, spec: Any, ctx: FlowCtx) -> _Control | None:
        if spec is None:
            return None
        if "click" in spec:
            ctx.owner.device.click(spec["click"], control_check=spec.get("control_check", True))
            return None
        if "click_and" in spec:
            for b in spec["click_and"]:
                ctx.owner.device.click(b)
            return None
        if "ensure_click" in spec:
            self._ensure_click(spec["ensure_click"], ctx)
            return None
        if "sleep" in spec:
            ctx.owner.device.sleep(spec["sleep"])
            return None
        if "wait_appear" in spec:
            self._wait(spec["wait_appear"], expect=True, ctx=ctx)
            return None
        if "wait_disappear" in spec:
            self._wait(spec["wait_disappear"], expect=False, ctx=ctx)
            return None
        if "call" in spec:
            spec["call"](ctx, spec.get("args") or {})
            return None
        if "goto" in spec:
            if spec["goto"] == EXIT:
                return _Control("exit", spec.get("value"))
            return _Control("goto", spec["goto"])
        if "raise" in spec:
            raise spec["raise"]
        raise FlowSpecError(f"unknown action spec: {sorted(spec)}")

    def _reset_intervals(self, spec: Any, ctx: FlowCtx) -> None:
        if spec and spec.get("reset_interval"):
            for button in spec["reset_interval"]:
                ctx.owner.interval_reset(button)

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
                    ctx.owner.device.click(click_button)
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
