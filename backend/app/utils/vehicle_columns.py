"""Fit a parsed value to the vehicle column it is written to.

Shared by the window sticker and the registration certificate imports: a
parser (OCR, a vision model) sometimes reads a paragraph into a short field,
and PostgreSQL refuses a string longer than its column with a 500 while
SQLite keeps it whole. Cutting it at the column's width keeps the write
and logs the cut, never the text itself (it is whatever was on the paper).
"""

from __future__ import annotations

import logging
from typing import Any

from app.models.vehicle import Vehicle

logger = logging.getLogger(__name__)


def column_length(column: str) -> int | None:
    """The width of a string column of ``vehicles``, or None for any other type."""
    return getattr(Vehicle.__table__.c[column].type, "length", None)


def fit_to_column(
    column: str, value: Any, *, source: str = "Parsed", log: logging.Logger | None = None
) -> Any:
    """Cut a parsed string to what its vehicle column holds; anything else passes.

    ``log`` lets a caller keep the warning on its own logger (the window
    sticker's tests read it there).
    """
    length = column_length(column)
    if not isinstance(value, str) or length is None or len(value) <= length:
        return value
    (log or logger).warning(
        "%s: cut parsed %s from %d to %d characters", source, column, len(value), length
    )
    return value[:length]
