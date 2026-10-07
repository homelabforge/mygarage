"""Automatic periodic technical inspection reminders from country profiles (#211).

The profile of the vehicle's country (`country_profile_service`) says how
often the roadworthiness test recurs: `inspection.schedules`, one cadence per
vehicle type (and, where the law differs, per fuel). This module turns that
into one `MaintenanceRule` of type ``state_inspection`` with
``source='inspection'`` per vehicle, and keeps its pending reminder in step
with what the owner records, through the same lifecycle every other rule
uses: a typed service of the type completes the reminder and the successor
counts from it (`maintenance_service.reconcile_rule`).

Two parts:

- the pure part (`schedule_for`, `theoretical_due_dates`, `plan_cycle`)
  computes the cycle a vehicle is in from its first registration date, its
  last recorded inspection and today, with no database;
- the database part (`sync_vehicle`, `pause_vehicle`, `sync_all`) applies
  that plan under the vehicle lock the caller holds, writing only what
  differs, so every hook that calls it twice changes nothing the second time.

When the engine has nothing to say (no country, a country without a profile
or without a schedule for this vehicle type, no first registration date, the
owner's preference off, the vehicle archived or sold) it pauses its own rule
and dismisses the reminder it produced; a rule a person made is never
touched. An inactive rule stays inactive on a routine sync (the owner
dismissed the reminder, which stops the repeat); only the events that could
turn the engine back on (a country, a date, the preference) pass
``force_reactivate``.

Dates are indicative: the profile's cadence is the legal minimum for the
common case, the `note` of each schedule says what it leaves out, and the
owner can edit the rule's interval like any other.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Literal

from dateutil.relativedelta import relativedelta
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.maintenance_rule import MaintenanceRule
from app.models.service_line_item import ServiceLineItem
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.country_profile import CountryProfile, InspectionSchedule
from app.schemas.maintenance import AnchorKind, RecurrenceSpec
from app.services import maintenance_service
from app.services.country_profile_service import profile_for_vehicle
from app.services.maintenance_recurrence import Anchor, add_interval
from app.services.settings_service import SettingsService
from app.services.vehicle_lock import lock_vehicle_for_write
from app.utils.household_time import household_today
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

#: The maintenance type the engine schedules (`app.utils.maintenance_types`).
INSPECTION_TYPE = "state_inspection"
#: `vehicle_maintenance_rules.source` / `vehicle_reminders.source` of what it writes.
INSPECTION_SOURCE = "inspection"
#: The instance fallback for a vehicle whose owner has no preference.
INSPECTION_AUTO_SCHEDULE_SETTING = "inspection_auto_schedule"
#: Days per month of lead window; the window is coarse by nature.
_DAYS_PER_MONTH = 30
#: Safety net on the theoretical cadence walk (a vehicle older than this
#: many cycles is not a car anyone schedules).
_MAX_CYCLES = 400

PauseReason = Literal[
    "archived", "disabled", "no_profile", "no_schedule", "no_first_registration_date"
]
SyncAction = Literal["scheduled", "paused", "skipped", "kept"]


# ============================================================================
#  Pure part
# ============================================================================


@dataclass(frozen=True)
class CyclePlan:
    """The cycle the vehicle is in: what the reminder counts from and when it is due."""

    #: What the next due date counts from: the last inspection, else the last
    #: theoretical due date (or the first registration on the first cycle).
    anchor_date: date
    #: 'service' when counted from a recorded inspection, 'baseline' when
    #: computed from the first registration date alone.
    anchor_kind: AnchorKind
    #: The rule's interval: months from the anchor to the due date.
    interval_months: int
    due_date: date
    #: No inspection is due yet: the vehicle has never reached its first one.
    first_cycle: bool
    #: The last inspection failed and a re-test is due within the retest window.
    retest: bool
    #: Days before `due_date` from which the inspection may be done, or None.
    lead_days: int | None


def schedule_for(
    profile: CountryProfile,
    vehicle_type: str | None,
    fuel_type: str | None = None,
    fuel_type_secondary: str | None = None,
) -> InspectionSchedule | None:
    """The schedule of the profile that applies to this vehicle.

    A schedule names its vehicle types; one that also names fuel types applies
    only to a vehicle running on one of them, primary or secondary. When two
    apply (a Dutch petrol car converted to LPG matches both grids) the
    stricter one wins, the one whose first inspection comes earliest, which
    is what the stricter fuel's rule says about such a vehicle.
    """
    if profile.inspection is None or not vehicle_type:
        return None
    fuels = {f for f in (fuel_type, fuel_type_secondary) if f}
    best: InspectionSchedule | None = None
    for schedule in profile.inspection.schedules:
        if vehicle_type not in schedule.vehicle_types:
            continue
        if schedule.fuel_types and not fuels.intersection(schedule.fuel_types):
            continue
        if best is None or (schedule.steps[0].first_after_years or 0) < (
            best.steps[0].first_after_years or 0
        ):
            best = schedule
    return best


def age_in_years(first_registration: date, on: date) -> int:
    """Whole years between the first registration and `on`, birthday style."""
    years = on.year - first_registration.year
    if (on.month, on.day) < (first_registration.month, first_registration.day):
        years -= 1
    return years


def every_years_at(schedule: InspectionSchedule, age_years: int) -> int:
    """How many years the cycle that starts at `age_years` lasts.

    The first step whose `until_age_years` is null or above the age applies;
    the profile schema guarantees a last step without an age limit.
    """
    for step in schedule.steps[1:]:
        if step.every_years is None:
            continue
        if step.until_age_years is None or step.until_age_years > age_years:
            return step.every_years
    last = schedule.steps[-1].every_years
    assert last is not None
    return last


def theoretical_due_dates(
    schedule: InspectionSchedule, first_registration: date, until: date
) -> list[date]:
    """Every due date from the first registration, up to and including the
    first one after `until`, assuming each inspection was done on its due date.

    France, car registered 2023-03-12, until 2026-10-07: [2027-03-12].
    Luxembourg, 2020-01-15, until 2026-10-07: [2024-01-15, 2026-01-15,
    2027-01-15] (4 years, then 2 until age 6, then yearly).
    """
    first = schedule.steps[0].first_after_years
    assert first is not None
    due = first_registration + relativedelta(years=first)
    dates = [due]
    while due <= until and len(dates) < _MAX_CYCLES:
        due = due + relativedelta(
            years=every_years_at(schedule, age_in_years(first_registration, due))
        )
        dates.append(due)
    return dates


def _months_between(start: date, end: date) -> int:
    """Whole calendar months from `start` to `end`, as `add_interval` counts
    them: 2024-02-29 to 2027-02-28 is 36, because 2024-02-29 plus 36 months
    lands on 2027-02-28 (month-end clamped), which is what the rule's
    interval must reproduce."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if add_interval(start, months, None) > end:
        months -= 1
    return max(months, 1)


