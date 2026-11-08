"""Nothing in the app writes the settings table around the model.

`Setting.value` is where secrets get encrypted. A Core `insert()` or `update()`,
the bare table, a bulk mapping write, or raw SQL writes the column as given, so
a secret would land in plaintext and sit there until the next start's sweep.
Migrations are left out: they run before the model exists and the sweep is
their backstop. Tests seed raw rows on purpose and aren't scanned. A
`delete(Setting)` is fine, it stores nothing.

Each file is searched as a whole, so a call split over lines or SQL split
over string literals is still caught.
"""

import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
SCANNED = (BACKEND / "app", BACKEND / "tools")
SKIPPED = BACKEND / "app" / "migrations"

# Between SQL words: whitespace, or the quotes of literals glued together.
_GAP = r"[\s\"']+"

PATTERNS = (
    # insert(Setting), pg_insert(Setting), sqlite_insert(Setting) and the like.
    re.compile(r"insert\(\s*Setting\b"),
    re.compile(r"update\(\s*Setting\b"),
    re.compile(r"bulk_(insert|update)_mappings\(\s*Setting\b"),
    re.compile(r"\bSetting\.__table__"),
    # The table looked up by name, as the tools do for other tables.
    re.compile(r"metadata\.tables(\[|\.get\()\s*(Setting\.__tablename__|[\"']settings[\"'])"),
    re.compile(r"\btable\(\s*[\"']settings[\"']"),
    re.compile(rf"\bINSERT{_GAP}(OR{_GAP}\w+{_GAP})?INTO{_GAP}settings\b", re.IGNORECASE),
    re.compile(rf"\bUPDATE{_GAP}settings\b", re.IGNORECASE),
)


def _sources() -> list[Path]:
    return sorted(
        path for root in SCANNED for path in root.rglob("*.py") if not path.is_relative_to(SKIPPED)
    )


def _hits(text: str) -> list[tuple[int, str]]:
    """Each match as (line number, matched text), found anywhere in ``text``."""
    return sorted(
        (text.count("\n", 0, match.start()) + 1, " ".join(match.group().split()))
        for pattern in PATTERNS
        for match in pattern.finditer(text)
    )


def test_the_scan_sees_the_settings_writers() -> None:
    """So an empty result below means clean, not a wrong path."""
    names = {path.relative_to(BACKEND).as_posix() for path in _sources()}

    assert "app/services/settings_service.py" in names
    assert "tools/oidc_allow_relink.py" in names
    assert not any(name.startswith("app/migrations/") for name in names)


@pytest.mark.parametrize(
    "source",
    [
        "await db.execute(insert(Setting).values(key='k'))",
        "stmt = pg_insert(Setting).values(key='k')",
        "await db.execute(update(\n    Setting\n).values(stored_value='x'))",
        "session.bulk_insert_mappings(Setting, rows)",
        "session.bulk_update_mappings(\n    Setting, rows)",
        "await conn.run_sync(Setting.__table__.create)",
        "_SETTINGS = Base.metadata.tables[Setting.__tablename__]",
        "_SETTINGS = Base.metadata.tables['settings']",
        'table = metadata.tables.get("settings")',
        'settings_table = table("settings", column("value"))',
        "text('INSERT INTO settings (key, value) VALUES (:k, :v)')",
        "text('INSERT OR REPLACE INTO settings VALUES (:k, :v)')",
        'text("UPDATE " "settings SET value = :v")',
        "text('''\n    update\n    settings set value = :v''')",
    ],
)
def test_every_raw_write_form_is_caught(source: str) -> None:
    assert _hits(source)


@pytest.mark.parametrize(
    "source",
    [
        "await db.execute(delete(Setting).where(Setting.key == key))",
        "result = await db.execute(select(Setting).where(Setting.key == key))",
        "# Update the settings page when the value changes",
        "UPDATE vehicle_settings SET x = 1",
    ],
)
def test_reads_deletes_and_prose_are_not_caught(source: str) -> None:
    assert _hits(source) == []


def test_no_raw_writes_to_the_settings_table() -> None:
    hits = [
        f"{path.relative_to(BACKEND)}:{line}: {found}"
        for path in _sources()
        for line, found in _hits(path.read_text(encoding="utf-8"))
    ]

    assert hits == []
