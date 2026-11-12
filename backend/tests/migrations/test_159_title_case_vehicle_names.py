"""Migration 159: stored makes and models in Title Case (#219 takeover)."""

import pytest
from sqlalchemy import Engine, text

from tests._logged import problems
from tests.migrations._loader import load_migration

pytestmark = pytest.mark.migrations

_NAME = "159_title_case_vehicle_names"


def _load():
    return load_migration(_NAME)


def _upgrade(engine: Engine) -> None:
    """Run it the way the runner does: on one connection, in one transaction."""
    with engine.begin() as conn:
        _load().upgrade(conn=conn)


def _seed(engine: Engine, *, external: bool = True) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY, make VARCHAR(50), model VARCHAR(50))"
            )
        )
        for vin, make, model in [
            ("JA3MIG15900000001", "MITSUBISHI", "MIRAGE"),
            ("3C6MIG15900000002", "RAM", "3500"),
            ("4KZMIG15900000003", "KZ-RV", "Durango"),
            ("SBMMIG15900000004", "McLaren", "720S"),
            ("1HGMIG15900000005", "Chevy", "SILVERADO 1500"),
            ("VF1MIG15900000006", None, None),
            ("TMBMIG15900000007", "SKODA", "OCTAVIA"),
            ("WMWMIG15900000008", "MINI", "ONE"),
            ("W1KMIG15900000009", "MERCEDES-AMG", "ONE"),
        ]:
            conn.execute(
                text("INSERT INTO vehicles (vin, make, model) VALUES (:v, :m, :md)"),
                {"v": vin, "m": make, "md": model},
            )
        if not external:
            return
        conn.execute(
            text(
                "CREATE TABLE external_vehicles (id INTEGER PRIMARY KEY, vin VARCHAR(17),"
                " make VARCHAR(50), model VARCHAR(50))"
            )
        )
        for row_id, vin, make, model in [
            (1, None, "TOYOTA", "RAV4"),
            (2, "1HGSHARED00000001", "HONDA", "CR-V"),
            (3, "1HGSHARED00000001", "ACURA", "MDX"),
            (4, None, "Ford", "F-150"),
        ]:
            conn.execute(
                text(
                    "INSERT INTO external_vehicles (id, vin, make, model) VALUES (:i, :v, :m, :md)"
                ),
                {"i": row_id, "v": vin, "m": make, "md": model},
            )


def _vehicles(engine: Engine) -> dict[str, tuple[str | None, str | None]]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT vin, make, model FROM vehicles")).all()
    return {r[0]: (r[1], r[2]) for r in rows}


def _externals(engine: Engine) -> dict[int, tuple[str | None, str | None]]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, make, model FROM external_vehicles")).all()
    return {r[0]: (r[1], r[2]) for r in rows}


def test_the_migration_is_not_fatal():
    # guard: a failed 159 leaves the old casing, which still reads fine.
    assert not getattr(_load(), "FATAL", False)


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_vehicles_take_title_case(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _seed(engine)

    _upgrade(engine)

    assert _vehicles(engine) == {
        "JA3MIG15900000001": ("Mitsubishi", "Mirage"),
        "3C6MIG15900000002": ("Ram", "3500"),
        "4KZMIG15900000003": ("KZ-RV", "Durango"),
        "SBMMIG15900000004": ("McLaren", "720S"),
        "1HGMIG15900000005": ("Chevrolet", "Silverado 1500"),
        "VF1MIG15900000006": (None, None),
        "TMBMIG15900000007": ("Škoda", "Octavia"),
        # The make picks the spelling (Fable fix-wave F-1).
        "WMWMIG15900000008": ("MINI", "One"),
        "W1KMIG15900000009": ("Mercedes-AMG", "ONE"),
    }


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_external_vehicles_are_rewritten_by_id(engine_for_migration):
    # R1-H1: a VIN-keyed update would skip the NULL-VIN rows and give the two
    # rows sharing a VIN one row's values.
    _dialect, engine, _url = engine_for_migration
    _seed(engine)

    _upgrade(engine)

    assert _externals(engine) == {
        1: ("Toyota", "RAV4"),
        2: ("Honda", "CR-V"),
        3: ("Acura", "MDX"),
        4: ("Ford", "F-150"),
    }


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_a_second_run_changes_nothing(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _seed(engine)
    _upgrade(engine)
    first = (_vehicles(engine), _externals(engine))

    _upgrade(engine)

    assert (_vehicles(engine), _externals(engine)) == first


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_a_missing_table_is_skipped(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _seed(engine, external=False)

    _upgrade(engine)

    assert _vehicles(engine)["JA3MIG15900000001"] == ("Mitsubishi", "Mirage")


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_a_failing_table_is_logged_and_the_rest_still_runs(
    engine_for_migration, caplog, caplog_only
):
    # external_vehicles without a model column: its SELECT fails inside the
    # savepoint, vehicles still commits, and nothing raises to stop the chain.
    _dialect, engine, _url = engine_for_migration
    _seed(engine, external=False)
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE external_vehicles (id INTEGER PRIMARY KEY, make VARCHAR(50))")
        )

    with caplog_only(_NAME):
        _upgrade(engine)

    assert _vehicles(engine)["JA3MIG15900000001"] == ("Mitsubishi", "Mirage")
    (logged,) = problems(caplog, _NAME)
    assert logged.getMessage() == "159: external_vehicles left as it was; the rewrite failed"
    assert logged.exc_info is not None


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_the_rewrite_rolls_back_with_the_runners_transaction(engine_for_migration):
    # Codex diff R1-M1 / Fable F-2: the runner stamps on the same transaction
    # after upgrade(). If that fails, the rewrite must go with it. On SQLite a
    # SAVEPOINT issued before any BEGIN opens its own transaction and its
    # RELEASE commits, ahead of the stamp.
    _dialect, engine, _url = engine_for_migration
    _seed(engine)

    with pytest.raises(RuntimeError, match="stamp failed"):
        with engine.begin() as conn:
            _load().upgrade(conn=conn)
            raise RuntimeError("stamp failed")

    assert _vehicles(engine)["JA3MIG15900000001"] == ("MITSUBISHI", "MIRAGE")
    assert _externals(engine)[1] == ("TOYOTA", "RAV4")
