"""The compliance view of one vehicle (#211): reads the country profile, the
vehicle's certificate fields and the inspection engine's reminder, writes
nothing."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle
from app.schemas.compliance import ComplianceResponse, InspectionStatus, LezStatus
from app.services import maintenance_service
from app.services.country_profile_service import profile_for_country, resolve_country
from app.services.inspection_schedule_service import engine_rule
from app.services.reminder_service import window_opens_on
from app.utils.lez import critair_class, estimated_euro_class, euro_class_number


async def compliance_for_vehicle(db: AsyncSession, vehicle: Vehicle) -> ComplianceResponse:
    country = await resolve_country(db, vehicle)
    if country is None:
        return ComplianceResponse(vin=vehicle.vin, reason="no_country")
    profile = profile_for_country(country)
    if profile is None:
        return ComplianceResponse(vin=vehicle.vin, country=country, reason="no_profile")

    euro = euro_class_number(vehicle.euro_emission_class)
    estimated = False
    if euro is None:
        euro = estimated_euro_class(vehicle.first_registration_date)
        estimated = euro is not None

    lez: LezStatus | None = None
    if profile.lez.scheme is not None:
        lez = LezStatus(
            scheme=profile.lez.scheme,
            name=profile.lez.name,
            url=profile.lez.url,
            computed=profile.lez.scheme == "critair",
        )
        if vehicle.lez_class:
            lez.value, lez.basis, lez.overridden = vehicle.lez_class, "override", True
        elif profile.lez.scheme == "critair":
            lez.value, lez.basis = critair_class(
                fuel_type=vehicle.fuel_type,
                fuel_type_secondary=vehicle.fuel_type_secondary,
                vehicle_type=vehicle.vehicle_type,
                euro_class=euro_class_number(vehicle.euro_emission_class),
                first_registration=vehicle.first_registration_date,
            )

    inspection: InspectionStatus | None = None
    if profile.inspection is not None:
        rule = await engine_rule(db, vehicle.vin)
        pending = await maintenance_service.pending_reminder(db, rule.id) if rule else None
        # One constructor call, so the lenient anchor_kind validator runs on
        # the stored value (an attribute set afterwards skips it).
        inspection = InspectionStatus(
            name=profile.inspection.name,
            automatic=rule is not None and rule.is_active,
            rule_id=rule.id if rule else None,
            reminder_id=pending.id if pending else None,
            next_due_date=pending.due_date if pending else None,
            lead_days=rule.lead_days if rule and pending else None,
            window_opens_on=window_opens_on(pending) if pending else None,
            anchor_kind=pending.anchor_kind if pending else None,  # pyright: ignore[reportArgumentType]  # lenient vocab reads the stored str
            from_registration=pending is not None and pending.anchor_kind == "baseline",
        )

    return ComplianceResponse(
        vin=vehicle.vin,
        country=country,
        profile_country=profile.country,
        euro_class=euro,
        euro_class_estimated=estimated,
        lez=lez,
        inspection=inspection,
        sources=list(profile.sources),
    )
