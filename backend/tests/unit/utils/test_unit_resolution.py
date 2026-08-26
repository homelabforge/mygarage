"""Unit resolution: preset base, override precedence, and new-user seeding.

D3: unit_preference is the BASE; any non-null override column beats it,
regardless of preset. `custom` is a UI affordance meaning "show me the ten
selects", not a distinct resolution mode.
"""

from __future__ import annotations

import inspect as inspect_module

import pytest

from app.constants.units import (
    IMPERIAL_PRESET,
    METRIC_PRESET,
    UNIT_FIELD_NAMES,
    UnitSet,
    field_to_column,
)
from app.models.user import User
from app.utils.default_unit_prefs import UK_IMPERIAL_PRESET
from app.utils.unit_resolution import (
    base_preset_for,
    initial_unit_columns,
    resolve_units,
)


def _user(**kwargs) -> User:
    """An unsaved User carrying only the fields resolution reads."""
    return User(username="u", email="u@example.test", **kwargs)


def _user_response_payload(**overrides) -> dict:
    """The minimum required fields for a `UserResponse`, plus overrides."""
    from datetime import datetime

    return {
        "id": 1,
        "username": "usr",
        "email": "u@example.com",
        "is_active": True,
        "is_admin": False,
        "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 1),
        "last_login": None,
    } | overrides


class TestBasePreset:
    def test_metric_preference_uses_the_metric_preset(self) -> None:
        assert base_preset_for("metric") == METRIC_PRESET

    def test_imperial_preference_uses_the_imperial_preset(self) -> None:
        """This alone cannot prove `"imperial"` is a real `_PRESETS` key rather
        than just falling through to the same-valued fallback default: removing
        the key from `_PRESETS` leaves this assertion passing, because
        `base_preset_for`'s output is unchanged either way. What does catch that
        regression is `TestNewUserSeeding.
        test_a_default_matching_a_preset_stores_the_preset_with_null_overrides`,
        which asserts `initial_unit_columns(IMPERIAL_PRESET)` reports the name
        `"imperial"` and needs a genuine `_PRESETS` entry to find it."""
        assert base_preset_for("imperial") == IMPERIAL_PRESET

    def test_custom_falls_back_to_imperial_when_nothing_is_materialised(self) -> None:
        """custom is expected to arrive fully materialised, so the base is only
        reached defensively. Imperial keeps that case identical to today's
        default rather than silently flipping a user to metric."""
        assert base_preset_for("custom") == IMPERIAL_PRESET

    def test_unknown_and_null_preferences_fall_back_to_imperial(self) -> None:
        for value in (None, "", "klingon"):
            assert base_preset_for(value) == IMPERIAL_PRESET


