"""The maintenance lifecycle: rules, anchors, reconciliation, completion, packs.

    MaintenanceRule (WHEN)  ->  typed ServiceLineItem (WHAT HAPPENED)  ->  Reminder (WHAT IS NEXT)

Everything here is idempotent by construction: a reconcile writes only what
differs, so a hook that runs twice, an import replayed, or a pack applied
again changes nothing the second time. The design (with its codex review
record) is `documents/obsidian/builds/mygarage/plans/2026-09-16-v3.5.0-maintenance-lifecycle-design.md`.

Concurrency: `reconcile_vehicle`, `complete_reminder`, `apply_pack` and
`reconcile_duplicates` take `lock_vehicle_for_write` after the route's
authorisation and before their first read, and commit once. Two hooks racing
on one vehicle therefore serialise, and `uq_reminders_rule_pending` is the
backstop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.maintenance_rule import MaintenanceRule
from app.models.reminder import Reminder
from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.schemas.maintenance import (
    AnchorCandidate,
    AnchorChoice,
    AnchorProposal,
    ApplyPackPreview,
    DuplicateGroup,
    IntervalOverride,
    MaintenanceRuleCreate,
    MaintenanceRuleUpdate,
    PackItemPlan,
    ReconcileDuplicatesRequest,
    ReminderCompleteRequest,
)
from app.schemas.reminder import ReminderCompleteResponse, ReminderCreate, ReminderUpdate
from app.schemas.reminder_pack import ReminderPackDetail, ReminderPackItem
from app.services.hours_service import nearest_hours
from app.services.maintenance_recurrence import (
    Anchor,
    HasIntervals,
    Thresholds,
    next_thresholds,
)
from app.services.odometer_service import nearest_odometer
from app.services.reminder_service import (
    enrich_with_estimate,
    get_current_hours,
    get_current_mileage,
    validate_reminder_state,
)
from app.services.vehicle_lock import lock_vehicle_for_write
from app.utils.cache import invalidate_cache_for_vehicle
from app.utils.datetime_utils import utc_now
from app.utils.household_time import household_today
from app.utils.logging_utils import sanitize_for_log
from app.utils.maintenance_types import (
    get_compiled,
    is_valid_code,
    label_for,
    normalise,
    resolve_type,
)

logger = logging.getLogger(__name__)

ACTIVE_STATUS = "pending"


# ============================================================================
#  Rules
# ============================================================================


async def rules_of_type(db: AsyncSession, vin: str, maintenance_type: str) -> list[MaintenanceRule]:
    """Every rule of `maintenance_type` on the vehicle, active or not, oldest first."""
    result = await db.execute(
        select(MaintenanceRule)
        .where(MaintenanceRule.vin == vin, MaintenanceRule.maintenance_type == maintenance_type)
        .order_by(MaintenanceRule.id)
    )
    return list(result.scalars().all())


async def list_rules(db: AsyncSession, vin: str) -> list[MaintenanceRule]:
    """Every rule on the vehicle, active first, then by title."""
    result = await db.execute(
        select(MaintenanceRule)
        .where(MaintenanceRule.vin == vin)
        .order_by(MaintenanceRule.is_active.desc(), MaintenanceRule.title, MaintenanceRule.id)
    )
    return list(result.scalars().all())


async def get_rule_or_404(db: AsyncSession, vin: str, rule_id: int) -> MaintenanceRule:
    """A rule scoped to the vehicle, or 404."""
    result = await db.execute(
        select(MaintenanceRule).where(MaintenanceRule.id == rule_id, MaintenanceRule.vin == vin)
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Maintenance rule not found")
    return rule


def apply_intervals(rule: MaintenanceRule, spec: HasIntervals) -> bool:
    """Copy the intervals of `spec` onto `rule`; True when something changed."""
    changed = False
    for name in ("interval_km", "interval_months", "interval_days", "interval_hours"):
        value = getattr(spec, name)
        if getattr(rule, name) != value:
            setattr(rule, name, value)
            changed = True
    return changed


@dataclass(frozen=True)
class RuleResolution:
    """What `ensure_rule` did: 'create', 'reuse' or 'reactivate'."""

    rule: MaintenanceRule
    action: str


def _rule_conflict(maintenance_type: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=(
            f"Two maintenance rules of type '{maintenance_type}' exist on this vehicle; "
            "edit one of them instead of adding a third"
        ),
    )


async def ensure_rule(
    db: AsyncSession,
    vin: str,
    *,
    maintenance_type: str | None,
    title: str,
    intervals: HasIntervals,
    source: str,
    source_pack_id: str | None = None,
    source_pack_key: str | None = None,
    notes: str | None = None,
) -> RuleResolution:
    """The vehicle's rule for a type, reusing or reactivating before creating.

    Every ordinary path funnels through here so a type acquires a second rule
    only through the explicit rules endpoint (`create_rule`). With two rules
    already present there is no right answer and the caller gets a 409 (a
    pack plans around it first and skips the item).

    `intervals` are the intervals that WILL apply, and they are written
    unconditionally. There used to be an `update_intervals` flag here so a pack
    could leave an active rule's own numbers alone; the caller decides that now,
    because the caller is the only one that knows whether the user typed an
    override. `apply_intervals` compares before assigning, so handing back a
    rule's existing values writes nothing and does not touch `updated_at`.
    """
    if maintenance_type is not None:
        existing = await rules_of_type(db, vin, maintenance_type)
        if len(existing) >= 2:
            raise _rule_conflict(maintenance_type)
        if existing:
            rule = existing[0]
            if rule.is_active:
                apply_intervals(rule, intervals)
                return RuleResolution(rule, "reuse")
            rule.is_active = True
            apply_intervals(rule, intervals)
            if source_pack_id is not None:
                rule.source_pack_id = source_pack_id
                rule.source_pack_key = source_pack_key
            return RuleResolution(rule, "reactivate")

    rule = MaintenanceRule(
        vin=vin,
        maintenance_type=maintenance_type,
        title=title,
        source=source,
        source_pack_id=source_pack_id,
        source_pack_key=source_pack_key,
        notes=notes,
    )
    apply_intervals(rule, intervals)
    db.add(rule)
    await db.flush()
    return RuleResolution(rule, "create")


async def create_rule(db: AsyncSession, vin: str, data: MaintenanceRuleCreate) -> MaintenanceRule:
    """The explicit path: a new rule even when one of the type exists."""
    rule = MaintenanceRule(
        vin=vin,
        maintenance_type=data.maintenance_type,
        title=data.title,
        source="manual",
        notes=data.notes,
    )
    apply_intervals(rule, data)
    db.add(rule)
    await db.flush()
    await reconcile_rule(db, rule)
    return rule


async def _retype(db: AsyncSession, rule: MaintenanceRule, maintenance_type: str | None) -> None:
    """Change what a rule tracks; its pending reminder follows.

    The pending reminder's anchor was an event of the OLD type, so it is not
    kept forward-only: the reminder re-anchors on this rule's newest event of
    the new type (`best_anchor`), else on a baseline.
    """
    if rule.maintenance_type == maintenance_type:
        return
    rule.maintenance_type = maintenance_type
    await db.flush()
    pending = await _pending_reminder(db, rule.id)
    if pending is None:
        return
    pending.maintenance_type = maintenance_type
    anchor = await best_anchor(db, rule)
    if anchor is None:
        anchor = await baseline_anchor(db, rule.vin, household_today())
    await _reanchor(db, pending, rule, anchor)


async def update_rule(db: AsyncSession, rule: MaintenanceRule, data: MaintenanceRuleUpdate) -> None:
    """Patch a rule and recompute its pending reminder from its own anchor."""
    fields = data.model_fields_set
    if "title" in fields and data.title is not None:
        rule.title = data.title
    if "maintenance_type" in fields:
        await _retype(db, rule, data.maintenance_type)
    if "notes" in fields:
        rule.notes = data.notes
    if "recurrence" in fields and data.recurrence is not None:
        apply_intervals(rule, data.recurrence)
    if "is_active" in fields and data.is_active is not None:
        rule.is_active = data.is_active
    await db.flush()
    if rule.is_active:
        await reconcile_rule(db, rule)


async def delete_rule(db: AsyncSession, rule: MaintenanceRule) -> str:
    """Remove a rule nothing references; deactivate one with history.

    Returns 'deleted' or 'deactivated'. A deactivated rule keeps counting as
    a rule of its type on purpose (see `best_anchor`).
    """
    referenced = await db.scalar(select(func.count(Reminder.id)).where(Reminder.rule_id == rule.id))
    if referenced:
        rule.is_active = False
        await db.flush()
        return "deactivated"
    await db.delete(rule)
    await db.flush()
    return "deleted"


# ============================================================================
#  Anchors
# ============================================================================


def _candidate(row: Any) -> AnchorCandidate:
    return AnchorCandidate(
        line_item_id=row.line_item_id,
        visit_id=row.visit_id,
        date=row.date,
        odometer_km=row.odometer_km,
        engine_hours=row.engine_hours,
        description=row.description,
        maintenance_type=row.maintenance_type,
    )


def _anchor_of_candidate(candidate: AnchorCandidate) -> Anchor:
    """The service anchor a history row stands for."""
    return Anchor(
        "service",
        candidate.date,
        candidate.odometer_km,
        candidate.engine_hours,
        candidate.line_item_id,
    )


def _history_query(vin: str):
    return (
        select(
            ServiceLineItem.id.label("line_item_id"),
            ServiceVisit.id.label("visit_id"),
            ServiceVisit.date.label("date"),
            ServiceVisit.odometer_km.label("odometer_km"),
            ServiceVisit.engine_hours.label("engine_hours"),
            ServiceLineItem.description.label("description"),
            ServiceLineItem.maintenance_type.label("maintenance_type"),
        )
        .join(ServiceVisit, ServiceLineItem.visit_id == ServiceVisit.id)
        .where(ServiceVisit.vin == vin)
        .order_by(ServiceVisit.date.desc(), ServiceVisit.id.desc(), ServiceLineItem.id.desc())
    )


async def typed_history(
    db: AsyncSession,
    vin: str,
    maintenance_type: str,
    *,
    for_rule_id: int | None,
    limit: int | None = None,
) -> list[AnchorCandidate]:
    """Line items of `maintenance_type` on the vehicle, newest first.

    A line item another rule's reminder references (as its anchor or as the
    work that completed it) is left out: a service one rule owns is never
    another rule's anchor.
    """
    other_rule = [Reminder.rule_id.isnot(None)]
    if for_rule_id is not None:
        other_rule.append(Reminder.rule_id != for_rule_id)
    # A reference only OWNS the line item while the two still agree on the
    # type. Retype a service and the reminder that used to count from it holds
    # a stale link; without this the service would belong to nobody.
    still_its_work = or_(
        Reminder.maintenance_type.is_(None),
        ServiceLineItem.maintenance_type.is_(None),
        Reminder.maintenance_type == ServiceLineItem.maintenance_type,
    )
    owned_elsewhere = (
        select(Reminder.line_item_id)
        .join(ServiceLineItem, ServiceLineItem.id == Reminder.line_item_id)
        .where(*other_rule, Reminder.line_item_id.isnot(None), still_its_work)
        .union(
            select(Reminder.completed_line_item_id)
            .join(ServiceLineItem, ServiceLineItem.id == Reminder.completed_line_item_id)
            .where(*other_rule, Reminder.completed_line_item_id.isnot(None), still_its_work)
        )
    )
    query = _history_query(vin).where(
        ServiceLineItem.maintenance_type == maintenance_type,
        ServiceLineItem.id.not_in(owned_elsewhere),
    )
    if limit is not None:
        query = query.limit(limit)
    rows = (await db.execute(query)).all()
    return [_candidate(row) for row in rows]


async def untyped_candidates(
    db: AsyncSession, vin: str, maintenance_type: str, *, limit: int = 5
) -> list[AnchorCandidate]:
    """Recent untyped line items the type's own patterns match.

    These are the descriptions the classifier declined because two types
    claimed them ("Oil change and air filter"). The preview offers them so
    the owner can say which one this is; choosing one stamps its type.
    """
    compiled = get_compiled(maintenance_type)
    if compiled is None:
        return []
    patterns = compiled.include
    rows = (
        await db.execute(
            _history_query(vin).where(ServiceLineItem.maintenance_type.is_(None)).limit(200)
        )
    ).all()
    out: list[AnchorCandidate] = []
    for row in rows:
        text = normalise(row.description)
        if any(p.search(text) for p in patterns):
            out.append(_candidate(row))
            if len(out) >= limit:
                break
    return out


async def _latest_completion(db: AsyncSession, rule: MaintenanceRule) -> Anchor | None:
    """The newest completion of this rule.

    A completion that wrote or linked a line item is a SERVICE anchor read
    from that line item's visit as it is now, so correcting the visit's date
    or odometer moves the anchor; the snapshot on the reminder is the fallback
    only when the line item is gone. Work of another type than the rule now
    tracks (the rule was retyped since) is not this rule's history: the done
    reminder's recorded type decides, which covers mark-only completions and
    completions whose line item was deleted, and a surviving line item of
    another type is skipped too.
    """
    result = await db.execute(
        select(Reminder).where(
            Reminder.rule_id == rule.id,
            Reminder.status == "done",
            Reminder.completed_date.isnot(None),
        )
    )
    best: Anchor | None = None
    for done in result.scalars().all():
        assert done.completed_date is not None
        if (
            done.maintenance_type is not None
            and rule.maintenance_type is not None
            and done.maintenance_type != rule.maintenance_type
        ):
            continue
        anchor: Anchor | None = None
        if done.completed_line_item_id is not None:
            found = await _anchor_from_line_item(db, rule.vin, done.completed_line_item_id)
            if found is not None:
                live, line_item = found
                if (
                    line_item.maintenance_type is not None
                    and rule.maintenance_type is not None
                    and line_item.maintenance_type != rule.maintenance_type
                ):
                    continue
                anchor = live
        if anchor is None:
            anchor = Anchor(
                "completion", done.completed_date, done.completed_odometer_km, done.completed_hours
            )
        if best is None or _newer(anchor, best):
            best = anchor
    return best


def _newer(a: Anchor, b: Anchor) -> bool:
    """Whether `a` is the newer anchor.

    By date; on the same day the higher odometer is the later event (an
    odometer does not run backwards within a day), then a service record
    beats a bare completion, then the higher line item id.
    """
    if a.date != b.date:
        return a.date > b.date
    if a.odometer_km is not None and b.odometer_km is not None and a.odometer_km != b.odometer_km:
        return a.odometer_km > b.odometer_km
    if (a.kind == "service") != (b.kind == "service"):
        return a.kind == "service"
    return (a.line_item_id or 0) > (b.line_item_id or 0)


async def best_anchor(db: AsyncSession, rule: MaintenanceRule) -> Anchor | None:
    """The newest event this rule may count from (design section 5.2)."""
    candidates: list[Anchor] = []
    if rule.maintenance_type is not None:
        siblings = await rules_of_type(db, rule.vin, rule.maintenance_type)
        if len(siblings) == 1:
            history = await typed_history(
                db, rule.vin, rule.maintenance_type, for_rule_id=rule.id, limit=1
            )
            if history:
                candidates.append(_anchor_of_candidate(history[0]))
    completion = await _latest_completion(db, rule)
    if completion is not None:
        candidates.append(completion)
    if not candidates:
        return None
    best = candidates[0]
    for candidate in candidates[1:]:
        if _newer(candidate, best):
            best = candidate
    return best


async def _fill_readings(
    db: AsyncSession,
    vin: str,
    on: date,
    odometer: Decimal | None,
    hours: Decimal | None,
    *,
    need_odometer: bool,
    need_hours: bool,
) -> tuple[Decimal | None, Decimal | None]:
    """A missing reading that is needed comes from the record nearest `on`,
    else from the vehicle's current one. A reading given, or not needed, is
    returned as it came."""
    if odometer is None and need_odometer:
        record = await nearest_odometer(db, vin, on)
        odometer = record.odometer_km if record is not None else await get_current_mileage(vin, db)
    if hours is None and need_hours:
        hours = await nearest_hours(db, vin, on)
        if hours is None:
            hours = await get_current_hours(vin, db)
    return odometer, hours


async def resolve_readings(
    db: AsyncSession, vin: str, anchor: Anchor, rule: HasIntervals
) -> Anchor:
    """Fill a reading the anchor lacks and the rule needs from the nearest record.

    A visit logged without an odometer still anchors a mileage rule on the
    reading closest to its date. A reading the rule does not use is left
    alone: the snapshot records what the service knew.
    """
    odometer, hours = await _fill_readings(
        db,
        vin,
        anchor.date,
        anchor.odometer_km,
        anchor.hours,
        need_odometer=rule.interval_km is not None,
        need_hours=rule.interval_hours is not None,
    )
    if odometer == anchor.odometer_km and hours == anchor.hours:
        return anchor
    return Anchor(anchor.kind, anchor.date, odometer, hours, anchor.line_item_id)


async def baseline_anchor(db: AsyncSession, vin: str, today: date) -> Anchor:
    """Nothing on record: today's date and the current readings, stored once."""
    return Anchor(
        "baseline", today, await get_current_mileage(vin, db), await get_current_hours(vin, db)
    )


