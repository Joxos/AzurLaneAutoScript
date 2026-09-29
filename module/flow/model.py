"""Flow data model: schemas (documented dict shapes) + structural validation.

Zero-string-reference design (D14): symbols are objects (Button/Template/
Page), capabilities are callable objects, parameters are factory arguments.
The only strings left are config/capability attribute names.
See .qoder/doc/reorg-cli-flow-2026.md §3.

The dict shapes are intentionally plain (keyword keys like "and"/"or"/
"not"/"raise" cannot be TypedDict keys); `validate_flow` is the structural
check, symbol existence is covered by pyright at import time.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

FlowCtxFun = Callable[["FlowCtx", dict[str, Any]], Any]
FlowGuard = Callable[["FlowCtx", dict[str, Any]], bool]

# ---------------------------------------------------------------------------
# Legal keys per spec kind. `validate_flow` rejects anything else, so a typo
# in the data fails when the flow is handed to the engine instead of halfway
# through a live loop on a real device. They live here rather than in
# engine.py because the engine imports this module.
# ---------------------------------------------------------------------------

CHECK_KEYS = frozenset(
    {"always", "not", "and", "or", "custom", "capability", "page", "button", "template", "color"}
)
# Forwarded to the owner's method, never dispatched on.
CHECK_PAYLOAD_KEYS = frozenset({"args", "offset", "interval", "similarity", "threshold", "crop", "pre"})

ACTION_KEYS = frozenset(
    {
        "click",
        "click_and",
        "ensure_click",
        "sleep",
        "wait_appear",
        "wait_disappear",
        "wait_stable",
        "call",
        "call_if",
        "goto",
        "raise",
        "reset_timeout",
        "reset_interval",
    }
)
ACTION_PAYLOAD_KEYS = frozenset(
    {
        "args",
        "control_check",
        "value",
        # ensure_click payload
        "check",
        "appear",
        "additional",
        "confirm_wait",
        "retry_wait",
        # wait_* payload
        "confirm",
        "timeout",
    }
)

CONTROL_KEYS = frozenset({"goto", "exit", "value"})
TIMEOUT_KEYS = frozenset({"seconds", "count", "mode", "goto", "value"})
RULE_KEYS = frozenset(
    {"name", "guard", "check", "action", "stop", "then", "on_handled", "attempts", "reset_confirm"}
)
STATE_KEYS = frozenset({"exit", "skip_if", "rules", "on_timeout"})


@dataclass
class FlowCtx:
    """Runtime context handed to custom checks/actions.

    `owner` is the domain component the flow runs under (e.g. a
    LoginHandler instance); wrappers bind to its methods, so no
    cross-domain imports and no string registries are needed (D13).
    """

    device: Any  # Device-like (real Device or a fake in tests)
    config: Any  # AzurLaneConfig-like (None when unused by a flow)
    owner: Any
    params: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Documented dict shapes (see design §3.0)
#
# FlowSpec = {
#   "name": str,
#   "entry": str,                      # default "entry" or first state
#   "groups": [GroupSpec...],          # applied before state rules
#   "states": {name: StateSpec},
# }
# StateSpec = {
#   "exit": {"check": CheckSpec, "confirm": {"seconds","count"}, "on_success": {...}},
#   "skip_if": CheckSpec,              # matched -> skip this frame
#   "rules": [RuleSpec...],            # priority order
#   "on_timeout": "warn"|"raise"|{ "seconds","count","mode" },
# }
# RuleSpec = {
#   "guard": FlowGuard|[FlowGuard],
#   "check": CheckSpec,
#   "action": ActionSpec,
#   "stop": bool,                      # default True (False = original `pass` semantics)
#   "then": {"goto": state} | {"exit": value},
#   "on_handled": {"extend_timeout": seconds},
#   "attempts": {"limit": int, "on_exceed": {"exit": value}|{"goto": state}|"warn"|"raise"},
#   "name": str,
# }
# CheckSpec = {"button":obj,"offset","interval","similarity","threshold"} | {"template":..}
#           | {"page": Page|list|{"any":[...]}} | {"color": {...}} | {"custom": fn, "args"}
#           | {"capability": "attr"} | {"and": [..]} | {"or": [..]} | {"not": ..} | {"always": True}
# ActionSpec = {"click": btn,"control_check"} | {"click_and": [..]}
#            | {"ensure_click": {...}} | {"swipe"} | {"sleep": float|tuple}
#            | {"wait_appear"/"wait_disappear"/"wait_stable": CheckSpec}
#            | {"call": fn, "args": {...}, "reset_interval": [...]}
#            | {"goto": "__exit__"|state, "value": v} | {"raise": ExceptionClass}
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Task (task-level orchestration, §3.1 T4 / roadmap P3):
#
# TaskSpec = {
#   "name": str,
#   "steps": [StepSpec...],            # executed in order
# }
# StepSpec = {"call": fn, "args": {...}}          # run a callable (arrows to ctx)
#          | {"flow": FlowSpec, "params": {...}}  # run a sub-flow (full loop semantics)
#          | {"if": {"check": fn, "args", "then": [StepSpec...], "else": [...]}}
#          | {"stop": value}                      # terminate, return value
#
# Task flow is the data form of a legacy `run()` skeleton: sequence + branches
# + nested loops, with zero strings (same D14 rules as FlowSpec).
# ---------------------------------------------------------------------------


def _validate_steps(steps: list[Any], errors: list[str], path: str = "steps") -> None:
    if not isinstance(steps, list) or not steps:
        errors.append(f"{path}: must be a non-empty list")
        return
    for idx, step in enumerate(steps):
        where = f"{path}[{idx}]"
        if not isinstance(step, dict):
            errors.append(f"{where}: must be a dict")
            continue
        if "stop" in step:
            if len(step) != 1:
                errors.append(f"{where}: 'stop' cannot be combined with other keys")
            continue
        if "call" in step:
            if "if" in step or "flow" in step:
                errors.append(f"{where}: 'call' cannot be combined with 'if'/'flow'")
            if not callable(step["call"]):
                errors.append(f"{where}: call must be callable")
            continue
        if "flow" in step:
            if "if" in step:
                errors.append(f"{where}: 'flow' cannot be combined with 'if'")
            sub = step["flow"]
            if not isinstance(sub, dict) or not isinstance(sub.get("states"), dict):
                errors.append(f"{where}: flow must be a FlowSpec with states")
            else:
                errors.extend(validate_flow(sub))
            continue
        if "if" in step:
            spec = step["if"]
            if not isinstance(spec, dict) or not callable(spec.get("check")):
                errors.append(f"{where}: if.check must be callable")
                continue
            if not isinstance(spec.get("then"), (list, type(None))) or not isinstance(
                spec.get("else"), (list, type(None))
            ):
                errors.append(f"{where}: if.then/else must be step lists")
                continue
            if spec.get("then"):
                _validate_steps(spec["then"], errors, f"{where}.if.then")
            if spec.get("else"):
                _validate_steps(spec["else"], errors, f"{where}.if.else")
            continue
        errors.append(f"{where}: unknown step (need one of call/flow/if/stop): {sorted(step)}")


def validate_task(task: dict[str, Any]) -> list[str]:
    """Structural validation of a Task data dict.

    Returns a list of errors (empty = valid). Mirrors validate_flow; symbol
    existence is covered by pyright at import time.
    """
    errors: list[str] = []
    if not isinstance(task, dict) or not task.get("name"):
        errors.append("task.name: must be a non-empty string")
    if not isinstance(task, dict):
        return errors
    steps = task.get("steps")
    _validate_steps(steps if isinstance(steps, list) else [], errors)
    return errors


def _validate_check(spec: Any, where: str, errors: list[str]) -> None:
    if spec is None or isinstance(spec, bool):
        return
    if not isinstance(spec, dict):
        errors.append(f"{where}: check must be a dict, got {type(spec).__name__}")
        return
    unknown = set(spec) - CHECK_KEYS - CHECK_PAYLOAD_KEYS
    if unknown:
        errors.append(f"{where}: unknown check key(s) {sorted(unknown)}")
    for key in ("and", "or"):
        for sub in spec.get(key, []) or []:
            _validate_check(sub, f"{where}.{key}", errors)
    if "not" in spec:
        _validate_check(spec["not"], f"{where}.not", errors)
    for key in ("custom", "capability", "button", "template", "color", "page", "always"):
        if key in spec and not callable(spec[key]) and key in ("custom", "capability"):
            errors.append(f"{where}.{key}: must be callable")


def _validate_action(spec: Any, where: str, errors: list[str]) -> None:
    if spec is None:
        return
    if not isinstance(spec, dict):
        errors.append(f"{where}: action must be a dict, got {type(spec).__name__}")
        return
    unknown = set(spec) - ACTION_KEYS - ACTION_PAYLOAD_KEYS
    if unknown:
        errors.append(f"{where}: unknown action key(s) {sorted(unknown)}")
    for key in ("call", "call_if"):
        if key in spec and not callable(spec[key]):
            errors.append(f"{where}.{key}: must be callable")
    if "goto" in spec and not isinstance(spec["goto"], str):
        errors.append(f"{where}.goto: must be a state name string")
    # An ensure_click / wait_* payload is itself a mini spec.
    if "ensure_click" in spec:
        inner = spec["ensure_click"]
        if not isinstance(inner, dict) or "click" not in inner or "check" not in inner:
            errors.append(f"{where}.ensure_click: needs 'click' and 'check'")
    for key in ("wait_appear", "wait_disappear", "wait_stable"):
        if key in spec and not isinstance(spec[key], dict):
            errors.append(f"{where}.{key}: must be a dict")


def _validate_control(spec: Any, where: str, errors: list[str]) -> None:
    if spec is None or isinstance(spec, str):
        return
    if not isinstance(spec, dict):
        errors.append(f"{where}: control must be a dict, got {type(spec).__name__}")
        return
    unknown = set(spec) - CONTROL_KEYS
    if unknown:
        errors.append(f"{where}: unknown control key(s) {sorted(unknown)}")


def validate_flow(flow: dict[str, Any]) -> list[str]:
    """Structural validation of a Flow data dict.

    Returns a list of errors (empty = valid). Checks the state graph, the
    rule shapes and the *payloads* (check/action/control keys) - symbol
    existence is covered by pyright at import time.
    """
    errors: list[str] = []

    states = flow.get("states", {})
    if not isinstance(states, dict) or not states:
        errors.append("flow.states: must be a non-empty dict")
        return errors

    entry = flow.get("entry")
    if entry is not None and entry not in states:
        errors.append(f"flow.entry {entry!r} not in states: {sorted(states)}")

    def _ref(target: Any) -> None:
        if isinstance(target, dict) and "goto" in target and target["goto"] not in states:
            errors.append(f"goto {target['goto']!r} not in states: {sorted(states)}")
        _validate_control(target, "control", errors)

    def _rule(rule: Any, where: str) -> None:
        if not isinstance(rule, dict):
            errors.append(f"{where}: must be a dict")
            return
        unknown = set(rule) - RULE_KEYS
        if unknown:
            errors.append(f"{where}: unknown rule key(s) {sorted(unknown)}")
        if "check" not in rule and "guard" not in rule:
            action = rule.get("action")
            if not (isinstance(action, dict) and "call_if" in action):
                errors.append(f"{where}: check missing")
        _validate_check(rule.get("check"), f"{where}.check", errors)
        _validate_action(rule.get("action"), f"{where}.action", errors)
        _ref(rule.get("then"))
        att = rule.get("attempts")
        if isinstance(att, dict):
            if att.get("limit", 1) < 1:
                errors.append(f"{where}: attempts.limit must be >= 1")
            _ref(att.get("on_exceed"))
        on_handled = rule.get("on_handled")
        if isinstance(on_handled, dict):
            unknown = set(on_handled) - {"extend_timeout"}
            if unknown:
                errors.append(f"{where}.on_handled: unknown key(s) {sorted(unknown)}")

    for name, state in states.items():
        if not isinstance(state, dict):
            errors.append(f"state {name}: must be a dict")
            continue
        unknown = set(state) - STATE_KEYS
        if unknown:
            errors.append(f"state {name}: unknown state key(s) {sorted(unknown)}")
        exit_spec = state.get("exit")
        if exit_spec is not None and not isinstance(exit_spec, dict):
            errors.append(f"state {name}: exit must be a dict")
        if isinstance(exit_spec, dict):
            if "check" not in exit_spec:
                errors.append(f"state {name}: exit.check missing")
            if "on_success" not in exit_spec:
                errors.append(f"state {name}: exit.on_success missing")
            _validate_check(exit_spec.get("check"), f"state {name}.exit.check", errors)
            _ref(exit_spec.get("on_success"))
        _validate_check(state.get("skip_if"), f"state {name}.skip_if", errors)

        ot = state.get("on_timeout")
        if isinstance(ot, dict):
            mode = ot.get("mode")
            if mode == "goto" and ot.get("goto") not in states:
                errors.append(f"state {name}: on_timeout.goto {ot.get('goto')!r} not in states")
            elif mode not in (None, "warn", "raise", "warn_proceed", "exit", "goto"):
                errors.append(f"state {name}: unknown on_timeout mode {mode!r}")
            unknown = set(ot) - TIMEOUT_KEYS
            if unknown:
                errors.append(f"state {name}.on_timeout: unknown key(s) {sorted(unknown)}")

        for idx, rule in enumerate(state.get("rules", []) or []):
            _rule(rule, f"state {name} rule#{idx}")
    for idx, rule in enumerate(flow.get("groups", []) or []):
        _rule(rule, f"group rule#{idx}")

    return errors
