"""Guards for `[tool.pyright]` and the suppression policy pyright can't enforce itself.

Typo guard: pyright prints "Config contains unrecognized setting" for a
misspelled key and then ignores it, exit code untouched. So every key here
has to be a name the installed pyright knows.

Policy guard: `# pyright: ignore[rule]  # reason` is the only suppression.
`# type: ignore` is inert (enableTypeIgnoreComments = false) and silent, a
bare ignore on a line with a real error isn't "unnecessary", and a file-level
pragma could switch a rule off for a whole file. Only the style rules may be
relaxed per file.
"""

from __future__ import annotations

import importlib.util
import io
import re
import tokenize
import tomllib
from functools import cache
from pathlib import Path
from typing import Any

import pytest

BACKEND = Path(__file__).resolve().parents[2]
PYPROJECT = BACKEND / "pyproject.toml"

#: Rules a file may relax with a pragma. Everything else stays project-wide.
STYLE_RULES = frozenset({"reportPrivateUsage", "reportUnusedFunction", "reportUnusedClass"})
MODE_WORDS = frozenset({"basic", "standard", "strict"})

# pyright's own pattern for an ignore comment (tokenizer.ts), so `#pyright:ignore`
# and `# noqa  # pyright: ignore[...]` count too.
_IGNORE = re.compile(r"(?:^|#)\s*pyright:\s*ignore(\[[\s\w\-,]*\]|\s|$)")
_TYPE_IGNORE = re.compile(r"type:\s*ignore")
_REASON = re.compile(r"^\s+#\s*\S")


@cache
def _bundle() -> str:
    """The installed pyright's checker bundle, where every setting name is a literal."""
    spec = importlib.util.find_spec("pyright")
    assert spec is not None and spec.origin is not None, "pyright isn't installed"
    bundle = Path(spec.origin).parent / "dist" / "dist" / "pyright-internal.js"
    # Fails rather than skips: a guard that never runs looks green.
    assert bundle.is_file(), f"pyright bundle not found at {bundle}"
    return bundle.read_text(encoding="utf-8")


def _known(name: str) -> bool:
    return f'"{name}"' in _bundle()


def _config() -> dict[str, Any]:
    with PYPROJECT.open("rb") as f:
        return tomllib.load(f)["tool"]["pyright"]


def _environments() -> list[dict[str, Any]]:
    return _config().get("executionEnvironments", [])


def _comments(source: str) -> list[tuple[int, str]]:
    """(line, text) for every comment token, so a string that looks like one isn't."""
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    return [(t.start[0], t.string) for t in tokens if t.type == tokenize.COMMENT]


def comment_problems(source: str) -> list[str]:
    """Every way the comments in `source` break the suppression policy."""
    problems: list[str] = []
    for line, comment in _comments(source):
        if _TYPE_IGNORE.search(comment):
            problems.append(
                f"line {line}: `# type: ignore` is inert here; use # pyright: ignore[rule]"
            )
        ignore = _IGNORE.search(comment)
        if ignore:
            bracket = ignore.group(1)
            if not bracket.startswith("["):
                problems.append(f"line {line}: a pyright ignore needs a [rule]")
                continue
            for rule in (r.strip() for r in bracket[1:-1].split(",")):
                if not rule or not _known(rule):
                    problems.append(f"line {line}: {rule!r} isn't a pyright rule")
            if not _REASON.match(comment[ignore.end() :]):
                problems.append(f"line {line}: a pyright ignore needs a `# reason` after it")
            continue
        for segment in comment.split("#"):
            text = segment.strip()
            if not text.startswith("pyright:"):
                continue
            for setting in (s.strip() for s in text.removeprefix("pyright:").split(",")):
                name, _, value = (part.strip() for part in setting.partition("="))
                if name in MODE_WORDS:
                    problems.append(f"line {line}: a file-level mode ({name}) isn't allowed")
                elif name not in STYLE_RULES and value != "error":
                    problems.append(f"line {line}: a file can't set {name}={value or '?'}")
    return problems


def _checked_files() -> list[Path]:
    # tests/ joins once its own suppressions follow the policy.
    files: list[Path] = []
    for entry in _config()["include"]:
        if entry == "tests":
            continue
        path = BACKEND / entry
        files.extend(sorted(path.rglob("*.py")) if path.is_dir() else [path])
    return files


class TestTypoGuard:
    def test_every_root_key_is_a_pyright_setting(self) -> None:
        unknown = [key for key in _config() if not _known(key)]
        assert unknown == [], f"pyright would skip these silently: {unknown}"

    def test_every_environment_key_is_a_pyright_setting(self) -> None:
        unknown = [key for env in _environments() for key in env if not _known(key)]
        assert unknown == [], f"pyright would skip these silently: {unknown}"

    def test_the_guard_can_tell(self) -> None:
        assert _known("reportArgumentType")
        assert not _known("reportArgumentTpye")

    def test_the_tests_environment_resolves_and_checks_imports(self) -> None:
        # executionEnvironments ignores typeCheckingMode, so without these a
        # broken import in tests would pass silently.
        tests_env = next(env for env in _environments() if env.get("root") == "tests")
        assert tests_env.get("reportMissingImports") == "error"
        assert tests_env.get("extraPaths") == ["."]

    def test_nothing_is_excluded_with_an_ignore_list(self) -> None:
        assert "ignore" not in _config()


class TestPolicyGuard:
    def test_the_checked_tree_follows_the_policy(self) -> None:
        files = _checked_files()
        assert any(f.parts[-2:] == ("app", "main.py") for f in files)
        problems = [
            f"{f.relative_to(BACKEND)} {p}"
            for f in files
            for p in comment_problems(f.read_text(encoding="utf-8"))
        ]
        assert problems == []

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("# pyright: reportArgumentType=false\nx = 1\n", "can't set reportArgumentType=false"),
            ("# pyright: basic\nx = 1\n", "mode (basic)"),
            ("# pyright: strict\nx = 1\n", "mode (strict)"),
            ("x = 1  # pyright: ignore\n", "needs a [rule]"),
            ("x = 1  #pyright:ignore[reportArgumentType]\n", "needs a `# reason`"),
            ("x = 1  # pyright: ignore[reportArgumentType]\n", "needs a `# reason`"),
            ("x = 1  # pyright: ignore[reportUnusedParameter]  # why\n", "isn't a pyright rule"),
            ("x = 1\ny = 2\n# pyright: reportArgumentType=false\n", "line 3: a file can't set"),
            ("x = 1  # type: ignore\n", "inert"),
            ("x = 1  # type: ignore[arg-type]\n", "inert"),
            ("x = 1  # noqa: F401  # type: ignore[attr-defined]\n", "inert"),
            ("# pyright: reportUnnecessaryTypeIgnoreComment=false\n", "can't set"),
            ("# pyright: reportPrivateUsage=false, reportReturnType=false\n", "reportReturnType"),
        ],
    )
    def test_a_violation_is_named(self, source: str, expected: str) -> None:
        problems = comment_problems(source)
        assert any(expected in p for p in problems), problems

    @pytest.mark.parametrize(
        "source",
        [
            "x = 1  # pyright: ignore[reportArgumentType]  # lenient vocab reads the stored str\n",
            "import a  # noqa: F401  # pyright: ignore[reportMissingImports, reportUnusedImport]  # optional\n",
            "# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false\n",
            "# pyright: reportArgumentType=error\n",
            'TEXT = "# pyright: ignore and # type: ignore"\n',
            '"""A docstring that says # pyright: basic."""\n',
        ],
    )
    def test_what_the_policy_allows_passes(self, source: str) -> None:
        assert comment_problems(source) == []
