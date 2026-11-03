#!/usr/bin/env python3
"""AST-based authorization tripwire for MyGarage's vehicle surface.

Replaces the two greps in ``.github/scripts/security-tripwire.sh``. The greps
could only see ``select(Vehicle).where(Vehicle.vin`` literals in route files;
they never inspected call arguments, the service layer, decorators, or control
flow, which is exactly why the v2.27.2 authorization cluster shipped (read-share
gates on mutating routes, ``optional_auth`` fail-opens, service-layer IDORs).

This checker walks ``backend/app/routes/`` and ``backend/app/services/`` with the
stdlib ``ast`` module (py3.14, no third-party deps) and applies five rules:

1. require-write-on-mutations  -- mutating handlers/service methods that reach
   ``get_vehicle_or_403`` without ``require_write=True`` (and without an OWNER
   gate). One-level call graph: a handler that delegates the gate to a service
   method is checked through that method.
2. delete-must-be-owner-only   -- a function that issues ``delete(Vehicle)`` whose
   only guard is ``get_vehicle_or_403`` rather than ``check_vehicle_ownership``.
3. vin-query-needs-access-gate -- a function that filters a query by its ``vin``
   path parameter (``Model.vin == vin`` / ``Model.vehicle_vin == vin``) with no
   access gate in the same function. Replaces the file-level exempt list with a
   presence-of-gate test.
4. no-new-read-wrappers        -- any ``(verify|ensure|check|get)_vehicle*`` helper
   not on the reviewed allowlist (fail-closed backstop for new bypass wrappers).
5. optional-auth-fail-open     -- a state-changing handler using ``optional_auth``
   at all, or a handler whose ``current_user is None`` branch reaches the Vehicle
   model without an explicit ``auth_mode == 'none'`` check.

Pragma escapes (placed on the relevant line):
    # tripwire: read-only       -- this get_vehicle_or_403 call is genuinely a read
    # tripwire: optional-auth-ok -- this optional_auth handler does not gate data

Usage:
    python backend/tools/authz_tripwire.py [--mode warn|fail] [--root .] [paths...]

``--mode warn`` prints findings and exits 0 (rollout phase). ``--mode fail``
exits 1 if any finding is present (enforcement). Defaults to ``fail``.
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --- configuration -----------------------------------------------------------

MUTATING_METHODS = {"post", "put", "patch", "delete"}

# The vehicle-access primitives. ``get_vehicle_or_403`` is the READ/WRITE gate
# (write via ``require_write=True``); ``check_vehicle_ownership`` and
# ``get_vehicle_for_owner_or_403`` are the OWNER gate.
READ_WRITE_GATE = "get_vehicle_or_403"
OWNER_GATES = {"check_vehicle_ownership", "get_vehicle_for_owner_or_403"}
ADMIN_DEP = "get_current_admin_user"

# Models whose ``.vin`` / ``.vehicle_vin`` filters carry access-control meaning.
# A select filtered by the path ``vin`` against one of these (or any child model)
# needs a gate in the same function; rule 3 keys off the comparison, not the model.
VIN_COLUMN_NAMES = {"vin", "vehicle_vin"}

# Reviewed allowlist for rule 4. Seeded with every vehicle-access helper that
# exists at the time this checker landed, plus the new owner-fetch primitive.
# Adding a name here is the "security review" the plan calls for.
WRAPPER_ALLOWLIST = {
    "get_vehicle_or_403",
    "get_vehicle_for_owner_or_403",
    "check_vehicle_ownership",
    "verify_vehicle_access",
    # Pre-existing route handlers / service methods that match the name pattern
    # but are not new bypass wrappers (they delegate to the gate or are reads).
    "get_vehicle",
    "get_vehicle_shares",
    "get_vehicle_templates",
    "get_vehicle_photo",
    "get_vehicle_thumbnail",
    "get_vehicle_analytics",
    "get_vehicle_sessions",
    "get_vehicle_recalls",
    "get_vehicle_livelink_status",
    "get_vehicle_telemetry",
}

# Functions exempt from rule 3 because they ARE the access primitives (they query
# Vehicle by vin precisely to implement the gate).
GATE_PRIMITIVE_NAMES = {"get_vehicle_or_403", "get_vehicle_for_owner_or_403"}

PRAGMA_READ_ONLY = "# tripwire: read-only"
PRAGMA_OPTIONAL_AUTH_OK = "# tripwire: optional-auth-ok"

RULE_REQUIRE_WRITE = "require-write-on-mutations"
RULE_DELETE_OWNER = "delete-must-be-owner-only"
RULE_VIN_GATE = "vin-query-needs-access-gate"
RULE_NEW_WRAPPER = "no-new-read-wrappers"
RULE_OPTIONAL_AUTH = "optional-auth-fail-open"


@dataclass
class Finding:
    rule: str
    path: str
    lineno: int
    func: str
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.lineno}  [{self.rule}]  {self.func}: {self.message}"


@dataclass
class FuncFacts:
    """Per-function facts gathered in a single AST pass."""

    name: str
    node: ast.AST
    lineno: int
    is_handler: bool = False
    http_method: str | None = None
    has_vin_param: bool = False
    deps: set[str] = field(default_factory=set)
    # gate signals
    g403_read_lines: list[int] = field(default_factory=list)
    has_g403_write: bool = False
    has_owner_gate: bool = False
    has_admin_dep: bool = False
    has_user_scope: bool = False  # filters by current_user.id / .user_id
    has_auth_mode_none_check: bool = False
    # destructive
    deletes_vehicle_lines: list[int] = field(default_factory=list)
    # raw vin query
    vin_filter_lines: list[int] = field(default_factory=list)
    touches_vehicle_model: bool = False
    # called simple names (for the one-level call graph)
    called_names: set[str] = field(default_factory=set)
    # optional_auth
    uses_optional_auth: bool = False
    optional_auth_pragma: bool = False


def _decorator_method(node: ast.AST) -> str | None:
    """Return the HTTP method if ``node`` is decorated with @<router>.<method>(...)."""
    for dec in getattr(node, "decorator_list", []):
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute) and target.attr in {
            "get",
            "post",
            "put",
            "patch",
            "delete",
        }:
            return target.attr
    return None


def _name_of(call_func: ast.AST) -> str | None:
    if isinstance(call_func, ast.Name):
        return call_func.id
    if isinstance(call_func, ast.Attribute):
        return call_func.attr
    return None


def _depends_callee(value: ast.AST) -> str | None:
    """If ``value`` is ``Depends(x)`` return the simple name of ``x``."""
    if isinstance(value, ast.Call) and _name_of(value.func) == "Depends" and value.args:
        return _name_of(value.args[0])
    return None


def _iter_calls(node: ast.AST):
    """Yield all Call nodes inside ``node`` without descending into nested defs."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(child, ast.Call):
            yield child
        yield from _iter_calls(child)


