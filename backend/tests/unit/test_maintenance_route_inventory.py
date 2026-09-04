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
    {"store_telemetry", "store_torque_telemetry", "bulk_backfill", "backfill_device"}
)

#: Models whose construction means a telemetry row is being written.
TELEMETRY_MODELS = frozenset({"VehicleTelemetry"})

#: Functions that build a telemetry model but are unreachable from any route.
#: `store_value` currently has zero callers anywhere in `app/`. Listed rather
#: than silently excluded, so that giving it a caller fails this test.
KNOWN_UNREACHABLE = frozenset({"store_value"})

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


def _writing_routes() -> list[tuple[str, str]]:
    """Every (path, source file) whose handler reaches a telemetry writer.

    Resolution is **transitive within the module**. The first version of this
    scan looked only at direct calls in the handler body and therefore missed
    `POST /api/v1/torque/{token}/upload`, whose writer call lives in a helper
    the handler delegates to. A one-level scan silently under-reports, which in
    a test that asserts "everything is closed" reads as everything passing.
    """
    found: list[tuple[str, str]] = []
    for module in sorted(ROUTES_DIR.glob("*.py")):
        tree = ast.parse(module.read_text())
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

        for name in writes:
            for dec in funcs[name].decorator_list:
                if (
                    isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr in _ROUTE_DECORATORS
                    and dec.args
                    and isinstance(dec.args[0], ast.Constant)
                ):
                    found.append((prefix + str(dec.args[0].value), module.name))
    return sorted(set(found))


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
        """{function name: module} for every telemetry-model constructor."""
        found: dict[str, str] = {}
        for module in sorted((APP_DIR / "services").glob("*.py")):
            tree = ast.parse(module.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                    continue
                built = {
                    sub.func.id
                    for sub in ast.walk(node)
                    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                }
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
