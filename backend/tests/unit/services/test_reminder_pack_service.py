"""Unit tests for reminder pack loading."""

import pytest

from app.services.reminder_pack_service import get_pack, list_packs


@pytest.mark.unit
class TestReminderPackService:
    def test_list_packs_includes_builtins(self):
        packs = list_packs()
        ids = {p.id for p in packs}
        assert "diy_oil_change" in ids
        assert "oil_and_filter" in ids
        assert "tire_rotation" in ids
        assert "boat_winterization" in ids

    def test_get_pack_diy_oil_change(self):
        pack = get_pack("diy_oil_change")
        assert pack.name
        assert len(pack.reminders) >= 1
        assert pack.reminders[0].title == "Oil Change"
        assert pack.reminders[0].due_date_offset_days == 180
