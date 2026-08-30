"""Route-level wiring: which render context each PDF route actually passes.

A generator-level test cannot catch the bug that matters here. Every
assertion in `tests/unit/utils/test_pdf_{generator,vehicle_report}.py`
passes just as happily if a route hands the generator a hardcoded default
context on every request, because those tests construct the context
themselves. The wiring is the thing under test, so these go through the
HTTP surface.

Each test therefore seeds the instance default (`default_unit_prefs`) to the
OPPOSITE of the expected answer. A route that fell back to
`render_context_default` on an authenticated request, or that resolved the
vehicle OWNER's units instead of the caller's, then fails rather than
coincidentally agreeing.

Tests share one database with no per-test rollback, so every row created
here is torn down in `finally` and every username, email and VIN is scoped
to this module.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import fitz  # PyMuPDF
import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.units import IMPERIAL_PRESET, METRIC_PRESET, UnitSet
from app.models.reminder import Reminder
from app.models.service_visit import ServiceVisit
from app.models.settings import Setting
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_share import VehicleShare
from app.services.auth import create_access_token
from app.utils.default_unit_prefs import DEFAULT_UNIT_PREFS_KEY

# Pre-computed argon2id hash for "testpassword123", copied from
# tests/conftest.py: hashing here would need threads these containers
# do not always have.
_PASSWORD_HASH = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"

_OWNER_USERNAME = "unitctx_owner"
_VIEWER_USERNAME = "unitctx_viewer"
_VIN = "UNITCTXPDF000001"

# 19,312 canonical km. Chosen so the imperial rendering is a clean, distinct
# number: 19312 / 1.60934 = 11,999.9503, which the mi adapter (precision 0)
# renders as "12,000". Neither figure can be mistaken for the other. The
# divisor is `UnitConverter.MILES_TO_KM`, the rounded 1.60934 this codebase
# actually uses, not the ISO-exact 1.609344.
_ODOMETER_KM = Decimal("19312")
_EXPECTED_KM = "19,312"
_EXPECTED_MI = "12,000"

# 50,000 canonical km -> 50000 / 1.60934 = 31,068.6368 -> "31,069" at
# precision 0. Rendered by the analytics report's reminders table.
_DUE_MILEAGE_KM = Decimal("50000")
_EXPECTED_DUE_KM = "50,000 km"
_EXPECTED_DUE_MI = "31,069 mi"


def _pdf_text(pdf_bytes: bytes) -> str:
    """Extracted PDF text with every whitespace run collapsed to one space.

    The odometer header is a Paragraph in a 0.9-inch column and wraps, so it
    extracts with a newline inside it. Collapsing whitespace asserts on the
    rendered content rather than on the layout.
    """
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return " ".join("".join(page.get_text() for page in doc).split())


def _headers_for(user: User) -> dict[str, str]:
    """Bearer headers for `user`, matching conftest's `auth_headers`."""
    token = create_access_token(data={"sub": str(user.id), "username": user.username})
    return {"Authorization": f"Bearer {token}"}