def anchor_of(reminder: Reminder) -> Anchor | None:
    """The anchor a reminder carries, or None for a legacy one without."""
    if reminder.anchor_kind is None or reminder.anchor_date is None:
        return None
    return Anchor(
        reminder.anchor_kind,  # type: ignore[arg-type]
        reminder.anchor_date,
        reminder.anchor_odometer_km,
        reminder.anchor_hours,
        reminder.line_item_id if reminder.anchor_kind == "service" else None,
    )


def _set_anchor(reminder: Reminder, anchor: Anchor) -> bool:
    changed = False
    values = {
        "anchor_kind": anchor.kind,
        "anchor_date": anchor.date,
        "anchor_odometer_km": anchor.odometer_km,
        "anchor_hours": anchor.hours,
        "line_item_id": anchor.line_item_id if anchor.kind == "service" else reminder.line_item_id,
    }
    for name, value in values.items():
        if getattr(reminder, name) != value:
            setattr(reminder, name, value)
            changed = True
    return changed


def _set_thresholds(reminder: Reminder, thresholds: Thresholds) -> bool:
    changed = False
    values = {
        "due_date": thresholds.due_date,
        "due_mileage_km": thresholds.due_mileage_km,
        "due_hours": thresholds.due_hours,
        "reminder_type": thresholds.reminder_type,
    }
    for name, value in values.items():
        if getattr(reminder, name) != value:
            setattr(reminder, name, value)
            changed = True
    return changed


