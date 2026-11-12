"""Import a migration file as a module, the way the runner does.

Migration files start with a number, so they can't be imported by name. This
is the one copy of the importlib dance the tests used to repeat per file.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import app.migrations

MIGRATIONS_DIR = Path(app.migrations.__file__).parent


def load_migration(stem: str, module_name: str | None = None) -> ModuleType:
    """Load `app/migrations/<stem>.py`, named `module_name` (default: the stem)."""
    path = MIGRATIONS_DIR / f"{stem}.py"
    spec = importlib.util.spec_from_file_location(module_name or stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load migration module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
