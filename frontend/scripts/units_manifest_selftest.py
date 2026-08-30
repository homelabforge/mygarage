#!/usr/bin/env python3
"""Mutation-test the unit-audit manifest checker against what it claims to cover.

★ WHY THIS FILE EXISTS. `units.manifest.json` is an artifact that asserts
something about every module in a stated universe, and this workstream's
standing rule is that any artifact asserting completeness must ITSELF be
mutation-tested against what it claims. A manifest whose checker cannot fail is
a name list wearing a guarantee's name, and this phase has now shipped that
exact shape once at each of four different levels.

★ THE DIRECTIONS, and each was added because the previous set was not enough.

  1. a module enters the universe and is not dispositioned;
  2. a row is removed while its file stays;
  3. a module dispositioned `no unit behaviour` is EDITED. R9 came out of a
     review that killed the name-parity design: drop `` `${draft.liters} L` ``
     into such a file and the name set does not change, so nothing fires. The
     digest closes it, and R9 asks for the proof to be specific, "SPECIFICALLY
     on the digest mismatch, not incidentally";
  4. a CONCLUSION gets cheaper while the file stays the same. Directions 1 to 3
     all pin content. A later review downgraded every row and deleted every
     finding, touched no source file, and the gate exited 0 while printing the
     permitted sentence.

★ ASSERTIONS ARE ON RULE IDS, NOT TAGS, and that is this file's third revision.
Asserting the exit code cannot tell "something was wrong" from "the digest
caught it". Asserting the TAG fixed that one level up and left a level below it:
a review deleted each rule one at a time and found THREE that survived, every
one masked by a SIBLING RULE EMITTING THE SAME TAG. Delete the disposition-rank
half of `weakened` and the finding-dropped half still says `weakened`; delete
"a `no unit behaviour` row may not carry a finding" and "a finding must name an
owner" still says `schema`.

That shape had already been found once here, for M-O, and fixed as an INSTANCE.
This is the class fix, and it has two halves:

  * every failure carries a stable rule id and every probe below asserts the
    exact RULE set;
  * `RULE_MUTATIONS` deletes each rule in turn and names the probes it must
    flip, so a rule whose removal changes nothing fails this harness instead of
    passing it.

★ AND THE CHECKER IS MUTATED, not only the tree and the manifest. A
tree-and-manifest mutation proves the CURRENT checker fires; it says nothing
about WHICH rule fired.

★ NO SHARED LOCK, DELIBERATELY. `units_gate_corpus.py` and
`units_gate_selftest.py` share a fixture path under `scripts/` and take an
O_EXCL lock against each other, because a concurrent run could otherwise report
a result reflecting a file it did not write. This file needs no lock: its whole
universe is a throwaway tree in a tempdir, addressed through the checker's
`--root` and `--manifest` flags. The only thing it writes under `scripts/` is a
`.mutant.generated.` checker copy, which nothing else touches and `eslint`
ignores. Keep it that way.

Usage::

    python3 frontend/scripts/units_manifest_selftest.py

Exit code: 1 if any probe or mutation does not behave exactly as it says.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

FRONTEND = Path(__file__).resolve().parents[1]
CHECKER = "scripts/validate-units-manifest.ts"
CHECKER_SRC = FRONTEND / CHECKER
# `.mutant.generated.` is the infix eslint.config.js ignores, so even a copy
# leaked by a killed run is inert rather than a lint failure.
CHECKER_MUTANT = FRONTEND / "scripts/units-manifest.mutant.generated.ts"

# re.M is load bearing: without it `^` anchors to the start of the whole
# capture and every failure line reads as no failure at all, which made the
# first run of this file report "rules=[]" for nine checks that had in fact
# fired. A parser that cannot see the gate firing is this phase's signature
# defect one more level up.
FAILURE_LINE = re.compile(r"^\s+\[([\w.-]+)\]\s+(\S+)", re.M)

# Everything after this line is the advice paragraph, not findings. It explains
# each rule in the SAME `  [rule]  text` shape, so a whole-output scan reports
# every rule on every run and no assertion here could ever fail.
LEGEND_SENTINEL = "The manifest is a REVIEWED SNAPSHOT"

SCHEMA_VERSION = 2


# ---------------------------------------------------------------------------
# the fixture
# ---------------------------------------------------------------------------
def build_tree(root: Path) -> None:
    """A miniature frontend: an entry document, three modules, the public tree."""
    (root / "src").mkdir(parents=True)
    (root / "public" / "locales" / "xx").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>t</title>\n")
    (root / "public" / "offline.html").write_text("<p>offline</p>\n")
    # ★ A binary asset, on purpose. The universe rule has no extension filter,
    # and this is what stops a future "just skip images" from putting a
    # judgement back in the middle of the universe.
    (root / "public" / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "src" / "main.tsx").write_text(
        "import './alpha'\nimport './beta'\nimport './delta'\n"
    )
    (root / "src" / "alpha.ts").write_text("export const A = 1\n")
    (root / "src" / "beta.ts").write_text("export const B = 2\n")
    # The baselined module. `units.baseline.json` records the same work from a
    # different program, which is what makes an erased finding detectable even
    # when no drift comparison is available at all.
    (root / "src" / "delta.ts").write_text("export const D = 4\n")
    # Named by the audited row below. Not imported from main.tsx, so it is not
    # in the universe and needs no row of its own.
    (root / "src" / "__tests__").mkdir()
    (root / "src" / "__tests__" / "alpha.test.ts").write_text("export const T = 1\n")
    (root / "public" / "sw.js").write_text(
        "self.addEventListener('install', () => {})\n"
    )
    (root / "public" / "locales" / "xx" / "common.json").write_text('{"a": "b"}\n')
    (root / "scripts").mkdir()
    (root / "scripts" / "units.baseline.json").write_text(
        json.dumps(
            [
                {
                    "file": "src/delta.ts",
                    "kind": "compare",
                    "text": "x === 'imperial'",
                    "count": 2,
                }
            ],
            indent=1,
        )
        + "\n"
    )


def seed(root: Path, manifest: Path) -> None:
    """Seed the fixture manifest and give every row a disposition AND a reason.

    ★ EVERY ROW CARRIES A `reason`, and that is the point rather than realism.
    The round-trip probe below exists because `--update` silently dropped all 50
    `owners` arrays when that field was added to the row schema and not to the
    checker's own `seed()`. It catches the NEXT field somebody forgets, but only
    for fields the fixture uses, and no fixture row had a `reason`. All 387 rows
    of the real manifest do, and `reason` is the per-row audit trail: losing it
    through the documented remedy for a [digest] failure would strip 381 rows of
    why anybody concluded anything. That is the `owners` defect one field over,
    inside the probe written to prevent it.

    Rows are rebuilt in the checker's own emission order (path, disposition,
    digest, reason, tests, findings, owners) rather than mutated in place. A
    dict that appends `reason` after `owners` round-trips to different BYTES for
    a reason that has nothing to do with a dropped field, and the probe compares
    bytes.
    """
    subprocess.run(
        ["bun", "run", CHECKER, "--update", "--root", str(root), "--manifest", str(manifest)],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
        check=True,
    )
    doc = json.loads(manifest.read_text())
    rebuilt: list[dict] = []
    for row in doc["rows"]:
        out: dict = {"path": row["path"], "disposition": "", "digest": row["digest"]}
        if row["path"] == "src/delta.ts":
            out["disposition"] = "audited"
            out["reason"] = "the module units.baseline.json also records work for"
            out["findings"] = ["compare x2 (units gate baseline)"]
            out["owners"] = ["task 6"]
        elif row["path"] == "src/alpha.ts":
            # One audited row carrying every kind of evidence, and TWO findings
            # so a probe can drop one and leave the row valid. Isolating a rule
            # matters more than realism here: a probe that trips two rules at
            # once cannot tell which of them a mutation killed.
            out["disposition"] = "audited"
            out["reason"] = "one audited row carrying every kind of evidence"
            out["tests"] = ["__tests__/alpha.test.ts"]
            out["findings"] = ["a recorded finding", "a second recorded finding"]
            out["owners"] = ["task 6"]
        else:
            out["disposition"] = "no unit behaviour"
            out["reason"] = "nothing here converts a quantity"
        rebuilt.append(out)
    doc["rows"] = rebuilt
    manifest.write_text(json.dumps(doc, indent=1) + "\n")


def write_manifest(manifest: Path, rows: list[dict]) -> None:
    manifest.write_text(
        json.dumps({"schemaVersion": SCHEMA_VERSION, "rows": rows}, indent=1) + "\n"
    )


def rows_of(text: str) -> list[dict]:
    return json.loads(text)["rows"]


def digest_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(
    root: Path,
    manifest: Path,
    checker: str = CHECKER,
    against: Path | None = None,
) -> tuple[int, set[str], list[tuple[str, str]], str]:
    """Run the checker and return (rc, rule set, (rule, path) pairs, output).

    With no `against`, the checker falls back to `--against-ref HEAD`, finds no
    git repository under a tempdir, and says so. That is what every probe which
    is not about drift wants; the git default is exercised for real further
    down, against a throwaway repository of this file's own making.
    """
    argv = ["bun", "run", checker, "--root", str(root), "--manifest", str(manifest)]
    argv += ["--baseline", str(root / "scripts" / "units.baseline.json")]
    if against is not None:
        argv += ["--against-file", str(against)]
    p = subprocess.run(argv, cwd=FRONTEND, capture_output=True, text=True)
    out = p.stdout + p.stderr
    pairs = [
        (m.group(1), m.group(2))
        for m in FAILURE_LINE.finditer(out.split(LEGEND_SENTINEL)[0])
    ]
    return p.returncode, {r for r, _ in pairs}, pairs, out


# ---------------------------------------------------------------------------
# probes: one manifest (and sometimes tree) state, one expected rule set
# ---------------------------------------------------------------------------
@dataclass
class Probe:
    """One state of the fixture, and exactly which rules it must trip."""

    label: str
    #: rewrite the pristine rows in place
    rows: Callable[[list[dict], Path], list[dict]]
    #: rule ids, exactly. Not tags: three rules once survived deletion by
    #: hiding behind a sibling that emitted the same tag.
    expect: set[str] = field(default_factory=set)
    #: compare against the pristine manifest, i.e. exercise the drift rules
    against: bool = False
    #: change the tree, and put it back
    setup: Callable[[Path], None] | None = None
    teardown: Callable[[Path], None] | None = None
    why: str = ""


def _find(rows: list[dict], path: str) -> dict:
    return next(r for r in rows if r["path"] == path)


def _drop(rows: list[dict], path: str) -> list[dict]:
    return [r for r in rows if r["path"] != path]


def _add_gamma(root: Path) -> None:
    (root / "src" / "gamma.ts").write_text("export const G = 3\n")
    (root / "src" / "main.tsx").write_text(
        "import './alpha'\nimport './beta'\nimport './delta'\nimport './gamma'\n"
    )


def _remove_gamma(root: Path) -> None:
    (root / "src" / "gamma.ts").unlink()
    (root / "src" / "main.tsx").write_text(
        "import './alpha'\nimport './beta'\nimport './delta'\n"
    )


def _edit_beta(root: Path) -> None:
    (root / "src" / "beta.ts").write_text(
        "export const B = 2\nexport const label = `${B} L`\n"
    )


def _restore_beta(root: Path) -> None:
    (root / "src" / "beta.ts").write_text("export const B = 2\n")


def _repair_alpha(root: Path) -> None:
    (root / "src" / "alpha.ts").write_text(
        "export const A = 1\nexport const repaired = true\n"
    )


def _restore_alpha(root: Path) -> None:
    (root / "src" / "alpha.ts").write_text("export const A = 1\n")


def _rename_alpha(root: Path) -> None:
    (root / "src" / "alpha.ts").rename(root / "src" / "epsilon.ts")
    (root / "src" / "main.tsx").write_text(
        "import './epsilon'\nimport './beta'\nimport './delta'\n"
    )


def _unrename_alpha(root: Path) -> None:
    (root / "src" / "epsilon.ts").rename(root / "src" / "alpha.ts")
    (root / "src" / "main.tsx").write_text(
        "import './alpha'\nimport './beta'\nimport './delta'\n"
    )


def _launder(rows: list[dict], root: Path) -> list[dict]:
    """The rename that used to launder a finding: same bytes, a clean new row."""
    alpha = _find(rows, "src/alpha.ts")
    out = _drop(rows, "src/alpha.ts")
    for r in out:
        if r["path"] == "src/main.tsx":
            r["digest"] = digest_of(root / "src" / "main.tsx")
    out.append(
        {
            "path": "src/epsilon.ts",
            "disposition": "no unit behaviour",
            "digest": alpha["digest"],
            "reason": "nothing to see here",
        }
    )
    return sorted(out, key=lambda r: r["path"])


def _erase_with_repair(rows: list[dict], root: Path) -> list[dict]:
    alpha = _find(rows, "src/alpha.ts")
    alpha["findings"] = []
    alpha.pop("owners", None)
    alpha["digest"] = digest_of(root / "src" / "alpha.ts")
    return rows


PROBES: list[Probe] = [
    Probe("pristine", lambda rows, root: rows, set(), why="the control"),
    # ---- the three R9 directions ----------------------------------------
    Probe(
        "D1-new-module",
        lambda rows, root: rows,
        {"unlisted", "digest"},
        setup=_add_gamma,
        teardown=_remove_gamma,
        why="a module entered the universe. The digest on main.tsx is the "
        "mechanism working, not noise: the file that gained an import changed.",
    ),
    Probe(
        "D2-row-removed",
        lambda rows, root: _drop(rows, "src/beta.ts"),
        {"unlisted"},
        why="a row left the manifest while its file stayed",
    ),
    Probe(
        "D3-module-edited",
        lambda rows, root: rows,
        {"digest"},
        setup=_edit_beta,
        teardown=_restore_beta,
        why="★ R9's own direction: a `no unit behaviour` module gains unit "
        "behaviour. The NAME set does not change, so only the digest can see it, "
        "and this must fail on the digest rule ALONE.",
    ),
    # ---- the fourth direction -------------------------------------------
    Probe(
        "D4-disposition-downgraded",
        lambda rows, root: [
            {**r, "disposition": "unverifiable", "reason": "a stated reason"}
            if r["path"] == "src/alpha.ts"
            else r
            for r in rows
        ],
        {"weakened.rank"},
        against=True,
        why="the conclusion got cheaper and the file did not move. Findings are "
        "kept so this trips the RANK rule alone.",
    ),
    Probe(
        "D4-finding-erased",
        lambda rows, root: [
            {**r, "findings": ["a recorded finding"]} if r["path"] == "src/alpha.ts" else r
            for r in rows
        ],
        {"weakened.finding"},
        against=True,
        why="one finding quietly disappears, disposition untouched",
    ),
    Probe(
        "D4-erased-WITH-a-repair",
        _erase_with_repair,
        set(),
        against=True,
        setup=_repair_alpha,
        teardown=_restore_alpha,
        why="★ the legitimate direction. The SAME erasure with the file actually "
        "repaired must stay silent, or the rule blocks the work it protects.",
    ),
    Probe(
        "D4-finding-added",
        lambda rows, root: [
            {**r, "findings": [*r["findings"], "a third"]}
            if r["path"] == "src/alpha.ts"
            else r
            for r in rows
        ],
        set(),
        against=True,
        why="strengthening is always allowed",
    ),
    Probe(
        "D4-rename-launders",
        _launder,
        {"weakened.rank", "weakened.finding"},
        against=True,
        setup=_rename_alpha,
        teardown=_unrename_alpha,
        why="★ PATH IS NOT THE IDENTITY. Move a file with its bytes untouched, "
        "give the new path a clean row, delete the old one: parity is satisfied, "
        "the digest is satisfied, and the finding is simply gone.",
    ),
    # ---- the schema rules, each isolated --------------------------------
    Probe(
        "orphan-row",
        lambda rows, root: [
            *rows,
            {"path": "src/deleted.ts", "disposition": "no unit behaviour", "digest": "0" * 64},
        ],
        {"orphan"},
        why="a row outlived its file",
    ),
    Probe(
        "duplicate-row",
        lambda rows, root: [*rows, dict(rows[0])],
        {"duplicate"},
        why="two rows for one path: one disposition hides the other",
    ),
    Probe(
        "row-without-path",
        lambda rows, root: [*_drop(rows, "src/beta.ts"), {"disposition": "no unit behaviour"}],
        {"schema.no-path", "unlisted"},
        why="a row that names no file at all",
    ),
    Probe(
        "audited-without-evidence",
        lambda rows, root: [
            {k: v for k, v in r.items() if k not in ("tests", "findings", "owners")}
            if r["path"] == "src/alpha.ts"
            else r
            for r in rows
        ],
        {"schema.evidence"},
        why="BOTH kinds of evidence have to go: dropping only `tests` leaves "
        "`findings` standing, and the first version of this probe did exactly "
        "that and reported clean.",
    ),
    Probe(
        "unverifiable-without-reason",
        lambda rows, root: [
            {"path": r["path"], "disposition": "unverifiable", "digest": r["digest"]}
            if r["path"] == "src/beta.ts"
            else r
            for r in rows
        ],
        {"schema.reason"},
        why="an unverifiable row that does not say what would settle it",
    ),
    Probe(
        "nub-with-finding",
        lambda rows, root: [
            {**r, "findings": ["renders canonical litres"], "owners": ["task 6"]}
            if r["path"] == "src/beta.ts"
            else r
            for r in rows
        ],
        {"schema.nub-finding"},
        why="a `no unit behaviour` row recording a unit finding. Owners are "
        "supplied so this trips one rule rather than two.",
    ),
    Probe(
        "test-id-names-nothing",
        lambda rows, root: [
            {**r, "tests": ["__tests__/renamed.test.ts"]} if r["path"] == "src/alpha.ts" else r
            for r in rows
        ],
        {"schema.test-missing"},
        why="★ the QUIET failure mode, and this repo learned it once already in "
        "the ESLint scope proof: a typo that un-exempts a file fails loudly, a "
        "typo that names nothing at all does not.",
    ),
    Probe(
        "owner-not-in-the-enum",
        lambda rows, root: [
            {**r, "owners": ["Task 6 (units)"]} if r["path"] == "src/alpha.ts" else r
            for r in rows
        ],
        {"schema.owner-enum"},
        why="free-text owners produced twelve spellings across 47 rows",
    ),
    Probe(
        "finding-without-an-owner",
        lambda rows, root: [
            {k: v for k, v in r.items() if k != "owners"} if r["path"] == "src/alpha.ts" else r
            for r in rows
        ],
        {"schema.finding-unowned"},
        why="a work item nobody holds",
    ),
    Probe(
        "owner-without-a-finding",
        lambda rows, root: [
            {**r, "owners": ["task 6"]} if r["path"] == "src/beta.ts" else r for r in rows
        ],
        {"schema.owner-idle"},
        why="a name attached to no work",
    ),
    Probe(
        "invented-disposition",
        lambda rows, root: [
            {**r, "disposition": "probably fine"} if r["path"] == "src/beta.ts" else r
            for r in rows
        ],
        {"schema.disposition"},
        why="a disposition nobody defined",
    ),
    # ---- the second, independent record ---------------------------------
    Probe(
        "baseline-count-misreported",
        lambda rows, root: [
            {**r, "findings": ["compare x1 (units gate baseline)"]}
            if r["path"] == "src/delta.ts"
            else r
            for r in rows
        ],
        {"baseline.counts"},
        why="the row and units.baseline.json disagree about the same work",
    ),
    Probe(
        "baselined-row-downgraded",
        lambda rows, root: [
            {"path": r["path"], "disposition": "no unit behaviour", "digest": r["digest"]}
            if r["path"] == "src/delta.ts"
            else r
            for r in rows
        ],
        {"baseline.not-audited"},
        why="★ the erasure the cross-check exists for, with NO drift comparison "
        "available at all. It still fails.",
    ),
    Probe(
        "baseline-work-invented",
        lambda rows, root: [
            {**r, "findings": ["token-branch x9 (units gate baseline)"]}
            if r["path"] == "src/alpha.ts"
            else r
            for r in rows
        ],
        {"baseline.invented"},
        why="a finding claiming baseline work the baseline does not have",
    ),
]


# ---------------------------------------------------------------------------
# rule mutations: delete one rule, name the probes it must flip
# ---------------------------------------------------------------------------
@dataclass
class RuleMutation:
    """One rule removed from a COPY of the checker, and what must go quiet."""

    mid: str
    old: str
    new: str
    flips: list[str]
    why: str = ""
    also: list[tuple[str, str]] = field(default_factory=list)


# ★ Every rule is deleted by disabling ITS OWN `failures.push(...)`, found by the
# rule id it carries. The table is BUILT from a list of (rule, probes, why)
# rather than written out eighteen times: near-identical hand-written blocks are
# one typo away from a mutation that matches nothing, and while the PATTERN
# guard would report that, nobody would notice a rule missing from the table
# altogether.
def _disable(rule: str, indent: int) -> tuple[str, str]:
    """Disable one `failures.push` by its rule id.

    The indent varies: two of the eighteen sit inside a nested loop, so a
    fixed-indent anchor matched nothing for them and the PATTERN guard reported
    it as "occurs 0 times". That guard doing its job on my own table is the
    reason it exists.
    """
    pad = " " * indent
    body = f"{pad}failures.push({{\n{pad}  rule: '{rule}',"
    return body, f"{pad}if (false) failures.push({{\n{pad}  rule: '{rule}',"


# The table itself, named so `declared_rules()` can check it covers every rule
# the checker declares. It was a bare comprehension and it covered 17 of 18:
# `schema.no-path` was emitted in a ONE-LINE `failures.push({...})` that
# `_disable`'s multi-line anchor could never match, so it was simply absent
# rather than reported as unmatched, while this file's closing sentence said
# "each rule in turn". `_disable`'s own docstring names that hazard for
# indentation; this is the same hazard one level up, where the PATTERN guard
# cannot reach because there is no pattern to guard.
_RULE_TABLE: list[tuple[str, int, list[str], str]] = [
        ("unlisted", 6, ["D1-new-module", "D2-row-removed", "row-without-path"], "parity, the file side"),
        ("orphan", 6, ["orphan-row"], "parity, the row side"),
        ("duplicate", 6, ["duplicate-row"], "one disposition hiding another"),
        ("schema.disposition", 6, ["invented-disposition"], "the closed set of dispositions"),
        ("schema.reason", 6, ["unverifiable-without-reason"], "an exemption must state its reason"),
        ("schema.evidence", 6, ["audited-without-evidence"], "audited must rest on something"),
        ("schema.nub-finding", 6, ["nub-with-finding"], "★ one of the three that survived a tag-level assertion"),
        ("schema.test-missing", 8, ["test-id-names-nothing"], "a test id that names nothing"),
        ("schema.finding-unowned", 6, ["finding-without-an-owner"], "work nobody holds"),
        ("schema.owner-idle", 6, ["owner-without-a-finding"], "a name attached to no work"),
        ("schema.owner-enum", 8, ["owner-not-in-the-enum"], "the closed set of owners"),
        ("digest", 6, ["D1-new-module", "D3-module-edited"], "R9's own direction"),
        ("baseline.not-audited", 6, ["baselined-row-downgraded"], "★ the second of the three survivors"),
        ("baseline.counts", 6, ["baseline-count-misreported"], "the two records must agree"),
        ("baseline.invented", 6, ["baseline-work-invented"], "and agree in both directions"),
        ("weakened.rank", 6, ["D4-disposition-downgraded", "D4-rename-launders"], "★ the third survivor"),
        ("weakened.finding", 8, ["D4-finding-erased", "D4-rename-launders"], "an erased finding"),
        ("schema.no-path", 6, ["row-without-path"], "a row that names no file at all"),
]

RULE_MUTATIONS = [
    RuleMutation(f"drop-{rule}", *_disable(rule, indent), flips, why)
    for rule, indent, flips, why in _RULE_TABLE
]

#: Which rule ids the sweep above actually deletes. Compared against the
#: checker's own `type Rule` union, so a rule added there without a mutation
#: here fails this harness instead of quietly shrinking its coverage.
RULE_COVERAGE = {rule for rule, _indent, _flips, _why in _RULE_TABLE}

# Mechanisms rather than rules: deleting one silences several rules at once.
RULE_MUTATIONS += [
    RuleMutation(
        "drop-the-drift-rule",
        "  const old = new Map(before.map((r) => [r.path, r]))",
        "  if (before) return failures\n  const old = new Map(before.map((r) => [r.path, r]))",
        ["D4-disposition-downgraded", "D4-finding-erased", "D4-rename-launders"],
        "the whole fourth direction",
    ),
    RuleMutation(
        "drop-the-rename-pairing",
        "    if (was === undefined && uniqueAfter.get(row.digest)?.path === row.path) {\n      was = uniqueBefore.get(row.digest)\n    }",
        "",
        ["D4-rename-launders"],
        "★ keying drift on PATH alone, which is how a rename laundered a finding",
    ),
    RuleMutation(
        "drop-the-baseline-cross-check",
        "  const work = baselineWork(baselinePath)",
        "  if (baselinePath) return failures\n  const work = baselineWork(baselinePath)",
        ["baseline-count-misreported", "baselined-row-downgraded", "baseline-work-invented"],
        "★ BOTH directions at once. Emptying `work` alone silences the forward "
        "check and leaves the reverse one firing, which is the rule being "
        "defended twice: a mutation that removes one defence flips nothing and "
        "reads as a survivor.",
    ),
]


def declared_rules() -> list[str]:
    """The rule ids the checker DECLARES, read from its `type Rule` union.

    Derived rather than transcribed, for the same reason the checker derives the
    manifest universe rather than keeping a list: a list I maintain is a floor.
    A rule added to the union with no entry in `_RULE_TABLE` is a rule this
    harness silently stops covering while still printing "each rule in turn".
    """
    text = CHECKER_SRC.read_text()
    match = re.search(r"^type Rule =\n((?:\s*\|\s*'[\w.-]+'\n)+)", text, re.M)
    if match is None:
        raise SystemExit(
            "could not read `type Rule` from the checker. The sweep's coverage claim "
            "rests on this parse, so a silent zero here would be worse than a crash."
        )
    return re.findall(r"'([\w.-]+)'", match.group(1))


def write_checker_mutant(old: str, new: str, also: list[tuple[str, str]] | None = None) -> tuple[str, int]:
    """Write a mutated COPY of the checker. Never the original."""
    text = CHECKER_SRC.read_text()
    worst = 1
    for a, b in [(old, new), *(also or [])]:
        n = text.count(a)
        if n != 1:
            worst = n
            break
        text = text.replace(a, b)
    if worst == 1:
        CHECKER_MUTANT.write_text(text)
    return str(CHECKER_MUTANT.relative_to(FRONTEND)), worst


# ---------------------------------------------------------------------------
# runners
# ---------------------------------------------------------------------------
def run_probes(
    root: Path, manifest: Path, pristine: str, prev: Path, checker: str = CHECKER
) -> dict[str, set[str]]:
    """Every probe under one checker, returning {label: rule set}."""
    out: dict[str, set[str]] = {}
    for probe in PROBES:
        if probe.setup is not None:
            probe.setup(root)
        try:
            write_manifest(manifest, probe.rows(rows_of(pristine), root))
            _rc, rules, _pairs, _text = run(
                root, manifest, checker, prev if probe.against else None
            )
            out[probe.label] = rules
        finally:
            if probe.teardown is not None:
                probe.teardown(root)
            manifest.write_text(pristine)
    return out


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=selftest@example.invalid", "-c", "user.name=selftest", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def git_probe(tmp: Path) -> list[str]:
    """The production path: previous manifest read from a git ref."""
    failures: list[str] = []
    repo = tmp / "gitrepo"
    build_tree(repo)
    manifest = repo / "scripts" / "units.manifest.json"
    seed(repo, manifest)
    pristine = manifest.read_text()
    try:
        git(repo, "init", "-q")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "seed")
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        failures.append(f"git probe: could not build a repository: {exc}")
        print("  git repository                         *** COULD NOT BUILD ***")
        return failures

    rc, rules, _pairs, out = run(repo, manifest)
    # The success line must NAME the ref, or the reader returned null and every
    # drift probe above proved nothing about production.
    compared = "no conclusion weakened against HEAD:" in out
    ok = rc == 0 and not rules and compared
    print(
        f"  {'git HEAD baseline':<38} "
        + ("clean, and it says what it compared" if ok else "*** " + out.strip()[:90] + " ***")
    )
    if not ok:
        failures.append(f"git probe baseline: rc={rc} rules={sorted(rules)} compared={compared}")

    weakened = rows_of(pristine)
    for r in weakened:
        if r["path"] == "src/alpha.ts":
            r["disposition"] = "no unit behaviour"
            for key in ("tests", "findings", "owners"):
                r.pop(key, None)
    write_manifest(manifest, weakened)
    rc, rules, pairs, out = run(repo, manifest)
    ok = rc == 1 and rules == {"weakened.rank", "weakened.finding"} and "src/alpha.ts" in [
        p for _, p in pairs
    ]
    print(
        f"  {'git HEAD weakening':<38} "
        + ("fails on rank and finding" if ok else "*** rc=" + str(rc) + " " + str(sorted(rules)) + " ***")
    )
    if not ok:
        failures.append(f"git probe weakening: rc={rc} rules={sorted(rules)}")
    manifest.write_text(pristine)
    return failures


def degradation_probe(root: Path, manifest: Path, tmp: Path) -> list[str]:
    """Every degraded path must warn AND drop the affirmative clause.

    ★ `--against-file` at a file holding `[]` used to print the affirmative
    "no conclusion weakened against ..." while comparing against nothing.
    Nothing can weaken against nothing, so the sentence is vacuously true and
    reads as evidence, which is the one thing a degraded path must never do.
    """
    failures: list[str] = []
    cases = {
        "empty array": "[]\n",
        "empty rows": '{"schemaVersion": 2, "rows": []}\n',
        "not a manifest": '{"nope": true}\n',
        "unparseable": "{oh no\n",
    }
    probe = tmp / "degraded.json"
    for label, body in cases.items():
        probe.write_text(body)
        rc, rules, _pairs, out = run(root, manifest, against=probe)
        warned = "conclusion drift NOT checked" in out
        affirmed = "no conclusion weakened against" in out
        ok = rc == 0 and not rules and warned and not affirmed
        print(
            f"  previous is {label:<26}"
            + ("warns, and claims nothing" if ok else f"*** warned={warned} affirmed={affirmed} ***")
        )
        if not ok:
            failures.append(f"degradation {label}: warned={warned} affirmed={affirmed} rc={rc}")
    missing = tmp / "does-not-exist.json"
    rc, _rules, _pairs, out = run(root, manifest, against=missing)
    ok = rc == 0 and "conclusion drift NOT checked" in out and "no conclusion weakened against" not in out
    print(f"  previous is {'missing entirely':<26}" + ("warns, and claims nothing" if ok else "*** wrong ***"))
    if not ok:
        failures.append("degradation missing file")
    return failures


def version_probe(root: Path, manifest: Path, tmp: Path) -> list[str]:
    """A format migration stands down the FINDING half, and only that half.

    ★ [weakened] forbids findings from shrinking while a digest holds still,
    which is right for an erasure and WRONG for a format migration: moving 47
    rows' owner text into an `owners` array shrank findings on 47 unchanged
    files. That was handled by ordering the commits, which worked locally and
    left an undocumented dependency on push granularity.

    ★ BUT STANDING DOWN THE WHOLE DIRECTION MADE A VERSION BUMP AN AMNESTY.
    Bump the version in the same commit that downgrades every row and the gate
    printed a reassuring sentence. A migration moves fields between columns; it
    never LOWERS a disposition, and forcing the real owner migration through the
    rank half produced 49 `weakened.finding` and 0 `weakened.rank`. So rank
    stays live across the bump, and the two probes below are the pair: the
    erasure a migration legitimately causes is forgiven, the downgrade it never
    causes is not.
    """
    failures: list[str] = []
    pristine = manifest.read_text()
    old_format = tmp / "previous.v1.json"
    # The pre-version shape: a bare array. Same rows, one field short.
    old_format.write_text(json.dumps(rows_of(pristine), indent=1) + "\n")
    erased = rows_of(pristine)
    for r in erased:
        if r["path"] == "src/alpha.ts":
            r["findings"] = []
            r.pop("owners", None)
    try:
        write_manifest(manifest, erased)
        rc, rules, _pairs, out = run(root, manifest, against=old_format)
        skipped = "erased-finding drift NOT checked" in out
        ok = rc == 0 and not rules and skipped and "no conclusion weakened against" not in out
        print(
            f"  {'findings erased across a version':<38} "
            + ("forgiven, and says why" if ok else f"*** rc={rc} {sorted(rules)} skipped={skipped} ***")
        )
        if not ok:
            failures.append(f"version probe: rc={rc} rules={sorted(rules)} skipped={skipped}")

        # ...and the half a migration can never justify is STILL LIVE across the
        # same bump. Findings and owners go with the downgrade so this trips the
        # rank rule alone rather than the schema rules a bare downgrade would.
        downgraded = rows_of(pristine)
        for r in downgraded:
            if r["path"] == "src/alpha.ts":
                r["disposition"] = "no unit behaviour"
                for key in ("tests", "findings", "owners"):
                    r.pop(key, None)
        write_manifest(manifest, downgraded)
        rc, rules, pairs, out = run(root, manifest, against=old_format)
        ok = (
            rc == 1
            and rules == {"weakened.rank"}
            and "src/alpha.ts" in [path for _rule, path in pairs]
        )
        print(
            f"  {'disposition lowered across a version':<38} "
            + ("still caught" if ok else f"*** rc={rc} {sorted(rules)} ***")
        )
        if not ok:
            failures.append(
                f"version probe, rank across a bump: rc={rc} rules={sorted(rules)}"
            )

        # ...and the same erasure WITHIN one version is still caught, or the
        # version field is just a bypass with a nicer name. The manifest is put
        # back to the ERASURE first: the downgrade probe above left the
        # disposition lowered too, and this check asserts the exact rule set, so
        # it would otherwise see the rank rule fire for the previous probe's
        # mutation rather than its own.
        write_manifest(manifest, erased)
        same_format = tmp / "previous.v2.json"
        same_format.write_text(pristine)
        rc, rules, _pairs, _out = run(root, manifest, against=same_format)
        ok = rc == 1 and rules == {"weakened.finding"}
        print(
            f"  {'within one schema version':<38} "
            + ("still caught" if ok else f"*** rc={rc} {sorted(rules)} ***")
        )
        if not ok:
            failures.append(f"version probe, same version: rc={rc} rules={sorted(rules)}")
    finally:
        manifest.write_text(pristine)
    return failures


def preserved_fields() -> list[str]:
    """The optional row fields the checker's `seed()` carries across `--update`.

    Read from the checker rather than listed, because the whole point of the
    round-trip probe is to catch a field somebody forgot, and a hand-written
    list here would be one more place to forget it.
    """
    text = CHECKER_SRC.read_text()
    body = re.search(
        r"^function seed\(root: string, rows: ManifestRow\[\]\): ManifestRow\[\] \{(.*?)^\}",
        text,
        re.S | re.M,
    )
    if body is None:
        raise SystemExit("could not read the checker's seed() to derive its preserved fields")
    return sorted(set(re.findall(r"if \(existing\?\.(\w+)", body.group(1))))


def round_trip_probe(root: Path, manifest: Path) -> list[str]:
    """`--update` must be a FIXED POINT on a fully dispositioned manifest.

    ★ `seed()` was not updated when `owners` landed, so `--update` silently
    dropped all 50 owner arrays and the next run reported 50 schema failures.
    That is nastier than its size: `--update` is the documented remedy for a
    [digest] failure, and the natural way to clear the schema errors it causes
    is to delete the findings, which [weakened] then holds shut. The remedy led
    into a trap the guard kept closed.

    ★ AND IT CATCHES THE NEXT FIELD ONLY IF THE FIXTURE CARRIES IT. The byte
    comparison cannot distinguish "reason survived" from "no row had a reason",
    so for one revision this probe reported success for a field it never
    exercised while the harness's closing sentence claimed the coverage. The
    kept-field check below closes that: the preserved set is derived from the
    checker's own `seed()`, and a field the fixture does not carry fails here
    instead of passing quietly.
    """
    failures: list[str] = []
    before = manifest.read_text()

    # ★ WHICH FIELDS THIS ACTUALLY EXERCISED, said out loud. The byte comparison
    # below is silent about coverage: it passes identically whether the fixture
    # carries `reason` or has never heard of it, so at exit 0 you cannot tell a
    # probe that covered every field from one that covered three of four. That
    # is the t=0 problem inside a probe, and it is exactly how `reason` sat
    # uncovered behind a sentence claiming the opposite. A field the checker
    # preserves and the fixture omits is now a FAILURE, not a silence.
    preserved = preserved_fields()
    carried = {key for row in rows_of(before) for key in row}
    uncovered = [field for field in preserved if field not in carried]
    print(
        f"  {'the fixture carries every kept field':<38} "
        + (
            f"{len(preserved)} of {len(preserved)}: {', '.join(preserved)}"
            if not uncovered
            else f"*** uncovered: {uncovered} ***"
        )
    )
    if uncovered:
        failures.append(
            f"round trip: the checker preserves {preserved} but the fixture carries "
            f"none of {uncovered}, so this probe cannot see them dropped"
        )

    subprocess.run(
        ["bun", "run", CHECKER, "--update", "--root", str(root), "--manifest", str(manifest)],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
        check=True,
    )
    after = manifest.read_text()
    ok = before == after
    print(
        f"  {'--update on a dispositioned manifest':<38} "
        + ("byte-identical" if ok else "*** REWROTE THE FILE ***")
    )
    if not ok:
        lost = {
            k
            for b, a in zip(rows_of(before), rows_of(after))
            for k in b
            if k not in a
        }
        failures.append(f"round trip: --update dropped field(s) {sorted(lost)}")
        manifest.write_text(before)
    return failures


def main() -> int:
    failures: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="units-manifest-selftest-"))
    root = tmp / "tree"
    manifest = tmp / "units.manifest.json"
    prev = tmp / "previous.manifest.json"
    try:
        build_tree(root)
        seed(root, manifest)
        pristine = manifest.read_text()
        prev.write_text(pristine)

        print("probes: each state trips exactly the RULES it names")
        print("-" * 78)
        reference = run_probes(root, manifest, pristine, prev)
        for probe in PROBES:
            got = reference[probe.label]
            ok = got == probe.expect
            mark = (
                "clean"
                if ok and not probe.expect
                else (f"trips {','.join(sorted(got))}" if ok else f"*** {sorted(got)} ***")
            )
            print(f"  {probe.label:<38} {mark}")
            if not ok:
                failures.append(
                    f"{probe.label}: expected {sorted(probe.expect)}, got {sorted(got)}"
                )
        if failures:
            print("\nthe probes are not green, so no mutation result would mean anything:")
            for f in failures:
                print("  " + f)
            return 1

        print("\nrule deletions: each must silence exactly the probes that name it")
        print("-" * 78)
        declared = declared_rules()
        uncovered = sorted(set(declared) - RULE_COVERAGE)
        invented = sorted(RULE_COVERAGE - set(declared))
        ok = not uncovered and not invented
        print(
            f"  {'the table covers the declared rules':<38} "
            + (
                f"{len(RULE_COVERAGE)} of {len(declared)}"
                if ok
                else f"*** uncovered={uncovered} invented={invented} ***"
            )
        )
        if not ok:
            failures.append(
                f"rule coverage: declared {len(declared)}, table covers "
                f"{len(RULE_COVERAGE)}; uncovered={uncovered} invented={invented}"
            )
        for mut in RULE_MUTATIONS:
            mutant, n = write_checker_mutant(mut.old, mut.new, mut.also)
            if n != 1:
                failures.append(f"{mut.mid}: PATTERN occurs {n} times, expected 1")
                print(f"  {mut.mid:<38} *** NOT A VALID MUTANT *** pattern occurs {n} times")
                continue
            try:
                got = run_probes(root, manifest, pristine, prev, mutant)
            finally:
                CHECKER_MUTANT.unlink(missing_ok=True)
            flipped = sorted(k for k, v in got.items() if v != reference[k])
            expected = sorted(mut.flips)
            ok = flipped == expected
            print(
                f"  {mut.mid:<38} "
                + (f"silences {len(expected)}: {','.join(expected)}" if ok else f"*** WRONG PROBES FLIPPED *** {flipped}")
            )
            if not ok:
                failures.append(f"{mut.mid}: expected to flip {expected}, flipped {flipped}")

        print("\nthe git default (--against-ref HEAD), against a real repository")
        print("-" * 78)
        failures += git_probe(tmp)

        print("\nevery degraded comparison warns and claims nothing")
        print("-" * 78)
        failures += degradation_probe(root, manifest, tmp)

        print("\na format migration is exempt by construction, and only a migration")
        print("-" * 78)
        failures += version_probe(root, manifest, tmp)

        print("\n--update is a fixed point")
        print("-" * 78)
        failures += round_trip_probe(root, manifest)

        print("\nthe named runtime roots, which the import walker cannot reach")
        print("-" * 78)
        for label, path in (
            ("entry document", root / "index.html"),
            ("service worker", root / "public" / "sw.js"),
            ("locale bundle", root / "public" / "locales" / "xx" / "common.json"),
            ("offline page", root / "public" / "offline.html"),
            ("binary asset", root / "public" / "icon.png"),
        ):
            target = str(path.relative_to(root))
            rows = rows_of(pristine)
            present = any(r["path"] == target for r in rows)
            write_manifest(manifest, [r for r in rows if r["path"] != target])
            rc, rules, pairs, _out = run(root, manifest)
            ok = present and rc == 1 and rules == {"unlisted"} and target in [p for _, p in pairs]
            print(
                f"  {label:<38} "
                + ("in the universe and required" if ok else "*** NOT ENFORCED ***")
            )
            if not ok:
                failures.append(f"{label}: present={present} rc={rc} rules={sorted(rules)}")
            manifest.write_text(pristine)
    finally:
        CHECKER_MUTANT.unlink(missing_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print("MANIFEST SELFTEST: FAILURES")
        for f in failures:
            print("  " + f)
        return 1
    print(
        f"MANIFEST SELFTEST: {len(PROBES)} probes trip exactly the rules they name; the "
        f"table covers all {len(RULE_COVERAGE)} rule ids the checker DECLARES, derived "
        "from its own `type Rule` union rather than transcribed; and all "
        f"{len(RULE_MUTATIONS)} deletions silence exactly the probes that name them, so "
        "no rule survives removal behind a sibling emitting the same tag. All "
        "four directions fire, the digest one alone; a repair makes the same erasure "
        "legitimate; a rename cannot launder a finding; the git default was driven "
        "against a real repository and says what it compared; every degraded comparison "
        "warns and claims nothing; a format migration stands down the erased-finding "
        "half ONLY, so a disposition lowered across a version bump is still caught and "
        "so is an erasure inside one version; --update is a fixed point, over a fixture "
        "CHECKED to carry every field the checker preserves rather than assumed to; "
        "and every named runtime root is enforced, the entry document and a binary "
        "asset among them."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
