"""Family plumbing for the 3b sections: the list check, the buckets, skip and refusal (task 3)."""

from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.maintenance_rule import MaintenanceRule
from app.models.supply import Supply
from app.models.tire import Tire, TireSet
from tests.integration.routes._json_backup import V9, import_json, post_json

# No asyncio mark: auto mode marks the async tests, and the sync ones would warn.
pytestmark = [pytest.mark.integration]

_FAMILY_LISTS = (
    "tire_sets",
    "tires",
    "brake_axles",
    "brake_jobs",
    "brake_measurements",
    "maintenance_rules",
    "supplies",
)


def _buckets(*names: str) -> dict[str, Any]:
    return {name: {"success": 0, "errors": 0, "skipped": 0} for name in names}


async def _tire_sets(db_session: AsyncSession, vin: str) -> int:
    db_session.expire_all()
    return (
        await db_session.execute(
            select(func.count()).select_from(TireSet).where(TireSet.vin == vin)
        )
    ).scalar_one()


# -- S1: a family list that isn't a list refuses the file -----------------------


@pytest.mark.parametrize("section", _FAMILY_LISTS)
async def test_a_family_section_that_is_not_a_list_refuses_the_file(
    section: str, client: AsyncClient, auth_headers, new_vehicle
):
    vin = await new_vehicle()
    response = await post_json(client, auth_headers, vin, {**V9, section: {"name": "x"}})
    # main: the key isn't read, so the file imports.
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == f"{section} must be a list of records"


# -- S9: every family list has its bucket ---------------------------------------


async def test_every_family_list_has_its_bucket(client: AsyncClient, auth_headers, new_vehicle):
    vin = await new_vehicle()
    data = await import_json(client, auth_headers, vin, dict(V9))
    for name in _FAMILY_LISTS:
        # main: KeyError, there's no such bucket.
        assert data[name] == {
            "success": 0,
            "errors": 0,
            "skipped": 0,
            "success_count": 0,
            "error_count": 0,
            "skipped_count": 0,
        }, name


# -- S3: what counts as already having the family -------------------------------


def test_the_families_and_their_lists():
    from app.routes.import_data._families import JSON_FAMILY_SECTIONS

    assert JSON_FAMILY_SECTIONS == {
        "supplies": ("supplies",),
        "maintenance_rules": ("maintenance_rules",),
        "tires": ("tire_sets", "tires"),
        "brakes": ("brake_axles", "brake_jobs", "brake_measurements"),
    }


async def test_one_empty_tire_set_is_having_tires(db_session: AsyncSession, new_vehicle):
    from app.routes.import_data._families import has_family

    vin = await new_vehicle()
    assert not await has_family(db_session, vin, "tires")
    db_session.add(TireSet(vin=vin, name="Winter"))
    await db_session.commit()
    assert await has_family(db_session, vin, "tires")


async def test_an_inactive_rule_is_having_rules(db_session: AsyncSession, new_vehicle):
    from app.routes.import_data._families import has_family

    vin = await new_vehicle()
    db_session.add(
        MaintenanceRule(vin=vin, title="Old", interval_days=30, source="manual", is_active=False)
    )
    await db_session.commit()
    assert await has_family(db_session, vin, "maintenance_rules")


async def test_only_a_supply_pinned_here_is_having_supplies(db_session: AsyncSession, new_vehicle):
    from app.routes.import_data._families import has_family

    vin = await new_vehicle()
    other = await new_vehicle()
    shared = Supply(name="Shared rag", unit_type="count")
    db_session.add_all([shared, Supply(name="Theirs", unit_type="count", vin=other)])
    await db_session.flush()
    shared_id = shared.id
    await db_session.commit()
    try:
        assert not await has_family(db_session, vin, "supplies")
        db_session.add(Supply(name="Ours", unit_type="count", vin=vin))
        await db_session.commit()
        assert await has_family(db_session, vin, "supplies")
    finally:
        # A shared supply has no vehicle to cascade from, so it goes by hand.
        await db_session.rollback()
        await db_session.execute(delete(Supply).where(Supply.id == shared_id))
        await db_session.commit()


# -- J1, K3, S5: the runner ---------------------------------------------------


def _tires_file() -> dict[str, list[Any]]:
    return {"tire_sets": [{"name": "Summer"}], "tires": [{"brand": "A"}, {"brand": "B"}]}


async def test_a_family_the_vehicle_has_is_skipped_whole_with_one_warning(
    db_session: AsyncSession, new_vehicle
):
    from app.routes.import_data._families import FamilyResult, run_family

    vin = await new_vehicle()
    db_session.add(TireSet(vin=vin, name="Winter"))
    await db_session.commit()
    results = _buckets("tire_sets", "tires")
    errors: list[str] = []
    warnings: list[str] = []

    def parse() -> None:
        raise AssertionError("a skipped family is never parsed")

    async def write(plan: None) -> None:
        raise AssertionError("a skipped family is never written")

    outcome = await run_family(
        db_session, vin, "tires", _tires_file(), results, errors, warnings, parse=parse, write=write
    )
    assert outcome == FamilyResult("skipped", None)
    assert results["tire_sets"] == {"success": 0, "errors": 0, "skipped": 1}
    assert results["tires"] == {"success": 0, "errors": 0, "skipped": 2}
    assert warnings == [
        "Tires: this vehicle already has tires, so the file's tires weren't imported"
    ]
    assert errors == []