def plan_cycle(
    profile: CountryProfile,
    schedule: InspectionSchedule,
    first_registration: date,
    today: date,
    *,
    last_inspection: date | None = None,
    last_failed: bool = False,
) -> CyclePlan:
    """The cycle the vehicle is in.

    1. The last inspection failed and the profile has a retest window: the
       re-test is due that many months after it.
    2. An inspection is on record: the next one is due the cycle length (at
       the vehicle's age at that inspection) after it. Validity runs from the
       test date in every profiled country, so an early test moves the next
       due date earlier too.
    3. Nothing on record: the theoretical cadence from the first registration.
       The reminder counts from the last theoretical due date (the owner is
       assumed to have passed it) and is due on the next one; before the first
       one it counts from the first registration itself.
    """
    rules = profile.inspection
    assert rules is not None
    lead_days = rules.lead_window_months * _DAYS_PER_MONTH or None

    if last_inspection is not None:
        if last_failed and rules.retest_window_months:
            months = rules.retest_window_months
            return CyclePlan(
                anchor_date=last_inspection,
                anchor_kind="service",
                interval_months=months,
                due_date=add_interval(last_inspection, months, None),
                first_cycle=False,
                retest=True,
                lead_days=lead_days,
            )
        months = every_years_at(schedule, age_in_years(first_registration, last_inspection)) * 12
        return CyclePlan(
            anchor_date=last_inspection,
            anchor_kind="service",
            interval_months=months,
            due_date=add_interval(last_inspection, months, None),
            first_cycle=False,
            retest=False,
            lead_days=lead_days,
        )

    dues = theoretical_due_dates(schedule, first_registration, today)
    past = [d for d in dues if d <= today]
    due = next(d for d in dues if d > today)
    anchor = past[-1] if past else first_registration
    return CyclePlan(
        anchor_date=anchor,
        anchor_kind="baseline",
        interval_months=_months_between(anchor, due),
        due_date=due,
        first_cycle=not past,
        retest=False,
        lead_days=lead_days,
    )


# ============================================================================
#  Database part
# ============================================================================


@dataclass(frozen=True)
class SyncResult:
    """What `sync_vehicle` did, for logs and tests."""

    action: SyncAction
    rule_id: int | None = None
    reminder_id: int | None = None
    reason: str | None = None


async def auto_schedule_enabled(db: AsyncSession, vehicle: Vehicle) -> bool:
    """The owner's preference; the instance setting for an ownerless vehicle."""
    if vehicle.user_id is not None:
        owner = await db.get(User, vehicle.user_id)
        if owner is not None:
            return bool(owner.inspection_auto_schedule)
    return await SettingsService.get_bool(db, INSPECTION_AUTO_SCHEDULE_SETTING, default=True)