class TestResolution:
    def test_no_overrides_resolves_to_the_preset(self) -> None:
        assert resolve_units(_user(unit_preference="metric")) == METRIC_PRESET
        assert resolve_units(_user(unit_preference="imperial")) == IMPERIAL_PRESET

    def test_a_single_override_beats_the_preset(self) -> None:
        """The reported bug (#152) in one assertion: a metric user who wants PSI."""
        user = _user(unit_preference="metric", unit_pressure="psi")

        resolved = resolve_units(user)

        assert resolved.pressure == "psi"
        assert resolved.distance == "km"  # everything else stays on the preset

    def test_overrides_win_under_every_preset_including_imperial(self) -> None:
        """D3 explicitly rejects the v1 draft where overrides applied only under
        `custom`, which made the UK backfill a no-op against its own preset."""
        user = _user(unit_preference="imperial", unit_distance="km")

        assert resolve_units(user).distance == "km"

    def test_a_fully_materialised_custom_user_resolves_to_its_columns(self) -> None:
        columns = {field_to_column(f): v for f, v in METRIC_PRESET.model_dump().items()}
        user = _user(unit_preference="custom", **columns)

        assert resolve_units(user) == METRIC_PRESET

    def test_every_field_is_independently_overridable(self) -> None:
        """A field the resolver forgot to copy would silently keep its preset
        value. Exercise all ten differing fields, not a representative sample."""
        differing = [
            field
            for field in UNIT_FIELD_NAMES
            if getattr(IMPERIAL_PRESET, field) != getattr(METRIC_PRESET, field)
        ]
        # Without this the loop could silently iterate zero times and pass.
        assert len(differing) == 10, differing

        for field in differing:
            want = getattr(METRIC_PRESET, field)
            user = _user(unit_preference="imperial", **{field_to_column(field): want})

            assert getattr(resolve_units(user), field) == want, field

    def test_secondary_gallon_is_overridable_even_though_presets_agree(self) -> None:
        """D4b: this is the field the UK migration moves for metric users, and
        both presets say 'us', so the loop above cannot cover it."""
        user = _user(unit_preference="metric", secondary_gallon="uk")

        assert resolve_units(user).secondary_gallon == "uk"

    def test_an_out_of_vocabulary_override_is_ignored(self) -> None:
        """The columns have no DB CHECK. A hand-edited value must not produce an
        invalid UnitSet that every downstream formatter then has to defend against."""
        user = _user(unit_preference="metric", unit_pressure="atmospheres")

        assert resolve_units(user).pressure == "kpa"

    def test_an_invalid_override_does_not_discard_a_valid_override(self) -> None:
        """The test above sets only the bad field, so it cannot tell "discard
        just the bad field" apart from "discard every override the moment any
        field is invalid": with nothing else overridden, both behaviors produce
        the same output. This test combines a VALID override (one that differs
        from the preset, so a silent discard is visible) with an invalid one on
        the same user."""
        user = _user(
            unit_preference="imperial",
            unit_distance="km",  # valid, and differs from the imperial preset ("mi")
            unit_pressure="atmospheres",  # invalid: not in PressureUnit's vocabulary
        )

        resolved = resolve_units(user)

        assert resolved.distance == "km"  # the valid override must survive
        assert resolved.pressure == "psi"  # only the invalid one falls back

    def test_two_valid_overrides_survive_one_invalid_override(self) -> None:
        """Complements the test above: with only one surviving override, a
        fallback loop that happens to apply the valid field before the invalid
        one could look correct by accident. Two surviving fields make that
        coincidence far less likely regardless of UNIT_FIELD_NAMES's order."""
        user = _user(
            unit_preference="imperial",
            unit_distance="km",
            unit_speed="kmh",
            unit_pressure="atmospheres",
        )

        resolved = resolve_units(user)

        assert resolved.distance == "km"
        assert resolved.speed == "kmh"
        assert resolved.pressure == "psi"


class TestPurity:
    def test_resolve_units_is_not_a_coroutine(self) -> None:
        """A Pydantic computed field cannot await. If resolution ever needs the
        database, the computed field on UserResponse has to go with it."""
        assert not inspect_module.iscoroutinefunction(resolve_units)

    def test_resolve_units_takes_only_the_user(self) -> None:
        params = list(inspect_module.signature(resolve_units).parameters)
        assert params == ["user"]


class TestNewUserSeeding:
    def test_a_default_matching_a_preset_stores_the_preset_with_null_overrides(
        self,
    ) -> None:
        """Ordinary instances stay on clean presets rather than making every
        account a custom one (spec Phase 1)."""
        columns = initial_unit_columns(IMPERIAL_PRESET)

        assert columns["unit_preference"] == "imperial"
        assert all(columns[field_to_column(f)] is None for f in UNIT_FIELD_NAMES)

    def test_a_metric_default_stores_the_metric_preset(self) -> None:
        columns = initial_unit_columns(METRIC_PRESET)

        assert columns["unit_preference"] == "metric"
        assert all(columns[field_to_column(f)] is None for f in UNIT_FIELD_NAMES)

    def test_a_non_preset_default_materialises_all_eleven_as_custom(self) -> None:
        """A UK instance's default matches neither preset, so a new account must
        carry every field explicitly or it silently gets US gallons: the same
        class of bug this whole change exists to fix."""
        uk = UK_IMPERIAL_PRESET

        columns = initial_unit_columns(uk)

        assert columns["unit_preference"] == "custom"
        assert columns["unit_volume"] == "gal_uk"
        assert columns["unit_consumption"] == "mpg_uk"
        assert columns["secondary_gallon"] == "uk"
        assert all(columns[field_to_column(f)] is not None for f in UNIT_FIELD_NAMES)

    @pytest.mark.parametrize("preset", [IMPERIAL_PRESET, METRIC_PRESET])
    def test_seeding_round_trips_through_resolution(self, preset: UnitSet) -> None:
        """Whatever seeding writes must resolve back to the default it came from."""
        columns = initial_unit_columns(preset)

        assert resolve_units(_user(**columns)) == preset

    def test_non_preset_seeding_round_trips_through_resolution(self) -> None:
        uk = UK_IMPERIAL_PRESET

        assert resolve_units(_user(**initial_unit_columns(uk))) == uk


