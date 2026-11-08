"""Nothing in the app writes the settings table around the model.

`Setting.value` is where secrets get encrypted. A Core `insert()` or `update()`,
the bare table, or raw SQL writes the column as given, so a secret would land in
plaintext and sit there until the next start's sweep. Migrations are left out:
they run before the model exists and the sweep is their backstop. Tests seed raw
rows on purpose and aren't scanned. A `delete(Setting)` is fine, it stores nothing.
"""

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
SCANNED = (BACKEND / "app", BACKEND / "tools")
SKIPPED = BACKEND / "app" / "migrations"

PATTERNS = (
    # insert(Setting), pg_insert(Setting), sqlite_insert(Setting) and the like.
    re.compile(r"insert\(\s*Setting\b"),
    re.compile(r"update\(\s*Setting\b"),
    re.compile(r"\bSetting\.__table__"),
    re.compile(r"\bINSERT\s+(OR\s+\w+\s+)?INTO\s+settings\b", re.IGNORECASE),
    re.compile(r"\bUPDATE\s+settings\b", re.IGNORECASE),
)


def _sources() -> list[Path]:
    return sorted(
        path for root in SCANNED for path in root.rglob("*.py") if not path.is_relative_to(SKIPPED)
    )


def test_the_scan_sees_the_settings_writers() -> None:
    """So an empty result below means clean, not a wrong path."""
    names = {path.relative_to(BACKEND).as_posix() for path in _sources()}

    assert "app/services/settings_service.py" in names
    assert "tools/oidc_allow_relink.py" in names
    assert not any(name.startswith("app/migrations/") for name in names)


def test_no_raw_writes_to_the_settings_table() -> None:
    hits = [
        f"{path.relative_to(BACKEND)}:{number}: {line.strip()}"
        for path in _sources()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if any(pattern.search(line) for pattern in PATTERNS)
    ]

    assert hits == []
