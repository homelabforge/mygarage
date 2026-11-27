"""Auth-off and admin get the same reach, and that rule lives in one place.

`current_user is None` (auth_mode='none') and `current_user.is_admin` both mean
"no restriction". That got hand-written 19 times in four spellings, and a
copy that drops either half locks the default install out or hides the garage
from the admin. So `app/services/auth.py` has `restricted_user` and
`acts_as_admin`, and this walks app/ with the AST for anything that restates
the rule instead:

* a BoolOp (any length) with a None test of X beside an `X.is_admin` test, like
  `X is None or X.is_admin` or `X is not None and not X.is_admin and ...`
* `if X is None: return ...` right before `if X.is_admin: return ...`
* a None test of X beside `acts_as_admin(X)`, which already covers None
* any `.is_admin` read in app/services or app/routes outside the two helpers
  and `ALLOWED_FILES`. That's what catches a check where None was refused just
  above (`if X is None: raise sign_in_required(...)`), which is fine and stays.

Every site reports once, keyed on its `.is_admin` read (or the BoolOp when
there isn't one).
"""

import ast
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import NamedTuple

APP_DIR = Path(__file__).resolve().parents[2] / "app"

#: Where the helpers live. Their bodies are the one place the rule is spelled out.
HELPER_FILE = PurePosixPath("services/auth.py")
HELPERS = frozenset({"restricted_user", "acts_as_admin"})

#: Bare `.is_admin` reads only count under these, relative to app/.
READ_SCOPES = (PurePosixPath("services"), PurePosixPath("routes"))

#: Files whose `.is_admin` reads aren't caller checks: admin bookkeeping in user
#: management and OIDC provisioning.
ALLOWED_FILES = frozenset(
    {PurePosixPath("routes/auth.py"), PurePosixPath("services/oidc/users.py")}
)

BOOLOP = "None test beside an is_admin test"
IF_PAIR = "`if X is None: return` then `if X.is_admin: return`"
REDUNDANT = "None test beside acts_as_admin(X)"
BARE_READ = "is_admin read"


class Finding(NamedTuple):
    """One hand-written admin check."""

    file: str
    line: int
    form: str

    def __str__(self) -> str:
        """One line for the failure message."""
        return f"{self.file}:{self.line} ({self.form})"


def _key(node: ast.expr) -> str:
    """A comparable spelling of X, so `self.user` matches `self.user`."""
    return ast.dump(node)


def _is_admin_attr(node: ast.expr) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "is_admin"


def _none_only_subject(node: ast.expr) -> str | None:
    """X for `X is None` or `not X`: a test that's true only without a user."""
    if isinstance(node, ast.Compare) and isinstance(node.ops[0], ast.Is):
        return _none_subject(node)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return _none_subject(node)
    return None


def _none_subject(node: ast.expr) -> str | None:
    """X for `X is None`, `X is not None`, `not X` or a bare truthy `X`."""
    if isinstance(node, ast.Compare):
        if (
            len(node.ops) == 1
            and isinstance(node.ops[0], ast.Is | ast.IsNot)
            and isinstance(node.comparators[0], ast.Constant)
            and node.comparators[0].value is None
        ):
            return _key(node.left)
        return None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        node = node.operand
    if isinstance(node, ast.Name | ast.Attribute) and not _is_admin_attr(node):
        return _key(node)
    return None


def _admin_subject(node: ast.expr) -> tuple[str, ast.Attribute] | None:
    """X and the read for `X.is_admin` or `not X.is_admin`."""
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        node = node.operand
    if isinstance(node, ast.Attribute) and node.attr == "is_admin":
        return _key(node.value), node
    return None


def _acts_as_admin_subject(node: ast.expr) -> str | None:
    """X for `acts_as_admin(X)` or `not acts_as_admin(X)`, by name or attribute."""
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        node = node.operand
    if not isinstance(node, ast.Call) or len(node.args) != 1:
        return None
    func = node.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
    return _key(node.args[0]) if name == "acts_as_admin" else None


def _exits(body: list[ast.stmt]) -> bool:
    return bool(body) and isinstance(body[-1], ast.Return)


def _bodies(tree: ast.AST) -> Iterator[list[ast.stmt]]:
    """Every statement list, so an if pair is matched wherever it sits."""
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            stmts = getattr(node, field, None)
            if isinstance(stmts, list) and stmts and isinstance(stmts[0], ast.stmt):
                yield stmts
        if isinstance(node, ast.Try | ast.TryStar):
            for handler in node.handlers:
                yield handler.body
        if isinstance(node, ast.Match):
            for case in node.cases:
                yield case.body


def _helper_nodes(tree: ast.Module) -> set[int]:
    """ids of every node inside the helpers' own bodies."""
    inside: set[int] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name in HELPERS:
            inside.update(id(sub) for sub in ast.walk(node))
    return inside


