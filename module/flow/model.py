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


def validate_flow(flow: dict[str, Any]) -> list[str]:
    """Structural validation of a Flow data dict.

    Returns a list of errors (empty = valid). Checks state references and
    the shapes of rules/checks/actions; symbol existence is covered by
    pyright at import time.
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

    for name, state in states.items():
        if not isinstance(state, dict):
            errors.append(f"state {name}: must be a dict")
            continue
        exit_spec = state.get("exit")
        if exit_spec is not None and not isinstance(exit_spec, dict):
            errors.append(f"state {name}: exit must be a dict")
        if isinstance(exit_spec, dict):
            if "check" not in exit_spec:
                errors.append(f"state {name}: exit.check missing")
            if "on_success" not in exit_spec:
                errors.append(f"state {name}: exit.on_success missing")
            _ref(exit_spec.get("on_success"))

        ot = state.get("on_timeout")
        if isinstance(ot, dict):
            mode = ot.get("mode")
            if mode == "goto" and ot.get("goto") not in states:
                errors.append(f"state {name}: on_timeout.goto {ot.get('goto')!r} not in states")
            elif mode not in (None, "warn", "raise", "warn_proceed"):
                errors.append(f"state {name}: unknown on_timeout mode {mode!r}")

        for idx, rule in enumerate(state.get("rules", []) or []):
            if not isinstance(rule, dict):
                errors.append(f"state {name} rule#{idx}: must be a dict")
                continue
            if "check" not in rule and "guard" not in rule:
                action = rule.get("action")
                if not (isinstance(action, dict) and "call_if" in action):
                    errors.append(f"state {name} rule#{idx}: check missing")
            _ref(rule.get("then"))
            att = rule.get("attempts")
            if isinstance(att, dict):
                if att.get("limit", 1) < 1:
                    errors.append(f"state {name} rule#{idx}: attempts.limit must be >= 1")
                _ref(att.get("on_exceed"))

    return errors
