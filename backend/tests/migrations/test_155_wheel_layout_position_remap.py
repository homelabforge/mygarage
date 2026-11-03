"""Migration 155: existing two-wheelers move onto F/R, none-types with data pin four (#272).

Built on the real model schema, parameterised over SQLite and PostgreSQL via
`engine_for_migration`. An axle remaps only when its family used exactly one
code for it (D3); a Boat or Generator that already has tire or brake rows gets
`wheel_layout='four'` so its tabs don't vanish on upgrade (D6).
"""

import importlib
import importlib.util
import inspect as python_inspect
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine, MetaData, create_engine, inspect, text
from sqlalchemy.orm import Session

import app.migrations as _m
from app.migrations.runner import MigrationRunner
from app.models.brake import BrakeAxle, BrakeJob, BrakeMeasurement, BrakeReminderMark
from app.models.reminder import Reminder
from app.models.tire import Tire, TireMountPeriod, TireReading
from app.models.vehicle import Vehicle

pytestmark = pytest.mark.migrations

_NAME = "155_wheel_layout_position_remap"
_BIKE = "B1KEMIG1550000001"
_CAR = "CARMIG15500000001"
_BOAT = "B0ATMIG1550000001"
_GEN = "GENMIG15500000001"


def _load():
    """Load the migration module by file, as the runner does."""
    path = Path(_m.__file__).parent / f"{_NAME}.py"
    spec = importlib.util.spec_from_file_location(_NAME, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _metadata() -> MetaData:
    """Every model registered, so create_all builds the whole schema the FKs need."""
    import app.models as models_pkg

    for py in sorted(Path(models_pkg.__file__).parent.glob("*.py")):
        if py.stem != "__init__":
            importlib.import_module(f"app.models.{py.stem}")
    from app.database import Base

    return Base.metadata


def _upgrade(engine: Engine) -> None:
    """Run it the way the runner does: on one connection, in one transaction."""
    with engine.begin() as conn:
        _load().upgrade(conn=conn)


def _vehicle(s: Session, vin: str, vehicle_type: str, layout: str | None = None) -> None:
    s.add(Vehicle(vin=vin, nickname=vin[:6], vehicle_type=vehicle_type, wheel_layout=layout))
    s.flush()


def _tire(s: Session, vin: str, position: str | None) -> Tire:
    tire = Tire(vin=vin, position=position)
    s.add(tire)
    s.flush()
    return tire


def _period(s: Session, tire: Tire, position: str, *, closed: bool = False) -> None:
    s.add(
        TireMountPeriod(
            tire_id=tire.id,
            position=position,
            is_assumed=False,
            mounted_on=date(2025, 1, 1) if closed else date(2026, 1, 1),
            dismounted_on=date(2025, 12, 31) if closed else None,
        )
    )
    s.flush()


def _reading(s: Session, tire: Tire, position: str) -> None:
    s.add(
        TireReading(tire_id=tire.id, vin=tire.vin, position=position, recorded_at=date(2026, 2, 1))
    )
    s.flush()


def _measurement(s: Session, vin: str, position: str) -> None:
    s.add(BrakeMeasurement(vin=vin, position=position, recorded_at=date(2026, 2, 1)))
    s.flush()


def _job(s: Session, vin: str, position: str) -> None:
    s.add(BrakeJob(vin=vin, position=position, brake_type="disc", performed_on=date(2026, 2, 1)))
    s.flush()


def _reminder(s: Session, tire: Tire, title: str, status: str = "pending") -> int:
    row = Reminder(
        vin=tire.vin,
        title=title,
        reminder_type="date",
        due_date=date(2026, 12, 1),
        source="low_tread",
        tire_id=tire.id,
        status=status,
    )
    s.add(row)
    s.flush()
    return row.id


def _positions(engine: Engine, table: str, vin: str) -> list[str | None]:
    """Every stored position for the vin in one table, sorted (NULLs as '')."""
    if table == "tire_mount_periods":
        sql = (
            "SELECT p.position FROM tire_mount_periods p"
            " JOIN tires t ON t.id = p.tire_id WHERE t.vin = :vin"
        )
    else:
        sql = f"SELECT position FROM {table} WHERE vin = :vin"
    with engine.connect() as conn:
        return sorted((r[0] or "") for r in conn.execute(text(sql), {"vin": vin}))


def _layout(engine: Engine, vin: str) -> str | None:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT wheel_layout FROM vehicles WHERE vin = :vin"), {"vin": vin}
        ).scalar_one()


