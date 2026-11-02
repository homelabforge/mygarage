"""Built-in packs for equipment without a VIN (#226)."""

from app.services.reminder_pack_service import builtin_pack, builtin_summaries


def test_small_engine_pack_loads_and_is_hour_based() -> None:
    pack = builtin_pack("small_engine_service")
    oil = next(item for item in pack.reminders if item.key == "engine_oil")
    assert oil.interval_hours == 50
    assert oil.interval_months == 12
    assert all(item.interval_km is None for item in pack.reminders)


def test_attachment_pack_is_time_only() -> None:
    pack = builtin_pack("attachment_grease")
    assert all(item.interval_hours is None and item.interval_km is None for item in pack.reminders)
    assert {item.interval_months for item in pack.reminders} == {3, 6}


def test_packs_are_offered_to_the_new_types_only() -> None:
    assert "small_engine_service" in {p.id for p in builtin_summaries("Tractor")}
    assert "attachment_grease" in {p.id for p in builtin_summaries("Attachment")}
    car = {p.id for p in builtin_summaries("Car")}
    assert "small_engine_service" not in car
    assert "attachment_grease" not in car
