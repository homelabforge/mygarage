"""Maintenance mode must close every route that can write telemetry.

The point of maintenance mode is that no new reading lands between migration
096 and the odometer repair tools; a single reading arriving mid-repair
recreates the mixed-unit state the tools refuse to run against.

The first implementation closed two prefixes, `/api/v1/livelink` and
`/api/v1/torque`, chosen by looking at the ingest routers. That missed
`POST /api/livelink/devices/{device_id}/backfill`, which lives under the *admin*
prefix, reaches `bulk_backfill`, and is callable by any admin or any script
holding an admin token while the instance is supposedly quiescent.

So this file does not check a hand-written list of paths. It derives the list
from the code: any route handler that calls a telemetry writer must be closed.
A new ingest route added later fails this test without anyone remembering to
update it, which a hand-written list would not do.
"""

import ast
import re
from pathlib import Path

import pytest

from app.middleware import is_maintenance_closed

#: Functions that write telemetry. A route reaching any of these must be closed.
#: Hand-written, and therefore a floor unless something checks it -- which is
#: what `TestTelemetryWriterSet` below does.
TELEMETRY_WRITERS = frozenset(
    {
        "store_telemetry",
        "bulk_backfill",
        "backfill_device",
        "store_readings",
        # The source pipeline. Torque's route calls only `ingest(...)` since it
        # was ported, so without this name the route scan below would silently
        # stop covering /api/v1/torque/{token}/upload.
        "ingest",
    }
)

#: Models whose construction means a telemetry row is being written.
TELEMETRY_MODELS = frozenset({"VehicleTelemetry"})

#: Functions that build a telemetry model but are unreachable from any route.
#: Empty since `store_value` was deleted: it had zero callers AND was broken
#: (it called `_should_store_historical` with three of its five arguments, so
#: any call with a non-zero storage interval raised TypeError). `store_readings`
#: replaced it and is reachable, so it belongs in TELEMETRY_WRITERS above.
KNOWN_UNREACHABLE: frozenset[str] = frozenset()

APP_DIR = Path(__file__).resolve().parents[2] / "app"
ROUTES_DIR = APP_DIR / "routes"

#: Routers whose paths are relative to a prefix declared in the module.
_ROUTE_DECORATORS = frozenset({"get", "post", "put", "patch", "delete"})


