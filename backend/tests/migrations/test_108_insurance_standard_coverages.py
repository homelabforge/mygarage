"""Tests for migration 108 — free-text coverage limits become standard rows.

Parameterized over SQLite *and* PostgreSQL via ``engine_for_migration``,
because the two take completely different routes to dropping a column: SQLite
rebuilds the whole table, PostgreSQL runs one ALTER. The conversion itself is
pure, so its edge cases are also tested without a database.
"""

from decimal import Decimal

from sqlalchemy import inspect, text

from tests.migrations._loader import load_migration

D = Decimal
RAM = "MIG108VIN00000001"
MIRAGE = "MIG108VIN00000002"

PROGRESSIVE = """Liability to Others $315
Bodily Injury Liability $100,000 each person/$300,000 each accident
Comprehensive Actual Cash Value $1,000 $146.00
Roadside Assistance
Disappearing Deductibles"""


def _load_107():
    return load_migration("107_household_insurance_policies")


def _load():
    return load_migration("108_insurance_standard_coverages")


def _make_post_107(engine):
    """The schema as migration 107 leaves it: household policies, text limits."""
    is_pg = engine.dialect.name == "postgresql"
    serial = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
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
                f"CREATE TABLE insurance_policies (id {serial}, provider VARCHAR(100) NOT NULL, "
                "policy_number VARCHAR(50) NOT NULL, start_date DATE NOT NULL, "
                "end_date DATE NOT NULL, premium_amount NUMERIC(10,2), "
                "premium_frequency VARCHAR(20), notes TEXT, created_by_user_id INTEGER, "
                f"previous_policy_id INTEGER, created_at {stamp}, last_notified_at {stamp})"
            )
        )
        conn.execute(
            text(
                f"CREATE TABLE insurance_policy_vehicles (id {serial}, "
                "policy_id INTEGER NOT NULL REFERENCES insurance_policies(id) ON DELETE CASCADE, "
                "vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE, "
                "policy_type VARCHAR(30) NOT NULL, premium_share NUMERIC(10,2), "
                "deductible NUMERIC(10,2), coverage_limits TEXT, notes TEXT, effective_to DATE, "
                f"created_at {stamp}, CONSTRAINT uq_insurance_policy_vehicle "
                "UNIQUE (policy_id, vin))"
            )
        )
        conn.execute(
            text(
                f"CREATE TABLE insurance_policy_fields (id {serial}, "
                "policy_id INTEGER NOT NULL REFERENCES insurance_policies(id) ON DELETE CASCADE, "
                "policy_vehicle_id INTEGER REFERENCES insurance_policy_vehicles(id) "
                "ON DELETE CASCADE, label VARCHAR(60) NOT NULL, value VARCHAR(255) NOT NULL, "
                "sort_order INTEGER NOT NULL DEFAULT 0)"
            )
        )
        conn.execute(text("INSERT INTO users (id, username) VALUES (1, 'jamey')"))
        conn.execute(
            text(
                "INSERT INTO vehicles (vin, user_id, nickname) VALUES (:a, 1, 'Ram'), (:b, 1, 'M')"
            ),
            {"a": RAM, "b": MIRAGE},
        )
        conn.execute(
            text(
                "INSERT INTO insurance_policies (id, provider, policy_number, start_date, "
                "end_date, premium_amount, premium_frequency, created_by_user_id) VALUES "
                "(1, 'Progressive', 'P-100', '2026-01-01', '2027-01-01', '2000.00', 'Annual', 1)"
            )
        )


def _link(conn, link_id, vin, **over):
    row = {
        "id": link_id,
        "policy_id": 1,
        "vin": vin,
        "policy_type": "Full Coverage",
        "premium_share": "1000.00",
        "deductible": "500.00",
        "coverage_limits": None,
        "notes": None,
        "effective_to": None,
    } | over
    conn.execute(
        text(
            "INSERT INTO insurance_policy_vehicles (id, policy_id, vin, policy_type, "
            "premium_share, deductible, coverage_limits, notes, effective_to) VALUES "
            "(:id, :policy_id, :vin, :policy_type, :premium_share, :deductible, "
            ":coverage_limits, :notes, :effective_to)"
        ),
        row,
    )


def _coverages(engine, link_id):
    with engine.begin() as conn:
        return {
            r.coverage_key: (r.limit_primary, r.limit_secondary, r.deductible, r.premium)
            for r in conn.execute(
                text(
                    "SELECT coverage_key, limit_primary, limit_secondary, deductible, premium "
                    "FROM insurance_coverages WHERE policy_vehicle_id = :id"
                ),
                {"id": link_id},
            )
        }


def _fields(engine, link_id):
    with engine.begin() as conn:
        return [
            (r.label, r.value, r.sort_order)
            for r in conn.execute(
                text(
                    "SELECT label, value, sort_order FROM insurance_policy_fields "
                    "WHERE policy_vehicle_id = :id ORDER BY sort_order"
                ),
                {"id": link_id},
            )
        ]


