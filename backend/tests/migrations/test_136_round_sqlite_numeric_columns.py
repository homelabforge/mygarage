"""Migration 136: SQLite's raw Numeric values rounded to their column's scale.

Rows are written with raw SQL, the way they sat in SQLite before 3.10 rounded
every bind: `text()` has no column type, so nothing rounds them on the way in.
They're read back the same way, so what's checked is what the file holds.
"""

import importlib.util
import logging
import shutil
from collections.abc import Generator
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.types import TypeDecorator

import app.main  # noqa: F401 (registers every model on Base.metadata)
import app.migrations as _m
from app.database import Base
from app.migrations.runner import run_migrations

pytestmark = pytest.mark.migrations

NAME = "136_round_sqlite_numeric_columns"
MIGRATIONS = Path(_m.__file__).parent

#: Model Numeric columns added after 136, as table.column. A new one goes here,
#: never into 136: a historical migration doesn't follow later models (Fable F-2).
ADDED_AFTER_136: frozenset[str] = frozenset()

MILE_KM = Decimal("1.609344")
DAY = date(2026, 9, 1)
VIN = "1HGCM82633A004352"


def _load() -> ModuleType:
    """Load 136 by file, as the runner does."""
    spec = importlib.util.spec_from_file_location(NAME, MIGRATIONS / f"{NAME}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _model_scales() -> dict[str, int]:
    """table.column -> scale, for every Numeric column on Base.metadata."""
    from sqlalchemy import Numeric

    found: dict[str, int] = {}
    for table in Base.metadata.tables.values():
        for column in table.columns:
            kind = column.type
            if isinstance(kind, TypeDecorator):
                kind = kind.impl_instance
            if isinstance(kind, Numeric):
                assert kind.scale is not None, f"{table.name}.{column.name} has no scale"
                found[f"{table.name}.{column.name}"] = kind.scale
    return found


@pytest.fixture
def sqlite_db(tmp_path: Path) -> Generator[tuple[Engine, Path]]:
    """Every model table in a fresh SQLite file, plus one vehicle for the rows to hang off."""
    path = tmp_path / "mygarage.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO vehicles (vin, nickname, vehicle_type, usage_unit, "
                "secondary_usage_enabled) VALUES (:vin, 'Raw', 'Car', 'km', 0)"
            ),
            {"vin": VIN},
        )
    try:
        yield engine, path
    finally:
        engine.dispose()


def _fuel(conn: Any, **values: Any) -> int:
    """A fuel row written raw. Returns its id."""
    row = {"vin": VIN, "date": DAY.isoformat(), "is_full_tank": 1, "missed_fillup": 0}
    row |= {"is_hauling": 0, **values}
    names = ", ".join(row)
    binds = ", ".join(f":{name}" for name in row)
    return conn.execute(
        text(f"INSERT INTO fuel_records ({names}) VALUES ({binds}) RETURNING id"), row
    ).scalar_one()


def _raw(engine: Engine, table: str, column: str, row_id: int, key: str = "id") -> Any:
    with engine.connect() as conn:
        value = conn.execute(
            text(f"SELECT {column} FROM {table} WHERE {key} = :id"), {"id": row_id}
        ).scalar_one()
    return Decimal(repr(value)) if isinstance(value, float) else value


