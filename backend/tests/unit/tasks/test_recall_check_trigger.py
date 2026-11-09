"""When the scheduled recall check is registered to run.

Kept apart from `test_check_recalls_all_vehicles.py`, whose autouse fixtures
set up and wipe the database for every test, which this one never touches.
"""

from datetime import UTC

import pytest

from app.tasks import scheduled

pytestmark = pytest.mark.unit


def test_the_recall_check_is_scheduled_daily_at_2_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    """The job ticks daily and decides itself whether the interval is due.

    Pinned to UTC: the scheduler has no zone, so a local-zone cron would put
    23 or 25 hours between ticks on DST days, and the hour of slack assumes 24.
    Red on main, which registered Sunday only, in the scheduler's zone.
    """
    monkeypatch.setenv("SCHEDULER_ENABLED", "true")
    monkeypatch.setattr(scheduled.scheduler, "start", lambda *args, **kwargs: None)
    try:
        scheduled.start_scheduler()
        job = scheduled.scheduler.get_job("check_recalls_all_vehicles")
        assert job is not None
        fields = {field.name: str(field) for field in job.trigger.fields}
        assert fields["day_of_week"] == "*"
        assert fields["hour"] == "2"
        assert fields["minute"] == "0"
        assert job.trigger.timezone == UTC
    finally:
        scheduled.scheduler.remove_all_jobs()
