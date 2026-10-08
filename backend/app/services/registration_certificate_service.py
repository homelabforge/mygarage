"""Import an EU registration certificate into a vehicle (#211).

``parse_upload`` reads the file through the document reader (the PDF's
text, else the vision model, else 409) and turns what the certificate says
into a validated ``vehicle_patch``; ``apply_to_vehicle`` writes that patch
through the ordinary vehicle update (which also re-plans the periodic
inspection), and records field X.1, the last inspection, as a service visit
the maintenance lifecycle then anchors on. Nothing here overwrites a value
a person typed unless asked to, and the VIN is never written.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.fuel import CARTE_GRISE_ENERGY_CODES
from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.service_visit import ServiceLineItemCreate, ServiceVisitCreate
from app.schemas.vehicle import VehicleUpdate
from app.services import document_reader_service, maintenance_service
from app.services.country_profile_service import profile_for_country
from app.services.document_parsers.registration import RegistrationData, from_llm_fields
from app.services.document_parsers.registry import DocumentParserRegistry
from app.services.service_visit_service import ServiceVisitService
from app.services.vehicle_lock import lock_vehicle_for_write
from app.services.vehicle_service import VehicleService
from app.utils.logging_utils import sanitize_for_log
from app.utils.vehicle_columns import fit_to_column

logger = logging.getLogger(__name__)

INSPECTION_TYPE = "state_inspection"
#: ``documents.document_type`` of a stored certificate: the type the Documents
#: tab already lists and labels.
DOCUMENT_TYPE = "registration"
#: What the inspection line item says when the country has no profile.
DEFAULT_INSPECTION_TITLE = "Technical inspection"

#: Field J.1 (national kind) → vehicle type. French codes; other countries
#: fall through to field J.
_NATIONAL_TYPES: dict[str, str] = {
    "VP": "Car",
    "CTTE": "Truck",
    "CAM": "Truck",
    "TRR": "Truck",
    "VASP": "RV",
    "MTL": "Motorcycle",
    "MTT1": "Motorcycle",
    "MTT2": "Motorcycle",
    "MTT": "Motorcycle",
    "CYCL": "Motorcycle",
    "CL": "Motorcycle",
    "TM": "Motorcycle",
    "QM": "ATV",
    "REM": "Trailer",
    "SREM": "Trailer",
}
#: Field J (EU category) by its first letters → vehicle type.
_EU_TYPES: tuple[tuple[str, str], ...] = (
    ("M1", "Car"),
    ("M", "Truck"),
    ("N", "Truck"),
    ("L6", "Car"),
    ("L7", "Car"),
    ("L", "Motorcycle"),
    ("O", "Trailer"),
)


def guess_vehicle_type(eu_category: str | None, national_category: str | None) -> str | None:
    """The vehicle type the categories imply, or None when neither says."""
    national = (national_category or "").upper()
    if national in _NATIONAL_TYPES:
        return _NATIONAL_TYPES[national]
    eu = (eu_category or "").upper()
    for prefix, vehicle_type in _EU_TYPES:
        if eu.startswith(prefix):
            return vehicle_type
    return None


def displacement_litres(displacement_cc: int) -> str:
    """P.1 in cm³ → the ``displacement_l`` string (1498 → ``1.5``)."""
    return f"{displacement_cc / 1000:.1f}"


def vehicle_patch(data: RegistrationData) -> tuple[dict[str, Any], list[str]]:
    """The vehicle fields the certificate fills, each validated as an update.

    A value the vehicle schema refuses (a bound, a vocabulary) is dropped
    with a warning rather than failing the whole read: the person still sees
    every other field. The VIN is carried for the wizard and the mismatch
    check; ``apply_to_vehicle`` never writes it.
    """
    patch: dict[str, Any] = {}
    if data.vin:
        patch["vin"] = data.vin
    if data.plate:
        patch["license_plate"] = data.plate
    if data.first_registration:
        patch["first_registration_date"] = data.first_registration
    if data.make:
        patch["make"] = data.make
    if data.commercial_name:
        patch["model"] = data.commercial_name
    if data.displacement_cc:
        patch["displacement_l"] = displacement_litres(data.displacement_cc)
    if data.power_kw is not None:
        patch["power_kw"] = data.power_kw
    if data.energy_code and data.energy_code in CARTE_GRISE_ENERGY_CODES:
        primary, secondary = CARTE_GRISE_ENERGY_CODES[data.energy_code]
        patch["fuel_type"] = primary.value
        if secondary is not None:
            patch["fuel_type_secondary"] = secondary.value
    if data.fiscal_power is not None:
        patch["fiscal_power"] = data.fiscal_power
    if data.co2_g_km is not None:
        patch["co2_g_km"] = data.co2_g_km
    if data.euro_class:
        patch["euro_emission_class"] = data.euro_class
    if data.eu_category:
        patch["eu_category"] = data.eu_category
    if data.national_category:
        patch["national_category"] = data.national_category
    if data.country:
        patch["registration_country"] = data.country
    vehicle_type = guess_vehicle_type(data.eu_category, data.national_category)
    if vehicle_type is not None:
        patch["vehicle_type"] = vehicle_type

    valid: dict[str, Any] = {}
    warnings: list[str] = []
    for key, value in patch.items():
        if key == "vin":
            valid[key] = value
            continue
        value = fit_to_column(key, value, source="Registration certificate")
        try:
            VehicleUpdate.model_validate({key: value})
        except ValidationError as exc:
            reason = exc.errors()[0].get("msg", "invalid") if exc.errors() else "invalid"
            warnings.append(f"{key}: {value!r} dropped ({reason})")
            continue
        valid[key] = value
    return valid, warnings


def suggested_tax_records(data: RegistrationData) -> list[dict[str, Any]]:
    """Y.1 (regional registration tax) and Y.3 (CO₂ malus) as tax records
    dated field B; the total Y.6 when neither component is printed."""
    if not data.first_registration:
        return []
    suggestions: list[dict[str, Any]] = []

    def add(code: str, tax_type: str) -> None:
        amount = data.taxes.get(code)
        if amount is not None and amount > 0:
            suggestions.append(
                {
                    "code": code,
                    "tax_type": tax_type,
                    "amount": amount,
                    "date": data.first_registration,
                }
            )

    add("Y.1", "registration_tax")
    add("Y.3", "co2_malus")
    if not suggestions:
        add("Y.6", "registration")
    return suggestions


@dataclass
class RegistrationParseResult:
    source: str
    data: RegistrationData
    vehicle_patch: dict[str, Any] = field(default_factory=dict)
    last_inspection_date: date | None = None
    suggested_tax_records: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confidence: float = 0.0
    model: str | None = None
    pages: int = 0

    def fields(self) -> dict[str, Any]:
        """The certificate's fields for the response, without the raw text."""
        fields = self.data.to_dict()
        fields.pop("raw_text", None)
        return fields