def scan_source(source: str, rel: PurePosixPath) -> list[Finding]:
    """Every hand-written admin check in one module, `rel` relative to app/."""
    tree = ast.parse(source)
    skip = _helper_nodes(tree) if rel == HELPER_FILE else set()
    found: dict[int, str] = {}

    def report(line: int, form: str) -> None:
        # The first form wins, so a pattern beats the bare read on the same site.
        found.setdefault(line, form)

    for node in ast.walk(tree):
        if id(node) in skip or not isinstance(node, ast.BoolOp):
            continue
        none_tested = {s for v in node.values if (s := _none_subject(v)) is not None}
        for value in node.values:
            admin = _admin_subject(value)
            if admin is not None and admin[0] in none_tested:
                report(admin[1].lineno, BOOLOP)
            subject = _acts_as_admin_subject(value)
            if subject is not None and subject in none_tested:
                report(node.lineno, REDUNDANT)

    for stmts in _bodies(tree):
        for first, second in zip(stmts, stmts[1:], strict=False):
            if id(first) in skip or not (isinstance(first, ast.If) and isinstance(second, ast.If)):
                continue
            if first.orelse or not _exits(first.body) or not _exits(second.body):
                continue
            subject = _none_only_subject(first.test)
            admin = _admin_subject(second.test)
            if (
                subject is not None
                and admin is not None
                and admin[0] == subject
                and not isinstance(second.test, ast.UnaryOp)
            ):
                report(admin[1].lineno, IF_PAIR)

    if any(rel.is_relative_to(scope) for scope in READ_SCOPES) and rel not in ALLOWED_FILES:
        for node in ast.walk(tree):
            if (
                id(node) not in skip
                and isinstance(node, ast.Attribute)
                and node.attr == "is_admin"
                and isinstance(node.ctx, ast.Load)
            ):
                report(node.lineno, BARE_READ)

    return [Finding(str(rel), line, form) for line, form in sorted(found.items())]


def scan_tree(app_dir: Path = APP_DIR) -> list[Finding]:
    """Every hand-written admin check under app/, migrations aside."""
    findings: list[Finding] = []
    for path in sorted(app_dir.rglob("*.py")):
        rel = PurePosixPath(path.relative_to(app_dir).as_posix())
        if rel.parts[0] == "migrations":
            continue
        findings.extend(scan_source(path.read_text(encoding="utf-8"), rel))
    return findings


# --------------------------------------------------------------- self-tests

_UTILS = PurePosixPath("utils/x.py")
_SERVICE = PurePosixPath("services/x.py")


def _forms(source: str, rel: PurePosixPath = _UTILS) -> list[tuple[int, str]]:
    return [(f.line, f.form) for f in scan_source(source, rel)]


def test_reports_none_or_is_admin() -> None:
    src = "def f(u):\n    if u is None or u.is_admin:\n        return 1\n"
    assert _forms(src) == [(2, BOOLOP)]


def test_reports_not_none_and_not_admin_three_operands() -> None:
    src = (
        "def f(u, v):\n"
        "    if (\n"
        "        u is not None\n"
        "        and not u.is_admin\n"
        "        and v.user_id != u.id\n"
        "    ):\n"
        "        raise E\n"
    )
    assert _forms(src) == [(4, BOOLOP)]


def test_reports_truthy_and_not_admin() -> None:
    src = "def f(u):\n    if u and not u.is_admin:\n        pass\n"
    assert _forms(src) == [(2, BOOLOP)]


def test_reports_attribute_subject() -> None:
    src = "def f(self):\n    return self.user is None or self.user.is_admin\n"
    assert _forms(src) == [(2, BOOLOP)]


def test_ignores_is_admin_of_another_subject() -> None:
    src = "def f(u, w):\n    return u is None or w.is_admin\n"
    assert _forms(src) == []


def test_reports_if_pair() -> None:
    src = (
        "def f(u, v):\n"
        "    if u is None:\n"
        "        return v\n"
        "    if u.is_admin:\n"
        "        return v\n"
        "    return None\n"
    )
    assert _forms(src) == [(4, IF_PAIR)]


def test_sign_in_refusal_then_admin_check_is_not_a_pair() -> None:
    src = (
        "def f(u, v):\n"
        "    if u is None:\n"
        "        raise sign_in_required('x')\n"
        "    if u.is_admin:\n"
        "        return v\n"
    )
    assert _forms(src) == []


def test_reports_none_or_acts_as_admin() -> None:
    src = "def f(u):\n    return u is None or acts_as_admin(u)\n"
    assert _forms(src) == [(2, REDUNDANT)]


def test_reports_bare_read_in_services_only() -> None:
    src = (
        "def f(u):\n"
        "    if u is None:\n"
        "        raise sign_in_required('x')\n"
        "    if not u.is_admin:\n"
        "        raise E\n"
    )
    assert _forms(src, _UTILS) == []
    assert _forms(src, _SERVICE) == [(4, BARE_READ)]
    assert _forms(src, PurePosixPath("routes/x.py")) == [(4, BARE_READ)]
    assert _forms(src, PurePosixPath("routes/auth.py")) == []


def test_pattern_beats_bare_read_on_one_site() -> None:
    src = "def f(u):\n    return u is None or u.is_admin\n"
    assert _forms(src, _SERVICE) == [(2, BOOLOP)]


def test_helpers_are_not_reported() -> None:
    src = (
        "def f(u, v):\n"
        "    if (me := restricted_user(u)) is None:\n"
        "        return v\n"
        "    if not acts_as_admin(u):\n"
        "        raise E\n"
        "    return me.id\n"
    )
    assert _forms(src, _SERVICE) == []


def test_helper_bodies_are_skipped_in_auth_only() -> None:
    src = (
        "def restricted_user(user):\n"
        "    if user is None or user.is_admin:\n"
        "        return None\n"
        "    return user\n"
    )
    assert _forms(src, HELPER_FILE) == []
    assert _forms(src, _SERVICE) == [(2, BOOLOP)]


def test_app_has_no_hand_written_admin_checks() -> None:
    findings = scan_tree()
    assert not findings, (
        f"{len(findings)} hand-written admin check(s). Use restricted_user() when you "
        "read the user afterwards, acts_as_admin() when you don't (app/services/auth.py):\n"
        + "\n".join(str(f) for f in findings)
    )


def test_helpers_exist_where_the_scan_expects_them() -> None:
    tree = ast.parse((APP_DIR / HELPER_FILE).read_text(encoding="utf-8"))
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert names >= HELPERS
