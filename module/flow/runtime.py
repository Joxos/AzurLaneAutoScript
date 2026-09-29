"""Session flow runtime: ONE engine instance per bot session.

A bot session (one `alas` scheduler process, one config) owns exactly one
FlowEngine bound to its device/config. Every flow — whether reached from a
domain module, a task, or the webui — executes on that instance, so engine
state (device/config binding, timers, per-run owner injection) lives in one
place and modules never construct engines themselves.

    scheduler ── registry/task ──▶ FlowEngine.run_task(task, owner=…)
                                   FlowEngine.run(flow, owner=…)

`get_runtime()` creates the engine lazily from the first owner seen (direct
use / tests), and `set_runtime()` lets the app shell (alas.AzurLaneAutoScript)
bind one explicitly to its own device/config so all modules share it.
"""

from __future__ import annotations

from typing import Any

from module.flow.engine import FlowEngine

_runtime: FlowEngine | None = None


def set_runtime(engine: FlowEngine | None) -> None:
    """Bind (or clear) the session engine. The shell calls this at startup."""
    global _runtime
    _runtime = engine


def get_runtime() -> FlowEngine:
    """Return the session engine, creating it lazily if unbound.

    A lazy instance has no device/config yet: `run`/`run_task` resolve them
    from the owner passed per call (see FlowEngine.run owner injection). Tests
    and direct module use therefore work without set_runtime().
    """
    global _runtime
    if _runtime is None:
        _runtime = FlowEngine()
    return _runtime


def run_flow(
    flow: dict[str, Any],
    owner: Any = None,
    params: dict[str, Any] | None = None,
    entry: str | None = None,
    *,
    skip_first: bool | None = None,
) -> Any:
    """Run a flow on the session engine (module/domain callers use this)."""
    return get_runtime().run(flow, params=params, entry=entry, owner=owner, skip_first=skip_first)


def run_group(
    group: list[dict[str, Any]],
    owner: Any = None,
    params: dict[str, Any] | None = None,
) -> bool:
    """Run a single-shot rule group on the session engine."""
    return get_runtime().run_group(group, params=params, owner=owner)


def run_task(
    task: dict[str, Any],
    owner: Any = None,
    params: dict[str, Any] | None = None,
) -> Any:
    """Run a task on the session engine (scheduler entry point)."""
    return get_runtime().run_task(task, params=params, owner=owner)