async def parse_upload(
    db: AsyncSession,
    *,
    file_bytes: bytes,
    filename: str | None,
    content_type: str | None,
    country: str | None = None,
) -> RegistrationParseResult:
    """Read the file and say what it fills. Raises the reader's 409/400/502."""
    read = await document_reader_service.read_document(
        db,
        kind="registration_certificate",
        file_bytes=file_bytes,
        filename=filename,
        content_type=content_type,
    )
    if read.source == "text":
        text = read.raw_text or ""
        parser = DocumentParserRegistry.get_registration_parser()
        data = parser.parse(text, country=country)
        assert isinstance(data, RegistrationData)
        if not parser.can_parse(text):
            data.warnings.append("The PDF's text does not look like a registration certificate")
    else:
        data = from_llm_fields(read.fields, country=country, model=read.model)
        data.warnings.extend(read.warnings)

    patch, dropped = vehicle_patch(data)
    last_inspection = date.fromisoformat(data.last_inspection) if data.last_inspection else None
    logger.info(
        "Registration certificate read (%s): country=%s confidence=%s fields=%d",
        sanitize_for_log(read.source),
        sanitize_for_log(data.country),
        data.confidence_score,
        len(patch),
    )
    return RegistrationParseResult(
        source=read.source,
        data=data,
        vehicle_patch=patch,
        last_inspection_date=last_inspection,
        suggested_tax_records=suggested_tax_records(data),
        warnings=data.get_validation_warnings() + dropped,
        confidence=data.confidence_score,
        model=read.model,
        pages=read.pages,
    )


