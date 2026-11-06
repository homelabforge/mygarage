"""Import an EU registration certificate into a vehicle (#211).

``parse_upload`` reads the file through the document reader (the PDF's
text, else the vision model, else 409) and turns what the certificate says
into a validated ``vehicle_patch``; ``apply_to_vehicle`` writes that patch
through the ordinary vehicle update (which also re-plans the periodic
inspection), and keeps field X.1, the date the NEXT inspection is due by,
as the vehicle's ``inspection_due_date``: the inspection engine holds its
reminder to it while no inspection is on record. X.1 never becomes service
history. Nothing here overwrites a value a person typed unless asked to,
and the VIN is never written.

The wizard reads a certificate before the vehicle exists and files it once
the vehicle does. So the document is read once (B5), the parse is kept in
memory under an opaque token bound to the user and the file's SHA-256 for
``PARSE_TOKEN_TTL_SECONDS``; the import presents the file and the token and
reuses the server's own read. The client never sends parsed values the
server trusts. In-process is enough: the app runs one worker.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.fuel import CARTE_GRISE_ENERGY_CODES
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.tax import TaxRecordCreate
from app.schemas.vehicle import VehicleUpdate
from app.services import document_reader_service, maintenance_service
from app.services.document_parsers.registration import RegistrationData, from_llm_fields
from app.services.document_parsers.registry import DocumentParserRegistry
from app.services.tax_service import TaxRecordService
from app.services.vehicle_lock import lock_vehicle_for_write
from app.services.vehicle_service import VehicleService
from app.utils.logging_utils import sanitize_for_log
from app.utils.vehicle_columns import fit_to_column
from app.utils.vehicle_key import display_identifier, has_real_vin, identifier_text

logger = logging.getLogger(__name__)

#: ``documents.document_type`` of a stored certificate: the type the Documents
#: tab already lists and labels.
DOCUMENT_TYPE = "registration"

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
            checked = VehicleUpdate.model_validate({key: value})
        except ValidationError as exc:
            reason = exc.errors()[0].get("msg", "invalid") if exc.errors() else "invalid"
            warnings.append(f"{key}: {value!r} dropped ({reason})")
            continue
        # The preview shows what will be saved: RENAULT is saved as Renault.
        valid[key] = getattr(checked, key) if key in ("make", "model") else value
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
    inspection_due_date: date | None = None
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
    allow_external_vision: bool = False,
) -> RegistrationParseResult:
    """Read the file and say what it fills. Raises the reader's 409/400/502."""
    read = await document_reader_service.read_document(
        db,
        kind="registration_certificate",
        file_bytes=file_bytes,
        filename=filename,
        content_type=content_type,
        allow_external_vision=allow_external_vision,
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
    inspection_due = date.fromisoformat(data.inspection_due) if data.inspection_due else None
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
        inspection_due_date=inspection_due,
        suggested_tax_records=suggested_tax_records(data),
        warnings=data.get_validation_warnings() + dropped,
        confidence=data.confidence_score,
        model=read.model,
        pages=read.pages,
    )


# --- One read per wizard (B5) --------------------------------------------------

#: How long a parse stays reusable: long enough to fill in the wizard.
PARSE_TOKEN_TTL_SECONDS = 30 * 60
#: More live parses than this and the oldest are dropped.
_PARSE_CACHE_MAX = 256


@dataclass
class _CachedParse:
    user_id: int | None
    file_sha256: str
    result: RegistrationParseResult
    expires_at: float


_parse_cache: dict[str, _CachedParse] = {}


def file_digest(content: bytes) -> str:
    """The SHA-256 a parse token is bound to."""
    return hashlib.sha256(content).hexdigest()


def _prune(now: float) -> None:
    for token in [t for t, entry in _parse_cache.items() if entry.expires_at <= now]:
        del _parse_cache[token]
    while len(_parse_cache) >= _PARSE_CACHE_MAX:
        del _parse_cache[next(iter(_parse_cache))]


def remember_parse(
    result: RegistrationParseResult, *, user_id: int | None, file_sha256: str
) -> str:
    """Keep ``result`` for the import that follows; return its opaque token."""
    now = time.monotonic()
    _prune(now)
    token = secrets.token_urlsafe(24)
    _parse_cache[token] = _CachedParse(
        user_id=user_id,
        file_sha256=file_sha256,
        result=result,
        expires_at=now + PARSE_TOKEN_TTL_SECONDS,
    )
    return token


