"""The maintenance rules family of a JSON backup, and the reminders a person made (J5).

Read whole before anything is written, so a bad rule refuses the family and
leaves the vehicle as it was. Every reminder travels under its rule, done ones
too, because reconcile only rebuilds a due point from typed service history
(N-1) and would otherwise start the schedule over on the import day (K1).
A manual reminder is a flat row instead, matched one to one like the others (R5).
"""

# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, get_args

from sqlalchemy import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.maintenance_rule import MaintenanceRule
from app.models.reminder import Reminder
from app.routes.import_data._common import (
    _blank_to_none,
    _json_bool,
    _json_decimal,
    _json_int,
    _json_optional_date,
    _json_row_datetime,
    _json_text,
    _RowError,
    _within_api_bounds,
    _within_field_bounds,
)
from app.routes.import_data._families import as_object, nested_list, required_word
from app.routes.import_data._matching import _matches, _same_figure
from app.schemas.maintenance import (
    AnchorKind,
    AnchorSpec,
    RecurrenceSpec,
    ReminderCompleteRequest,
    validate_maintenance_type,
)
from app.schemas.reminder import ReminderCreate, ReminderType
from app.services.reminder_service import validate_reminder_state
from app.utils.maintenance_types import is_valid_code

logger = logging.getLogger(__name__)

_REMINDER_TYPES: tuple[str, ...] = get_args(ReminderType)
_ANCHOR_KINDS: tuple[str, ...] = get_args(AnchorKind)
#: The check_reminder_status CHECK.
_REMINDER_STATUSES = ("pending", "done", "dismissed")
#: Where a rule came from (models/maintenance_rule.py).
_RULE_SOURCES = ("pack", "manual", "service")


@dataclass(frozen=True)
class RulePlan:
    """Everything the file's rules family writes, checked and ready."""

    rules: list[tuple[MaintenanceRule, list[Reminder]]]
    warnings: list[str]


def _anchor_kind(row: Mapping[str, Any]) -> str | None:
    """The anchor's kind, a service anchor read as a completion (S8).

    The line item doesn't travel, so a service anchor would drop to a baseline
    on the next reconcile. A word we don't know is no kind, as the API reads it.
    """
    raw = _blank_to_none(row.get("anchor_kind"))
    if raw == "service":
        return "completion"
    return raw if raw in _ANCHOR_KINDS else None


def reminder_from_json(vin: str, row: Any) -> tuple[Reminder, bool]:
    """One reminder as an unsaved row with no rule, and whether its type was dropped.

    A type that isn't a code is dropped rather than refusing the row: the
    reminder still works without one. The caller adds its own path to a reason.
    """
    data = as_object(row)
    title = _json_text(data, "title")
    if title is None:
        raise _RowError("title is missing")
    reminder_type = required_word(data, "reminder_type", _REMINDER_TYPES)
    status = required_word(data, "status", _REMINDER_STATUSES)
    due_date = _json_optional_date(data, "due_date")
    due_mileage_km = _json_decimal(data, "due_mileage_km")
    due_hours = _json_decimal(data, "due_hours")
    _within_api_bounds(ReminderCreate, due_mileage_km=due_mileage_km, due_hours=due_hours)
    try:
        validate_reminder_state(reminder_type, due_date, due_mileage_km, due_hours)
    except ValueError as e:
        raise _RowError(str(e)) from e

    anchor_odometer_km = _json_decimal(data, "anchor_odometer_km")
    anchor_hours = _json_decimal(data, "anchor_hours")
    start_odometer_km = _json_decimal(data, "start_odometer_km")
    start_hours = _json_decimal(data, "start_hours")
    completed_odometer_km = _json_decimal(data, "completed_odometer_km")
    completed_hours = _json_decimal(data, "completed_hours")
    _within_field_bounds(
        AnchorSpec,
        "odometer_km",
        anchor_odometer_km=anchor_odometer_km,
        start_odometer_km=start_odometer_km,
    )
    _within_field_bounds(AnchorSpec, "hours", anchor_hours=anchor_hours, start_hours=start_hours)
    _within_field_bounds(
        ReminderCompleteRequest, "odometer_km", completed_odometer_km=completed_odometer_km
    )
    _within_field_bounds(ReminderCompleteRequest, "engine_hours", completed_hours=completed_hours)

    raw_type = _blank_to_none(data.get("maintenance_type"))
    maintenance_type = raw_type if isinstance(raw_type, str) and is_valid_code(raw_type) else None
    columns: dict[str, Any] = {
        "vin": vin,
        "title": title,
        "reminder_type": reminder_type,
        "status": status,
        "due_date": due_date,
        "due_mileage_km": due_mileage_km,
        "due_hours": due_hours,
        "notes": _json_text(data, "notes"),
        "snoozed_until": _json_optional_date(data, "snoozed_until"),
        "maintenance_type": maintenance_type,
        "anchor_kind": _anchor_kind(data),
        "anchor_date": _json_optional_date(data, "anchor_date"),
        "anchor_odometer_km": anchor_odometer_km,
        "anchor_hours": anchor_hours,
        "start_odometer_km": start_odometer_km,
        "start_hours": start_hours,
        "completed_at": _json_row_datetime(data, "completed_at"),
        "completed_date": _json_optional_date(data, "completed_date"),
        "completed_odometer_km": completed_odometer_km,
        "completed_hours": completed_hours,
    }
    # Missing keeps the column's default, the import's own now.
    created_at = _json_row_datetime(data, "created_at")
    if created_at is not None:
        columns["created_at"] = created_at
    return Reminder(**columns), raw_type is not None and maintenance_type is None