async def _reanchor(
    db: AsyncSession, reminder: Reminder, rule: HasIntervals, anchor: Anchor
) -> Anchor:
    """Point `reminder` at `anchor` (readings filled) and recompute its thresholds.

    The one write path for "this reminder now counts from here"; every
    caller that is not creating or completing a reminder goes through it.
    """
    resolved = await resolve_readings(db, reminder.vin, anchor, rule)
    _set_anchor(reminder, resolved)
    thresholds = next_thresholds(rule, resolved)
    if thresholds is not None:
        _set_thresholds(reminder, thresholds)
    return resolved


def _complete(reminder: Reminder, anchor: Anchor) -> None:
    reminder.status = "done"
    reminder.completed_at = utc_now()
    reminder.completed_date = anchor.date
    reminder.completed_odometer_km = anchor.odometer_km
    reminder.completed_hours = anchor.hours
    reminder.completed_line_item_id = anchor.line_item_id
    # The cycle this snooze silenced is over; a rule's successor is a new
    # row and starts un-snoozed either way.
    reminder.snoozed_until = None


async def _pending_reminder(db: AsyncSession, rule_id: int) -> Reminder | None:
    result = await db.execute(
        select(Reminder)
        .where(Reminder.rule_id == rule_id, Reminder.status == ACTIVE_STATUS)
        .order_by(Reminder.id)
    )
    return result.scalars().first()


async def _anchor_from_line_item(
    db: AsyncSession, vin: str, line_item_id: int
) -> tuple[Anchor, ServiceLineItem] | None:
    """A service anchor from one of the vehicle's own line items."""
    row = (
        await db.execute(
            select(ServiceLineItem, ServiceVisit)
            .join(ServiceVisit, ServiceLineItem.visit_id == ServiceVisit.id)
            .where(ServiceLineItem.id == line_item_id, ServiceVisit.vin == vin)
        )
    ).first()
    if row is None:
        return None
    line_item, visit = row
    return (
        Anchor("service", visit.date, visit.odometer_km, visit.engine_hours, line_item.id),
        line_item,
    )


async def _line_item_anchor_or_raise(
    db: AsyncSession, vin: str, line_item_id: int, *, status: int
) -> tuple[Anchor, ServiceLineItem]:
    """`_anchor_from_line_item`, or an HTTP error for a line item that is not the vehicle's."""
    found = await _anchor_from_line_item(db, vin, line_item_id)
    if found is None:
        raise HTTPException(
            status_code=status,
            detail=f"Line item {line_item_id} does not belong to vehicle {vin}",
        )
    return found


