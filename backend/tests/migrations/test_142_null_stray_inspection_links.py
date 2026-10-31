"""Migration 142: a repair's link only names an inspection on its own visit (S1d-04, D1).

Built on the real model schema, so the FK and the column types are the ones a
migrated database has.
"""

import importlib
import importlib.util
import logging
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine, MetaData, create_engine, text
from sqlalchemy.orm import Session

import app.migrations as _m
from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.models.vehicle import Vehicle

pytestmark = pytest.mark.migrations

_NAME = "142_null_stray_inspection_links"
_VIN = "B10MIG14200000001"


def _load():
    """Load the migration module by file, as the runner does."""
    path = Path(_m.__file__).parent / f"{_NAME}.py"
    spec = importlib.util.spec_from_file_location(_NAME, path)
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


def _seed(engine: Engine) -> dict[str, int]:
    """Two visits. Visit A has an inspection and four repairs, one link of each kind."""
    _metadata().create_all(engine)
    with Session(engine) as s:
        s.add(Vehicle(vin=_VIN, nickname="142", vehicle_type="Car"))
        s.flush()
        a = ServiceVisit(vin=_VIN, date=date(2026, 3, 1))
        b = ServiceVisit(vin=_VIN, date=date(2026, 3, 2))
        s.add_all([a, b])
        s.flush()
        insp = ServiceLineItem(visit_id=a.id, description="Brake inspection", is_inspection=True)
        wipers = ServiceLineItem(visit_id=a.id, description="Wipers")
        other_insp = ServiceLineItem(
            visit_id=b.id, description="Tire inspection", is_inspection=True
        )
        s.add_all([insp, wipers, other_insp])
        s.flush()
        good = ServiceLineItem(
            visit_id=a.id, description="Pads", triggered_by_inspection_id=insp.id
        )
        to_plain = ServiceLineItem(
            visit_id=a.id, description="Rotors", triggered_by_inspection_id=wipers.id
        )
        cross = ServiceLineItem(
            visit_id=a.id, description="Tires", triggered_by_inspection_id=other_insp.id
        )
        s.add_all([good, to_plain, cross])
        s.flush()
        # An inspection pointing at itself still counts as stray.
        self_link = ServiceLineItem(visit_id=a.id, description="Fluids", is_inspection=True)
        s.add(self_link)
        s.flush()
        self_link.triggered_by_inspection_id = self_link.id
        ids = {
            "insp": insp.id,
            "wipers": wipers.id,
            "other_insp": other_insp.id,
            "good": good.id,
            "to_plain": to_plain.id,
            "cross": cross.id,
            "self": self_link.id,
        }
        s.commit()
    return ids


def _links(engine: Engine) -> dict[int, int | None]:
    with engine.connect() as conn:
        return dict(
            conn.execute(
                text("SELECT id, triggered_by_inspection_id FROM service_line_items")
            ).all()
        )


def _upgrade(engine: Engine) -> None:
    """Run it the way the runner does: on one connection, in one transaction."""
    with engine.begin() as conn:
        _load().upgrade(conn=conn)


def test_the_migration_is_not_fatal():
    # guard: a failed 142 leaves the stray links, which the API drops on the
    # next save anyway, so the app can boot without it.
    assert not getattr(_load(), "FATAL", False)


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_stray_links_clear_and_a_link_to_this_visits_inspection_stays(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    ids = _seed(engine)

    _upgrade(engine)

    # main: FileNotFoundError, no migration 142
    assert _links(engine) == {
        ids["insp"]: None,
        ids["wipers"]: None,
        ids["other_insp"]: None,
        ids["good"]: ids["insp"],
        ids["to_plain"]: None,
        ids["cross"]: None,
        ids["self"]: None,
    }


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_a_second_run_changes_nothing(engine_for_migration, caplog: pytest.LogCaptureFixture):
    _dialect, engine, _url = engine_for_migration
    _seed(engine)
    _upgrade(engine)
    before = _links(engine)
    caplog.set_level(logging.INFO)

    _upgrade(engine)

    assert _links(engine) == before
    assert "142: cleared 0 stray inspection link(s)" in caplog.text


def test_a_missing_table_is_skipped(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    engine = create_engine("sqlite://")
    _upgrade(engine)
    assert "142: service_line_items missing" in caplog.text


def test_the_runner_takes_the_atomic_path(tmp_path: Path) -> None:
    # guard: kills an upgrade(engine) 142, which the runner would stamp in a
    # second transaction after the UPDATE committed.
    from app.migrations.runner import MigrationRunner

    runner = MigrationRunner(f"sqlite:///{tmp_path / 'r.db'}", Path(_m.__file__).parent)
    try:
        assert runner._takes_conn(_load())
    finally:
        runner.engine.dispose()
