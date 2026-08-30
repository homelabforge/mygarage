"""The instance-wide default unit set, for clients with no user.

Anonymous visitors and every client on an ``auth_mode=none`` instance skip
``/auth/me`` entirely, so they have no user row to resolve units from. Before
this, they learned gallon flavour from the public ``imperial_gallon_standard``
setting; this row replaces it with a full unit set (spec D5).

Every parse failure degrades to the imperial preset rather than raising. This
value is read during frontend bootstrap, so an exception here would take the
whole app down for logged-out users on nothing worse than a hand-edited setting.
The fallback is logged at warning level so a malformed row is still visible.
"""

from __future__ import annotations

import json
import logging

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.units import IMPERIAL_PRESET, UnitSet
from app.models.settings import Setting
from app.utils.gallon_flavour import resolve_gallon_flavour

logger = logging.getLogger(__name__)

DEFAULT_UNIT_PREFS_KEY = "default_unit_prefs"

# Mirrors app/migrations/093_add_unit_preferences.py's UK_IMPERIAL_SET: same
# three overrides (volume, consumption, secondary_gallon). Duplicated rather
# than imported, because importing live application code from a one-shot
# migration script would make this module depend on migration internals that
# are frozen the moment they've run in production. The two are tied by
# tests/unit/utils/test_default_unit_prefs.py::TestUkImperialSetMatchesMigration093,
# which fails if either side moves without the other.
UK_IMPERIAL_PRESET = UnitSet.model_validate(
    IMPERIAL_PRESET.model_dump()
    | {"volume": "gal_uk", "consumption": "mpg_uk", "secondary_gallon": "uk"}
)


def parse_default_unit_prefs(raw: str | None) -> UnitSet:
    """Parse a stored default unit set, falling back to the imperial preset.

    A partial or out-of-vocabulary set falls back whole rather than being
    patched field by field: filling the gaps from the imperial preset would hand
    a metric instance imperial pressure, which is a worse outcome than an honest
    default.

    That makes the stored row's ARITY a compatibility contract, and nothing
    migrates it. A row written before a quantity was added or removed no longer
    validates, so it degrades here to IMPERIAL_PRESET whole: on a UK instance
    that is US gallons for anonymous clients and for every new account, behind
    one WARNING. `default_unit_prefs_for_instance` cannot repair it, because it
    only runs when the row is ABSENT. So any change to `UnitSet`'s shape must
    ship a migration that rewrites existing `default_unit_prefs` rows. See
    `UnitSet`'s docstring and
    `test_unit_set_shape_matches_what_stored_default_unit_prefs_rows_carry`.
    """
    if not raw:
        return IMPERIAL_PRESET
    try:
        payload = json.loads(raw)
    except ValueError, TypeError, RecursionError:
        # RecursionError (a RuntimeError subclass, not a ValueError/TypeError)
        # is reachable via deeply nested JSON: json.loads's recursive-descent
        # parser blows the interpreter's recursion limit before it can report
        # a decode error. Caught explicitly, not via a bare `except Exception`,
        # so a genuinely unexpected failure mode still surfaces.
        logger.warning("default_unit_prefs is not valid JSON; using the imperial preset")
        return IMPERIAL_PRESET
    if not isinstance(payload, dict):
        logger.warning("default_unit_prefs is not a JSON object; using the imperial preset")
        return IMPERIAL_PRESET
    try:
        return UnitSet.model_validate(payload)
    except ValidationError:
        logger.warning(
            "default_unit_prefs does not describe a complete unit set; using the imperial preset"
        )
        return IMPERIAL_PRESET


def validate_default_unit_prefs_value(raw: str | None) -> None:
    """Raise ``ValueError`` when a candidate ``default_unit_prefs`` would not parse.

    The write-side half of ``parse_default_unit_prefs``, and it exists because
    that function degrades WHOLE and only logs. On READ that is right: an
    exception during frontend bootstrap would take the whole app down for
    logged-out users on nothing worse than a hand-edited row. On WRITE it means
    an admin can store a value that silently reverts every anonymous client to
    the imperial fallback, with a 200 in the response and nothing but a warning
    in a log nobody is reading.

    Same JSON load, same ``UnitSet.model_validate``, same whole-set rule
    (``extra="forbid"`` rejects an unknown key, a missing one fails required).
    An empty value is rejected too: storing it is the same silent revert spelled
    differently.

    The message names the reason, never the submitted value, which is untrusted
    text bound for a log line and an error response.

    Args:
        raw: The candidate settings-row value.

    Raises:
        ValueError: When the value is not a complete, in-vocabulary unit set.
    """
    if not raw:
        raise ValueError("must be a JSON object describing a complete unit set")
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError, RecursionError) as exc:
        # RecursionError is a RuntimeError subclass reachable through deeply
        # nested JSON; caught for the reason parse_default_unit_prefs states.
        raise ValueError("is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("is not a JSON object")
    try:
        UnitSet.model_validate(payload)
    except ValidationError as exc:
        raise ValueError("does not describe a complete unit set") from exc


async def load_default_unit_prefs(db: AsyncSession) -> UnitSet:
    """Return the instance default unit set, or the imperial preset."""
    row = (
        await db.execute(select(Setting).where(Setting.key == DEFAULT_UNIT_PREFS_KEY))
    ).scalar_one_or_none()
    return parse_default_unit_prefs(row.value if row is not None else None)


async def default_unit_prefs_for_instance(db: AsyncSession) -> UnitSet:
    """Compute the unit set that should seed `default_unit_prefs` right now.

    Mirrors migration 093's one-shot derivation: read the live
    `imperial_gallon_standard` row via `resolve_gallon_flavour` and pick
    `UK_IMPERIAL_PRESET` or `IMPERIAL_PRESET` accordingly.

    Used by `initialize_default_settings` (`app/services/settings_init.py`) so
    a `default_unit_prefs` row deleted through the generic, admin-only
    `DELETE /api/settings/{key}` endpoint (which has no per-key protection)
    reseeds from the instance's real gallon flavour instead of a static US
    default. Migration 093 is a one-shot, stamped migration: once applied, the
    runner never reconsiders it, so it will never re-run to repair a deleted
    row. Without this derivation, a UK instance that lost this row would come
    back US on the very next boot.

    Note this derivation only runs when the row is (re)created at boot.
    Changing `imperial_gallon_standard` through the settings API afterward
    does not live-update an already-seeded `default_unit_prefs` row, because
    phase 0 deliberately removed write side effects from that route (see
    `app/utils/gallon_flavour.py`). Phase 3 retires `imperial_gallon_standard`
    entirely, which makes this moot.
    """
    flavour = await resolve_gallon_flavour(db)
    return UK_IMPERIAL_PRESET if flavour == "uk" else IMPERIAL_PRESET