def _has_pragma(lines: list[str], lineno: int, pragma: str) -> bool:
    idx = lineno - 1
    if 0 <= idx < len(lines) and pragma in lines[idx]:
        return True
    return False


def _analyze_function(node: ast.FunctionDef | ast.AsyncFunctionDef, lines: list[str]) -> FuncFacts:
    facts = FuncFacts(name=node.name, node=node, lineno=node.lineno)

    method = _decorator_method(node)
    if method is not None:
        facts.is_handler = True
        facts.http_method = method

    # Parameters & dependency injections.
    args = node.args
    all_args = list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
    for a in all_args:
        if a.arg == "vin":
            facts.has_vin_param = True
    # Defaults carry the Depends(...) markers (kwonly defaults align with kwonlyargs).
    for default in list(args.defaults) + [d for d in args.kw_defaults if d is not None]:
        callee = _depends_callee(default)
        if callee:
            facts.deps.add(callee)
    if ADMIN_DEP in facts.deps:
        facts.has_admin_dep = True
    if "optional_auth" in facts.deps:
        facts.uses_optional_auth = True
        facts.optional_auth_pragma = _has_pragma(lines, node.lineno, PRAGMA_OPTIONAL_AUTH_OK)

    for call in _iter_calls(node):
        cname = _name_of(call.func)
        if cname:
            facts.called_names.add(cname)

        # Any call passing require_write=True (to get_vehicle_or_403 OR a wrapper
        # such as verify_vehicle_access) authorises a write.
        rw_kw = next((kw for kw in call.keywords if kw.arg == "require_write"), None)
        rw_is_true = (
            rw_kw is not None
            and isinstance(rw_kw.value, ast.Constant)
            and rw_kw.value.value is True
        )
        if rw_is_true:
            facts.has_g403_write = True

        if cname == READ_WRITE_GATE:
            if rw_kw is None:
                # No require_write kwarg -> read gate (unless annotated read-only).
                if not _has_pragma(lines, call.lineno, PRAGMA_READ_ONLY):
                    facts.g403_read_lines.append(call.lineno)
            elif isinstance(rw_kw.value, ast.Constant):
                if rw_kw.value.value is not True and not _has_pragma(
                    lines, call.lineno, PRAGMA_READ_ONLY
                ):
                    facts.g403_read_lines.append(call.lineno)
            # else: require_write forwarded from a parameter (a write-capable
            # wrapper like verify_vehicle_access) -- neither a hard read nor write.
        elif cname in OWNER_GATES:
            facts.has_owner_gate = True
        elif cname == "delete":
            # SQLAlchemy ``delete(Vehicle)`` destructive statement.
            if call.args and isinstance(call.args[0], ast.Name) and call.args[0].id == "Vehicle":
                facts.deletes_vehicle_lines.append(call.lineno)
        elif cname == "select":
            if call.args and isinstance(call.args[0], ast.Name) and call.args[0].id == "Vehicle":
                facts.touches_vehicle_model = True

    # Comparisons: vin filters and user-scope detection.
    for cmp_node in [n for n in ast.walk(node) if isinstance(n, ast.Compare)]:
        operands = [cmp_node.left] + list(cmp_node.comparators)
        names = {o.id for o in operands if isinstance(o, ast.Name)}
        attrs = {o.attr for o in operands if isinstance(o, ast.Attribute)}
        if "vin" in names and (attrs & VIN_COLUMN_NAMES):
            facts.vin_filter_lines.append(cmp_node.lineno)
        if "user_id" in attrs or _references_current_user_id(operands):
            facts.has_user_scope = True

    # auth_mode == 'none' guard anywhere in the function.
    for cmp_node in [n for n in ast.walk(node) if isinstance(n, ast.Compare)]:
        consts = [c.value for c in cmp_node.comparators if isinstance(c, ast.Constant)]
        if "none" in consts:
            facts.has_auth_mode_none_check = True

    return facts


