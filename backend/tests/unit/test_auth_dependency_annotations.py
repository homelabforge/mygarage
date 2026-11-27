"""A param fed by an auth dependency that can return None has to say so.

`require_auth`, `get_current_admin_user` and `optional_auth` return None when
auth_mode is none, which is the default install. 168 params were typed plain
`User` anyway (A-12), and pyright couldn't tell: a `Depends()` default is
untyped to it and `reportArgumentType` is off. So a None read just 500'd.
Typed honestly, pyright warns on every unguarded read.

This walks app/ with the AST and fails on any param fed by one of those that
isn't typed `... | None`. It reads both FastAPI forms (`x: T = Depends(f)` and
`x: Annotated[T, Depends(f)]`, inline or through an alias), `Security()`, and
`fastapi.Depends` by attribute name. A wrapper dependency that takes one of
these and returns a type without None, and doesn't raise on None, is a lie of
its own and becomes a None dependency too.

The scanner first went blind on `Annotated`, so the self-tests feed it a
snippet of every form, and `test_every_none_dependency_call_is_read` fails if
the real tree has a form it can't read.

Names resolve per module: an alias or an import rename means what its own
module says, or what the scanned module it's imported from says.
`Depends(partial(f))` reads as f, and an instance of a class in app/
(`Depends(Gate())`, or `gate = Gate()` at module level) as `Gate.__call__`. An
instance from outside app/ has to be in `EXTERNAL_INSTANCES`. A plain name has
to land on a def or class in app/ or a known dependency, so a closure param, a
local or an outside import can't pass as a function. With two Depends in one
`Annotated`, the last one counts, as in FastAPI. Any other Depends argument is
an `unreadable dependency` finding, so a new form fails loud.
"""

import ast
from collections import defaultdict
from collections.abc import Iterator, Mapping
from pathlib import Path, PurePosixPath
from typing import NamedTuple

import pytest

APP_DIR = Path(__file__).resolve().parents[2] / "app"

#: Auth dependencies that return None when auth is off. Hand-written, so it's a
#: floor: the scan adds any function in app/ whose return type admits None, and
#: any wrapper around one of these that drops the None.
KNOWN_NONE_DEPS = frozenset(
    {
        "require_auth",
        "get_current_admin_user",
        "optional_auth",
        "get_current_user_optional",
        "get_optional_user",
    }
)

#: Callable instances from outside app/, spelled the way the scanner reads them,
#: and whether each can hand back None. HTTPBearer returns None instead of a 403
#: when auto_error is off. An outside instance missing here is unreadable.
EXTERNAL_INSTANCES: Mapping[str, bool] = {"HTTPBearer(auto_error=False)": True}

#: What a Depends argument the scanner can't read reports as.
UNREADABLE = "unreadable dependency"
#: A bare `Depends()` builds the annotation's class, and a constructor never hands back None.
_ANNOTATION_CLASS = "<the annotation's class>"

_DEPENDS = frozenset({"Depends", "Security"})
_GENERATORS = frozenset({"Generator", "AsyncGenerator", "Iterator", "AsyncIterator"})

type _Func = ast.FunctionDef | ast.AsyncFunctionDef


class Finding(NamedTuple):
    """One spot where a None can arrive but the type says it can't."""

    file: str
    line: int
    function: str
    #: The param's name, "return" for a wrapper whose return type drops the None,
    #: or "" for an unreadable Depends that feeds no param.
    param: str
    dep: str

    def __str__(self) -> str:
        """One line for the failure message."""
        where = f"{self.file}:{self.line} {self.function}"
        if self.dep == UNREADABLE:
            return (
                f"{where}({self.param}) has a Depends the scanner can't read. An outside "
                f"class by name reads fine as `x: Annotated[Cls, Depends()]`; an outside "
                f"instance goes in EXTERNAL_INSTANCES"
            )
        if self.param == "return":
            return f"{where}() takes {self.dep} but its return type drops None"
        return f"{where}({self.param}) is fed by {self.dep}"


class ScanResult(NamedTuple):
    """What a scan found, plus what it couldn't read."""

    findings: list[Finding]
    #: Depends/Security calls on a None dependency that aren't bound to a param.
    unbound: list[str]
    #: Every None dependency the scan ended up with (known, derived and wrappers).
    none_deps: frozenset[str]


def _name(node: ast.expr | None) -> str | None:
    """`f` for both `f` and `mod.f`, so an import style can't hide a call."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _root(node: ast.expr) -> ast.expr:
    """`svc` for `svc.a.b`: the name an attribute chain hangs off."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node


def _is_outside(level: int, module: str | None) -> bool:
    """Whether an import reads a module outside app/ (not relative, not `app.`)."""
    return not level and module is not None and module != "app" and not module.startswith("app.")


def _module_level(stmts: list[ast.stmt]) -> Iterator[ast.stmt]:
    """Module-level statements, including the ones under `if` / `try`."""
    for stmt in stmts:
        yield stmt
        if isinstance(stmt, ast.If):
            yield from _module_level(stmt.body + stmt.orelse)
        elif isinstance(stmt, ast.Try):
            handlers = [s for h in stmt.handlers for s in h.body]
            yield from _module_level(stmt.body + handlers + stmt.orelse + stmt.finalbody)


