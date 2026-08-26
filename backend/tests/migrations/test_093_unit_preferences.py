"""Migration 093: unit preference columns, UK materialisation, public default.

Every test builds a throwaway SQLite database from scratch, so these are
independent of the shared test database described in the project's test-isolation
notes.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from app.constants.units import UNIT_COLUMN_NAMES
from app.services.settings_init import DEFAULT_SETTINGS

_MIGRATION = (
    Path(__file__).parent.parent.parent / "app" / "migrations" / "093_add_unit_preferences.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("m093", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_db(tmp_path: Path, *, gallon_standard: str | None, users: list[dict]):
    """Build a pre-093 database: users and settings tables, no unit columns."""
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username VARCHAR(100) NOT NULL,
                    email VARCHAR(255) NOT NULL,
                    unit_preference VARCHAR(20) DEFAULT 'imperial' NOT NULL,
                    show_both_units BOOLEAN DEFAULT 0 NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE settings (
                    key VARCHAR(50) PRIMARY KEY,
                    value TEXT,
                    category VARCHAR(50) DEFAULT 'general',
                    description TEXT,
                    encrypted BOOLEAN DEFAULT false,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        if gallon_standard is not None:
            conn.execute(
                text("INSERT INTO settings (key, value) VALUES ('imperial_gallon_standard', :v)"),
                {"v": gallon_standard},
            )
        for user in users:
            conn.execute(
                text(
                    "INSERT INTO users (username, email, unit_preference, show_both_units) "
                    "VALUES (:u, :e, :p, :s)"
                ),
                {
                    "u": user["username"],
                    "e": f"{user['username']}@example.test",
                    "p": user["unit_preference"],
                    "s": user.get("show_both_units", 0),
                },
            )
    return engine


def _users(engine) -> dict[str, dict]:
    with engine.begin() as conn:
        cols = ", ".join(("username", "unit_preference", *UNIT_COLUMN_NAMES))
        rows = conn.execute(text(f"SELECT {cols} FROM users")).mappings().all()
    return {row["username"]: dict(row) for row in rows}


def _setting(engine, key: str) -> str | None:
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT value FROM settings WHERE key = :k"), {"k": key}
        ).scalar_one_or_none()
    return row


def _setting_metadata(engine, key: str) -> dict:
    """category and description, the two columns settings_init.py's update
    branch rewrites whenever they differ from DEFAULT_SETTINGS."""
    with engine.begin() as conn:
        row = (
            conn.execute(
                text("SELECT category, description FROM settings WHERE key = :k"), {"k": key}
            )
            .mappings()
            .one()
        )
    return dict(row)


class TestColumnCreation:
    def test_every_declared_unit_column_is_added(self, tmp_path: Path) -> None:
        """Every name in UNIT_COLUMN_NAMES gets an ADD COLUMN.

        This catches a migration that stops adding columns (a broken loop, a
        wrong-shaped guard, an early return). It does NOT catch a quantity added
        to the constants module: the migration iterates UNIT_COLUMN_NAMES, so a
        twelfth quantity is added here automatically and this test still passes,
        verified by reintroducing that defect. TestOrmModelParity is what makes
        that drift loud, because the ORM model is the hand-written side."""
        engine = _make_db(tmp_path, gallon_standard="us", users=[])
        _load_migration().upgrade(engine)

        columns = {c["name"] for c in inspect(engine).get_columns("users")}
        assert set(UNIT_COLUMN_NAMES) <= columns

    def test_all_new_columns_are_nullable(self, tmp_path: Path) -> None:
        """NULL means 'no override' (spec Phase 1), not 'derive from preset'."""
        engine = _make_db(tmp_path, gallon_standard="us", users=[])
        _load_migration().upgrade(engine)

        columns = {c["name"]: c for c in inspect(engine).get_columns("users")}
        for name in UNIT_COLUMN_NAMES:
            assert columns[name]["nullable"], f"{name} must be nullable"


class TestOrmModelParity:
    """The eleven ``users`` columns are hand-declared on the ORM model, so nothing
    but a test ties them to ``UNIT_COLUMN_NAMES``.

    ``create_all()`` builds a fresh database's schema from the model and migration
    093 builds an existing one's; a quantity added to ``UnitSet`` without a
    matching ``mapped_column`` would give the two paths different schemas, and the
    model is the side that does not update itself.
    """

    def test_user_model_declares_every_unit_column(self) -> None:
        from app.models.user import User

        declared = {column.name for column in User.__table__.columns}
        missing = [name for name in UNIT_COLUMN_NAMES if name not in declared]
        assert not missing, f"app/models/user.py is missing unit columns: {missing}"

    def test_declared_unit_columns_are_nullable_varchar_12(self) -> None:
        """Uniform VARCHAR(12) across all eleven (ruling P3). PostgreSQL enforces
        the width and SQLite does not, so a narrow column only fails in CI."""
        from app.models.user import User

        columns = {column.name: column for column in User.__table__.columns}
        for name in UNIT_COLUMN_NAMES:
            column = columns[name]
            assert column.nullable, f"{name} must be nullable"
            assert getattr(column.type, "length", None) == 12, (
                f"{name} must be VARCHAR(12), got {column.type}"
            )


class TestUsDefault:
    def test_us_instance_writes_secondary_gallon_only(self, tmp_path: Path) -> None:
        """Every current user must resolve exactly as they do now. On a US
        instance that means secondary_gallon='us' and ten untouched NULLs."""
        engine = _make_db(
            tmp_path,
            gallon_standard="us",
            users=[
                {"username": "imp", "unit_preference": "imperial"},
                {"username": "met", "unit_preference": "metric"},
            ],
        )
        _load_migration().upgrade(engine)

        rows = _users(engine)
        for username, seeded in (("imp", "imperial"), ("met", "metric")):
            assert rows[username]["secondary_gallon"] == "us"
            # The preset must survive untouched: on a US instance this migration
            # writes secondary_gallon and nothing else.
            assert rows[username]["unit_preference"] == seeded
            overrides = {
                k: v
                for k, v in rows[username].items()
                if k.startswith("unit_") and k != "unit_preference"
            }
            assert set(overrides.values()) == {None}, f"{username} got unexpected overrides"

    def test_absent_gallon_setting_is_treated_as_us(self, tmp_path: Path) -> None:
        """Migration 093 runs BEFORE default-settings init (app/main.py:144), so on
        a fresh database the imperial_gallon_standard row does not exist yet. Its
        absence must mean 'us', not a failure and not a NULL."""
        engine = _make_db(
            tmp_path,
            gallon_standard=None,
            users=[{"username": "fresh", "unit_preference": "imperial"}],
        )
        _load_migration().upgrade(engine)

        assert _users(engine)["fresh"]["secondary_gallon"] == "us"
        assert json.loads(_setting(engine, "default_unit_prefs"))["secondary_gallon"] == "us"


class TestUkMaterialisation:
    def test_uk_instance_materialises_imperial_users_to_custom(self, tmp_path: Path) -> None:
        """A UK instance's imperial users become fully-materialised custom users,
        so a later preset selection cannot silently revert them to US gallons."""
        engine = _make_db(
            tmp_path,
            gallon_standard="uk",
            users=[{"username": "imp", "unit_preference": "imperial"}],
        )
        _load_migration().upgrade(engine)

        row = _users(engine)["imp"]
        assert row["unit_preference"] == "custom"
        assert row["unit_volume"] == "gal_uk"
        assert row["unit_consumption"] == "mpg_uk"
        assert row["unit_distance"] == "mi"
        assert row["unit_pressure"] == "psi"
        assert row["unit_tread"] == "in32"
        assert row["secondary_gallon"] == "uk"
        # Fully materialised: no NULL survives.
        assert all(row[name] is not None for name in UNIT_COLUMN_NAMES)

    def test_uk_instance_leaves_metric_users_on_their_preset(self, tmp_path: Path) -> None:
        """Metric users are untouched apart from secondary_gallon, which is what
        preserves their show-both counterpart as UK gallons (D4b)."""
        engine = _make_db(
            tmp_path,
            gallon_standard="uk",
            users=[{"username": "met", "unit_preference": "metric"}],
        )
        _load_migration().upgrade(engine)

        row = _users(engine)["met"]
        assert row["unit_preference"] == "metric"
        assert row["secondary_gallon"] == "uk"
        overrides = [row[n] for n in UNIT_COLUMN_NAMES if n != "secondary_gallon"]
        assert overrides == [None] * 10

    def test_uk_instance_seeds_uk_default_unit_prefs(self, tmp_path: Path) -> None:
        """Anonymous and auth_mode=none clients read this row instead of the
        retiring public imperial_gallon_standard setting (D5)."""
        engine = _make_db(tmp_path, gallon_standard="uk", users=[])
        _load_migration().upgrade(engine)

        prefs = json.loads(_setting(engine, "default_unit_prefs"))
        assert prefs["volume"] == "gal_uk"
        assert prefs["consumption"] == "mpg_uk"
        assert prefs["secondary_gallon"] == "uk"
        assert len(prefs) == 11


class TestIdempotency:
    def test_running_twice_changes_nothing(self, tmp_path: Path) -> None:
        engine = _make_db(
            tmp_path,
            gallon_standard="uk",
            users=[
                {"username": "imp", "unit_preference": "imperial"},
                {"username": "met", "unit_preference": "metric"},
            ],
        )
        migration = _load_migration()
        migration.upgrade(engine)
        after_first = _users(engine)
        default_after_first = _setting(engine, "default_unit_prefs")

        migration.upgrade(engine)

        assert _users(engine) == after_first
        assert _setting(engine, "default_unit_prefs") == default_after_first

    def test_does_not_restamp_a_volume_chosen_after_materialisation(self, tmp_path: Path) -> None:
        """Kills the ``unit_volume IS NULL`` half of the UK backfill's guard.

        The state that matters is ruling P1's accepted mid-branch wart: a UK user
        materialised to ``custom`` saves the old two-option Units toggle, which
        writes ``unit_preference='imperial'`` back while the eleven override
        columns stay populated. That row matches ``unit_preference = 'imperial'``
        again, so the preset half of the predicate no longer protects it and
        ``unit_volume IS NULL`` is the only thing standing between the next
        boot's re-run and stamping over a deliberate choice.

        The obvious version of this test, where the user stays ``custom``, is
        protected by the preset half instead and passes with this guard deleted.
        """
        engine = _make_db(
            tmp_path,
            gallon_standard="uk",
            users=[{"username": "imp", "unit_preference": "imperial"}],
        )
        migration = _load_migration()
        migration.upgrade(engine)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE users SET unit_volume = 'L', unit_preference = 'imperial' "
                    "WHERE username = 'imp'"
                )
            )

        migration.upgrade(engine)

        row = _users(engine)["imp"]
        assert row["unit_volume"] == "L", "the UK backfill stamped over a chosen volume"
        assert row["unit_preference"] == "imperial", "the row should be left alone entirely"

    def test_does_not_restamp_a_secondary_gallon_the_user_changed(self, tmp_path: Path) -> None:
        """Kills the ``WHERE secondary_gallon IS NULL`` half of the flavour backfill.

        A user on a UK instance who picks US gallons for their show-both
        counterpart must keep that choice across the next boot. Without the
        predicate the re-run stamps the instance flavour back over it, and the
        preset predicates cannot help here because this backfill has none: it
        writes every user, every preset (D4b).
        """
        engine = _make_db(
            tmp_path,
            gallon_standard="uk",
            users=[{"username": "met", "unit_preference": "metric"}],
        )
        migration = _load_migration()
        migration.upgrade(engine)
        assert _users(engine)["met"]["secondary_gallon"] == "uk"

        with engine.begin() as conn:
            conn.execute(text("UPDATE users SET secondary_gallon = 'us' WHERE username = 'met'"))

        migration.upgrade(engine)

        assert _users(engine)["met"]["secondary_gallon"] == "us", (
            "the flavour backfill stamped over a chosen secondary_gallon"
        )

    def test_preserves_an_existing_default_unit_prefs_row(self, tmp_path: Path) -> None:
        """An admin who has already tuned the instance default keeps it."""
        engine = _make_db(tmp_path, gallon_standard="uk", users=[])
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO settings (key, value) VALUES ('default_unit_prefs', :v)"),
                {"v": '{"custom": "value"}'},
            )
        _load_migration().upgrade(engine)

        assert _setting(engine, "default_unit_prefs") == '{"custom": "value"}'

    def test_preserves_a_default_unit_prefs_row_whose_value_is_null(self, tmp_path: Path) -> None:
        """``settings.value`` is nullable, so "no row" and "row with a NULL value"
        are different states. Conflating them makes the seed attempt an INSERT
        against an existing primary key, which aborts the transaction; this
        migration is FATAL, so that failure stops the application booting."""
        engine = _make_db(tmp_path, gallon_standard="uk", users=[])
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO settings (key, value) VALUES ('default_unit_prefs', NULL)")
            )

        _load_migration().upgrade(engine)  # must not raise

        assert _setting(engine, "default_unit_prefs") is None


class TestRestartAfterPartialApplication:
    def test_resumes_when_some_columns_already_exist(self, tmp_path: Path) -> None:
        """Simulates a crash between two ADD COLUMN statements: the migration must
        add the rest rather than failing on the ones already present."""
        engine = _make_db(
            tmp_path,
            gallon_standard="uk",
            users=[{"username": "imp", "unit_preference": "imperial"}],
        )
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN unit_distance VARCHAR(12)"))
            conn.execute(text("ALTER TABLE users ADD COLUMN unit_speed VARCHAR(12)"))

        _load_migration().upgrade(engine)

        row = _users(engine)["imp"]
        assert row["unit_preference"] == "custom"
        assert all(row[name] is not None for name in UNIT_COLUMN_NAMES)


class TestMissingTables:
    def test_skips_cleanly_when_users_table_is_absent(self, tmp_path: Path) -> None:
        engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE placeholder (id INTEGER PRIMARY KEY)"))

        _load_migration().upgrade(engine)  # must not raise

    def test_is_marked_fatal(self) -> None:
        """The ORM selects these columns on every user query, so a silent failure
        would break every authenticated request. See the migration-FATAL note."""
        assert _load_migration().FATAL is True


class TestSettingsMetadataParity:
    def test_seeded_row_matches_the_default_settings_declaration(self, tmp_path: Path) -> None:
        """initialize_default_settings (app/services/settings_init.py) preserves
        an existing setting's *value* but rewrites its category and description
        whenever they differ from its DEFAULT_SETTINGS entry. This migration
        seeds default_unit_prefs with its own hardcoded category and
        description, written independently of that dict. If the two ever
        drift, every application boot after this migration runs issues a
        pointless UPDATE, forever, with nothing failing.

        This reads back what the migration actually wrote to a real database
        and compares it against what DEFAULT_SETTINGS actually declares: two
        independently-authored literals (one in this migration file, one in
        settings_init.py), not one constant compared against itself. Change
        either literal and this test must fail.
        """
        engine = _make_db(tmp_path, gallon_standard="us", users=[])
        _load_migration().upgrade(engine)

        seeded = _setting_metadata(engine, "default_unit_prefs")
        declared = DEFAULT_SETTINGS["default_unit_prefs"]

        assert seeded["category"] == declared["category"]
        assert seeded["description"] == declared["description"]
