"""Every import catch-all logs its exception through `sanitize_for_log`.

A database error's text carries the SQL and the row's own values, newlines
and all, so a raw `e` lets an uploaded cell forge a log line. Nine of the CSV
catch-alls logged it raw while the service one sanitised it.
"""

import ast

import pytest

from tests._importer_source import importer_files

#: Every importer module's source by file name: one file today, the package after B3-9.
_SOURCES = {path.name: path.read_text() for path in importer_files()}


def _uses_raw(node: ast.AST, name: str) -> bool:
    """Whether `node` reads `name` anywhere outside a `sanitize_for_log(...)` call."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "sanitize_for_log"
    ):
        return False
    if isinstance(node, ast.Name) and node.id == name:
        return True
    return any(_uses_raw(child, name) for child in ast.iter_child_nodes(node))


def _raw_exception_logs(source: str) -> list[int]:
    """Lines where a `logger` call in an `except ... as e` gets `e` unsanitised.

    Bare, through str() or repr(), inside an f-string: any read of it that
    doesn't go through `sanitize_for_log` counts.
    """
    lines = []
    for handler in ast.walk(ast.parse(source)):
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
            if any(_uses_raw(arg, handler.name) for arg in call.args):
                lines.append(call.lineno)
    return lines


def _handler(log_call: str) -> str:
    return f"try:\n    pass\nexcept Exception as e:\n    {log_call}\n"


@pytest.mark.parametrize(
    "log_call",
    [
        'logger.error("failed: %s", e)',
        'logger.error("failed: %s", str(e))',
        'logger.error("failed: %s", repr(e))',
        'logger.error(f"failed: {e}")',
        'logger.error(f"failed: {e!r}")',
        'logger.error("failed: " + str(e))',
    ],
)
def test_the_walk_flags_every_raw_form(log_call: str) -> None:
    assert _raw_exception_logs(_handler(log_call)) == [4]


@pytest.mark.parametrize(
    "log_call",
    [
        'logger.error("failed: %s", sanitize_for_log(e))',
        'logger.error(f"failed: {sanitize_for_log(e)}")',
        'logger.error("failed: %s", row_num)',
    ],
)
def test_the_walk_lets_a_sanitised_read_through(log_call: str) -> None:
    assert _raw_exception_logs(_handler(log_call)) == []


def test_the_walk_sees_the_catch_alls() -> None:
    # Guards the guard: a walk that finds no handlers passes for nothing.
    # 63 is the count on 32b15b50, so a walk that drops a module comes up short.
    handlers = [
        node
        for source in _SOURCES.values()
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ExceptHandler) and node.name is not None
    ]
    assert len(handlers) >= 63


def test_no_catch_all_logs_a_raw_exception() -> None:
    raw = {
        name: lines for name, source in _SOURCES.items() if (lines := _raw_exception_logs(source))
    }
    assert raw == {}