def manual_reminder_key(row: Mapping[str, Any], reminder: Reminder) -> list[ColumnElement[bool]]:
    """S6's manual reminder key, each due part only when the row has it (T-16).

    Type and status are always in it: the row can't parse without them. The
    route adds the vehicle and the no-rule, no-sync filters.
    """
    key = [
        Reminder.title == reminder.title,
        Reminder.reminder_type == reminder.reminder_type,
        Reminder.status == reminder.status,
    ]
    if "due_date" in row:
        key.append(_matches(Reminder.due_date, reminder.due_date))
    if "due_mileage_km" in row:
        key.append(_same_figure(Reminder.due_mileage_km, reminder.due_mileage_km))
    if "due_hours" in row:
        key.append(_same_figure(Reminder.due_hours, reminder.due_hours))
    return key


def _rule_from_json(vin: str, row: Mapping[str, Any]) -> MaintenanceRule:
    """One rule as an unsaved row, held to RecurrenceSpec's interval rules."""
    title = _json_text(row, "title")
    if title is None:
        raise _RowError("title is missing")
    maintenance_type = _blank_to_none(row.get("maintenance_type"))
    if maintenance_type is not None:
        if not isinstance(maintenance_type, str):
            raise _RowError("maintenance_type must be a lowercase snake_case code (2-50 chars)")
        try:
            validate_maintenance_type(maintenance_type)
        except ValueError as e:
            raise _RowError(str(e)) from e
    interval_km = _json_decimal(row, "interval_km")
    interval_months = _json_int(row, "interval_months")
    interval_days = _json_int(row, "interval_days")
    interval_hours = _json_decimal(row, "interval_hours")
    _within_api_bounds(
        RecurrenceSpec,
        interval_km=interval_km,
        interval_months=interval_months,
        interval_days=interval_days,
        interval_hours=interval_hours,
    )
    # RecurrenceSpec's own two rules, in its order and words (D-7). No stored
    # rule can break them: every write path goes through it or the pack's twin.
    if all(v is None for v in (interval_km, interval_months, interval_days, interval_hours)):
        raise _RowError("recurrence needs at least one interval")
    if interval_km is not None and interval_hours is not None:
        raise _RowError("recurrence may use a distance or an hours interval, not both")
    return MaintenanceRule(
        vin=vin,
        maintenance_type=maintenance_type,
        title=title,
        interval_km=interval_km,
        interval_months=interval_months,
        interval_days=interval_days,
        interval_hours=interval_hours,
        source=required_word(row, "source", _RULE_SOURCES),
        # A soft link: the pack may not exist here, and the rule is the vehicle's own copy (N-8).
        source_pack_id=_json_text(row, "source_pack_id"),
        source_pack_key=_json_text(row, "source_pack_key"),
        notes=_json_text(row, "notes"),
        is_active=_json_bool(row, "is_active", default=True),
    )


def parse_rules(vin: str, sections: Mapping[str, list[Any]]) -> RulePlan:
    """The file's rules, each with its reminders, every row checked, nothing touching the session.

    Two rules of one type come in as two (K2). `ensure_rule` would 409 on the
    second, and merging them would move both due points.
    """
    rules: list[tuple[MaintenanceRule, list[Reminder]]] = []
    warnings: list[str] = []
    for i, raw in enumerate(sections["maintenance_rules"]):
        try:
            row = as_object(raw)
            rule = _rule_from_json(vin, row)
            raw_reminders = nested_list(row, "reminders")
        except _RowError as e:
            raise _RowError(f"Maintenance rule {i}: {e.reason}") from e
        reminders: list[Reminder] = []
        for j, raw_reminder in enumerate(raw_reminders):
            try:
                reminder, type_dropped = reminder_from_json(vin, raw_reminder)
            except _RowError as e:
                raise _RowError(f"Maintenance rule {i}, reminder {j}: {e.reason}") from e
            if type_dropped:
                warnings.append(
                    f"Maintenance rule {i}, reminder {j}: its maintenance type isn't a code, "
                    "so it was saved without one"
                )
            reminders.append(reminder)
        # One pending per rule, as `uq_reminders_rule_pending` will insist anyway.
        if sum(r.status == "pending" for r in reminders) > 1:
            raise _RowError(f"Maintenance rule {i}: has more than one pending reminder")
        rules.append((rule, reminders))
    return RulePlan(rules=rules, warnings=warnings)


async def write_rules(db: AsyncSession, plan: RulePlan) -> None:
    """Write each rule, then its reminders with the rule's new id."""
    for rule, reminders in plan.rules:
        db.add(rule)
        await db.flush()
        for reminder in reminders:
            reminder.rule_id = rule.id
        db.add_all(reminders)
        await db.flush()