async def engine_rule(db: AsyncSession, vin: str) -> MaintenanceRule | None:
    """The engine's own rule on the vehicle, if any."""
    rules = await maintenance_service.rules_of_type(db, vin, INSPECTION_TYPE)
    return next((r for r in rules if r.source == INSPECTION_SOURCE), None)


async def pause_vehicle(
    db: AsyncSession, vin: str, *, reason: PauseReason | None = None
) -> SyncResult:
    """Deactivate the engine's rule and dismiss its pending reminder.

    A rule a person made (any other `source`) is left alone: the engine only
    takes back what it wrote. The caller holds the lock and commits.
    """
    rule = await engine_rule(db, vin)
    if rule is None:
        return SyncResult("skipped", reason=reason)
    changed = False
    if rule.is_active:
        rule.is_active = False
        changed = True
    pending = await maintenance_service.pending_reminder(db, rule.id)
    if pending is not None:
        pending.status = "dismissed"
        changed = True
    if changed:
        await db.flush()
    return SyncResult(
        "paused" if changed else "skipped",
        rule_id=rule.id,
        reminder_id=pending.id if pending is not None else None,
        reason=reason,
    )


async def _newest_inspection(
    db: AsyncSession, vin: str, rule: MaintenanceRule | None
) -> Anchor | None:
    """The newest inspection on record: the rule's best anchor (typed history
    and completions), or, before the rule exists, the newest typed line item."""
    if rule is not None:
        return await maintenance_service.best_anchor(db, rule)
    history = await maintenance_service.typed_history(
        db, vin, INSPECTION_TYPE, for_rule_id=None, limit=1
    )
    if not history:
        return None
    first = history[0]
    return Anchor("service", first.date, first.odometer_km, first.engine_hours, first.line_item_id)


async def _failed(db: AsyncSession, anchor: Anchor | None) -> bool:
    """Whether the anchor's line item records a failed inspection."""
    if anchor is None or anchor.line_item_id is None:
        return False
    result = await db.execute(
        select(ServiceLineItem.inspection_result).where(ServiceLineItem.id == anchor.line_item_id)
    )
    return result.scalar_one_or_none() == "failed"


async def sync_vehicle(
    db: AsyncSession,
    vehicle: Vehicle,
    *,
    today: date | None = None,
    force_reactivate: bool = False,
) -> SyncResult:
    """Bring the vehicle's inspection rule and reminder in line with its profile.

    The caller holds `lock_vehicle_for_write` and commits. Idempotent: a
    second call writes nothing.
    """
    if today is None:
        today = household_today()
    vin = vehicle.vin

    if vehicle.archived_at is not None or vehicle.sold_date is not None:
        return await pause_vehicle(db, vin, reason="archived")
    if not await auto_schedule_enabled(db, vehicle):
        return await pause_vehicle(db, vin, reason="disabled")
    profile = await profile_for_vehicle(db, vehicle)
    if profile is None or profile.inspection is None:
        return await pause_vehicle(db, vin, reason="no_profile")
    schedule = schedule_for(
        profile, vehicle.vehicle_type, vehicle.fuel_type, vehicle.fuel_type_secondary
    )
    if schedule is None:
        return await pause_vehicle(db, vin, reason="no_schedule")
    if vehicle.first_registration_date is None:
        return await pause_vehicle(db, vin, reason="no_first_registration_date")

    rules = await maintenance_service.rules_of_type(db, vin, INSPECTION_TYPE)
    if len(rules) >= 2:
        logger.warning(
            "Inspection schedule skipped for %s: two %s rules exist",
            sanitize_for_log(vin),
            INSPECTION_TYPE,
        )
        return SyncResult("skipped", reason="two_rules")
    rule = rules[0] if rules else None
    if rule is not None and not rule.is_active and not force_reactivate:
        # The owner stopped it (dismissing the reminder stops the repeat), or
        # the engine paused it and nothing that could turn it back on has
        # happened. Either way a routine sync keeps its hands off.
        return SyncResult("kept", rule_id=rule.id, reason="inactive")

    last = await _newest_inspection(db, vin, rule)
    plan = plan_cycle(
        profile,
        schedule,
        vehicle.first_registration_date,
        today,
        last_inspection=last.date if last is not None else None,
        last_failed=await _failed(db, last),
    )

    resolution = await maintenance_service.ensure_rule(
        db,
        vin,
        maintenance_type=INSPECTION_TYPE,
        title=profile.inspection.name,
        intervals=RecurrenceSpec(interval_months=plan.interval_months),
        source=INSPECTION_SOURCE,
    )
    rule = resolution.rule
    if rule.source != INSPECTION_SOURCE:
        # A rule the owner made for the same test is adopted: from now on
        # the engine keeps its cadence, and it carries the test's proper name
        # (« Contrôle technique », « Hauptuntersuchung (HU) »), which follows
        # the vehicle's country.
        rule.source = INSPECTION_SOURCE
    if rule.title != profile.inspection.name:
        rule.title = profile.inspection.name
    if rule.lead_days != plan.lead_days:
        rule.lead_days = plan.lead_days
    await db.flush()

    if last is not None:
        # A real inspection on record: the ordinary lifecycle completes the
        # pending reminder from it (or re-anchors a placeholder) and the
        # successor counts from the test date with the interval set above.
        reminder = await maintenance_service.reconcile_rule(db, rule, today=today)
    else:
        anchor = Anchor("baseline", plan.anchor_date)
        reminder = await maintenance_service.pending_reminder(db, rule.id)
        if reminder is None:
            reminder = await maintenance_service.create_reminder_for_rule(db, rule, anchor)
        else:
            await maintenance_service.reanchor_pending(db, reminder, rule, anchor)
    if reminder is not None:
        if reminder.source != INSPECTION_SOURCE:
            reminder.source = INSPECTION_SOURCE
        if reminder.title != rule.title:
            reminder.title = rule.title
    await db.flush()
    return SyncResult(
        "scheduled",
        rule_id=rule.id,
        reminder_id=reminder.id if reminder is not None else None,
    )


