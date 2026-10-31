"""Migration 140: one live low-tread reminder per tire, and readings lose their period (G3a-17, D2).

Built on the real model schema. A "migrated" database is create_all with the
index dropped, the shape 140 upgrades; a "create_all" one keeps the model's
index. The parity test only compares an index's columns and uniqueness, so the
WHERE is checked here by what each one refuses and lets through (F2-5).
"""

import importlib
import importlib.util
import logging
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine, MetaData, create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

import app.migrations as _m
from app.migrations.runner import MigrationRunner
from app.models.maintenance_rule import MaintenanceRule
from app.models.reminder import Reminder
from app.models.tire import Tire, TireMountPeriod, TireReading
from app.models.vehicle import Vehicle

pytestmark = pytest.mark.migrations

_NAME = "140_tire_reminder_index_and_reading_period"
_INDEX = "uq_reminder_source_tire_live"
_VIN = "B9MIG140000000001"


def _load(name: str = _NAME):
    """Load a migration module by file, as the runner does."""
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
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


def _build(engine: Engine, kind: str) -> None:
    """The model schema, as 140 finds it ("pre"), after 140 ("migrated"), or fresh ("create_all")."""
    _metadata().create_all(engine)
    if kind == "create_all":
        return
    with engine.begin() as conn:
        conn.execute(text(f"DROP INDEX IF EXISTS {_INDEX}"))
    if kind == "migrated":
        _load().upgrade(engine)


def _parents(engine: Engine) -> dict[str, int]:
    """A vehicle with two tires, a mount period and two rules."""
    with Session(engine) as s:
        s.add(Vehicle(vin=_VIN, nickname="140", vehicle_type="Car"))
        s.flush()
        a, b = Tire(vin=_VIN, position="FL"), Tire(vin=_VIN, position="FR")
        oil = MaintenanceRule(vin=_VIN, title="Oil", source="manual", interval_months=6)
        air = MaintenanceRule(vin=_VIN, title="Air filter", source="manual", interval_months=12)
        s.add_all([a, b, oil, air])
        s.flush()
        period = TireMountPeriod(tire_id=a.id, position="FL", is_assumed=False)
        s.add(period)
        s.flush()
        ids = {"a": a.id, "b": b.id, "oil": oil.id, "air": air.id, "period": period.id}
        s.commit()
    return ids


def _remind(
    engine: Engine,
    *,
    source: str | None = None,
    tire_id: int | None = None,
    rule_id: int | None = None,
    status: str = "pending",
) -> int:
    with Session(engine) as s:
        row = Reminder(
            vin=_VIN,
            title="r",
            reminder_type="date",
            due_date=date(2026, 12, 1),
            source=source,
            tire_id=tire_id,
            rule_id=rule_id,
            status=status,
        )
        s.add(row)
        s.commit()
        return row.id


def _statuses(engine: Engine) -> dict[int, str]:
    with engine.connect() as conn:
        return dict(conn.execute(text("SELECT id, status FROM vehicle_reminders")).all())


def _indexes(engine: Engine) -> set[str]:
    return {ix["name"] for ix in inspect(engine).get_indexes("vehicle_reminders")}


def _bystanders(engine: Engine, ids: dict[str, int]) -> list[int]:
    """Pending rows outside the index predicate: manual, rule and partly-NULL identity, two of each."""
    return [
        _remind(engine),
        _remind(engine),
        _remind(engine, rule_id=ids["oil"]),
        _remind(engine, rule_id=ids["air"]),
        _remind(engine, source="low_tread"),
        _remind(engine, source="low_tread"),
        _remind(engine, tire_id=ids["a"]),
        _remind(engine, tire_id=ids["a"]),
    ]


