"""Parse a WiCAN SD-card OBD log (SQLite) into canonical telemetry rows."""

from __future__ import annotations

import logging
import math
import sqlite3
import tempfile
from datetime import UTC, datetime
from typing import NamedTuple

from app.utils.autopid_normalizer import canonical_param_key, is_telemetry_param

logger = logging.getLogger(__name__)


class SdRow(NamedTuple):
    param_key: str
    value: float
    timestamp: datetime


TS_FLOOR = 1577836800  # 2020-01-01; rows at/below are pre-RTC-sync garbage


class SdLogSchemaError(Exception):
    """The log DB does not have the expected param_info/param_data schema."""


_QUERY = (
    "SELECT i.Name, d.timestamp, d.value FROM param_data d "
    "JOIN param_info i ON i.Id = d.param_id "
    "WHERE d.timestamp > ? ORDER BY d.timestamp"
)
_QUERY_NOINDEX = _QUERY.replace("param_data d ", "param_data d NOT INDEXED ")


class SdLogParser:
    """Turns SD log bytes into canonical (param_key, value, timestamp) rows."""

    def parse(self, db_bytes: bytes, since_ts: int = 0) -> list[SdRow]:
        """Parse SD-log bytes into canonical SdRows, dropping rows at/below max(since_ts, TS_FLOOR). Raises SdLogSchemaError if the param_info/param_data schema is absent."""
        floor = max(since_ts, TS_FLOOR)
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            tmp.write(db_bytes)
            tmp.flush()
            conn = sqlite3.connect(f"file:{tmp.name}?mode=ro", uri=True)
            try:
                self._assert_schema(conn)
                try:
                    cur = conn.execute(_QUERY, (floor,))
                    raw = cur.fetchall()
                except sqlite3.DatabaseError:
                    logger.warning("SD log index corrupt; retrying NOT INDEXED")
                    raw = conn.execute(_QUERY_NOINDEX, (floor,)).fetchall()
            finally:
                conn.close()
        rows: list[SdRow] = []
        for name, ts, value in raw:
            if name is None or value is None:
                continue
            param_key = canonical_param_key(name)
            if not is_telemetry_param(param_key):
                continue  # drop WiCAN frame-metadata (TS, TIMESTAMP); not telemetry
            number = float(value)
            if not math.isfinite(number):
                continue  # live ingest drops these too; a NaN can't be stored
            rows.append(SdRow(param_key, number, datetime.fromtimestamp(ts, UTC)))
        return rows

    @staticmethod
    def _assert_schema(conn: sqlite3.Connection) -> None:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"param_info", "param_data"} <= tables:
            raise SdLogSchemaError(f"missing param_info/param_data (have {sorted(tables)})")
