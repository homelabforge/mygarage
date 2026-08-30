#!/usr/bin/env python3
"""Mutation-test the unit gate against its own corpus, plus a positive control.

★ The rule this file exists for: any artifact asserting completeness must
itself be mutation-tested against what it claims to cover. `units_gate_corpus.py`
is such an artifact, and a corpus case that passes identically whether or not
the rule exists is an assertion true at t=0, one level up. Task 3's corpus had
exactly that defect: its negative case declared a const and never called `t()`,
so the anchor it existed to justify was pinned by nothing.

So every case in the corpus names a mutation here, and this file proves that the
mutation FLIPS THAT CASE AND ONLY THAT CASE. A run that reports "some case
failed" would report success forever if a different case broke, which is why the
comparison is by case id and the failure reads *** WRONG CASES FLIPPED ***.

★ ROUND 2, and the finding that shaped it: a reviewer's independent matrix
found EIGHT surviving mutants, none of which the corpus, this selftest, the real
gate or `bun run lint` could kill. The structural cause is worth stating rather
than patching around:

    BASELINE MODE CAN ONLY KILL TIGHTENING MUTATIONS.

The gate fails when an occurrence count RISES and never when one falls, so every
loosening reads as migration progress. The corpus is therefore the sole
executioner for the entire loosening direction, which is where all eight
survivors sat. The mutation table below is now weighted accordingly.

Three more things it proves, each demanded by a ruling:

  T4-R6  the ESLint leg's `files:` scope is real, and every path in it names a
         file that exists (a typo silently un-scopes a file and ESLint never
         warns about a `files:` entry that matches nothing).
  R4     the baseline is keyed by occurrence COUNT and not set membership.
  T4-R7  a guard that fires unconditionally is as worthless as one that never
         fires, and looks healthier. Both legs carry a positive control.

★ NOTHING HERE MUTATES A COMMITTED FILE. Round 1 patched `validate-units.ts` and
`eslint.config.js` in place, so a run that died mid-way left the repo modified,
and that was the real reason neither script could be wired into CI. Every
mutation is applied to a `*.mutant.generated.*` COPY which the tools are pointed
at explicitly, and `eslint.config.js` ignores that suffix so even a leaked copy
is inert. The fixtures likewise live outside `src/`, where a leak used to fail
`validate-reachability.ts`.

★ And the mutants prove themselves valid before they are scored: a mutation that
broke the gate outright would flip every case at once and could masquerade as a
successful wide mutation. Each one must still run cleanly on a control input
first, the same check `mutation_harness.py` learned to make after round 1 scored
a syntax-broken mutant as a clean survivor.

The reference results are DERIVED by running the corpus once, never passed in.

Usage::

    python3 frontend/scripts/units_gate_selftest.py

Exit code: 1 if any mutation fails to flip exactly the cases that name it.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "units_corpus", Path(__file__).parent / "units_gate_corpus.py"
)
C = importlib.util.module_from_spec(spec)
# Registered before execution because @dataclass resolves annotations through
# sys.modules, and a module loaded by path alone is not there yet.
sys.modules["units_corpus"] = C
spec.loader.exec_module(C)

FRONTEND = C.FRONTEND
GATE_SRC = FRONTEND / "scripts/validate-units.ts"
ESLINT_CFG = FRONTEND / "eslint.config.js"

# Mutated copies. Never the originals. The `.mutant.generated.` infix is what
# eslint.config.js ignores, and it must not be widened to `.generated.` because
# src/types/api.generated.ts is linted.
GATE_MUTANT = FRONTEND / "scripts/units-gate.mutant.generated.ts"
CFG_MUTANT = FRONTEND / "eslint.mutant.generated.js"

# Fixtures this file owns outright, all outside src/.
SCOPE_FIXTURE = FRONTEND / "scripts/__units_scope_probe__.tsx"

# A control input for the mutant-validity check: no numbers, no comparisons, so
# it stays clean under every mutation including the deliberately over-firing
# ones. Anything other than "runs and reports nothing" means the mutant is
# broken rather than merely wrong.
VALIDITY_PROBE = "export const OK = 'ok'\n"


@dataclass
class Mutation:
    """One deliberate defect in a COPY of the gate, and the cases it must flip.

    `also` carries further simultaneous edits, because some guards are defended
    twice and removing either one alone flips nothing. Round 2 hit that with `UnitSystem` (the name list
    and the fail-closed identifier rule) and round 3 hits it again with
    parenthesised aliases (paren stripping and the fail-closed UNKNOWN class).
    A mutation that flips nothing is a survivor wearing a mutation's name, so
    the honest fix is a mutation that removes every defence at once.
    """

    mid: str
    target: str  # 'gate' or 'config'
    old: str
    new: str
    leg: str
    flips: list[str] = field(default_factory=list)
    why: str = ""
    #: further simultaneous edits, for a guard that is defended more than once.
    also: list[tuple[str, str]] = field(default_factory=list)
    #: what the validity probe must see. 'clean' is the default: the mutant runs
    #: and reports nothing on an input with nothing in it. 'refuses:<substring>'
    #: is for a mutation whose whole point is that the gate now refuses
    #: everything, where a clean probe would read as a broken mutant. The
    #: substring is REQUIRED and names the refusal expected: an earlier version
    #: matched any nonzero exit carrying the one hardcoded message, so a second
    #: refusing mutation would have been scored against the first one's text.
    expect_probe: str = "clean"


MUTATIONS = [
    # ---------------- script leg: what the detector must catch ----------------
    Mutation(
        "M17-drop-imperial-literal",
        "gate",
        "const SYSTEM_LITERALS = new Set(['imperial', 'metric'])",
        "const SYSTEM_LITERALS = new Set(['metric'])",
        "script",
        [
            "S-P1-eq-imperial",
            "S-P3-yoda",
            "S-P4-neq",
            "S-P5-switch",
            "S-P6-aliased-boolean",
            "S-P7-destructuring-rename",
            "S-P8-resolvedSystem",
            "S-P10-member-expression",
            "S-P11-annotated-unitsystem",
            "S-P12-ts-angle-assertion",
            "S-P14-alias-union",
            "S-P15-imported-alias",
            "S-P16-widened-alias",
            "S-P17-loose-equality",
            "S-P18-template-literal",
            "S-P19-shadowed-name",
            "S-P20-multiline",
            "S-P21-non-placeholder-attribute",
            "S-P22-bare-pragma",
            "S-P23-string-union",
            "S-P24-unitsystem-union",
            "S-P25-nullable-unit-union",
            "S-P26-parenthesised-alias",
            "S-P27-indexed-access",
            "S-P28-alias-or-undefined",
            "S-P36-double-quoted-union",
            "S-P29-backtick-vocabulary",
        ],
        "half the vocabulary is half the gate",
    ),
    Mutation(
        "M20-drop-metric-literal",
        "gate",
        "const SYSTEM_LITERALS = new Set(['imperial', 'metric'])",
        "const SYSTEM_LITERALS = new Set(['imperial'])",
        "script",
        ["S-P2-eq-metric", "S-P5-switch", "S-P9-displaySystem"],
        "R2: v1 prohibited only the imperial half and production uses both",
    ),
    Mutation(
        "M1-drop-yoda",
        "gate",
        "        const leftIsLiteral = isSystemLiteral(node.left)",
        "        const leftIsLiteral = false",
        "script",
        ["S-P3-yoda"],
        "a literal-on-the-left comparison is the same decision",
    ),
    Mutation(
        "M2-drop-neq",
        "gate",
        "  ts.SyntaxKind.ExclamationEqualsEqualsToken,\n  ts.SyntaxKind.EqualsEqualsToken,",
        "  ts.SyntaxKind.EqualsEqualsToken,",
        "script",
        ["S-P4-neq"],
        "negation is not an escape hatch",
    ),
    Mutation(
        "M27-drop-loose-equality",
        "gate",
        "  ts.SyntaxKind.EqualsEqualsToken,\n  ts.SyntaxKind.ExclamationEqualsToken,\n",
        "",
        "script",
        ["S-P17-loose-equality"],
        "nothing in this repo forbids `==`, so the gate cannot assume `===`",
    ),
    Mutation(
        "M28-drop-template-literal-kind",
        "gate",
        "  ts.SyntaxKind.NoSubstitutionTemplateLiteral,\n",
        "",
        "script",
        ["S-P18-template-literal"],
        "a backtick literal is the same comparison with different punctuation",
    ),
    Mutation(
        "M3-drop-switch",
        "gate",
        "    if (node.kind === ts.SyntaxKind.CaseClause && isSystemLiteral(node.expression)) {",
        "    if (false && node.kind === ts.SyntaxKind.CaseClause) {",
        "script",
        ["S-P5-switch"],
        "a switch is a branch wearing different punctuation",
    ),
    Mutation(
        "M18-skip-variable-initialisers",
        "gate",
        "    ts.forEachChild(node, walk)\n  }\n\n  walk(sf)",
        "    if (node.kind === ts.SyntaxKind.VariableDeclaration) return\n"
        "    ts.forEachChild(node, walk)\n  }\n\n  walk(sf)",
        "script",
        ["S-P6-aliased-boolean"],
        "a walker that stops short of initialisers misses the aliased boolean. "
        "Predicted S-P14 and S-P16 too and that was wrong: their comparison is in "
        "a return, and only the declaration they read from is an initialiser.",
    ),
    Mutation(
        "M19-key-on-identifier-name",
        "gate",
        "          if (!hasForeignProvenance(operand, index)) {",
        "          if (operand.text === 'system') {",
        "script",
        [
            "S-P7-destructuring-rename",
            "S-P8-resolvedSystem",
            "S-P9-displaySystem",
            "S-P10-member-expression",
            "S-P14-alias-union",
            "S-P15-imported-alias",
            "S-P16-widened-alias",
            "S-P19-shadowed-name",
            "S-P23-string-union",
            "S-P24-unitsystem-union",
            "S-P25-nullable-unit-union",
            "S-P26-parenthesised-alias",
            "S-P27-indexed-access",
            "S-P28-alias-or-undefined",
            "S-P36-double-quoted-union",
            "S-P29-backtick-vocabulary",
        ],
        "★ R2's forbidden implementation: it passes every case that spells the "
        "variable `system` and misses both spellings production actually uses",
    ),
    Mutation(
        "M4-unresolved-is-exempt",
        "gate",
        "  if (operand.kind !== ts.SyntaxKind.Identifier) return false",
        "  if (operand.kind !== ts.SyntaxKind.Identifier) return true",
        "script",
        ["S-P10-member-expression"],
        "fail-open on an unresolvable operand is how a gate becomes a floor",
    ),
    Mutation(
        "M24-drop-alias-expansion",
        "gate",
        "    if (body === undefined || depth >= 8) return 'unknown'\n"
        "    return classifyAnnotation(body, aliases, depth + 1)",
        "    if (body === undefined || depth >= 8) return 'unknown'\n    return 'foreign'",
        "script",
        [
            "S-P14-alias-union",
            "S-P16-widened-alias",
            "S-P26-parenthesised-alias",
            "S-P28-alias-or-undefined",
            "S-P36-double-quoted-union",
            "S-P29-backtick-vocabulary",
        ],
        "★ R8's hole: a name denylist walks straight past `type Sys = 'imperial'|'metric'`",
    ),
    Mutation(
        "M41a-unresolvable-name-is-foreign",
        "gate",
        "    if (body === undefined || depth >= 8) return 'unknown'",
        "    if (body === undefined || depth >= 8) return 'foreign'",
        "script",
        [
            "S-P9-displaySystem",
            "S-P11-annotated-unitsystem",
            "S-P12-ts-angle-assertion",
            "S-P15-imported-alias",
            "S-P23-string-union",
            "S-P24-unitsystem-union",
        ],
        "an imported alias the gate cannot read is not evidence of innocence, and "
        "since round 3 deleted the redundant NAME denylist this one rule is also "
        "what keeps `string`, `any`, `unknown` and `UnitSystem` non-exempt",
    ),
    Mutation(
        "M26-drop-custom-from-vocabulary",
        "gate",
        # Anchored to the whole line, not to a fragment of a single-line set
        # literal: round 4 reformatted UNIT_VOCABULARY across several lines and
        # the old fragment anchor stopped matching. The PATTERN guard caught it
        # as "occurs 0 times", which is the guard doing its job on my own edit.
        "  \"'custom'\",\n",
        "",
        "script",
        ["S-P16-widened-alias"],
        "phase 1 widened the union to admit 'custom' and it is still a unit system",
    ),
    Mutation(
        "M29-any-declaration-exempts",
        "gate",
        "  return annotations.every((a) => a !== null && isForeignAnnotation(a, index.aliases))",
        "  return annotations.some((a) => a !== null && isForeignAnnotation(a, index.aliases))",
        "script",
        ["S-P19-shadowed-name"],
        "the flat index is deliberate: one foreign declaration must not silence a "
        "bare one sharing the name",
    ),
    Mutation(
        "M30-drop-normalize",
        "gate",
        "  return text.replace(/\\s+/g, ' ').trim()",
        "  return text",
        "script",
        ["S-P20-multiline"],
        "a wrapped comparison must key the same as a flat one or the baseline splits",
    ),
    Mutation(
        "M22-hardcode-tsx-scriptkind",
        "gate",
        "  const kind = rel.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS",
        "  const kind = ts.ScriptKind.TSX",
        "script",
        ["S-P12-ts-angle-assertion"],
        "★ round 1's CRITICAL: `<string>raw` is legal TS and illegal TSX, so the "
        "parser dropped the subtree and the whole file went silent",
    ),
    Mutation(
        "M23-ignore-parse-diagnostics",
        "gate",
        "  if (diagnostics.length > 0) {",
        "  if (false) {",
        "script",
        ["S-P13-unparseable"],
        "★ the other half of round 1's CRITICAL: a wrecked parse reported as a clean file",
    ),
    Mutation(
        "M43-drop-backtick-vocabulary",
        "gate",
        "  '`imperial`',\n  '`metric`',\n  '`custom`',\n",
        "",
        "script",
        ["S-P29-backtick-vocabulary"],
        "★ the round-3 FAIL-OPEN: STRING_LITERAL_TYPE recognises a backtick "
        "literal, so a missing vocabulary entry did not fall through to "
        "fail-closed unknown, it was confidently classified foreign and exempted "
        "the whole union. A gate with a known fail-open is not a gate.",
    ),
    Mutation(
        "M39-nullish-member-is-foreign",
        "gate",
        "  if (NULLISH_MEMBERS.has(m)) return 'nullish'",
        "  if (NULLISH_MEMBERS.has(m)) return 'foreign'",
        "script",
        ["S-P25-nullable-unit-union", "S-P28-alias-or-undefined"],
        "★ round 2's F2 REGRESSION, reintroduced on purpose: treat `null` as an "
        "ordinary foreign member and `'imperial' | 'metric' | null` becomes exempt, "
        "which is exactly the shape round 1 caught and round 2 lost",
    ),
    Mutation(
        "M41b-unreadable-type-is-foreign",
        "gate",
        "    return classifyAnnotation(body, aliases, depth + 1)\n  }\n  return 'unknown'\n}",
        "    return classifyAnnotation(body, aliases, depth + 1)\n  }\n  return 'foreign'\n}",
        "script",
        ["S-P27-indexed-access"],
        "a type expression the gate cannot parse must not be read as innocence",
    ),
    Mutation(
        "M40b-parens-unread-then-exempt",
        "gate",
        "    return classifyAnnotation(body, aliases, depth + 1)\n  }\n  return 'unknown'\n}",
        "    return classifyAnnotation(body, aliases, depth + 1)\n  }\n  return 'foreign'\n}",
        "script",
        ["S-P26-parenthesised-alias", "S-P27-indexed-access"],
        "a parenthesised unit alias is defended twice, by paren stripping and by "
        "the fail-closed UNKNOWN class, so only removing BOTH flips it",
        also=[
            (
                "  while (out.startsWith('(') && out.endsWith(')')) {",
                "  while (false) {",
            )
        ],
    ),
    Mutation(
        "M42-no-parse-diagnostics-property",
        "gate",
        "  const diagnostics = sf.parseDiagnostics",
        "  const diagnostics = undefined",
        "script",
        [],  # filled in below: every script case
        "★ F1's other half, unpinned until now. `parseDiagnostics` is internal to "
        "the compiler and absent from its public typings, so a build that stopped "
        "exposing it would silently restore the blindness. The guard turns that "
        "into a refusal on every file, which is why this mutation needs the "
        "'refuses' probe: a clean probe would read a deliberate refusal as a "
        "broken mutant.",
        expect_probe="refuses:parseDiagnostics",
    ),
    # ---------------- script leg: the three phase-3b detectors ---------------
    Mutation(
        "M44-drop-formatter-leg",
        "gate",
        "        if (binaryFormattersHere.has(called)) {",
        "        if (false && binaryFormattersHere.has(called)) {",
        "script",
        [
            "S-P30-formatter-binary-call",
            "S-P31-formatter-label-selector",
            "S-P35-aliased-formatter-receiver",
            "S-P37-binary-formatter-on-a-foreign-class",
            "S-P47-instance-method",
        ],
        "the whole formatter leg. 73 production calls carry no system literal, so "
        "without it the comparison leg certifies every one of them as clean.",
    ),
    Mutation(
        "M45-formatter-format-prefix-only",
        "gate",
        "        if (!takesBinarySystem(member, source, ctx)) continue",
        "        if (!member.name.getText(source).startsWith('format')) continue",
        "script",
        [
            "S-N7-formatter-resolved-set",
            "S-P31-formatter-label-selector",
            "S-P35-aliased-formatter-receiver",
        ],
        "★ ROUND 1's ACTUAL MISTAKE, built and run. A `format*` name rule is wrong "
        "in BOTH directions at once: it misses every label selector "
        "(`getFuelEconomyUnit`, `getFuelRateUnit`, `getCostPerDistanceLabel`) and "
        "it flags `formatVolume`, which takes a resolved set and is the "
        "destination. That is why the callable set is derived as 'a parameter is "
        "a UnitSystem'. The examples used to include `getDistanceUnit`; task 6 "
        "retired that one, and an example naming a method the derivation can no "
        "longer find teaches the next reader nothing.",
    ),
    Mutation(
        "M49-formatter-receiver-spelling",
        "gate",
        "      if (callee?.kind === ts.SyntaxKind.PropertyAccessExpression) {",
        "      if (callee?.expression?.getText(sf) === FORMATTER_CLASS) {",
        "script",
        [
            "S-P35-aliased-formatter-receiver",
            "S-P37-binary-formatter-on-a-foreign-class",
            "S-P47-instance-method",
        ],
        "keying on the receiver's spelling makes `import { UnitFormatter as UF }` "
        "a one-line bypass, and since task 7 it also loses a binary formatter "
        "declared on a class with any other name",
    ),
    Mutation(
        "M52-formatter-name-without-receiver",
        "gate",
        "      if (callee?.kind === ts.SyntaxKind.PropertyAccessExpression) {",
        "      if (true) {",
        "script",
        ["S-N8-local-format-distance"],
        "the mirror of M49: dropping the receiver entirely flags a module-local "
        "helper whose NAME collides with a binary formatter. Three such helpers are "
        "spelled `formatDistance` in production and POICard's is correct migrated "
        "code; task 6 retired that method, so S-N8 now collides on a surviving name "
        "instead. See its `why`.",
    ),
    Mutation(
        "M51-every-static-method-is-binary",
        "gate",
        "        if (!takesBinarySystem(member, source, ctx)) continue",
        "        if (false) continue",
        "script",
        ["S-N7-formatter-resolved-set"],
        "T4-R7's mirror on the new leg: a detector that flags every formatter call "
        "looks healthier than one that flags none and is worth exactly as much",
    ),
    Mutation(
        "M46-drop-conversion-leg",
        "gate",
        "      if (binaryHelpersHere.has(called)) {",
        "      if (false && binaryHelpersHere.has(called)) {",
        "script",
        [
            "S-P32-binary-conversion-call",
            "S-P38-aliased-import-annotation",
            "S-P39-union-annotation",
            "S-P40-inline-props-annotation",
            "S-P41-named-props-interface",
            "S-P43-scoped-declaration-wrong-kind",
            "S-P45-module-local-helper",
            "S-P46-exported-arrow-helper",
            "S-P48-renaming-import-alias",
        ],
        "R8's whole point: the function that WRITES the wrong number, invisible to "
        "both of the originally proposed legs. ★ ONE case until task 8 and FIVE "
        "after it, because the four shapes the old predicate could not read are "
        "all this leg: an annotation `takesBinarySystem` cannot see is a helper "
        "whose whole call-site population is invisible, and there is nothing at "
        "those call sites for the other legs to catch instead.",
    ),
    Mutation(
        "M53-every-exported-helper-is-binary",
        "gate",
        "    if (!takesBinarySystem(decl.signature, source, ctx)) continue",
        "    if ((decl.signature.parameters ?? []).length === 0) continue",
        "script",
        [
            "S-N18-binary-inside-a-generic-argument",
            "S-N8-local-format-distance",
            "S-N9-set-conversion-helper",
            "S-P44-binary-helper-as-a-value",
        ],
        "a resolved-set helper sits in the same file as the binary ones did: the "
        "leg cannot key on the module or on a name prefix. The case spelled "
        "`toCanonicalLiters` until task 7 deleted it and now spells "
        "`seedPriceField`, which is what a negative naming a live symbol costs "
        "and is cheaper than a negative that can no longer be made positive. "
        "★ THE ZERO-PARAMETER CARVE-OUT IS DELIBERATE and is task 8's doing. This "
        "used to drop the predicate outright, which was narrow while the "
        "vocabulary came from `decimalSafe.ts` alone; tree-wide it also admits "
        "`useUnitPreference`, which every fixture calls through HOOK_IMPORT, so "
        "the mutation flipped twenty cases for a reason having nothing to do with "
        "the annotation. Requiring one parameter keeps the subject exactly where "
        "it was. ★ S-N18 flips with it, measured rather than reasoned: `tally` "
        "takes a `Record<string, UnitSystem>` and IS called, so any predicate "
        "that stops reading the annotation admits it too. ★ FOUR cases since fix "
        "round 1, and the two that joined say what the widening did: S-N8's "
        "module-local `formatDistance` and S-P44's `apply` are both local "
        "declarations, which the vocabulary could not see at all before and which "
        "a predicate that stops reading the annotation now admits.",
    ),
    Mutation(
        "M47-drop-token-branch-leg",
        "gate",
        "        const quantity = quantityBranchOf(node, sf)",
        "        const quantity = null",
        "script",
        [
            "S-N22-pragma-mentioned-in-a-docstring",
            "S-P33-token-branch-property",
            "S-P34-token-branch-destructured",
            "S-P42-scoped-pragma-wrong-kind",
        ],
        "scope category 4's second half, which carries no system literal at all. "
        "S-P42 joins them because a pragma scoped to a DIFFERENT leg cannot save a "
        "finding the leg no longer makes.",
    ),
    Mutation(
        "M48-token-branch-property-only",
        "gate",
        "      : operand.kind === ts.SyntaxKind.Identifier",
        "      : false",
        "script",
        ["S-P34-token-branch-destructured"],
        "one destructure would otherwise be a complete bypass",
    ),
    Mutation(
        "M54-token-branch-any-property",
        "gate",
        "  return QUANTITY_TOKENS.has(name) ? name : null",
        "  return name === '' ? null : name",
        "script",
        ["S-N10-foreign-token-property", "S-N11-wrong-quantity-vocabulary"],
        "the property name and the per-quantity vocabulary defend this leg "
        "TOGETHER, so only removing both flips anything: with the name gate alone "
        "removed, `size` has no vocabulary and the lookup still misses. Both off, "
        "and every shirt sized 'L' is a fuel record.",
        also=[
            (
                "    if (quantity !== null && QUANTITY_TOKENS.get(quantity)?.has(literal.text)) return quantity",
                "    if (quantity !== null && [...QUANTITY_TOKENS.values()].some((v) => v.has(literal.text)))\n      return quantity",
            )
        ],
    ),
    Mutation(
        "M55-token-vocabulary-is-pooled",
        "gate",
        "    if (quantity !== null && QUANTITY_TOKENS.get(quantity)?.has(literal.text)) return quantity",
        "    if (quantity !== null && [...QUANTITY_TOKENS.values()].some((v) => v.has(literal.text)))\n      return quantity",
        "script",
        ["S-N11-wrong-quantity-vocabulary"],
        "pooling the ten vocabularies loses the pairing, and a `pressure` field "
        "holding 'kg' becomes a unit decision",
    ),
    Mutation(
        "M56-secondary-gallon-is-a-quantity",
        "gate",
        "        if (!quantities.has(quantity)) continue",
        "        if (false) continue",
        "script",
        ["S-N12-secondary-gallon"],
        "★ R1's structural exemption, from the other side. Deriving the quantity "
        "names from `UnitSet`'s keys instead of `UNIT_QUANTITIES` admits "
        "`secondary_gallon`, and the gallon-panel visibility becomes a finding "
        "that no correct code can clear.",
    ),
    # ---------------- script leg: the guard that stops a blind detector ------
    Mutation(
        "M61-empty-formatter-derivation-refuses",
        "gate",
        "      (onlyClass === null || node.name?.text === onlyClass)",
        "      false",
        "script",
        [],  # filled in below: every script case, because the gate refuses them all
        "★ THE loadTypeScript LESSON, one layer in. The callable set is DERIVED "
        "from units.ts, so a rename of the class (or of the UnitSystem type) "
        "empties it, and a detector with an empty vocabulary reports zero "
        "findings on a tree full of them while the gate prints a tick. The "
        "fail-loud guard turns that into a refusal, which is what this mutation "
        "measures. ★ WHAT IT GUARDS MOVED IN TASK 7: the BINARY set is legitimately "
        "empty now that the last two cost-per-distance methods are retired, so an "
        "empty one can no longer be the alarm. The guard reads the walk's own "
        "receipt instead, the STATIC methods `UnitFormatter` does declare, exactly "
        "as `deriveBinaryConversionHelpers` has guarded `exported` since task 5.",
        expect_probe="refuses:derived no static UnitFormatter method",
    ),
    Mutation(
        "M62-empty-derivation-without-the-guard",
        "gate",
        "      (onlyClass === null || node.name?.text === onlyClass)",
        "      false",
        "script",
        [
            "S-P30-formatter-binary-call",
            "S-P31-formatter-label-selector",
            "S-P35-aliased-formatter-receiver",
            "S-P37-binary-formatter-on-a-foreign-class",
            "S-P47-instance-method",
        ],
        "★ and the SURVIVOR the guard prevents, built and run: with "
        "requireNonEmpty gone, the same empty walk is SILENT. Three "
        "positives quietly stop being reported and every other case, including "
        "both positive controls, still passes. That is what a gate that cannot "
        "fire looks like from the outside, and it is why the guard is not "
        "defensive clutter. Since task 7 the walk feeds BOTH the derivation and "
        "the per-file augmentation, so disabling it takes the fixtures' own "
        "declarations with it, which is why these three still flip.",
        also=[
            (
                "  requireNonEmpty(statics, `static ${FORMATTER_CLASS} method`, UNITS_SOURCE)\n",
                "",
            )
        ],
    ),
    Mutation(
        "M66-formatter-augmentation-dropped",
        "gate",
        "    ...formatterMethodsIn(sf, null).binary,\n",
        "",
        "script",
        [
            "S-P30-formatter-binary-call",
            "S-P31-formatter-label-selector",
            "S-P35-aliased-formatter-receiver",
            "S-P37-binary-formatter-on-a-foreign-class",
            "S-P47-instance-method",
        ],
        "★ THE LINE TASK 7 ADDED, mutated on its own rather than through the walk "
        "it shares with the derivation. `UnitFormatter`'s binary surface is empty, "
        "so without the scanned file's own class declarations the formatter leg "
        "has NO vocabulary and cannot fire at all: the three positives score zero "
        "and every negative still passes, which is precisely the shape M62 exists "
        "to make visible one level up. It also measures the same-file blindness "
        "the augmentation closes, where a component declares a static "
        "`format(x, system: UnitSystem)` on a class of its own and calls it.",
    ),
    Mutation(
        "M67-augmentation-only-the-production-class",
        "gate",
        "    ...formatterMethodsIn(sf, null).binary,",
        "    ...formatterMethodsIn(sf, FORMATTER_CLASS).binary,",
        "script",
        [
            "S-P37-binary-formatter-on-a-foreign-class",
            "S-P47-instance-method",
        ],
        "★ THE NARROWING THREE POSITIVES COULD NOT SEE. S-P30, S-P31 and S-P35 "
        "declare a class called `UnitFormatter` on purpose, so restricting the "
        "per-file augmentation to that name leaves all three green while the leg "
        "quietly stops covering a binary formatter declared on any other class. "
        "S-P37 exists for exactly this mutation, and this mutation exists so the "
        "`onlyClass === null` argument is not a guard nothing can kill.",
    ),
    # ---------------- task 8: the precondition's own mutations ----------------
    Mutation(
        "M68-exact-annotation-text-only",
        "gate",
        "  return (node.parameters ?? []).some((p) => typeIsBinarySystem(p.type, source, ctx))",
        "  return (node.parameters ?? []).some((p) => p.type?.getText(source).trim() === BINARY_SYSTEM_TYPE)",
        "script",
        [
            "S-P38-aliased-import-annotation",
            "S-P39-union-annotation",
            "S-P40-inline-props-annotation",
            "S-P41-named-props-interface",
            "S-P49-binary-props-component-render",
        ],
        "★ THE PREDICATE AS TASK 5 LEFT IT, run rather than described. It compares "
        "the annotation's TEXT to one literal, so an `as Sys` import, a "
        "`| undefined`, an inline props object and a named props interface all "
        "walk past it, and with them the ENTIRE call-site population of whatever "
        "they annotate: a helper the vocabulary never learned reports nothing at "
        "any of its call sites and the gate prints a tick. Three of the nineteen "
        "production declarations carrying the type were in these shapes when task "
        "8 started, two of them live components on the supplies path.",
    ),
    Mutation(
        "M69-props-types-unresolved",
        "gate",
        "    const body = ctx.local.get(name)",
        "    const body = undefined as TsNode | undefined",
        "script",
        ["S-P41-named-props-interface"],
        "the narrower survivor M68 hides: handle inline `{ system: UnitSystem }` "
        "and stop there, and the three inline shapes pass while a props type given "
        "a NAME one line up is still invisible. That is the spelling "
        "`SupplyHistoryModal`'s PurchaseRow actually uses, so the case that dies "
        "here is the production one.",
    ),
    Mutation(
        "M70-declaration-exemption-ignored",
        "gate",
        "  return exemptedAtLine(lines, line, kind)",
        "  return false",
        "script",
        ["S-N17-exempt-binary-declaration"],
        "the declaration-level hatch is the ONLY pragma in this gate that silences "
        "findings in other files, so it needs a mutation that can kill it. Without "
        "one it would be a guard nothing could fail, which is the shape this "
        "workstream has ruled a survivor wearing a guard's name.",
    ),
    Mutation(
        "M71-recurse-into-type-arguments",
        "gate",
        "  if (type.kind === ts.SyntaxKind.TypeReference) {\n    const name = referenceName(type, source)",
        "  if (type.kind === ts.SyntaxKind.TypeReference) {\n"
        "    const args = (type as unknown as { typeArguments?: TsNode[] }).typeArguments ?? []\n"
        "    if (args.some((t) => typeIsBinarySystem(t, source, ctx, depth + 1, seen))) return true\n"
        "    const name = referenceName(type, source)",
        "script",
        ["S-N18-binary-inside-a-generic-argument"],
        "the far side of the widened predicate's stated boundary. A type ARGUMENT "
        "holds the binary type rather than deciding on it, so `Record<string, "
        "UnitSystem>` is not a binary API; widening one step further makes it one. "
        "The boundary is pinned from outside rather than left in prose, because a "
        "residual nothing can fail is a residual nobody will notice moving.",
    ),
    # ------------- fix round 1: the floor under the whole leg -----------------
    Mutation(
        "M78-only-exported-declarations",
        "gate",
        "    if (decl.exported) exportedBinary.add(decl.name)\n    else localBinary.add(decl.name)",
        "    if (decl.exported) exportedBinary.add(decl.name)",
        "script",
        [
            "S-P45-module-local-helper",
            "S-P49-binary-props-component-render",
        ],
        "★ THE FLOOR THE FLIP SHIPPED ON, and it held up a completeness claim. "
        "The vocabulary took only EXPORTED declarations, so three module-local "
        "helpers in `SupplyHistoryModal.tsx`, one in `SuppliesUsedTab.tsx` and "
        "one in `ServiceVisitForm.tsx` were invisible to both binary forms, with "
        "ten call sites between them. Two of those are the exact lines task 8's "
        "report celebrated catching through the value-reference leg: the gate "
        "saw the fourth ARGUMENT of `convertSupplyUsages` and not "
        "`convertSupplyUsages`.",
    ),
    Mutation(
        "M79-only-function-declarations",
        "gate",
        "      node.kind === ts.SyntaxKind.VariableDeclaration &&\n"
        "      node.name?.kind === ts.SyntaxKind.Identifier &&",
        "      false &&\n"
        "      node.name?.kind === ts.SyntaxKind.Identifier &&",
        "script",
        ["S-P46-exported-arrow-helper"],
        "the other half of the same floor. An arrow const carries its `export` on "
        "the VariableStatement two levels up and is not a FunctionDeclaration at "
        "all, and 52 of them already exist under `src/`, so this was the spelling "
        "most likely to arrive next.",
    ),
    Mutation(
        "M80-only-static-methods",
        "gate",
        "        if (member.kind !== ts.SyntaxKind.MethodDeclaration) continue",
        "        if (member.kind !== ts.SyntaxKind.MethodDeclaration || !isStatic(member)) continue",
        "script",
        ["S-P47-instance-method"],
        "the formatter leg's half. `this.format(km, system)` is the same "
        "D8-collapsed decision as `C.format(km, system)`, and the leg's receiver "
        "requirement already matched it; only the derivation refused to see it.",
    ),
    Mutation(
        "M81-drop-import-alias-resolution",
        "gate",
        "  const resolveAlias = (name: string): string => importAliases.get(name) ?? name",
        "  const resolveAlias = (name: string): string => name",
        "script",
        ["S-P48-renaming-import-alias"],
        "the escape hatch `calleeName`'s own docstring says must not exist. The "
        "receiver was defended (`import { UnitFormatter as UF }`); the CALLEE was "
        "not, in either the call form or the value form.",
    ),
    Mutation(
        "M83-jsx-render-labelled-as-a-value",
        "gate",
        "        jsx ? `<${node.text ?? ''} ...>` : `${node.text ?? ''} (as a value)`,",
        "        `${node.text ?? ''} (as a value)`,",
        "script",
        ["S-P49-binary-props-component-render"],
        "★ THE BRANCH FIX ROUND 1 ADDED AND NOTHING COULD KILL. Deleting the "
        "ternary left all 84 corpus cases and all 9 API-surface tests green, "
        "because no case rendered a binary-props component: the branch was "
        "defended in a comment and in a report, and by nothing that runs. It is a "
        "labelling branch rather than a detection one, so the consequence is small "
        "and the pattern is exactly the one this phase keeps recording, in code "
        "written to close an instance of it.",
    ),
    Mutation(
        "M75-drop-value-reference-leg",
        "gate",
        "      binaryHelpersHere.has(resolveAlias(node.text ?? '')) &&\n      isValueReference(node)\n    ) {",
        "      false &&\n      isValueReference(node)\n    ) {",
        "script",
        [
            "S-P44-binary-helper-as-a-value",
            "S-P49-binary-props-component-render",
        ],
        "the leg task 8 added last, and it was added because a NUMBER in this "
        "task's own report did not survive being checked against the enumerator. "
        "Two production sites in `ServiceVisitForm.tsx` pass a binary helper as a "
        "value, one of them the write path, and the call-shaped leg saw neither.",
    ),
    Mutation(
        "M76-binding-specifiers-are-uses",
        "gate",
        "  if (parent.kind === K.ImportSpecifier || parent.kind === K.ExportSpecifier) return false",
        "  if (false) return false",
        "script",
        [
            "S-N21-binary-helper-binding-sites",
            "S-P48-renaming-import-alias",
        ],
        "an import or an export names the symbol without deciding anything with "
        "it. Counting them makes every module that merely re-exports a binary "
        "helper a finding, which is how a leg earns a blanket pragma. ★ S-P48 joins it since fix round 1: that fixture aliases the import, so counting specifiers turns the import LINE into a finding on top of the call it exists to measure.",
    ),
    Mutation(
        "M77-declaration-names-are-uses",
        "gate",
        "  if (parent.name === node) {",
        "  if (false) {",
        "script",
        [
            "S-N21-binary-helper-binding-sites",
            "S-P46-exported-arrow-helper",
        ],
        "the other half of the same rule: the name half of a declaration, a "
        "binding or an object key is not a use. Without it a `{ toCanonicalKm: 1 }` "
        "registry reads as a call site. ★ S-P46 joins it since fix round 1: an arrow const's own VariableDeclaration name is a binding, and the widening that made arrow consts visible is what put it in reach of this rule.",
    ),
    Mutation(
        "M82-docstring-mention-is-a-pragma",
        "gate",
        "  if (/^\\s*\\*/.test(line)) return false",
        "  if (false) return false",
        "script",
        ["S-N22-pragma-mentioned-in-a-docstring"],
        "prose about a guard must not be the guard. Two lines in `utils/units.ts` "
        "describe this pragma inside a docstring and were inert only because a "
        "backtick precedes the `//` in both.",
    ),
    Mutation(
        "M72-scoped-pragma-silences-anything",
        "gate",
        "  return scope.split(',').map((k) => k.trim()).includes(kind)",
        "  return true",
        "script",
        [
            "S-P42-scoped-pragma-wrong-kind",
            "S-P43-scoped-declaration-wrong-kind",
        ],
        "★ the pragma as it behaved before task 8, run rather than described. "
        "`units.manifest.json` objected that a reason-bearing pragma \"silences "
        "anything\", and it was right: the bare form covers every kind on its line, "
        "including one nobody had thought about when they wrote the reason. That "
        "objection is what the bracket answers, and this is the mutation that makes "
        "the answer falsifiable rather than a comment.",
    ),
    Mutation(
        "M73-scoped-pragma-not-recognised",
        "gate",
        "const EXEMPT_PRAGMA = /(?:^|\\s)\\/\\/\\s*units-exempt(?:\\(([^)]*)\\))?:\\s*\\S/",
        "const EXEMPT_PRAGMA = /(?:^|\\s)\\/\\/\\s*units-exempt:\\s*\\S/",
        "script",
        ["S-N19-scoped-pragma-own-kind"],
        "the far side of M72: a form the regex does not recognise silences nothing, "
        "and after task 8 EVERY pragma under `src/` that suppresses anything carries "
        "the bracket. MEASURED by applying this mutation to the real gate and "
        "running `--report`: 45 findings under 32 keys across 11 files land in a "
        "clean-room gate, from 15 line pragmas covering 16 findings and 12 "
        "declaration pragmas hiding 29 more. ★ This description said \"nine\" twice "
        "until fix round 2, derived from a count that had already been corrected "
        "one file over and not re-derived here: wrong by 5x, in the sentence whose "
        "job is to say what the guard protects.",
    ),
    Mutation(
        "M74-placeholder-token-branch-flagged",
        "gate",
        "          if (inPlaceholder) structurallyExempt += 1\n          else record(node, 'token-branch', `${quantity}: ${normalize(node.getText(sf))}`)",
        "          record(node, 'token-branch', `${quantity}: ${normalize(node.getText(sf))}`)",
        "script",
        ["S-N20-placeholder-token-branch"],
        "R5 wired to the comparison leg only, which is how it stood for the whole "
        "phase. M7 removes the exemption from BOTH legs at once and cannot tell the "
        "two apart; this one leaves S-N1 passing and flags the placeholder spelling "
        "production actually uses.",
    ),
    Mutation(
        "M63-rename-the-binary-type-refuses",
        "gate",
        "const BINARY_SYSTEM_TYPE = 'UnitSystem'",
        "const BINARY_SYSTEM_TYPE = 'UnitSystemRenamed'",
        "script",
        [],  # filled in below: every script case, because the gate refuses them all
        "★ THE ONE-WORD RENAME THAT EMPTIES EVERY VOCABULARY AT ONCE. Both derived "
        "sets are matched by `takesBinarySystem`, which compares an annotation's "
        "TEXT to this literal, so changing it makes the formatter leg and the "
        "conversion leg blind in the same instant. `requireBinarySystemType` "
        "refuses on it directly, and refuses FIRST, which is the point: the "
        "accidental cover in `deriveBinaryFormatterMethods` only holds while the "
        "formatter surface is non-empty, and that surface shrinks with every task "
        "that migrates its call sites.",
        expect_probe="refuses:declares no type named",
    ),
    Mutation(
        "M64-renamed-type-with-no-direct-check",
        "gate",
        "const BINARY_SYSTEM_TYPE = 'UnitSystem'",
        "const BINARY_SYSTEM_TYPE = 'UnitSystemRenamed'",
        "script",
        [
            "S-P30-formatter-binary-call",
            "S-P31-formatter-label-selector",
            "S-P32-binary-conversion-call",
            "S-P35-aliased-formatter-receiver",
            "S-P37-binary-formatter-on-a-foreign-class",
            "S-P38-aliased-import-annotation",
            "S-P39-union-annotation",
            "S-P40-inline-props-annotation",
            "S-P41-named-props-interface",
            "S-P43-scoped-declaration-wrong-kind",
            "S-P44-binary-helper-as-a-value",
            "S-P45-module-local-helper",
            "S-P46-exported-arrow-helper",
            "S-P47-instance-method",
            "S-P48-renaming-import-alias",
            "S-P49-binary-props-component-render",
        ],
        "★ and the SURVIVOR it prevents, built and run. Take away the direct check "
        "AND the accidental cover (which is what retiring the last binary formatter "
        "does to `requireNonEmpty`, exactly as it already did on the conversion "
        "leg), and the same one-word rename is SILENT: three positives quietly stop "
        "being reported, every other case including both positive controls still "
        "passes, and the gate prints a tick. That is why the direct check is not "
        "defensive clutter. ★ FOUR positives, not three: the FIRST run of this "
        "mutation listed only the formatter cases and the harness reported the "
        "extra one, which is the mutation teaching its own author something. "
        "`takesBinarySystem` is shared, so the one-word rename blinds the "
        "conversion leg in the same instant, and S-P32 goes quiet with them. "
        "FIVE since task 7, which added a fourth formatter positive; the guard it "
        "takes away is now the one over the walk's static-method receipt, because "
        "the binary set the old one guarded is legitimately empty. ★ NINE since "
        "task 8, and it now has to take away a THIRD cover to stay a survivor. "
        "The tree-wide vocabulary is derived from the modules that MENTION the "
        "type, so renaming it leaves that walk with no module at all, and "
        "`deriveBinarySurface` refuses on the empty list. That cover is real and "
        "does not expire: the type is spelled wherever it is used, so a rename "
        "empties the walk on the day it lands. The four cases task 8 added go "
        "quiet with the rest, because an annotation the predicate cannot read is "
        "the same blindness spelled differently.",
        also=[
            ("requireBinarySystemType()\n", ""),
            (
                "  requireNonEmpty(statics, `static ${FORMATTER_CLASS} method`, UNITS_SOURCE)\n",
                "",
            ),
            (
                """  if (paths.length === 0) {
    throw new Error(
      `no module under ${relative(ROOT, SRC_DIR)} mentions ${BINARY_SYSTEM_TYPE}, so the ` +
        'tree-wide binary vocabulary would be empty and both binary legs would report ' +
        'zero findings for every file. Refusing to run: the type is declared in ' +
        `${relative(ROOT, UNITS_SOURCE)}, so at minimum that module must be here.`,
    )
  }