def _tests_for_none(test: ast.expr, param: str) -> bool:
    """`if p is None` or `if not p`."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return isinstance(test.operand, ast.Name) and test.operand.id == param
    return (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Is)
        and isinstance(test.left, ast.Name)
        and test.left.id == param
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value is None
    )


def _raises_on_none(fn: _Func, param: str) -> bool:
    """True if the body raises on a None `param` before it can return.

    Only a top-level `if p is None: ... raise` counts, and only ahead of any
    `return`. Anything cleverer reads as not raising, which fails closed.
    """
    for stmt in fn.body:
        if (
            isinstance(stmt, ast.If)
            and _tests_for_none(stmt.test, param)
            and isinstance(stmt.body[-1], ast.Raise)
        ):
            return True
        if any(isinstance(n, ast.Return) for n in ast.walk(stmt)):
            return False
    return False


def _returns_exactly_none(fn: _Func) -> bool:
    """`-> None`: a dependency run for a check or a side effect. It hands nobody a user."""
    return isinstance(fn.returns, ast.Constant) and fn.returns.value is None


def _own_binds(scope: _Func | ast.ClassDef | ast.Lambda) -> frozenset[str]:
    """Names a def, lambda or class binds for itself: params, assignments, imports, defs."""
    names: set[str] = set()
    if not isinstance(scope, ast.ClassDef):
        a = scope.args
        params = [*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg]
        names.update(p.arg for p in params if p)
    declared: set[str] = set()
    todo: list[ast.AST] = list(scope.body) if isinstance(scope.body, list) else [scope.body]
    while todo:
        node = todo.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)  # a nested scope's own names stay in there
            continue
        if isinstance(node, ast.Lambda):
            continue
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            names.add(node.id)
        elif isinstance(node, ast.alias):
            names.add((node.asname or node.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.Global | ast.Nonlocal):
            declared.update(node.names)
        todo.extend(ast.iter_child_nodes(node))
    return frozenset(names - declared)


class _Scanner:
    """One pass over a set of sources. Labels show up in findings as file names."""

    def __init__(self, sources: Mapping[str, str], known: frozenset[str] = KNOWN_NONE_DEPS) -> None:
        self.known = known
        self.trees = {label: ast.parse(src) for label, src in sources.items()}
        self.funcs: list[tuple[str, _Func]] = [
            (label, fn)
            for label, tree in self.trees.items()
            for fn in ast.walk(tree)
            if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef)
        ]
        # Module-level names, keyed (module, name): `CurrentUser = Annotated[...]`,
        # `auth_dep = require_auth`. A list, in case a module assigns one twice.
        self.aliases: dict[tuple[str, str], list[ast.expr]] = defaultdict(list)
        # `from app.x import y [as z]` between scanned modules: (module, z) -> (x, y).
        self.imports: dict[tuple[str, str], tuple[str, str]] = {}
        # Any `import y as z`, scanned or not: (module, z) -> y. So `Depends as D`
        # and `require_auth as ra` still read as Depends and require_auth.
        self.renames: dict[tuple[str, str], str] = {}
        # A scanned module bound to a name: `from app.services import auth` or
        # `import app.services.auth as auth`, so `auth.security` reads in auth.py.
        self.modules: dict[tuple[str, str], str] = {}
        # Names bound by an import from outside app/: `from somelib import check`,
        # `import somelib`. They aren't the app's defs, whatever they're called.
        self.outside: set[tuple[str, str]] = set()
        for label, tree in self.trees.items():
            for stmt in _module_level(tree.body):
                if isinstance(stmt, ast.ImportFrom):
                    source = self._source_label(label, stmt)
                    for alias in stmt.names:
                        local = alias.asname or alias.name
                        if alias.asname:
                            self.renames[(label, local)] = alias.name
                        if source is not None:
                            self.imports[(label, local)] = (source, alias.name)
                        dotted = f"{stmt.module}.{alias.name}" if stmt.module else alias.name
                        if module := self._module_label(label, stmt.level, dotted):
                            self.modules[(label, local)] = module
                        elif _is_outside(stmt.level, stmt.module):
                            self.outside.add((label, local))
                elif isinstance(stmt, ast.Import):
                    for alias in stmt.names:
                        local = alias.asname or alias.name.split(".")[0]
                        if alias.asname and (module := self._module_label(label, 0, alias.name)):
                            self.modules[(label, alias.asname)] = module
                        elif _is_outside(0, alias.name):
                            self.outside.add((label, local))
                elif (
                    isinstance(stmt, ast.Assign)
                    and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                ):
                    self.aliases[(label, stmt.targets[0].id)].append(stmt.value)
                elif (
                    isinstance(stmt, ast.AnnAssign)
                    and isinstance(stmt.target, ast.Name)
                    and stmt.value is not None
                ):
                    self.aliases[(label, stmt.target.id)].append(stmt.value)
                elif isinstance(stmt, ast.TypeAlias):
                    self.aliases[(label, stmt.name.id)].append(stmt.value)
        # A class's own `__call__` goes by `Cls.__call__`, so `Depends(Cls())` can find it.
        self.callable_classes: set[str] = set()
        self.class_names: set[str] = set()
        self.dep_names: dict[int, str] = {}
        for tree in self.trees.values():
            for cls in ast.walk(tree):
                if not isinstance(cls, ast.ClassDef):
                    continue
                self.class_names.add(cls.name)
                for stmt in cls.body:
                    if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef) and (
                        stmt.name == "__call__"
                    ):
                        self.callable_classes.add(cls.name)
                        self.dep_names[id(stmt)] = f"{cls.name}.__call__"
        # What a plain name may resolve to: a def or class in the sources, or a known
        # dependency. Anything else (an outside import, a typo) can't be read.
        self.defined = known | self.class_names | {self._dep_name(fn) for _, fn in self.funcs}
        # Name reads that a def, lambda or class around them binds for itself: a
        # closure param or a local. Nobody can say what those hold.
        self.local_loads: set[int] = set()
        for tree in self.trees.values():
            self._mark_local_loads(tree, frozenset())
        # Depends calls we managed to tie to a param, by node id.
        self.bound: set[int] = set()

    def _mark_local_loads(
        self, node: ast.AST, local: frozenset[str], class_body: frozenset[str] = frozenset()
    ) -> None:
        """Note every Name read inside a scope that binds that name itself.

        `class_body` is what the class we're directly in binds. Its methods can't
        see those names, as in Python, so a def or lambda drops them.
        """
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load) and node.id in local | class_body:
                self.local_loads.add(id(node))
            return
        inner: list[ast.AST] = []
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            # Defaults, annotations and decorators run outside; only the body runs inside.
            inner = list(node.body) if isinstance(node.body, list) else [node.body]
            for child in inner:
                self._mark_local_loads(child, local | _own_binds(node))
        elif isinstance(node, ast.ClassDef):
            inner = list(node.body)
            for child in inner:
                self._mark_local_loads(child, local, _own_binds(node))
        inner_ids = {id(n) for n in inner}
        for child in ast.iter_child_nodes(node):
            if id(child) not in inner_ids:
                self._mark_local_loads(child, local, class_body)

    def _dep_name(self, fn: _Func) -> str:
        """What a Depends on this function reads as: its name, or `Cls.__call__`."""
        return self.dep_names.get(id(fn), fn.name)

    def _source_label(self, label: str, stmt: ast.ImportFrom) -> str | None:
        """The scanned module a `from ... import` reads, or None if it isn't one."""
        if stmt.level and stmt.module is None:
            return None
        return self._module_label(label, stmt.level, stmt.module or "")

    def _module_label(self, label: str, level: int, module: str) -> str | None:
        """The scanned file a dotted module path names, relative or `app.`-absolute."""
        if level:
            base = PurePosixPath(label).parent
            for _ in range(level - 1):
                base = base.parent
            parts = [*base.parts, *module.split(".")]
        elif module.startswith("app."):
            parts = module.split(".")[1:]
        else:
            return None
        stem = "/".join(p for p in parts if p not in ("", "."))
        for candidate in (f"{stem}.py", f"{stem}/__init__.py"):
            if candidate in self.trees:
                return candidate
        return None

    def _resolve(
        self, label: str, name: str, seen: frozenset[tuple[str, str]] = frozenset()
    ) -> list[tuple[str, ast.expr]]:
        """(defining module, value) for a module-level name, through imports. Empty if none."""
        key = (label, name)
        if key in seen:
            return []
        if values := self.aliases.get(key):
            return [(label, value) for value in values]
        if key in self.imports:
            return self._resolve(*self.imports[key], seen | {key})
        return []

    def _target_name(
        self, label: str, name: str, seen: frozenset[tuple[str, str]] = frozenset()
    ) -> str:
        """The function a name stands for: through `import f as g`, re-exports and `g = f`."""
        return self._target(label, name, seen)[0]

    def _target(
        self, label: str, name: str, seen: frozenset[tuple[str, str]] = frozenset()
    ) -> tuple[str, bool]:
        """`_target_name`, plus whether that name came in from outside app/."""
        key = (label, name)
        if key in seen:
            return name, False
        seen = seen | {key}
        if key in self.imports:
            # Imported from a scanned module: ask that module what its name is.
            return self._target(*self.imports[key], seen)
        if key in self.renames:
            # `from elsewhere import f as g`: g is f.
            return self.renames[key], key in self.outside
        if key in self.outside:
            return name, True
        for value in self.aliases.get(key, []):
            if isinstance(value, ast.Name | ast.Attribute) and (inner := _name(value)):
                if isinstance(value, ast.Attribute) and self._from_outside(label, value):
                    return inner, True
                return self._target(label, inner, seen)
        return name, False

    def _from_outside(self, label: str, node: ast.Attribute) -> bool:
        """`somelib.check` with somelib imported from outside app/."""
        root = _root(node)
        return isinstance(root, ast.Name) and (label, root.id) in self.outside

    def _depends_call(self, label: str, node: ast.expr | None) -> ast.Call | None:
        """`node` if it's a `Depends(...)` / `Security(...)` call, renamed or not."""
        if not isinstance(node, ast.Call):
            return None
        name = _name(node.func)
        if name is None:
            return None
        if name in _DEPENDS or self.renames.get((label, name)) in _DEPENDS:
            return node
        return None

    def _dep_target(self, label: str, call: ast.Call) -> str | None:
        """The dependency a Depends call names, positional or `dependency=`. None if unreadable."""
        node: ast.expr | None = call.args[0] if call.args else None
        if node is None:
            node = next((kw.value for kw in call.keywords if kw.arg == "dependency"), None)
        if node is None:
            return _ANNOTATION_CLASS
        return self._runs(label, node)

    def _runs(
        self, label: str, node: ast.expr, seen: frozenset[tuple[str, str]] = frozenset()
    ) -> str | None:
        """What a Depends argument runs: a function, `Cls.__call__` or an outside instance."""
        # A closure param or a local, or an attribute hanging off one (`svc.check`):
        # nobody can say what those hold, whatever the attribute is called.
        func_or_node = node.func if isinstance(node, ast.Call) else node
        if id(_root(func_or_node)) in self.local_loads:
            return None
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and (module := self.modules.get((label, node.value.id)))
        ):
            # `auth.security` with auth a scanned module: read the name over there.
            return self._runs(module, ast.Name(node.attr), seen)
        if isinstance(node, ast.Call):
            func = _name(node.func)
            if not func:
                return None
            func, outside = self._target(label, func)
            if isinstance(node.func, ast.Attribute) and self._from_outside(label, node.func):
                outside = True
            if func == "partial":
                return self._runs(label, node.args[0], seen) if node.args else None
            if func in self.callable_classes and not outside:
                return f"{func}.__call__"
            # Anything else built by a call has to be in the table, spelled exactly.
            spelled = ast.unparse(ast.Call(ast.Name(func), node.args, node.keywords))
            return spelled if spelled in EXTERNAL_INSTANCES else None
        name = _name(node)
        if name is None:
            return None
        key = (label, name)
        if isinstance(node, ast.Name) and key not in seen:
            # A module-level name means whatever it's bound to, and every binding has to agree.
            if bound := self._resolve(label, name):
                reads = {self._runs(def_label, value, seen | {key}) for def_label, value in bound}
                return reads.pop() if len(reads) == 1 else None
        target, outside = self._target(label, name)
        if isinstance(node, ast.Attribute) and self._from_outside(label, node):
            outside = True
        # Something imported from outside app/ isn't the app's def of that name.
        return target if target in self.defined and not outside else None

    def _default_deps(self, label: str, default: ast.expr | None) -> list[str]:
        """Dependencies named by a param's default: `Depends(f)`, or an alias of one."""
        calls: list[tuple[str, ast.Call]] = []
        if call := self._depends_call(label, default):
            calls = [(label, call)]
        elif isinstance(default, ast.Name):
            for def_label, value in self._resolve(label, default.id):
                if c := self._depends_call(def_label, value):
                    calls.append((def_label, c))
        elif (
            isinstance(default, ast.Attribute)
            and isinstance(default.value, ast.Name)
            and (module := self.modules.get((label, default.value.id)))
        ):
            # `deps.auth_dep` with deps a scanned module: its `auth_dep = Depends(...)`.
            for def_label, value in self._resolve(module, default.attr):
                if c := self._depends_call(def_label, value):
                    calls.append((def_label, c))
        deps: list[str] = []
        for def_label, c in calls:
            self.bound.add(id(c))
            deps.append(self._dep_target(def_label, c) or UNREADABLE)
        return deps

    def _readings(
        self, label: str, ann: ast.expr | None, seen: frozenset[tuple[str, str]] = frozenset()
    ) -> list[tuple[str, ast.expr | None, str | None]]:
        """Each (module, type, Annotated dependency or None) an annotation can mean."""
        if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
            try:
                ann = ast.parse(ann.value, mode="eval").body
            except SyntaxError:
                return [(label, ann, None)]
        if isinstance(ann, ast.Subscript) and self._typing_name(label, ann.value) == "Annotated":
            elts = ann.slice.elts if isinstance(ann.slice, ast.Tuple) else [ann.slice]
            dep = None
            for elt in elts[1:]:
                if call := self._depends_call(label, elt):
                    self.bound.add(id(call))
                    # FastAPI runs the last one (`fastapi_specific_annotations[-1]`).
                    dep = self._dep_target(label, call) or UNREADABLE
            return [(label, elts[0], dep)]
        if isinstance(ann, ast.Name) and (label, ann.id) not in seen:
            if bound := self._resolve(label, ann.id):
                return [
                    r
                    for def_label, value in bound
                    for r in self._readings(def_label, value, seen | {(label, ann.id)})
                ]
        return [(label, ann, None)]

    def _typing_name(self, label: str, node: ast.expr) -> str | None:
        """`Optional` for `Optional`, `typing.Optional` and `Opt` from `import Optional as Opt`."""
        name = _name(node)
        if isinstance(node, ast.Name) and name is not None:
            return self.renames.get((label, name), name)
        return name

    def admits_none(
        self, label: str, ann: ast.expr | None, seen: frozenset[tuple[str, str]] = frozenset()
    ) -> bool:
        """Whether a type annotation lets None through. Missing counts as no."""
        if ann is None:
            return False
        if isinstance(ann, ast.Constant):
            if ann.value is None:
                return True
            if isinstance(ann.value, str):
                try:
                    return self.admits_none(label, ast.parse(ann.value, mode="eval").body, seen)
                except SyntaxError:
                    return False
            return False
        if isinstance(ann, ast.BinOp) and isinstance(ann.op, ast.BitOr):
            return self.admits_none(label, ann.left, seen) or self.admits_none(
                label, ann.right, seen
            )
        if isinstance(ann, ast.Subscript):
            base = self._typing_name(label, ann.value)
            elts = ann.slice.elts if isinstance(ann.slice, ast.Tuple) else [ann.slice]
            if base == "Optional":
                return True
            if base == "Union":
                return any(self.admits_none(label, e, seen) for e in elts)
            if base == "Annotated":
                return self.admits_none(label, elts[0], seen)
            return False
        if isinstance(ann, ast.Name) and (label, ann.id) not in seen:
            bound = self._resolve(label, ann.id)
            return bool(bound) and all(
                self.admits_none(def_label, value, seen | {(label, ann.id)})
                for def_label, value in bound
            )
        return False

    def returns_none(self, label: str, fn: _Func) -> bool:
        """Whether a dependency's value can be None. A generator's value is what it yields."""
        ret = fn.returns
        if isinstance(ret, ast.Subscript) and self._typing_name(label, ret.value) in _GENERATORS:
            ret = ret.slice.elts[0] if isinstance(ret.slice, ast.Tuple) else ret.slice
        return self.admits_none(label, ret)

    def depends_params(
        self, label: str, fn: _Func
    ) -> Iterator[tuple[ast.arg, str, ast.expr | None, str]]:
        """(param, its type's module, its type, its dependency) for every Depends-filled param."""
        a = fn.args
        positional = a.posonlyargs + a.args
        defaults: list[ast.expr | None] = [None] * (len(positional) - len(a.defaults))
        defaults += a.defaults
        pairs = list(zip(positional, defaults, strict=True))
        pairs += list(zip(a.kwonlyargs, a.kw_defaults, strict=True))
        for arg, default in pairs:
            default_deps = self._default_deps(label, default)
            for type_label, typ, ann_dep in self._readings(label, arg.annotation):
                for dep in default_deps or ([ann_dep] if ann_dep else []):
                    yield arg, type_label, typ, dep

    def run(self) -> ScanResult:
        """Find the None dependencies, then every param and wrapper that hides one."""
        # A `-> None` dependency is a check or a side effect: nobody gets a user from it.
        # Names are global here, so a name only counts when EVERY def of it is `-> None`;
        # another module's same-named real dependency keeps it checked.
        defs: dict[str, list[_Func]] = defaultdict(list)
        for _, fn in self.funcs:
            defs[self._dep_name(fn)].append(fn)
        side_effect = {name for name, fns in defs.items() if all(map(_returns_exactly_none, fns))}
        none_deps = (
            set(self.known)
            | {spelled for spelled, admits in EXTERNAL_INSTANCES.items() if admits}
            | {
                self._dep_name(fn)
                for label, fn in self.funcs
                if self._dep_name(fn) not in side_effect and self.returns_none(label, fn)
            }
        )
        used = {dep for label, fn in self.funcs for *_, dep in self.depends_params(label, fn)}
        findings: list[Finding] = []

        # A wrapper dependency fed by a None dependency either admits None in its
        # own return type (picked up above) or raises on None. Otherwise it's
        # lying, and its consumers get the None anyway. Loop for wrappers of wrappers.
        changed = True
        while changed:
            changed = False
            for label, fn in self.funcs:
                name = self._dep_name(fn)
                if name not in used or name in none_deps or name in side_effect:
                    continue
                fed = [
                    (arg, dep)
                    for arg, _, _, dep in self.depends_params(label, fn)
                    if dep in none_deps
                ]
                if fed and not all(_raises_on_none(fn, arg.arg) for arg, _ in fed):
                    findings.append(Finding(label, fn.lineno, name, "return", fed[0][1]))
                    none_deps.add(name)
                    changed = True

        for label, fn in self.funcs:
            for arg, type_label, typ, dep in self.depends_params(label, fn):
                if dep == UNREADABLE or (
                    dep in none_deps and not self.admits_none(type_label, typ)
                ):
                    findings.append(Finding(label, arg.lineno, self._dep_name(fn), arg.arg, dep))

        # An unreadable Depends that feeds no param (a `dependencies=[...]` list, an
        # unused alias) still fails, so a new form can't slip in anywhere.
        owner: dict[int, str] = {}
        for _, fn in self.funcs:  # outer defs come first, so the innermost one wins
            owner.update((id(n), self._dep_name(fn)) for n in ast.walk(fn))
        for label, tree in self.trees.items():
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.expr)
                    and (call := self._depends_call(label, node))
                    and id(call) not in self.bound
                    and self._dep_target(label, call) is None
                ):
                    where = owner.get(id(call), "<module>")
                    findings.append(Finding(label, call.lineno, where, "", UNREADABLE))

        # The instrument check: every Depends on a None dependency should be one we
        # read as a param, or sit in a `dependencies=[...]` list where no param exists.
        in_dependencies_kw: set[int] = set()
        for tree in self.trees.values():
            for node in ast.walk(tree):
                if isinstance(node, ast.keyword) and node.arg == "dependencies":
                    in_dependencies_kw.update(id(n) for n in ast.walk(node.value))
        unbound = [
            f"{label}:{node.lineno}"
            for label, tree in self.trees.items()
            for node in ast.walk(tree)
            if isinstance(node, ast.expr)
            and (call := self._depends_call(label, node))
            and self._dep_target(label, call) in none_deps
            and id(call) not in self.bound
            and id(call) not in in_dependencies_kw
        ]
        return ScanResult(sorted(set(findings)), sorted(unbound), frozenset(none_deps))