@contextmanager
def _updates(engine: Engine) -> Generator[list[str]]:
    """Every UPDATE the engine runs inside the block."""
    seen: list[str] = []

    def record(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        if statement.lstrip().upper().startswith("UPDATE"):
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


def _count_rewrites(engine: Engine, table: str) -> None:
    """Log every row an UPDATE touches in `table`, changed or not, into `rewrites`."""
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS rewrites (tbl TEXT, row_id INTEGER)"))
        conn.execute(
            text(
                f"CREATE TRIGGER count_{table} AFTER UPDATE ON {table} "
                f"BEGIN INSERT INTO rewrites VALUES ('{table}', old.rowid); END"
            )
        )


def _rewrites(engine: Engine) -> list[tuple[str, int]]:
    with engine.connect() as conn:
        return sorted(
            (row[0], row[1]) for row in conn.execute(text("SELECT tbl, row_id FROM rewrites")).all()
        )


def test_is_not_fatal() -> None:
    # A failure leaves 3.10's behaviour (new writes round, old rows stay raw)
    # and retries next boot, so it mustn't stop the app.
    assert _load().FATAL is False


def test_the_map_is_every_model_numeric_column_at_its_scale() -> None:
    """Guard: passes once 136 exists. Kills a column 136 misses or rounds at the
    wrong scale today, and one a later model adds to 136 instead of to
    ADDED_AFTER_136."""
    listed = {
        f"{table}.{column}": scale
        for table, columns in _load().COLUMNS.items()
        for column, scale in columns.items()
    }
    models = _model_scales()
    # A floor, so a scan that sees no models can't pass as all clear.
    assert len(models) >= 126
    assert ADDED_AFTER_136 <= models.keys(), "ADDED_AFTER_136 names a column no model has"
    assert not ADDED_AFTER_136 & listed.keys(), "a later column went into 136"
    assert listed == {q: s for q, s in models.items() if q not in ADDED_AFTER_136}


def test_raw_rows_round_to_the_column_scale(sqlite_db: tuple[Engine, Path]) -> None:
    engine, _path = sqlite_db
    with engine.begin() as conn:
        record = _fuel(
            conn,
            odometer_km=19868.4361,
            price_per_unit=1.31982,
            # The double nearest 1.005 sits below it; it still rounds as typed.
            cost=1.005,
            outside_temp_c=-1.005,
        )
    assert _raw(engine, "fuel_records", "odometer_km", record) == Decimal("19868.4361")

    _load().upgrade(engine)

    assert _raw(engine, "fuel_records", "odometer_km", record) == Decimal("19868.44")
    # The new scale (13,4), not 122's (12,3).
    assert _raw(engine, "fuel_records", "price_per_unit", record) == Decimal("1.3198")
    assert _raw(engine, "fuel_records", "cost", record) == Decimal("1.01")
    assert _raw(engine, "fuel_records", "outside_temp_c", record) == Decimal("-1.01")


def test_a_table_without_an_integer_key_rounds_too(sqlite_db: tuple[Engine, Path]) -> None:
    # Guard: passes once 136 exists. vehicles is keyed by VIN, so this kills an
    # UPDATE keyed on `id` instead of rowid.
    engine, _path = sqlite_db
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE vehicles SET purchase_price = 20000.005, current_hours = 12.35"),
        )

    _load().upgrade(engine)

    assert _raw(engine, "vehicles", "purchase_price", VIN, key="vin") == Decimal("20000.01")
    assert _raw(engine, "vehicles", "current_hours", VIN, key="vin") == Decimal("12.4")


def test_unchanged_rows_are_not_rewritten(sqlite_db: tuple[Engine, Path]) -> None:
    engine, _path = sqlite_db
    with engine.begin() as conn:
        raw = _fuel(conn, odometer_km=19868.4361)
        at_scale = _fuel(conn, odometer_km=19868.44, liters=40.5)
        whole = _fuel(conn, odometer_km=19869)
        empty = _fuel(conn)
        # Not a number: SQLite keeps unparseable text in a NUMERIC column.
        text_value = _fuel(conn, odometer_km="n/a")
    _count_rewrites(engine, "fuel_records")

    migration = _load()
    migration.upgrade(engine)

    assert _rewrites(engine) == [("fuel_records", raw)]
    assert _raw(engine, "fuel_records", "odometer_km", at_scale) == Decimal("19868.44")
    assert _raw(engine, "fuel_records", "odometer_km", whole) == 19869
    assert _raw(engine, "fuel_records", "odometer_km", empty) is None
    assert _raw(engine, "fuel_records", "odometer_km", text_value) == "n/a"

    # And a rerun has nothing left to write.
    migration.upgrade(engine)
    assert _rewrites(engine) == [("fuel_records", raw)]


