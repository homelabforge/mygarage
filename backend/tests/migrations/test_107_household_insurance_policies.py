"""Tests for migration 107 — per-vehicle insurance rows become household policies.

Parameterized over SQLite *and* PostgreSQL via ``engine_for_migration``. The
merge plan itself is pure, so its edge cases are also tested without a database.
"""

import importlib.util
from decimal import Decimal
from pathlib import Path

from sqlalchemy import inspect, text

import app.migrations as _m

D = Decimal
RAM = "MIG107VIN00000001"
MIRAGE = "MIG107VIN00000002"
OTHERS = "MIG107VIN00000003"


def _load():
    name = "107_household_insurance_policies"
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_legacy(engine, dialect):
    is_pg = engine.dialect.name == "postgresql"
    serial = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY"
    stamp = "TIMESTAMP" if is_pg else "DATETIME"
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(50))"))
        conn.execute(
            text(
                "CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY, "
                "user_id INTEGER REFERENCES users(id), nickname VARCHAR(50))"
            )
        )
        conn.execute(
            text(
                f"CREATE TABLE insurance_policies (id {serial}, "
                "vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE, "
                "provider VARCHAR(100) NOT NULL, policy_number VARCHAR(50) NOT NULL, "
                "policy_type VARCHAR(30) NOT NULL, start_date DATE NOT NULL, "
                "end_date DATE NOT NULL, premium_amount NUMERIC(10,2), "
                "premium_frequency VARCHAR(20), deductible NUMERIC(10,2), "
                f"coverage_limits TEXT, notes TEXT, created_at {stamp}, "
                f"last_notified_at {stamp})"
            )
        )
        conn.execute(text("CREATE INDEX idx_insurance_policies_vin ON insurance_policies (vin)"))
        conn.execute(text("INSERT INTO users (id, username) VALUES (1, 'jamey'), (2, 'friend')"))
        conn.execute(
            text(
                "INSERT INTO vehicles (vin, user_id, nickname) VALUES "
                "(:a, 1, 'Ram'), (:b, 1, 'Mirage'), (:c, 2, 'Theirs')"
            ),
            {"a": RAM, "b": MIRAGE, "c": OTHERS},
        )


def _policy(conn, pid, vin, **over):
    row = {
        "id": pid,
        "vin": vin,
        "provider": "Progressive",
        "policy_number": "P-100",
        "policy_type": "Full Coverage",
        "start_date": "2026-01-01",
        "end_date": "2026-07-01",
        "premium_amount": "300.00",
        "premium_frequency": "Semi-Annual",
        "deductible": "500.00",
        "coverage_limits": None,
        "notes": None,
        "created_at": "2026-01-01 00:00:00",
        "last_notified_at": None,
    } | over
    conn.execute(
        text(
            "INSERT INTO insurance_policies (id, vin, provider, policy_number, policy_type, "
            "start_date, end_date, premium_amount, premium_frequency, deductible, "
            "coverage_limits, notes, created_at, last_notified_at) VALUES (:id, :vin, "
            ":provider, :policy_number, :policy_type, :start_date, :end_date, "
            ":premium_amount, :premium_frequency, :deductible, :coverage_limits, :notes, "
            ":created_at, :last_notified_at)"
        ),
        row,
    )


def _state(engine):
    with engine.begin() as conn:
        policies = {
            r.id: r
            for r in conn.execute(
                text(
                    "SELECT id, provider, policy_number, premium_amount, premium_frequency, "
                    "created_by_user_id, previous_policy_id FROM insurance_policies ORDER BY id"
                )
            )
        }
        links = [
            (r.policy_id, r.vin, r.policy_type, r.premium_share, r.deductible, r.notes)
            for r in conn.execute(
                text(
                    "SELECT policy_id, vin, policy_type, premium_share, deductible, notes "
                    "FROM insurance_policy_vehicles ORDER BY policy_id, vin"
                )
            )
        ]
    return policies, links


def _money(value):
    return None if value is None else D(str(value)).quantize(D("0.01"))


def test_107_merges_one_owners_duplicated_policy_and_keeps_every_vehicle_number(
    engine_for_migration,
):
    dialect, engine, _url = engine_for_migration
    _make_legacy(engine, dialect)
    with engine.begin() as conn:
        _policy(conn, 1, RAM, premium_amount="320.00", deductible="500.00", notes="truck")
        _policy(conn, 2, MIRAGE, premium_amount="280.00", policy_type="Liability", deductible=None)

    _load().upgrade(engine)

    policies, links = _state(engine)
    assert list(policies) == [1], "two rows of one policy must become ONE policy"
    assert _money(policies[1].premium_amount) == D("600.00")
    assert policies[1].created_by_user_id == 1
    # THE INVARIANT: each vehicle still shows exactly what it showed before.
    assert [(p, v, t, _money(s), _money(d), n) for p, v, t, s, d, n in links] == [
        (1, RAM, "Full Coverage", D("320.00"), D("500.00"), "truck"),
        (1, MIRAGE, "Liability", D("280.00"), None, None),
    ]
    assert "vin" not in {c["name"] for c in inspect(engine).get_columns("insurance_policies")}


