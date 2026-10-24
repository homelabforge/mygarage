"""Unit tests for the Ask My Garage context builder."""

import re
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.services.garage_context_service import extract_dtc_codes


def test_extract_dtc_codes_normalizes_and_dedupes():
    assert extract_dtc_codes("What does p0420 and B0001 mean?") == ["P0420", "B0001"]
    assert extract_dtc_codes("P0420 then p0420 again") == ["P0420"]


def test_extract_dtc_codes_ignores_non_codes():
    assert extract_dtc_codes("no codes here") == []
    assert extract_dtc_codes("") == []
    assert extract_dtc_codes("P42 is too short") == []


class TestContextRendersInTheReadersUnits:
    """The assistant quotes what it is handed, so every measurement must already
    be in the reader's units.

    #237: the context carried `lug_nut_torque_nm` and `oil_capacity_liters`
    beside the rendered strings, and the model quoted the canonical number
    (100 lb-ft came back as "135.6"). No frontend adapter can reach a unit
    already baked into model output, so this is the only place to pin it.
    """

    @pytest.mark.asyncio
    async def test_renders_specs_in_the_readers_units(self, db_session, test_vehicle):
        from app.constants.units import IMPERIAL_PRESET, METRIC_PRESET
        from app.models.vehicle import Vehicle
        from app.services.garage_context_service import build_garage_context
        from app.utils.render_context import RenderContext

        vehicle = await db_session.get(Vehicle, test_vehicle["vin"])
        assert vehicle is not None
        vehicle.oil_capacity_liters = Decimal("4.7")
        vehicle.lug_nut_torque_nm = Decimal("135")
        await db_session.commit()

        imperial = await build_garage_context(
            db_session,
            test_vehicle["vin"],
            ctx=RenderContext(units=IMPERIAL_PRESET, show_both=False),
        )
        metric = await build_garage_context(
            db_session,
            test_vehicle["vin"],
            ctx=RenderContext(units=METRIC_PRESET, show_both=False),
        )

        imp = imperial["maintenance_specs"]
        met = metric["maintenance_specs"]

        # The whole point: the same canonical row reads differently per reader.
        assert imp["lug_nut_torque"] == "99.6 lb-ft"
        assert met["lug_nut_torque"] == "135.0 Nm"
        assert "gal" in imp["oil_capacity"]
        assert met["oil_capacity"].endswith(" L")

    @pytest.mark.asyncio
    async def test_mixed_set_renders_torque_the_binary_flag_would_miss(
        self, db_session, test_vehicle
    ):
        """Litres with lb-ft: the pair a single imperial/metric flag cannot hold."""
        from app.constants.units import IMPERIAL_PRESET
        from app.models.vehicle import Vehicle
        from app.services.garage_context_service import build_garage_context
        from app.utils.render_context import RenderContext

        vehicle = await db_session.get(Vehicle, test_vehicle["vin"])
        assert vehicle is not None
        vehicle.oil_capacity_liters = Decimal("4.7")
        vehicle.lug_nut_torque_nm = Decimal("135")
        await db_session.commit()

        mixed = IMPERIAL_PRESET.model_copy(update={"volume": "L"})
        context = await build_garage_context(
            db_session,
            test_vehicle["vin"],
            ctx=RenderContext(units=mixed, show_both=False),
        )
        specs = context["maintenance_specs"]

        assert "L" in specs["oil_capacity"]
        assert "gal" not in specs["oil_capacity"]
        assert "lb-ft" in specs["lug_nut_torque"]
        assert "Nm" not in specs["lug_nut_torque"]

    @pytest.mark.asyncio
    async def test_no_canonical_measurement_reaches_the_model(self, db_session, test_vehicle):
        """Every unit-bearing row, not just the two specs #237 was reported on."""
        import datetime as dt
        import json

        from app.constants.units import IMPERIAL_PRESET
        from app.models.reminder import Reminder
        from app.models.service_visit import ServiceVisit
        from app.models.tire import Tire
        from app.models.vehicle import TrailerDetails, Vehicle
        from app.services.garage_context_service import build_garage_context
        from app.utils.render_context import RenderContext

        vin = test_vehicle["vin"]
        vehicle = await db_session.get(Vehicle, vin)
        assert vehicle is not None
        vehicle.oil_capacity_liters = Decimal("4.73")
        vehicle.lug_nut_torque_nm = Decimal("135.6")
        vehicle.def_tank_capacity_liters = Decimal("18.93")
        # The test vehicle is shared, so other tests' rows sit beside these. The
        # far-off dates keep ours inside each capped, ordered query on both
        # dialects, and the lookups below find ours instead of trusting [0].
        db_session.add_all(
            [
                ServiceVisit(vin=vin, date=dt.date(2099, 12, 31), odometer_km=Decimal("16093.44")),
                Reminder(
                    vin=vin,
                    title="Oil change #237",
                    reminder_type="both",
                    status="pending",
                    due_date=dt.date(2000, 1, 1),
                    due_mileage_km=Decimal("24140.16"),
                ),
            ]
        )
        tire = (
            await db_session.execute(select(Tire).where(Tire.vin == vin, Tire.position == "FL"))
        ).scalar_one_or_none()
        if tire is None:
            tire = Tire(vin=vin, position="FL")
            db_session.add(tire)
        tire.pressure_kpa = Decimal("241.32")
        tire.tread_depth_mm = Decimal("7.94")
        await db_session.merge(
            TrailerDetails(
                vin=vin,
                gvwr_kg=Decimal("3175.15"),
                length_m=Decimal("6.10"),
                width_m=Decimal("2.44"),
                height_m=Decimal("2.13"),
            )
        )
        await db_session.commit()

        context = await build_garage_context(
            db_session, vin, ctx=RenderContext(units=IMPERIAL_PRESET, show_both=False)
        )
        serialized = json.dumps(context, default=str)

        # The reporter's exact answers, and every other canonical figure seeded.
        for canonical in (
            "135.6",
            "4.73",
            "18.93",
            "16093",
            "24140",
            "241.3",
            "7.94",
            "3175",
            "6.1",
            "2.44",
        ):
            assert canonical not in serialized, canonical

        visit = next(v for v in context["service_visits"] if v["date"] == "2099-12-31")
        reminder = next(r for r in context["reminders"] if r["title"] == "Oil change #237")
        front_left = next(t for t in context["tires"] if t["position"] == "FL")
        assert visit["odometer"] == "10,000 mi"
        assert reminder["due_mileage"] == "15,000 mi"
        assert front_left["pressure"] == "35.0 PSI"
        assert "lb" in context["trailer"]["gvwr"]
        assert "ft" in context["trailer"]["length"]

        # No key may name a canonical unit: a model reads `_nm` as the unit.
        # displacement_l stays: it is the engine's name ("6.7"), not a reading.
        unit_suffix = re.compile(r"_(nm|liters|km|kpa|mm|kg|m)$")

        def keys(node: object) -> list[str]:
            if isinstance(node, dict):
                return [k for k in node] + [k for v in node.values() for k in keys(v)]
            if isinstance(node, list):
                return [k for v in node for k in keys(v)]
            return []

        assert [k for k in keys(context) if unit_suffix.search(k)] == []

    @pytest.mark.asyncio
    async def test_odometer_follows_the_vehicles_own_distance_unit(self, db_session, test_vehicle):
        """A km-odometer import read by an imperial user still reads in km (#172)."""
        import datetime as dt

        from app.constants.units import IMPERIAL_PRESET
        from app.models.service_visit import ServiceVisit
        from app.models.vehicle import Vehicle
        from app.services.garage_context_service import build_garage_context
        from app.utils.render_context import RenderContext

        vin = test_vehicle["vin"]
        vehicle = await db_session.get(Vehicle, vin)
        assert vehicle is not None
        previous = vehicle.distance_unit
        vehicle.distance_unit = "km"
        db_session.add(
            ServiceVisit(vin=vin, date=dt.date(2099, 12, 30), odometer_km=Decimal("16093.44"))
        )
        await db_session.commit()

        try:
            context = await build_garage_context(
                db_session, vin, ctx=RenderContext(units=IMPERIAL_PRESET, show_both=False)
            )
        finally:
            # Shared fixture: a km vehicle leaks into every later test that
            # expects the account's miles (it broke the Telegram fuel tests).
            vehicle.distance_unit = previous
            await db_session.commit()

        visit = next(v for v in context["service_visits"] if v["date"] == "2099-12-30")
        assert visit["odometer"] == "16,093 km"