class TestEveryCreationPathSeeds:
    """A creation path that builds a User without the seeding helper silently
    gives new accounts US gallons on a UK instance."""

    def test_all_known_user_construction_sites_use_the_helper(self) -> None:
        import ast
        from pathlib import Path

        backend = Path(__file__).parent.parent.parent.parent
        sources = [
            backend / "app" / "routes" / "auth.py",
            backend / "app" / "services" / "oidc" / "users.py",
        ]

        offenders: list[str] = []
        for path in sources:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                    continue
                if node.func.id != "User":
                    continue
                starred = {
                    kw.value.id
                    for kw in node.keywords
                    if kw.arg is None and isinstance(kw.value, ast.Name)
                }
                if "unit_kwargs" not in starred:
                    offenders.append(f"{path.name}:{node.lineno}")

        assert offenders == [], (
            f"User(...) built without **unit_kwargs at {offenders}. "
            "Call new_user_unit_kwargs(db) and splat it in."
        )

    def test_the_guard_sees_the_call_sites_it_claims_to_check(self) -> None:
        """A path typo would make the guard above scan nothing and pass. Assert
        it actually found User(...) constructions."""
        import ast
        from pathlib import Path

        backend = Path(__file__).parent.parent.parent.parent
        found = 0
        for name in (
            backend / "app" / "routes" / "auth.py",
            backend / "app" / "services" / "oidc" / "users.py",
        ):
            assert name.exists(), name
            tree = ast.parse(name.read_text(encoding="utf-8"))
            found += sum(
                1
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "User"
            )
        assert found == 3, f"expected 3 User(...) construction sites, found {found}"


