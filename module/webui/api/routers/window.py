"""Window control for the desktop flavor (the tray lives in another process).

The tray icon runs in the launcher, the window in the backend, so bringing a
hidden window back needs a channel between them. The webui already is that
channel, and the frontend polls `/api/status` - so the tray calls these
endpoints instead of the app growing a second IPC mechanism.

Headless/web mode has no window; the endpoints answer with a reason instead
of pretending to have worked, so the tray can fall back to opening a browser.
"""

from fastapi import APIRouter

from module.logger import logger
from module.webui.setting import State

router = APIRouter(tags=["window"])


@router.get("/api/window")
def window_state():
    """Whether a native window exists, and whether it is visible."""
    window = State.window
    if window is None:
        return {"ok": False, "exists": False, "visible": False, "reason": "no desktop window (headless/web mode)"}
    try:
        visible = bool(window.visible)
    except Exception as e:  # pragma: no cover - depends on the pywebview backend
        logger.warning(f"Cannot read window visibility: {e}")
        visible = False
    return {"ok": True, "exists": True, "visible": visible}


@router.post("/api/window/show")
def window_show():
    """Bring the window back (tray click, or a second Alas.exe)."""
    window = State.window
    if window is None:
        return {"ok": False, "shown": False, "reason": "no desktop window (headless/web mode)"}
    try:
        window.show()
        # A window that was only hidden may still be minimized on some window
        # managers; restore() is the documented counterpart of minimize().
        window.restore()
    except Exception as e:
        logger.error(f"Cannot show the window: {e}")
        return {"ok": False, "shown": False, "reason": str(e)}
    logger.info("Window shown (tray)")
    return {"ok": True, "shown": True}


@router.post("/api/window/hide")
def window_hide():
    """Hide the window without stopping the bot (same as closing it in tray mode)."""
    window = State.window
    if window is None:
        return {"ok": False, "hidden": False, "reason": "no desktop window (headless/web mode)"}
    try:
        window.hide()
    except Exception as e:
        logger.error(f"Cannot hide the window: {e}")
        return {"ok": False, "hidden": False, "reason": str(e)}
    return {"ok": True, "hidden": True}
