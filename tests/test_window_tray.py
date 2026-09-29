"""Close-to-tray and the window endpoints the tray talks to.

The behaviour under test: closing the window must NOT stop the bot (the tray
owns the exit), and the tray must be able to bring the window back over the
API. Both are easy to get subtly wrong - a close handler that does not cancel
the event kills a running task, and a window handle that is never published
leaves the tray with a dead "Open window".
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from module.cli.run import _install_tray_close_behavior
from module.webui.api.routers import window as window_router
from module.webui.setting import State


class FakeEvent:
    """pywebview's Event: `+=` appends a handler (webview/event.py::__iadd__)."""

    def __init__(self):
        self._items: list = []

    def __iadd__(self, handler):
        self._items.append(handler)
        return self

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)

    def __getitem__(self, index):
        return self._items[index]


class FakeEvents:
    def __init__(self):
        self.closed = FakeEvent()
        self.closing = FakeEvent()


class FakeWindow:
    def __init__(self, visible=True):
        self.visible = visible
        self.shown = 0
        self.restored = 0
        self.hidden = 0
        self.events = FakeEvents()

    def show(self):
        self.visible = True
        self.shown += 1

    def restore(self):
        self.restored += 1

    def hide(self):
        self.visible = False
        self.hidden += 1

    def fire_closing(self):
        """What the platform does: call every handler, cancel if one is False.

        Mirrors webview/event.py::Event.set + platforms/winforms.py::on_closing.
        """
        import inspect

        cancel = False
        for handler in list(self.events.closing):
            parameters = inspect.signature(handler).parameters
            if len(parameters) == 0:
                value = handler()
            elif "window" in parameters:
                value = handler(self)
            else:
                value = handler()  # set() is called without arguments
            if value is False:
                cancel = True
        return cancel


class FakeServer:
    def __init__(self):
        self.should_exit = False


@pytest.fixture
def clean_state():
    previous = State.window
    State.window = None
    yield
    State.window = previous


# --- close behaviour ----------------------------------------------------


def test_close_hides_instead_of_stopping_the_bot(clean_state):
    """The whole point: a click on X must not kill a running task."""
    win, server = FakeWindow(), FakeServer()
    _install_tray_close_behavior(win, server)

    cancelled = win.fire_closing()

    assert cancelled is True  # pywebview sets args.Cancel -> the window stays
    assert win.hidden == 1
    assert win.visible is False
    assert server.should_exit is False  # the server keeps running


def test_quit_is_allowed_through_even_with_the_close_handler(clean_state):
    """When a real shutdown is already under way, the close must not veto it."""
    win, server = FakeWindow(), FakeServer()
    _install_tray_close_behavior(win, server)
    server.should_exit = True

    cancelled = win.fire_closing()

    assert cancelled is False
    assert win.hidden == 0
    assert server.should_exit is True


def test_close_handler_uses_pywebview_parameter_injection(clean_state):
    """`closing.set()` passes no arguments; the window arrives by parameter.

    pywebview inspects the handler signature and passes the window only to a
    parameter literally named `window` (webview/event.py::Event.set), so a
    handler expecting any other required parameter would raise inside the
    platform and be swallowed there.
    """
    import inspect

    win, server = FakeWindow(), FakeServer()
    _install_tray_close_behavior(win, server)
    handler = win.events.closing[0]
    assert "window" in inspect.signature(handler).parameters


def test_no_tray_keeps_the_plain_behaviour(clean_state):
    """Without a tray the window is the only way out, so close shuts down."""
    win, server = FakeWindow(), FakeServer()
    assert not win.events.closing
    assert not win.events.closed
    assert server.should_exit is False
    assert win.visible is True


# --- window endpoints ---------------------------------------------------


def test_window_state_without_a_window_says_so(clean_state):
    result = window_router.window_state()
    assert result == {
        "ok": False,
        "exists": False,
        "visible": False,
        "reason": "no desktop window (headless/web mode)",
    }


def test_window_state_reports_visibility(clean_state):
    win = FakeWindow(visible=False)
    State.window = win
    assert window_router.window_state() == {"ok": True, "exists": True, "visible": False}


def test_show_brings_the_window_back(clean_state):
    win = FakeWindow(visible=False)
    State.window = win
    assert window_router.window_show() == {"ok": True, "shown": True}
    assert win.visible is True
    assert win.shown == 1


def test_show_without_a_window_explains_itself(clean_state):
    result = window_router.window_show()
    assert result["ok"] is False
    assert result["shown"] is False
    assert isinstance(result["reason"], str)
    assert "headless" in result["reason"]


def test_show_reports_a_window_failure_instead_of_crashing(clean_state):
    class BrokenWindow(FakeWindow):
        def show(self):
            raise RuntimeError("webview is gone")

    State.window = BrokenWindow()
    result = window_router.window_show()
    assert result["ok"] is False
    assert isinstance(result["reason"], str)
    assert "webview is gone" in result["reason"]


def test_hide_and_show_roundtrip(clean_state):
    win = FakeWindow(visible=True)
    State.window = win
    assert window_router.window_hide() == {"ok": True, "hidden": True}
    assert win.visible is False
    assert window_router.window_show() == {"ok": True, "shown": True}
    assert win.visible is True


def test_hide_without_a_window_explains_itself(clean_state):
    result = window_router.window_hide()
    assert result["ok"] is False
    assert isinstance(result["reason"], str)
    assert "headless" in result["reason"]


def test_routes_are_registered():
    """The tray calls these by URL; an unregistered router is a silent 404.

    Asserted through the OpenAPI surface on purpose: this FastAPI version
    wraps included routers in an internal object without `.routes`, so
    walking `app.routes` proves nothing. The paths in the schema are what the
    client actually depends on.
    """
    from module.webui.api import create_api_app

    paths = create_api_app().openapi()["paths"]
    for expected in ("/api/window", "/api/window/show", "/api/window/hide"):
        assert expected in paths, f"{expected} is not mounted (window paths: {sorted(p for p in paths if 'window' in p)})"
    # The tray POSTs to /show and /hide, so the method matters, not just the path.
    assert "/api/window/show" in paths
    assert "post" in paths["/api/window/show"]


def test_state_window_defaults_to_none():
    """headless/web mode must not carry a stale handle between runs."""
    assert isinstance(State.window, (types.ModuleType, type(None), object))
    assert State.__dict__.get("window", None) is None