async def test_an_empty_family_says_nothing(db_session: AsyncSession, new_vehicle):
    from app.routes.import_data._families import FamilyResult, run_family

    vin = await new_vehicle()
    db_session.add(TireSet(vin=vin, name="Winter"))
    await db_session.commit()
    results = _buckets("tire_sets", "tires")
    warnings: list[str] = []

    async def write(plan: object) -> None:
        raise AssertionError("nothing to write")

    outcome = await run_family(
        db_session,
        vin,
        "tires",
        {"tire_sets": [], "tires": []},
        results,
        [],
        warnings,
        parse=lambda: object(),
        write=write,
    )
    assert outcome == FamilyResult("empty", None)
    assert warnings == []
    assert results == _buckets("tire_sets", "tires")


async def test_a_bad_row_refuses_the_whole_family_before_any_write(
    db_session: AsyncSession, new_vehicle
):
    from app.routes.import_data._common import _RowError
    from app.routes.import_data._families import FamilyResult, run_family

    vin = await new_vehicle()
    results = _buckets("tire_sets", "tires")
    errors: list[str] = []

    def parse() -> None:
        raise _RowError("Tire 1, reading 0: tread_depth_mm is above 30")

    async def write(plan: None) -> None:
        raise AssertionError("a refused family is never written")

    outcome = await run_family(
        db_session, vin, "tires", _tires_file(), results, errors, [], parse=parse, write=write
    )
    assert outcome == FamilyResult("refused", None)
    assert errors == [
        "Tire 1, reading 0: tread_depth_mm is above 30, so the file's tires weren't imported"
    ]
    assert results["tire_sets"] == {"success": 0, "errors": 1, "skipped": 0}
    assert results["tires"] == {"success": 0, "errors": 2, "skipped": 0}


async def test_a_parser_that_crashes_refuses_the_family_not_the_file(
    db_session: AsyncSession, new_vehicle
):
    from app.routes.import_data._families import FamilyResult, run_family

    vin = await new_vehicle()
    results = _buckets("tire_sets", "tires")
    errors: list[str] = []

    def parse() -> None:
        # A parser bug, not a row error: it still mustn't 500 the import.
        raise TypeError("'int' object is not subscriptable")

    async def write(plan: None) -> None:
        raise AssertionError("a refused family is never written")

    outcome = await run_family(
        db_session, vin, "tires", _tires_file(), results, errors, [], parse=parse, write=write
    )
    assert outcome == FamilyResult("refused", None)
    assert errors == ["Tires: could not be imported, so the file's tires weren't imported"]
    assert results["tire_sets"] == {"success": 0, "errors": 1, "skipped": 0}
    assert results["tires"] == {"success": 0, "errors": 2, "skipped": 0}


async def test_a_write_that_fails_halfway_leaves_no_row(db_session: AsyncSession, new_vehicle):
    from app.routes.import_data._families import FamilyResult, run_family

    vin = await new_vehicle()
    results = _buckets("tire_sets", "tires")
    errors: list[str] = []

    async def write(plan: None) -> None:
        db_session.add(TireSet(vin=vin, name="Summer"))
        await db_session.flush()
        # Two tires on one corner: uq_tires_vin_position stops the second.
        db_session.add_all([Tire(vin=vin, position="FL"), Tire(vin=vin, position="FL")])
        await db_session.flush()

    outcome = await run_family(
        db_session,
        vin,
        "tires",
        _tires_file(),
        results,
        errors,
        [],
        parse=lambda: None,
        write=write,
    )
    await db_session.commit()
    assert outcome == FamilyResult("refused", None)
    assert errors == ["Tires: could not be imported, so the file's tires weren't imported"]
    assert results["tires"] == {"success": 0, "errors": 2, "skipped": 0}
    # The set flushed before the failure went back with it.
    assert await _tire_sets(db_session, vin) == 0


async def test_a_written_family_counts_each_top_level_row(db_session: AsyncSession, new_vehicle):
    from app.routes.import_data._families import FamilyResult, run_family

    vin = await new_vehicle()
    results = _buckets("tire_sets", "tires")

    async def write(plan: str) -> None:
        assert plan == "parsed"
        db_session.add(TireSet(vin=vin, name="Summer"))
        await db_session.flush()

    outcome = await run_family(
        db_session,
        vin,
        "tires",
        _tires_file(),
        results,
        [],
        [],
        parse=lambda: "parsed",
        write=write,
    )
    await db_session.commit()
    assert outcome == FamilyResult("written", "parsed")
    assert results["tire_sets"] == {"success": 1, "errors": 0, "skipped": 0}
    assert results["tires"] == {"success": 2, "errors": 0, "skipped": 0}
    assert await _tire_sets(db_session, vin) == 1


