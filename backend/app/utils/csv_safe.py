"""CSV formula-injection hardening.

Spreadsheet apps (Excel, LibreOffice, Google Sheets) treat a cell whose text
begins with ``=``, ``+``, ``-``, ``@``, or a leading tab/CR as a *formula*. An
attacker who can influence an exported string field (e.g. a device-supplied
LiveLink ``param_key``, a vehicle nickname, a vendor name) can smuggle a payload
like ``=cmd|'/c calc'!A1`` that executes when the victim opens the export.

The rule (plan §11-F, R1-F2): act only on ``str`` values -- numeric types are
written by ``csv.writer`` verbatim and cannot carry a formula. A string is
neutralised (prefixed with a single ``'``) only when it is non-empty, its first
character is one of the dangerous lead characters, AND it does not parse as a
number. That leaves genuine numeric strings like ``-12.5`` untouched (R5).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

_DANGEROUS_LEAD = ("=", "+", "-", "@", "\t", "\r")


def _is_number(text: str) -> bool:
    """Whether ``text`` parses cleanly as an int / float / Decimal."""
    s = text.strip()
    if not s:
        return False
    try:
        Decimal(s)
        return True
    except InvalidOperation, ValueError:
        return False


def sanitize_csv_cell(value: Any) -> Any:
    """Neutralise a potential CSV formula-injection payload.

    Non-string values are returned unchanged (``csv.writer`` renders them
    safely). A string is prefixed with a single quote only when it starts with a
    dangerous lead character and is not a legitimate number.
    """
    if not isinstance(value, str):
        return value
    if not value:
        return value
    if value[0] in _DANGEROUS_LEAD and not _is_number(value):
        return "'" + value
    return value


def unquote_csv_cell(value: str) -> str:
    """Undo `sanitize_csv_cell` on a cell read back: one `'` before a formula lead character.

    The export quotes a text cell that starts with = + - @, a tab or a CR and
    isn't a number, so a spreadsheet won't run it. Read back as it is, the
    quote became part of the stored text and no key matched it (T-21).
    """
    if (
        len(value) > 1
        and value[0] == "'"
        and value[1] in _DANGEROUS_LEAD
        and not _is_number(value[1:])
    ):
        return value[1:]
    return value


def sanitize_csv_row(row: list[Any]) -> list[Any]:
    """Apply :func:`sanitize_csv_cell` to each cell of a row."""
    return [sanitize_csv_cell(cell) for cell in row]