async def sync_vehicle_by_vin(
    db: AsyncSession, vin: str, *, force_reactivate: bool = False
) -> SyncResult | None:
    """`sync_vehicle` for a VIN the caller has locked; None for an unknown VIN."""
    vehicle = await db.get(Vehicle, vin)
    if vehicle is None:
        return None
    return await sync_vehicle(db, vehicle, force_reactivate=force_reactivate)


async def pause_vehicle_locked(db: AsyncSession, vin: str) -> None:
    """Lock, pause, commit: the archive hook. A failure is logged, never raised."""
    try:
        await lock_vehicle_for_write(db, vin)
        await pause_vehicle(db, vin, reason="archived")
        await db.commit()
    except Exception as exc:  # noqa: BLE001 - the archive already succeeded
        await db.rollback()
        logger.error(
            "Inspection schedule pause failed for %s: %s",
            sanitize_for_log(vin),
            sanitize_for_log(exc),
        )


async def resync_vehicle(db: AsyncSession, vin: str, *, force_reactivate: bool = False) -> None:
    """The hook a vehicle or preference write calls after its own commit.

    Goes through `maintenance_service.reconcile_vehicle`, which locks, runs
    every active rule and this engine, commits, and logs a failure instead
    of failing the request that already persisted the change.
    """
    try:
        await maintenance_service.reconcile_vehicle(
            db, vin, inspection_force_reactivate=force_reactivate
        )
    except HTTPException as exc:
        # The lock could not be taken in time: the next hook or the daily
        # sync repairs from the same state.
        logger.warning(
            "Inspection schedule sync deferred for %s: %s",
            sanitize_for_log(vin),
            sanitize_for_log(exc.detail),
        )


async def resync_user_vehicles(db: AsyncSession, user_id: int) -> None:
    """Every live vehicle of the user, after their country or preference changed."""
    result = await db.execute(
        select(Vehicle.vin).where(Vehicle.user_id == user_id, Vehicle.archived_at.is_(None))
    )
    for vin in result.scalars().all():
        await resync_vehicle(db, vin, force_reactivate=True)


async def sync_all(db: AsyncSession, *, today: date | None = None) -> dict[str, int]:
    """The daily job: every live vehicle, one transaction each.

    Catches up with what no hook sees: an instance setting changed, a profile
    corrected by a release, a vehicle whose owner's preference was set before
    the vehicle existed. Returns the count of each action, for the log.
    """
    result = await db.execute(select(Vehicle.vin).where(Vehicle.archived_at.is_(None)))
    vins = list(result.scalars().all())
    # The listing opened no write transaction on SQLite, but a rollback here
    # keeps the lock below from ever finding one open.
    await db.rollback()
    counts: dict[str, int] = {}
    for vin in vins:
        try:
            await lock_vehicle_for_write(db, vin)
            vehicle = await db.get(Vehicle, vin)
            if vehicle is None:
                await db.rollback()
                continue
            outcome = await sync_vehicle(db, vehicle, today=today)
            await db.commit()
            counts[outcome.action] = counts.get(outcome.action, 0) + 1
        except Exception as exc:  # noqa: BLE001 - one vehicle must not stop the sweep
            await db.rollback()
            counts["failed"] = counts.get("failed", 0) + 1
            logger.error(
                "Inspection schedule sync failed for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(exc),
            )
    return counts
