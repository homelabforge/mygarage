"""The test suite stays out of the real data directory.

The backup and attachment tests used to touch `/data` at import and skip when
it wasn't writable, which was everywhere they ran, so 20 tests skipped for
months. Where it was writable they wrote into the real `/data`. Point the code
at a tmp dir instead.
"""

import os
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parents[1]
THIS_FILE = Path(__file__).resolve()

# The probe's names, and the env lookup it was built on.
NEEDLES = ("HAS_WRITE_ACCESS", "requires_write_access", 'getenv("DATA_DIR"')


def test_no_test_module_probes_the_data_dir() -> None:
    hits = [
        f"{path.relative_to(TESTS_DIR)}: {needle}"
        for path in sorted(TESTS_DIR.rglob("*.py"))
        if path.resolve() != THIS_FILE
        for needle in NEEDLES
        if needle in path.read_text(encoding="utf-8")
    ]

    assert hits == []


def test_the_jwt_key_comes_from_the_env_not_a_data_file() -> None:
    # Unset, importing app.config writes /data/secret.key wherever /data is writable.
    from app.config import settings

    assert os.environ.get("MYGARAGE_SECRET_KEY")
    assert settings.secret_key == os.environ["MYGARAGE_SECRET_KEY"]