def scan(sources: Mapping[str, str], known: frozenset[str] = KNOWN_NONE_DEPS) -> ScanResult:
    """Scan `{label: source}` for params and wrappers that hide a None."""
    return _Scanner(sources, known).run()


def _app_sources() -> dict[str, str]:
    return {str(f.relative_to(APP_DIR)): f.read_text() for f in sorted(APP_DIR.rglob("*.py"))}


class TestAppTree:
    """The real code."""

    def test_params_fed_by_a_none_dependency_admit_none(self) -> None:
        findings = scan(_app_sources()).findings
        if findings:
            lines = "\n".join(f"  {f}" for f in findings)
            pytest.fail(
                f"{len(findings)} spots take a dependency that returns None when auth "
                f"is off, but are typed as if it can't:\n{lines}\n"
                f"A param: type it `User | None` and handle the None. A `return` line "
                f"is a dependency that takes one of these and returns a type without "
                f"None: type its return `... | None`, or raise on a None user at the top "
                f"(`if u is None: raise ...`). An unreadable one: use a plain function, "
                f"or teach the scanner that form (an outside instance goes in "
                f"EXTERNAL_INSTANCES).",
                pytrace=False,
            )

    def test_every_none_dependency_call_is_read(self) -> None:
        """Guards the guard: a Depends form the scanner can't read would pass silently."""
        unbound = scan(_app_sources()).unbound
        assert not unbound, (
            f"Depends calls on a None dependency the scanner couldn't tie to a "
            f"param: {unbound}. Teach it that form."
        )

    def test_known_none_deps_still_return_none(self) -> None:
        """The hand-written list goes stale if one is renamed or starts raising."""
        scanner = _Scanner(_app_sources())
        defined = {
            fn.name: (label, fn) for label, fn in scanner.funcs if fn.name in KNOWN_NONE_DEPS
        }
        assert set(defined) == KNOWN_NONE_DEPS
        assert all(scanner.returns_none(label, fn) for label, fn in defined.values())