async def create_reminder_for_rule(
    db: AsyncSession,
    rule: MaintenanceRule,
    anchor: Anchor,
    *,
    title: str | None = None,
    notes: str | None = None,
) -> Reminder | None:
    """A pending reminder for `rule` counting from `anchor`, or None if the
    rule produces no threshold from it."""
    anchor = await resolve_readings(db, rule.vin, anchor, rule)
    thresholds = next_thresholds(rule, anchor)
    if thresholds is None:
        logger.warning(
            "Rule %s on %s produces no threshold from its anchor; no reminder written",
            rule.id,
            sanitize_for_log(rule.vin),
        )
        return None
    reminder = Reminder(
        vin=rule.vin,
        rule_id=rule.id,
        maintenance_type=rule.maintenance_type,
        title=title or rule.title,
        notes=notes if notes is not None else rule.notes,
        status=ACTIVE_STATUS,
        reminder_type=thresholds.reminder_type,
        due_date=thresholds.due_date,
        due_mileage_km=thresholds.due_mileage_km,
        due_hours=thresholds.due_hours,
    )
    _set_anchor(reminder, anchor)
    db.add(reminder)
    await db.flush()
    return reminder


# ============================================================================
#  Reconciliation
# ============================================================================


async def reconcile_rule(
    db: AsyncSession,
    rule: MaintenanceRule,
    *,
    candidate: Anchor | None = None,
    today: date | None = None,
) -> Reminder | None:
    """Bring the rule's pending reminder in line with the history (section 5.3).

    Returns the pending reminder afterwards (None when the rule cannot
    produce one). `candidate` overrides `best_anchor` for a caller that
    already knows the event, e.g. a typeless rule created from a line item.
    Writes only what differs, so calling it again is a no-op.
    """
    if today is None:
        today = household_today()
    pending = await _pending_reminder(db, rule.id)

    # 0. Refresh a service-anchored reminder from its visit. When that service
    #    is no longer this rule's work, because the owner retyped it or deleted
    #    it, the reminder re-anchors on whatever history is left.
    retyped_away = False
    if pending is not None and pending.anchor_kind == "service":
        if pending.line_item_id is None:
            # The service this reminder counted from was deleted (the link is
            # ON DELETE SET NULL), so its snapshot describes a record that no
            # longer exists.
            retyped_away = True
        else:
            refreshed = await _anchor_from_line_item(db, rule.vin, pending.line_item_id)
            if refreshed is not None:
                anchor, line_item = refreshed
                if (
                    line_item.maintenance_type is not None
                    and rule.maintenance_type is not None
                    and line_item.maintenance_type != rule.maintenance_type
                ):
                    retyped_away = True
                else:
                    _set_anchor(pending, await resolve_readings(db, rule.vin, anchor, rule))

    best = candidate if candidate is not None else await best_anchor(db, rule)

    if retyped_away and pending is not None:
        pending.line_item_id = None
        await _reanchor(
            db,
            pending,
            rule,
            best if best is not None else await baseline_anchor(db, rule.vin, today),
        )
        return pending

    if best is None:
        if pending is None:
            return await create_reminder_for_rule(
                db, rule, await baseline_anchor(db, rule.vin, today)
            )
        current = anchor_of(pending)
        if current is not None:
            # A reading the anchor lacked may exist by now (a pack applied
            # before the first odometer entry); keep the resolved snapshot.
            await _reanchor(db, pending, rule, current)
        return pending

    best = await resolve_readings(db, rule.vin, best, rule)

    if pending is None:
        return await create_reminder_for_rule(db, rule, best)

    current = anchor_of(pending)
    if current is None:
        # A legacy reminder without an anchor: a service newer than its own
        # creation completes it (section 5.3 step 4 with a NULL anchor date);
        # anything else it adopts as its anchor.
        created_on = pending.created_at.date() if pending.created_at else None
        if created_on is not None and best.date > created_on:
            _complete(pending, best)
            return await create_reminder_for_rule(db, rule, best)
        await _reanchor(db, pending, rule, best)
        return pending

    same_line_item = (
        best.line_item_id is not None
        and current.line_item_id is not None
        and best.line_item_id == current.line_item_id
    )
    if same_line_item or (current.kind == "baseline" and best.date <= current.date):
        # The same service seen again (its visit may have been edited), or a
        # placeholder that a real event on or before its date replaces:
        # re-anchor, no completion.
        await _reanchor(db, pending, rule, best)
        return pending

    if best.date == current.date:
        # Two events on one day never complete each other. The later one
        # (`_newer`: higher odometer, then a service over a bare completion)
        # is the anchor, so an explicit "done today" at a higher reading keeps
        # precedence over an earlier same-day service, and a service logged at
        # the same reading as a mark-only completion takes over from it.
        await _reanchor(db, pending, rule, current if _newer(current, best) else best)
        return pending

    if best.date > current.date:
        _complete(pending, best)
        await db.flush()
        return await create_reminder_for_rule(db, rule, best)

    # best is older than the pending reminder's own anchor: nothing to do
    # beyond keeping its thresholds in step with the intervals.
    await _reanchor(db, pending, rule, current)
    return pending


async def reconcile_vehicle_unlocked(db: AsyncSession, vin: str) -> None:
    """Reconcile every active rule; the caller holds the lock and commits."""
    result = await db.execute(
        select(MaintenanceRule)
        .where(MaintenanceRule.vin == vin, MaintenanceRule.is_active.is_(True))
        .order_by(MaintenanceRule.id)
    )
    for rule in result.scalars().all():
        await reconcile_rule(db, rule)
    await db.flush()


async def reconcile_vehicle(db: AsyncSession, vin: str) -> None:
    """The hook every service-visit write calls: lock, reconcile, commit.

    Runs after the visit's own commits. A failure here is logged and does
    not fail the request that already persisted the visit; the next hook or
    `POST .../reminders/reconcile` repairs from the same state.
    """
    try:
        await lock_vehicle_for_write(db, vin)
        await reconcile_vehicle_unlocked(db, vin)
        await db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        logger.error(
            "Maintenance reconcile failed for %s: %s", sanitize_for_log(vin), sanitize_for_log(exc)
        )


# ============================================================================
#  Reminders created by hand or from a line item
# ============================================================================


