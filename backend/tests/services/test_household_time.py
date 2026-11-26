"""Zone resolution precedence and fallback for the household clock."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.utils import zone_resolve
from app.utils.household_time import (
    household_today,
    household_zone,
    household_zone_var,
    resolve_zone,
)

FROZEN_UTC = datetime(2026, 9, 17, 2, 0, tzinfo=UTC)


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: D102 - datetime API
        return FROZEN_UTC.astimezone(tz) if tz else FROZEN_UTC.replace(tzinfo=None)


@pytest.fixture
def frozen_clock(monkeypatch):
    monkeypatch.setattr("app.utils.household_time.datetime", _FrozenDatetime)


@pytest.fixture
def no_env(monkeypatch):
    monkeypatch.delenv("MYGARAGE_TIMEZONE", raising=False)


class TestResolveZone:
    def test_valid_row_wins_over_everything(self, monkeypatch, no_env):
        monkeypatch.setenv("MYGARAGE_TIMEZONE", "America/Denver")
        assert resolve_zone("America/Chicago") == ZoneInfo("America/Chicago")

    @pytest.mark.parametrize("row", [None, "", "Not/AZone"])
    def test_bad_row_falls_to_env(self, monkeypatch, row):
        monkeypatch.setenv("MYGARAGE_TIMEZONE", "America/Denver")
        assert resolve_zone(row) == ZoneInfo("America/Denver")

    @pytest.mark.parametrize("env", ["", "Also/Bogus"])
    def test_bad_env_falls_to_container_zone(self, monkeypatch, env):
        monkeypatch.setenv("MYGARAGE_TIMEZONE", env)
        monkeypatch.setattr(zone_resolve.tzlocal, "get_localzone_name", lambda: "Pacific/Auckland")
        assert resolve_zone(None) == ZoneInfo("Pacific/Auckland")

    def test_unresolvable_container_zone_falls_to_utc(self, monkeypatch, no_env):
        def boom():
            raise RuntimeError("no zone")

        monkeypatch.setattr(zone_resolve.tzlocal, "get_localzone_name", boom)
        assert resolve_zone(None) == ZoneInfo("UTC")

    def test_invalid_value_warns_once_per_distinct_value(self, monkeypatch, no_env, caplog):
        monkeypatch.setattr(zone_resolve.tzlocal, "get_localzone_name", lambda: "UTC")
        with caplog.at_level(logging.WARNING, logger="app.utils.zone_resolve"):
            resolve_zone("Not/AZone")
            resolve_zone("Not/AZone")
            resolve_zone("Other/Bogus")
        warnings = [r for r in caplog.records if "Ignoring invalid timezone" in r.getMessage()]
        assert len(warnings) == 2


class TestHouseholdToday:
    def test_uses_the_loaded_zone(self, frozen_clock):
        household_zone_var.set(ZoneInfo("America/Chicago"))
        assert household_today() == date(2026, 9, 16)
        household_zone_var.set(ZoneInfo("UTC"))
        assert household_today() == date(2026, 9, 17)

    def test_unloaded_context_falls_back_to_the_chain(self, frozen_clock, monkeypatch, no_env):
        household_zone_var.set(None)
        monkeypatch.setattr(zone_resolve.tzlocal, "get_localzone_name", lambda: "America/Denver")
        assert household_zone() == ZoneInfo("America/Denver")
        assert household_today() == date(2026, 9, 16)