""",
                "",
            ),
        ],
    ),
    # ---------------- script leg: the R6 carry, five of six ------------------
    Mutation(
        "M50-drop-double-quoted-vocabulary",
        "gate",
        "  '\"imperial\"',\n  '\"metric\"',\n  '\"custom\"',\n",
        "",
        "script",
        ["S-P36-double-quoted-union"],
        "R6 carry, branch 6 of 6: added in round 2, unexercised until now. "
        "STRING_LITERAL_TYPE reads a double-quoted literal, so a missing "
        "vocabulary entry is a FAIL-OPEN rather than a fail-closed miss.",
    ),
    Mutation(
        "M57-drop-paren-balance-check",
        "gate",
        "    if (!balanced || depth !== 0) break",
        "    if (false) break",
        "script",
        ["S-N13-doubly-parenthesised-foreign"],
        "R6 carry, branch 2 of 6: without the balance check `('light') | "
        "('imperial')` is stripped ACROSS the union, both halves become "
        "unreadable, and fail-closed UNKNOWN flags correct code",
    ),
    Mutation(
        "M58-drop-void-never-nullish",
        "gate",
        "const NULLISH_MEMBERS = new Set(['null', 'undefined', 'void', 'never'])",
        "const NULLISH_MEMBERS = new Set(['null', 'undefined'])",
        "script",
        ["S-N14-void-and-never-members"],
        "R6 carry, branch 3 of 6: only `null` and `undefined` were exercised",
    ),
    Mutation(
        "M59-drop-numeric-boolean-literals",
        "gate",
        "const STRING_LITERAL_TYPE = /^(?:'[^']*'|\"[^\"]*\"|`[^`]*`|-?\\d+(?:\\.\\d+)?|true|false)$/",
        "const STRING_LITERAL_TYPE = /^(?:'[^']*'|\"[^\"]*\"|`[^`]*`)$/",
        "script",
        ["S-N15-numeric-and-boolean-members"],
        "R6 carry, branch 4 of 6: the gate's own docstring states this rounding "
        "(`'imperial' | 'metric' | 0` is a different enum) and nothing exercised it",
    ),
    Mutation(
        "M60-all-nullish-is-unknown",
        "gate",
        "  if (significant.length === 0) return 'nullish'",
        "  if (significant.length === 0) return 'unknown'",
        "script",
        ["S-N16-all-nullish-annotation"],
        "R6 carry, branch 5 of 6: the all-nullish return, reachable only from a "
        "degenerate annotation and unexercised since it was written",
    ),
    # ---------------- script leg: what the detector must NOT catch -----------
    Mutation(
        "M7-drop-placeholder-exemption",
        "gate",
        "        const inPlaceholder = isPlaceholderAttribute(node)",
        "        const inPlaceholder = false",
        "script",
        ["S-N1-placeholder", "S-N20-placeholder-token-branch"],
        "R5: a placeholder is an example value, and flagging it flags correct code. "
        "★ TWO cases since task 8, which wired the exemption to the token-branch leg "
        "as well; `FuelRecordForm.tsx:1029` had sat in the baseline as migration work "
        "for the whole phase because only the comparison leg asked.",
    ),
    Mutation(
        "M31-any-jsx-attribute-exempts",
        "gate",
        "      return cur.name?.text === 'placeholder'",
        "      return true",
        "script",
        ["S-P21-non-placeholder-attribute"],
        "★ widening R5 from `placeholder` to any JSX attribute took the real gate "
        "from 45 findings to 37, exit 0, reported as '8 fixed'",
    ),
    Mutation(
        "M8-drop-annotation-exemption",
        "gate",
        "          if (!hasForeignProvenance(operand, index)) {",
        "          if (true) {",
        "script",
        [
            "S-N13-doubly-parenthesised-foreign",
            "S-N14-void-and-never-members",
            "S-N15-numeric-and-boolean-members",
            "S-N16-all-nullish-annotation",
            "S-N2-foreign-provenance",
            "S-N6-parenthesised-foreign-alias",
        ],
        "★ R3: without the binding lookup this leg is an ESLint selector again. "
        "Both Theme cases go, which is the point: the exemption is one rule, not "
        "one case.",
    ),
    Mutation(
        "M9-literal-contains",
        "gate",
        "    SYSTEM_LITERALS.has(node.text)",
        "    [...SYSTEM_LITERALS].some((s) => (node.text ?? '').includes(s))",
        "script",
        ["S-N3-near-miss-literal"],
        "the literal must match exactly, not merely contain the word",
    ),
    Mutation(
        "M10a-drop-same-line-pragma",
        "gate",
        "  return lineExempts(lines[line - 1] ?? '', kind) || lineExempts(lines[line - 2] ?? '', kind)",
        "  return lineExempts(lines[line - 2] ?? '', kind)",
        "script",
        ["S-N4-pragma"],
        "R4 requires the escape hatch, so each of its two positions needs a test",
    ),
    Mutation(
        "M10b-drop-line-above-pragma",
        "gate",
        "  return lineExempts(lines[line - 1] ?? '', kind) || lineExempts(lines[line - 2] ?? '', kind)",
        "  return lineExempts(lines[line - 1] ?? '', kind)",
        "script",
        [
            "S-N4-pragma",
            "S-N17-exempt-binary-declaration",
            "S-N19-scoped-pragma-own-kind",
        ],
        "the first version of this mutation disabled only the other position and "
        "flipped nothing, which is what a corpus covering one position looks like. "
        "★ Task 8 gave this position a second tenant: `declarationExempt` marks a "
        "binary DECLARATION through the same helper, and a documented export "
        "carries its pragma above the `export` keyword because the line before "
        "that is the docstring's closing `*/`. So the line-above position now "
        "silences a call-site population in other modules as well, and S-N17 "
        "measures it. Measured, not reasoned: the first run of this edit reported "
        "the extra case.",
    ),
    Mutation(
        "M32-pragma-without-reason",
        "gate",
        "const EXEMPT_PRAGMA = /(?:^|\\s)\\/\\/\\s*units-exempt(?:\\(([^)]*)\\))?:\\s*\\S/",
        "const EXEMPT_PRAGMA = /units-exempt/",
        "script",
        [
            "S-P22-bare-pragma",
            "S-P42-scoped-pragma-wrong-kind",
            "S-P43-scoped-declaration-wrong-kind",
        ],
        "the docstring and the failure message both promise a reason",
    ),
    Mutation(
        "M38-any-unit-member-flags",
        "gate",
        "  if (significant.includes('foreign')) return 'foreign'",
        "  if (false) return 'foreign'",
        "script",
        [
            "S-N13-doubly-parenthesised-foreign",
            "S-N14-void-and-never-members",
            "S-N15-numeric-and-boolean-members",
            "S-N2-foreign-provenance",
            "S-N6-parenthesised-foreign-alias",
        ],
        "★ the reviewer's LITERAL rule, built and run: foreign only when no member "
        "is a unit system. It flips `type Theme = 'light' | 'dark' | 'imperial'`, "
        "which R2 requires to be accepted and R3 names as the case this leg exists "
        "to distinguish. That is why the shipped rule rounds the other way.",
    ),
    Mutation(
        "M40-drop-paren-stripping",
        "gate",
        "  while (out.startsWith('(') && out.endsWith(')')) {",
        "  while (false) {",
        "script",
        ["S-N13-doubly-parenthesised-foreign", "S-N6-parenthesised-foreign-alias"],
        "paren stripping can only be pinned from the NEGATIVE side: removing it "
        "makes the gate stricter, so no positive can flip",
    ),
    Mutation(
        "M11-flag-every-equality",
        "gate",
        "        if (rightIsLiteral || leftIsLiteral) {",
        "        if (true) {",
        "script",
        [
            "S-N10-foreign-token-property",
            "S-N11-wrong-quantity-vocabulary",
            "S-N12-secondary-gallon",
            "S-N19-scoped-pragma-own-kind",
            "S-N22-pragma-mentioned-in-a-docstring",
            "S-N3-near-miss-literal",
            "S-N5-positive-control",
            "S-P33-token-branch-property",
            "S-P34-token-branch-destructured",
        ],
        "★ T4-R7's mirror: a guard that fires unconditionally looks healthier "
        "than one that never fires and is worth exactly as much",
    ),
    # ---------------- ESLint leg ---------------------------------------------
    Mutation(
        "M12-drop-named-list",
        "config",
        "'Literal[raw=/^(?:1609\\\\.34|25\\\\.4|235\\\\.214|282\\\\.481)$/]'",
        "'Literal[raw=/^(?:__never__)$/]'",
        "eslint",
        [
            "E-P1-metres-per-mile",
            "E-P3-mm-per-inch",
            "E-P4-mpg-to-l100km",
            "E-P9-uk-mpg-factor",
        ],
        "the low-precision factors are invisible to the precision rule",
    ),
    Mutation(
        "M33-drop-uk-mpg-from-named-list",
        "config",
        "|282\\\\.481)$/]",
        ")$/]",
        "eslint",
        ["E-P9-uk-mpg-factor"],
        "one factor at a time: dropping the whole list is not the same experiment",
    ),
    Mutation(
        "M21-narrow-precision-threshold",
        "config",
        "'Literal[raw=/^\\\\d+\\\\.\\\\d{4,}$/]'",
        "'Literal[raw=/^\\\\d+\\\\.\\\\d{7,}$/]'",
        "eslint",
        ["E-P2-litres-per-gallon", "E-P5-bar-to-psi", "E-P6-unlisted-factor"],
        "four digits is the line between a factor and a UI constant",
    ),
    Mutation(
        "M13-widen-precision-threshold",
        "config",
        "'Literal[raw=/^\\\\d+\\\\.\\\\d{4,}$/]'",
        "'Literal[raw=/^\\\\d+\\\\.\\\\d{3,}$/]'",
        "eslint",
        [
            "E-N1-propane-density",
            "E-N3-ordinary-ui-numbers",
            "E-P4-mpg-to-l100km",
            "E-P9-uk-mpg-factor",
        ],
        "★ R5: this is the widening that would flag the propane density, which "
        "is correct code that codex hard-reviewed twice",
    ),
    Mutation(
        "M14-drop-cf-idiom",
        "config",
        "[left.operator='/'][left.right.value=5]",
        "[left.operator='/'][left.right.value=5555]",
        "eslint",
        ["E-P7-c-to-f-ninths"],
        "R7: the idiom carries no constant distinctive enough to list",
    ),
    Mutation(
        "M14b-drop-cf-decimal-idiom",
        "config",
        "[left.operator='*'][left.right.value=1.8]",
        "[left.operator='*'][left.right.value=1.8888]",
        "eslint",
        ["E-P8-c-to-f-decimal"],
        "the same conversion spelled with 1.8",
    ),
    Mutation(
        "M15-match-value-not-raw",
        "config",
        "'Literal[raw=/^\\\\d+\\\\.\\\\d{4,}$/]'",
        "'Literal[value=/^\\\\d+\\\\.\\\\d{4,}$/]'",
        "eslint",
        [
            "E-N2-string-that-looks-like-a-factor",
            "E-P2-litres-per-gallon",
            "E-P5-bar-to-psi",
            "E-P6-unlisted-factor",
        ],
        "a string's value looks exactly like a factor and its raw text does not, "
        "and esquery does not coerce a number to match a regex, so this breaks "
        "the rule in both directions at once",
    ),
    Mutation(
        "M34-drop-i18n-spread",
        "config",
        "'no-restricted-syntax': ['error', ...I18N_RESTRICTED, ...UNIT_CONSTANT_RESTRICTED],",
        "'no-restricted-syntax': ['error', ...UNIT_CONSTANT_RESTRICTED],",
        "eslint",
        ["E-P10-i18n-guard-survives-scoping"],
        "★ the exact regression the hoisting comment claims to prevent: a later "
        "config object REPLACES a rule's options rather than merging into them",
    ),
    Mutation(
        "M16-flag-every-number",
        "config",
        "'Literal[raw=/^\\\\d+\\\\.\\\\d{4,}$/]'",
        "'Literal[raw=/^\\\\d+(?:\\\\.\\\\d+)?$/]'",
        "eslint",
        [
            "E-N1-propane-density",
            "E-N3-ordinary-ui-numbers",
            "E-N4-positive-control",
            "E-P1-metres-per-mile",
            "E-P3-mm-per-inch",
            "E-P4-mpg-to-l100km",
            "E-P7-c-to-f-ninths",
            "E-P8-c-to-f-decimal",
            "E-P9-uk-mpg-factor",
        ],
        "★ T4-R7's mirror on the ESLint leg: every ordinary number becomes a "
        "finding and every real factor is reported twice",
    ),
]

# M42 makes the gate refuse every file, so it flips every script case by
# construction. Derived, never typed out: this phase has now twice been bitten by
# a hardcoded expectation that went stale one argument over.
# M61 does the same for a different reason: the derivation guard refuses before
# any file is scanned.
for _m in MUTATIONS:
    if _m.mid in {
        "M42-no-parse-diagnostics-property",
        "M61-empty-formatter-derivation-refuses",
        "M63-rename-the-binary-type-refuses",
    }:
        _m.flips = [c.cid for c in C.SCRIPT_POSITIVE + C.SCRIPT_NEGATIVE]

# Mutations of the tree WALK rather than the scan. `walkDir` is unreachable from
# `--scan`, so the corpus cannot see these at all: they are scored against an
# owned fixture tree via `--src`.
WALK_MUTATIONS = [
    (
        "M35-drop-dts-exclusion",
        "      !entry.endsWith('.d.ts')\n",
        "      true\n",
        "types.d.ts",
        "a declaration file holds types, not decisions",
    ),
    (
        "M36-drop-test-file-exclusion",
        "      !entry.endsWith('.test.ts') &&\n      !entry.endsWith('.test.tsx') &&\n",
        "",
        "b.test.ts",
        "tests mock both systems on purpose; including them drowns the work list",
    ),
    (
        "M37-drop-tests-dir-exclusion",
        "      if (entry === '__tests__' || entry === 'node_modules') continue\n",
        "",
        "__tests__/t.ts",
        "same reasoning, one directory over",
    ),
]


def write_mutant(
    target: str, old: str, new: str, also: list[tuple[str, str]] | None = None
) -> tuple[Path, int]:
    """Write a mutated COPY and return (path, the WORST occurrence count seen).

    Every edit must match exactly once. Returning the worst count rather than
    the first keeps the PATTERN guard meaningful for multi-edit mutations: a
    combined mutation whose second edit silently matched nothing would otherwise
    be scored as though it had applied.
    """
    src = GATE_SRC if target == "gate" else ESLINT_CFG
    dst = GATE_MUTANT if target == "gate" else CFG_MUTANT
    text = src.read_text()
    worst = 1
    for a, b in [(old, new), *(also or [])]:
        n = text.count(a)
        if n != 1:
            worst = n
            break
        text = text.replace(a, b)
    if worst == 1:
        dst.write_text(text)
    return dst, worst


def mutant_is_valid(
    target: str, tmpdir: Path, expect_probe: str = "clean"
) -> str | None:
    """Prove the mutant still RUNS before its result is allowed to mean anything.

    Round 1 of the sibling mutation harness scored a syntax-broken mutant as a
    clean survivor. Here the mirror risk is worse: a mutant that fails to run
    flips every case at once and reads as a successful wide mutation.
    """
    probe = tmpdir / "validity_probe.tsx"
    probe.write_text(VALIDITY_PROBE)
    if target == "gate":
        p = subprocess.run(
            [
                "bun",
                "run",
                str(GATE_MUTANT.relative_to(FRONTEND)),
                "--scan",
                str(probe),
            ],
            cwd=FRONTEND,
            capture_output=True,
            text=True,
        )
        if expect_probe.startswith("refuses:"):
            # The mutation's whole point is that the gate now refuses every
            # file. It must still refuse with the SPECIFIC message it names,
            # rather than crashing or refusing for some other reason: a
            # substring check against one hardcoded message would score every
            # refusing mutation against whichever one was written first.
            expected = expect_probe.split(":", 1)[1]
            if p.returncode == 0:
                return "mutant was expected to refuse and did not"
            if expected not in (p.stderr or p.stdout):
                return (
                    f"mutant did not refuse with {expected!r}: "
                    f"{(p.stderr or p.stdout).strip()[-200:]}"
                )
            return None
        if p.returncode != 0:
            return f"mutant does not run: {(p.stderr or p.stdout).strip()[-200:]}"
        try:
            if json.loads(p.stdout)["findings"]:
                return "mutant reports findings on an input with none"
        except (json.JSONDecodeError, KeyError):
            return f"mutant emitted non-JSON: {p.stdout.strip()[:200]}"
        return None
    p = subprocess.run(
        [
            "bunx",
            "eslint",
            "--format",
            "json",
            "--config",
            str(CFG_MUTANT.relative_to(FRONTEND)),
            str(probe),
        ],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(p.stdout)
    except json.JSONDecodeError:
        return f"mutated config does not load: {(p.stderr or p.stdout).strip()[-200:]}"
    if any(
        m.get("ruleId") == "no-restricted-syntax"
        for f in payload
        for m in f["messages"]
    ):
        return "mutated config reports findings on an input with none"
    return None


def run_leg(
    leg: str, tmpdir: Path, mutated: str | None = None
) -> dict[str, tuple[int, list[str]]]:
    """Run every case of one leg and return {case id: (count, detail)}."""
    cases = (
        C.SCRIPT_POSITIVE + C.SCRIPT_NEGATIVE
        if leg == "script"
        else C.ESLINT_POSITIVE + C.ESLINT_NEGATIVE
    )
    out: dict[str, tuple[int, list[str]]] = {}
    for case in cases:
        if leg == "script":
            gate = mutated or C.GATE
            out[case.cid] = C.run_script_leg(case, tmpdir, gate)
        else:
            out[case.cid] = C.run_eslint_leg(case, mutated)
    return out


def eslint_messages(path: Path, config: str | None = None) -> list[str]:
    argv = ["bunx", "eslint", "--format", "json"]
    if config is not None:
        argv += ["--config", config]
    p = subprocess.run([*argv, str(path)], cwd=FRONTEND, capture_output=True, text=True)
    try:
        payload = json.loads(p.stdout)
    except json.JSONDecodeError:
        return [f"eslint emitted non-JSON: {(p.stdout or p.stderr).strip()[:200]}"]
    return [
        m["message"]
        for f in payload
        for m in f["messages"]
        if m.get("ruleId") == "no-restricted-syntax"
    ]


def scope_proof() -> list[str]:
    """T4-R6: the constant rule's scope is real, proved four ways.

    ★ Rewritten for round 5. The rule used to be opt-in over a list of migrated
    paths, and the whole-branch review measured what nobody had: running it over
    the whole tree yields exactly two findings, both in files already named as
    deliberate omissions. So the scope is now `src/**` minus three named files,
    and the interesting question changed with it. It is no longer "does an
    unmigrated path stay quiet"; it is "does a file that did not exist when the
    list was written get seen", and "is each exemption real rather than a bare
    omission".
    """
    failures: list[str] = []
    SCOPE_FIXTURE.write_text("export const METRES_PER_MILE = 1609.34\n")
    original = ESLINT_CFG.read_text()
    try:
        outside = eslint_messages(SCOPE_FIXTURE)
        if outside:
            failures.append(
                f"scope: a path outside the scope was linted anyway: {outside}"
            )
        print(
            f"  scope OUTSIDE  {'silent' if not outside else '*** LOUD ***'}"
            "   scripts/ is outside src/**, so the corpus cannot self-trigger"
        )

        anchor = "const UNITS_CONSTANT_SCOPE = ['src/**/*.{ts,tsx}', 'scripts/__units_corpus__.tsx']"
        if anchor not in original:
            failures.append("scope: could not find UNITS_CONSTANT_SCOPE")
            return failures
        CFG_MUTANT.write_text(
            original.replace(
                anchor,
                anchor.replace("]", ", 'scripts/__units_scope_probe__.tsx']"),
            )
        )
        inside = eslint_messages(SCOPE_FIXTURE, str(CFG_MUTANT.relative_to(FRONTEND)))
        if len(inside) != 1 or "Raw unit-conversion constant" not in inside[0]:
            failures.append(f"scope: a path INSIDE the scope was not flagged: {inside}")
        print(
            f"  scope INSIDE   {'fired' if inside else '*** SILENT ***'}"
            f"     {inside[0][:58] if inside else 'nothing reported'}"
        )
        CFG_MUTANT.unlink(missing_ok=True)

        # Each exemption must be a real one: silent now, loud the moment it is
        # taken off the list. unitAdapters.ts carries `IN32_TO_MM = 25.4 / 32`,
        # a genuine factor, so it is the honest probe.
        #
        # units.ts is not a candidate, and the reason CHANGED in phase 3b task 2.
        # It used to be on this list AND silenced outright by the i18n-utility
        # `'off'` block further down, which wins by ordering, so un-listing it
        # here proved nothing. It is now on NEITHER list: the factor table
        # carries its own scoped `eslint-disable` and the rest of the file is
        # linted like any other, which is why removing it from the list below
        # was a real change rather than a no-op.
        probe = FRONTEND / "src/utils/unitAdapters.ts"
        before = eslint_messages(probe)
        if before:
            failures.append(f"scope: an exempt file was flagged: {before}")
        # Anchor 2 gets the same existence check anchor 1 has. Without it a
        # rename here fails only as a downstream outcome, reported as
        # "un-exempting did not flag it" when the un-exempting never happened:
        # a misattributing message, which is worse than a loud one because it
        # sends the reader to the wrong file. The PATTERN guard does not reach
        # this function, so nothing else would catch it.
        exempt_anchor = "  'src/utils/unitAdapters.ts',\n"
        if exempt_anchor not in original:
            failures.append(
                f"scope: the exemption anchor {exempt_anchor.strip()!r} is missing "
                "from eslint.config.js, so the EXEMPT check cannot run"
            )
            return failures
        CFG_MUTANT.write_text(original.replace(exempt_anchor, ""))
        after = eslint_messages(probe, str(CFG_MUTANT.relative_to(FRONTEND)))
        if len(after) != 1 or "Raw unit-conversion constant" not in after[0]:
            failures.append(
                f"scope: un-exempting unitAdapters.ts did not flag it: {after}"
            )
        print(
            f"  scope EXEMPT   {'real' if not before and after else '*** NOT REAL ***'}"
            f"       silent while listed, {len(after)} finding(s) when un-listed"
        )
        CFG_MUTANT.unlink(missing_ok=True)

        # A typo in an exemption path silently un-exempts a file, which fails
        # loudly; a typo that names nothing at all is the quiet one.
        block = re.search(r"const UNITS_CONSTANT_EXEMPT = \[(.*?)\n\]", original, re.S)
        if block is None:
            failures.append("scope: could not read UNITS_CONSTANT_EXEMPT")
            return failures
        entries = re.findall(r"^\s*'([^']+)',\s*$", block.group(1), re.M)
        missing = [e for e in entries if not (FRONTEND / e).exists()]
        if missing:
            failures.append(
                f"scope: {len(missing)} exemption(s) name no file: {missing}"
            )
        print(
            f"  scope ENTRIES  {'all real' if not missing else '*** MISSING ***'}"
            f"    {len(entries)} exemptions, {len(missing)} that name nothing"
        )
    finally:
        SCOPE_FIXTURE.unlink(missing_ok=True)
        CFG_MUTANT.unlink(missing_ok=True)
    return failures


def run_gate(baseline: Path, src: Path, gate: Path = GATE_SRC) -> tuple[int, str]:
    p = subprocess.run(
        [
            "bun",
            "run",
            str(gate.relative_to(FRONTEND)),
            "--baseline",
            str(baseline),
            "--src",
            str(src),
        ],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
    )
    return p.returncode, (p.stdout + p.stderr)


ONE_COMPARISON = (
    "import { useUnitPreference } from '@/hooks/useUnitPreference'\n"
    "export function a(): string {\n"
    "  const { system } = useUnitPreference()\n"
    "  return system === 'imperial' ? 'mi' : 'km'\n"
    "}\n"
)


def baseline_proof(tmpdir: Path) -> list[str]:
    """R4: the baseline counts occurrences; set membership lets a duplicate pass."""
    failures: list[str] = []
    tree = tmpdir / "baseline_tree"
    tree.mkdir()
    baseline = tmpdir / "units.baseline.probe.json"
    (tree / "a.ts").write_text(ONE_COMPARISON)
    try:
        subprocess.run(
            [
                "bun",
                "run",
                "scripts/validate-units.ts",
                "--update",
                "--baseline",
                str(baseline),
                "--src",
                str(tree),
            ],
            cwd=FRONTEND,
            capture_output=True,
            text=True,
            check=True,
        )
        rc, out = run_gate(baseline, tree)
        if rc != 0:
            failures.append(
                f"baseline: a freshly written baseline did not pass: {out[:200]}"
            )
        print(f"  baseline SAME  {'passes' if rc == 0 else '*** FAILS ***'}")

        # The duplicate. Same file, same expression, one more occurrence.
        (tree / "a.ts").write_text(
            ONE_COMPARISON + "export function b(): string {\n"
            "  const { system } = useUnitPreference()\n"
            "  return system === 'imperial' ? 'mi' : 'km'\n"
            "}\n"
        )
        rc, out = run_gate(baseline, tree)
        ok = rc == 1 and "1 unit-system branch" in out
        if not ok:
            failures.append(
                f"baseline: a DUPLICATE occurrence did not fail: rc={rc} {out[:200]}"
            )
        print(f"  baseline DUP   {'fails as it must' if ok else '*** PASSED ***'}")

        # ...and the same duplicate under the set-keyed model the ruling rejects.
        dst, n = write_mutant(
            "gate",
            "    .filter(([key, count]) => count > (allowed.get(key) ?? 0))",
            "    .filter(([key]) => !allowed.has(key))",
        )
        if n != 1:
            failures.append(
                f"baseline: set-keying mutation matched {n} times, expected 1"
            )
        else:
            rc, _ = run_gate(baseline, tree, dst)
            if rc != 0:
                failures.append(
                    "baseline: set-keying was expected to MISS the duplicate"
                )
            print(
                f"  baseline SET   {'misses it, as the ruling says' if rc == 0 else '*** caught ***'}"
                "   <- the hole R4 exists to close"
            )
    finally:
        GATE_MUTANT.unlink(missing_ok=True)
    return failures


def cleanroom_proof(tmpdir: Path) -> list[str]:
    """★ R5: AN EMPTY BASELINE IS NOT THE PROOF. Fire every leg on purpose.

    The plan's wording, kept verbatim because it names the failure this section
    exists to prevent: "an empty baseline with a gate that cannot fire is the
    phase's signature defect wearing its final costume." A clean-room gate over
    a tree with nothing in it is green whether it detects anything or not, and
    green is exactly what a broken one looks like.

    So each detector kind gets its own violation, introduced into a tree the gate
    is pointed at, and each has to make the gate exit nonzero and NAME that kind.
    Then the file goes and the tree has to be green again, because a gate stuck
    at "fail" proves as little as one stuck at "pass".

    ★ THE LEGS ARE DERIVED FROM THE GATE, NOT LISTED HERE. The kinds are read
    out of `validate-units.ts`'s own `record(...)` calls, and the fixtures are
    the CORPUS's own positives, one per kind. A sixth leg added without a corpus
    positive fails this section rather than quietly going unproved, which is the
    difference between a per-leg proof and an inventory that is a floor.

    The `--update` refusal is proved here too, and it is proved by watching the
    committed baseline's bytes rather than by trusting an exit code: the whole
    point of that guard is that the file must not move.
    """
    failures: list[str] = []
    tree = tmpdir / "cleanroom_tree"
    tree.mkdir()
    gate = str(GATE_SRC.relative_to(FRONTEND))

    def run(argv: list[str]) -> tuple[int, str]:
        p = subprocess.run(
            ["bun", "run", gate, *argv], cwd=FRONTEND, capture_output=True, text=True
        )
        return p.returncode, p.stdout + p.stderr

    # The control. Clean-room means the tick is reachable at all, and a gate
    # that refuses everything would pass every fixture below.
    rc, out = run(["--src", str(tree)])
    ok = rc == 0
    if not ok:
        failures.append(f"cleanroom: an empty tree did not pass: rc={rc} {out[-200:]}")
    print(f"  cleanroom EMPTY      {'green' if ok else '*** ' + out[-100:] + ' ***'}")

    # ★ TWO DERIVATIONS OF THE SAME LIST, ASSERTED TO AGREE. The gate DECLARES
    # `FINDING_KINDS` and its success line counts that list; this reads the
    # `record(...)` CALL SITES instead. A leg added at a call site and forgotten
    # in the list makes the gate refuse on its first finding, and a name left in
    # the list with no call site would make the claim count a detector that does
    # not exist. Neither half can move alone, and this is what makes the
    # registry killable rather than a guard nothing can fail.
    gate_text = GATE_SRC.read_text()
    called = sorted(set(re.findall(r"record\([^,]+, '([a-z-]+)'", gate_text)))
    declared_block = re.search(r"const FINDING_KINDS = \[(.*?)\] as const", gate_text, re.S)
    declared = sorted(re.findall(r"'([a-z-]+)'", declared_block.group(1))) if declared_block else []
    if not called:
        failures.append("cleanroom: read no finding kinds out of the gate; refusing to conclude")
        return failures
    if not declared:
        failures.append("cleanroom: found no FINDING_KINDS declaration; the claim counts it")
        return failures
    if called != declared:
        failures.append(
            f"cleanroom: the gate records {called} and declares {declared}. The success "
            "line counts the declaration, so it would name a different number of "
            "detectors than the gate runs."
        )
    print(
        f"  cleanroom KINDS      {len(declared)} declared, {len(called)} recorded, "
        + ("they agree" if called == declared else "*** THEY DISAGREE ***")
    )
    kinds = called
    covered: dict[str, object] = {}
    for case in C.SCRIPT_POSITIVE:
        if case.expect_kind and case.expect_kind not in covered:
            covered[case.expect_kind] = case
    missing = [k for k in kinds if k not in covered]
    if missing:
        failures.append(
            f"cleanroom: the gate emits {missing} and the corpus has no positive for it, "
            "so those legs would go unproved while this section printed a tick"
        )

    for kind in kinds:
        case = covered.get(kind)
        if case is None:
            print(f"  cleanroom {kind:<10} *** NO CORPUS POSITIVE ***")
            continue
        fixture = tree / f"{kind.replace('-', '_')}{case.ext}"
        fixture.write_text(case.body)
        try:
            rc, out = run(["--src", str(tree)])
            fired = rc == 1 and f"[{kind}]" in out
            if not fired:
                failures.append(
                    f"cleanroom {kind}: a fresh violation did not fail the gate: "
                    f"rc={rc} {out[-200:]}"
                )
        finally:
            fixture.unlink(missing_ok=True)
        rc_after, out_after = run(["--src", str(tree)])
        recovered = rc_after == 0
        if not recovered:
            failures.append(
                f"cleanroom {kind}: the gate stayed red after the violation was removed: "
                f"rc={rc_after} {out_after[-200:]}"
            )
        print(
            f"  cleanroom {kind:<10} "
            + ("fails on it, green without it" if fired and recovered else "*** " + ("did not fire" if not fired else "stayed red") + " ***")
            + f"   <- {case.cid}"
        )

    # ★ The one-word undo, watched at the FILE rather than at the exit code.
    baseline = FRONTEND / "scripts/units.baseline.json"
    before = baseline.read_bytes()
    try:
        rc, out = run(["--update"])
        unchanged = baseline.read_bytes() == before
        ok = rc != 0 and unchanged
        if not ok:
            failures.append(
                f"cleanroom: --update was expected to refuse the default baseline and leave "
                f"it byte-identical: rc={rc}, unchanged={unchanged}"
            )
        print(
            f"  cleanroom --update   "
            + ("refused, file untouched" if ok else "*** rewrote the baseline ***")
        )
    finally:
        baseline.write_bytes(before)
    return failures


def reexport_refusal_proof(tmpdir: Path) -> list[str]:
    """A module that renames the binary type must make the gate REFUSE.

    ★ The prefilter that makes this gate affordable (3 ms against 221 ms, times
    53 scans per mutation) is sound only while every module using the binary
    type spells its name. One module re-exporting it under another name breaks
    that for every module downstream, silently, so the gate refuses rather than
    hoping. `--scan` runs the same refusal, which is what lets this be proved
    against a fixture in a temp directory instead of one written into `src/`,
    where the corpus already learned not to put fixtures.

    Both spellings are probed. The gate covered only the first until fix round 1,
    and the second is the one anybody would actually write.
    """
    failures: list[str] = []
    probes = [
        (
            "specifier",
            "import type { UnitSystem } from '@/utils/units'\n"
            "export type { UnitSystem as Sys }\n",
        ),
        (
            "type alias",
            "import type { UnitSystem } from '@/utils/units'\nexport type Sys = UnitSystem\n",
        ),
    ]
    control = "import type { UnitSystem } from '@/utils/units'\nexport type Sys2 = { a: UnitSystem }\n"
    for label, body in [*probes, ("control (not an alias)", control)]:
        probe = tmpdir / "reexport_probe.ts"
        probe.write_text(body)
        p = subprocess.run(
            ["bun", "run", str(GATE_SRC.relative_to(FRONTEND)), "--scan", str(probe)],
            cwd=FRONTEND,
            capture_output=True,
            text=True,
        )
        probe.unlink(missing_ok=True)
        wanted_refusal = label != "control (not an alias)"
        refused = p.returncode != 0 and "would never spell" in (p.stderr + p.stdout)
        ok = refused == wanted_refusal
        if not ok:
            failures.append(
                f"reexport {label}: expected {'a refusal' if wanted_refusal else 'no refusal'}, "
                f"rc={p.returncode} {(p.stderr or p.stdout).strip()[-160:]}"
            )
        print(
            f"  reexport {label:<24} "
            + ("refuses" if refused else "runs")
            + ("" if ok else "   *** WRONG ***")
        )
    return failures


def crossfile_proof() -> list[str]:
    """Task 8's precondition, proved against the REAL tree rather than a fixture.

    ★ WHY IT CANNOT BE A CORPUS CASE. The corpus scans fixtures under
    `scripts/`, and the whole subject here is a vocabulary derived from
    `frontend/src`: a helper declared in one module and called from ANOTHER.
    One file is all `--scan` can ever see, so the leg that closes the
    cross-file hole is, to the corpus, a guard nothing can kill.

    Three runs of the real gate over the real tree, and the third is the one
    that matters:

      BASE          as committed: green.
      HATCH OFF     `declarationExempt` always false, so every exempted binary
                    declaration re-enters the vocabulary. The gate must FAIL and
                    must name a site in a file OTHER than the one that declares
                    them, which is the cross-file reach itself.
      HATCH OFF +   and the same run with the pre-task-8 vocabulary restored:
      PRE-TASK 8    `decimalSafe.ts` alone, which is what task 5 left, AND no
                    module-local declarations, which is what fix round 1 added.
                    It must go GREEN, because none of those helpers was in the
                    vocabulary at all. That silence IS the defect the
                    precondition names, reproduced on demand.
    """
    failures: list[str] = []

    def run(gate: Path) -> tuple[int, str]:
        p = subprocess.run(
            ["bun", "run", str(gate.relative_to(FRONTEND))],
            cwd=FRONTEND,
            capture_output=True,
            text=True,
        )
        return p.returncode, p.stdout + p.stderr

    HATCH_OFF = ("  return exemptedAtLine(lines, line, kind)", "  return false")
    SINGLE_FILE = (
        "const BINARY_CONVERSION_HELPERS = BINARY_SURFACE.helpers",
        "const BINARY_CONVERSION_HELPERS = deriveBinaryConversionHelpers()",
    )
    # ★ THE PRE-TASK-8 GATE HAD TWO FLOORS, NOT ONE, and fix round 1 is what
    # taught this probe that. Reverting the vocabulary to `decimalSafe.ts` alone
    # stopped reproducing the silence once module-local declarations became
    # visible per file, because the supplies components declare their own
    # helpers and the scanned file's augmentation still found them. So the
    # reproduction reverts BOTH: the tree-wide vocabulary and the local half.
    # A reproduction that no longer reproduces is worse than none, since it
    # reads as the defect being gone.
    NO_LOCALS = (
        "    if (decl.exported) exportedBinary.add(decl.name)\n    else localBinary.add(decl.name)",
        "    if (decl.exported) exportedBinary.add(decl.name)",
    )
    try:
        rc, out = run(GATE_SRC)
        ok = rc == 0
        if not ok:
            failures.append(f"crossfile: the committed gate is not green: {out[-300:]}")
        print(f"  crossfile BASE      {'green' if ok else '*** ' + out[-120:] + ' ***'}")

        dst, n = write_mutant("gate", *HATCH_OFF)
        if n != 1:
            failures.append(f"crossfile: HATCH OFF matched {n} times, expected 1")
        else:
            rc, out = run(dst)
            # The three helpers are declared in utils/supplyUnits.ts. A finding
            # anywhere else is the cross-file reach; a finding only in that file
            # would prove nothing the same-file augmentation did not already do.
            # ★ `and "src/" in line` is not decoration. The failure output ends
            # with a guidance block that also contains "[binary-conversion]",
            # and without the path test this counted it as a twelfth call-site
            # key. The assertion (`> 0`) never noticed; the NUMBER printed
            # beside it was wrong, which is the same defect one level down from
            # the one this whole gate exists to prevent.
            elsewhere = [
                line
                for line in out.splitlines()
                if "[binary-conversion]" in line
                and "src/" in line
                and "supplyUnits.ts" not in line
            ]
            ok = rc == 1 and len(elsewhere) > 0
            if not ok:
                failures.append(
                    "crossfile: with the declaration hatch off the gate was expected to "
                    f"fail on call sites outside the declaring module: rc={rc} {out[-300:]}"
                )
            print(
                f"  crossfile HATCH OFF {'fails on ' + str(len(elsewhere)) + ' call site key(s) outside supplyUnits.ts' if ok else '*** PASSED ***'}"
            )
        GATE_MUTANT.unlink(missing_ok=True)

        dst, n = write_mutant("gate", *HATCH_OFF, also=[SINGLE_FILE, NO_LOCALS])
        if n != 1:
            failures.append(f"crossfile: PRE-TASK8 matched {n} times, expected 1")
        else:
            rc, out = run(dst)
            ok = rc == 0
            if not ok:
                failures.append(
                    "crossfile: the pre-task-8 vocabulary was expected to be BLIND to "
                    f"them: rc={rc} {out[-300:]}"
                )
            print(
                f"  crossfile PRE-TASK8 {'silent, which is the hole' if ok else '*** it saw them ***'}"
                "   <- what the flip would have claimed clean"
            )
    finally:
        GATE_MUTANT.unlink(missing_ok=True)
    return failures


def walk_proof(tmpdir: Path) -> list[str]:
    """The tree walk's exclusions, which `--scan` can never reach."""
    failures: list[str] = []
    tree = tmpdir / "walk_tree"
    (tree / "__tests__").mkdir(parents=True)
    (tree / "a.ts").write_text(ONE_COMPARISON)
    (tree / "types.d.ts").write_text(ONE_COMPARISON)
    (tree / "b.test.ts").write_text(ONE_COMPARISON)
    (tree / "__tests__" / "t.ts").write_text(ONE_COMPARISON)
    baseline = tmpdir / "walk.baseline.json"

    def scanned(gate: Path) -> set[str]:
        subprocess.run(
            [
                "bun",
                "run",
                str(gate.relative_to(FRONTEND)),
                "--update",
                "--baseline",
                str(baseline),
                "--src",
                str(tree),
            ],
            cwd=FRONTEND,
            capture_output=True,
            text=True,
            check=True,
        )
        return {
            e["file"].split("walk_tree/")[-1] for e in json.loads(baseline.read_text())
        }

    try:
        base = scanned(GATE_SRC)
        ok = base == {"a.ts"}
        if not ok:
            failures.append(
                f"walk: expected only a.ts to be scanned, got {sorted(base)}"
            )
        print(
            f"  walk BASE      {'a.ts only' if ok else '*** ' + str(sorted(base)) + ' ***'}"
        )

        for mid, old, new, expected_file, why in WALK_MUTATIONS:
            dst, n = write_mutant("gate", old, new)
            if n != 1:
                failures.append(f"{mid}: PATTERN occurs {n} times, expected 1")
                print(f"  {mid:<32} *** NOT A VALID MUTANT ***")
                continue
            bad = mutant_is_valid("gate", tmpdir)
            if bad:
                failures.append(f"{mid}: {bad}")
                print(f"  {mid:<32} *** MUTANT DID NOT RUN *** {bad}")
                GATE_MUTANT.unlink(missing_ok=True)
                continue
            got = scanned(dst)
            GATE_MUTANT.unlink(missing_ok=True)
            gained = got - base
            ok = gained == {expected_file}
            if not ok:
                failures.append(
                    f"{mid}: expected to gain {expected_file}, gained {sorted(gained)}"
                )
            print(
                f"  {mid:<32} {'gains ' + expected_file if ok else '*** ' + str(sorted(gained)) + ' ***'}"
            )
    finally:
        GATE_MUTANT.unlink(missing_ok=True)
    return failures