async def _make_user(
    db: AsyncSession, username: str, units: UnitSet, *, is_admin: bool = False
) -> User:
    """Create a user whose resolved unit set is exactly `units`.

    Every one of the ten quantities is written as an explicit override
    rather than relying on `unit_preference`, so the resolved set cannot
    drift with a preset change.
    """
    user = User(
        username=username,
        email=f"{username}@example.com",
        hashed_password=_PASSWORD_HASH,
        is_active=True,
        is_admin=is_admin,
        unit_preference="custom",
        show_both_units=False,
        unit_distance=units.distance,
        unit_speed=units.speed,
        unit_length=units.length,
        unit_volume=units.volume,
        unit_consumption=units.consumption,
        unit_pressure=units.pressure,
        unit_temperature=units.temperature,
        unit_mass=units.mass,
        unit_torque=units.torque,
        unit_tread=units.tread,
        secondary_gallon=units.secondary_gallon,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _set_setting(db: AsyncSession, key: str, value: str | None) -> None:
    """Upsert (or delete, for `value=None`) one settings row."""
    existing = (await db.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    if value is None:
        if existing is not None:
            await db.delete(existing)
    elif existing is None:
        db.add(Setting(key=key, value=value))
    else:
        existing.value = value
    await db.commit()


async def _seed_vehicle_with_service_visit(db: AsyncSession, owner: User) -> None:
    """One vehicle owned by `owner`, with a single odometer-bearing visit."""
    db.add(
        Vehicle(
            vin=_VIN,
            user_id=owner.id,
            nickname="Unit Context",
            vehicle_type="Car",
            year=2020,
            make="Test",
            model="Units",
            license_plate="UNIT-001",
        )
    )
    await db.commit()
    db.add(
        ServiceVisit(
            vin=_VIN,
            date=date(2026, 1, 15),
            odometer_km=_ODOMETER_KM,
            service_category="Maintenance",
        )
    )
    await db.commit()


async def _cleanup(db: AsyncSession) -> None:
    """Remove every row this module creates, plus the settings it overwrites.

    Ordered child-first rather than relying on cascade, so the teardown does
    not depend on the FK pragma being on for whichever dialect is running.
    """
    await db.execute(delete(VehicleShare).where(VehicleShare.vehicle_vin == _VIN))
    await db.execute(delete(Reminder).where(Reminder.vin == _VIN))
    await db.execute(delete(ServiceVisit).where(ServiceVisit.vin == _VIN))
    await db.execute(delete(Vehicle).where(Vehicle.vin == _VIN))
    await db.execute(delete(User).where(User.username.in_([_OWNER_USERNAME, _VIEWER_USERNAME])))
    await db.commit()
    await _set_setting(db, DEFAULT_UNIT_PREFS_KEY, None)
    await _set_setting(db, "auth_mode", "local")


@pytest.mark.integration
@pytest.mark.asyncio
class TestPdfRoutesUseTheCallersUnits:
    """The four `reports.py` routes and `analytics.py`'s vehicle export."""

    async def test_service_pdf_renders_the_callers_metric_units(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        try:
            owner = await _make_user(db_session, _OWNER_USERNAME, METRIC_PRESET)
            await _seed_vehicle_with_service_visit(db_session, owner)
            # Instance default is imperial: a route that fell back to it
            # would render "Odometer (mi)" here.
            await _set_setting(
                db_session, DEFAULT_UNIT_PREFS_KEY, json.dumps(IMPERIAL_PRESET.model_dump())
            )

            response = await client.get(
                f"/api/vehicles/{_VIN}/reports/service-history-pdf",
                headers=_headers_for(owner),
            )

            assert response.status_code == 200
            text = _pdf_text(response.content)
            assert "Odometer (km)" in text
            assert _EXPECTED_KM in text
            assert "Odometer (mi)" not in text
        finally:
            await _cleanup(db_session)

    async def test_service_pdf_renders_the_callers_imperial_units(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        try:
            owner = await _make_user(db_session, _OWNER_USERNAME, IMPERIAL_PRESET)
            await _seed_vehicle_with_service_visit(db_session, owner)
            await _set_setting(
                db_session, DEFAULT_UNIT_PREFS_KEY, json.dumps(METRIC_PRESET.model_dump())
            )

            response = await client.get(
                f"/api/vehicles/{_VIN}/reports/service-history-pdf",
                headers=_headers_for(owner),
            )

            assert response.status_code == 200
            text = _pdf_text(response.content)
            assert "Odometer (mi)" in text
            assert _EXPECTED_MI in text
            assert "Odometer (km)" not in text
            assert _EXPECTED_KM not in text
        finally:
            await _cleanup(db_session)

    async def test_sale_pdf_renders_the_callers_imperial_units(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A separate route and a separate generator method with its own
        header row, so it needs its own wiring assertion. It is also the one
        route that built its generator with no arguments at all."""
        try:
            owner = await _make_user(db_session, _OWNER_USERNAME, IMPERIAL_PRESET)
            await _seed_vehicle_with_service_visit(db_session, owner)
            await _set_setting(
                db_session, DEFAULT_UNIT_PREFS_KEY, json.dumps(METRIC_PRESET.model_dump())
            )

            response = await client.get(
                f"/api/vehicles/{_VIN}/reports/sale-history-pdf",
                headers=_headers_for(owner),
            )

            assert response.status_code == 200
            text = _pdf_text(response.content)
            assert "Vehicle History Summary" in text
            assert "Odometer (mi)" in text
            assert _EXPECTED_MI in text
            assert "Odometer (km)" not in text
        finally:
            await _cleanup(db_session)

    async def test_a_shared_viewers_units_beat_the_vehicle_owners(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The wiring bug this whole file exists for.

        The owner is imperial, the instance default is imperial, and only
        the shared, non-admin viewer is metric. So "km" is reachable ONLY by
        resolving the caller's own preferences: resolving the owner's units,
        or falling back to the instance default, both render "mi".
        """
        try:
            owner = await _make_user(db_session, _OWNER_USERNAME, IMPERIAL_PRESET)
            viewer = await _make_user(db_session, _VIEWER_USERNAME, METRIC_PRESET)
            await _seed_vehicle_with_service_visit(db_session, owner)
            db_session.add(
                VehicleShare(
                    vehicle_vin=_VIN,
                    user_id=viewer.id,
                    permission="read",
                    shared_by=owner.id,
                )
            )
            await db_session.commit()
            await _set_setting(
                db_session, DEFAULT_UNIT_PREFS_KEY, json.dumps(IMPERIAL_PRESET.model_dump())
            )

            response = await client.get(
                f"/api/vehicles/{_VIN}/reports/service-history-pdf",
                headers=_headers_for(viewer),
            )

            assert response.status_code == 200
            text = _pdf_text(response.content)
            assert "Odometer (km)" in text
            assert _EXPECTED_KM in text
            assert "Odometer (mi)" not in text
            assert _EXPECTED_MI not in text
        finally:
            await _cleanup(db_session)

    async def test_auth_mode_none_uses_the_instance_default_not_the_owners_units(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """With `auth_mode=none` there is no caller to resolve from, so the
        instance default applies. The owner is imperial and the default is
        metric, so resolving the owner's units would render "mi"."""
        try:
            owner = await _make_user(db_session, _OWNER_USERNAME, IMPERIAL_PRESET)
            await _seed_vehicle_with_service_visit(db_session, owner)
            await _set_setting(
                db_session, DEFAULT_UNIT_PREFS_KEY, json.dumps(METRIC_PRESET.model_dump())
            )
            await _set_setting(db_session, "auth_mode", "none")

            # No Authorization header at all: `require_auth` returns None.
            response = await client.get(f"/api/vehicles/{_VIN}/reports/service-history-pdf")

            assert response.status_code == 200
            text = _pdf_text(response.content)
            assert "Odometer (km)" in text
            assert _EXPECTED_KM in text
            assert "Odometer (mi)" not in text
        finally:
            await _cleanup(db_session)

    async def test_analytics_export_renders_the_callers_imperial_units(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The fifth call site, a different route module and a different
        generator. Asserted on the reminders table, whose due-mileage figure
        is canonical km and depends on nothing but the render context."""
        try:
            owner = await _make_user(db_session, _OWNER_USERNAME, IMPERIAL_PRESET)
            await _seed_vehicle_with_service_visit(db_session, owner)
            db_session.add(
                Reminder(
                    vin=_VIN,
                    title="Tire rotation",
                    reminder_type="mileage",
                    due_mileage_km=_DUE_MILEAGE_KM,
                    status="pending",
                )
            )
            await db_session.commit()
            await _set_setting(
                db_session, DEFAULT_UNIT_PREFS_KEY, json.dumps(METRIC_PRESET.model_dump())
            )

            response = await client.get(
                f"/api/analytics/vehicles/{_VIN}/export",
                headers=_headers_for(owner),
            )

            assert response.status_code == 200
            text = _pdf_text(response.content)
            assert "Tire rotation" in text
            assert _EXPECTED_DUE_MI in text
            assert _EXPECTED_DUE_KM not in text
            # The KPI label no longer hardcodes a distance unit.
            assert "COST PER DISTANCE" in text
            assert "COST PER KM" not in text
        finally:
            await _cleanup(db_session)
