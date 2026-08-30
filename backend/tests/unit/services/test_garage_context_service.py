"""Unit tests for Ask My Garage DTC code extraction."""

from decimal import Decimal

import pytest

from app.services.garage_context_service import extract_dtc_codes


def test_extract_dtc_codes_normalizes_and_dedupes():
    assert extract_dtc_codes("What does p0420 and B0001 mean?") == ["P0420", "B0001"]
    assert extract_dtc_codes("P0420 then p0420 again") == ["P0420"]


def test_extract_dtc_codes_ignores_non_codes():
    assert extract_dtc_codes("no codes here") == []
    assert extract_dtc_codes("") == []
    assert extract_dtc_codes("P42 is too short") == []


class TestMaintenanceSpecDisplayUnits:
    """The assistant quotes a rendered string, so the render must follow units.

    The prompt used to say "Nm for lug torque, liters for oil capacity", which
    is a unit named in the prompt rather than resolved from the reader. No
    frontend adapter can reach a unit already baked into model output, so this
    is the only place the behaviour can be pinned.
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

        imp = imperial["maintenance_specs"]["display"]
        met = metric["maintenance_specs"]["display"]

        # The whole point: the same canonical row reads differently per reader.
        assert imp["lug_nut_torque"] != met["lug_nut_torque"]
        assert "lb-ft" in imp["lug_nut_torque"]
        assert "Nm" in met["lug_nut_torque"]
        assert "gal" in imp["oil_capacity"]
        assert "L" in met["oil_capacity"]

        # Canonical values stay untouched beside the rendered ones.
        assert float(imperial["maintenance_specs"]["oil_capacity_liters"]) == 4.7
        assert float(imperial["maintenance_specs"]["lug_nut_torque_nm"]) == 135.0

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
        display = context["maintenance_specs"]["display"]

        assert "L" in display["oil_capacity"]
        assert "gal" not in display["oil_capacity"]
        assert "lb-ft" in display["lug_nut_torque"]
        assert "Nm" not in display["lug_nut_torque"]
