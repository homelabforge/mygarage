"""RenderContext resolution: the three paths are not interchangeable.

A request uses the caller's own resolved units (`render_context_for_request`,
whose user-bearing half is `render_context_for_user`), never the vehicle
owner's -- a shared viewer must see their own preferences.
A scheduled job (`render_context_for_vehicle`) has no caller, so it uses the
vehicle owner's, falling back to the instance default
(`render_context_default`) when the vehicle is ownerless or does not exist.
`auth_mode=none` uses the instance default directly.

The suite shares one database with no per-test rollback (see
`reference_mygarage_test_isolation`): every row this file writes is cleaned
up in `try/finally`, and every VIN/username is freshly generated per test.
"""

from __future__ import annotations

import json
import uuid

import pytest

from app.constants.units import IMPERIAL_PRESET, METRIC_PRESET, UnitSet
from app.models.settings import Setting
from app.models.user import User
from app.models.vehicle import Vehicle
from app.utils.default_unit_prefs import DEFAULT_UNIT_PREFS_KEY
from app.utils.render_context import (
    RenderContext,
    render_context_default,
    render_context_for_user,
    render_context_for_vehicle,
)


def _unique_vin() -> str:
    """A 17-char test VIN, unique per call to avoid fixture collisions."""
    return ("RC3" + uuid.uuid4().hex)[:17].upper()


def _unique_username() -> str:
    return f"rc3_{uuid.uuid4().hex[:16]}"


async def _seed_default_unit_prefs(db_session, unit_set: UnitSet) -> dict | None:
    """Upsert `default_unit_prefs` to `unit_set`, returning the prior row's
    fields (`None` if the row was absent) so the caller can restore it."""
    existing = await db_session.get(Setting, DEFAULT_UNIT_PREFS_KEY)
    original: dict | None = None
    if existing is not None:
        original = {"value": existing.value, "category": existing.category}
        existing.value = json.dumps(unit_set.model_dump())
    else:
        db_session.add(
            Setting(
                key=DEFAULT_UNIT_PREFS_KEY,
                value=json.dumps(unit_set.model_dump()),
                category="general",
            )
        )
    await db_session.commit()
    return original


async def _restore_default_unit_prefs(db_session, original: dict | None) -> None:
    row = await db_session.get(Setting, DEFAULT_UNIT_PREFS_KEY)
    if original is None:
        if row is not None:
            await db_session.delete(row)
            await db_session.commit()
        return
    if row is not None:
        row.value = original["value"]
        row.category = original["category"]
    else:
        db_session.add(Setting(key=DEFAULT_UNIT_PREFS_KEY, **original))
    await db_session.commit()


class TestRenderContextForUser:
    """Pure and synchronous: an unsaved `User` is enough, matching how
    `test_unit_resolution.py` exercises `resolve_units`."""

    def test_uses_the_users_own_resolved_units(self) -> None:
        user = User(
            username="rc3-unsaved-metric",
            email="rc3-unsaved-metric@example.test",
            unit_preference="metric",
            show_both_units=True,
        )
        ctx = render_context_for_user(user)
        assert ctx.units == METRIC_PRESET

    @pytest.mark.parametrize("show_both_units", [True, False])
    def test_show_both_propagates_from_the_user(self, show_both_units: bool) -> None:
        """Both states, not one sampled case: a name that generalises over a
        space its body samples once is the exact defect this project keeps
        catching (see `feedback_tests_that_assert_unexercised_properties`)."""
        user = User(
            username="rc3-unsaved-sb",
            email="rc3-unsaved-sb@example.test",
            unit_preference="imperial",
            show_both_units=show_both_units,
        )
        ctx = render_context_for_user(user)
        assert ctx.show_both is show_both_units

    def test_an_override_beats_the_preset_same_as_resolve_units(self) -> None:
        """Not a re-test of `resolve_units` itself (Task 1 owns that): this
        confirms `render_context_for_user` actually calls it rather than
        reading `unit_preference` alone."""
        user = User(
            username="rc3-unsaved-override",
            email="rc3-unsaved-override@example.test",
            unit_preference="metric",
            unit_pressure="psi",
            show_both_units=False,
        )
        ctx = render_context_for_user(user)
        assert ctx.units.pressure == "psi"
        assert ctx.units.distance == "km"


