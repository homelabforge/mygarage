"""Every import catch-all logs its exception through `sanitize_for_log`.

A database error's text carries the SQL and the row's own values, newlines
and all, so a raw `e` lets an uploaded cell forge a log line. Nine of the CSV
catch-alls logged it raw while the service one sanitised it.
"""

import ast
from pathlib import Path

import app.routes.import_data as import_data

_SOURCE = Path(import_data.__file__).read_text()


def _raw_exception_logs() -> list[int]:
    """Lines where a `logger` call in an `except ... as e` passes `e` itself."""
    lines = []
    for handler in ast.walk(ast.parse(_SOURCE)):
        if not isinstance(handler, ast.ExceptHandler) or handler.name is None:
            continue
        for call in ast.walk(handler):
            if not (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "logger"
            ):
                continue
            if any(isinstance(arg, ast.Name) and arg.id == handler.name for arg in call.args):
                lines.append(call.lineno)
    return lines


def test_the_walk_sees_the_catch_alls() -> None:
    # Guards the guard: a walk that finds no handlers passes for nothing.
    handlers = [
        node
        for node in ast.walk(ast.parse(_SOURCE))
        if isinstance(node, ast.ExceptHandler) and node.name is not None
    ]
    assert len(handlers) > 20


def test_no_catch_all_logs_a_raw_exception() -> None:
    assert _raw_exception_logs() == []
