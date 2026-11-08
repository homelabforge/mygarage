"""Tidy stored switches, drop the dead map keys and empty the token tables.

Every stored switch becomes "true" or "false" (blank stays blank), using the
live switch set and rule from ``app.services.setting_switches``. Junk text
reads as off through ``parse_bool`` already, so nobody sees a change, but the
settings tabs resend every stored value on save and a switch check on write
would otherwise refuse their own stored junk.

``google_maps_api_key``, ``geoapify_api_key`` and ``mapbox_api_key`` were
seeded by 027 and nothing has read them since the POI providers moved on.

``csrf_tokens`` and ``oidc_pending_links`` are emptied because the tokens are
now stored hashed, so the plain ones in there can never match again. Both are
short-lived: a signed-in user's next write gets a fresh CSRF token, and
someone mid-link just signs in again.

``upgrade(conn)``: the work and the stamp commit together. Not FATAL: the app
works fine with the old values.
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection, bindparam, inspect, text

from app.services.setting_switches import SWITCH_SETTING_KEYS, stored_switch_value

logger = logging.getLogger(__name__)

FATAL = False

_DEAD_MAP_KEYS = ("google_maps_api_key", "geoapify_api_key", "mapbox_api_key")
_TOKEN_TABLES = ("csrf_tokens", "oidc_pending_links")


def _tidy_switches(conn: Connection) -> int:
    """Store every switch as "true"/"false"; return how many rows changed."""
    rows = conn.execute(
        text("SELECT key, value FROM settings WHERE key IN :keys").bindparams(
            bindparam("keys", expanding=True)
        ),
        {"keys": sorted(SWITCH_SETTING_KEYS)},
    ).all()
    changed = 0
    for key, value in rows:
        tidy = stored_switch_value(key, value)
        if tidy == value:
            continue
        conn.execute(
            text("UPDATE settings SET value = :value WHERE key = :key"),
            {"value": tidy, "key": key},
        )
        changed += 1
    return changed


def _drop_map_keys(conn: Connection) -> int:
    """Delete the three map provider keys nothing reads; return how many went."""
    result = conn.execute(
        text("DELETE FROM settings WHERE key IN :keys").bindparams(
            bindparam("keys", expanding=True)
        ),
        {"keys": list(_DEAD_MAP_KEYS)},
    )
    return result.rowcount


def upgrade(conn: Connection) -> None:
    """Tidy the settings and empty the token tables, on the runner's connection."""
    present = set(inspect(conn).get_table_names())

    if "settings" in present:
        logger.info("160: %d switch setting(s) rewritten", _tidy_switches(conn))
        logger.info("160: %d dead map key(s) deleted", _drop_map_keys(conn))
    else:
        logger.info("160: settings missing; nothing to tidy")

    for table in _TOKEN_TABLES:
        if table not in present:
            logger.info("160: %s missing; nothing to clear", table)
            continue
        cleared = conn.execute(text(f"DELETE FROM {table}")).rowcount
        logger.info("160: %d %s row(s) deleted", cleared, table)


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError("Migration 160 is forward-only; the old values are not kept.")
