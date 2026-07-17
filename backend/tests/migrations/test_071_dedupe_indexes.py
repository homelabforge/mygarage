"""Tests for migration 071 — dedupe redundant duplicate indexes + adopt
migration 011's partial oidc indexes in the ``User`` model.

Redundant indexes (dossier map — each duplicates a model/create_all index on
the same column(s) under a different name; nothing dedupes differently-named
indexes, so a fresh create_all-then-migrate replay carries both):
  - csrf_tokens: ``idx_csrf_token`` (migration 012) dup of the model's
    ``ix_csrf_tokens_token``.
  - odometer_records: ``idx_odometer_fuel_record_id`` (migration 055) dup of
    the model's ``ix_odometer_records_fuel_record_id``.
  - users: ``idx_users_auth_method`` (migration 011) dup of the model's
    ``ix_users_auth_method``.
  - users: ``ix_users_oidc_subject`` / ``ix_users_oidc_provider`` — the old
    plain create_all indexes built from the pre-Step-1 bare column flags
    (``unique=True, index=True`` / ``index=True``); superseded by migration
    011's leaner partial indexes (``idx_users_oidc_subject`` /
    ``idx_users_oidc_provider``), which the model now declares explicitly via
    ``__table_args__`` and which 071 keeps.

Part 2 proves the Step-1 model change stands on its own: building just the
``User`` table via ``Base.metadata`` must produce migration 011's partial
index directly (and never the old plain one), independent of the 071
migration ever running.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

import app.migrations as _m

MIGRATION = "071_dedupe_indexes"

DROPPED_INDEXES = (
    "idx_csrf_token",
    "idx_odometer_fuel_record_id",
    "idx_users_auth_method",
    "ix_users_oidc_subject",
    "ix_users_oidc_provider",
)

KEPT_INDEXES = {
    "csrf_tokens": ("ix_csrf_tokens_token",),
    "odometer_records": ("ix_odometer_records_fuel_record_id",),
    "users": ("ix_users_auth_method", "idx_users_oidc_subject", "idx_users_oidc_provider"),
}


def _load(name: str):
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _index_names(engine, table: str) -> set[str]:
    return {ix["name"] for ix in inspect(engine).get_indexes(table)}


def _sqlite_index_sql(engine, name: str) -> str:
    """Raw index DDL from ``sqlite_master`` (SQLite only) — the only way to see
    a partial index's WHERE predicate; SQLAlchemy's ``get_indexes()`` reports
    columns + uniqueness but not the predicate (R1 recommended).
    """
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='index' AND name=:n"),
            {"n": name},
        ).fetchone()
    assert row is not None, f"index {name} not found in sqlite_master"
    return row[0] or ""


def _create_dossier_tables(engine, dialect: str) -> None:
    """Create the three affected tables in their pre-071 shape: BOTH the
    model-declared index and the redundant hand-named duplicate present.
    """
    id_type = "SERIAL PRIMARY KEY" if dialect == "pg" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    with engine.begin() as conn:
        conn.execute(
            text(f"""
                CREATE TABLE csrf_tokens (
                    id {id_type},
                    token VARCHAR(64) NOT NULL,
                    user_id INTEGER NOT NULL
                )
            """)
        )
        conn.execute(
            text(f"""
                CREATE TABLE odometer_records (
                    id {id_type},
                    fuel_record_id INTEGER
                )
            """)
        )
        conn.execute(
            text(f"""
                CREATE TABLE users (
                    id {id_type},
                    auth_method VARCHAR(20),
                    oidc_subject VARCHAR(255),
                    oidc_provider VARCHAR(100)
                )
            """)
        )

        # csrf_tokens: model index (kept) + migration 012's redundant duplicate.
        conn.execute(text("CREATE UNIQUE INDEX ix_csrf_tokens_token ON csrf_tokens(token)"))
        conn.execute(text("CREATE UNIQUE INDEX idx_csrf_token ON csrf_tokens(token)"))

        # odometer_records: model index (kept) + migration 055's redundant duplicate.
        conn.execute(
            text(
                "CREATE INDEX ix_odometer_records_fuel_record_id "
                "ON odometer_records(fuel_record_id)"
            )
        )
        conn.execute(
            text("CREATE INDEX idx_odometer_fuel_record_id ON odometer_records(fuel_record_id)")
        )

        # users.auth_method: model index (kept) + migration 011's redundant duplicate.
        conn.execute(text("CREATE INDEX ix_users_auth_method ON users(auth_method)"))
        conn.execute(text("CREATE INDEX idx_users_auth_method ON users(auth_method)"))

        # users.oidc_subject/provider: old plain create_all indexes (dropped) +
        # migration 011's partial indexes, now also declared by the model (kept).
        conn.execute(text("CREATE UNIQUE INDEX ix_users_oidc_subject ON users(oidc_subject)"))
        conn.execute(text("CREATE INDEX ix_users_oidc_provider ON users(oidc_provider)"))
        conn.execute(
            text(
                "CREATE UNIQUE INDEX idx_users_oidc_subject ON users(oidc_subject) "
                "WHERE oidc_subject IS NOT NULL"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX idx_users_oidc_provider ON users(oidc_provider) "
                "WHERE oidc_provider IS NOT NULL"
            )
        )


def test_dedupes_redundant_indexes_and_keeps_predicates(engine_for_migration):
    """071 drops the five redundant hand-named indexes and leaves the kept
    (model-matching) ones in place; on SQLite the kept partial oidc indexes
    still carry their ``IS NOT NULL`` predicate after the migration runs.
    """
    dialect, engine, _url = engine_for_migration
    _create_dossier_tables(engine, dialect)

    _load(MIGRATION).upgrade(engine=engine)

    csrf_idx = _index_names(engine, "csrf_tokens")
    odo_idx = _index_names(engine, "odometer_records")
    users_idx = _index_names(engine, "users")

    for name in DROPPED_INDEXES:
        assert name not in csrf_idx | odo_idx | users_idx, f"{name} should have been dropped"

    assert set(KEPT_INDEXES["csrf_tokens"]) <= csrf_idx
    assert set(KEPT_INDEXES["odometer_records"]) <= odo_idx
    assert set(KEPT_INDEXES["users"]) <= users_idx

    if dialect == "sqlite":
        subj_sql = _sqlite_index_sql(engine, "idx_users_oidc_subject").upper()
        prov_sql = _sqlite_index_sql(engine, "idx_users_oidc_provider").upper()
        assert "IS NOT NULL" in subj_sql
        assert "IS NOT NULL" in prov_sql
        assert "UNIQUE" in subj_sql


def test_idempotent_second_run(engine_for_migration):
    """Second run over already-dropped indexes must not raise — DROP INDEX IF
    EXISTS is inherently idempotent (missing index -> no-op).
    """
    dialect, engine, _url = engine_for_migration
    _create_dossier_tables(engine, dialect)
    migration = _load(MIGRATION)

    migration.upgrade(engine=engine)
    migration.upgrade(engine=engine)  # must not raise

    users_idx = _index_names(engine, "users")
    assert "idx_users_oidc_subject" in users_idx
    assert "ix_users_oidc_subject" not in users_idx


def test_missing_indexes_and_tables_is_noop(engine_for_migration):
    """None of the target tables/indexes exist at all — must not raise."""
    _dialect, engine, _url = engine_for_migration
    _load(MIGRATION).upgrade(engine=engine)  # must not raise


def test_model_produces_partial_oidc_index(engine_for_migration):
    """Step-1 model coverage: creating just the ``User`` table via
    ``Base.metadata`` must produce migration 011's partial
    ``idx_users_oidc_subject`` (unique, ``WHERE ... IS NOT NULL``) and never
    the old plain ``ix_users_oidc_subject``. ``sqlite_master`` is the only way
    to see the predicate, so this check is SQLite-only — the parity snapshot
    (structural, not predicate-aware) can't see it either.
    """
    dialect, engine, _url = engine_for_migration
    if dialect != "sqlite":
        pytest.skip("predicate check requires sqlite_master; index presence is dialect-generic")

    from app.models.user import User

    User.__table__.create(engine)

    subj_sql = _sqlite_index_sql(engine, "idx_users_oidc_subject").upper()
    assert "IS NOT NULL" in subj_sql
    assert "UNIQUE" in subj_sql

    prov_sql = _sqlite_index_sql(engine, "idx_users_oidc_provider").upper()
    assert "IS NOT NULL" in prov_sql

    names = _index_names(engine, "users")
    assert "ix_users_oidc_subject" not in names
    assert "idx_users_oidc_subject" in names
    assert "idx_users_oidc_provider" in names