def test_the_migration_is_not_fatal():
    # guard: passes once the file exists. It kills a 140 marked FATAL; a failed
    # 140 raises and retries next boot, and the app runs fine meanwhile.
    assert not getattr(_load(), "FATAL", False)


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_duplicates_collapse_to_the_lowest_id_and_the_index_lands(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _build(engine, "pre")
    ids = _parents(engine)
    first, second, third = (_remind(engine, source="low_tread", tire_id=ids["a"]) for _ in "abc")
    closed = _remind(engine, source="low_tread", tire_id=ids["a"], status="dismissed")
    lone = _remind(engine, source="low_tread", tire_id=ids["b"])
    bystanders = _bystanders(engine, ids)

    _load().upgrade(engine)

    # main: FileNotFoundError, no migration 140
    assert _statuses(engine) == {
        first: "pending",
        second: "done",
        third: "done",
        closed: "dismissed",
        lone: "pending",
        **dict.fromkeys(bystanders, "pending"),
    }
    assert _INDEX in _indexes(engine)


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_readings_lose_their_mount_period(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _build(engine, "pre")
    ids = _parents(engine)
    with Session(engine) as s:
        s.add_all(
            [
                TireReading(
                    tire_id=ids["a"],
                    vin=_VIN,
                    recorded_at=date(2026, 1, day),
                    tread_depth_mm=7,
                    mount_period_id=period,
                )
                for day, period in ((1, ids["period"]), (2, None))
            ]
        )
        s.commit()

    _load().upgrade(engine)

    with engine.connect() as conn:
        periods = conn.execute(text("SELECT mount_period_id FROM tire_readings")).scalars().all()
    # main: FileNotFoundError, no migration 140
    assert periods == [None, None]


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_a_second_run_changes_nothing(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _build(engine, "pre")
    ids = _parents(engine)
    for _ in range(2):
        _remind(engine, source="low_tread", tire_id=ids["a"])
    _bystanders(engine, ids)
    mod = _load()
    mod.upgrade(engine)
    before = (_statuses(engine), _indexes(engine))

    mod.upgrade(engine)

    assert (_statuses(engine), _indexes(engine)) == before


@pytest.mark.parametrize("build", ["migrated", "create_all"])
@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_the_index_refuses_a_second_live_reminder_for_a_tire(engine_for_migration, build):
    _dialect, engine, _url = engine_for_migration
    _build(engine, build)
    ids = _parents(engine)
    _remind(engine, source="low_tread", tire_id=ids["a"])

    # main: the create_all build takes the second row, and the migrated one has no 140
    with pytest.raises(IntegrityError):
        _remind(engine, source="low_tread", tire_id=ids["a"])


@pytest.mark.parametrize("build", ["migrated", "create_all"])
@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_the_index_leaves_closed_and_unowned_reminders_alone(engine_for_migration, build):
    # guard on the create_all build, where main has no index to refuse anything;
    # it kills a WHERE that's too wide.
    _dialect, engine, _url = engine_for_migration
    _build(engine, build)
    ids = _parents(engine)
    _remind(engine, source="low_tread", tire_id=ids["a"])
    _remind(engine, source="low_tread", tire_id=ids["a"], status="done")
    _remind(engine, source="low_tread", tire_id=ids["a"], status="dismissed")
    _remind(engine, source="low_tread", tire_id=ids["b"])
    bystanders = _bystanders(engine, ids)

    with Session(engine) as s:
        pending = s.scalars(select(Reminder.id).where(Reminder.status == "pending")).all()
    assert set(bystanders) <= set(pending)
    assert len(pending) == len(bystanders) + 2


def test_missing_table_or_columns_are_skipped(caplog: pytest.LogCaptureFixture) -> None:
    """Skipped on purpose, not caught by the error log: without the checks the UPDATEs fail."""
    caplog.set_level(logging.INFO)
    engine = create_engine("sqlite://")
    _load().upgrade(engine)
    assert "140: vehicle_reminders missing" in caplog.text
    assert "140: tire_readings missing" in caplog.text

    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE vehicle_reminders (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE tire_readings (id INTEGER PRIMARY KEY)"))
    _load().upgrade(engine)
    assert "140: vehicle_reminders.source, tire_id or status missing" in caplog.text
    assert "140: tire_readings.mount_period_id missing" in caplog.text
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_a_failed_dedupe_raises_after_the_periods_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    """The dedupe's failure reaches the runner, so 140 isn't stamped (F-1). The clear still ran."""
    mod = _load()
    cleared: list[Engine] = []

    def boom(_engine: Engine) -> None:
        raise OperationalError("UPDATE vehicle_reminders", {}, Exception("database is locked"))

    monkeypatch.setattr(mod, "_dedupe_and_index", boom)
    monkeypatch.setattr(mod, "_clear_reading_periods", cleared.append)
    with pytest.raises(OperationalError):
        mod.upgrade(create_engine("sqlite://"))
    assert len(cleared) == 1


def test_a_failed_clear_is_logged_not_raised(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # guard: the clear's catch is unchanged. A failure there leaves old period
    # ids behind, and nothing reads them, so it isn't worth a retry.
    mod = _load()
    deduped: list[Engine] = []

    def boom(_engine: Engine) -> None:
        raise OperationalError("UPDATE tire_readings", {}, Exception("database is locked"))

    monkeypatch.setattr(mod, "_clear_reading_periods", boom)
    monkeypatch.setattr(mod, "_dedupe_and_index", deduped.append)
    mod.upgrade(create_engine("sqlite://"))
    assert "140: reading mount periods not cleared" in caplog.text
    assert len(deduped) == 1


def _stamp_all_but_140(runner: MigrationRunner, engine: Engine) -> None:
    runner._ensure_migration_tracking_table()
    with engine.begin() as conn:
        for stem, _path in runner._discover_migrations():
            if stem != _NAME:
                conn.execute(
                    text("INSERT INTO schema_migrations (migration_name) VALUES (:n)"),
                    {"n": stem},
                )


def _stamped(engine: Engine) -> bool:
    with engine.connect() as conn:
        names = conn.execute(text("SELECT migration_name FROM schema_migrations")).scalars()
        return _NAME in set(names)


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_a_failed_140_is_left_unstamped_and_the_next_boot_applies_it(engine_for_migration):
    """Through the runner, which loads its own copy, so the failure comes from the
    database: another table already holds an index by the name 140 builds."""
    _dialect, engine, url = engine_for_migration
    _build(engine, "pre")
    ids = _parents(engine)
    keeper, extra = (_remind(engine, source="low_tread", tire_id=ids["a"]) for _ in "ab")
    with engine.begin() as conn:
        conn.execute(text(f"CREATE INDEX {_INDEX} ON tire_readings (recorded_at)"))
    runner = MigrationRunner(url, Path(_m.__file__).parent)
    _stamp_all_but_140(runner, engine)

    try:
        with pytest.raises(Exception) as failed:
            runner.run_pending_migrations()
    finally:
        runner.engine.dispose()

    # main: 140 swallowed the error, so the runner stamped it and nothing retries
    assert getattr(failed.value, "__migration_fatal__", None) is False
    assert not _stamped(engine)
    assert _statuses(engine) == {keeper: "pending", extra: "pending"}

    with engine.begin() as conn:
        conn.execute(text(f"DROP INDEX {_INDEX}"))
    runner = MigrationRunner(url, Path(_m.__file__).parent)
    try:
        runner.run_pending_migrations()
    finally:
        runner.engine.dispose()

    assert _stamped(engine)
    assert _statuses(engine) == {keeper: "pending", extra: "done"}
    assert _INDEX in _indexes(engine)
