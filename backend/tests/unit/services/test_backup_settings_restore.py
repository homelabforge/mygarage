"""A settings restore may not reinstate a `default_unit_prefs` no reader can use.

``app/routes/settings.py`` rejects an unparseable ``default_unit_prefs`` on all
three of its write paths, and the enumeration in
``tests/integration/routes/test_settings.py`` derives that list from the router
so a fourth ROUTE cannot ship unguarded. The settings-restore path is not on
that router: ``BackupService.restore_settings_backup`` pushes every uploaded
key and value straight into ``SettingsService.set``, so a hand-edited or
pre-093 backup file was a back door onto exactly the row that validator exists
to protect.

Why it matters more than a bad row usually would: ``parse_default_unit_prefs``
degrades WHOLE and only logs, so an unreadable value silently hands every
anonymous client and every ``auth_mode=none`` client the imperial preset. On a
UK or metric instance that is about a twenty percent error in every volume,
every price per volume and every fuel economy, with nothing in any response to
say it happened.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.units import IMPERIAL_PRESET, METRIC_PRESET
from app.models.settings import Setting
from app.services.backup_service import BackupService
from app.utils.default_unit_prefs import DEFAULT_UNIT_PREFS_KEY

# The two complete sets used below. Neither is the imperial fallback a rejected
# write would silently produce, so "the row still says metric" cannot be
# satisfied by the degradation this test exists to prevent.
METRIC_RAW = json.dumps(METRIC_PRESET.model_dump(), sort_keys=True)
IMPERIAL_RAW = json.dumps(IMPERIAL_PRESET.model_dump(), sort_keys=True)

# A companion key restored in the same pass, so a skip can be told apart from a
# restore that aborted on the first bad row and left everything after it alone.
COMPANION_KEY = "__restore_guard_probe__"


def _service(tmp_path: Path) -> BackupService:
    """A service whose backup directory is this test's own tmp dir."""
    backups = tmp_path / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    return BackupService(
        backup_dir=backups,
        database_path=tmp_path / "mygarage.db",
        data_dir=tmp_path / "data",
        is_sqlite=True,
    )


def _write_backup(service: BackupService, rows: list[dict[str, object]]) -> str:
    """Write a settings backup file in the shape the exporter produces."""
    filename = "mygarage-settings-test.json"
    payload = {"version": "2.0", "type": "settings", "settings": rows}
    (service.backup_dir / filename).write_text(json.dumps(payload))
    return filename


async def _stored(db: AsyncSession, key: str) -> str | None:
    """The value currently stored under `key`, or None when there is no row."""
    row = (await db.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    return None if row is None else row.value


async def _clear(db: AsyncSession) -> None:
    """Drop this file's two rows.

    Every test in this repo shares ONE database, so a leftover row from a
    failing case makes the next case fail on a UNIQUE constraint rather than on
    its own assertion. Run before AND after, so a failure leaves nothing behind
    and inherits nothing either.
    """
    await db.execute(
        delete(Setting).where(Setting.key.in_([DEFAULT_UNIT_PREFS_KEY, COMPANION_KEY]))
    )
    await db.commit()


@pytest_asyncio.fixture(autouse=True)
async def _isolated_rows(db_session: AsyncSession):
    """Bracket each case with a clean slate, failures included."""
    await _clear(db_session)
    yield
    await _clear(db_session)


@pytest.mark.unit
@pytest.mark.asyncio
class TestSettingsRestoreValidatesDefaultUnitPrefs:
    """The restore loop applies the same rule the settings routes apply."""

    @pytest.mark.parametrize(
        "bad",
        [
            pytest.param('{"distance": "km", "volume": "L"}', id="partial"),
            pytest.param(METRIC_RAW[:-1] + ', "colour": "red"}', id="extra_key"),
            pytest.param(
                METRIC_RAW.replace('"pressure": "kpa"', '"pressure": "atm"'),
                id="out_of_vocabulary",
            ),
            pytest.param("{not json at all", id="malformed_json"),
            pytest.param("", id="empty"),
        ],
    )
    async def test_an_unusable_value_is_skipped_and_the_stored_row_survives(
        self, db_session: AsyncSession, tmp_path: Path, bad: str
    ) -> None:
        """A backup row the reader could not parse must not reach the database."""
        db_session.add(Setting(key=DEFAULT_UNIT_PREFS_KEY, value=METRIC_RAW, category="units"))
        await db_session.commit()
        # The setup write is asserted, not assumed: a silent failure here would
        # leave the assertion below comparing None against None.
        assert await _stored(db_session, DEFAULT_UNIT_PREFS_KEY) == METRIC_RAW

        service = _service(tmp_path)
        filename = _write_backup(
            service,
            [
                {"key": DEFAULT_UNIT_PREFS_KEY, "value": bad, "category": "units"},
                {"key": COMPANION_KEY, "value": "restored", "category": "general"},
            ],
        )

        details = await service.restore_settings_backup(filename, db_session, create_safety=False)

        assert await _stored(db_session, DEFAULT_UNIT_PREFS_KEY) == METRIC_RAW
        # The rest of the file still restores: one bad row is skipped, not fatal.
        assert await _stored(db_session, COMPANION_KEY) == "restored"
        assert details["restored_count"] == 1

    async def test_a_usable_value_still_restores(
        self, db_session: AsyncSession, tmp_path: Path
    ) -> None:
        """The mirror, so the guard cannot be satisfied by refusing every restore."""
        db_session.add(Setting(key=DEFAULT_UNIT_PREFS_KEY, value=METRIC_RAW, category="units"))
        await db_session.commit()
        assert await _stored(db_session, DEFAULT_UNIT_PREFS_KEY) == METRIC_RAW

        service = _service(tmp_path)
        filename = _write_backup(
            service,
            [
                {"key": DEFAULT_UNIT_PREFS_KEY, "value": IMPERIAL_RAW, "category": "units"},
                {"key": COMPANION_KEY, "value": "restored", "category": "general"},
            ],
        )

        details = await service.restore_settings_backup(filename, db_session, create_safety=False)

        assert await _stored(db_session, DEFAULT_UNIT_PREFS_KEY) == IMPERIAL_RAW
        assert details["restored_count"] == 2