@pytest.mark.asyncio
class TestRenderContextDefault:
    async def test_reflects_a_seeded_default(self, db_session) -> None:
        original = await _seed_default_unit_prefs(db_session, METRIC_PRESET)
        try:
            ctx = await render_context_default(db_session)
            assert ctx.units == METRIC_PRESET
        finally:
            await _restore_default_unit_prefs(db_session, original)

    async def test_show_both_is_always_false(self, db_session) -> None:
        """There is no user to have opted in, regardless of what the
        default unit set itself is."""
        original = await _seed_default_unit_prefs(db_session, METRIC_PRESET)
        try:
            ctx = await render_context_default(db_session)
            assert ctx.show_both is False
        finally:
            await _restore_default_unit_prefs(db_session, original)

    async def test_absent_row_falls_back_to_imperial(self, db_session) -> None:
        original = await _seed_default_unit_prefs(db_session, METRIC_PRESET)
        try:
            await _restore_default_unit_prefs(db_session, None)  # delete the row
            ctx = await render_context_default(db_session)
            assert ctx.units == IMPERIAL_PRESET
        finally:
            await _restore_default_unit_prefs(db_session, original)


@pytest.mark.asyncio
class TestRenderContextForVehicle:
    async def test_owner_present_uses_the_owners_render_context(self, db_session) -> None:
        """The instance default is pinned to imperial for the duration of
        this test, deliberately different from the owner's metric/show-both
        set, so a mutation collapsing this path onto the default is
        distinguishable from the correct one -- not just equal by luck."""
        default_original = await _seed_default_unit_prefs(db_session, IMPERIAL_PRESET)
        username = _unique_username()
        vin = _unique_vin()
        owner = User(
            username=username,
            email=f"{username}@example.test",
            unit_preference="metric",
            show_both_units=True,
        )
        db_session.add(owner)
        await db_session.commit()
        await db_session.refresh(owner)
        vehicle = Vehicle(vin=vin, nickname="RC3 Owner Test", vehicle_type="Car", user_id=owner.id)
        db_session.add(vehicle)
        await db_session.commit()

        try:
            ctx = await render_context_for_vehicle(db_session, vin)
            assert ctx.units == METRIC_PRESET
            assert ctx.show_both is True
        finally:
            saved_vehicle = await db_session.get(Vehicle, vin)
            if saved_vehicle is not None:
                await db_session.delete(saved_vehicle)
            saved_owner = await db_session.get(User, owner.id)
            if saved_owner is not None:
                await db_session.delete(saved_owner)
            await db_session.commit()
            await _restore_default_unit_prefs(db_session, default_original)

    async def test_ownerless_vehicle_falls_back_to_the_instance_default(self, db_session) -> None:
        default_original = await _seed_default_unit_prefs(db_session, METRIC_PRESET)
        vin = _unique_vin()
        vehicle = Vehicle(vin=vin, nickname="RC3 Ownerless", vehicle_type="Car", user_id=None)
        db_session.add(vehicle)
        await db_session.commit()

        try:
            ctx = await render_context_for_vehicle(db_session, vin)
            assert ctx.units == METRIC_PRESET
            assert ctx.show_both is False
        finally:
            saved_vehicle = await db_session.get(Vehicle, vin)
            if saved_vehicle is not None:
                await db_session.delete(saved_vehicle)
            await db_session.commit()
            await _restore_default_unit_prefs(db_session, default_original)

    async def test_nonexistent_vin_falls_back_rather_than_raising(self, db_session) -> None:
        default_original = await _seed_default_unit_prefs(db_session, METRIC_PRESET)
        vin = _unique_vin()  # deliberately never inserted
        try:
            ctx = await render_context_for_vehicle(db_session, vin)
            assert ctx.units == METRIC_PRESET
            assert ctx.show_both is False
        finally:
            await _restore_default_unit_prefs(db_session, default_original)


def test_render_context_is_frozen() -> None:
    """A mutable context passed through several call layers could be
    tampered with mid-render; frozen makes that a `FrozenInstanceError`."""
    ctx = RenderContext(units=METRIC_PRESET, show_both=False)
    with pytest.raises(Exception):  # noqa: B017 -- FrozenInstanceError, dataclasses-internal
        ctx.show_both = True  # type: ignore[misc]
