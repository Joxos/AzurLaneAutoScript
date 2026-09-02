"""Pytest root configuration.

The project is not installed as a package: `module.*` imports resolve from
the repo root (cwd / sys.path). Insert the root here so tests can import
the project regardless of how pytest is invoked.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _reset_flow_runtime():
    """Each test gets a fresh flow engine: the session runtime is a process
    singleton, so tests that reach module flows through run_flow() must not
    share device/config bindings. Tests constructing FlowEngine directly are
    unaffected."""
    from module.flow.runtime import set_runtime

    set_runtime(None)
    yield
    set_runtime(None)
