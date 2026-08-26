"""The public default unit set: parsing, validation, and fallback.

This row replaces the public imperial_gallon_standard setting for anonymous and
auth_mode=none clients (spec D5). Every failure mode must degrade to the
imperial preset rather than raising: it is read during frontend bootstrap, and a
500 there takes the whole app down for logged-out users.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from app.constants.units import IMPERIAL_PRESET, METRIC_PRESET, UnitSet
from app.models.settings import Setting
from app.utils.default_unit_prefs import (
    DEFAULT_UNIT_PREFS_KEY,
    UK_IMPERIAL_PRESET,
    default_unit_prefs_for_instance,
    load_default_unit_prefs,
    parse_default_unit_prefs,
)

_MIGRATION_093 = (
    Path(__file__).resolve().parents[3] / "app" / "migrations" / "093_add_unit_preferences.py"
)


def _load_migration_093():
    """Load migration 093 by file location, as the migration tests do.

    Its module name starts with a digit, so it is not importable by name.
    """
    spec = importlib.util.spec_from_file_location("m093_tie", _MIGRATION_093)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestParsing:
    def test_parses_a_full_valid_set(self) -> None:
        raw = json.dumps(METRIC_PRESET.model_dump())
        assert parse_default_unit_prefs(raw) == METRIC_PRESET

    def test_absent_value_falls_back_to_imperial(self) -> None:
        assert parse_default_unit_prefs(None) == IMPERIAL_PRESET

    def test_empty_string_falls_back_to_imperial(self) -> None:
        assert parse_default_unit_prefs("") == IMPERIAL_PRESET

    def test_malformed_json_falls_back_to_imperial(self) -> None:
        assert parse_default_unit_prefs("{not json") == IMPERIAL_PRESET

    def test_json_that_is_not_an_object_falls_back(self) -> None:
        assert parse_default_unit_prefs("[1, 2, 3]") == IMPERIAL_PRESET

    def test_missing_field_falls_back_to_imperial(self) -> None:
        """A partial set is not a set. Filling the gaps from the imperial preset
        would hand a metric instance imperial pressure, which is worse than an
        honest fallback."""
        partial = METRIC_PRESET.model_dump()
        del partial["pressure"]
        assert parse_default_unit_prefs(json.dumps(partial)) == IMPERIAL_PRESET

    def test_out_of_vocabulary_value_falls_back_to_imperial(self) -> None:
        bad = METRIC_PRESET.model_dump()
        bad["pressure"] = "atmospheres"
        assert parse_default_unit_prefs(json.dumps(bad)) == IMPERIAL_PRESET

    def test_unknown_extra_key_falls_back_to_imperial(self) -> None:
        """An extra key means the writer and reader disagree about the shape."""
        extra = METRIC_PRESET.model_dump()
        extra["unit_pressure"] = "kpa"
        assert parse_default_unit_prefs(json.dumps(extra)) == IMPERIAL_PRESET

    def test_never_raises_on_any_input(self) -> None:
        """The docstring's contract: never raises, no matter how hostile the
        input.

        Includes deeply nested JSON, which blows the interpreter's recursion
        limit inside json.loads (RecursionError, a RuntimeError subclass, not
        a ValueError/TypeError) rather than raising anything the original
        except clause caught. Proven to catch a regression: dropping
        RecursionError from parse_default_unit_prefs's except clause makes
        this fail (captured in the task-3 report, Fix round 1)."""
        deeply_nested_array = "[" * 200_000
        deeply_nested_object = '{"a":' * 200_000 + "1" + "}" * 200_000
        for raw in (
            None,
            "",
            "null",
            "0",
            '"str"',
            "{}",
            "[]",
            "\x00",
            deeply_nested_array,
            deeply_nested_object,
        ):
            assert isinstance(parse_default_unit_prefs(raw), UnitSet)


class TestUkImperialSetMatchesMigration093:
    """The UK imperial set exists twice: `UK_IMPERIAL_PRESET` here and
    `UK_IMPERIAL_SET` in migration 093.

    The duplication is deliberate. A migration is frozen the moment it has run
    in production, so a live module must not import one, and the migration must
    not import `app.utils` (it would then track head instead of the schema it
    was written against). What was missing is the tie: the two files carried a
    "keep in sync" comment and nothing enforced it. A divergence would show up
    as a UK instance whose deleted `default_unit_prefs` row reseeds a different
    set from the one materialised into its user rows, and nothing would notice.

    (A third copy used to live in `tests/unit/utils/test_unit_resolution.py`;
    that one now imports `UK_IMPERIAL_PRESET` directly, since a test may depend
    on live application code.)
    """

    def test_the_migration_writes_the_set_this_module_reseeds(self) -> None:
        module = _load_migration_093()

        assert module.UK_IMPERIAL_SET == UK_IMPERIAL_PRESET

    def test_the_tie_compares_a_genuinely_uk_set(self) -> None:
        """If both constants drifted to the plain imperial preset together, the
        assertion above would still pass while every UK user got US gallons."""
        module = _load_migration_093()

        assert module.UK_IMPERIAL_SET != IMPERIAL_PRESET
        assert module.UK_IMPERIAL_SET.volume == "gal_uk"
        assert module.UK_IMPERIAL_SET.consumption == "mpg_uk"
        assert module.UK_IMPERIAL_SET.secondary_gallon == "uk"


@pytest.mark.asyncio
class TestLoading:
    async def test_reads_the_settings_row(self, db_session) -> None:
        """Writes and removes its own row: the suite shares one database with no
        per-test rollback."""
        db_session.add(
            Setting(
                key=DEFAULT_UNIT_PREFS_KEY,
                value=json.dumps(METRIC_PRESET.model_dump()),
                category="general",
            )
        )
        await db_session.commit()
        try:
            assert await load_default_unit_prefs(db_session) == METRIC_PRESET
        finally:
            row = await db_session.get(Setting, DEFAULT_UNIT_PREFS_KEY)
            if row is not None:
                await db_session.delete(row)
                await db_session.commit()

    async def test_absent_row_falls_back_to_imperial(self, db_session) -> None:
        """Deletes any pre-existing row to exercise the absent-row path, then
        restores exactly what it deleted: the suite shares one database with
        no per-test rollback (see reference_mygarage_test_isolation), and this
        test previously left a pre-existing row destroyed for good."""
        existing = await db_session.get(Setting, DEFAULT_UNIT_PREFS_KEY)
        original = None
        if existing is not None:
            original = {
                "value": existing.value,
                "category": existing.category,
                "description": existing.description,
                "encrypted": existing.encrypted,
            }
            await db_session.delete(existing)
            await db_session.commit()

        try:
            assert await load_default_unit_prefs(db_session) == IMPERIAL_PRESET
        finally:
            if original is not None:
                db_session.add(Setting(key=DEFAULT_UNIT_PREFS_KEY, **original))
                await db_session.commit()


@pytest.mark.asyncio
class TestPublicExposure:
    async def test_public_settings_includes_default_unit_prefs(self, client, db_session) -> None:
        """Anonymous clients must be able to read it without authenticating; that
        is the entire reason the row exists (D5).

        Seeds its own row: the `client` fixture never runs the ASGI lifespan, so
        `DEFAULT_SETTINGS` (Step 5) never gets applied to the shared test
        database. Only deletes what it added, matching TestLoading above.
        """
        existing = await db_session.get(Setting, DEFAULT_UNIT_PREFS_KEY)
        seeded = existing is None
        if seeded:
            db_session.add(
                Setting(
                    key=DEFAULT_UNIT_PREFS_KEY,
                    value=json.dumps(IMPERIAL_PRESET.model_dump()),
                    category="general",
                )
            )
            await db_session.commit()
        try:
            response = await client.get("/api/settings/public")

            assert response.status_code == 200
            keys = {s["key"] for s in response.json()["settings"]}
            assert "default_unit_prefs" in keys
        finally:
            if seeded:
                row = await db_session.get(Setting, DEFAULT_UNIT_PREFS_KEY)
                if row is not None:
                    await db_session.delete(row)
                    await db_session.commit()

    async def test_public_settings_still_includes_the_retiring_gallon_key(
        self, client, db_session
    ) -> None:
        """imperial_gallon_standard is not retired until a later phase; removing
        it now would break useGallonStandardSync.ts on the spot.

        Seeds its own row for the same reason as above.
        """
        existing = await db_session.get(Setting, "imperial_gallon_standard")
        seeded = existing is None
        if seeded:
            db_session.add(Setting(key="imperial_gallon_standard", value="us", category="general"))
            await db_session.commit()
        try:
            response = await client.get("/api/settings/public")

            keys = {s["key"] for s in response.json()["settings"]}
            assert "imperial_gallon_standard" in keys
        finally:
            if seeded:
                row = await db_session.get(Setting, "imperial_gallon_standard")
                if row is not None:
                    await db_session.delete(row)
                    await db_session.commit()


@pytest.mark.asyncio
class TestDefaultUnitPrefsForInstance:
    """The per-boot derivation used to reseed a deleted `default_unit_prefs`
    row from the instance's real gallon flavour (task-3 review, Fix 1):
    `DELETE /api/settings/{key}` has no per-key protection, and migration 093
    is a one-shot, stamped migration that never re-runs to repair a deleted
    row. See `default_unit_prefs_for_instance`'s own docstring for the
    one-shot caveat: this only runs when the row is (re)created, so it does
    not live-track later changes to `imperial_gallon_standard`.
    """

    async def test_us_or_absent_gallon_standard_derives_imperial(self, db_session) -> None:
        """Absent, empty, or non-uk `imperial_gallon_standard` all derive the
        plain imperial preset, matching migration 093's own default.

        All four states the name covers, not just the absent one:
        `resolve_gallon_flavour` treats everything that is not a
        case-insensitive "uk" as US, and a name that generalises over a space
        its body samples once is the defect this phase keeps catching.

        Restores whatever it found in `try/finally`. The suite shares one
        database with no per-test rollback (see reference_mygarage_test_isolation)
        and this test used to leave `imperial_gallon_standard` deleted for the
        rest of the session.
        """
        existing = await db_session.get(Setting, "imperial_gallon_standard")
        existed = existing is not None
        original = existing.value if existing is not None else None

        async def write(value: str | None) -> None:
            """Set the row's value, or remove the row entirely when None."""
            row = await db_session.get(Setting, "imperial_gallon_standard")
            if value is None:
                if row is not None:
                    await db_session.delete(row)
            elif row is not None:
                row.value = value
            else:
                db_session.add(
                    Setting(key="imperial_gallon_standard", value=value, category="general")
                )
            await db_session.commit()

        try:
            for value in (None, "", "us", "not-a-flavour"):
                await write(value)

                result = await default_unit_prefs_for_instance(db_session)

                assert result == IMPERIAL_PRESET, repr(value)
                assert result != UK_IMPERIAL_PRESET, repr(value)
        finally:
            row = await db_session.get(Setting, "imperial_gallon_standard")
            if not existed:
                if row is not None:
                    await db_session.delete(row)
            elif row is not None:
                row.value = original
            else:
                db_session.add(
                    Setting(key="imperial_gallon_standard", value=original, category="general")
                )
            await db_session.commit()

    async def test_uk_gallon_standard_derives_uk_imperial(self, db_session) -> None:
        """A UK instance derives the UK-flavoured preset (gal_uk/mpg_uk/uk),
        not the plain (US) imperial preset."""
        existing = await db_session.get(Setting, "imperial_gallon_standard")
        original = existing.value if existing is not None else None
        if existing is None:
            db_session.add(Setting(key="imperial_gallon_standard", value="uk", category="general"))
        else:
            existing.value = "uk"
        await db_session.commit()

        try:
            result = await default_unit_prefs_for_instance(db_session)
            assert result == UK_IMPERIAL_PRESET
            # Both sides of that equality are the same constant, so it only
            # proves the uk branch was taken if the constant really is UK.
            assert result != IMPERIAL_PRESET
            assert result.volume == "gal_uk"
            assert result.consumption == "mpg_uk"
            assert result.secondary_gallon == "uk"
        finally:
            row = await db_session.get(Setting, "imperial_gallon_standard")
            if original is None:
                if row is not None:
                    await db_session.delete(row)
            elif row is not None:
                row.value = original
            else:
                db_session.add(Setting(key="imperial_gallon_standard", value=original))
            await db_session.commit()