def _money(value):
    return None if value is None else D(str(value)).quantize(D("0.01"))


# ---------------------------------------------------------------------------
# The conversion, with a database
# ---------------------------------------------------------------------------


def test_108_reads_the_coverage_text_into_standard_rows(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_post_107(engine)
    with engine.begin() as conn:
        _link(conn, 1, RAM, coverage_limits=PROGRESSIVE)

    _load().upgrade(engine)

    coverages = _coverages(engine, 1)
    assert set(coverages) == {"bodily_injury", "comprehensive", "roadside_assistance"}
    assert _money(coverages["bodily_injury"][0]) == D("100000.00")
    assert _money(coverages["bodily_injury"][1]) == D("300000.00")
    assert _money(coverages["comprehensive"][2]) == D("1000.00")
    assert _money(coverages["comprehensive"][3]) == D("146.00")
    # A coverage carried with no amounts is still a row: its existence is the fact.
    assert coverages["roadside_assistance"] == (None, None, None, None)


def test_108_keeps_an_unrecognised_priced_line_as_a_named_field(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_post_107(engine)
    with engine.begin() as conn:
        _link(conn, 1, RAM, coverage_limits=PROGRESSIVE)

    _load().upgrade(engine)

    assert _fields(engine, 1) == [("Liability to Others", "$315", 0)]


def test_108_keeps_an_unpriced_line_in_the_notes(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_post_107(engine)
    with engine.begin() as conn:
        _link(conn, 1, RAM, coverage_limits=PROGRESSIVE, notes="Garaged at home")

    _load().upgrade(engine)

    with engine.begin() as conn:
        notes = conn.execute(
            text("SELECT notes FROM insurance_policy_vehicles WHERE id = 1")
        ).scalar()
    assert notes == "Garaged at home\nDisappearing Deductibles"


def test_108_appends_converted_fields_after_the_ones_the_user_typed(engine_for_migration):
    """A user's own fields keep their order and their place at the top."""
    _dialect, engine, _url = engine_for_migration
    _make_post_107(engine)
    with engine.begin() as conn:
        _link(conn, 1, RAM, coverage_limits=PROGRESSIVE)
        conn.execute(
            text(
                "INSERT INTO insurance_policy_fields (policy_id, policy_vehicle_id, label, "
                "value, sort_order) VALUES (1, 1, 'Agent', 'Dana', 0), "
                "(1, 1, 'Claims Phone', '555-0100', 1)"
            )
        )

    _load().upgrade(engine)

    assert _fields(engine, 1) == [
        ("Agent", "Dana", 0),
        ("Claims Phone", "555-0100", 1),
        ("Liability to Others", "$315", 2),
    ]


def test_108_leaves_a_vehicle_with_no_coverage_text_alone(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_post_107(engine)
    with engine.begin() as conn:
        _link(conn, 1, RAM, coverage_limits=None, notes="Nothing to convert")
        _link(conn, 2, MIRAGE, coverage_limits="   ")

    _load().upgrade(engine)

    assert _coverages(engine, 1) == {}
    assert _coverages(engine, 2) == {}
    with engine.begin() as conn:
        notes = conn.execute(
            text("SELECT notes FROM insurance_policy_vehicles WHERE id = 1")
        ).scalar()
    assert notes == "Nothing to convert"


def test_108_carries_every_other_column_through_the_rebuild(engine_for_migration):
    """SQLite drops the column by rebuilding the table: nothing else may move."""
    _dialect, engine, _url = engine_for_migration
    _make_post_107(engine)
    with engine.begin() as conn:
        _link(
            conn,
            7,
            RAM,
            coverage_limits=PROGRESSIVE,
            policy_type="Liability",
            premium_share="1234.56",
            deductible="750.00",
            effective_to="2026-06-30",
            notes="keep me",
        )

    _load().upgrade(engine)

    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT id, policy_id, vin, policy_type, premium_share, deductible, notes, "
                "effective_to FROM insurance_policy_vehicles"
            )
        ).one()
    assert row.id == 7
    assert (row.policy_id, row.vin, row.policy_type) == (1, RAM, "Liability")
    assert _money(row.premium_share) == D("1234.56")
    assert _money(row.deductible) == D("750.00")
    assert str(row.effective_to) == "2026-06-30"
    # The id is preserved because the coverages just written point at it.
    assert set(_coverages(engine, 7))


def test_108_drops_the_text_column(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_post_107(engine)
    with engine.begin() as conn:
        _link(conn, 1, RAM, coverage_limits=PROGRESSIVE)

    _load().upgrade(engine)

    columns = {c["name"] for c in inspect(engine).get_columns("insurance_policy_vehicles")}
    assert "coverage_limits" not in columns
    assert {"policy_type", "premium_share", "deductible", "notes", "effective_to"} <= columns


def test_108_is_re_entrant(engine_for_migration):
    """The second run must not double the rows it wrote on the first."""
    _dialect, engine, _url = engine_for_migration
    _make_post_107(engine)
    with engine.begin() as conn:
        _link(conn, 1, RAM, coverage_limits=PROGRESSIVE)

    module = _load()
    module.upgrade(engine)
    first_coverages, first_fields = _coverages(engine, 1), _fields(engine, 1)
    module.upgrade(engine)

    assert _coverages(engine, 1) == first_coverages
    assert _fields(engine, 1) == first_fields


def test_108_cascades_from_the_rebuilt_link_table(engine_for_migration):
    """Deleting a vehicle's link must still take its coverages with it.

    The SQLite path drops and recreates the parent table, so the child's
    foreign key has to end up pointing at the new one.
    """
    _dialect, engine, _url = engine_for_migration
    _make_post_107(engine)
    with engine.begin() as conn:
        _link(conn, 1, RAM, coverage_limits=PROGRESSIVE)

    _load().upgrade(engine)

    with engine.begin() as conn:
        if engine.dialect.name != "postgresql":
            conn.execute(text("PRAGMA foreign_keys = ON"))
        conn.execute(text("DELETE FROM insurance_policy_vehicles WHERE id = 1"))
    assert _coverages(engine, 1) == {}


# ---------------------------------------------------------------------------
# The conversion, pure
# ---------------------------------------------------------------------------


def _plan(text_value, **over):
    row = {"id": 1, "policy_id": 1, "coverage_limits": text_value, "notes": None} | over
    return _load().plan_conversion([row])


def test_plan_skips_a_link_whose_text_holds_nothing():
    assert _plan(None) == []
    assert _plan("") == []
    assert _plan("\n \n") == []


def test_plan_starts_converted_fields_after_the_existing_ones():
    planned = _plan("Roof Protection $5,000", next_sort_order=4)
    assert planned[0]["fields"][0]["sort_order"] == 4


def test_plan_leaves_notes_alone_when_every_line_was_understood():
    planned = _plan("Roadside Assistance", notes="Garaged at home")
    assert planned[0]["notes_changed"] is False
    assert planned[0]["notes"] == "Garaged at home"


def test_plan_starts_the_notes_when_a_vehicle_had_none():
    planned = _plan("Disappearing Deductibles")
    assert planned[0]["notes"] == "Disappearing Deductibles"


def test_107_still_runs_when_create_all_built_the_link_table_first(engine_for_migration):
    """Upgrading from a release BEFORE 107 must not break at startup.

    `create_all` runs before the migrations and builds
    `insurance_policy_vehicles` from the CURRENT ORM, which no longer has
    `coverage_limits`. Migration 107 then has to move the legacy text into a
    table that was made without the column it writes to, and 107 is FATAL, so
    failing there stops the app from starting at all.
    """
    _dialect, engine, _url = engine_for_migration
    is_pg = engine.dialect.name == "postgresql"
    serial = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    stamp = "TIMESTAMP" if is_pg else "DATETIME"
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(50))"))
        conn.execute(
            text(
                "CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY, "
                "user_id INTEGER REFERENCES users(id), nickname VARCHAR(50))"
            )
        )
        # The PRE-107 shape: one policy row per vehicle, carrying the text.
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
        # What create_all makes from TODAY's ORM: no coverage_limits.
        conn.execute(
            text(
                f"CREATE TABLE insurance_policy_vehicles (id {serial}, "
                "policy_id INTEGER NOT NULL REFERENCES insurance_policies(id) ON DELETE CASCADE, "
                "vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE, "
                "policy_type VARCHAR(30) NOT NULL, premium_share NUMERIC(10,2), "
                "deductible NUMERIC(10,2), notes TEXT, effective_to DATE, "
                f"created_at {stamp})"
            )
        )
        conn.execute(
            text(
                f"CREATE TABLE insurance_policy_fields (id {serial}, policy_id INTEGER NOT NULL, "
                "policy_vehicle_id INTEGER, label VARCHAR(60) NOT NULL, "
                "value VARCHAR(255) NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0)"
            )
        )
        conn.execute(text("INSERT INTO users (id, username) VALUES (1, 'jamey')"))
        conn.execute(
            text("INSERT INTO vehicles (vin, user_id, nickname) VALUES (:a, 1, 'Ram')"),
            {"a": RAM},
        )
        conn.execute(
            text(
                "INSERT INTO insurance_policies (vin, provider, policy_number, policy_type, "
                "start_date, end_date, premium_amount, premium_frequency, deductible, "
                "coverage_limits) VALUES (:vin, 'Progressive', 'P-1', 'Full Coverage', "
                "'2026-01-01', '2026-07-01', '600.00', 'Semi-Annual', '500.00', :limits)"
            ),
            {"vin": RAM, "limits": PROGRESSIVE},
        )

    _load_107().upgrade(engine)
    _load().upgrade(engine)

    # Both ran, and the vehicle's coverage survived the whole path.
    with engine.begin() as conn:
        link_id = conn.execute(text("SELECT id FROM insurance_policy_vehicles")).scalar()
    assert set(_coverages(engine, link_id)) >= {"bodily_injury", "comprehensive"}