def _references_current_user_id(operands: list[ast.AST]) -> bool:
    for o in operands:
        if (
            isinstance(o, ast.Attribute)
            and o.attr == "id"
            and isinstance(o.value, ast.Name)
            and o.value.id == "current_user"
        ):
            return True
    return False


def _has_write_or_owner(facts: FuncFacts) -> bool:
    return facts.has_g403_write or facts.has_owner_gate or facts.has_admin_dep


def check_paths(roots: list[Path]) -> list[Finding]:
    findings: list[Finding] = []

    files: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            files.append(root)
        elif root.is_dir():
            files.extend(sorted(root.rglob("*.py")))

    # First pass: gather facts per (file, function).
    file_funcs: dict[Path, list[FuncFacts]] = {}
    index: dict[str, list[FuncFacts]] = {}
    for path in files:
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:  # pragma: no cover - defensive
            findings.append(
                Finding("parse-error", str(path), exc.lineno or 0, "<module>", str(exc))
            )
            continue
        funcs: list[FuncFacts] = []
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                facts = _analyze_function(n, lines)
                funcs.append(facts)
                index.setdefault(facts.name, []).append(facts)
        file_funcs[path] = funcs

    # Second pass: apply rules.
    for path, funcs in file_funcs.items():
        rel = _rel(path)
        for facts in funcs:
            findings.extend(_apply_rules(rel, facts, index))

    return findings


def _rel(path: Path) -> str:
    parts = path.parts
    if "backend" in parts:
        i = parts.index("backend")
        return str(Path(*parts[i:]))
    return str(path)


def _reached_facts(facts: FuncFacts, index: dict[str, list[FuncFacts]]) -> list[FuncFacts]:
    """The function plus, one level deep, the functions it calls by simple name."""
    reached = [facts]
    for name in facts.called_names:
        for target in index.get(name, []):
            if target is facts:
                continue
            reached.append(target)
    return reached