def _lies(src: str) -> set[tuple[str, str]]:
    """(function, param) for every finding in one snippet."""
    result = scan({"snippet.py": src})
    assert not result.unbound, result.unbound
    return {(f.function, f.param) for f in result.findings}


class TestScannerForms:
    """Snippets for each form, because a scanner that can't read one passes everything."""

    @pytest.mark.parametrize(
        ("src", "expected"),
        [
            pytest.param(
                """
async def lies(u: User = Depends(require_auth)): ...
async def honest(u: User | None = Depends(require_auth)): ...
""",
                {("lies", "u")},
                id="default-form",
            ),
            pytest.param(
                """
async def lies(u: Annotated[User, Depends(get_current_admin_user)]): ...
async def honest(u: Annotated[User | None, Depends(get_current_admin_user)]): ...
async def typing_attr(u: typing.Annotated[User, fastapi.Depends(require_auth)]): ...
async def quoted(u: "Annotated[User, Depends(require_auth)]"): ...
""",
                {("lies", "u"), ("typing_attr", "u"), ("quoted", "u")},
                id="annotated-form",
            ),
            pytest.param(
                """
async def doc_first(u: Annotated[User, Doc("x"), Depends(require_auth)]): ...
""",
                {("doc_first", "u")},
                id="annotated-depends-not-second",
            ),
            pytest.param(
                """
async def attr(u: User = fastapi.Depends(auth.optional_auth)): ...
async def sec(u: User = Security(require_auth, scopes=["x"])): ...
async def kw(u: User = Depends(dependency=require_auth)): ...
async def kwonly(vin: str, *, u: User = Depends(require_auth)): ...
async def posonly(vin: str, u: User = Depends(require_auth), /): ...
async def untyped(u=Depends(require_auth)): ...
""",
                {
                    ("attr", "u"),
                    ("sec", "u"),
                    ("kw", "u"),
                    ("kwonly", "u"),
                    ("posonly", "u"),
                    ("untyped", "u"),
                },
                id="call-shapes-and-param-kinds",
            ),
            pytest.param(
                """
async def a(u: Optional[User] = Depends(require_auth)): ...
async def b(u: Union[User, None] = Depends(require_auth)): ...
async def c(u: "User | None" = Depends(require_auth)): ...
async def d(u: None | User = Depends(require_auth)): ...
async def e(u: typing.Optional[User] = Depends(require_auth)): ...
async def f(u: Annotated[User | None, "meta"] = Depends(require_auth)): ...
async def g(u: Annotated["User | None", "meta"] = Depends(require_auth)): ...
""",
                set(),
                id="none-spellings-pass",
            ),
            pytest.param(
                """
async def a(u: User | Admin = Depends(require_auth)): ...
async def b(u: Union[User, Admin] = Depends(require_auth)): ...
async def c(u: Annotated["User", "meta"] = Depends(require_auth)): ...
""",
                {("a", "u"), ("b", "u"), ("c", "u")},
                id="none-spellings-fail",
            ),
            pytest.param(
                """
CurrentUser = Annotated[User, Depends(require_auth)]
MaybeUser = Annotated[User | None, Depends(require_auth)]
type AdminUser = Annotated[User, Depends(get_current_admin_user)]
UserDep = Depends(require_auth)
OptUser = User | None
async def a(u: CurrentUser): ...
async def b(u: MaybeUser): ...
async def c(u: AdminUser): ...
async def d(u: User = UserDep): ...
async def e(u: OptUser = Depends(require_auth)): ...
""",
                {("a", "u"), ("c", "u"), ("d", "u")},
                id="aliases",
            ),
            pytest.param(
                """
if TYPE_CHECKING:
    HiddenUser = Annotated[User, Depends(require_auth)]
try:
    TriedUser = Annotated[User, Depends(require_auth)]
except ImportError:
    pass
async def h(u: HiddenUser): ...
async def t(u: TriedUser): ...
""",
                {("h", "u"), ("t", "u")},
                id="aliases-under-if-and-try",
            ),
            pytest.param(
                """
from fastapi import Depends as D
from app.services.auth import require_auth as ra
auth_dep = require_auth
async def a(u: User = D(require_auth)): ...
async def b(u: User = Depends(ra)): ...
async def c(u: User = Depends(auth_dep)): ...
async def ok(u: User | None = D(ra)): ...
""",
                {("a", "u"), ("b", "u"), ("c", "u")},
                id="renamed-imports-and-name-aliases",
            ),
            pytest.param(
                """
security = HTTPBearer(auto_error=False)
async def get_current_user() -> User: ...
def token(c: Creds | None = Depends(security)) -> str | None: ...
async def stream() -> AsyncGenerator[Session | None]:
    yield None
async def a(t: str = Depends(token)): ...
async def b(s: Session = Depends(stream)): ...
async def c(u: User = Depends(get_current_user)): ...
""",
                {("a", "t"), ("b", "s")},
                id="derived-from-return-type",
            ),
            pytest.param(
                """
async def get_db() -> AsyncIterator[Session]: ...
async def gate(db: Session = Depends(get_db)) -> None:
    if not await enabled(db):
        raise HTTPException(status_code=400)
async def a(_=Depends(gate)): ...
async def b(_: None = Depends(gate)): ...
""",
                set(),
                id="side-effect-deps-are-not-none-deps",
            ),
            pytest.param(
                """
from functools import partial
async def lies(u: User = Depends(partial(require_auth))): ...
async def ann(u: Annotated[User, Depends(partial(require_auth, strict=True))]): ...
async def honest(u: User | None = Depends(partial(require_auth))): ...
""",
                {("lies", "u"), ("ann", "u")},
                id="partial",
            ),
            pytest.param(
                """
import functools
async def lies(u: User = Depends(functools.partial(require_auth))): ...
async def honest(u: User | None = Depends(functools.partial(require_auth))): ...
""",
                {("lies", "u")},
                id="functools-partial",
            ),
            pytest.param(
                """
class MaybeUser:
    async def __call__(self, request: Request) -> User | None: ...
class SureUser:
    async def __call__(self, request: Request) -> User: ...
maybe_user = MaybeUser()
async def lies(u: User = Depends(MaybeUser())): ...
async def lies_by_name(u: User = Depends(maybe_user)): ...
async def honest(u: User | None = Depends(MaybeUser())): ...
async def sure(u: User = Depends(SureUser())): ...
""",
                {("lies", "u"), ("lies_by_name", "u")},
                id="class-instances",
            ),
            pytest.param(
                """
security = HTTPBearer(auto_error=False)
async def lies(c: HTTPAuthorizationCredentials = Depends(security)): ...
async def inline(c: HTTPAuthorizationCredentials = Depends(HTTPBearer(auto_error=False))): ...
async def honest(c: HTTPAuthorizationCredentials | None = Depends(security)): ...
""",
                {("lies", "c"), ("inline", "c")},
                id="outside-instance-that-admits-none",
            ),
            pytest.param(
                """
async def get_db() -> AsyncIterator[Session]: ...
async def lies(u: Annotated[User, Depends(get_db), Depends(require_auth)]): ...
async def honest(u: Annotated[User | None, Depends(get_db), Depends(require_auth)]): ...
async def first_only(u: Annotated[User, Depends(require_auth), Depends(get_db)]): ...
""",
                {("lies", "u")},
                id="annotated-runs-the-last-depends",
            ),
        ],
    )
    def test_forms(self, src: str, expected: set[tuple[str, str]]) -> None:
        assert _lies(src) == expected


