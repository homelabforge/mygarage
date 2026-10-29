"""The 3b families of a JSON backup: tires, brakes, maintenance rules and pinned supplies.

A family's rows hang together (indices into each other, nested lists), so it
imports whole or not at all: skipped when the vehicle already has some,
refused when one row fails its check or the write fails.
"""

# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Literal, cast, get_args

from pydantic.fields import FieldInfo
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brake import BrakeAxle, BrakeJob, BrakeMeasurement
from app.models.maintenance_rule import MaintenanceRule
from app.models.supply import Supply
from app.models.tire import Tire, TireSet
from app.routes.import_data._common import (
    _check_bounds,
    _in_vocabulary,
    _is_blank,
    _RowError,
    _unexpected_reason,
)
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

#: Each family and the top-level lists of the file that carry it.
JSON_FAMILY_SECTIONS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "supplies": ("supplies",),
        "maintenance_rules": ("maintenance_rules",),
        "tires": ("tire_sets", "tires"),
        "brakes": ("brake_axles", "brake_jobs", "brake_measurements"),
    }
)

#: The tables that say a vehicle already has the family. Any row counts, an
#: inactive rule and an empty tire set too; a shared supply has no vin, so it doesn't.
_FAMILY_ROWS: Mapping[str, tuple[Any, ...]] = MappingProxyType(
    {
        "supplies": (Supply,),
        "maintenance_rules": (MaintenanceRule,),
        "tires": (TireSet, Tire),
        "brakes": (BrakeAxle, BrakeJob, BrakeMeasurement),
    }
)

#: How a family reads in a message: its label, what the vehicle has, what the file's are.
_FAMILY_WORDS: Mapping[str, tuple[str, str, str]] = MappingProxyType(
    {
        "supplies": ("Supplies", "supplies pinned to it", "pinned supplies"),
        "maintenance_rules": (
            "Maintenance rules",
            "maintenance rules",
            "rules and their reminders",
        ),
        "tires": ("Tires", "tires", "tires"),
        "brakes": ("Brakes", "brake records", "brake records"),
    }
)

FamilyOutcome = Literal["empty", "written", "skipped", "refused"]


@dataclass(frozen=True)
class FamilyResult[T]:
    """What became of one family: the plan only when it was written."""

    outcome: FamilyOutcome
    plan: T | None = None


async def has_family(db: AsyncSession, vin: str, family: str) -> bool:
    """Whether the vehicle already has any row of `family`."""
    for model in _FAMILY_ROWS[family]:
        found = await db.execute(select(model.id).where(model.vin == vin).limit(1))
        if found.first() is not None:
            return True
    return False


def _count_rows(
    family: str, sections: Mapping[str, list[Any]], results: dict[str, Any], kind: str
) -> None:
    """Count every top-level row of the family's lists under `kind`."""
    for section in JSON_FAMILY_SECTIONS[family]:
        results[section][kind] += len(sections[section])


async def run_family[T](
    db: AsyncSession,
    vin: str,
    family: str,
    sections: Mapping[str, list[Any]],
    results: dict[str, Any],
    errors: list[str],
    warnings: list[str],
    *,
    parse: Callable[[], T],
    write: Callable[[T], Awaitable[None]],
) -> FamilyResult[T]:
    """Import one family whole: parse every row first, then write it in one savepoint.

    Skipped whatever `skip_duplicates` says when the vehicle has the family
    already (S3). A bad row or a failed write refuses all of it, so nothing
    is half there (K3).
    """
    label, has, files = _FAMILY_WORDS[family]
    if not any(sections[section] for section in JSON_FAMILY_SECTIONS[family]):
        return FamilyResult("empty")

    if await has_family(db, vin, family):
        _count_rows(family, sections, results, "skipped")
        warnings.append(
            f"{label}: this vehicle already has {has}, so the file's {files} weren't imported"
        )
        return FamilyResult("skipped")

    def refuse(reason: str) -> FamilyResult[T]:
        _count_rows(family, sections, results, "errors")
        errors.append(f"{reason}, so the file's {files} weren't imported")
        return FamilyResult("refused")

    try:
        plan = parse()
    except _RowError as e:
        return refuse(e.reason)
    except Exception as e:
        # A parser bug refuses its family, not the whole file.
        logger.warning("Import: %s family failed: %s", family, sanitize_for_log(e))
        return refuse(f"{label}: {_unexpected_reason(e)}")

    try:
        async with db.begin_nested():
            await write(plan)
    except _RowError as e:
        return refuse(e.reason)
    except Exception as e:
        logger.warning("Import: %s family failed: %s", family, sanitize_for_log(e))
        return refuse(f"{label}: {_unexpected_reason(e)}")

    _count_rows(family, sections, results, "success")
    return FamilyResult("written", plan)


def as_object(row: Any) -> Mapping[str, Any]:
    """The row as a mapping, or a row error when it isn't an object."""
    if not isinstance(row, Mapping):
        raise _RowError("must be an object")
    return cast(Mapping[str, Any], row)


def required_word(row: Mapping[str, Any], key: str, vocabulary: tuple[str, ...]) -> str:
    """A word the row must carry, from the API's vocabulary."""
    raw = row.get(key)
    if _is_blank(raw):
        raise _RowError(f"{key} is missing")
    # Not blank, so a word that passes is one of the vocabulary's strings.
    return cast(str, _in_vocabulary(raw, key, vocabulary))


def file_index(row: Mapping[str, Any], key: str, size: int, *, what: str) -> int | None:
    """The in-file index under `key`, None when it's missing, a row error when it points nowhere."""
    raw = row.get(key)
    if raw is None:
        return None
    # bool first: True is an int, and would point at row 1.
    if isinstance(raw, bool) or not isinstance(raw, int) or not 0 <= raw < size:
        raise _RowError(f"{key} must be the index of {what}")
    return raw


def nested_list(row: Mapping[str, Any], key: str) -> list[Any]:
    """The list under `key`, empty when it's missing or null, a row error when it isn't one."""
    raw = row.get(key)
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise _RowError(f"{key} must be a list")
    return cast(list[Any], raw)


def within_figure_bounds(figure: Any, **values: Decimal | None) -> None:
    """`_within_api_bounds` for a figure whose bounds sit on its Annotated alias.

    A field typed `HoursFigure | None` shows no metadata on the schema, so the
    bounds are read off the alias itself (D-8).
    """
    metadata = [
        bound
        for arg in get_args(figure)[1:]
        if isinstance(arg, FieldInfo)
        for bound in arg.metadata
    ]
    # Same trap as the one this exists for: a figure with no bounds checks nothing.
    if not metadata:
        raise TypeError(f"{figure!r} carries no bounds")
    for name, value in values.items():
        if value is not None:
            _check_bounds(name, value, metadata)
