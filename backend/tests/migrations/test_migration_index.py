"""The generated migration index must list every migration file."""

import importlib.util
import re
from pathlib import Path

_GEN = Path(__file__).parent.parent.parent / "tools" / "gen_migration_index.py"


def _load_gen():
    spec = importlib.util.spec_from_file_location("gen_migration_index", _GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_index_lists_every_migration():
    gen = _load_gen()
    index = gen.build_index()
    migrations = [p.stem for p in gen.MIGRATIONS_DIR.glob("*.py") if re.match(r"^\d{3}_", p.name)]
    assert migrations, "expected migration files to exist"
    for stem in migrations:
        assert f"`{stem}`" in index, f"{stem} missing from generated index"


def test_index_flags_fatal_migrations():
    """A known FATAL migration (053) is marked; a non-FATAL one (060) is not."""
    gen = _load_gen()
    index = gen.build_index()
    fatal_line = next(ln for ln in index.splitlines() if "`053_" in ln)
    plain_line = next(ln for ln in index.splitlines() if "`060_" in ln)
    assert "FATAL" in fatal_line
    assert "FATAL" not in plain_line


def test_committed_index_is_fresh():
    """The committed INDEX.md must equal the generator output, so CI catches a
    migration added without regenerating the index."""
    gen = _load_gen()
    assert gen.INDEX_PATH.read_text(encoding="utf-8") == gen.build_index(), (
        "INDEX.md is stale — regenerate with `python tools/gen_migration_index.py`"
    )


def test_is_fatal_recognizes_plain_and_annotated_forms():
    """_is_fatal must match the runner's dynamic getattr(module, "FATAL", False)
    semantics for both plain and annotated assignment forms."""
    gen = _load_gen()
    assert gen._is_fatal("FATAL = True\n") is True
    assert gen._is_fatal("FATAL: bool = True\n") is True
    assert gen._is_fatal("FATAL = False\n") is False
    assert gen._is_fatal("FATAL: bool = False\n") is False
    assert gen._is_fatal("x = 1\n") is False