# -- R6: in-file indices and nested lists ---------------------------------------


@pytest.mark.parametrize("raw", [True, False, -1, 3, "0", 1.0])
def test_an_index_must_be_an_int_in_range(raw: object):
    from app.routes.import_data._common import _RowError
    from app.routes.import_data._families import file_index

    with pytest.raises(_RowError) as caught:
        file_index({"set_index": raw}, "set_index", 3, what="a tire set in this file")
    assert caught.value.reason == "set_index must be the index of a tire set in this file"


def test_an_index_reads_none_when_absent_or_null():
    from app.routes.import_data._common import _RowError
    from app.routes.import_data._families import file_index

    assert file_index({}, "set_index", 3, what="a tire set in this file") is None
    assert file_index({"set_index": None}, "set_index", 3, what="a tire set in this file") is None
    assert file_index({"set_index": 2}, "set_index", 3, what="a tire set in this file") == 2
    # Nothing to point at: any index is out of range.
    with pytest.raises(_RowError):
        file_index({"set_index": 0}, "set_index", 0, what="a tire set in this file")


def test_a_nested_list_reads_absent_as_empty_and_refuses_anything_else():
    from app.routes.import_data._common import _RowError
    from app.routes.import_data._families import nested_list

    assert nested_list({}, "readings") == []
    assert nested_list({"readings": None}, "readings") == []
    assert nested_list({"readings": [{"x": 1}]}, "readings") == [{"x": 1}]
    with pytest.raises(_RowError) as caught:
        nested_list({"readings": {"x": 1}}, "readings")
    assert caught.value.reason == "readings must be a list"


# -- S4: bounds that sit on an Annotated figure ---------------------------------


def test_a_figure_type_bounds_are_checked():
    from app.routes.import_data._common import _RowError
    from app.routes.import_data._families import within_figure_bounds
    from app.schemas.brake import Thickness
    from app.schemas.tire import HoursFigure

    # _within_api_bounds sees no bounds on `HoursFigure | None`: they live on the alias.
    with pytest.raises(_RowError) as caught:
        within_figure_bounds(HoursFigure, engine_hours=Decimal("1000000000"))
    assert caught.value.reason == "engine_hours must be at most 999999999.9, not 1000000000"
    with pytest.raises(_RowError) as caught:
        within_figure_bounds(Thickness, inner_pad_mm=Decimal("-1"))
    assert caught.value.reason == "inner_pad_mm must be at least 0, not -1"
    # A bare NaN in the file is a row error too, not an InvalidOperation 500.
    with pytest.raises(_RowError) as caught:
        within_figure_bounds(Thickness, inner_pad_mm=Decimal("NaN"))
    assert caught.value.reason == "inner_pad_mm must be a number"
    within_figure_bounds(Thickness, inner_pad_mm=Decimal("50"), outer_pad_mm=None)
    # The field's type, not the alias: its bounds are out of reach, so it mustn't check nothing.
    with pytest.raises(TypeError):
        within_figure_bounds(HoursFigure | None, engine_hours=Decimal("1"))


def test_a_borrowed_field_bound_names_the_files_key():
    from app.routes.import_data._common import (
        _RowError,
        _within_api_bounds,
        _within_field_bounds,
    )
    from app.schemas.maintenance import AnchorSpec
    from app.schemas.reminder import ReminderCreate

    # The bound is AnchorSpec.odometer_km's; the reason names the file's column.
    with pytest.raises(_RowError) as caught:
        _within_field_bounds(AnchorSpec, "odometer_km", start_odometer_km=Decimal("-1"))
    assert caught.value.reason == "start_odometer_km must be at least 0, not -1"
    _within_field_bounds(AnchorSpec, "odometer_km", anchor_odometer_km=None)
    # A field with no bounds would check nothing, so it's a bug, not a pass.
    with pytest.raises(TypeError):
        _within_field_bounds(ReminderCreate, "notes", notes=None)
    with pytest.raises(TypeError):
        _within_api_bounds(ReminderCreate, notes="x")


# -- D-9: one boolean reader for every 3b section --------------------------------


def test_a_bool_reads_true_false_or_its_default():
    from app.routes.import_data._common import _json_bool

    assert _json_bool({}, "is_active", default=True) is True
    assert _json_bool({"is_active": None}, "is_active", default=False) is False
    assert _json_bool({"is_active": False}, "is_active", default=True) is False
    assert _json_bool({"is_active": True}, "is_active", default=False) is True


@pytest.mark.parametrize("raw", ["yes", "true", 1, 0])
def test_a_bool_refuses_anything_but_true_or_false(raw: object):
    from app.routes.import_data._common import _json_bool, _RowError

    # 1 and 0 too: a JSON backup writes true and false.
    with pytest.raises(_RowError) as caught:
        _json_bool({"is_active": raw}, "is_active", default=True)
    assert caught.value.reason == "is_active must be true or false"