class TestScannerWrappers:
    """A dependency wrapping a None dependency is one too, unless it raises on None."""

    def test_wrapper_that_admits_none_passes_it_on(self) -> None:
        src = """
async def actor(u: User | None = Depends(require_auth)) -> User | None:
    return u
async def route(a: User = Depends(actor)): ...
async def ok(a: User | None = Depends(actor)): ...
"""
        assert _lies(src) == {("route", "a")}

    def test_wrapper_that_drops_the_none_is_flagged_and_so_are_its_consumers(self) -> None:
        src = """
async def actor(u: User | None = Depends(require_auth)) -> User:
    return u
async def route(a: User = Depends(actor)): ...
"""
        assert _lies(src) == {("actor", "return"), ("route", "a")}

    def test_wrappers_of_wrappers(self) -> None:
        # w2 comes first, so one pass in source order would miss it.
        src = """
async def w2(u: User | None = Depends(w1)) -> User: ...
async def w1(u: User | None = Depends(require_auth)) -> User: ...
async def route(x: User = Depends(w2)): ...
"""
        assert _lies(src) == {("w1", "return"), ("w2", "return"), ("route", "x")}

    def test_wrapper_that_raises_on_none_is_honest(self) -> None:
        src = '''
async def actor(u: User | None = Depends(require_auth)) -> User:
    if u is None:
        raise HTTPException(status_code=401)
    return u
async def actor2(u: User | None = Depends(require_auth)) -> User:
    """Doc."""
    if not u:
        logger.info("nope")
        raise HTTPException(status_code=401)
    return u
async def route(a: User = Depends(actor), b: User = Depends(actor2)): ...
'''
        assert _lies(src) == set()

    def test_a_guard_after_a_return_does_not_count(self) -> None:
        src = """
async def actor(u: User | None = Depends(require_auth)) -> User:
    if flag:
        return u
    if u is None:
        raise HTTPException(status_code=401)
    return u
async def route(a: User = Depends(actor)): ...
"""
        assert _lies(src) == {("actor", "return"), ("route", "a")}

    def test_a_guard_on_something_else_does_not_count(self) -> None:
        src = """
async def actor(u: User | None = Depends(require_auth)) -> User:
    if not u.is_admin:
        raise HTTPException(status_code=403)
    return u
async def route(a: User = Depends(actor)): ...
"""
        assert _lies(src) == {("actor", "return"), ("route", "a")}

    def test_a_none_check_that_does_not_raise_does_not_count(self) -> None:
        src = """
async def actor(u: User | None = Depends(require_auth)) -> User:
    if u is None:
        logger.warning("no user")
    return u
async def route(a: User = Depends(actor)): ...
"""
        assert _lies(src) == {("actor", "return"), ("route", "a")}

    def test_a_side_effect_wrapper_is_not_a_lying_wrapper(self) -> None:
        src = """
async def zone(u: User | None = Depends(require_auth)) -> None:
    set_zone(u)
async def route(_: None = Depends(zone)): ...
"""
        assert _lies(src) == set()

    def test_a_callable_class_can_be_a_lying_wrapper(self) -> None:
        src = """
class Gate:
    async def __call__(self, u: User | None = Depends(require_auth)) -> User:
        return u
async def route(a: User = Depends(Gate())): ...
"""
        assert _lies(src) == {("Gate.__call__", "return"), ("route", "a")}

    def test_a_route_is_not_a_wrapper(self) -> None:
        # Nothing depends on a route handler, so its return type isn't a promise about None.
        src = """
@router.get("/x")
async def handler(u: User | None = Depends(require_auth)) -> VehicleResponse: ...
"""
        assert _lies(src) == set()