class TestUserResponseSerialisation:
    """UserResponse carries both the raw columns and the resolved set, so the
    settings UI can show what is stored and the app can format with what applies."""

    def test_response_exposes_all_eleven_raw_columns(self) -> None:
        from app.constants.units import UNIT_COLUMN_NAMES
        from app.schemas.user import UserResponse

        assert set(UNIT_COLUMN_NAMES) <= set(UserResponse.model_fields) | set(
            UserResponse.model_computed_fields
        )

    def test_resolved_units_is_computed_from_the_raw_columns(self) -> None:
        from datetime import datetime

        from app.schemas.user import UserResponse

        response = UserResponse(
            id=1,
            username="usr",
            email="u@example.com",
            is_active=True,
            is_admin=False,
            unit_preference="metric",
            unit_pressure="psi",
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
            last_login=None,
        )

        assert response.resolved_units.pressure == "psi"
        assert response.resolved_units.distance == "km"

    def test_resolved_units_appears_in_the_serialised_payload(self) -> None:
        """A computed field that is not serialised is invisible to the frontend,
        which is the only consumer that matters here."""
        from datetime import datetime

        from app.schemas.user import UserResponse

        payload = UserResponse(
            id=1,
            username="usr",
            email="u@example.com",
            is_active=True,
            is_admin=False,
            unit_preference="custom",
            unit_volume="gal_uk",
            secondary_gallon="uk",
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
            last_login=None,
        ).model_dump()

        assert payload["resolved_units"]["volume"] == "gal_uk"
        assert payload["resolved_units"]["secondary_gallon"] == "uk"
        assert payload["unit_volume"] == "gal_uk"

    def test_unit_preference_accepts_custom(self) -> None:
        """Migration 093 writes 'custom'; a response schema that rejects it would
        500 every UK user's /auth/me.

        Constructs and serialises, not just introspects the Literal: a
        field_validator rejecting 'custom' at runtime while leaving it in the
        Literal would pass a type-only check but 500 the real response."""
        from datetime import datetime

        from app.schemas.user import UserResponse

        assert "custom" in UserResponse.model_fields["unit_preference"].annotation.__args__

        response = UserResponse(
            id=1,
            username="usr",
            email="u@example.com",
            is_active=True,
            is_admin=False,
            unit_preference="custom",
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
            last_login=None,
        )

        assert response.unit_preference == "custom"
        assert response.model_dump()["unit_preference"] == "custom"

    def test_every_raw_unit_column_reads_as_no_override_when_out_of_vocabulary(self) -> None:
        """A hand-edited column degrades instead of 500ing /auth/me.

        `resolve_units` was built to tolerate an out-of-vocabulary column
        (TestResolution above), but `UserResponse` types the same columns as
        strict `Literal`s, so without the before-validator the response raises
        before resolution ever runs and FastAPI turns that into a 500 on
        /auth/me, the login payload and the admin user list.

        All eleven columns, not a sample: the validator is registered by field
        name, so a name left out of the list is invisible to any single-field
        check.
        """
        from app.constants.units import UNIT_COLUMN_NAMES
        from app.schemas.user import UserResponse

        for column in UNIT_COLUMN_NAMES:
            response = UserResponse.model_validate(
                _user_response_payload(unit_preference="metric") | {column: "atmospheres"}
            )

            assert getattr(response, column) is None, column
            assert response.resolved_units == METRIC_PRESET, column

    def test_a_bad_column_keeps_the_preset_value_and_a_valid_sibling_override(self) -> None:
        """The API path degrades the way resolve_units does: field by field.

        The loop above sets one bad column at a time, so it cannot tell
        "discard just the bad field" apart from "discard every override". This
        pairs a valid override that differs from the preset with an invalid one
        on the same response.
        """
        from app.schemas.user import UserResponse

        response = UserResponse.model_validate(
            _user_response_payload(unit_preference="imperial")
            | {"unit_distance": "km", "unit_pressure": "atmospheres"}
        )

        assert response.unit_distance == "km"
        assert response.unit_pressure is None
        assert response.resolved_units.distance == "km"
        assert response.resolved_units.pressure == "psi"

    def test_a_valid_raw_column_still_survives_the_validator(self) -> None:
        """The coercion must not swallow legitimate values: a validator that
        returned None unconditionally would pass both tests above."""
        from app.schemas.user import UserResponse

        response = UserResponse.model_validate(
            _user_response_payload(unit_preference="metric") | {"unit_pressure": "psi"}
        )

        assert response.unit_pressure == "psi"
        assert response.resolved_units.pressure == "psi"

    def test_write_schemas_still_reject_custom(self) -> None:
        """Ruling P1: the dedicated unit mutation arrives in phase 4, and until it
        does, a generic setter that can write 'custom' without materialising the
        eleven columns is the back door D9b exists to close."""
        import pytest as _pytest
        from pydantic import ValidationError

        from app.schemas.user import AdminUserUpdate, UserSelfUpdate

        for schema in (UserSelfUpdate, AdminUserUpdate):
            with _pytest.raises(ValidationError):
                schema(unit_preference="custom")

    def test_out_of_vocabulary_unit_preference_reads_as_imperial(self) -> None:
        """The twelfth field needs the same defence-in-depth as the eleven raw
        unit columns above: `unit_preference` sits over an unconstrained
        `String(20)` column with no database CHECK, so a hand-edited row can
        hold anything. Unlike the eleven, it has no `None` "no override" state
        to fall back to, so the correct degrade target is what
        `base_preset_for` already does for a half-written row: imperial, not a
        raise. Without the fix this construction raises `ValidationError`,
        which is a 500 on `/auth/me` and an account that cannot load the app.
        """
        from app.schemas.user import UserResponse

        response = UserResponse.model_validate(_user_response_payload(unit_preference="Imperial"))

        assert response.unit_preference == "imperial"
        assert response.resolved_units == IMPERIAL_PRESET
