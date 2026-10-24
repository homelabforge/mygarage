"""Build a compact, grounded context blob for Ask My Garage."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.note import Note
from app.models.reminder import Reminder
from app.models.service_visit import ServiceVisit
from app.models.supply import Supply
from app.models.tire import Tire
from app.models.vehicle import TrailerDetails, Vehicle
from app.models.vehicle_dtc import VehicleDTC
from app.services.dtc_service import DTCService
from app.utils.render_context import RenderContext, render_context_default, with_vehicle
from app.utils.unit_formatting import format_quantity

# SAE-style OBD codes: P/B/C/U + 4 hex digits (e.g. P0420, B0001).
_DTC_CODE_RE = re.compile(r"\b([PBCUpbcu][0-9A-Fa-f]{4})\b")

_MAX_CONTEXT_CHARS = 12_000
_NOTE_CONTENT_CAP = 400
_MAX_SERVICE_VISITS = 5
_MAX_NOTES = 8
_MAX_SUPPLIES = 12
_MAX_ACTIVE_DTCS = 10
_MAX_CLEARED_DTCS = 5
_MAX_LOOKED_UP = 8


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _measure(value: Decimal | None, ctx: RenderContext, quantity: str) -> str | None:
    """A canonical reading as the string the model quotes, unit included.

    None stays None rather than format_quantity's "N/A", so the model still
    sees the field as missing and says so.
    """
    return None if value is None else format_quantity(value, ctx, quantity)


def extract_dtc_codes(text: str) -> list[str]:
    """Return unique uppercase DTC codes mentioned in free text."""
    seen: set[str] = set()
    out: list[str] = []
    for match in _DTC_CODE_RE.finditer(text or ""):
        code = match.group(1).upper()
        if code not in seen:
            seen.add(code)
            out.append(code)
    return out


async def build_garage_context(
    db: AsyncSession,
    vin: str,
    *,
    user_message: str | None = None,
    ctx: RenderContext | None = None,
) -> dict[str, Any]:
    """Assemble garage + diagnostics context for one VIN.

    Pure DB reads — no LLM call. Truncates deterministically to stay under
    ``_MAX_CONTEXT_CHARS`` when serialized.

    :param ctx: Whose units the reader reads in. Every measurement goes out
        as a finished string in those units, with the vehicle's own odometer
        unit laid on top, and the canonical number is never sent: a model
        handed both quotes whichever it likes (#237). Defaults to the instance
        default when omitted.
    """
    vin = vin.upper().strip()
    vehicle = await db.get(Vehicle, vin)
    if vehicle is None:
        return {}

    if ctx is None:
        ctx = await render_context_default(db)
    ctx = with_vehicle(ctx, vehicle)

    dtc_service = DTCService(db)

    visits_result = await db.execute(
        select(ServiceVisit)
        .where(ServiceVisit.vin == vin)
        .options(selectinload(ServiceVisit.line_items))
        .order_by(ServiceVisit.date.desc(), ServiceVisit.id.desc())
        .limit(_MAX_SERVICE_VISITS)
    )
    visits = list(visits_result.scalars().all())

    notes_result = await db.execute(
        select(Note)
        .where(Note.vin == vin)
        .order_by(Note.date.desc(), Note.id.desc())
        .limit(_MAX_NOTES)
    )
    notes = list(notes_result.scalars().all())

    supplies_result = await db.execute(
        select(Supply)
        .where(
            Supply.is_active.is_(True),
            or_(Supply.vin == vin, Supply.vin.is_(None)),
        )
        .order_by(Supply.name)
        .limit(_MAX_SUPPLIES)
    )
    supplies = list(supplies_result.scalars().all())

    tires_result = await db.execute(select(Tire).where(Tire.vin == vin).order_by(Tire.position))
    tires = list(tires_result.scalars().all())

    reminders_result = await db.execute(
        select(Reminder)
        .where(Reminder.vin == vin, Reminder.status == "pending")
        .order_by(Reminder.due_date.asc(), Reminder.id.desc())
        .limit(8)
    )
    reminders = list(reminders_result.scalars().all())

    trailer = await db.get(TrailerDetails, vin)

    active_dtcs_result = await db.execute(
        select(VehicleDTC)
        .where(VehicleDTC.vin == vin, VehicleDTC.is_active.is_(True))
        .order_by(VehicleDTC.last_seen.desc())
        .limit(_MAX_ACTIVE_DTCS)
    )
    active_dtcs = list(active_dtcs_result.scalars().all())

    cleared_dtcs_result = await db.execute(
        select(VehicleDTC)
        .where(VehicleDTC.vin == vin, VehicleDTC.is_active.is_(False))
        .order_by(VehicleDTC.last_seen.desc())
        .limit(_MAX_CLEARED_DTCS)
    )
    cleared_dtcs = list(cleared_dtcs_result.scalars().all())

    looked_up: list[dict[str, Any]] = []
    mentioned = extract_dtc_codes(user_message or "")
    known_codes = {d.code.upper() for d in active_dtcs} | {d.code.upper() for d in cleared_dtcs}

    def _parse_list(raw: str | None) -> list[str] | None:
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except json.JSONDecodeError, TypeError:
            pass
        return None

    for code in mentioned[:_MAX_LOOKED_UP]:
        if code in known_codes:
            continue
        definition = await dtc_service.lookup_dtc(code)
        if definition is None:
            looked_up.append({"code": code, "found": False})
            continue
        looked_up.append(
            {
                "code": code,
                "found": True,
                "description": definition.description,
                "category": definition.category,
                "common_causes": _parse_list(definition.common_causes),
                "symptoms": _parse_list(definition.symptoms),
                "fix_guidance": definition.fix_guidance,
                "estimated_severity_level": definition.estimated_severity_level,
            }
        )

    async def _enrich_list(rows: list[VehicleDTC]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in rows:
            enriched = await dtc_service.enrich_dtc_response(row)
            out.append(
                {
                    "code": enriched.get("code"),
                    "description": enriched.get("description"),
                    "severity": enriched.get("severity"),
                    "is_active": enriched.get("is_active"),
                    "first_seen": _jsonable(enriched.get("first_seen")),
                    "last_seen": _jsonable(enriched.get("last_seen")),
                    "cleared_at": _jsonable(enriched.get("cleared_at")),
                    "user_notes": enriched.get("user_notes"),
                    "common_causes": enriched.get("common_causes"),
                    "symptoms": enriched.get("symptoms"),
                    "fix_guidance": enriched.get("fix_guidance"),
                    "category": enriched.get("category"),
                }
            )
        return out

    context: dict[str, Any] = {
        "vehicle": {
            "vin": vehicle.vin,
            "nickname": vehicle.nickname,
            "year": vehicle.year,
            "make": vehicle.make,
            "model": vehicle.model,
            "trim": vehicle.trim,
            "vehicle_type": vehicle.vehicle_type,
            "fuel_type": vehicle.fuel_type,
            "displacement_l": vehicle.displacement_l,
            "cylinders": vehicle.cylinders,
            "transmission_type": vehicle.transmission_type,
            "drive_type": vehicle.drive_type,
            "tire_specs": vehicle.tire_specs,
            "wheel_specs": vehicle.wheel_specs,
            "def_tank_capacity": _measure(vehicle.def_tank_capacity_liters, ctx, "volume"),
        },
        "maintenance_specs": {
            "oil_viscosity": vehicle.oil_viscosity,
            "oil_capacity": _measure(vehicle.oil_capacity_liters, ctx, "volume"),
            "oil_filter_part_number": vehicle.oil_filter_part_number,
            "lug_nut_torque": _measure(vehicle.lug_nut_torque_nm, ctx, "torque"),
            "coolant_type": vehicle.coolant_type,
            "brake_fluid_type": vehicle.brake_fluid_type,
            "transmission_fluid_type": vehicle.transmission_fluid_type,
            "maintenance_specs_notes": vehicle.maintenance_specs_notes,
        },
        "service_visits": [
            {
                "date": _jsonable(v.date),
                "odometer": _measure(v.odometer_km, ctx, "distance"),
                "engine_hours": _jsonable(v.engine_hours),
                "total_cost": _jsonable(v.total_cost),
                "service_category": v.service_category,
                "notes": (v.notes or "")[:300] or None,
                "line_items": [
                    {
                        "description": li.description,
                        "category": li.category,
                        "notes": (li.notes or "")[:200] or None,
                        "cost": _jsonable(li.cost),
                    }
                    for li in (v.line_items or [])
                ],
            }
            for v in visits
        ],
        "notes": [
            {
                "date": _jsonable(n.date),
                "title": n.title,
                "content": (n.content or "")[:_NOTE_CONTENT_CAP],
            }
            for n in notes
        ],
        "supplies": [
            {
                "name": s.name,
                "part_number": s.part_number,
                "category": s.category,
                "vin_scoped": s.vin == vin,
                "notes": (s.notes or "")[:200] or None,
            }
            for s in supplies
        ],
        "tires": [
            {
                "position": t.position,
                "brand": t.brand,
                "model_name": t.model_name,
                "size": t.size,
                "pressure": _measure(t.pressure_kpa, ctx, "pressure"),
                "tread_depth": _measure(t.tread_depth_mm, ctx, "tread"),
            }
            for t in tires
        ],
        "reminders": [
            {
                "title": r.title,
                "reminder_type": r.reminder_type,
                "due_date": _jsonable(r.due_date),
                "due_mileage": _measure(r.due_mileage_km, ctx, "distance"),
                "due_hours": _jsonable(r.due_hours),
                "notes": (r.notes or "")[:200] or None,
            }
            for r in reminders
        ],
        "diagnostics": {
            "active_dtcs": await _enrich_list(active_dtcs),
            "recently_cleared_dtcs": await _enrich_list(cleared_dtcs),
            "looked_up_codes": looked_up,
        },
    }

    if trailer is not None:
        context["trailer"] = {
            "gvwr": _measure(trailer.gvwr_kg, ctx, "mass"),
            "hitch_type": trailer.hitch_type,
            "axle_count": trailer.axle_count,
            "brake_type": trailer.brake_type,
            "length": _measure(trailer.length_m, ctx, "length"),
            "width": _measure(trailer.width_m, ctx, "length"),
            "height": _measure(trailer.height_m, ctx, "length"),
            "tow_vehicle_vin": trailer.tow_vehicle_vin,
        }

    serialized = json.dumps(context, default=str)
    if len(serialized) > _MAX_CONTEXT_CHARS:
        # Drop oldest notes / supplies first, then truncate note content further.
        while (
            len(context["notes"]) > 2 and len(json.dumps(context, default=str)) > _MAX_CONTEXT_CHARS
        ):
            context["notes"].pop()
        while (
            len(context["supplies"]) > 4
            and len(json.dumps(context, default=str)) > _MAX_CONTEXT_CHARS
        ):
            context["supplies"].pop()
        while (
            len(context["service_visits"]) > 2
            and len(json.dumps(context, default=str)) > _MAX_CONTEXT_CHARS
        ):
            context["service_visits"].pop()

    return context
