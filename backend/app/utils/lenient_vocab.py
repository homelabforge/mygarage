"""Reading a stored vocabulary value the vocabulary doesn't know.

A response describes what's stored. A vocabulary column with no CHECK can hold
whatever a restored backup, a hand edit or a downgrade put there, and a strict
`Literal` on the response turns that one row into a 500 on every page that
lists it. So a lenient field reads an unknown value as null (or as the
vocabulary's own "unknown" member) and logs it once. The inputs stay strict.

A lenient field is a static alias, written where its vocabulary lives::

    LenientVehicleType = Annotated[
        VehicleType | None, BeforeValidator(lenient_reader(VehicleType)), LenientVocab(None)
    ]

The `LenientVocab` marker is how the response contract test tells a lenient
field from a strict one. That test also reads each marked field back, so a
marker can't promise more than its validator does.
"""

import logging
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, TypeAliasType

from pydantic import ValidationInfo

from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

# (model, field, value) triples already warned about. A bad row is read on
# every list it's in, so without this one value would log on every page load.
# The value is the cut repr the log shows, so a huge one can't bloat the set.
_warned: set[tuple[str, str, str]] = set()

# The keys that name a row, in the order a log line gives them.
_ROW_KEYS = ("id", "vin", "vehicle_vin")
# Plenty to recognise a bad value by, without a whole text column in the log
# (or in `_warned`).
_MAX_LOGGED_VALUE = 80


@dataclass(frozen=True)
class LenientVocab:
    """Marks a response field that reads an out-of-vocabulary value leniently.

    `fallback` is what such a value reads as: None, or the vocabulary's own
    member (`"unknown"`) for a field that stays required.
    """

    fallback: str | None


def _vocabulary(vocab: Any) -> frozenset[object]:
    """The values a `Literal` (or a `type` alias of one) allows."""
    if isinstance(vocab, TypeAliasType):
        return _vocabulary(vocab.__value__)
    if typing.get_origin(vocab) is not Literal:
        raise TypeError(f"lenient_reader needs a Literal vocabulary, got {vocab!r}")
    return frozenset(typing.get_args(vocab))


def _known(value: object, vocabulary: frozenset[object]) -> bool:
    """Whether `value` is in the vocabulary. An unhashable one never is."""
    try:
        return value in vocabulary
    except TypeError:
        return False


def _row(data: dict[str, Any]) -> str:
    """The id or VIN of the row being read, from the fields validated so far."""
    named = [f"{key}={sanitize_for_log(data[key])}" for key in _ROW_KEYS if data.get(key)]
    return ", ".join(named) or "row not known yet"


def warn_once(
    model: str, field: str, value: object, fallback: object, row: Callable[[], str]
) -> None:
    """Log an out-of-vocabulary value read as `fallback`, once per (model, field, value).

    For readers outside pydantic too, like `resolve_wheel_layout`. `row` names
    the row and only runs when the line is actually logged.
    """
    shown = repr(value)[:_MAX_LOGGED_VALUE]
    key = (model, field, shown)
    if key in _warned:
        return
    _warned.add(key)
    logger.warning(
        "Out-of-vocabulary %s.%s %s read as %s (%s)",
        model,
        field,
        sanitize_for_log(shown),
        fallback,
        row(),
    )


def lenient_reader(
    vocab: Any, *, fallback: str | None = None
) -> Callable[[object, ValidationInfo], object]:
    """A before-validator that passes `vocab`'s values and reads anything else as `fallback`.

    None reads as `fallback` too, so a required field with an "unknown" member
    stays required. Raises TypeError for a `vocab` that isn't a `Literal`, and
    ValueError for a `fallback` outside it, when the alias is built.
    """
    vocabulary = _vocabulary(vocab)
    if fallback is not None and fallback not in vocabulary:
        raise ValueError(
            f"fallback {fallback!r} isn't in the vocabulary {sorted(map(str, vocabulary))}"
        )

    def read(value: object, info: ValidationInfo) -> object:
        if value is None:
            return fallback
        if _known(value, vocabulary):
            return value
        model = info.config.get("title") if info.config is not None else None
        # Outside a model (a bare TypeAdapter) pydantic hands over no data at all.
        data: dict[str, Any] = info.data or {}
        warn_once(
            model or "<no model>",
            info.field_name or "<no field>",
            value,
            fallback,
            lambda: _row(data),
        )
        return fallback

    return read
