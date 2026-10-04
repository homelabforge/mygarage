"""Load and apply reminder packs, built in and saved.

Two sources, one namespace. The built-ins are JSON files under
`app/data/reminder_packs/`; a saved pack is rows in `reminder_packs` and
`reminder_pack_items`. A saved pack's id always starts with `custom-`, so
`get_pack` decides which side to read from the id's SHAPE rather than trying one
and falling through to the other. A missing saved pack therefore 404s instead of
quietly matching a file.

Everything downstream consumes `ReminderPackDetail`, so the apply pipeline cannot
tell where a pack came from, which is the whole point.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import cast

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.maintenance_rule import MaintenanceRule
from app.models.reminder_pack import ReminderPack, ReminderPackItemRow
from app.models.user import User
from app.schemas.maintenance import AnchorChoice, ApplyPackPreview, IntervalOverride
from app.schemas.reminder import ReminderResponse
from app.schemas.reminder_pack import (
    CUSTOM_PREFIX,
    ReminderPackDetail,
    ReminderPackItem,
    ReminderPackSummary,
    SaveReminderPackRequest,
    custom_pack_id,
    is_custom_pack_id,
)
from app.services import maintenance_service, reminder_service
from app.services.auth import get_vehicle_or_403
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

PACKS_DIR = Path(__file__).resolve().parent.parent / "data" / "reminder_packs"
# Pack ids are filenames (minus .json). Reject anything that could traverse.
_PACK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def _path_within_packs(path: Path) -> Path | None:
    """Return the resolved path if it stays inside PACKS_DIR, else None."""
    try:
        resolved = path.resolve()
        resolved.relative_to(PACKS_DIR.resolve())
    except ValueError, OSError:
        return None
    return resolved


def _load_pack_file(path: Path) -> ReminderPackDetail:
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return ReminderPackDetail.model_validate(data)


def _pack_paths() -> dict[str, Path]:
    """Map filename stem -> resolved path for every readable pack in PACKS_DIR.

    Every path here comes from directory enumeration, never from caller input,
    so a caller-supplied id is only ever used as a dict *key*. That keeps user
    data out of path expressions entirely instead of relying on a
    validate-then-join round trip to make it safe after the fact.
    """
    index: dict[str, Path] = {}
    if not PACKS_DIR.is_dir():
        return index
    for candidate in sorted(PACKS_DIR.glob("*.json")):
        resolved = _path_within_packs(candidate)
        if resolved is None or not resolved.is_file():
            continue
        # The `custom-` prefix is what makes a saved pack's id unable to collide
        # with a file's. `get_pack` routes that prefix to the database and never
        # looks here, so a file claiming it would list as a built-in and then 404
        # on apply. Dropping it here is what turns that invariant from a comment
        # into something enforced.
        if is_custom_pack_id(candidate.stem):
            logger.warning(
                "Ignoring reminder pack %s: the '%s' prefix is reserved for saved packs",
                sanitize_for_log(candidate.name),
                CUSTOM_PREFIX,
            )
            continue
        index[candidate.stem] = resolved
    return index


async def list_packs(
    db: AsyncSession,
    vehicle_type: str | None = None,
    current_user: User | None = None,
) -> list[ReminderPackSummary]:
    """Every pack the caller may apply, built in and saved, sorted by name.

    When ``vehicle_type`` is provided, packs that declare a non-empty
    ``vehicle_types`` list are included only if that type is listed.
    Packs with an empty ``vehicle_types`` list apply to every vehicle.

    One list rather than two sections: a saved pack is marked ``is_custom``, and
    ``can_edit`` says whether THIS caller may rename, overwrite or delete it, so
    the UI never offers a control the API will refuse.
    """
    packs = builtin_summaries(vehicle_type)
    packs.extend(await _saved_summaries(db, vehicle_type, current_user))
    packs.sort(key=lambda p: p.name.lower())
    return packs


def builtin_summaries(vehicle_type: str | None = None) -> list[ReminderPackSummary]:
    """The shipped packs. Unreadable ones are logged and skipped, never fatal:
    one bad file must not take the whole list down.

    Public, and separate from `list_packs`, so the file-loading hardening below
    can be tested without a database session it would not use."""
    packs: list[ReminderPackSummary] = []
    if not PACKS_DIR.is_dir():
        logger.warning("Reminder packs directory missing: %s", PACKS_DIR)
        return packs

    for path in _pack_paths().values():
        try:
            detail = _load_pack_file(path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.error("Failed to load reminder pack %s: %s", path.name, sanitize_for_log(exc))
            continue
        if is_custom_pack_id(detail.id):
            logger.warning(
                "Ignoring reminder pack %s: it declares the reserved '%s' prefix",
                sanitize_for_log(path.name),
                CUSTOM_PREFIX,
            )
            continue
        if vehicle_type and detail.vehicle_types and vehicle_type not in detail.vehicle_types:
            continue
        packs.append(
            ReminderPackSummary(
                id=detail.id,
                name=detail.name,
                description=detail.description,
                reminder_count=len(detail.reminders),
                vehicle_types=list(detail.vehicle_types),
                is_custom=False,
                # A shipped file is never editable through the API: it lives in
                # git, and an overwrite would be lost on the next release.
                can_edit=False,
            )
        )
    return packs


async def get_pack(db: AsyncSession, pack_id: str) -> ReminderPackDetail:
    """Load a single pack by id, or raise 404.

    The id's SHAPE picks the source: a `custom-` prefix means the database and
    only the database, anything else means the files and only the files. No
    fallthrough, so a deleted saved pack 404s instead of matching a file that
    happens to share its name, and the branch is decided before either lookup.

    ``pack_id`` is checked against a conservative identifier pattern and then
    used only as a key into the enumerated pack index, so it never becomes a
    path component. ``../`` and absolute paths 404.
    """
    if not _PACK_ID_RE.fullmatch(pack_id):
        raise HTTPException(status_code=404, detail=f"Reminder pack '{pack_id}' not found")

    if is_custom_pack_id(pack_id):
        return _detail_from_row(await _saved_or_404(db, pack_id))

    return builtin_pack(pack_id)


def builtin_pack(pack_id: str) -> ReminderPackDetail:
    """One shipped pack, by filename stem or by the id it declares."""
    index = _pack_paths()
    path = index.get(pack_id)
    if path is not None:
        try:
            detail = _load_pack_file(path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.error(
                "Failed to load reminder pack %s: %s",
                sanitize_for_log(pack_id),
                sanitize_for_log(exc),
            )
            raise HTTPException(status_code=500, detail="Failed to load reminder pack") from exc
        if detail.id != pack_id:
            raise HTTPException(status_code=404, detail=f"Reminder pack '{pack_id}' not found")
        return detail

    # A pack's filename may differ from the id it declares, so fall back to
    # reading the declared id out of each enumerated pack.
    for resolved in index.values():
        try:
            detail = _load_pack_file(resolved)
        except OSError, json.JSONDecodeError, ValueError:
            continue
        if is_custom_pack_id(detail.id):
            continue
        if detail.id == pack_id:
            return detail

    raise HTTPException(status_code=404, detail=f"Reminder pack '{pack_id}' not found")


async def apply_pack(
    vin: str,
    pack_id: str,
    db: AsyncSession,
    anchors: dict[str, AnchorChoice | None] | None = None,
    overrides: dict[str, IntervalOverride | None] | None = None,
) -> list[ReminderResponse]:
    """Apply a reminder pack to a vehicle through the maintenance lifecycle.

    Each item becomes (or reuses) a per-vehicle maintenance rule; the rule's
    pending reminder is anchored on the vehicle's most recent qualifying
    service, adopts a loose reminder of the same type instead of duplicating
    it, and is created from today's readings only when nothing is on record.
    See ``maintenance_service.apply_pack`` and the design's section 5.4.

    Returns the pending reminder of every rule the pack touched, in pack
    order, the list shape this endpoint always returned.
    """
    pack = await get_pack(db, pack_id)
    reminders = await maintenance_service.apply_pack(db, vin, pack, anchors, overrides)
    return await reminder_service.enrich_reminders(reminders, db)


async def preview_pack(
    vin: str,
    pack_id: str,
    db: AsyncSession,
    anchors: dict[str, AnchorChoice | None] | None = None,
    overrides: dict[str, IntervalOverride | None] | None = None,
) -> ApplyPackPreview:
    """What ``apply_pack`` would do, with no writes."""
    pack = await get_pack(db, pack_id)
    return await maintenance_service.plan_pack(db, vin, pack, anchors, overrides)


# --------------------------------------------------------------------------
# Saved packs
# --------------------------------------------------------------------------


def _vehicle_types(row: ReminderPack) -> list[str]:
    """The pack's vehicle types, tolerating a hand-edited column.

    The column is JSON, so the list arrives as a list and this only has to
    survive a row edited by hand into the wrong SHAPE: a JSON object or a bare
    string deserializes fine and is not a list of types. Either means "every
    type" rather than a 500 on the list endpoint, the same tolerance
    `_coverage_responses` gives a coverage key outside its catalogue.

    A value that is not valid JSON at all is no longer tolerated here, because a
    JSON column raises while the row loads and never reaches this function. That
    is a deliberate trade for the column type: the old `Text` column logged a
    warning and carried on, and a JSON column that cannot be parsed is a corrupt
    database rather than a pack with odd contents.
    """
    # Cast to `object` deliberately, and it is not ceremony. The column is
    # annotated `list[str]`, but that is a promise the model makes and the
    # database does not keep: nothing stops a hand-edited row holding a JSON
    # object. Without the cast pyright narrows to the declared type and calls
    # both checks below statically redundant, which is how a real runtime guard
    # gets deleted to satisfy a type checker.
    value = cast(object, row.vehicle_types)
    if not isinstance(value, list):
        logger.warning("Pack %s has unreadable vehicle_types", sanitize_for_log(row.pack_id))
        return []
    return [v for v in value if isinstance(v, str)]


def _detail_from_row(row: ReminderPack) -> ReminderPackDetail:
    """Project a saved pack into the shape a pack file produces.

    This is the join between the two sources: everything downstream of here sees
    a `ReminderPackDetail` and cannot tell a saved pack from a shipped one.
    """
    return ReminderPackDetail(
        id=row.pack_id,
        name=row.name,
        description=row.description or "",
        vehicle_types=_vehicle_types(row),
        reminders=[
            ReminderPackItem(
                title=item.title,
                key=item.item_key,
                maintenance_type=item.maintenance_type,
                interval_km=item.interval_km,
                interval_months=item.interval_months,
                interval_days=item.interval_days,
                interval_hours=item.interval_hours,
                notes=item.notes,
            )
            for item in row.items
        ],
    )


def may_edit(row: ReminderPack, current_user: User | None) -> bool:
    """Whether this caller may rename, overwrite or delete this saved pack.

    Three cases, and the middle one is the one that needs writing down:

    * No authenticated user. `auth_mode='none'` is supported and `require_auth`
      returns None in it, so there is no identity to compare and everyone is
      effectively the owner. Same shape as `InsuranceService._resolve_access`,
      which treats `current_user is None` as access to everything.
    * Auth on, creator NULL (a deleted user, or a pack saved while auth was
      off). Admin only: nobody can prove they made it, so nobody inherits it.
    * Auth on, creator set. The creator or an admin.
    """
    if current_user is None:
        return True
    if current_user.is_admin:
        return True
    return row.created_by_user_id is not None and row.created_by_user_id == current_user.id


async def _saved_summaries(
    db: AsyncSession,
    vehicle_type: str | None,
    current_user: User | None,
) -> list[ReminderPackSummary]:
    result = await db.execute(select(ReminderPack))
    summaries = []
    for row in result.scalars().unique().all():
        types = _vehicle_types(row)
        if vehicle_type and types and vehicle_type not in types:
            continue
        summaries.append(
            ReminderPackSummary(
                id=row.pack_id,
                name=row.name,
                description=row.description or "",
                reminder_count=len(row.items),
                vehicle_types=types,
                is_custom=True,
                can_edit=may_edit(row, current_user),
            )
        )
    return summaries


async def _saved_or_404(db: AsyncSession, pack_id: str) -> ReminderPack:
    """One saved pack and its items, or 404.

    Items always come along. There WAS a `with_items=False` here, taking the
    `lazy="selectin"` second query off the rename path, and rename was its only
    caller. It was wrong: rename answers a full `ReminderPackDetail`, so
    suppressing the load made every successful rename report `reminders: []` to
    the client. Saving one query on a once-in-a-while request was never worth a
    response that lies about the pack's contents.
    """
    query = select(ReminderPack).where(ReminderPack.pack_id == pack_id)
    result = await db.execute(query)
    row = result.scalars().unique().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Reminder pack '{pack_id}' not found")
    return row


async def _writable_or_403(
    db: AsyncSession, pack_id: str, current_user: User | None
) -> ReminderPack:
    """The saved pack this caller may change, or the right refusal.

    A built-in id is a 409, not a 404: the pack plainly exists, it is just not
    one the API can change, and a 404 would send a reader hunting for a typo in
    an id they read off the list a moment ago.
    """
    if not is_custom_pack_id(pack_id):
        raise HTTPException(
            status_code=409,
            detail=f"'{pack_id}' is a built-in pack and cannot be changed",
        )
    row = await _saved_or_404(db, pack_id)
    if not may_edit(row, current_user):
        raise HTTPException(
            status_code=403, detail="Only the pack's creator or an admin may change it"
        )
    return row


def unsavable_reason(rule: MaintenanceRule, repeated_types: set[str | None]) -> str | None:
    """Why this rule cannot go in a pack, or None when it can.

    Both reasons come from the same place: `maintenance_service` resolves a pack
    item to a rule by `maintenance_type`, so a pack cannot express anything that
    does not survive being keyed that way.

    * A typeless rule. `_plan_item` does
      `resolve_type(item.maintenance_type, item.title) or item.key`, so a
      typeless item comes back TYPED and begins matching services by type. The
      rule's own docstring is explicit that NULL means it never does that, so the
      pack would change the schedule's meaning rather than copy it.
    * Two selected rules of one type. `ensure_rule` reuses by type, so both items
      resolve to the same rule on apply and the second silently vanishes.

    Reported per rule rather than as one refusal for the request, because the
    dialog shows these beside the rules they disqualify.
    """
    if rule.maintenance_type is None:
        return "a reminder with no maintenance type cannot go in a pack"
    if rule.maintenance_type in repeated_types:
        return f"two selected reminders share the type '{rule.maintenance_type}'"
    return None


def _repeated_types(rules: list[MaintenanceRule]) -> set[str | None]:
    """The maintenance types more than one of these rules carries."""
    seen: set[str | None] = set()
    repeated: set[str | None] = set()
    for rule in rules:
        if rule.maintenance_type in seen:
            repeated.add(rule.maintenance_type)
        seen.add(rule.maintenance_type)
    return repeated


async def savable_rules(db: AsyncSession, vin: str, rule_ids: list[int]) -> list[MaintenanceRule]:
    """The vehicle's active rules named by `rule_ids`, in the order given.

    Scoped by `vin` AND `is_active`, so an id belonging to another vehicle is a
    422 naming it rather than a silent skip: silence here would let a caller
    probe for rules on vehicles they cannot see, and a pack is visible to
    everyone.
    """
    result = await db.execute(
        select(MaintenanceRule).where(
            MaintenanceRule.vin == vin,
            MaintenanceRule.is_active.is_(True),
            MaintenanceRule.id.in_(rule_ids),
        )
    )
    by_id = {rule.id: rule for rule in result.scalars().all()}
    missing = [rule_id for rule_id in rule_ids if rule_id not in by_id]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=(
                "These reminders are not active on this vehicle: "
                + ", ".join(str(rule_id) for rule_id in missing)
            ),
        )

    rules = [by_id[rule_id] for rule_id in rule_ids]
    repeated = _repeated_types(rules)
    refusals = [
        f"{rule.title}: {reason}"
        for rule in rules
        if (reason := unsavable_reason(rule, repeated)) is not None
    ]
    if refusals:
        raise HTTPException(status_code=422, detail="; ".join(refusals))
    return rules


def _typed(rule: MaintenanceRule) -> str:
    """The rule's maintenance type, which `savable_rules` has already guaranteed.

    An assert rather than an `or slugify(title)` fallback: the fallback read as a
    supported path and could never run, and `slugify` remains the SCHEMA's
    fallback for pack FILES, which may still declare an item without a type.
    """
    assert rule.maintenance_type is not None, "savable_rules refuses a typeless rule"
    return rule.maintenance_type


def _items_from_rules(rules: list[MaintenanceRule]) -> list[ReminderPackItemRow]:
    """Project rules into pack items.

    `item_key` is the maintenance type, full stop. It needs no de-duplication
    because `savable_rules` has already refused a typeless rule and a repeated
    type, which between them are the only ways two items could want the same key.
    """
    return [
        ReminderPackItemRow(
            # `savable_rules` refused every typeless rule, so this is the type.
            item_key=_typed(rule),
            title=rule.title,
            maintenance_type=rule.maintenance_type,
            interval_km=rule.interval_km,
            interval_months=rule.interval_months,
            interval_days=rule.interval_days,
            interval_hours=rule.interval_hours,
            notes=rule.notes,
            sort_order=order,
        )
        for order, rule in enumerate(rules)
    ]


async def save_pack_from_vehicle(
    db: AsyncSession,
    data: SaveReminderPackRequest,
    current_user: User | None,
) -> ReminderPackDetail:
    """Save one vehicle's chosen rules as a new pack.

    `require_write=True` on the source vehicle, not read access: a pack is
    visible to every user of the instance, so saving one publishes that
    vehicle's schedule, and being allowed to LOOK at someone else's shared
    vehicle is not consent to publish it.
    """
    await get_vehicle_or_403(data.vin, current_user, db, require_write=True)
    rules = await savable_rules(db, data.vin, data.rule_ids)

    pack_id = custom_pack_id(data.name)
    # `usable_pack_name` already refused a name with no slug, so this only fires
    # if a caller bypassed the request schema.
    assert pack_id, "a validated name always yields a pack id"

    row = ReminderPack(
        pack_id=pack_id,
        name=data.name,
        description=data.description,
        vehicle_types=list(data.vehicle_types),
        # From the authenticated context, never from the request body.
        created_by_user_id=current_user.id if current_user else None,
    )
    row.items = _items_from_rules(rules)
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        # The UNIQUE on `pack_id` is the only check: a pre-SELECT would be a
        # round trip on every save and would still lose a two-caller race.
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"A pack named '{data.name}' already exists; overwrite it or choose another name",
        ) from exc
    logger.info("Saved reminder pack %s with %d item(s)", sanitize_for_log(pack_id), len(row.items))
    return _detail_from_row(row)


async def overwrite_pack(
    db: AsyncSession,
    pack_id: str,
    data: SaveReminderPackRequest,
    current_user: User | None,
) -> ReminderPackDetail:
    """Replace a saved pack's contents from a vehicle, keeping its id.

    Items are deleted and re-inserted rather than reconciled: an item's key is
    DERIVED from its rule, so a reconcile would have to guess which old item a
    renamed or retyped rule corresponds to. Wholesale replacement makes the
    result indistinguishable from a fresh save under the same id, which is what
    "save a vehicle over it" should mean.
    """
    row = await _writable_or_403(db, pack_id, current_user)
    await get_vehicle_or_403(data.vin, current_user, db, require_write=True)
    rules = await savable_rules(db, data.vin, data.rule_ids)

    row.name = data.name
    row.description = data.description
    row.vehicle_types = list(data.vehicle_types)

    # ★ THE OLD ITEMS GO IN THEIR OWN FLUSH, BEFORE THE NEW ONES EXIST.
    # `item_key` IS the maintenance type, so any type the vehicle still carries
    # means the replacement row collides with the row it replaces on the
    # `(pack_id, item_key)` unique constraint. SQLAlchemy orders INSERTs ahead of
    # delete-orphan DELETEs within one flush, so assigning the new collection in a
    # single step made the ordinary "save this vehicle over the pack again" a 500.
    # Clearing first turns the DELETEs into their own statement, which is the only
    # ordering that lets a key survive an overwrite.
    row.items.clear()
    await db.flush()

    row.items = _items_from_rules(rules)
    await db.commit()
    logger.info(
        "Overwrote reminder pack %s with %d item(s)", sanitize_for_log(pack_id), len(row.items)
    )
    return _detail_from_row(row)


async def rename_pack(
    db: AsyncSession,
    pack_id: str,
    name: str,
    current_user: User | None,
) -> ReminderPackDetail:
    """Rename a saved pack.

    `pack_id` deliberately does not move with the name. Rules record it in
    `source_pack_id`, so a new id would orphan every rule this pack has already
    created from the pack that created it.
    """
    row = await _writable_or_403(db, pack_id, current_user)
    row.name = name
    await db.commit()
    return _detail_from_row(row)


async def delete_pack(db: AsyncSession, pack_id: str, current_user: User | None) -> None:
    """Delete a saved pack.

    Rules it created are left alone. A rule made from a pack is the vehicle's own
    copy, which is the contract `MaintenanceRule` already documents, so deleting
    the pack must not touch anyone's schedule.
    """
    row = await _writable_or_403(db, pack_id, current_user)
    await db.delete(row)
    await db.commit()
    logger.info("Deleted reminder pack %s", sanitize_for_log(pack_id))
