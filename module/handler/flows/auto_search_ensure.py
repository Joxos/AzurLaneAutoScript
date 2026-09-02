"""Sample 2 (design §3.4-G): T3 "try until condition" loop as flow data.

Transcribed from module/handler/auto_search.py `auto_search_setting_ensure`
(L142-168): exit = correct setting active; rule = click once per tick with
attempts limit 5 -> exit False (original `counter >= 5: return False`).
"""

from __future__ import annotations

from typing import Any

from module.handler.flow_actions import auto_search_setting_click, auto_search_setting_is_active


def make_auto_search_setting_ensure(setting: str) -> dict[str, Any]:
    return {
        "name": "auto_search_setting_ensure",
        "entry": "try",
        "states": {
            "try": {
                "exit": {
                    "check": {"custom": auto_search_setting_is_active, "args": {"setting": setting}},
                    "on_success": {"exit": True},
                },
                "rules": [
                    # T3: the click helper detects + clicks in one call (original
                    # `_auto_search_set_click`); `call_if` keeps that semantics and
                    # attempts count each execution (original counter >= 5).
                    {"action": {"call_if": auto_search_setting_click, "args": {"setting": setting}},
                     "attempts": {"limit": 5, "on_exceed": {"exit": False}}},
                ],
                "on_timeout": {"seconds": 20, "mode": "warn"},
            },
        },
    }