def test_107_never_merges_across_owners_or_frequencies(engine_for_migration):
    dialect, engine, _url = engine_for_migration
    _make_legacy(engine, dialect)
    with engine.begin() as conn:
        _policy(conn, 1, RAM)
        _policy(conn, 2, OTHERS)  # same provider/number/dates, ANOTHER user's vehicle
        _policy(conn, 3, MIRAGE, premium_frequency="Monthly", premium_amount="50.00")

    _load().upgrade(engine)

    policies, links = _state(engine)
    assert sorted(policies) == [1, 2, 3]
    assert {p: v for p, v, *_ in links} == {1: RAM, 2: OTHERS, 3: MIRAGE}
    assert policies[2].created_by_user_id == 2
    # Kept apart by this migration => concurrent => must NOT read as superseded.
    assert all(p.previous_policy_id is None for p in policies.values())


def test_107_chains_sequential_terms_only(engine_for_migration):
    dialect, engine, _url = engine_for_migration
    _make_legacy(engine, dialect)
    with engine.begin() as conn:
        _policy(conn, 1, RAM, start_date="2025-07-01", end_date="2026-01-01")
        _policy(conn, 2, RAM, start_date="2026-01-01", end_date="2026-07-01")
        _policy(conn, 3, RAM, start_date="2026-07-01", end_date="2027-01-01")
        _policy(conn, 4, MIRAGE, provider="GEICO", policy_number="G-9")

    _load().upgrade(engine)

    policies, _links = _state(engine)
    assert {i: p.previous_policy_id for i, p in policies.items()} == {
        1: None,
        2: 1,
        3: 2,
        4: None,
    }


def test_107_an_unknown_premium_stays_unknown(engine_for_migration):
    dialect, engine, _url = engine_for_migration
    _make_legacy(engine, dialect)
    with engine.begin() as conn:
        _policy(conn, 1, RAM, premium_amount="320.00")
        _policy(conn, 2, MIRAGE, premium_amount=None)

    _load().upgrade(engine)

    policies, links = _state(engine)
    assert policies[1].premium_amount is None, "a partial sum would invent a total"
    assert [(v, _money(s)) for _p, v, _t, s, *_ in links] == [(RAM, D("320.00")), (MIRAGE, None)]


def test_107_is_idempotent_and_leaves_other_tables_alone(engine_for_migration):
    dialect, engine, _url = engine_for_migration
    _make_legacy(engine, dialect)
    with engine.begin() as conn:
        _policy(conn, 1, RAM)
        _policy(conn, 2, MIRAGE)

    mod = _load()
    mod.upgrade(engine)
    before = _state(engine)
    mod.upgrade(engine)  # second run: `vin` is gone, so it must be a no-op

    assert _state(engine)[1] == before[1]
    with engine.begin() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM vehicles")).scalar() == 3
        assert conn.execute(text("SELECT COUNT(*) FROM users")).scalar() == 2


class TestPlanMerge:
    """The pure plan, for the shapes a database fixture makes awkward."""

    @staticmethod
    def _row(rid, vin, **over):
        return {
            "id": rid,
            "vin": vin,
            "provider": "Progressive",
            "policy_number": "P-100",
            "policy_type": "Full Coverage",
            "start_date": "2026-01-01",
            "end_date": "2026-07-01",
            "premium_amount": D("300.00"),
            "premium_frequency": "Semi-Annual",
            "deductible": D("500.00"),
            "coverage_limits": None,
            "notes": None,
            "created_at": "2026-01-01",
            "last_notified_at": None,
        } | over

    def test_a_compatible_same_vehicle_duplicate_folds_without_doubling_the_premium(self):
        rows = [self._row(1, RAM, notes=None), self._row(2, RAM, notes="garage kept")]
        policies, log = _load().plan_merge(rows, {RAM: 1})
        assert len(policies) == 1
        assert policies[0]["premium_amount"] == D("300.00")
        assert policies[0]["links"][0]["notes"] == "garage kept"
        assert any("folded" in line for line in log)

    def test_a_conflicting_same_vehicle_duplicate_becomes_its_own_policy(self):
        rows = [self._row(1, RAM), self._row(2, RAM, deductible=D("1000.00"))]
        policies, _log = _load().plan_merge(rows, {RAM: 1})
        assert [p["id"] for p in policies] == [1, 2]
        assert [p["links"][0]["deductible"] for p in policies] == [D("500.00"), D("1000.00")]
        assert all(p["previous_policy_id"] is None for p in policies)

    def test_unknown_vocabulary_is_coerced_not_fatal(self):
        rows = [self._row(1, RAM, policy_type="Umbrella", premium_frequency="Weekly")]
        policies, log = _load().plan_merge(rows, {RAM: 1})
        assert policies[0]["links"][0]["policy_type"] == "Other"
        assert policies[0]["premium_frequency"] is None
        assert len(log) == 2

    def test_two_concurrent_successors_of_one_term_are_not_chained(self):
        rows = [
            self._row(1, RAM, start_date="2025-07-01", end_date="2026-01-01"),
            self._row(2, RAM, start_date="2026-01-01", end_date="2026-07-01"),
            self._row(
                3, RAM, start_date="2026-01-01", end_date="2026-07-01", deductible=D("1000.00")
            ),
        ]
        policies, _log = _load().plan_merge(rows, {RAM: 1})
        assert {p["id"]: p["previous_policy_id"] for p in policies} == {1: None, 2: None, 3: None}
