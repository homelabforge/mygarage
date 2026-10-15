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
module says, or what the scanned module it's imported from says. Class-instance
dependencies (`Depends(SomeChecker())`) and `Depends(partial(...))` stay blind;
nothing in app/ uses them.
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

_DEPENDS = frozenset({"Depends", "Security"})
_GENERATORS = frozenset({"Generator", "AsyncGenerator", "Iterator", "AsyncIterator"})

type _Func = ast.FunctionDef | ast.AsyncFunctionDef


class Finding(NamedTuple):
    """One spot where a None can arrive but the type says it can't."""

    file: str
    line: int
    function: str
    #: The param's name, or "return" for a wrapper whose return type drops the None.
    param: str
    dep: str

    def __str__(self) -> str:
        """One line for the failure message."""
        where = f"{self.file}:{self.line} {self.function}"
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


class _Scanner:
    """One pass over a set of sources. Labels show up in findings as file names."""

    def __init__(self, sources: Mapping[str, str]) -> None:
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
        # Depends calls we managed to tie to a param, by node id.
        self.bound: set[int] = set()

    def _source_label(self, label: str, stmt: ast.ImportFrom) -> str | None:
        """The scanned module a `from ... import` reads, or None if it isn't one."""
        if stmt.level:
            if stmt.module is None:
                return None
            base = PurePosixPath(label).parent
            for _ in range(stmt.level - 1):
                base = base.parent
            parts = [*base.parts, *stmt.module.split(".")]
        elif stmt.module and stmt.module.startswith("app."):
            parts = stmt.module.split(".")[1:]
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
        key = (label, name)
        if key in seen:
            return name
        seen = seen | {key}
        if key in self.imports:
            # Imported from a scanned module: ask that module what its name is.
            return self._target_name(*self.imports[key], seen)
        if key in self.renames:
            # `from outside import f as g`: g is f.
            return self.renames[key]
        for value in self.aliases.get(key, []):
            if isinstance(value, ast.Name | ast.Attribute) and (inner := _name(value)):
                return self._target_name(label, inner, seen)
        return name

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
        """The dependency a Depends call names, positional or `dependency=`, resolved."""
        node: ast.expr | None = call.args[0] if call.args else None
        if node is None:
            node = next((kw.value for kw in call.keywords if kw.arg == "dependency"), None)
        name = _name(node)
        return self._target_name(label, name) if name else None

    def _default_deps(self, label: str, default: ast.expr | None) -> list[str]:
        """Dependencies named by a param's default: `Depends(f)`, or an alias of one."""
        calls: list[tuple[str, ast.Call]] = []
        if call := self._depends_call(label, default):
            calls = [(label, call)]
        elif isinstance(default, ast.Name):
            for def_label, value in self._resolve(label, default.id):
                if c := self._depends_call(def_label, value):
                    calls.append((def_label, c))
        deps: list[str] = []
        for def_label, c in calls:
            self.bound.add(id(c))
            if target := self._dep_target(def_label, c):
                deps.append(target)
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
        if isinstance(ann, ast.Subscript) and _name(ann.value) == "Annotated":
            elts = ann.slice.elts if isinstance(ann.slice, ast.Tuple) else [ann.slice]
            dep = None
            for elt in elts[1:]:
                if call := self._depends_call(label, elt):
                    self.bound.add(id(call))
                    dep = dep or self._dep_target(label, call)
            return [(label, elts[0], dep)]
        if isinstance(ann, ast.Name) and (label, ann.id) not in seen:
            if bound := self._resolve(label, ann.id):
                return [
                    r
                    for def_label, value in bound
                    for r in self._readings(def_label, value, seen | {(label, ann.id)})
                ]
        return [(label, ann, None)]

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
            base = _name(ann.value)
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
        if isinstance(ret, ast.Subscript) and _name(ret.value) in _GENERATORS:
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

    def run(self, known: frozenset[str]) -> ScanResult:
        """Find the None dependencies, then every param and wrapper that hides one."""
        # A `-> None` dependency is a check or a side effect: nobody gets a user from it.
        # Names are global here, so a name only counts when EVERY def of it is `-> None`;
        # another module's same-named real dependency keeps it checked.
        defs: dict[str, list[_Func]] = defaultdict(list)
        for _, fn in self.funcs:
            defs[fn.name].append(fn)
        side_effect = {name for name, fns in defs.items() if all(map(_returns_exactly_none, fns))}
        none_deps = set(known) | {
            fn.name
            for label, fn in self.funcs
            if fn.name not in side_effect and self.returns_none(label, fn)
        }
        used = {dep for label, fn in self.funcs for *_, dep in self.depends_params(label, fn)}
        findings: list[Finding] = []

        # A wrapper dependency fed by a None dependency either admits None in its
        # own return type (picked up above) or raises on None. Otherwise it's
        # lying, and its consumers get the None anyway. Loop for wrappers of wrappers.
        changed = True
        while changed:
            changed = False
            for label, fn in self.funcs:
                if fn.name not in used or fn.name in none_deps or fn.name in side_effect:
                    continue
                fed = [
                    (arg, dep)
                    for arg, _, _, dep in self.depends_params(label, fn)
                    if dep in none_deps
                ]
                if fed and not all(_raises_on_none(fn, arg.arg) for arg, _ in fed):
                    findings.append(Finding(label, fn.lineno, fn.name, "return", fed[0][1]))
                    none_deps.add(fn.name)
                    changed = True

        for label, fn in self.funcs:
            for arg, type_label, typ, dep in self.depends_params(label, fn):
                if dep in none_deps and not self.admits_none(type_label, typ):
                    findings.append(Finding(label, arg.lineno, fn.name, arg.arg, dep))

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
    return _Scanner(sources).run(known)


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
                f"(`if u is None: raise ...`).",
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
async def gate(db: Session = Depends(get_db)) -> None:
    if not await enabled(db):
        raise HTTPException(status_code=400)
async def a(_=Depends(gate)): ...
async def b(_: None = Depends(gate)): ...
""",
                set(),
                id="side-effect-deps-are-not-none-deps",
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
    return u  # type: ignore[return-value]
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
                "a.py": "async def actor(db: Session = Depends(get_db)) -> None: ...\n",
                "b.py": (
                    "async def actor(u: User | None = Depends(require_auth)) -> User | None:\n"
                    "    return u\n"
                    "async def route(x: User = Depends(actor)): ...\n"
                ),
            }
        )
        assert {(f.file, f.function) for f in result.findings} == {("b.py", "route")}

    def test_an_imported_annotated_alias_is_read(self) -> None:
        result = scan(
            {
                "deps.py": "CurrentUser = Annotated[User, Depends(require_auth)]\n",
                "routes.py": "from app.deps import CurrentUser\nasync def r(u: CurrentUser): ...\n",
            }
        )
        assert {(f.file, f.function) for f in result.findings} == {("routes.py", "r")}
        assert result.unbound == []
