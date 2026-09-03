"""The admin view of reconstruction runs.

The tool's audit rows are only useful if something reads them back. Without a
route they are a table nobody can see, and the run record's entire justification
-- that a log rotates and a container restart loses it -- would be defeated by
storing the answer somewhere equally unreachable.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_reconstruction_run import LiveLinkReconstructionRun
from app.routes.livelink_admin import list_reconstruction_runs

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 9, 1, 8, 0, 0)


async def _add_run(db: AsyncSession, **kwargs) -> LiveLinkReconstructionRun:
    fields = {
        "started_at": T0,
        "finished_at": T0,
        "dry_run": True,
        "gap_minutes": 15,
        "boundary_version": 1,
    }
    fields.update(kwargs)
    run = LiveLinkReconstructionRun(**fields)
    db.add(run)
    await db.flush()
    return run


class TestListReconstructionRuns:
    async def test_it_returns_the_counts(self, db_session: AsyncSession):
        await _add_run(db_session, sessions_closed=42, sessions_created=3, sessions_split=3)

        result = await list_reconstruction_runs(limit=20, db=db_session, current_user=None)

        assert result.total >= 1
        newest = result.runs[0]
        assert newest.sessions_closed == 42
        assert newest.sessions_created == 3

    async def test_it_parses_the_refusals(self, db_session: AsyncSession):
        """Stored as JSON text so the shape is identical on both dialects; this
        is the one place it is read back, so it is the one place a malformed
        payload could surface."""
        await _add_run(
            db_session,
            sessions_refused=2,
            refusals=json.dumps(
                [
                    {"session_id": 11, "reason": "no_telemetry"},
                    {"session_id": 12, "reason": "outside_retention_horizon"},
                ]
            ),
        )

        result = await list_reconstruction_runs(limit=20, db=db_session, current_user=None)

        refusals = result.runs[0].refusals
        assert [r.session_id for r in refusals] == [11, 12]
        assert refusals[1].reason == "outside_retention_horizon"

    async def test_a_malformed_payload_does_not_take_the_page_down(self, db_session: AsyncSession):
        """The counts are the part an admin acts on, and they are still readable.

        Failing the whole request instead would mean one bad row hides every
        other run, including the ones that explain what happened to their data.
        """
        await _add_run(db_session, sessions_refused=1, refusals="{not json at all")

        result = await list_reconstruction_runs(limit=20, db=db_session, current_user=None)

        assert result.runs[0].sessions_refused == 1
        assert result.runs[0].refusals == []

    async def test_runs_are_newest_first(self, db_session: AsyncSession):
        from datetime import timedelta

        await _add_run(db_session, started_at=T0, gap_minutes=5)
        await _add_run(db_session, started_at=T0 + timedelta(hours=2), gap_minutes=25)

        result = await list_reconstruction_runs(limit=20, db=db_session, current_user=None)

        assert result.runs[0].gap_minutes == 25, "an admin wants the last run first"

    async def test_the_dry_run_flag_survives_the_round_trip(self, db_session: AsyncSession):
        """Telling a preview from a real run is the whole point of the record."""
        await _add_run(db_session, dry_run=False, sessions_closed=7)

        result = await list_reconstruction_runs(limit=20, db=db_session, current_user=None)

        assert result.runs[0].dry_run is False