@dataclass
class ApplyOutcome:
    applied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    inspection_recorded: bool = False


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


async def apply_to_vehicle(
    db: AsyncSession,
    vehicle: Vehicle,
    result: RegistrationParseResult,
    *,
    overwrite: bool,
    current_user: User,
) -> ApplyOutcome:
    """Write the patch onto the vehicle and record the last inspection.

    Empty fields are filled; a field already set is skipped unless
    ``overwrite``. The vehicle type is never changed without ``overwrite``
    (it is never empty). The VIN is never written: a certificate whose VIN
    differs from the vehicle's gets a warning on the result instead.
    """
    outcome = ApplyOutcome()
    update: dict[str, Any] = {}
    for key, value in result.vehicle_patch.items():
        if key == "vin":
            if value != vehicle.vin:
                outcome.skipped.append("vin")
                result.warnings.append(
                    f"The certificate's VIN {value} is not this vehicle's ({vehicle.vin})"
                )
            continue
        if key == "vehicle_type":
            if overwrite and value != vehicle.vehicle_type:
                update[key] = value
                outcome.applied.append(key)
            else:
                outcome.skipped.append(key)
            continue
        current = getattr(vehicle, key, None)
        if overwrite or _is_empty(current):
            if current != value:
                update[key] = value
                outcome.applied.append(key)
        else:
            outcome.skipped.append(key)

    if update:
        await VehicleService(db).update_vehicle(vehicle.vin, VehicleUpdate(**update), current_user)
        await db.refresh(vehicle)

    if result.last_inspection_date is not None:
        outcome.inspection_recorded = await record_inspection(
            db,
            vehicle.vin,
            result.last_inspection_date,
            country=result.data.country or vehicle.registration_country,
            first_registration=vehicle.first_registration_date,
        )
    return outcome


async def record_inspection(
    db: AsyncSession,
    vin: str,
    on: date,
    *,
    country: str | None,
    first_registration: date | None = None,
) -> bool:
    """Field X.1 as a passed inspection on that date, once.

    A service visit with one ``state_inspection`` line item: the same record
    a person logs after a test, so the inspection engine anchors the next
    due date on it. Skipped when a typed inspection already sits on that
    date, when the date is in the future, or before the first registration.
    """
    if on > date.today() or (first_registration is not None and on < first_registration):
        return False
    profile = profile_for_country(country)
    title = (
        profile.inspection.name
        if profile is not None and profile.inspection is not None
        else DEFAULT_INSPECTION_TITLE
    )
    await lock_vehicle_for_write(db, vin)
    existing = (
        await db.execute(
            select(ServiceLineItem.id)
            .join(ServiceVisit, ServiceLineItem.visit_id == ServiceVisit.id)
            .where(
                ServiceVisit.vin == vin,
                ServiceVisit.date == on,
                ServiceLineItem.maintenance_type == INSPECTION_TYPE,
            )
        )
    ).first()
    if existing is not None:
        await db.rollback()
        return False
    visit = ServiceVisitCreate(
        date=on,
        service_category="Inspection",
        notes="Recorded from the registration certificate (field X.1)",
        line_items=[
            ServiceLineItemCreate(
                description=title,
                category="Inspection",
                maintenance_type=INSPECTION_TYPE,
                is_inspection=True,
                inspection_result="passed",
            )
        ],
    )
    await ServiceVisitService(db).persist_visit_rows(vin, visit, sync_readings=False)
    await db.commit()
    await maintenance_service.reconcile_vehicle(db, vin)
    logger.info(
        "Registration certificate: recorded inspection on %s for %s",
        on.isoformat(),
        sanitize_for_log(vin),
    )
    return True