class TestScannerUnbound:
    """The instrument check itself."""

    def test_reports_a_depends_it_cannot_tie_to_a_param(self) -> None:
        src = """
@router.get("/x", dependencies=[Depends(require_auth)])
async def a(): ...
async def b(u: User = wrap(Depends(require_auth))): ...
"""
        result = scan({"snippet.py": src})
        assert result.unbound == ["snippet.py:4"]


class TestScannerUnreadable:
    """A Depends argument the scanner can't read is a finding, typed honestly or not."""

    def test_a_dependency_it_cannot_read_is_a_finding(self) -> None:
        # make_dep() hands back a lambda, so nobody can say what it returns.
        src = """
def make_dep():
    return lambda: None
made = make_dep()
class NoCall: ...
async def lies(u: User = Depends(make_dep())): ...
async def honest(u: User | None = Depends(make_dep())): ...
async def lam(u: User | None = Depends(lambda: None)): ...
async def by_name(u: User | None = Depends(made)): ...
async def no_call(u: User | None = Depends(NoCall())): ...
async def outside(k: str | None = Depends(APIKeyHeader(name="k"))): ...
async def flag(c: Creds | None = Depends(HTTPBearer(auto_error=strict))): ...
async def ann(u: Annotated[User | None, Depends(partial())]): ...
@router.get("/x", dependencies=[Depends(make_dep())])
async def listed(): ...
async def ann_last(u: Annotated[User | None, Depends(require_auth), Depends(lambda: 1)]): ...
"""
        result = scan({"snippet.py": src})
        assert {(f.function, f.param) for f in result.findings} == {
            ("lies", "u"),
            ("honest", "u"),
            ("lam", "u"),
            ("by_name", "u"),
            ("no_call", "u"),
            ("outside", "k"),
            ("flag", "c"),
            ("ann", "u"),
            ("listed", ""),
            ("ann_last", "u"),
        }
        assert {f.dep for f in result.findings} == {UNREADABLE}

    def test_a_name_it_cannot_place_is_unreadable(self) -> None:
        # Each of these used to read as a function with that name, so nothing matched.
        src = """
from somelib import current_user_optional
dep = get_db
async def get_db() -> AsyncIterator[Session]: ...
class MaybeUser:
    async def __call__(self) -> User | None: ...
def make(dep):
    async def shadowed(u: User = Depends(dep)): ...
    return shadowed
def make2(d2):
    async def closure(u: User = Depends(d2)): ...
    return closure
def holder():
    held = MaybeUser()
    async def local_var(u: User = Depends(held)): ...
    return local_var
async def outside(u: User = Depends(current_user_optional)): ...
async def attr(c: Creds = Depends(somelib.security)): ...
"""
        result = scan({"snippet.py": src})
        assert {(f.function, f.param) for f in result.findings} == {
            ("shadowed", "u"),
            ("closure", "u"),
            ("local_var", "u"),
            ("outside", "u"),
            ("attr", "c"),
        }
        assert {f.dep for f in result.findings} == {UNREADABLE}

    def test_bindings_that_disagree_are_unreadable(self) -> None:
        # Whichever one runs, the scanner can't pick, so it says so.
        src = """
class MaybeUser:
    async def __call__(self) -> User | None: ...
class SureUser:
    async def __call__(self) -> User: ...
if FLAG:
    either = SureUser()
else:
    either = MaybeUser()
async def either_way(u: User | None = Depends(either)): ...
"""
        result = scan({"snippet.py": src})
        assert [(f.function, f.param, f.dep) for f in result.findings] == [
            ("either_way", "u", UNREADABLE)
        ]

    def test_readable_forms_are_not_unreadable(self) -> None:
        # Bare Depends() builds the annotation's class, which is never None.
        src = """
class Paging: ...
async def get_db() -> AsyncIterator[Session]: ...
security = HTTPBearer(auto_error=False)
bearer = security
async def a(p: Paging = Depends()): ...
async def b(p: Annotated[Paging, Depends()]): ...
async def c(p: Paging = Depends(Paging)): ...
async def d(c: Creds | None = Depends(bearer)): ...
async def e(db: Session = Depends(get_db)): ...
"""
        assert _lies(src) == set()