def test_rows_past_one_batch_all_round(
    sqlite_db: tuple[Engine, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guard: passes once 136 exists. Kills paging that stops after the first
    batch or skips the row each batch starts after."""
    engine, _path = sqlite_db
    with engine.begin() as conn:
        ids = [_fuel(conn, odometer_km=1000 + n + 0.005) for n in range(7)]
    migration = _load()
    monkeypatch.setattr(migration, "BATCH", 3)

    migration.upgrade(engine)

    assert [_raw(engine, "fuel_records", "odometer_km", i) for i in ids] == [
        Decimal(1000 + n) + Decimal("0.01") for n in range(7)
    ]


@pytest.mark.parametrize("engine_for_migration", ["pg"], indirect=True)
def test_pg_is_a_no_op(engine_for_migration: tuple[str, Engine, str]) -> None:
    """Even a column 135 left alone, unbounded and holding five places, is untouched."""
    _dialect, engine, _url = engine_for_migration
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE fuel_records (id INTEGER PRIMARY KEY, price_per_unit NUMERIC)")
        )
        conn.execute(text("INSERT INTO fuel_records VALUES (1, 1.31982)"))

    with _updates(engine) as statements:
        _load().upgrade(engine)

    assert statements == []
    with engine.connect() as conn:
        assert conn.execute(text("SELECT price_per_unit FROM fuel_records")).scalar_one() == (
            Decimal("1.31982")
        )


def test_a_missing_table_or_column_is_skipped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """An old database without some tables still rounds the ones it has."""
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    try:
        with engine.begin() as conn:
            conn.execute(
                text("CREATE TABLE fuel_records (id INTEGER PRIMARY KEY, cost NUMERIC(8, 2))")
            )
            conn.execute(text("INSERT INTO fuel_records VALUES (1, 1.005)"))

        with caplog.at_level(logging.INFO):
            _load().upgrade(engine)

        assert _raw(engine, "fuel_records", "cost", 1) == Decimal("1.01")
        assert "136: vehicles missing; skip" in caplog.text
        assert "136: fuel_records.price_per_unit missing; skip" in caplog.text
    finally:
        engine.dispose()


def _only_136(tmp_path: Path) -> Path:
    """A migrations folder holding just 136, so the runner runs nothing else."""
    folder = tmp_path / "migrations"
    folder.mkdir()
    shutil.copy(MIGRATIONS / f"{NAME}.py", folder / f"{NAME}.py")
    return folder


def _stamped(engine: Engine) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text("SELECT count(*) FROM schema_migrations WHERE migration_name = :n"),
                {"n": NAME},
            ).scalar_one()
        )


def test_a_failure_keeps_the_tables_done_and_the_next_boot_finishes(
    sqlite_db: tuple[Engine, Path], tmp_path: Path
) -> None:
    """A table per transaction, not FATAL: fuel_records commits, vehicles refuses, then retries."""
    engine, path = sqlite_db
    order = list(_load().COLUMNS)
    assert order.index("fuel_records") < order.index("vehicles")
    with engine.begin() as conn:
        record = _fuel(conn, odometer_km=19868.4361)
        conn.execute(text("UPDATE vehicles SET purchase_price = 20000.005"))
        conn.execute(
            text(
                "CREATE TRIGGER refuse BEFORE UPDATE ON vehicles "
                "BEGIN SELECT RAISE(ABORT, 'vehicles refuses the update'); END"
            )
        )
    folder = _only_136(tmp_path)
    url = f"sqlite:///{path}"

    with pytest.raises(Exception, match="refuses the update") as raised:
        run_migrations(url, folder)

    assert getattr(raised.value, "__migration_fatal__", None) is False
    assert _raw(engine, "fuel_records", "odometer_km", record) == Decimal("19868.44")
    assert _raw(engine, "vehicles", "purchase_price", VIN, key="vin") == Decimal("20000.005")
    assert not _stamped(engine)

    with engine.begin() as conn:
        conn.execute(text("DROP TRIGGER refuse"))
    run_migrations(url, folder)

    assert _raw(engine, "vehicles", "purchase_price", VIN, key="vin") == Decimal("20000.01")
    assert _stamped(engine)


def _km(miles: int) -> float:
    """What the browser posted for an imperial odometer, as SQLite stored it."""
    return float(Decimal(miles) * MILE_KM)


async def _session(path: Path) -> tuple[Any, AsyncSession]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    return engine, async_sessionmaker(engine, expire_on_commit=False)()


async def test_the_economy_window_on_rows_written_before_3_10(
    sqlite_db: tuple[Engine, Path],
) -> None:
    """T6's window case, on the prod shape: the odometers were stored raw before
    ScaledNumeric, so only 136 brings them to what a comparison binds.

    Full 40 L, partial 10 L, full 30 L: 40 L over 572.93 km is 6.98. Raw, the
    previous full tank's 40 L joined the window too.
    """
    from app.models.fuel import FuelRecord
    from app.services.fuel_service import FuelRecordService

    engine, path = sqlite_db
    with engine.begin() as conn:
        ids = [
            _fuel(
                conn,
                date=(DAY + timedelta(days=7 * n)).isoformat(),
                odometer_km=_km(miles),
                liters=litres,
                is_full_tank=int(full),
            )
            for n, (miles, litres, full) in enumerate(
                [(12345, 40, True), (12500, 10, False), (12701, 30, True)]
            )
        ]

    _load().upgrade(engine)

    async_engine, db = await _session(path)
    try:
        record = await db.get(FuelRecord, ids[-1])
        assert record is not None
        assert await FuelRecordService(db)._economy_for(VIN, record) == Decimal("6.98")
    finally:
        await db.close()
        await async_engine.dispose()


async def test_the_widget_keeps_its_anchor_tank_on_rows_written_before_3_10(
    sqlite_db: tuple[Engine, Path],
) -> None:
    """T6's widget case, on the prod shape. Raw, the anchor's 17936.13888 sat
    below the 17936.14 bound and dropped out: 8.28, not 9.67 and 9.32."""
    from app.services.widget_aggregation import WidgetAggregationService

    engine, path = sqlite_db
    miles = [11145, 11445, 11745, 12045, 12345]
    with engine.begin() as conn:
        for n, mi in enumerate(miles):
            _fuel(
                conn,
                date=(DAY + timedelta(days=7 * n)).isoformat(),
                odometer_km=_km(mi),
                liters=60.0 if n == len(miles) - 1 else 40.0,
            )

    _load().upgrade(engine)

    async_engine, db = await _session(path)
    try:
        recent, average = await WidgetAggregationService(db)._consumption_l100km(VIN)
        assert (recent, average) == (Decimal("9.67"), Decimal("9.32"))
    finally:
        await db.close()
        await async_engine.dispose()