def _router_prefix(tree: ast.Module) -> str:
    """The `prefix=` of the module's `APIRouter(...)`, or "" if it has none."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "APIRouter":
            continue
        for kw in node.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                return str(kw.value.value)
    return ""


def _called_names(node: ast.AST) -> set[str]:
    """Every function name called anywhere inside `node`, by either call shape."""
    names: set[str] = set()
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        if isinstance(sub.func, ast.Attribute):
            names.add(sub.func.attr)
        elif isinstance(sub.func, ast.Name):
            names.add(sub.func.id)
    return names


def _route_sources() -> list[tuple[str, ast.Module]]:
    """Each router's source as one tree: a module, or every module of a package.

    A package declares its router in one module and decorates it in others, so
    its prefix and its helpers only line up when the package reads as one.
    """
    sources = [(path.name, ast.parse(path.read_text())) for path in sorted(ROUTES_DIR.glob("*.py"))]
    for package in sorted(p for p in ROUTES_DIR.iterdir() if (p / "__init__.py").is_file()):
        body = [
            stmt
            for path in sorted(package.glob("*.py"))
            for stmt in ast.parse(path.read_text()).body
        ]
        sources.append((package.name, ast.Module(body=body, type_ignores=[])))
    return sources


def _routes() -> list[tuple[str, str, bool]]:
    """Every (path, source, reaches a telemetry writer) the scan reads off a decorator.

    Resolution is **transitive within the module**. The first version of this
    scan looked only at direct calls in the handler body and therefore missed
    `POST /api/v1/torque/{token}/upload`, whose writer call lives in a helper
    the handler delegates to. A one-level scan silently under-reports, which in
    a test that asserts "everything is closed" reads as everything passing.
    """
    found: list[tuple[str, str, bool]] = []
    for source, tree in _route_sources():
        prefix = _router_prefix(tree)

        funcs = {
            n.name: n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef)
        }
        calls = {name: _called_names(node) for name, node in funcs.items()}

        # Fixed point: a function writes telemetry if it calls a writer, or
        # calls something in this module that does.
        writes = {name for name, c in calls.items() if c & TELEMETRY_WRITERS}
        changed = True
        while changed:
            changed = False
            for name, c in calls.items():
                if name not in writes and c & writes:
                    writes.add(name)
                    changed = True

        for name, func in funcs.items():
            for dec in func.decorator_list:
                if (
                    isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr in _ROUTE_DECORATORS
                    and dec.args
                    and isinstance(dec.args[0], ast.Constant)
                ):
                    found.append((prefix + str(dec.args[0].value), source, name in writes))
    return found


def _writing_routes() -> list[tuple[str, str]]:
    """Every (path, source) whose handler reaches a telemetry writer."""
    return sorted({(path, source) for path, source, writes in _routes() if writes})


class TestMaintenanceRouteInventory:
    """Derived from the code, not from a list someone remembered to update."""

    def test_the_scan_finds_the_routes_it_is_supposed_to_find(self):
        """Guards the guard: an AST walk that silently matches nothing would
        make every assertion below vacuously true."""
        paths = {path for path, _ in _writing_routes()}
        assert "/api/v1/livelink/ingest" in paths
        # Transitive: the writer call is in a helper, not in the handler.
        assert "/api/v1/torque/{token}/upload" in paths
        # The route the first implementation of maintenance mode left open.
        assert "/api/livelink/devices/{device_id}/backfill" in paths

    def test_the_scan_reads_every_import_route(self):
        """The importer writes no telemetry, but a scan that skips it skips any package.

        14 is the count on 32b15b50, read with the router's own prefix.
        """
        imports = {path for path, _, _ in _routes() if path.startswith("/api/import/")}
        assert len(imports) >= 14

    @pytest.mark.parametrize("path,module", _writing_routes(), ids=lambda v: str(v))
    def test_every_telemetry_writing_route_is_closed(self, path: str, module: str):
        assert is_maintenance_closed(path), (
            f"{path} (in {module}) reaches a telemetry writer but maintenance mode "
            f"lets it through, so a reading can land during the repair window."
        )


class TestIsMaintenanceClosed:
    """The predicate itself, including what must stay open."""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/livelink",
            "/api/v1/torque",
            "/api/livelink/devices/abc123/backfill",
        ],
    )
    def test_closed(self, path: str):
        assert is_maintenance_closed(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            # The operator needs the admin UI to watch the repair and to flip
            # the flag back off. Closing the whole /api/livelink prefix would
            # take it away.
            "/api/livelink/devices",
            "/api/livelink/devices/abc123",
            "/api/livelink/settings",
            "/api/vehicles",
            "/health",
            # Not a backfill route despite the substring.
            "/api/livelink/devices/abc123/backfill-history",
        ],
    )
    def test_open(self, path: str):
        assert is_maintenance_closed(path) is False


class TestTelemetryWriterSet:
    """The writer set is itself an inventory, so it is itself a floor.

    Everything above assumes `TELEMETRY_WRITERS` names every function that can
    write a telemetry row. Nothing checked that. This does: any function in
    `app/services/` that constructs a telemetry model must either be a declared
    writer, or be provably unreachable from a route.
    """

    @staticmethod
    def _functions_building_telemetry() -> dict[str, str]:
        """{function name: module} for every telemetry-model constructor.

        Also counts `dialect_insert(Model)` (`sqlalchemy.dialects.*.insert`,
        this codebase's Core-level upsert idiom) and a plain `insert(Model)`
        (`sqlalchemy.insert`, the dialect-generic form nothing here uses yet)
        as building `Model`: the model there is a call argument, never a
        constructor, so the plain Name-call scan below would otherwise miss
        every writer that dedups on a unique index instead of using the ORM
        constructor.
        """
        insert_builders = frozenset({"dialect_insert", "insert"})
        found: dict[str, str] = {}
        for module in sorted((APP_DIR / "services").glob("*.py")):
            tree = ast.parse(module.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                    continue
                built: set[str] = set()
                for sub in ast.walk(node):
                    if not isinstance(sub, ast.Call) or not isinstance(sub.func, ast.Name):
                        continue
                    built.add(sub.func.id)
                    if sub.func.id in insert_builders:
                        built.update(arg.id for arg in sub.args if isinstance(arg, ast.Name))
                if built & TELEMETRY_MODELS:
                    found[node.name] = module.name
        return found

    def test_the_scan_finds_the_known_writer(self):
        """Guards the guard: a scan matching nothing makes the next test vacuous."""
        assert "store_telemetry" in self._functions_building_telemetry()

    def test_every_telemetry_builder_is_declared_or_unreachable(self):
        builders = self._functions_building_telemetry()
        undeclared = {
            name: mod
            for name, mod in builders.items()
            if name not in TELEMETRY_WRITERS and name not in KNOWN_UNREACHABLE
        }
        assert not undeclared, (
            f"these build a telemetry row but are not in TELEMETRY_WRITERS: "
            f"{undeclared}. Add them there (so the route scan sees them), or to "
            f"KNOWN_UNREACHABLE if nothing calls them."
        )

    def test_the_unreachable_ones_really_are_unreachable(self):
        """`KNOWN_UNREACHABLE` is an escape hatch, so it needs its own guard.

        Without this, listing a function here would be a way to silence the
        test above rather than a statement of fact.
        """
        sources = "\n".join(
            f.read_text() for f in APP_DIR.rglob("*.py") if f.name != "telemetry_service.py"
        )
        for name in KNOWN_UNREACHABLE:
            calls = re.findall(rf"\b{re.escape(name)}\s*\(", sources)
            assert not calls, (
                f"{name} is listed as unreachable but is now called. Either move "
                f"it into TELEMETRY_WRITERS or remove it from KNOWN_UNREACHABLE."
            )
