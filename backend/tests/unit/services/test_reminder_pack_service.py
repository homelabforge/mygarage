"""Unit tests for reminder pack loading."""

import json

import pytest
from fastapi import HTTPException

from app.services import reminder_pack_service
from app.services.reminder_pack_service import get_pack, list_packs


@pytest.mark.unit
class TestReminderPackService:
    def test_list_packs_includes_builtins(self):
        packs = list_packs()
        ids = {p.id for p in packs}
        assert "oil_and_filter" in ids
        assert "tire_rotation" in ids
        assert "boat_winterization" in ids
        assert "atv_utv_service" in ids
        assert "snowmobile_season" in ids
        assert "diy_oil_change" not in ids

    def test_list_packs_filters_by_vehicle_type(self):
        boat_packs = list_packs(vehicle_type="Boat")
        boat_ids = {p.id for p in boat_packs}
        assert "boat_winterization" in boat_ids
        assert "oil_and_filter" not in boat_ids

        car_packs = list_packs(vehicle_type="Car")
        car_ids = {p.id for p in car_packs}
        assert "oil_and_filter" in car_ids
        assert "boat_winterization" not in car_ids
        assert "atv_utv_service" not in car_ids

    def test_get_pack_oil_and_filter(self):
        pack = get_pack("oil_and_filter")
        assert pack.name
        assert len(pack.reminders) >= 1
        assert pack.reminders[0].title == "Oil & Filter Change"
        assert pack.reminders[0].due_date_offset_days == 180
        assert any(r.title == "Inspect Drain Plug Washer" for r in pack.reminders)
        assert "Car" in pack.vehicle_types

    def test_get_pack_rejects_path_traversal(self):
        from fastapi import HTTPException

        for pack_id in (
            "../oil_and_filter",
            "../../etc/passwd",
            "/etc/passwd",
            "oil_and_filter/../oil_and_filter",
            "foo.json\x00",
        ):
            with pytest.raises(HTTPException) as exc:
                get_pack(pack_id)
            assert exc.value.status_code == 404


@pytest.mark.unit
class TestReminderPackLookup:
    """Cover the index-based lookup, including the branch real packs never hit.

    All three shipped packs declare an id equal to their filename stem, so the
    declared-id fallback in ``get_pack`` is dead against real data. These tests
    drive it with a temp packs dir.
    """

    @staticmethod
    def _write(dirpath, filename, payload):
        (dirpath / filename).write_text(json.dumps(payload), encoding="utf-8")

    def test_finds_pack_whose_filename_differs_from_declared_id(self, tmp_path, monkeypatch):
        monkeypatch.setattr(reminder_pack_service, "PACKS_DIR", tmp_path)
        self._write(
            tmp_path,
            "renamed_file.json",
            {"id": "declared_id", "name": "Declared", "description": "d", "reminders": []},
        )

        # Filename stem misses, so the declared-id scan has to find it.
        pack = get_pack("declared_id")
        assert pack.id == "declared_id"
        assert pack.name == "Declared"

    def test_filename_hit_declaring_a_different_id_is_404(self, tmp_path, monkeypatch):
        monkeypatch.setattr(reminder_pack_service, "PACKS_DIR", tmp_path)
        self._write(
            tmp_path,
            "on_disk.json",
            {"id": "something_else", "name": "N", "description": "d", "reminders": []},
        )

        with pytest.raises(HTTPException) as exc:
            get_pack("on_disk")
        assert exc.value.status_code == 404

    def test_unreadable_filename_hit_is_500_not_404(self, tmp_path, monkeypatch):
        monkeypatch.setattr(reminder_pack_service, "PACKS_DIR", tmp_path)
        (tmp_path / "broken.json").write_text("{not valid json", encoding="utf-8")

        with pytest.raises(HTTPException) as exc:
            get_pack("broken")
        assert exc.value.status_code == 500

    def test_malformed_pack_does_not_break_list_packs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(reminder_pack_service, "PACKS_DIR", tmp_path)
        (tmp_path / "broken.json").write_text("{not valid json", encoding="utf-8")
        self._write(
            tmp_path,
            "good.json",
            {"id": "good", "name": "Good", "description": "d", "reminders": []},
        )

        assert [p.id for p in list_packs()] == ["good"]

    def test_symlink_escaping_packs_dir_is_not_loaded(self, tmp_path, monkeypatch):
        packs = tmp_path / "packs"
        packs.mkdir()
        outside = tmp_path / "outside.json"
        self._write(
            tmp_path,
            "outside.json",
            {"id": "outside", "name": "Outside", "description": "d", "reminders": []},
        )
        (packs / "escape.json").symlink_to(outside)
        monkeypatch.setattr(reminder_pack_service, "PACKS_DIR", packs)

        # resolve() follows the link before the containment check, so the
        # target lands outside PACKS_DIR and is dropped from the index.
        assert list_packs() == []
        with pytest.raises(HTTPException) as exc:
            get_pack("escape")
        assert exc.value.status_code == 404
