"""The importer's modules: the `app.routes.import_data` package and every module in it.

It was one file until batch 3b-1 split it into a package (B3-9). The guards that
walk its source and the tests that patch its names read every module here, so a
walk can't go quietly empty when code moves between modules.
"""

import importlib
import pkgutil
from pathlib import Path
from types import ModuleType

import app.routes.import_data as import_data


def importer_modules() -> list[ModuleType]:
    """The package itself, then each of its submodules."""
    infos = list(pkgutil.iter_modules(import_data.__path__))
    # The guards only walk one level, so a subpackage would hide its modules from
    # all of them. The package stays flat by design.
    nested = [info.name for info in infos if info.ispkg]
    assert not nested, (
        f"{import_data.__name__} has subpackages {nested}; the importer guards walk "
        "one level, so keep the package flat"
    )
    return [
        import_data,
        *(importlib.import_module(f"{import_data.__name__}.{info.name}") for info in infos),
    ]


def importer_files() -> list[Path]:
    """The source file behind each of `importer_modules()`."""
    files: list[Path] = []
    for module in importer_modules():
        assert module.__file__ is not None, module.__name__
        files.append(Path(module.__file__))
    return files