class TestScannerModules:
    """A name means what its own module, or the module it's imported from, says."""

    def test_an_alias_only_counts_where_it_is_defined_or_imported(self) -> None:
        result = scan(
            {
                "a.py": "Foo = User | None\n",
                "b.py": "async def route(u: Foo = Depends(require_auth)): ...\n",
                "c.py": "from app.a import Foo\nasync def ok(u: Foo = Depends(require_auth)): ...\n",
                "d/e.py": "from ..a import Foo\nasync def rel(u: Foo = Depends(require_auth)): ...\n",
            }
        )
        assert {(f.file, f.function) for f in result.findings} == {("b.py", "route")}

    def test_a_re_exported_rename_is_followed(self) -> None:
        result = scan(
            {
                "deps.py": "from app.services.auth import require_auth as ra\n",
                "routes.py": "from app.deps import ra\nasync def r(u: User = Depends(ra)): ...\n",
            }
        )
        assert {(f.file, f.function) for f in result.findings} == {("routes.py", "r")}

    def test_a_same_named_side_effect_dep_does_not_hide_a_real_one(self) -> None:
        result = scan(
            {
                "a.py": (
                    "async def get_db() -> AsyncIterator[Session]: ...\n"
                    "async def actor(db: Session = Depends(get_db)) -> None: ...\n"
                ),
                "b.py": (
                    "async def actor(u: User | None = Depends(require_auth)) -> User | None:\n"
                    "    return u\n"
                    "async def route(x: User = Depends(actor)): ...\n"
                ),
            }
        )
        assert {(f.file, f.function) for f in result.findings} == {("b.py", "route")}

    def test_an_instance_read_through_its_module_is_followed(self) -> None:
        result = scan(
            {
                "services/auth.py": "security = HTTPBearer(auto_error=False)\n",
                "routes.py": (
                    "from app.services import auth\n"
                    "async def lies(c: Creds = Depends(auth.security)): ...\n"
                    "async def honest(c: Creds | None = Depends(auth.security)): ...\n"
                ),
                "other.py": (
                    "import app.services.auth as a\n"
                    "async def aliased(c: Creds = Depends(a.security)): ...\n"
                ),
            }
        )
        assert {(f.file, f.function, f.dep) for f in result.findings} == {
            ("routes.py", "lies", "HTTPBearer(auto_error=False)"),
            ("other.py", "aliased", "HTTPBearer(auto_error=False)"),
        }

    def test_an_imported_annotated_alias_is_read(self) -> None:
        result = scan(
            {
                "deps.py": "CurrentUser = Annotated[User, Depends(require_auth)]\n",
                "routes.py": "from app.deps import CurrentUser\nasync def r(u: CurrentUser): ...\n",
            }
        )
        assert {(f.file, f.function) for f in result.findings} == {("routes.py", "r")}
        assert result.unbound == []


