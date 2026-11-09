"""Every FixedRuleError in the app is built from a plain string literal.

The validation-error handler shows a FixedRuleError's message even on a field
named like a secret, because its text is fixed and can't hold the input. An
f-string, a format call or a variable could put the rejected value in it, and
the scrubber would echo it. So the rule is checked on the source (the AST,
not a regex), not left to the class's docstring.
"""

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
SCANNED = (BACKEND / "app", BACKEND / "tools")
CLASS_NAME = "FixedRuleError"


def _sources() -> list[Path]:
    return sorted(path for root in SCANNED for path in root.rglob("*.py"))


def _local_names(tree: ast.AST) -> set[str]:
    """The names the class goes by in this module, aliases included."""
    names = {CLASS_NAME}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(a.asname for a in node.names if a.name == CLASS_NAME and a.asname)
    return names


def _is_the_class(func: ast.expr, names: set[str]) -> bool:
    if isinstance(func, ast.Name):
        return func.id in names
    return isinstance(func, ast.Attribute) and func.attr == CLASS_NAME


def _is_plain_literal(call: ast.Call) -> bool:
    """One positional str constant and nothing else. Adjacent literals parse as one."""
    if call.keywords or len(call.args) != 1:
        return False
    (arg,) = call.args
    return isinstance(arg, ast.Constant) and isinstance(arg.value, str)


def _calls(text: str) -> list[tuple[int, bool]]:
    """Each construction of the class as (line, built from a plain literal)."""
    tree = ast.parse(text)
    names = _local_names(tree)
    return sorted(
        (node.lineno, _is_plain_literal(node))
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _is_the_class(node.func, names)
    )


def _bad(text: str) -> list[int]:
    return [line for line, plain in _calls(text) if not plain]


def test_the_scan_sees_the_password_rules() -> None:
    """So an empty result below means clean, not a wrong path or a missed name."""
    user = BACKEND / "app" / "schemas" / "user.py"

    assert user in _sources()
    assert len(_calls(user.read_text(encoding="utf-8"))) >= 5


@pytest.mark.parametrize(
    "source",
    [
        'raise FixedRuleError(f"{v!r} is not allowed")',
        'raise FixedRuleError("Password %s is weak" % v)',
        'raise FixedRuleError("Password {} is weak".format(v))',
        'raise FixedRuleError("Password " + v)',
        "raise FixedRuleError(message)",
        "raise FixedRuleError()",
        'raise FixedRuleError("Too short", v)',
        'raise FixedRuleError(msg="Too short")',
        'error = FixedRuleError(f"{v}")\nraise error',
        'raise validation_errors.FixedRuleError(f"{v}")',
        'from app.utils.validation_errors import FixedRuleError as Rule\nraise Rule(f"{v}")',
    ],
)
def test_anything_but_a_plain_literal_is_caught(source: str) -> None:
    assert _bad(source)


@pytest.mark.parametrize(
    "source",
    [
        'raise FixedRuleError("Password must contain at least one digit")',
        'raise FixedRuleError(\n    "Password must be at least "\n    "8 characters long"\n)',
        'raise ValueError(f"{v!r} is not allowed")',
    ],
)
def test_plain_literals_and_other_errors_pass(source: str) -> None:
    assert _bad(source) == []


def test_every_fixed_rule_error_in_the_app_is_a_plain_literal() -> None:
    hits = [
        f"{path.relative_to(BACKEND)}:{line}"
        for path in _sources()
        for line in _bad(path.read_text(encoding="utf-8"))
    ]

    assert hits == []