async def create_recurring_reminder(db: AsyncSession, vin: str, data: ReminderCreate) -> Reminder:
    """A reminder with a recurrence: its rule, its anchor, its thresholds.

    The rule of the type is reused (intervals updated) or created. The anchor
    is the linked line item's visit, else the caller's `anchor` (a
    completion: "last done then"), else a baseline. If the rule already has a
    pending reminder, that reminder is the result: an explicit anchor moves it
    (a completion anchor is the owner's word), a baseline never does.
    """
    assert data.recurrence is not None
    # Before the rule lookup: two racing creates would otherwise both read no
    # rule of the type and create one each.
    await lock_vehicle_for_write(db, vin)
    resolution = await ensure_rule(
        db,
        vin,
        maintenance_type=resolve_type(data.maintenance_type, data.title),
        title=data.title,
        intervals=data.recurrence,
        source="manual",
        notes=data.notes,
    )
    rule = resolution.rule
    if resolution.action == "reuse":
        rule.title = data.title
        if data.notes is not None:
            rule.notes = data.notes

    explicit: Anchor | None = None
    if data.line_item_id is not None:
        explicit, _line_item = await _line_item_anchor_or_raise(
            db, vin, data.line_item_id, status=400
        )
    elif data.anchor is not None and (
        data.anchor.date is not None
        or data.anchor.odometer_km is not None
        or data.anchor.hours is not None
    ):
        explicit = Anchor(
            "completion",
            data.anchor.date or household_today(),
            data.anchor.odometer_km,
            data.anchor.hours,
        )

    reminder = await _pending_reminder(db, rule.id)
    if reminder is not None:
        if explicit is not None:
            await _reanchor(db, reminder, rule, explicit)
        else:
            # Newer history may complete this reminder and create its
            # successor; the result is whatever is pending afterwards.
            reminder = await reconcile_rule(db, rule)
    elif explicit is not None:
        reminder = await create_reminder_for_rule(db, rule, explicit)
    else:
        reminder = await reconcile_rule(db, rule)
    if reminder is None:
        raise HTTPException(
            status_code=422,
            detail="The recurrence produces no due target from the available readings",
        )
    reminder.title = data.title
    if data.notes is not None:
        reminder.notes = data.notes
    return reminder


async def create_reminder_for_line_item(
    db: AsyncSession,
    vin: str,
    line_item: ServiceLineItem,
    visit: ServiceVisit,
    data: ReminderCreate,
) -> Reminder | None:
    """A line item's follow-up reminder, anchored on ITS visit.

    Never on the client's idea of the current odometer, which is what put
    Mirage reminder 4 below its own service. With a recurrence, the line
    item's type gets a rule (or the existing one takes these intervals) and
    reconciliation from the typed history does the rest; a typeless line
    item is anchored explicitly. Without a recurrence it is a one-off with
    the client's thresholds and a service anchor snapshot.
    """
    anchor = Anchor("service", visit.date, visit.odometer_km, visit.engine_hours, line_item.id)
    if data.recurrence is None:
        assert data.reminder_type is not None
        validate_reminder_state(
            data.reminder_type, data.due_date, data.due_mileage_km, data.due_hours
        )
        reminder = Reminder(
            vin=vin,
            line_item_id=line_item.id,
            maintenance_type=line_item.maintenance_type,
            title=data.title,
            reminder_type=data.reminder_type,
            due_date=data.due_date,
            due_mileage_km=data.due_mileage_km,
            due_hours=data.due_hours,
            notes=data.notes,
        )
        _set_anchor(reminder, anchor)
        db.add(reminder)
        await db.flush()
        return reminder

    resolution = await ensure_rule(
        db,
        vin,
        maintenance_type=data.maintenance_type or line_item.maintenance_type,
        title=data.title,
        intervals=data.recurrence,
        source="service",
        notes=data.notes,
    )
    rule = resolution.rule
    if rule.maintenance_type is None:
        return await reconcile_rule(db, rule, candidate=anchor)
    return await reconcile_rule(db, rule)


async def update_reminder_recurrence(
    db: AsyncSession, reminder: Reminder, data: ReminderUpdate
) -> None:
    """Apply the recurrence and type parts of a reminder update.

    `recurrence: null` deactivates the rule; the reminder keeps its current
    thresholds as a one-off. A recurrence on a reminder without a rule gives
    it one (reusing the vehicle's rule of the type) and recomputes its
    thresholds from its own anchor when it has one.
    """
    fields = data.model_fields_set
    rule = reminder.rule
    if "maintenance_type" in fields:
        if rule is not None and rule.is_active and reminder.status == ACTIVE_STATUS:
            # The rule's pending reminder and the rule track one type.
            await _retype(db, rule, data.maintenance_type)
        reminder.maintenance_type = data.maintenance_type
    if "recurrence" not in fields:
        if rule is not None and rule.is_active and ("title" in fields or "notes" in fields):
            if data.title is not None:
                rule.title = data.title
            if "notes" in fields:
                rule.notes = data.notes
        return
    if data.recurrence is None:
        if rule is not None and rule.is_active:
            rule.is_active = False
        return
    if rule is None:
        resolution = await ensure_rule(
            db,
            reminder.vin,
            maintenance_type=reminder.maintenance_type,
            title=data.title or reminder.title,
            intervals=data.recurrence,
            source="manual",
            notes=reminder.notes,
        )
        rule = resolution.rule
        other = await _pending_reminder(db, rule.id)
        if other is not None and other.id != reminder.id:
            raise HTTPException(
                status_code=409,
                detail=f"Reminder {other.id} already tracks this rule; reconcile the duplicates first",
            )
        reminder.rule_id = rule.id
        reminder.rule = rule
    else:
        apply_intervals(rule, data.recurrence)
        rule.is_active = True
    if data.title is not None:
        rule.title = data.title
    if "maintenance_type" in fields:
        await _retype(db, rule, data.maintenance_type)
    current = anchor_of(reminder)
    if current is not None:
        await _reanchor(db, reminder, rule, current)
    await db.flush()


# ============================================================================
#  Completion
# ============================================================================


#: The line item's own width, read off the model so the two can't drift.
_DESCRIPTION_WIDTH: int | None = getattr(
    ServiceLineItem.__table__.c.description.type, "length", None
)


def _line_item_description(title: str, maintenance_type: str | None) -> str:
    """The text a completion's line item carries for the reminder's title.

    The import stores a title raw, so it can be empty, or on SQLite longer than
    a line item holds. Both modes go through here so they write the same text.
    """
    description = title.strip()[:_DESCRIPTION_WIDTH]
    return description or label_for(maintenance_type) or "Completed reminder"


