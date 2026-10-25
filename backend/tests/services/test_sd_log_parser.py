import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from app.services.sd_log_parser import SdLogParser, SdLogSchemaError


def _make_db(rows, *, good_schema=True) -> bytes:
    """rows: list of (name, timestamp_epoch, value). Returns SQLite file bytes."""
    fd = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    fd.close()
    conn = sqlite3.connect(fd.name)
    if good_schema:
        conn.execute(
            "CREATE TABLE param_info (Id INTEGER PRIMARY KEY, Name VARCHAR, Type VARCHAR, Data TEXT)"
        )
        conn.execute("CREATE TABLE param_data (timestamp INTEGER, param_id INTEGER, value REAL)")
        names = {}
        for name, ts, val in rows:
            if name not in names:
                cur = conn.execute(
                    "INSERT INTO param_info (Name, Type) VALUES (?, 'NUMERIC')", (name,)
                )
                names[name] = cur.lastrowid
            conn.execute("INSERT INTO param_data VALUES (?,?,?)", (ts, names[name], val))
    else:
        conn.execute("CREATE TABLE wrong (x INTEGER)")
    conn.commit()
    conn.close()
    try:
        return Path(fd.name).read_bytes()
    finally:
        Path(fd.name).unlink(missing_ok=True)


def test_parse_yields_canonical_rows():
    db = _make_db([("0C-EngineRPM", 1781967506, 957.0)])
    rows = SdLogParser().parse(db)
    assert len(rows) == 1
    assert rows[0].param_key == "0C-ENGINERPM"  # canonicalized
    assert rows[0].value == 957.0
    assert isinstance(rows[0].timestamp, datetime)


def test_parse_drops_zero_and_pre_floor_timestamps():
    db = _make_db(
        [("0C-EngineRPM", 0, 1.0), ("0C-EngineRPM", 100, 2.0), ("0C-EngineRPM", 1781967506, 3.0)]
    )
    rows = SdLogParser().parse(db)
    assert [r.value for r in rows] == [3.0]  # only the post-2020 row


def test_parse_since_ts_filters():
    db = _make_db([("X", 1781967000, 1.0), ("X", 1781967506, 2.0)])
    rows = SdLogParser().parse(db, since_ts=1781967100)
    assert [r.value for r in rows] == [2.0]


def test_parse_drops_wican_metadata_params():
    """TS and TIMESTAMP are WiCAN frame metadata, not telemetry — must be dropped."""
    db = _make_db(
        [
            ("TS", 1781967506, 49573.0),
            ("0C-EngineRPM", 1781967506, 957.0),
            ("Timestamp", 1781967506, 1781967506.0),  # canonicalizes to TIMESTAMP
        ]
    )
    rows = SdLogParser().parse(db)
    assert [r.param_key for r in rows] == ["0C-ENGINERPM"]


def test_parse_bad_schema_raises():
    db = _make_db([], good_schema=False)
    with pytest.raises(SdLogSchemaError):
        SdLogParser().parse(db)


def test_parse_drops_nan_and_infinity():
    """A NaN binds as NULL into NOT NULL columns, and inf is no reading either.

    Live ingest has dropped both since T1; the SD path has to agree. SQLite
    keeps an Inf REAL as is, and a 'NaN' string as text that float() reads.
    """
    db = _make_db(
        [
            ("0C-EngineRPM", 1781967506, float("inf")),
            ("0C-EngineRPM", 1781967507, "NaN"),
            ("0C-EngineRPM", 1781967508, "-Infinity"),
            ("0C-EngineRPM", 1781967509, 957.0),
        ]
    )
    rows = SdLogParser().parse(db)
    assert [r.value for r in rows] == [957.0]
