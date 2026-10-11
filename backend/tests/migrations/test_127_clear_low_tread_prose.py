"""Migration 127: clear the low-tread sync's old prose (G3a-21). Exact matches only."""

import importlib.util
from pathlib import Path

from sqlalchemy import text

import app.migrations as _m

_NAME = "127_clear_low_tread_prose"


def _load():
    path = Path(_m.__file__).parent / f"{_NAME}.py"
    spec = importlib.util.spec_from_file_location(_NAME, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ROWS = [
    (1, "low_tread", "Tread 1.5 mm ≤ threshold 2.0 mm. ~0 km remaining."),
    (2, "low_tread", "Tread 1.80 mm ≤ threshold 2.00 mm."),
    (3, "low_tread", "Tread 1.5 mm ≤ threshold 2.0 mm. Rotated in spring."),
    (4, None, "Tread 1.5 mm ≤ threshold 2.0 mm."),
    (5, "low_tread", "Check the spare too."),
    (6, "low_tread", None),
]


def _make_table(engine):
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE vehicle_reminders "
                "(id INTEGER PRIMARY KEY, source VARCHAR(20), notes TEXT)"
            )
        )
        for row_id, source, notes in _ROWS:
            conn.execute(
                text(
                    "INSERT INTO vehicle_reminders (id, source, notes) "
                    "VALUES (:id, :source, :notes)"
                ),
                {"id": row_id, "source": source, "notes": notes},
            )


def _notes(engine) -> dict[int, str | None]:
    with engine.connect() as conn:
        return dict(conn.execute(text("SELECT id, notes FROM vehicle_reminders")).all())


def test_127_clears_only_the_generated_sentence(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_table(engine)
    _load().upgrade(engine)
    notes = _notes(engine)
    assert notes[1] is None and notes[2] is None
    # Edited, someone else's, or not ours: untouched.
    assert notes[3] == _ROWS[2][2]
    assert notes[4] == _ROWS[3][2]
    assert notes[5] == _ROWS[4][2]
    assert notes[6] is None


def test_127_is_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_table(engine)
    mod = _load()
    mod.upgrade(engine)
    mod.upgrade(engine)
    assert _notes(engine)[3] == _ROWS[2][2]


def test_127_missing_table_skips(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _load().upgrade(engine)


def test_127_is_not_fatal():
    assert _load().FATAL is False
