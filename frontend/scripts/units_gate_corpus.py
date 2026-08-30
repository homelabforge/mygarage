#!/usr/bin/env python3
"""Two-sided corpus for the unit gate's two legs (plan ruling R2).

A gate that never fires is worse than no gate, because it is believed:
`eslint.config.js` once carried a `no-restricted-syntax` selector demanding two
literal `$` where the AST produces one, and it silently matched nothing for
months. So neither leg of this gate ships on a single probe. Each leg gets a
POSITIVE half it must reject and a NEGATIVE half it must accept, and a case that
passes identically whether or not the rule exists is a case that pins nothing.

★ The fixtures are OWNED BY THIS FILE. Nothing here reads a production line, so
no change under `frontend/src` can quietly leave a case unexercised the way
`mutation_harness_selftest.py`'s first version did when the source line it
patched was deleted by the very task it certified. Round 2 moved the ESLint
fixture out of `src/` as well: a run that died between the write and its
`finally` used to leave a file that failed `validate-reachability.ts`, so the
gate's own tests could break the working tree.

★ EVERY case names a mutation that flips it, and round 2 added twelve cases
because a reviewer's independent matrix found eight surviving mutants that
nothing here could kill. The structural reason is worth keeping in view:
BASELINE MODE CAN ONLY KILL TIGHTENING MUTATIONS. The script leg fails when a
count RISES and never when one falls, so every loosening of the gate reads as
migration progress, and this corpus is the sole executioner for that entire
direction.

Legs, split by PROVENANCE-SENSITIVITY (ruling R3):

  ESLint  raw conversion constants. A numeric literal means the same thing
          wherever it appears, so a purely syntactic selector is sound for it.
  script  every `=== 'imperial'` / `=== 'metric'` comparison, because deciding
          whether the left-hand side is a unit system or a theme requires
          knowing what the identifier refers to, and `no-restricted-syntax`
          performs no binding analysis at all.

Usage::

    python3 frontend/scripts/units_gate_corpus.py

Exit code: 1 if any positive passes or any negative fails.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# frontend/scripts/units_gate_corpus.py -> frontend/scripts -> frontend.
FRONTEND = Path(__file__).resolve().parents[1]
GATE = "scripts/validate-units.ts"

# The ESLint leg is scoped by `files:` to migrated paths, so a corpus fixture has
# to sit at a path that scope names. `eslint.config.js` lists this one for that
# purpose; it exists only while this script runs.
#
# Under `scripts/`, not `src/`: the rule is path-scoped so the location is free,
# and `src/` is the subject of validate-reachability.ts and of validate-units.ts's
# own tree walk. A leaked fixture there fails an unrelated gate.
ESLINT_FIXTURE = FRONTEND / "scripts/__units_corpus__.tsx"

# Mutual exclusion between this script and units_gate_selftest.py.
#
# ★ Both scripts write the SAME fixture path, and until round 4 both deleted
# leftovers at start. Two runs overlapping therefore destroyed each other's
# fixture and could each report a result reflecting a file it did not write:
# a FALSE RESULT, which is this phase's signature defect rather than a mere
# inconvenience. The collision surface grew when the corpus joined
# `validate:translations`, because every local `bin/ci-check --frontend` now
# takes that path.
#
# So neither script cleans up at start any more. They refuse. The lock is taken
# with O_EXCL, so the refusal is a real interlock rather than a check with a
# race in the middle of it, and a stale lock after a kill is a loud manual
# cleanup rather than a quiet wrong answer.
LOCK = FRONTEND / "scripts/.units-gate.lock"


def acquire_lock(owner: str, artifacts: list[Path]) -> str | None:
    """Take the shared lock, or return the reason this run must not start."""
    stale = [a for a in artifacts if a.exists()]
    if stale:
        return (
            f"{owner}: refusing to start, these files already exist:\n"
            + "\n".join(f"    {a.relative_to(FRONTEND)}" for a in stale)
            + "\n  Either another unit-gate run is in progress, or one was killed"
            "\n  before its cleanup. Deleting them here could destroy a running"
            "\n  run's fixture and make BOTH results meaningless, so remove them"
            "\n  by hand once you are sure nothing else is running."
        )
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return (
            f"{owner}: refusing to start, {LOCK.relative_to(FRONTEND)} is held.\n"
            "  units_gate_corpus.py and units_gate_selftest.py share a fixture"
            "\n  path and cannot run concurrently. Wait for the other run, or"
            "\n  delete the lock if you are certain none is in progress."
        )
    os.write(fd, f"{owner} pid={os.getpid()}\n".encode())
    os.close(fd)
    return None


def release_lock() -> None:
    LOCK.unlink(missing_ok=True)


@dataclass
class Case:
    """One corpus case: a fixture body plus what the leg must say about it."""

    cid: str
    body: str
    #: findings the leg must report. 0 means the case must be ACCEPTED.
    expect: int
    #: substring that must appear in every reported finding, so a case cannot be
    #: satisfied by the wrong rule firing. Empty when `expect` is 0.
    expect_kind: str = ""
    why: str = ""
    #: mutation id in units_gate_selftest.py that flips this case. Every case
    #: names one: a case no mutation can flip is an assertion true at t=0, one
    #: level up.
    pinned_by: str = ""
    #: fixture extension. `.ts` and `.tsx` are DIFFERENT languages to the
    #: parser: `<string>raw` is a type assertion in one and a broken JSX tag in
    #: the other, which is how round 1's gate went blind to whole files.
    ext: str = ".tsx"
    #: exact normalized text the single finding must carry. Pins normalize().
    expect_text: str = ""
    tags: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# script leg: provenance-sensitive comparisons
# --------------------------------------------------------------------------
HOOK_IMPORT = "import { useUnitPreference } from '@/hooks/useUnitPreference'\n"

# A binary formatter the FIXTURE declares, so the formatter leg's three
# positives own their own vocabulary.
#
# ★ THEY USED TO NAME A LIVE PRODUCTION METHOD, and that had to end. The
# derived set is read from `src/utils/units.ts`, so each fixture spelled
# whichever binary formatter still existed: `formatDistance` until task 6
# deleted it, `formatFuelEconomy` until task 6b deleted that one,
# `formatCostPerDistance` until task 7 deleted the last two. Every rename was
# the case working rather than bending, and the third one exhausted the supply:
# `UnitFormatter`'s binary surface is now EMPTY, which is the goal state, and a
# positive naming a method the derivation cannot find scores zero.
#
# Task 7 therefore made the formatter leg read the SCANNED FILE's own class
# declarations as well, exactly as the conversion leg has read the scanned
# file's own function declarations since task 5, and these fixtures declare
# theirs. That closes the corpus's dependence on a production name for good:
# the file docstring's claim that "nothing here reads a production line" is
# true again. It also closes a real same-file blindness, which is why it is a
# gate change and not a test convenience.
#
# ★ TWO DELIBERATE NAMING CHOICES, both so the mutations keep their precision.
# The class is called `UnitFormatter` because M49 mutates the leg into requiring
# that exact receiver SPELLING, and its whole subject is that an alias
# (S-P35's `UF`) must not be a bypass; a fixture class named anything else would
# make M49 flip all three formatter positives instead of the one it is about.
# `formatRate` starts with `format` because M45 mutates the derivation into a
# `format*` NAME rule, and its subject is that label selectors like `unitLabel`
# are just as binary; a fixture where BOTH methods failed that prefix would make
# M45 flip more than it is measuring. Neither method name may equal the EXPORTED
# WRAPPER's name in a case that uses it, which is why the label selector is
# `unitLabel` and not `unit`: M53 turns every exported function into a
# binary-conversion helper, and a call whose name matches one then scores a
# second finding on top of the formatter one, so the case reads as flipped for
# a reason that has nothing to do with the mutation it is pinned by. Measured,
# not reasoned: the run said `M53 *** WRONG CASES FLIPPED ***` and named them. The class is the fixture's own declaration
# either way: production's `UnitFormatter` has no binary method left.
FIXTURE_FORMATTER = (
    "import type { UnitSystem } from '@/utils/units'\n"
    "export class UnitFormatter {\n"
    "  static formatRate(value: number, system: UnitSystem): string {\n"
    "    return String(value) + system\n"
    "  }\n"
    "  static unitLabel(system: UnitSystem): string {\n"
    "    return String(system)\n"
    "  }\n"
    "}\n"
)

SCRIPT_POSITIVE = [
    Case(
        "S-P1-eq-imperial",
        HOOK_IMPORT + "export function distanceLabel(): string {\n"
        "  const { system } = useUnitPreference()\n"
        "  return system === 'imperial' ? 'mi' : 'km'\n"
        "}\n",
        1,
        "compare",
        "the canonical forbidden branch",
        "M17-drop-imperial-literal",
    ),
    Case(
        "S-P2-eq-metric",
        HOOK_IMPORT + "export function volumeLabel(): string {\n"
        "  const { system } = useUnitPreference()\n"
        "  return system === 'metric' ? 'L' : 'gal'\n"
        "}\n",
        1,
        "compare",
        "R2: v1 prohibited only the imperial half; production spells it both ways",
        "M20-drop-metric-literal",
    ),
    Case(
        "S-P3-yoda",
        HOOK_IMPORT + "export function isImperial(): boolean {\n"
        "  const { system } = useUnitPreference()\n"
        "  return 'imperial' === system\n"
        "}\n",
        1,
        "compare",
        "operand order must not matter",
        "M1-drop-yoda",
    ),
    Case(
        "S-P4-neq",
        HOOK_IMPORT + "export function isMetric(): boolean {\n"
        "  const { system } = useUnitPreference()\n"
        "  return system !== 'imperial'\n"
        "}\n",
        1,
        "compare",
        "negation is the same decision",
        "M2-drop-neq",
    ),
    Case(
        "S-P5-switch",
        HOOK_IMPORT + "export function pressureLabel(): string {\n"
        "  const { system } = useUnitPreference()\n"
        "  switch (system) {\n"
        "    case 'imperial':\n"
        "      return 'PSI'\n"
        "    case 'metric':\n"
        "      return 'bar'\n"
        "    default:\n"
        "      return ''\n"
        "  }\n"
        "}\n",
        2,
        "switch-case",
        "a switch is a branch wearing different punctuation",
        "M3-drop-switch",
    ),
    Case(
        "S-P6-aliased-boolean",
        HOOK_IMPORT + "export function treadLabel(): string {\n"
        "  const { system } = useUnitPreference()\n"
        "  const isImp = system === 'imperial'\n"
        "  return isImp ? 'in' : 'mm'\n"
        "}\n",
        1,
        "compare",
        "hiding the branch behind a boolean does not remove it",
        "M18-skip-variable-initialisers",
    ),
    Case(
        "S-P7-destructuring-rename",
        HOOK_IMPORT + "export function speedLabel(): string {\n"
        "  const { system: unitSystem } = useUnitPreference()\n"
        "  return unitSystem === 'imperial' ? 'mph' : 'km/h'\n"
        "}\n",
        1,
        "compare",
        "R2: a selector keyed on Identifier[name='system'] misses this",
        "M19-key-on-identifier-name",
    ),
    Case(
        "S-P8-resolvedSystem",
        HOOK_IMPORT + "export function tempLabel(): string {\n"
        "  const { system: resolvedSystem } = useUnitPreference()\n"
        "  return resolvedSystem === 'imperial' ? 'F' : 'C'\n"
        "}\n",
        1,
        "compare",
        "T4-R3: this spelling is real, at SettingsSystemTab.tsx:81",
        "M19-key-on-identifier-name",
    ),
    Case(
        "S-P9-displaySystem",
        "export function massLabel(displaySystem: string): string {\n"
        "  return displaySystem === 'metric' ? 'kg' : 'lbs'\n"
        "}\n",
        1,
        "compare",
        "T4-R3: real spelling at SettingsSystemTab.tsx:82; `string` earns no silence",
        "M6-string-is-foreign",
    ),
    Case(
        "S-P10-member-expression",
        "interface Props { system: string }\n"
        "export function torqueLabel(props: Props): string {\n"
        "  return props.system === 'imperial' ? 'lb-ft' : 'Nm'\n"
        "}\n",
        1,
        "compare",
        "an operand the gate cannot resolve is flagged, not waved through",
        "M4-unresolved-is-exempt",
    ),
    Case(
        "S-P11-annotated-unitsystem",
        "import type { UnitSystem } from '@/utils/units'\n"
        "export function economyLabel(system: UnitSystem): string {\n"
        "  return system === 'imperial' ? 'MPG' : 'L/100km'\n"
        "}\n",
        1,
        "compare",
        "the annotation exemption must not swallow the annotation that proves it",
        "M5-unitsystem-is-foreign",
    ),
    Case(
        "S-P12-ts-angle-assertion",
        "const raw: unknown = null\n"
        "export const asText = <string>raw\n"
        "export function label(system: string): string {\n"
        "  return system === 'imperial' ? 'mi' : 'km'\n"
        "}\n",
        1,
        "compare",
        "★ legal TS, illegal TSX: round 1 parsed every file as TSX and lost this whole file",
        "M22-hardcode-tsx-scriptkind",
        ext=".ts",
    ),
    Case(
        "S-P13-unparseable",
        "export const broken = (\n",
        -1,
        "parse error",
        "★ a file the parser rejects must make the gate REFUSE, not report zero",
        "M23-ignore-parse-diagnostics",
        ext=".ts",
    ),
    Case(
        "S-P14-alias-union",
        "type Sys = 'imperial' | 'metric'\n"
        "declare function getSys(): Sys\n"
        "export function label(): string {\n"
        "  const s: Sys = getSys()\n"
        "  return s === 'imperial' ? 'mi' : 'km'\n"
        "}\n",
        1,
        "compare",
        "R8: this repo re-declares the union, and a name denylist walks straight past an alias",
        "M24-drop-alias-expansion",
    ),
    Case(
        "S-P15-imported-alias",
        "import type { BinarySystem } from '@/utils/units'\n"
        "export function label(s: BinarySystem): string {\n"
        "  return s === 'imperial' ? 'mi' : 'km'\n"
        "}\n",
        1,
        "compare",
        "an annotation the gate cannot resolve earns no silence: a rename is not an escape hatch",
        "M25-unresolvable-alias-is-foreign",
    ),
    Case(
        "S-P16-widened-alias",
        "type Pref = 'imperial' | 'metric' | 'custom'\n"
        "declare function getPref(): Pref\n"
        "export function label(): string {\n"
        "  const p: Pref = getPref()\n"
        "  return p === 'imperial' ? 'mi' : 'km'\n"
        "}\n",
        1,
        "compare",
        "phase 1 widened the union to admit 'custom'; it is still a unit system",
        "M26-drop-custom-from-vocabulary",
    ),
    Case(
        "S-P17-loose-equality",
        HOOK_IMPORT + "export function label(): string {\n"
        "  const { system } = useUnitPreference()\n"
        "  return system == 'imperial' ? 'mi' : 'km'\n"
        "}\n",
        1,
        "compare",
        "nothing in this repo forbids ==, so the gate cannot assume === ",
        "M27-drop-loose-equality",
    ),
    Case(
        "S-P18-template-literal",
        HOOK_IMPORT + "export function label(): string {\n"
        "  const { system } = useUnitPreference()\n"
        "  return system === `imperial` ? 'mi' : 'km'\n"
        "}\n",
        1,
        "compare",
        "a backtick literal is the same comparison with different punctuation",
        "M28-drop-template-literal-kind",
    ),
    Case(
        "S-P19-shadowed-name",
        "type Theme = 'light' | 'dark' | 'imperial'\n"
        "declare function resolveTheme(): Theme\n"
        + HOOK_IMPORT
        + "export function a(): string {\n"
        "  const mode: Theme = resolveTheme()\n"
        "  return mode === 'imperial' ? 'x' : 'y'\n"
        "}\n"
        "export function b(): string {\n"
        "  const { system: mode } = useUnitPreference()\n"
        "  return mode === 'imperial' ? 'mi' : 'km'\n"
        "}\n",
        2,
        "compare",
        "the flat index the docstring argues for: one foreign declaration must not "
        "silence a bare one sharing the name",
        "M29-any-declaration-exempts",
    ),
    Case(
        "S-P20-multiline",
        HOOK_IMPORT + "export function label(): string {\n"
        "  const { system } = useUnitPreference()\n"
        "  return (\n"
        "    system ===\n"
        "    'imperial'\n"
        "      ? 'mi'\n"
        "      : 'km'\n"
        "  )\n"
        "}\n",
        1,
        "compare",
        "a wrapped comparison must key the same as a flat one or the baseline splits in two",
        "M30-drop-normalize",
        expect_text="system === 'imperial'",
    ),
    Case(
        "S-P21-non-placeholder-attribute",
        HOOK_IMPORT + "export function Field(): JSX.Element {\n"
        "  const { system } = useUnitPreference()\n"
        "  return <input title={system === 'imperial' ? 'miles' : 'kilometres'} />\n"
        "}\n",
        1,
        "compare",
        "★ R5 exempts `placeholder`, not JSX: widening it took the real gate 45 -> 37 and exit 0",
        "M31-any-jsx-attribute-exempts",
    ),
    Case(
        "S-P22-bare-pragma",
        HOOK_IMPORT + "export function label(): string {\n"
        "  const { system } = useUnitPreference()\n"
        "  // units-exempt\n"
        "  return system === 'imperial' ? 'mi' : 'km'\n"
        "}\n",
        1,
        "compare",
        "the docstring and the failure message both promise a reason, so a bare marker cannot silence",
        "M32-pragma-without-reason",
    ),
    Case(
        "S-P23-string-union",
        "export function readStored(): string | null {\n"
        "  const stored: string | null = localStorage.getItem('unit_preference')\n"
        "  return stored === 'imperial' ? stored : null\n"
        "}\n",
        1,
        "compare",
        "the real shape at useUnitPreference.ts. Round 2 pinned this to a NAME-list "
        "mutation and the name list turned out to be redundant, so the case passed "
        "for a reason it did not name; `string` is UNKNOWN and fail-closed",
        "M41-unknown-member-is-foreign",
        ext=".ts",
    ),
    Case(
        "S-P24-unitsystem-union",
        "import type { UnitSystem } from '@/utils/units'\n"
        "export function label(s: UnitSystem | null): string {\n"
        "  return s === 'imperial' ? 'mi' : 'km'\n"
        "}\n",
        1,
        "compare",
        "★ this is `readStoredUnitSystem`'s own return type. Round 2 caught it only "
        "because the NAME `UnitSystem` appeared in the text; spelled out or aliased "
        "it walked past. Now it is an UNKNOWN member beside a stripped nullish one",
        "M41-unknown-member-is-foreign",
        ext=".ts",
    ),
    Case(
        "S-P25-nullable-unit-union",
        "export function label(s: 'imperial' | 'metric' | null): string {\n"
        "  return s === 'imperial' ? 'mi' : 'km'\n"
        "}\n",
        1,
        "compare",
        "★ the F2 REGRESSION: round 1 caught this, round 2 read one non-vocabulary "
        "member as proof the whole annotation was foreign. A nullable unit system "
        "is a unit system, and this is the case that exercises the vocabulary half",
        "M39-keep-nullish-members",
        ext=".ts",
    ),
    Case(
        "S-P26-parenthesised-alias",
        "type Sys = ('imperial' | 'metric')\n"
        "export function label(s: Sys): string {\n"
        "  return s === 'imperial' ? 'mi' : 'km'\n"
        "}\n",
        1,
        "compare",
        "one pair of parentheses was a complete bypass. It is now defended twice, "
        "by paren stripping and by the fail-closed UNKNOWN class, so only a "
        "mutation removing BOTH flips it",
        "M40b-parens-unread-then-exempt",
        ext=".ts",
    ),
    Case(
        "S-P27-indexed-access",
        "const SYSTEMS = ['imperial', 'metric'] as const\n"
        "export function label(s: (typeof SYSTEMS)[number]): string {\n"
        "  return s === 'imperial' ? 'mi' : 'km'\n"
        "}\n",
        1,
        "compare",
        "a type expression the gate cannot read is not evidence of innocence",
        "M41-unknown-member-is-foreign",
        ext=".ts",
    ),
    Case(
        "S-P28-alias-or-undefined",
        "type Sys = 'imperial' | 'metric'\n"
        "export function label(s: Sys | undefined): string {\n"
        "  return s === 'imperial' ? 'mi' : 'km'\n"
        "}\n",
        1,
        "compare",
        "the alias must be resolved at MEMBER level, not only when it is the whole text",
        "M39-keep-nullish-members",
        ext=".ts",
    ),
    Case(
        "S-P29-backtick-vocabulary",
        "type Sys = `imperial` | 'metric'\n"
        "export function label(s: Sys): string {\n"
        "  return s === 'imperial' ? 'mi' : 'km'\n"
        "}\n",
        1,
        "compare",
        "★ a FAIL-OPEN, not a miss: STRING_LITERAL_TYPE recognises a backtick "
        "literal, so `imperial` was confidently classified foreign instead of "
        "falling through to fail-closed unknown, and ONE such member exempted the "
        "whole union. The all-backtick spelling is the same code path.",
        "M43-drop-backtick-vocabulary",
        ext=".ts",
    ),
    # ---- phase 3b: the three shapes the comparison leg cannot see -----------
    Case(
        "S-P30-formatter-binary-call",
        FIXTURE_FORMATTER
        + HOOK_IMPORT
        + "export function costRate(costPerKm: number): string {\n"
        "  const { system } = useUnitPreference()\n"
        "  return UnitFormatter.formatRate(costPerKm, system)\n"
        "}\n",
        1,
        "formatter-binary",
        "★ nothing at this call site names a system: the binary collapse happens "
        "inside the callee, so the comparison leg is blind to it by construction. "
        "It spelled `formatDistance` until task 6 deleted that method, then "
        "`formatFuelEconomy` until task 6b, then `formatCostPerDistance` until "
        "task 7 retired the last two; each time the case scored zero and the "
        "corpus said so, because a positive naming a method the DERIVATION can no "
        "longer find is a case that passes for the wrong reason. There is no "
        "production binary formatter left to spell, which is the goal state, so "
        "the fixture DECLARES one — the same move S-P32 made when task 5 deleted "
        "the conversion helpers.",
        "M44-drop-formatter-leg",
        ext=".ts",
    ),
    Case(
        "S-P31-formatter-label-selector",
        FIXTURE_FORMATTER
        + HOOK_IMPORT
        + "export function unit(): string {\n"
        "  const { system } = useUnitPreference()\n"
        "  return UnitFormatter.unitLabel(system)\n"
        "}\n",
        1,
        "formatter-binary",
        "★ THE case that makes the set DERIVED rather than transcribed: round 1 "
        "hand-listed the `format*` methods and missed every label selector, which "
        "takes the same binary system and is just as wrong for a mixed user. It "
        "spelled `getDistanceUnit` until task 6 retired that one, "
        "`getFuelRateUnit` until task 6b retired the next and "
        "`getCostPerDistanceLabel` until task 7 retired the last; a label "
        "selector is a label selector whichever quantity it names, and the "
        "fixture's own `unit` is deliberately named nothing like `get*Label` so "
        "the rule cannot be passing on a name shape.",
        "M45-formatter-format-prefix-only",
        ext=".ts",
    ),
    Case(
        "S-P32-binary-conversion-call",
        "import type { UnitSystem } from '@/utils/units'\n"
        + HOOK_IMPORT
        + "export function toCanonicalKm(value: number, system: UnitSystem): number {\n"
        "  return convert(value, system)\n"
        "}\n"
        "export function submit(entered: number): number {\n"
        "  const { system } = useUnitPreference()\n"
        "  return toCanonicalKm(entered, system)\n"
        "}\n",
        1,
        "binary-conversion",
        "★ R8: this one WRITES. `system` collapses from volume, so a "
        "{volume:'L', distance:'mi'} user's 500 miles is stored as 500 km, and "
        "neither of the originally proposed gate legs saw the function that "
        "wrote the wrong number. Task 5 DELETED the three real helpers, so the "
        "fixture declares its own: the leg reads `decimalSafe.ts` plus the file "
        "under scan, and this half is now the only half with a population. The "
        "body delegates instead of comparing so the one finding is the CALL, "
        "not a `system === 'metric'` inside the declaration",
        "M46-drop-conversion-leg",
        ext=".ts",
    ),
    Case(
        "S-P33-token-branch-property",
        "import type { UnitSet } from '@/types/units'\n"
        "export function label(units: UnitSet, km: number): string {\n"
        "  return units.volume === 'L' ? `${km} km` : `${km} mi`\n"
        "}\n",
        1,
        "token-branch",
        "scope category 4: DISTANCE collapsed out of VOLUME, with no 'imperial' "
        "or 'metric' anywhere. Live at PropaneRecordList and twice in Analytics.",
        "M47-drop-token-branch-leg",
        ext=".ts",
    ),
    Case(
        "S-P34-token-branch-destructured",
        "import type { UnitSet } from '@/types/units'\n"
        "export function label(units: UnitSet): string {\n"
        "  const { volume } = units\n"
        "  return volume === 'L' ? 'km' : 'mi'\n"
        "}\n",
        1,
        "token-branch",
        "keying on the property access alone would make one destructure a bypass, "
        "which is S-P7's rename wearing different punctuation",
        "M48-token-branch-property-only",
        ext=".ts",
    ),
    Case(
        "S-P35-aliased-formatter-receiver",
        FIXTURE_FORMATTER
        + HOOK_IMPORT
        + "const UF = UnitFormatter\n"
        "export function unit(): string {\n"
        "  const { system } = useUnitPreference()\n"
        "  return UF.unitLabel(system)\n"
        "}\n",
        1,
        "formatter-binary",
        "the receiver is REQUIRED but never READ: requiring the spelling makes "
        "`import { UnitFormatter as UF }` a one-line bypass. It spelled that "
        "import until task 7 retired the last production binary formatter; a "
        "local alias of the fixture's own class is the same decision through the "
        "same shape, and it no longer depends on a name production owns.",
        "M49-formatter-receiver-spelling",
        ext=".ts",
    ),
    Case(
        "S-P37-binary-formatter-on-a-foreign-class",
        "import type { UnitSystem } from '@/utils/units'\n"
        + HOOK_IMPORT
        + "class TripFormatter {\n"
        "  static formatLeg(km: number, system: UnitSystem): string {\n"
        "    return String(km) + system\n"
        "  }\n"
        "}\n"
        "export function leg(km: number): string {\n"
        "  const { system } = useUnitPreference()\n"
        "  return TripFormatter.formatLeg(km, system)\n"
        "}\n",
        1,
        "formatter-binary",
        "★ THE CASE THAT MAKES THE PER-FILE AUGMENTATION FALSIFIABLE. S-P30, "
        "S-P31 and S-P35 all declare a class called `UnitFormatter`, chosen so "
        "M49's receiver-spelling mutation keeps a precise subject, and that means "
        "narrowing the scan to the production class NAME would leave all three "
        "passing. This one names its class something else, so it fails the moment "
        "the augmentation stops meaning 'any class this file declares'. It is "
        "also the shape the augmentation exists to catch: a module that declares "
        "its own static binary formatter and calls it makes the D8-collapsed "
        "decision where neither the comparison leg (the comparison is inside the "
        "callee) nor the derived leg (the method is not on `UnitFormatter`) can "
        "see it.",
        "M67-augmentation-only-the-production-class",
        ext=".ts",
    ),
    # ---- task 8: the precondition. Shapes the exact-text predicate missed. ----
    #
    # ★ ALL FOUR ARE binary-conversion RATHER THAN compare, and that is the
    # point rather than a convenience. `takesBinarySystem` is what builds BOTH
    # binary vocabularies, so a shape it cannot read is a helper whose entire
    # call-site population is invisible: no `imperial` literal, no
    # `UnitFormatter` receiver, nothing at the call site to see. Three of the
    # nineteen production declarations carrying the type were in these shapes
    # when task 8 started, two of them live components on the supplies path.
    Case(
        "S-P38-aliased-import-annotation",
        "import type { UnitSystem as Sys } from '@/utils/units'\n"
        + HOOK_IMPORT
        + "export function toCanonicalFathoms(value: number, s: Sys): number {\n"
        "  return convert(value, s)\n"
        "}\n"
        "export function submit(entered: number): number {\n"
        "  const { system } = useUnitPreference()\n"
        "  return toCanonicalFathoms(entered, system)\n"
        "}\n",
        1,
        "binary-conversion",
        "an aliased import renames the annotation and nothing else. The old "
        "predicate compared the annotation TEXT to the literal 'UnitSystem', so "
        "one `as Sys` retired the whole leg for that helper.",
        "M68-exact-annotation-text-only",
        ext=".ts",
    ),
    Case(
        "S-P39-union-annotation",
        "import type { UnitSystem } from '@/utils/units'\n"
        + HOOK_IMPORT
        + "export function toCanonicalFurlongs(value: number, s: UnitSystem | undefined): number {\n"
        "  return convert(value, s)\n"
        "}\n"
        "export function submit(entered: number): number {\n"
        "  const { system } = useUnitPreference()\n"
        "  return toCanonicalFurlongs(entered, system)\n"
        "}\n",
        1,
        "binary-conversion",
        "a nullable binary system is a binary system, which the comparison leg "
        "learned in round 2 (`NULLISH_MEMBERS`) and the derivation had not.",
        "M68-exact-annotation-text-only",
        ext=".ts",
    ),
    Case(
        "S-P40-inline-props-annotation",
        "import type { UnitSystem } from '@/utils/units'\n"
        + HOOK_IMPORT
        + "export function toCanonicalChains(value: number, opts: { system: UnitSystem }): number {\n"
        "  return convert(value, opts.system)\n"
        "}\n"
        "export function submit(entered: number): number {\n"
        "  const { system } = useUnitPreference()\n"
        "  return toCanonicalChains(entered, { system })\n"
        "}\n",
        1,
        "binary-conversion",
        "an inline props object, the shape SupplyHistoryModal's PurchaseForm "
        "and AdjustmentForm both use. The decision is identical; only the "
        "punctuation differs.",
        "M68-exact-annotation-text-only",
        ext=".ts",
    ),
    Case(
        "S-P41-named-props-interface",
        "import type { UnitSystem } from '@/utils/units'\n"
        + HOOK_IMPORT
        + "interface ChainOpts {\n"
        "  system: UnitSystem\n"
        "}\n"
        "export function toCanonicalRods(value: number, opts: ChainOpts): number {\n"
        "  return convert(value, opts.system)\n"
        "}\n"
        "export function submit(entered: number): number {\n"
        "  const { system } = useUnitPreference()\n"
        "  return toCanonicalRods(entered, { system })\n"
        "}\n",
        1,
        "binary-conversion",
        "the same shape one indirection further out, which is how "
        "SupplyHistoryModal's PurchaseRow spells it. Resolving it needs the "
        "file's own interface declarations, not just its parameter text.",
        "M69-props-types-unresolved",
        ext=".ts",
    ),
    # ---- fix round 1: the three declaration spellings the leg could not see --
    #
    # ★ ALL THREE WERE LIVE IN PRODUCTION when the flip shipped, five
    # declarations carrying ten call sites on the supplies path, and the review
    # found them by adding `export` and nothing else. The walk behind the
    # vocabulary required an EXPORTED top-level `function`, which is one
    # visibility modifier and one syntax kind away from the shape the whole
    # precondition was about.
    Case(
        "S-P45-module-local-helper",
        "import type { UnitSystem } from '@/utils/units'\n"
        + HOOK_IMPORT
        + "function toCanonicalYards(value: number, s: UnitSystem): number {\n"
        "  return convert(value, s)\n"
        "}\n"
        "export function submit(entered: number): number {\n"
        "  const { system } = useUnitPreference()\n"
        "  return toCanonicalYards(entered, system)\n"
        "}\n",
        1,
        "binary-conversion",
        "a module-local helper, which is `export function canonicalToDisplay` "
        "minus one keyword. It can only be called where it is declared, and the "
        "scanner already parses that file, so there was never a reason to "
        "require the keyword. `SupplyHistoryModal.tsx` had three of these.",
        "M78-only-exported-declarations",
        ext=".ts",
    ),
    Case(
        "S-P46-exported-arrow-helper",
        "import type { UnitSystem } from '@/utils/units'\n"
        + HOOK_IMPORT
        + "export const toCanonicalLinks = (value: number, s: UnitSystem): number =>\n"
        "  convert(value, s)\n"
        "export function submit(entered: number): number {\n"
        "  const { system } = useUnitPreference()\n"
        "  return toCanonicalLinks(entered, system)\n"
        "}\n",
        1,
        "binary-conversion",
        "an arrow const, which is 52 declarations' worth of daily spelling under "
        "`src/` and carried its `export` on the VariableStatement two levels up, "
        "so asking the declaration itself always answered no.",
        "M79-only-function-declarations",
        ext=".ts",
    ),
    Case(
        "S-P47-instance-method",
        "import type { UnitSystem } from '@/utils/units'\n"
        + HOOK_IMPORT
        + "class TripFormatter {\n"
        "  formatLeg(km: number, system: UnitSystem): string {\n"
        "    return String(km) + system\n"
        "  }\n"
        "}\n"
        "export function leg(km: number): string {\n"
        "  const { system } = useUnitPreference()\n"
        "  return new TripFormatter().formatLeg(km, system)\n"
        "}\n",
        1,
        "formatter-binary",
        "the formatter leg's half of the same floor: it required `StaticKeyword`, "
        "though `this.format(km, system)` is the identical decision and the leg's "
        "receiver requirement already matches an instance call.",
        "M80-only-static-methods",
        ext=".ts",
    ),
    Case(
        "S-P48-renaming-import-alias",
        "import type { UnitSystem } from '@/utils/units'\n"
        "import { toCanonicalPoles as tcp } from './elsewhere'\n"
        + HOOK_IMPORT
        + "export function toCanonicalPoles(value: number, s: UnitSystem): number {\n"
        "  return convert(value, s)\n"
        "}\n"
        "export function submit(entered: number): number {\n"
        "  const { system } = useUnitPreference()\n"
        "  return tcp(entered, system)\n"
        "}\n",
        1,
        "binary-conversion",
        "★ `calleeName`'s docstring has said \"an import alias must not be an "
        "escape hatch\" since task 5, and the formatter leg defends against "
        "`import { UnitFormatter as UF }`, but that closed it on the RECEIVER "
        "only: a renaming import of the CALLEE was invisible in both the call "
        "form and the value form, while the namespace form was caught all along, "
        "which is what made the gap easy to miss. The fixture declares the name "
        "so it is in this file's own vocabulary, and calls it through the alias.",
        "M81-drop-import-alias-resolution",
        ext=".ts",
    ),
    Case(
        "S-P49-binary-props-component-render",
        "import type { UnitSystem } from '@/utils/units'\n"
        + HOOK_IMPORT
        + "function ProbeRow({ km, system }: { km: number; system: UnitSystem }): JSX.Element {\n"
        "  return <span>{String(km) + system}</span>\n"
        "}\n"
        "export function Panel(): JSX.Element {\n"
        "  const { system } = useUnitPreference()\n"
        "  return <ProbeRow km={12} system={system} />\n"
        "}\n",
        1,
        "binary-conversion",
        "★ THE RENDER LEG, AND THE TEXT IT REPORTS. A component whose props carry "
        "the binary system IS a binary API by the rule the precondition set, and "
        "its JSX element is where the collapsed system crosses that boundary: an "
        "element is an invocation, not a value. `expect_text` pins the label, "
        "because fix round 1 added the branch that produces it and NOTHING could "
        "kill it: deleting the ternary so every render read `X (as a value)` left "
        "all 84 corpus cases and all 9 API-surface tests green. A guard no test "
        "can kill is this phase's own recorded pattern, and it was in code written "
        "to close an instance of it. Four such components are live on the supplies "
        "path, exempted at their declarations.",
        "M83-jsx-render-labelled-as-a-value",
        expect_text="<ProbeRow ...>",
    ),
    Case(
        "S-P44-binary-helper-as-a-value",
        "import type { UnitSystem } from '@/utils/units'\n"
        "export function toCanonicalSpans(value: number, s: UnitSystem): number {\n"
        "  return convert(value, s)\n"
        "}\n"
        # ★ `apply` deliberately does NOT name the binary type, and there is no
        # comparison anywhere. Fix round 1 put module-local declarations into the
        # vocabulary, so the first spelling of this fixture scored a second
        # finding on `apply(...)` and stopped measuring one thing; writing the
        # union out keeps `apply` from being a binary API itself. Same reason the
        # formatter cases pick their method names the way they do.
        "function apply(v: number, f: (v: number, s: 'metric' | 'imperial') => number): number {\n"
        "  return f(v, 'metric')\n"
        "}\n"
        "export function submit(entered: number): number {\n"
        "  return apply(entered, toCanonicalSpans)\n"
        "}\n",
        1,
        "binary-conversion",
        "★ THE SAME DECISION WITHOUT THE PARENTHESES, and it was live in "
        "production when task 8 found it. The leg matched a CallExpression whose "
        "callee is in the vocabulary, so `displayToCanonical(v, t, system)` was a "
        "finding and `convertSupplyUsages(usages, byId, system, "
        "displayToCanonical)` was not: the helper travels as a VALUE and the "
        "D8-collapsed decision happens one frame down where nothing looks. Both "
        "spellings are in `ServiceVisitForm.tsx`, and the second is the WRITE "
        "path. Closed rather than declared, for the reason S-P7 and S-P35 are: "
        "one decision spelled differently is not a new category.",
        "M75-drop-value-reference-leg",
        ext=".ts",
    ),
    Case(
        "S-P42-scoped-pragma-wrong-kind",
        "import type { UnitSet } from '@/types/units'\n"
        "export function label(units: UnitSet, km: number): string {\n"
        "  // units-exempt(compare): a reason, for a leg this line does not carry.\n"
        "  return units.volume === 'L' ? `${km} km` : `${km} mi`\n"
        "}\n",
        1,
        "token-branch",
        "★ THE WHOLE VALUE OF THE KIND LIST, and the objection it answers is on "
        "the record: `units.manifest.json` said a reason-bearing pragma "
        "\"silences anything\". This one names the comparison leg and the line "
        "carries a token branch, so the finding stands. Without the scope check "
        "the same pragma silences a defect class its author never considered, "
        "which matters most after the clean-room flip because the pragma is then "
        "the only suppression left in the gate.",
        "M72-scoped-pragma-silences-anything",
        ext=".ts",
    ),
    Case(
        "S-P43-scoped-declaration-wrong-kind",
        "import type { UnitSystem } from '@/utils/units'\n"
        + HOOK_IMPORT
        + "// units-exempt(compare): a reason, for a leg a declaration cannot carry.\n"
        "export function toCanonicalCubits(value: number, s: UnitSystem): number {\n"
        "  return convert(value, s)\n"
        "}\n"
        "export function submit(entered: number): number {\n"
        "  const { system } = useUnitPreference()\n"
        "  return toCanonicalCubits(entered, system)\n"
        "}\n",
        1,
        "binary-conversion",
        "S-P42's rule where it matters most. The DECLARATION hatch is the only "
        "suppression in this gate that reaches other files, so the kind it names "
        "has to be the kind it removes: `(compare)` on an exported binary helper "
        "silences nothing, and the fifteen sites of `supplyUnits.ts`'s three "
        "stay visible unless the pragma says `binary-conversion`. Without this "
        "case the kind argument threaded into `declarationExempt` is a guard no "
        "mutation could kill.",
        "M72-scoped-pragma-silences-anything",
        ext=".ts",
    ),
    Case(
        "S-P36-double-quoted-union",
        'type Sys = "imperial" | "metric"\n'
        "export function label(s: Sys): string {\n"
        "  return s === 'imperial' ? 'mi' : 'km'\n"
        "}\n",
        1,
        "compare",
        "R6 carry, branch 6 of 6: UNIT_VOCABULARY's double-quoted forms went in "
        "during round 2 and were still unexercised three rounds later",
        "M50-drop-double-quoted-vocabulary",
        ext=".ts",
    ),
]

SCRIPT_NEGATIVE = [
    Case(
        "S-N1-placeholder",
        HOOK_IMPORT + "export function OdometerField(): JSX.Element {\n"
        "  const { system } = useUnitPreference()\n"
        "  return <input placeholder={system === 'imperial' ? '45000' : '72420'} />\n"
        "}\n",
        0,
        why="R5: a placeholder is a plausible EXAMPLE value; nothing canonical to convert",
        pinned_by="M7-drop-placeholder-exemption",
    ),
    Case(
        "S-N2-foreign-provenance",
        "type Theme = 'light' | 'dark' | 'imperial'\n"
        "declare function resolveTheme(): Theme\n"
        "export function themeClass(): string {\n"
        "  const theme: Theme = resolveTheme()\n"
        "  return theme === 'imperial' ? 'skin-imperial' : 'skin-plain'\n"
        "}\n",
        0,
        why="R3: the case no no-restricted-syntax selector can tell apart, and the "
        "one that decides how per-member classification must round: a member no unit "
        "system has ever contained means a different enum sharing a spelling",
        pinned_by="M8-drop-annotation-exemption / M38-any-unit-member-flags",
    ),
    Case(
        "S-N6-parenthesised-foreign-alias",
        "type Theme = ('light' | 'dark' | 'imperial')\n"
        "declare function resolveTheme(): Theme\n"
        "export function themeClass(): string {\n"
        "  const theme: Theme = resolveTheme()\n"
        "  return theme === 'imperial' ? 'a' : 'b'\n"
        "}\n",
        0,
        why="paren stripping can only be pinned from the NEGATIVE side: dropping it "
        "makes the gate stricter, so no positive can flip, and this one goes 0 to 1",
        pinned_by="M40-drop-paren-stripping",
        ext=".ts",
    ),
    Case(
        "S-N3-near-miss-literal",
        "export function describe(label: Readonly<{ text: string }>): boolean {\n"
        "  return label.text === 'imperial units'\n"
        "}\n",
        0,
        why="the literal must match exactly, not merely contain the word",
        pinned_by="M9-literal-contains",
    ),
    Case(
        "S-N4-pragma",
        HOOK_IMPORT + "export function legacyLabel(): string {\n"
        "  const { system } = useUnitPreference()\n"
        "  // units-exempt: parses a browser key phase 4 retires, not a display branch\n"
        "  const above = system === 'imperial' ? 'mi' : 'km'\n"
        "  const same = system === 'metric' ? 'km' : 'mi' // units-exempt: same reason\n"
        "  return above + same\n"
        "}\n",
        0,
        why="R4: BOTH documented positions, the line above and the line itself",
        pinned_by="M10a-drop-same-line-pragma / M10b-drop-line-above-pragma",
    ),
    Case(
        "S-N5-positive-control",
        "import { useUnitFormat } from '@/hooks/useUnitFormat'\n"
        "export function TreadCell(props: Readonly<{ mm: number; label: string }>): JSX.Element {\n"
        "  const u = useUnitFormat()\n"
        "  const unlabelled = props.label === ''\n"
        "  return <span>{unlabelled ? '' : u.tread.toDisplayText(props.mm)}</span>\n"
        "}\n",
        0,
        why="T4-R7 positive control: correctly migrated code must be silently clean",
        pinned_by="M11-flag-every-equality",
        tags=["control"],
    ),
    # ---- phase 3b: what the three new legs must NOT catch -------------------
    Case(
        "S-N7-formatter-resolved-set",
        "import { UnitFormatter } from '@/utils/units'\n"
        "import type { UnitSet } from '@/types/units'\n"
        "export function label(liters: number, units: UnitSet): string {\n"
        "  return UnitFormatter.formatVolume(liters, units)\n"
        "}\n",
        0,
        why="the DESTINATION shape. A UnitSet-taking formatter is what the binary "
        "ones must become, so a leg that flags it flags correct code",
        pinned_by="M51-every-static-method-is-binary",
        ext=".ts",
    ),
    Case(
        "S-N8-local-format-distance",
        FIXTURE_FORMATTER
        + "import type { UnitSet } from '@/types/units'\n"
        "function formatRate(perKm: number, units: UnitSet): string {\n"
        "  return `${perKm} ${units.distance}`\n"
        "}\n"
        "export function cell(v: number, units: UnitSet): string {\n"
        "  return formatRate(v, units)\n"
        "}\n",
        0,
        why="★ POICard's real shape, measured: matching the METHOD NAME alone "
        "flagged three module-local `formatDistance` helpers, and POICard's is "
        "correct migrated code taking a resolved set. A static method is only "
        "reachable through a receiver, so requiring one separates them. "
        "★ IT HAS BEEN RENAMED TWICE AND IS NOW SELF-OWNED, which is better than "
        "the third rename its old comment planned for. It spelled the helper "
        "`formatDistance` until task 6 and `formatFuelEconomy` until task 6b; each "
        "retirement took that name out of the DERIVED set, so the fixture stopped "
        "colliding with anything and M52 became a survivor flipping nothing. Task "
        "7 retired the last two binary formatters and left no production name to "
        "collide with at all, so the fixture declares the class AND the "
        "module-local helper that shadows one of its method names. The collision "
        "is now a property of this file, and M52 has a subject that cannot "
        "expire.",
        pinned_by="M52-formatter-name-without-receiver",
        ext=".ts",
    ),
    Case(
        "S-N9-set-conversion-helper",
        "import { seedPriceField } from '@/utils/decimalSafe'\n"
        "import type { UnitSet } from '@/types/units'\n"
        "export function seed(stored: number, units: UnitSet): string {\n"
        "  return seedPriceField(stored, units, 'per_volume').display\n"
        "}\n",
        0,
        why="R8's destination: the resolved-set helper beside the binary ones "
        "in the same file, so the leg cannot key on the file or the name prefix. "
        "It spelled `toCanonicalLiters` until task 7 deleted that one for a "
        "different defect (it converted a DISPLAY value straight to canonical, "
        "which is ruling R4's entry-grid shift); the case needs a name the "
        "mutation M53 can still reach, so it spells a survivor.",
        pinned_by="M53-every-exported-helper-is-binary",
        ext=".ts",
    ),
    Case(
        "S-N10-foreign-token-property",
        "export function size(shirt: Readonly<{ size: string }>): string {\n"
        "  return shirt.size === 'L' ? 'large' : 'small'\n"
        "}\n",
        0,
        why="'L' is a volume token and `size` is not a quantity. Without the "
        "property name in the rule, every shirt is a fuel record.",
        pinned_by="M54-token-branch-any-property",
        ext=".ts",
    ),
    Case(
        "S-N11-wrong-quantity-vocabulary",
        "export function isKg(record: Readonly<{ pressure: string }>): boolean {\n"
        "  return record.pressure === 'kg'\n"
        "}\n",
        0,
        why="`pressure` IS a quantity and 'kg' IS a token, but not of that "
        "quantity. Pooling the ten vocabularies into one loses the pairing.",
        pinned_by="M55-token-vocabulary-is-pooled",
        ext=".ts",
    ),
    Case(
        "S-N12-secondary-gallon",
        "import type { UnitSet } from '@/types/units'\n"
        "export function showsPanel(units: UnitSet): boolean {\n"
        "  return units.secondary_gallon === 'uk'\n"
        "}\n",
        0,
        why="★ R1's exemption, made STRUCTURAL rather than a prose pragma: the "
        "gallon flavour is a choice BETWEEN units with no quantity to convert, "
        "and UNIT_QUANTITIES excludes it behind a compile-time completeness proof",
        pinned_by="M56-secondary-gallon-is-a-quantity",
        ext=".ts",
    ),
    # ---- phase 3b: the R6 carry, five of the six unexercised helper branches -
    Case(
        "S-N13-doubly-parenthesised-foreign",
        "type Theme = ('light') | ('imperial')\n"
        "export function themeClass(theme: Theme): string {\n"
        "  return theme === 'imperial' ? 'a' : 'b'\n"
        "}\n",
        0,
        why="R6 carry, branch 2 of 6: stripOuterParens' balance check. Without "
        "it the outer parens are stripped across the union, both halves become "
        "unreadable, and fail-closed UNKNOWN flags correct code.",
        pinned_by="M57-drop-paren-balance-check",
        ext=".ts",
    ),
    Case(
        "S-N14-void-and-never-members",
        "type Theme = 'light' | 'dark' | void | never\n"
        "export function themeClass(theme: Theme): string {\n"
        "  return theme === 'imperial' ? 'a' : 'b'\n"
        "}\n",
        0,
        why="R6 carry, branch 3 of 6: only `null` and `undefined` were ever "
        "exercised. Dropped from NULLISH_MEMBERS, `void` reads as a bare "
        "identifier, resolves to nothing, and takes the whole union to UNKNOWN.",
        pinned_by="M58-drop-void-never-nullish",
        ext=".ts",
    ),
    Case(
        "S-N15-numeric-and-boolean-members",
        "type Flag = 'imperial' | 0 | true\n"
        "export function on(flag: Flag): boolean {\n"
        "  return flag === 'imperial'\n"
        "}\n",
        0,
        why="R6 carry, branch 4 of 6: STRING_LITERAL_TYPE's numeric and boolean "
        "alternatives. The gate docstring already states this rounding (a "
        "recognised literal no unit system contains means a different enum); "
        "nothing exercised it.",
        pinned_by="M59-drop-numeric-boolean-literals",
        ext=".ts",
    ),
    Case(
        "S-N16-all-nullish-annotation",
        "export function label(s: null | undefined): string {\n"
        "  return s === 'imperial' ? 'mi' : 'km'\n"
        "}\n",
        0,
        why="R6 carry, branch 5 of 6: the all-nullish return. A degenerate "
        "annotation rather than production code, kept because the branch is "
        "otherwise unexercised and returning UNKNOWN instead would flag it.",
        pinned_by="M60-all-nullish-is-unknown",
        ext=".ts",
    ),
    # ---- task 8: the two boundaries the widened predicate must NOT cross ----
    Case(
        "S-N17-exempt-binary-declaration",
        "import type { UnitSystem } from '@/utils/units'\n"
        + HOOK_IMPORT
        + "// units-exempt: the ruling lives at the declaration, not on each call site.\n"
        "export function toCanonicalPerches(value: number, s: UnitSystem): number {\n"
        "  return convert(value, s)\n"
        "}\n"
        "export function submit(entered: number): number {\n"
        "  const { system } = useUnitPreference()\n"
        "  return toCanonicalPerches(entered, system)\n"
        "}\n",
        0,
        why="★ task 8's declaration-level hatch, and the ONLY pragma in this "
        "gate that silences findings in OTHER files. It exists because making "
        "the vocabulary tree-wide turned `supplyUnits.ts`'s three exported "
        "binary helpers into fifteen findings under eleven keys across five files, all "
        "of them one deferred ruling (R3). Character-identical to S-P32 apart "
        "from the pragma line, so the case measures the hatch and nothing else.",
        pinned_by="M70-declaration-exemption-ignored / M10b-drop-line-above-pragma",
        ext=".ts",
    ),
    Case(
        "S-N21-binary-helper-binding-sites",
        "import type { UnitSystem } from '@/utils/units'\n"
        "export function toCanonicalSpans(value: number, s: UnitSystem): number {\n"
        "  return convert(value, s)\n"
        "}\n"
        "export { toCanonicalSpans as toCanonicalSpansAlias }\n"
        "export const REGISTRY = { toCanonicalSpans: 1 }\n",
        0,
        why="the far side of S-P44. A value-reference leg that cannot tell a USE "
        "from a BINDING reports the declaration, its own re-export and any object "
        "key that happens to share the spelling, which is three findings on a "
        "module that calls nothing. The leg is fail-CLOSED on shape and would "
        "otherwise be the noisiest thing in the gate, and a noisy gate is the one "
        "people learn to route around.",
        pinned_by="M76-binding-specifiers-are-uses / M77-declaration-names-are-uses",
        ext=".ts",
    ),
    Case(
        "S-N22-pragma-mentioned-in-a-docstring",
        "import type { UnitSet } from '@/types/units'\n"
        "export function label(units: UnitSet, km: number): string {\n"
        # ★ The mention has to sit on a line the hatch actually READS, which is
        # the finding's own line or the one above it. The first spelling of this
        # case put it three lines up inside a leading docstring, where it could
        # never have mattered, and M82 flipped nothing: an assertion true at
        # t=0, in the case whose whole subject is a guard that fires when it
        # should not.
        "  /* the sibling one file over carries a\n"
        "   * // units-exempt(token-branch): reason */\n"
        "  return units.volume === 'L' ? `${km} km` : `${km} mi`\n"
        "}\n",
        1,
        "token-branch",
        "★ the hatch reads a LINE, and `EXEMPT_PRAGMA` allows any whitespace "
        "before the `//`, so a docstring continuation describing the pragma "
        "exempted whatever followed it. `utils/units.ts` has two such lines and "
        "they were inert only because a backtick happens to precede the `//` in "
        "both, which is luck rather than a rule. Prose about a guard must not be "
        "the guard.",
        "M82-docstring-mention-is-a-pragma",
        ext=".ts",
    ),
    Case(
        "S-N19-scoped-pragma-own-kind",
        "import type { UnitSet } from '@/types/units'\n"
        "export function label(units: UnitSet, liters: number): string {\n"
        "  // units-exempt(token-branch): volume dispatch inside a volume formatter.\n"
        "  return units.volume === 'L' ? `${liters} L` : `${liters} gal`\n"
        "}\n",
        0,
        why="the other side of S-P42: a scoped pragma has to silence the kind it "
        "names, or the form is decoration. Five of the sixteen line-suppressed "
        "findings under `src/` are this exact shape, resolved-set dispatch inside "
        "the unit layer. ★ THE CONSEQUENT USED TO SAY \"nine findings\", derived "
        "from the wrong count beside it and left behind when that count was "
        "corrected, which is the A3 defect reproduced inside the A3 fix. MEASURED "
        "by applying M73 to the real gate: 45 findings under 32 keys across 11 "
        "files, because EVERY pragma under `src/` that suppresses anything carries "
        "the bracket. 27 bracketed lines, of which 15 are line pragmas covering 16 "
        "findings and 12 are declaration pragmas hiding 29 more; the only two bare "
        "ones are inert prose in `units.ts`.",
        pinned_by="M73-scoped-pragma-not-recognised",
        ext=".ts",
    ),
    Case(
        "S-N20-placeholder-token-branch",
        "import type { UnitSet } from '@/types/units'\n"
        "export function OdometerField(props: Readonly<{ units: UnitSet }>): JSX.Element {\n"
        "  return <input placeholder={props.units.distance === 'mi' ? '45000' : '72420'} />\n"
        "}\n",
        0,
        why="★ ruling R5 on the OTHER leg, which is where it was missing. S-N1 "
        "pins the same exemption for `system === 'imperial'`; this is the "
        "spelling `FuelRecordForm.tsx:1029` actually uses, and it sat in the "
        "units gate baseline as phase 3b migration work for the whole phase "
        "because only the comparison leg asked whether it was a placeholder. A "
        "placeholder is a plausible EXAMPLE with nothing canonical behind it.",
        pinned_by="M74-placeholder-token-branch-flagged / M7-drop-placeholder-exemption",
    ),
    Case(
        "S-N18-binary-inside-a-generic-argument",
        "import type { UnitSystem } from '@/utils/units'\n"
        + HOOK_IMPORT
        + "export function tally(value: number, seen: Record<string, UnitSystem>): number {\n"
        "  return value + Object.keys(seen).length\n"
        "}\n"
        "export function submit(entered: number): number {\n"
        "  const { system } = useUnitPreference()\n"
        "  return tally(entered, { a: system })\n"
        "}\n",
        0,
        why="★ the residual the widened predicate DECLARES rather than hides: a "
        "type ARGUMENT is a container of the binary type, not a parameter that "
        "decides on one, so a map of systems is not a binary API. Recursing "
        "into type arguments would flag this, which is why the boundary is "
        "pinned from the far side instead of being left to prose.",
        pinned_by="M71-recurse-into-type-arguments / M53-every-exported-helper-is-binary",
        ext=".ts",
    ),
]

# --------------------------------------------------------------------------
# ESLint leg: provenance-free conversion constants
# --------------------------------------------------------------------------
ESLINT_POSITIVE = [
    Case(
        "E-P1-metres-per-mile",
        "export const RADIUS_M = 1609.34\n",
        1,
        "Raw unit-conversion constant",
        "the three copies phase 3a deleted; the named low-precision list",
        "M12-drop-named-list",
    ),
    Case(
        "E-P2-litres-per-gallon",
        "export const LITERS_PER_GALLON = 3.78541\n",
        1,
        "High-precision numeric literal",
        "defect L1's constant",
        "M21-narrow-precision-threshold",
    ),
    Case(
        "E-P3-mm-per-inch",
        "export const MM_PER_IN = 25.4\n",
        1,
        "Raw unit-conversion constant",
        "the factor the frontend did not have until the adapter supplied it",
        "M12-drop-named-list",
    ),
    Case(
        "E-P4-mpg-to-l100km",
        "export const US_MPG_TO_L100KM = 235.214\n",
        1,
        "Raw unit-conversion constant",
        "three fractional digits, so only the named list can see it",
        "M12-drop-named-list",
    ),
    Case(
        "E-P5-bar-to-psi",
        "export const barToPsi = 14.5038\n",
        1,
        "High-precision numeric literal",
        "R7: the fourth telemetry factor nobody had listed",
        "M21-narrow-precision-threshold",
    ),
    Case(
        "E-P6-unlisted-factor",
        "export const SOME_NEW_FACTOR = 1.234567\n",
        1,
        "High-precision numeric literal",
        "★ the anti-floor case: a factor no ruling, spec or enumerator named",
        "M21-narrow-precision-threshold",
    ),
    Case(
        "E-P7-c-to-f-ninths",
        "export const toF = (c: number): number => (c * 9) / 5 + 32\n",
        1,
        "Inline Celsius-to-Fahrenheit",
        "R7: the idiom appeared in four files and holds no matchable constant",
        "M14-drop-cf-idiom",
    ),
    Case(
        "E-P9-uk-mpg-factor",
        "export const UK_MPG_TO_L100KM = 282.481\n",
        1,
        "Raw unit-conversion constant",
        "the one named factor round 1's corpus never exercised",
        "M33-drop-uk-mpg-from-named-list",
    ),
    Case(
        "E-P10-i18n-guard-survives-scoping",
        "export const price = (amount: number): string => `$${amount}`\n",
        1,
        "Avoid raw $",
        "the migrated block REPLACES the rule's options, so it must spread the "
        "i18n guards back in; without a case here that regression is silent",
        "M34-drop-i18n-spread",
    ),
    Case(
        "E-P8-c-to-f-decimal",
        "export const toF2 = (c: number): number => c * 1.8 + 32\n",
        1,
        "Inline Celsius-to-Fahrenheit",
        "the same conversion spelled with 1.8, which is too generic to list",
        "M14-drop-cf-idiom",
    ),
]

ESLINT_NEGATIVE = [
    Case(
        "E-N1-propane-density",
        "// Propane density: 1 kg is about 1.968 L. Physical, not a unit system.\n"
        "export const KG_TO_LITERS = 1.968\n",
        0,
        why="R5: a physical density, unit-system independent, and CORRECT",
        pinned_by="M13-widen-precision-threshold",
    ),
    Case(
        "E-N2-string-that-looks-like-a-factor",
        "export const PLACEHOLDER = '3.78541'\n",
        0,
        why="the rule reads a numeric literal's raw text, not any string's value",
        pinned_by="M15-match-value-not-raw",
    ),
    Case(
        "E-N3-ordinary-ui-numbers",
        "export const OPACITY = 0.5\n"
        "export const DEBOUNCE_MS = 250\n"
        "export const LINE_HEIGHT = 1.5\n"
        "export const MAX_DECIMAL = 9999.999\n",
        0,
        why="a noisy gate is a gate people turn off",
        pinned_by="M13-widen-precision-threshold",
    ),
    Case(
        "E-N4-positive-control",
        "import { useUnitFormat } from '@/hooks/useUnitFormat'\n"
        "export function RadiusLabel(props: Readonly<{ km: number }>): JSX.Element {\n"
        "  const u = useUnitFormat()\n"
        "  const rounded = Math.round(props.km * 10) / 10\n"
        "  return <span>{u.distance.toDisplayText(rounded)}</span>\n"
        "}\n",
        0,
        why="T4-R7 positive control: correctly migrated code must be silently clean",
        pinned_by="M16-flag-every-number",
        tags=["control"],
    ),
]


# --------------------------------------------------------------------------
# runners
# --------------------------------------------------------------------------
def _refusal(err: str) -> str:
    """Canonicalise ANY refusal to its substantive, path-free message.

    The raw stderr carries the gate's own path and a stack trace, so pointing
    the runner at a mutated COPY changed this string for every mutation and made
    S-P13 look as though it flipped 26 times over.

    ★ Round 2 canonicalised only the PARSE-ERROR refusal and left a raw
    `stderr[-200:]` fallback. That fallback was unreachable at the time and
    became reachable the moment `M42` was written: the one mutation that pins
    the missing-parseDiagnostics guard makes every scan refuse with a DIFFERENT
    message, so S-P13 counted as flipped while its behaviour was identical. A
    canonicaliser with a path-bearing fallback is the bug it was written to fix,
    holding its breath. Every message the gate can throw is matched here, and
    anything unmatched has its paths and stack frames removed rather than being
    passed through.
    """
    for rx in (
        r"parsed as (?:TS|TSX) with \d+ parse error\(s\)[^\n]*",
        r"this TypeScript build exposes no parseDiagnostics[^\n]*",
        r"typescript did not expose createSourceFile[^\n]*",
    ):
        m = re.search(rx, err)
        if m:
            return f"refused: {m.group(0)}"
    cleaned = [
        re.sub(r"(?:/[\w.@+-]+)+", "<path>", line).strip()
        for line in err.splitlines()
        if line.strip() and not re.match(r"\s*at\s", line)
    ]
    return f"refused: {' | '.join(cleaned)[-200:] if cleaned else 'no message'}"


def run_script_leg(case: Case, tmpdir: Path, gate: str = GATE) -> tuple[int, list[str]]:
    """Scan one fixture with validate-units.ts and return (count, detail).

    A count of -1 means the gate REFUSED, which for S-P13 is the correct answer
    rather than an error: a file the parser rejects must not read as a clean one.
    """
    path = tmpdir / f"{case.cid}{case.ext}"
    path.write_text(case.body)
    p = subprocess.run(
        ["bun", "run", gate, "--scan", str(path)],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
    )
    if p.returncode != 0:
        return -1, [_refusal(p.stderr or p.stdout)]
    try:
        payload = json.loads(p.stdout)
    except json.JSONDecodeError:
        return -1, [f"gate emitted non-JSON: {p.stdout.strip()[:200]}"]
    findings = payload["findings"]
    return len(findings), [f"{f['kind']} {f['text']}" for f in findings]


def run_eslint_leg(case: Case, config: str | None = None) -> tuple[int, list[str]]:
    """Lint one fixture at the corpus path and return (count, messages)."""
    ESLINT_FIXTURE.write_text(case.body)
    argv = ["bunx", "eslint", "--format", "json"]
    if config is not None:
        argv += ["--config", config]
    p = subprocess.run(
        [*argv, str(ESLINT_FIXTURE)],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(p.stdout)
    except json.JSONDecodeError:
        return -1, [f"eslint emitted non-JSON: {(p.stdout or p.stderr).strip()[:300]}"]
    msgs = [
        m["message"]
        for f in payload
        for m in f["messages"]
        if m.get("ruleId") == "no-restricted-syntax"
    ]
    return len(msgs), msgs


def check(case: Case, got: int, detail: list[str]) -> str | None:
    """Return a failure description, or None when the case behaved."""
    if got != case.expect:
        return (
            f"expected {case.expect} finding(s), got {got}: {[d[:160] for d in detail]}"
        )
    if case.expect != 0 and case.expect_kind:
        wrong = [d for d in detail if case.expect_kind not in d]
        if wrong:
            return (
                f"*** WRONG RULE FIRED *** expected {case.expect_kind!r}, "
                f"got {[d[:160] for d in wrong]}"
            )
    if case.expect_text:
        texts = [d.split(" ", 1)[1] if " " in d else d for d in detail]
        if texts != [case.expect_text]:
            return f"*** WRONG TEXT *** expected {[case.expect_text]}, got {texts}"
    return None


def main() -> int:
    refusal = acquire_lock("units_gate_corpus.py", [ESLINT_FIXTURE])
    if refusal:
        print(refusal)
        return 2
    failures: list[str] = []
    tmpdir = Path(tempfile.mkdtemp(prefix="units-corpus-"))
    try:
        for title, cases, runner in (
            ("script leg  POSITIVE (must be REJECTED)", SCRIPT_POSITIVE, "script"),
            ("script leg  NEGATIVE (must be ACCEPTED)", SCRIPT_NEGATIVE, "script"),
            ("ESLint leg  POSITIVE (must be REJECTED)", ESLINT_POSITIVE, "eslint"),
            ("ESLint leg  NEGATIVE (must be ACCEPTED)", ESLINT_NEGATIVE, "eslint"),
        ):
            print(f"\n{title}")
            print("-" * 78)
            for case in cases:
                if runner == "script":
                    got, detail = run_script_leg(case, tmpdir)
                else:
                    got, detail = run_eslint_leg(case)
                bad = check(case, got, detail)
                mark = "FAIL" if bad else ("rejected" if case.expect else "accepted")
                print(f"  {case.cid:<34} {mark:<9} {bad or case.why}")
                if bad:
                    failures.append(f"{case.cid}: {bad}")
    finally:
        ESLINT_FIXTURE.unlink(missing_ok=True)
        for leftover in tmpdir.glob("*"):
            leftover.unlink()
        tmpdir.rmdir()
        release_lock()

    total = (
        len(SCRIPT_POSITIVE)
        + len(SCRIPT_NEGATIVE)
        + len(ESLINT_POSITIVE)
        + len(ESLINT_NEGATIVE)
    )
    print()
    if failures:
        print(f"CORPUS: {len(failures)} of {total} case(s) FAILED")
        for f in failures:
            print("  " + f)
        return 1
    print(f"CORPUS: all {total} cases behaved (positives rejected, negatives accepted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