def main() -> int:
    # ★ Round 4 replaced a start-time CLEANUP with a start-time REFUSAL.
    # Deleting leftovers meant a concurrent corpus run had its fixture removed
    # underneath it, so each run could report a result reflecting a file it did
    # not write. A wrong answer is worse than a manual cleanup, and the corpus
    # now runs inside `validate:translations`, so every local
    # `bin/ci-check --frontend` is a candidate for that collision.
    refusal = C.acquire_lock(
        "units_gate_selftest.py",
        [GATE_MUTANT, CFG_MUTANT, SCOPE_FIXTURE, C.ESLINT_FIXTURE],
    )
    if refusal:
        print(refusal)
        return 2
    failures: list[str] = []
    tmpdir = Path(tempfile.mkdtemp(prefix="units-selftest-"))
    try:
        print("deriving reference results from the unmutated gate")
        reference = {
            "script": run_leg("script", tmpdir),
            "eslint": run_leg("eslint", tmpdir),
        }
        for leg, results in reference.items():
            cases = (
                C.SCRIPT_POSITIVE + C.SCRIPT_NEGATIVE
                if leg == "script"
                else C.ESLINT_POSITIVE + C.ESLINT_NEGATIVE
            )
            for case in cases:
                bad = C.check(case, *results[case.cid])
                if bad:
                    failures.append(f"reference {case.cid}: {bad}")
        if failures:
            print("the corpus is not green, so no mutation result would mean anything:")
            for f in failures:
                print("  " + f)
            return 1
        print(
            f"  {len(reference['script'])} script cases + {len(reference['eslint'])} "
            "ESLint cases, all as documented\n"
        )

        print("mutations: each must RUN, then flip exactly the cases that name it")
        print("-" * 78)
        for mut in MUTATIONS:
            dst, n = write_mutant(mut.target, mut.old, mut.new, mut.also)
            if n != 1:
                failures.append(f"{mut.mid}: PATTERN occurs {n} times, expected 1")
                print(
                    f"  {mut.mid:<32} *** NOT A VALID MUTANT *** pattern occurs {n} times"
                )
                continue
            try:
                bad = mutant_is_valid(mut.target, tmpdir, mut.expect_probe)
                if bad:
                    failures.append(f"{mut.mid}: {bad}")
                    print(f"  {mut.mid:<32} *** MUTANT DID NOT RUN *** {bad}")
                    continue
                got = run_leg(mut.leg, tmpdir, str(dst.relative_to(FRONTEND)))
            finally:
                dst.unlink(missing_ok=True)
            flipped = sorted(
                cid for cid, r in got.items() if r != reference[mut.leg][cid]
            )
            expected = sorted(mut.flips)
            ok = flipped == expected
            if not ok:
                failures.append(
                    f"{mut.mid}: expected to flip {expected}, flipped {flipped}"
                )
            print(
                f"  {mut.mid:<32} "
                + (
                    f"flips {len(expected)}: {','.join(expected)}"
                    if ok
                    else f"*** WRONG CASES FLIPPED *** {flipped}"
                )
            )

        print("\nT4-R6: the ESLint leg's files: scope, proved four ways")
        print("-" * 78)
        failures += scope_proof()

        print("\nThe tree walk, which --scan cannot reach")
        print("-" * 78)
        failures += walk_proof(tmpdir)

        print("\nTask 8's precondition: the cross-file vocabulary, on the real tree")
        print("-" * 78)
        failures += crossfile_proof()

        print("\nThe prefilter's one hole, refused in both of its spellings")
        print("-" * 78)
        failures += reexport_refusal_proof(tmpdir)

        print("\nR5: clean-room, proved PER LEG rather than by an empty baseline")
        print("-" * 78)
        failures += cleanroom_proof(tmpdir)

        print("\nR4: the baseline counts occurrences rather than storing a set")
        print("-" * 78)
        failures += baseline_proof(tmpdir)
    finally:
        for leftover in (GATE_MUTANT, CFG_MUTANT, SCOPE_FIXTURE, C.ESLINT_FIXTURE):
            leftover.unlink(missing_ok=True)
        shutil.rmtree(tmpdir, ignore_errors=True)
        C.release_lock()

    print()
    if failures:
        print("SELFTEST: FAILURES")
        for f in failures:
            print("  " + f)
        return 1
    print(
        f"SELFTEST: all {len(MUTATIONS)} scan mutations and {len(WALK_MUTATIONS)} walk "
        "mutations ran and flipped exactly their own cases; the scope is proved four "
        "ways and names only real files; the baseline counts; the cross-file "
        "vocabulary reaches call sites in other modules and a single-file one does "
        "not; both spellings of a renaming re-export are refused and an ordinary "
        "type alias is not; every detector kind the gate emits fails a freshly "
        "introduced "
        "violation of its own shape and goes green when it is removed; --update "
        "leaves the retired baseline byte-identical; and both positive controls "
        "stayed silent on correct code"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