def _apply_rules(rel: str, facts: FuncFacts, index: dict[str, list[FuncFacts]]) -> list[Finding]:
    out: list[Finding] = []

    # Rule 4 -- no new read wrappers (applies to non-handler helpers only).
    if not facts.is_handler and _is_vehicle_helper_name(facts.name):
        if facts.name not in WRAPPER_ALLOWLIST:
            out.append(
                Finding(
                    RULE_NEW_WRAPPER,
                    rel,
                    facts.lineno,
                    facts.name,
                    "new vehicle-access helper not on the reviewed allowlist "
                    "(add to WRAPPER_ALLOWLIST after security review, and ensure it "
                    "forwards require_write / checks ownership)",
                )
            )

    # Rule 5 -- optional_auth fail-open.
    if facts.is_handler and facts.uses_optional_auth and not facts.optional_auth_pragma:
        if facts.http_method in MUTATING_METHODS:
            out.append(
                Finding(
                    RULE_OPTIONAL_AUTH,
                    rel,
                    facts.lineno,
                    facts.name,
                    f"state-changing handler ({facts.http_method.upper()}) uses "
                    "optional_auth; use require_auth so a no-token request 401s "
                    "instead of falling through the auth_mode=='none' branch",
                )
            )
        elif facts.touches_vehicle_model and not facts.has_auth_mode_none_check:
            out.append(
                Finding(
                    RULE_OPTIONAL_AUTH,
                    rel,
                    facts.lineno,
                    facts.name,
                    "optional_auth handler reaches the Vehicle model with no explicit "
                    "auth_mode=='none' check; current_user is None for BOTH none-mode "
                    "and an auth-enabled no-token request (fail-open). Use require_auth",
                )
            )

    # Rule 2 -- delete(Vehicle) must be owner-gated.
    if facts.deletes_vehicle_lines and not facts.has_owner_gate:
        for line in facts.deletes_vehicle_lines:
            out.append(
                Finding(
                    RULE_DELETE_OWNER,
                    rel,
                    line,
                    facts.name,
                    "deletes the Vehicle row guarded only by get_vehicle_or_403; "
                    "vehicle delete is OWNER-only -- use check_vehicle_ownership "
                    "(get_vehicle_or_403(require_write=True) still admits a write-share)",
                )
            )

    # Rule 1 -- mutating routes must reach a write/owner gate.
    if facts.is_handler and facts.http_method in MUTATING_METHODS:
        reached = _reached_facts(facts, index)
        read_lines = [ln for f in reached for ln in f.g403_read_lines]
        if read_lines and not any(_has_write_or_owner(f) for f in reached):
            line = min(read_lines)
            out.append(
                Finding(
                    RULE_REQUIRE_WRITE,
                    rel,
                    line,
                    facts.name,
                    f"mutating handler ({facts.http_method.upper()}) reaches "
                    "get_vehicle_or_403 without require_write=True and without an "
                    "OWNER gate; a read-share would pass. Add require_write=True "
                    "(child write) or check_vehicle_ownership (vehicle core/owner op), "
                    f"or annotate the call '{PRAGMA_READ_ONLY}'",
                )
            )

    # Rule 3 -- a request entry point (route handler) that filters a query by its
    # vin path param, where neither the handler nor the service methods it calls
    # (one level) apply an access gate. Rooting only at handlers avoids flagging
    # the many internal service helpers that take a vin but run inside an already
    # gated request flow; the call graph still reaches a delegated service IDOR
    # (e.g. transfer_service.get_transfer_history).
    if facts.is_handler and facts.has_vin_param:
        reached = _reached_facts(facts, index)
        has_vin_filter = any(f.vin_filter_lines for f in reached)
        if has_vin_filter and not any(_is_gated(f) for f in reached):
            line = min(ln for f in reached for ln in f.vin_filter_lines)
            out.append(
                Finding(
                    RULE_VIN_GATE,
                    rel,
                    line,
                    facts.name,
                    "filters a query by the path-param vin with no access gate in the "
                    "handler or the service methods it calls (no get_vehicle_or_403 / "
                    "check_vehicle_ownership / admin / user_id scope). IDOR risk -- gate it",
                )
            )

    return out


def _is_gated(facts: FuncFacts) -> bool:
    """Whether a function applies (or delegates to) a vehicle access gate."""
    return bool(
        facts.g403_read_lines
        or facts.has_g403_write
        or facts.has_owner_gate
        or facts.has_admin_dep
        or facts.has_user_scope
        or READ_WRITE_GATE in facts.called_names
        or facts.name in GATE_PRIMITIVE_NAMES
    )


def _is_vehicle_helper_name(name: str) -> bool:
    for prefix in ("verify_vehicle", "ensure_vehicle", "check_vehicle", "get_vehicle"):
        if name.startswith(prefix):
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["warn", "fail"], default="fail")
    parser.add_argument(
        "--root",
        default=".",
        help="repository root (default: cwd). Used to resolve default scan paths.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="explicit files/dirs to scan (default: backend/app/routes + services)",
    )
    args = parser.parse_args(argv)

    root = Path(args.root)
    if args.paths:
        roots = [Path(p) for p in args.paths]
    else:
        roots = [
            root / "backend" / "app" / "routes",
            root / "backend" / "app" / "services",
        ]

    findings = check_paths(roots)
    findings.sort(key=lambda f: (f.rule, f.path, f.lineno))

    if findings:
        print(f"authz-tripwire: {len(findings)} finding(s)\n")
        by_rule: dict[str, list[Finding]] = {}
        for f in findings:
            by_rule.setdefault(f.rule, []).append(f)
        for rule, items in by_rule.items():
            print(f"== {rule} ({len(items)}) ==")
            for f in items:
                print(f"  {f.render()}")
            print()
    else:
        print("authz-tripwire: no findings")

    if args.mode == "fail" and findings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
