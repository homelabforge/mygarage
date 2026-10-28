"""The importer's modules, whether `app.routes.import_data` is one file or a package.

It's one file until batch 3b-1 splits it into a package (B3-9). The guards that
walk its source and the tests that patch its names read every module either
way, so a walk can't go quietly empty when the file becomes a directory.
"""

import importlib
import pkgutil
from pathlib import Path
from types import ModuleType

import app.routes.import_data as import_data


def importer_modules() -> list[ModuleType]:
    """The module itself, then each of its submodules once it's a package."""
    if not hasattr(import_data, "__path__"):
        return [import_data]
    return [
        import_data,
        *(
            importlib.import_module(f"{import_data.__name__}.{info.name}")
            for info in pkgutil.iter_modules(import_data.__path__)
        ),
    ]


def importer_files() -> list[Path]:
    """The source file behind each of `importer_modules()`."""
    files = []
    for module in importer_modules():
        assert module.__file__ is not None, module.__name__
        files.append(Path(module.__file__))
    return files