def recall_parse(
    token: str, *, user_id: int | None, file_sha256: str
) -> RegistrationParseResult | None:
    """The parse ``token`` names, used up, when it is this user's and this file's.

    Another user's token is a 403. An unknown or expired token, or a file
    that is not the one parsed, is None: the caller reads the file afresh.
    """
    entry = _parse_cache.get(token)
    if entry is None:
        return None
    if entry.expires_at <= time.monotonic():
        del _parse_cache[token]
        return None
    if entry.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This certificate was read by another user",
        )
    if entry.file_sha256 != file_sha256:
        return None
    del _parse_cache[token]
    return entry.result


def clear_parse_cache() -> None:
    """Forget every kept parse (tests)."""
    _parse_cache.clear()


async def create_suggested_taxes(
    db: AsyncSession,
    vin: str,
    result: RegistrationParseResult,
    codes: list[str],
    current_user: User | None,
) -> list[str]:
    """Create the suggested tax records whose code the person ticked.

    The amounts come from the server's own parse, never from the request:
    a code the parse did not suggest creates nothing.
    """
    wanted = {code.strip().upper() for code in codes if code and code.strip()}
    created: list[str] = []
    service = TaxRecordService(db)
    for suggestion in result.suggested_tax_records:
        if suggestion["code"] not in wanted:
            continue
        await service.create_record(
            vin,
            TaxRecordCreate(
                vin=vin,
                date=date.fromisoformat(suggestion["date"]),
                tax_type=suggestion["tax_type"],
                amount=suggestion["amount"],
                notes=f"Registration certificate, field {suggestion['code']}",
            ),
            current_user,
        )
        created.append(suggestion["code"])
    return created


@dataclass
class ApplyOutcome:
    applied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    inspection_due_recorded: bool = False


def _compact(value: str | None) -> str:
    return "".join(ch for ch in (value or "").upper() if ch.isalnum())


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
    """Write the patch onto the vehicle and keep X.1 as its inspection deadline.

    Empty fields are filled; a field already set is skipped unless
    ``overwrite``. The vehicle type is never changed without ``overwrite``
    (it is never empty). The VIN is never written: a certificate whose VIN
    differs from the vehicle's gets a warning on the result instead.
    """
    outcome = ApplyOutcome()
    update: dict[str, Any] = {}
    # Named by what people see: a vehicle without a VIN (#226) shows its
    # serial, never its generated key.
    own_id = identifier_text(vehicle) or "it has no identifier"
    chassis = result.data.chassis_number
    if chassis and _compact(chassis) != _compact(display_identifier(vehicle)[1]):
        result.warnings.append(
            f"The certificate's chassis number {chassis} is not this vehicle's ({own_id})"
        )
    for key, value in result.vehicle_patch.items():
        if key == "vin":
            if not has_real_vin(vehicle) or value != vehicle.vin:
                outcome.skipped.append("vin")
                result.warnings.append(
                    f"The certificate's VIN {value} is not this vehicle's ({own_id})"
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

    if result.inspection_due_date is not None:
        outcome.inspection_due_recorded = await record_inspection_due(
            db, vehicle.vin, result.inspection_due_date, overwrite=overwrite
        )
    return outcome


async def record_inspection_due(db: AsyncSession, vin: str, due: date, *, overwrite: bool) -> bool:
    """Field X.1 as the vehicle's inspection deadline; whether it changed.

    X.1 (« visite avant le ») is the date the next periodic inspection is
    due by, so it is never recorded as a passed test: the inspection engine
    makes its pending reminder due on it while no inspection is on record and
    the deadline is earlier than its own cadence (`plan_cycle`). Deadlines
    only move forward, so a later one already on file is the newer sticker
    and is kept, unless ``overwrite``.

    Written under the vehicle lock and reconciled in the same transaction
    (B8), so a failed reconcile leaves the old deadline. When nothing
    changes, the lock is let go with a commit, not a rollback: a rollback
    would expire every row in the session, the caller's user included, and
    the tax records written next would trip on it (CX-M1).
    """
    await lock_vehicle_for_write(db, vin)
    vehicle = await db.get(Vehicle, vin, populate_existing=True)
    current = vehicle.inspection_due_date if vehicle is not None else None
    if (
        vehicle is None
        or current == due
        or (current is not None and current > due and not overwrite)
    ):
        await db.commit()
        return False
    vehicle.inspection_due_date = due
    try:
        await db.flush()
        await maintenance_service.reconcile_vehicle_unlocked(db, vin)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    logger.info(
        "Registration certificate: next inspection due by %s for %s",
        due.isoformat(),
        sanitize_for_log(vin),
    )
    return True