def _titles(engine: Engine) -> dict[int, str]:
    with engine.connect() as conn:
        return dict(conn.execute(text("SELECT id, title FROM vehicle_reminders")).all())


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_unambiguous_bike_remaps(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _metadata().create_all(engine)
    with Session(engine) as s:
        _vehicle(s, _BIKE, "Motorcycle")
        front = _tire(s, _BIKE, "FL")
        _period(s, front, "FL", closed=True)
        _period(s, front, "FL")
        _reading(s, front, "FL")
        rear = _tire(s, _BIKE, "RR")
        _period(s, rear, "RR")
        _reading(s, rear, "RR")
        _measurement(s, _BIKE, "FL")
        s.commit()

    _upgrade(engine)

    # main: FileNotFoundError, no migration 155
    assert _positions(engine, "tires", _BIKE) == ["F", "R"]
    assert _positions(engine, "tire_mount_periods", _BIKE) == ["F", "F", "R"]
    assert _positions(engine, "tire_readings", _BIKE) == ["F", "R"]
    assert _positions(engine, "brake_measurements", _BIKE) == ["F"]
    # A bike isn't pinned: NULL already reads as `two`.
    assert _layout(engine, _BIKE) is None


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_ambiguous_axle_left_alone(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _metadata().create_all(engine)
    with Session(engine) as s:
        _vehicle(s, _BIKE, "Motorcycle")
        _tire(s, _BIKE, "FL")
        _tire(s, _BIKE, "FR")
        rear = _tire(s, _BIKE, "RL")
        _reading(s, rear, "RL")
        s.commit()

    _upgrade(engine)

    # The front used two codes, so it stays; the rear used one, so it moves.
    assert _positions(engine, "tires", _BIKE) == ["FL", "FR", "R"]
    assert _positions(engine, "tire_readings", _BIKE) == ["R"]


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_codes_count_across_the_whole_family(engine_for_migration):
    # guard: kills a per-table decision. The tire sits at FL today but an old
    # stint had it at FR, so the front axle used two codes across the family.
    _dialect, engine, _url = engine_for_migration
    _metadata().create_all(engine)
    with Session(engine) as s:
        _vehicle(s, _BIKE, "Motorcycle")
        tire = _tire(s, _BIKE, "FL")
        _period(s, tire, "FR", closed=True)
        _period(s, tire, "FL")
        s.commit()

    _upgrade(engine)

    assert _positions(engine, "tires", _BIKE) == ["FL"]
    assert _positions(engine, "tire_mount_periods", _BIKE) == ["FL", "FR"]


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_families_independent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _metadata().create_all(engine)
    with Session(engine) as s:
        _vehicle(s, _BIKE, "Motorcycle")
        _tire(s, _BIKE, "FL")
        _job(s, _BIKE, "FL")
        _job(s, _BIKE, "FR")
        _measurement(s, _BIKE, "FR")
        s.add(BrakeReminderMark(vin=_BIKE, position="RR", seen_through_id=1))
        s.commit()

    _upgrade(engine)

    assert _positions(engine, "tires", _BIKE) == ["F"]
    assert _positions(engine, "brake_jobs", _BIKE) == ["FL", "FR"]
    assert _positions(engine, "brake_measurements", _BIKE) == ["FR"]
    # The brake rear used one code, so it still moves.
    assert _positions(engine, "brake_reminder_marks", _BIKE) == ["R"]


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_car_untouched(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _metadata().create_all(engine)
    with Session(engine) as s:
        _vehicle(s, _CAR, "Car")
        _tire(s, _CAR, "FL")
        _measurement(s, _CAR, "RR")
        s.commit()

    _upgrade(engine)

    assert _positions(engine, "tires", _CAR) == ["FL"]
    assert _positions(engine, "brake_measurements", _CAR) == ["RR"]
    assert _layout(engine, _CAR) is None


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_override_untouched(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _metadata().create_all(engine)
    with Session(engine) as s:
        _vehicle(s, _BIKE, "Motorcycle", layout="four")
        _tire(s, _BIKE, "FL")
        _measurement(s, _BIKE, "RR")
        s.commit()

    _upgrade(engine)

    assert _positions(engine, "tires", _BIKE) == ["FL"]
    assert _positions(engine, "brake_measurements", _BIKE) == ["RR"]
    assert _layout(engine, _BIKE) == "four"


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_none_type_with_tires_pinned_four(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _metadata().create_all(engine)
    with Session(engine) as s:
        _vehicle(s, _BOAT, "Boat")
        _tire(s, _BOAT, "FL")
        _vehicle(s, _GEN, "Generator")
        _measurement(s, _GEN, "FL")
        # Brake setup alone counts too: it's what the Brakes tab shows.
        _vehicle(s, "SNOWMIG1550000001", "Snowmobile")
        s.add(
            BrakeAxle(
                vin="SNOWMIG1550000001",
                axle="front",
                brake_type="disc",
                min_thickness_mm=2,
                new_thickness_mm=10,
            )
        )
        _vehicle(s, "SMALLMIG155000001", "SmallEngine")
        _job(s, "SMALLMIG155000001", "FL")
        _vehicle(s, "B0ATMIG1550000002", "Boat")
        s.add(BrakeReminderMark(vin="B0ATMIG1550000002", position="FL", seen_through_id=1))
        # Someone already picked `none` on purpose: that stays.
        _vehicle(s, "ATTMIG15500000001", "Attachment", layout="none")
        _tire(s, "ATTMIG15500000001", "FL")
        s.commit()

    _upgrade(engine)

    assert _layout(engine, _BOAT) == "four"
    assert _layout(engine, _GEN) == "four"
    assert _layout(engine, "SNOWMIG1550000001") == "four"
    assert _layout(engine, "SMALLMIG155000001") == "four"
    assert _layout(engine, "B0ATMIG1550000002") == "four"
    assert _layout(engine, "ATTMIG15500000001") == "none"
    # Pinned four, so FL means the front-left again: no remap.
    assert _positions(engine, "tires", _BOAT) == ["FL"]


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_none_type_without_data_stays_null(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _metadata().create_all(engine)
    with Session(engine) as s:
        _vehicle(s, _BOAT, "Boat")
        _vehicle(s, "SMALLMIG155000001", "SmallEngine")
        # Another vehicle's tire mustn't leak into the boat's check.
        _vehicle(s, _CAR, "Car")
        _tire(s, _CAR, "FL")
        s.commit()

    _upgrade(engine)

    assert _layout(engine, _BOAT) is None
    assert _layout(engine, "SMALLMIG155000001") is None
    assert _layout(engine, _CAR) is None


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_spare_on_bike_left(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _metadata().create_all(engine)
    with Session(engine) as s:
        _vehicle(s, _BIKE, "Bicycle")
        _tire(s, _BIKE, "FL")
        spare = _tire(s, _BIKE, "SPARE")
        _reading(s, spare, "SPARE")
        s.commit()

    _upgrade(engine)

    assert _positions(engine, "tires", _BIKE) == ["F", "SPARE"]
    assert _positions(engine, "tire_readings", _BIKE) == ["SPARE"]


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_a_target_code_already_there_makes_the_axle_ambiguous(engine_for_migration):
    # guard: an F row next to an FL one would collide on uq_tires_vin_position
    # if FL moved, which would fail the FATAL migration and stop the boot.
    _dialect, engine, _url = engine_for_migration
    _metadata().create_all(engine)
    with Session(engine) as s:
        _vehicle(s, _BIKE, "EBike")
        _tire(s, _BIKE, "FL")
        _tire(s, _BIKE, "F")
        s.add(BrakeReminderMark(vin=_BIKE, position="R", seen_through_id=1))
        s.add(BrakeReminderMark(vin=_BIKE, position="RL", seen_through_id=1))
        s.commit()

    _upgrade(engine)

    assert _positions(engine, "tires", _BIKE) == ["F", "FL"]
    assert _positions(engine, "brake_reminder_marks", _BIKE) == ["R", "RL"]


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_low_tread_title_follows(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _metadata().create_all(engine)
    with Session(engine) as s:
        _vehicle(s, _BIKE, "Motorcycle")
        front = _tire(s, _BIKE, "FL")
        rear = _tire(s, _BIKE, "RR")
        pending_front = _reminder(s, front, "Tire tread low (FL)")
        done_front = _reminder(s, front, "Tire tread low (FL)", status="done")
        pending_rear = _reminder(s, rear, "Tire tread low (RR)")
        # A car's identical title is none of 155's business.
        _vehicle(s, _CAR, "Car")
        car_tire = _tire(s, _CAR, "FL")
        car = _reminder(s, car_tire, "Tire tread low (FL)")
        s.commit()

    _upgrade(engine)

    titles = _titles(engine)
    assert titles[pending_front] == "Tire tread low (F)"
    assert titles[pending_rear] == "Tire tread low (R)"
    assert titles[done_front] == "Tire tread low (FL)"
    assert titles[car] == "Tire tread low (FL)"


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_a_second_run_changes_nothing(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _metadata().create_all(engine)
    with Session(engine) as s:
        _vehicle(s, _BIKE, "Motorcycle")
        _tire(s, _BIKE, "FL")
        _vehicle(s, _BOAT, "Boat")
        _tire(s, _BOAT, "FL")
        s.commit()
    _upgrade(engine)

    _upgrade(engine)

    assert _positions(engine, "tires", _BIKE) == ["F"]
    assert _positions(engine, "tires", _BOAT) == ["FL"]
    assert _layout(engine, _BOAT) == "four"


def test_a_missing_table_is_skipped() -> None:
    engine = create_engine("sqlite://")
    try:
        _upgrade(engine)
        assert inspect(engine).get_table_names() == []
    finally:
        engine.dispose()


def test_is_fatal_and_takes_conn() -> None:
    mod = _load()
    assert mod.FATAL is True
    assert list(python_inspect.signature(mod.upgrade).parameters) == ["conn"]


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_is_fatal_and_atomic(engine_for_migration, monkeypatch: pytest.MonkeyPatch):
    # A remap that blows up after the pin rolls the pin back too, 155 stays
    # unstamped, and the failure stops the boot.
    _dialect, engine, url = engine_for_migration
    _metadata().create_all(engine)
    with Session(engine) as s:
        _vehicle(s, _BOAT, "Boat")
        _tire(s, _BOAT, "FL")
        _vehicle(s, _BIKE, "Motorcycle")
        _tire(s, _BIKE, "FL")
        s.commit()

    migrations_dir = Path(_m.__file__).parent
    runner = MigrationRunner(url, migrations_dir)
    try:
        runner._ensure_migration_tracking_table()
        with runner.engine.begin() as conn:
            runner._insert_stamps(
                conn, [n for n, _p in runner._discover_migrations() if n != _NAME]
            )

        seen: list[tuple[str | None, str | None]] = []
        real_load = MigrationRunner._load_module

        def loading(self, name, path):
            mod = real_load(self, name, path)
            if name == _NAME:
                real_remap = mod._remap_vehicle

                def remap_then_boom(conn, vin, *args, **kwargs):
                    real_remap(conn, vin, *args, **kwargs)
                    seen.append(
                        (
                            conn.execute(
                                text("SELECT wheel_layout FROM vehicles WHERE vin = :v"),
                                {"v": _BOAT},
                            ).scalar_one(),
                            conn.execute(
                                text("SELECT position FROM tires WHERE vin = :v"), {"v": vin}
                            ).scalar_one(),
                        )
                    )
                    raise RuntimeError("injected after the pin")

                mod._remap_vehicle = remap_then_boom
            return mod

        monkeypatch.setattr(MigrationRunner, "_load_module", loading)

        with pytest.raises(RuntimeError, match="injected after the pin") as exc:
            runner.run_pending_migrations()

        # The pin and the remap both happened inside the transaction...
        assert seen == [("four", "F")]
        assert getattr(exc.value, "__migration_fatal__", False) is True
        with runner.engine.connect() as conn:
            stamped = set(
                conn.execute(text("SELECT migration_name FROM schema_migrations")).scalars()
            )
    finally:
        runner.engine.dispose()

    # ...and both rolled back with the missing stamp.
    assert _NAME not in stamped
    assert _layout(engine, _BOAT) is None
    assert _positions(engine, "tires", _BIKE) == ["FL"]
    assert _positions(engine, "tires", _BOAT) == ["FL"]
