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
"""

import ast
from collections import defaultdict
from collections.abc import Iterator, Mapping
from pathlib import Path
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


def _depends_call(node: ast.expr | None) -> ast.Call | None:
    """`node` if it's a `Depends(...)` / `Security(...)` call."""
    if isinstance(node, ast.Call) and _name(node.func) in _DEPENDS:
        return node
    return None


def _dep_target(call: ast.Call) -> str | None:
    """The dependency a Depends call names, positional or `dependency=`."""
    if call.args:
        return _name(call.args[0])
    for kw in call.keywords:
        if kw.arg == "dependency":
            return _name(kw.value)
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
        # Module-level names, for `CurrentUser = Annotated[...]` and friends.
        # A list, because the same name can be defined in two modules.
        self.aliases: dict[str, list[ast.expr]] = defaultdict(list)
        for tree in self.trees.values():
            for stmt in _module_level(tree.body):
                if (
                    isinstance(stmt, ast.Assign)
                    and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                ):
                    self.aliases[stmt.targets[0].id].append(stmt.value)
                elif (
                    isinstance(stmt, ast.AnnAssign)
                    and isinstance(stmt.target, ast.Name)
                    and stmt.value is not None
                ):
                    self.aliases[stmt.target.id].append(stmt.value)
                elif isinstance(stmt, ast.TypeAlias):
                    self.aliases[stmt.name.id].append(stmt.value)
        # Depends calls we managed to tie to a param, by node id.
        self.bound: set[int] = set()

    def _default_deps(self, default: ast.expr | None) -> list[str]:
        """Dependencies named by a param's default: `Depends(f)`, or an alias of one."""
        call = _depends_call(default)
        if call is None and isinstance(default, ast.Name):
            calls = [c for c in map(_depends_call, self.aliases.get(default.id, [])) if c]
        else:
            calls = [call] if call else []
        deps: list[str] = []
        for c in calls:
            self.bound.add(id(c))
            if target := _dep_target(c):
                deps.append(target)
        return deps

    def _readings(
        self, ann: ast.expr | None, seen: frozenset[str] = frozenset()
    ) -> list[tuple[ast.expr | None, str | None]]:
        """Each (type, Annotated dependency or None) an annotation can mean.

        More than one only when an alias name is defined twice.
        """
        if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
            try:
                ann = ast.parse(ann.value, mode="eval").body
            except SyntaxError:
                return [(ann, None)]
        if isinstance(ann, ast.Subscript) and _name(ann.value) == "Annotated":
            elts = ann.slice.elts if isinstance(ann.slice, ast.Tuple) else [ann.slice]
            dep = None
            for call in filter(None, map(_depends_call, elts[1:])):
                self.bound.add(id(call))
                dep = dep or _dep_target(call)
            return [(elts[0], dep)]
        if isinstance(ann, ast.Name) and ann.id in self.aliases and ann.id not in seen:
            return [r for d in self.aliases[ann.id] for r in self._readings(d, seen | {ann.id})]
        return [(ann, None)]

    def admits_none(self, ann: ast.expr | None, seen: frozenset[str] = frozenset()) -> bool:
        """Whether a type annotation lets None through. Missing counts as no."""
        if ann is None:
            return False
        if isinstance(ann, ast.Constant):
            if ann.value is None:
                return True
            if isinstance(ann.value, str):
                try:
                    return self.admits_none(ast.parse(ann.value, mode="eval").body, seen)
                except SyntaxError:
                    return False
            return False
        if isinstance(ann, ast.BinOp) and isinstance(ann.op, ast.BitOr):
            return self.admits_none(ann.left, seen) or self.admits_none(ann.right, seen)
        if isinstance(ann, ast.Subscript):
            base = _name(ann.value)
            elts = ann.slice.elts if isinstance(ann.slice, ast.Tuple) else [ann.slice]
            if base == "Optional":
                return True
            if base == "Union":
                return any(self.admits_none(e, seen) for e in elts)
            if base == "Annotated":
                return self.admits_none(elts[0], seen)
            return False
        if isinstance(ann, ast.Name) and ann.id in self.aliases and ann.id not in seen:
            return all(self.admits_none(d, seen | {ann.id}) for d in self.aliases[ann.id])
        return False

    def returns_none(self, fn: _Func) -> bool:
        """Whether a dependency's value can be None. A generator's value is what it yields."""
        ret = fn.returns
        if isinstance(ret, ast.Subscript) and _name(ret.value) in _GENERATORS:
            ret = ret.slice.elts[0] if isinstance(ret.slice, ast.Tuple) else ret.slice
        return self.admits_none(ret)

    def depends_params(self, fn: _Func) -> Iterator[tuple[ast.arg, ast.expr | None, str]]:
        """(param, its type, its dependency) for every param FastAPI fills from a Depends."""
        a = fn.args
        positional = a.posonlyargs + a.args
        defaults: list[ast.expr | None] = [None] * (len(positional) - len(a.defaults))
        defaults += a.defaults
        pairs = list(zip(positional, defaults, strict=True))
        pairs += list(zip(a.kwonlyargs, a.kw_defaults, strict=True))
        for arg, default in pairs:
            default_deps = self._default_deps(default)
            for typ, ann_dep in self._readings(arg.annotation):
                for dep in default_deps or ([ann_dep] if ann_dep else []):
                    yield arg, typ, dep

    def run(self, known: frozenset[str]) -> ScanResult:
        """Find the None dependencies, then every param and wrapper that hides one."""
        none_deps = set(known) | {fn.name for _, fn in self.funcs if self.returns_none(fn)}
        used = {dep for _, fn in self.funcs for _, _, dep in self.depends_params(fn)}
        findings: list[Finding] = []

        # A wrapper dependency fed by a None dependency either admits None in its
        # own return type (picked up above) or raises on None. Otherwise it's
        # lying, and its consumers get the None anyway. Loop for wrappers of wrappers.
        changed = True
        while changed:
            changed = False
            for label, fn in self.funcs:
                if fn.name not in used or fn.name in none_deps:
                    continue
                fed = [(arg, dep) for arg, _, dep in self.depends_params(fn) if dep in none_deps]
                if fed and not all(_raises_on_none(fn, arg.arg) for arg, _ in fed):
                    findings.append(Finding(label, fn.lineno, fn.name, "return", fed[0][1]))
                    none_deps.add(fn.name)
                    changed = True

        for label, fn in self.funcs:
            for arg, typ, dep in self.depends_params(fn):
                if dep in none_deps and not self.admits_none(typ):
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
            if (call := _depends_call(node if isinstance(node, ast.expr) else None))
            and _dep_target(call) in none_deps
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
                f"Type the param `User | None` (and handle the None), or make the "
                f"wrapper's return type admit None or raise on it.",
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
        defined = {fn.name: fn for _, fn in scanner.funcs if fn.name in KNOWN_NONE_DEPS}
        assert set(defined) == KNOWN_NONE_DEPS
        assert all(scanner.returns_none(fn) for fn in defined.values())


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
