"""Pytest root configuration.

The project is not installed as a package: `module.*` imports resolve from
the repo root (cwd / sys.path). Insert the root here so tests can import the
project regardless of how pytest is invoked.
"""

import logging
import sys
from pathlib import Path

import pytest
from loguru import logger as _loguru

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The name tests scope a level against, e.g. `caplog.at_level('ERROR', logger='alas')`.
CAPLOG_LOGGER = "alas"


def _forward_to_logging(message) -> None:
    """loguru sink that republishes a record into the stdlib hierarchy."""
    record = message.record
    logging.getLogger(CAPLOG_LOGGER).handle(
        logging.LogRecord(
            name=CAPLOG_LOGGER,
            level=record["level"].no,
            pathname=record["file"].path,
            lineno=record["line"],
            msg=record["message"],
            args=(),
            exc_info=record["exception"],
        )
    )


@pytest.fixture(autouse=True)
def _bridge_loguru_into_caplog():
    """Let pytest's caplog observe the project's logs.

    The bot logs through loguru, which does not propagate into the stdlib
    logging hierarchy, so a test that asserts on log messages would see
    nothing. Forward every record into a stdlib logger for the duration of
    each test.
    """
    handler_id = _loguru.add(_forward_to_logging, level=0, format="{message}")
    try:
        yield
    finally:
        _loguru.remove(handler_id)


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