async def complete_reminder(
    db: AsyncSession, vin: str, reminder_id: int, req: ReminderCompleteRequest
) -> ReminderCompleteResponse:
    """Close a reminder with the real date and readings, in one transaction.

    Lock, read, then (by mode) persist a visit with one typed line item, link
    an existing visit (adding a line item if it has none of the type), or
    record the completion alone. Mark the reminder done, create the successor
    if the rule is active, commit once. Two racing completions serialise on
    the lock and the loser reads `done` and gets 409.
    """
    from app.schemas.service_visit import ServiceLineItemCreate, ServiceVisitCreate
    from app.services.service_visit_service import ServiceVisitService

    await lock_vehicle_for_write(db, vin)
    # populate_existing: a caller (the /done route, the webhook) may already
    # hold this reminder in the session from before the lock, and the identity
    # map would hand back that stale `pending` copy.
    reminder = (
        await db.execute(
            select(Reminder)
            .where(Reminder.id == reminder_id, Reminder.vin == vin)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if reminder is None:
        raise HTTPException(status_code=404, detail="Reminder not found")
    if reminder.status != ACTIVE_STATUS:
        raise HTTPException(status_code=409, detail="Reminder is not pending")

    service = ServiceVisitService(db)
    # A hand edit or an old restore can leave free text ("Oil Change") where a
    # code belongs. The strict line-item schema below would raise on it inside
    # the handler, a 500 (EBR-5), so a non-code falls back to the title's
    # classification, as a reminder with no type does. The reminder keeps it.
    stored_type = reminder.maintenance_type
    if stored_type is not None and not is_valid_code(stored_type):
        logger.warning(
            "Reminder %s has a maintenance type that is not a code; completing it by its title",
            reminder.id,
        )
        stored_type = None
    maintenance_type = resolve_type(stored_type, reminder.title)
    visit_id: int | None = None
    line_item_id: int | None = None
    # The event being recorded. A linked visit IS the service record, so its
    # own date and readings are the anchor, not the request's values.
    completed_on = req.completed_date
    given_odometer = req.odometer_km
    given_hours = req.engine_hours

    if req.mode == "create_visit":
        visit_data = ServiceVisitCreate(
            date=req.completed_date,
            odometer_km=req.odometer_km,
            engine_hours=req.engine_hours,
            vendor_id=req.vendor_id,
            notes=req.notes,
            service_category="Maintenance",
            line_items=[
                ServiceLineItemCreate(
                    description=_line_item_description(reminder.title, maintenance_type),
                    category="Maintenance",
                    maintenance_type=maintenance_type,
                    cost=req.cost,
                )
            ],
        )
        # The completion visit is a real visit: its readings feed the
        # odometer/hours history like one logged from the service form.
        visit, items = await service.persist_visit_rows(vin, visit_data, sync_readings=True)
        visit_id = visit.id
        line_item_id = items[0].id
    elif req.mode == "link_visit":
        assert req.service_visit_id is not None
        visit = (
            await db.execute(
                select(ServiceVisit).where(
                    ServiceVisit.id == req.service_visit_id, ServiceVisit.vin == vin
                )
            )
        ).scalar_one_or_none()
        if visit is None:
            raise HTTPException(status_code=404, detail="Service visit not found")
        visit_id = visit.id
        completed_on = visit.date
        given_odometer = visit.odometer_km
        given_hours = visit.engine_hours
        existing_item = None
        if maintenance_type is not None:
            existing_item = (
                (
                    await db.execute(
                        select(ServiceLineItem)
                        .where(
                            ServiceLineItem.visit_id == visit.id,
                            ServiceLineItem.maintenance_type == maintenance_type,
                        )
                        .order_by(ServiceLineItem.id)
                    )
                )
                .scalars()
                .first()
            )
        if existing_item is None:
            existing_item = ServiceLineItem(
                visit_id=visit.id,
                description=_line_item_description(reminder.title, maintenance_type),
                category="Maintenance",
                maintenance_type=maintenance_type,
                cost=req.cost,
            )
            db.add(existing_item)
            await db.flush()
            await service.recompute_visit_total(visit.id)
        line_item_id = existing_item.id

    odometer, hours = await _fill_readings(
        db,
        vin,
        completed_on,
        given_odometer,
        given_hours,
        need_odometer=True,
        need_hours=True,
    )
    if line_item_id is not None:
        anchor = Anchor("service", completed_on, odometer, hours, line_item_id)
    else:
        anchor = Anchor("completion", completed_on, odometer, hours)
    _complete(reminder, anchor)
    await db.flush()

    successor: Reminder | None = None
    rule = reminder.rule
    if rule is not None and rule.is_active:
        successor = await reconcile_rule(db, rule)
    if line_item_id is not None:
        # The typed line item written above is a service like any other, so
        # every active rule of the vehicle reconciles against it in this
        # transaction (a one-off reminder of a type can sit beside that type's
        # rule). The reminder's own rule is reconciled again as a no-op.
        await reconcile_vehicle_unlocked(db, vin)

    await db.commit()
    await invalidate_cache_for_vehicle(vin)
    await db.refresh(reminder)
    if successor is not None:
        await db.refresh(successor)
    return ReminderCompleteResponse(
        reminder=await enrich_with_estimate(reminder, db),
        next_reminder=await enrich_with_estimate(successor, db) if successor is not None else None,
        service_visit_id=visit_id,
        line_item_id=line_item_id,
    )


async def stop_repeating(db: AsyncSession, reminder: Reminder) -> None:
    """Dismissing or deleting a rule's pending reminder stops the repeat.

    The owner removed the reminder the rule produced, so the rule goes
    inactive: leaving it active would have the next reconcile (any service or
    import write) recreate the reminder with the same thresholds. "Not now" is
    a snooze, which is its own feature; this is "stop". The rule keeps its
    history and the Repeat toggle turns it back on.
    """
    rule = reminder.rule
    if reminder.status == ACTIVE_STATUS and rule is not None and rule.is_active:
        rule.is_active = False
        await db.flush()


# ============================================================================
#  Packs
# ============================================================================


@dataclass(frozen=True)
class _Choice:
    """A validated `AnchorChoice`: the line item resolved once, up front."""

    done_today: bool
    anchor: Anchor | None
    line_item: ServiceLineItem | None


async def _loose_candidates(db: AsyncSession, vin: str, maintenance_type: str) -> list[Reminder]:
    """Pending reminders of the type that belong to no rule, newest first."""
    result = await db.execute(
        select(Reminder)
        .where(
            Reminder.vin == vin,
            Reminder.status == ACTIVE_STATUS,
            Reminder.rule_id.is_(None),
            Reminder.maintenance_type == maintenance_type,
        )
        .order_by(Reminder.id.desc())
    )
    return list(result.scalars().all())


def _pick_keeper(candidates: list[Reminder]) -> Reminder:
    """A service-linked candidate (newest anchor) beats a loose one."""
    linked = [r for r in candidates if r.anchor_kind == "service" and r.anchor_date is not None]
    if linked:
        return max(linked, key=lambda r: (r.anchor_date or date.min, r.id))
    return candidates[0]


async def _validate_anchor_choices(
    db: AsyncSession,
    vin: str,
    pack: ReminderPackDetail,
    anchors: dict[str, AnchorChoice | None] | None,
) -> dict[str, _Choice]:
    """Every line item is the vehicle's own; `_by_pack_key` vets the keys."""
    chosen: dict[str, _Choice] = {}
    for key, choice in _by_pack_key(pack, anchors).items():
        anchor: Anchor | None = None
        line_item: ServiceLineItem | None = None
        if choice.line_item_id is not None:
            anchor, line_item = await _line_item_anchor_or_raise(
                db, vin, choice.line_item_id, status=422
            )
        chosen[key] = _Choice(choice.done_today, anchor, line_item)
    return chosen


def _by_pack_key[T](pack: ReminderPackDetail, values: dict[str, T | None] | None) -> dict[str, T]:
    """A caller's per-item map, checked against the pack and stripped of Nones.

    Anchors and interval overrides are both keyed by pack item key and both owe
    the caller the same answer for a key the pack does not have. Keeping that in
    one place means the 422 message exists once: it used to be written out at two
    call sites with tests asserting the literal on both.

    An item the caller did not name is simply absent, so an untouched form sends
    nothing and behaves exactly as it did before the feature existed.
    """
    if not values:
        return {}
    keys = {item.key for item in pack.reminders}
    chosen: dict[str, T] = {}
    for key, value in values.items():
        if key not in keys:
            raise HTTPException(status_code=422, detail=f"Unknown pack item '{key}'")
        if value is not None:
            chosen[key] = value
    return chosen


def _overridden(item: ReminderPackItem, override: IntervalOverride) -> ReminderPackItem:
    """The pack item as the caller just retyped it.

    A copy, never a mutation: `pack.reminders` is the resolved pack and
    `apply_pack` plans each item after the preview already planned it, so
    editing the item in place would leak one call's override into the next.
    """
    return item.model_copy(
        update={
            "interval_km": override.interval_km,
            "interval_months": override.interval_months,
            "interval_days": override.interval_days,
            "interval_hours": override.interval_hours,
        }
    )


async def _plan_item(
    db: AsyncSession,
    vin: str,
    item: ReminderPackItem,
    choice: _Choice | None,
    today: date,
    *,
    for_preview: bool,
    override: IntervalOverride | None = None,
) -> PackItemPlan:
    """What applying `item` would do. Reads only.

    `for_preview` adds the lists only the dialog shows (the typed history and
    the untyped candidates); `apply_pack` plans without them.

    `override` is intervals the caller typed while applying. It is substituted
    BEFORE anything is planned, because the plan reads the intervals: the anchor
    proposal, a `skip` verdict and the "a newer typed service completes this"
    branch all depend on them, so overriding afterwards would preview one thing
    and do another.
    """
    assert item.key is not None
    if override is not None:
        item = _overridden(item, override)
    maintenance_type = resolve_type(item.maintenance_type, item.title) or item.key
    intervals: HasIntervals = item
    plan = PackItemPlan(
        key=item.key,
        maintenance_type=maintenance_type,
        title=item.title,
        interval_km=item.interval_km,
        interval_months=item.interval_months,
        interval_days=item.interval_days,
        interval_hours=item.interval_hours,
        rule_action="create",
    )
    rules = await rules_of_type(db, vin, maintenance_type)
    if len(rules) >= 2:
        plan.rule_action = "skip"
        plan.skip_reason = "two rules of this type exist on the vehicle"
        return plan
    rule = rules[0] if rules else None
    if rule is not None:
        plan.rule_id = rule.id
        plan.rule_action = "reuse" if rule.is_active else "reactivate"
        if rule.is_active and override is None:
            # The vehicle's own intervals win over the pack's, so re-applying a
            # pack does not undo a schedule the owner has tuned.
            #
            # An OVERRIDE is not the pack's value: the caller typed it a moment
            # ago, so it wins over the rule as well and this branch stands down.
            # Without the `override is None` guard the override is substituted
            # above, discarded here, and then previewed and persisted as the old
            # number, which is the failure the reuse-override test exists for.
            plan.interval_km = rule.interval_km
            plan.interval_months = rule.interval_months
            plan.interval_days = rule.interval_days
            plan.interval_hours = rule.interval_hours
            intervals = plan

    pending = await _pending_reminder(db, rule.id) if rule is not None else None
    if pending is None:
        loose = await _loose_candidates(db, vin, maintenance_type)
        if loose:
            keeper = _pick_keeper(loose)
            plan.keep_reminder_id = keeper.id
            plan.adopted = True
            plan.supersede_reminder_ids = [r.id for r in loose if r.id != keeper.id]
            pending = keeper
    else:
        plan.keep_reminder_id = pending.id

    history = await typed_history(
        db,
        vin,
        maintenance_type,
        for_rule_id=rule.id if rule else None,
        limit=5 if for_preview else 1,
    )
    if for_preview:
        plan.typed_history = history
        plan.untyped_candidates = await untyped_candidates(db, vin, maintenance_type)

    # The anchor the reminder would count from after applying.
    current = anchor_of(pending) if pending is not None else None
    newest = history[0] if history else None
    if choice is not None and choice.anchor is not None and choice.line_item is not None:
        # A chosen line item counts as typed history for this plan.
        if newest is None or _newer(choice.anchor, _anchor_of_candidate(newest)):
            newest = AnchorCandidate(
                line_item_id=choice.line_item.id,
                visit_id=choice.line_item.visit_id,
                date=choice.anchor.date,
                odometer_km=choice.anchor.odometer_km,
                engine_hours=choice.anchor.hours,
                description=choice.line_item.description,
                maintenance_type=maintenance_type,
            )
    newest_anchor = _anchor_of_candidate(newest) if newest is not None else None

    proposal: Anchor | None
    origin: str
    note: str | None = None
    if choice is not None and choice.done_today:
        proposal = Anchor(
            "completion",
            today,
            await get_current_mileage(vin, db),
            await get_current_hours(vin, db),
        )
        origin = "reminder"
        note = "treated as done today at the current readings"
    elif current is not None:
        proposal = current
        origin = "reminder"
        if (
            newest_anchor is not None
            and newest_anchor.date > current.date
            and not (
                newest_anchor.line_item_id is not None
                and newest_anchor.line_item_id == current.line_item_id
            )
        ):
            plan.newer_service = newest
            note = "a newer service completes this reminder and starts the next cycle"
        elif (
            current.kind == "baseline"
            and newest_anchor is not None
            and newest_anchor.date < current.date
        ):
            proposal = newest_anchor
            origin = "history"
            note = "an older service replaces the placeholder baseline"
    elif newest_anchor is not None:
        proposal = newest_anchor
        origin = "history"
    elif pending is not None:
        proposal = None
        origin = "reminder"
        note = "keeps its current due values until the first service is logged"
    else:
        proposal = await baseline_anchor(db, vin, today)
        origin = "baseline"
        note = "no matching service on record; counting from today"

    effective = plan.newer_service and newest_anchor or proposal
    if effective is not None:
        resolved = await resolve_readings(db, vin, effective, intervals)
        if resolved.odometer_km != effective.odometer_km or resolved.hours != effective.hours:
            note = (note + "; " if note else "") + "a reading was taken from the nearest record"
        plan.anchor = AnchorProposal(
            kind=resolved.kind,
            date=resolved.date,
            odometer_km=resolved.odometer_km,
            hours=resolved.hours,
            line_item_id=resolved.line_item_id,
            origin=origin,  # type: ignore[arg-type]
            note=note,
        )
        thresholds = next_thresholds(intervals, resolved)
        if thresholds is not None:
            plan.due_date = thresholds.due_date
            plan.due_mileage_km = thresholds.due_mileage_km
            plan.due_hours = thresholds.due_hours
            plan.reminder_type = thresholds.reminder_type
    elif pending is not None:
        plan.due_date = pending.due_date
        plan.due_mileage_km = pending.due_mileage_km
        plan.due_hours = pending.due_hours
        plan.reminder_type = pending.reminder_type
        plan.note = note
    return plan


async def plan_pack(
    db: AsyncSession,
    vin: str,
    pack: ReminderPackDetail,
    anchors: dict[str, AnchorChoice | None] | None,
    overrides: dict[str, IntervalOverride | None] | None = None,
    *,
    today: date | None = None,
) -> ApplyPackPreview:
    """The preview: the same decisions `apply_pack` makes, with no writes."""
    if today is None:
        today = household_today()
    chosen = await _validate_anchor_choices(db, vin, pack, anchors)
    typed = _by_pack_key(pack, overrides)
    items = [
        await _plan_item(
            db,
            vin,
            item,
            chosen.get(item.key or ""),
            today,
            for_preview=True,
            override=typed.get(item.key or ""),
        )
        for item in pack.reminders
    ]
    return ApplyPackPreview(pack_id=pack.id, pack_name=pack.name, items=items)


async def apply_pack(
    db: AsyncSession,
    vin: str,
    pack: ReminderPackDetail,
    anchors: dict[str, AnchorChoice | None] | None,
    overrides: dict[str, IntervalOverride | None] | None = None,
    *,
    today: date | None = None,
) -> list[Reminder]:
    """Apply a pack under the vehicle lock, one commit (section 5.4).

    Returns the pending reminder of every rule the pack touched, in pack
    order, so the response shape stays the list it always was.
    """
    if today is None:
        today = household_today()
    await lock_vehicle_for_write(db, vin)
    chosen = await _validate_anchor_choices(db, vin, pack, anchors)
    typed = _by_pack_key(pack, overrides)
    results: list[Reminder] = []
    for item in pack.reminders:
        assert item.key is not None
        choice = chosen.get(item.key)
        override = typed.get(item.key)
        plan = await _plan_item(db, vin, item, choice, today, for_preview=False, override=override)
        if plan.rule_action == "skip":
            continue
        # 1. A chosen untyped line item is typed: that is what makes the choice durable.
        if choice is not None and choice.line_item is not None:
            if choice.line_item.maintenance_type != plan.maintenance_type:
                choice.line_item.maintenance_type = plan.maintenance_type
                await db.flush()
        # 2. The rule.
        resolution = await ensure_rule(
            db,
            vin,
            maintenance_type=plan.maintenance_type,
            title=item.title,
            source="pack",
            source_pack_id=pack.id,
            source_pack_key=item.key,
            notes=item.notes,
            # THE PLAN, not the item. `_plan_item` has already decided whose
            # intervals win: the override's when the caller typed one, otherwise
            # an active rule's own. Re-deriving that here from `item` plus a flag
            # was the same decision made twice, and the half that got it wrong is
            # how an override used to preview correctly and never persist.
            intervals=plan,
        )
        rule = resolution.rule
        # 3. Adopt loose reminders of the type when the rule has none.
        pending = await _pending_reminder(db, rule.id)
        if pending is None and plan.keep_reminder_id is not None:
            keeper = await db.get(Reminder, plan.keep_reminder_id)
            assert keeper is not None
            keeper.rule_id = rule.id
            keeper.rule = rule
            current = anchor_of(keeper)
            if current is not None:
                await _reanchor(db, keeper, rule, current)
            for superseded_id in plan.supersede_reminder_ids:
                superseded = await db.get(Reminder, superseded_id)
                if superseded is not None and superseded.status == ACTIVE_STATUS:
                    superseded.status = "dismissed"
                    superseded.superseded_by_id = keeper.id
            await db.flush()
            pending = keeper
        # 4. An explicit "done today" is a completion anchor on the pending reminder.
        if choice is not None and choice.done_today:
            completion = Anchor("completion", today, None, None)
            if pending is None:
                pending = await create_reminder_for_rule(db, rule, completion)
            else:
                await _reanchor(db, pending, rule, completion)
            await db.flush()
        # 5. Reconcile: creates when absent, otherwise only moves forward.
        reminder = await reconcile_rule(db, rule, today=today)
        if reminder is not None:
            results.append(reminder)
    await db.commit()
    await invalidate_cache_for_vehicle(vin)
    for reminder in results:
        await db.refresh(reminder)
    return results


# ============================================================================
#  Duplicates
# ============================================================================


async def duplicate_groups(db: AsyncSession, vin: str) -> list[DuplicateGroup]:
    """Pending reminders sharing a maintenance type, with a suggested keeper."""
    result = await db.execute(
        select(Reminder)
        .where(
            Reminder.vin == vin,
            Reminder.status == ACTIVE_STATUS,
            Reminder.maintenance_type.isnot(None),
        )
        .order_by(Reminder.id)
    )
    by_type: dict[str, list[Reminder]] = {}
    for reminder in result.scalars().all():
        assert reminder.maintenance_type is not None
        by_type.setdefault(reminder.maintenance_type, []).append(reminder)
    groups: list[DuplicateGroup] = []
    for maintenance_type, reminders in by_type.items():
        if len(reminders) < 2:
            continue
        ruled = [r for r in reminders if r.rule_id is not None]
        keeper = ruled[0] if ruled else _pick_keeper(list(reversed(reminders)))
        groups.append(
            DuplicateGroup(
                maintenance_type=maintenance_type,
                label=label_for(maintenance_type, reminders[0].title) or maintenance_type,
                reminder_ids=[r.id for r in reminders],
                suggested_keep_id=keeper.id,
            )
        )
    return groups


async def reconcile_duplicates(
    db: AsyncSession, vin: str, req: ReconcileDuplicatesRequest
) -> list[Reminder]:
    """Keep one reminder, supersede the rest, and keep their rules from
    growing the duplicate back (section 5.8). Whole request or nothing."""
    await lock_vehicle_for_write(db, vin)
    ids = [req.keep_id, *req.supersede_ids]
    result = await db.execute(select(Reminder).where(Reminder.id.in_(ids), Reminder.vin == vin))
    found = {r.id: r for r in result.scalars().all()}
    missing = [i for i in ids if i not in found]
    if missing:
        raise HTTPException(
            status_code=404, detail=f"Reminder(s) not found on this vehicle: {missing}"
        )
    keeper = found[req.keep_id]
    losers = [found[i] for i in req.supersede_ids]
    for reminder in [keeper, *losers]:
        if reminder.status != ACTIVE_STATUS:
            raise HTTPException(status_code=409, detail=f"Reminder {reminder.id} is not pending")
    # Only a duplicate GROUP can be reconciled: one maintenance type, named.
    # Without this a stale or hand-made request dismisses unrelated reminders
    # and deactivates their rules.
    types = {reminder.maintenance_type for reminder in [keeper, *losers]}
    if None in types or len(types) != 1:
        raise HTTPException(
            status_code=422,
            detail=(
                "Reminders can only be reconciled as duplicates when they all track "
                "the same maintenance type"
            ),
        )

    loser_rules = [r.rule for r in losers if r.rule is not None and r.rule.id != keeper.rule_id]
    if keeper.rule is None and len(loser_rules) == 1:
        rule = loser_rules[0]
        for loser in losers:
            if loser.rule_id == rule.id:
                loser.status = "dismissed"
                loser.superseded_by_id = keeper.id
        await db.flush()
        keeper.rule_id = rule.id
        keeper.rule = rule
        rule.is_active = True
    else:
        for rule in loser_rules:
            rule.is_active = False
    for loser in losers:
        loser.status = "dismissed"
        loser.superseded_by_id = keeper.id
    await db.flush()
    if keeper.rule is not None and keeper.rule.is_active:
        await reconcile_rule(db, keeper.rule)
    await db.commit()
    await invalidate_cache_for_vehicle(vin)
    for reminder in [keeper, *losers]:
        await db.refresh(reminder)
    return [keeper, *losers]
