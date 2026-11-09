"""The `caplog_only` fixture's type, and reading back what its block caught."""

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager

import pytest

#: What `caplog_only` yields: call it with logger names, and inside the block
#: their records reach caplog only, not log_cli's live output.
CaplogOnly = Callable[..., AbstractContextManager[None]]


def problems(caplog: pytest.LogCaptureFixture, logger: str) -> list[logging.LogRecord]:
    """The WARNING-and-up records the named logger wrote during the test."""
    return [r for r in caplog.records if r.name == logger and r.levelno >= logging.WARNING]