class TestScannerNames:
    """Where a name or an attribute actually comes from, not what it's called."""

    def test_an_attribute_on_a_closure_param_or_local_is_unreadable(self) -> None:
        # `check` is a real def here, but `svc.check` is whatever svc got handed.
        src = """
async def check() -> User | None: ...
def make(svc):
    async def closure(u: User | None = Depends(svc.check)): ...
    return closure
def holder():
    svc = Service()
    async def local_var(u: User | None = Depends(svc.check)): ...
    return local_var
"""
        result = scan({"snippet.py": src})
        assert {(f.function, f.param, f.dep) for f in result.findings} == {
            ("closure", "u", UNREADABLE),
            ("local_var", "u", UNREADABLE),
        }

    def test_an_outside_import_is_not_the_apps_def_of_that_name(self) -> None:
        result = scan(
            {
                "checks.py": "async def check() -> User | None: ...\n",
                "routes.py": (
                    "from somelib import check\n"
                    "import otherlib\n"
                    "async def named(u: User | None = Depends(check)): ...\n"
                    "async def attr(u: User | None = Depends(otherlib.check)): ...\n"
                ),
            }
        )
        assert {(f.file, f.function, f.dep) for f in result.findings} == {
            ("routes.py", "named", UNREADABLE),
            ("routes.py", "attr", UNREADABLE),
        }

    def test_class_body_names_stay_out_of_its_methods(self) -> None:
        # Inside build(), `check` is the module's, as in Python. A default on a
        # method itself runs in the class body, where it's the method.
        src = """
async def check() -> User | None: ...
class Routes:
    def check(self): ...
    def build(self):
        async def route(u: User = Depends(check)): ...
        return route
    async def in_class_scope(self, u: User | None = Depends(check)): ...
"""
        result = scan({"snippet.py": src})
        assert {(f.function, f.param, f.dep) for f in result.findings} == {
            ("route", "u", "check"),
            ("in_class_scope", "u", UNREADABLE),
        }

    def test_a_renamed_optional_admits_none(self) -> None:
        src = """
from typing import Optional as Opt, Annotated as Ann
async def ok(u: Opt[User] = Depends(require_auth)): ...
async def ann(u: Ann[User, Depends(require_auth)]): ...
async def lies(u: User = Depends(require_auth)): ...
"""
        assert _lies(src) == {("ann", "u"), ("lies", "u")}

    def test_an_outside_class_by_name_points_at_the_way_out(self) -> None:
        src = """
from fastapi.security import OAuth2PasswordRequestForm
async def login(form: OAuth2PasswordRequestForm = Depends(OAuth2PasswordRequestForm)): ...
async def ok(form: Annotated[OAuth2PasswordRequestForm, Depends()]): ...
"""
        [finding] = scan({"snippet.py": src}).findings
        assert finding.function == "login"
        assert "Annotated[Cls, Depends()]" in str(finding)


class TestScannerModuleAttributes:
    """A Depends alias read off a scanned module."""

    def test_a_depends_alias_read_through_its_module_is_followed(self) -> None:
        result = scan(
            {
                "deps.py": "auth_dep = Depends(require_auth)\n",
                "routes.py": (
                    "from app import deps\n"
                    "async def lies(u: User = deps.auth_dep): ...\n"
                    "async def honest(u: User | None = deps.auth_dep): ...\n"
                ),
            }
        )
        assert {(f.file, f.function) for f in result.findings} == {("routes.py", "lies")}
        assert result.unbound == []
