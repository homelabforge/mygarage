#!/usr/bin/env bun
/**
 * Unit-system branch detection: the provenance-sensitive half of the unit gate.
 *
 * Phase 3a migrated a batch of call sites off `system === 'imperial'` ternaries
 * and onto `useUnitFormat()`. This exists so the next contributor cannot rebuild
 * TireList's ternary somewhere else and have nothing complain.
 *
 * ★ FOUR KINDS, AND WHAT THEY DELIBERATELY DO NOT COVER (plan 3b, criterion 2).
 * Phase 3b added three legs beside the original comparison one, because the
 * comparison leg sees a literal `'imperial'` or `'metric'` and three whole
 * defect shapes carry neither:
 *
 *   compare / switch-case  `system === 'imperial'`, the original leg.
 *   formatter-binary       a call to a static `UnitFormatter` method whose
 *                          parameter is a `UnitSystem`. Nothing at the call
 *                          site names a system; the binary decision happens
 *                          inside the callee.
 *   binary-conversion      a call to an exported helper whose parameter is a
 *                          `UnitSystem` and whose result is WRITTEN as
 *                          canonical (`toCanonicalKm(500, system)` stored 500
 *                          km for a `{volume:'L', distance:'mi'}` user, because
 *                          `system` collapses from volume). Task 5 deleted all
 *                          three such helpers from `decimalSafe.ts`; task 8
 *                          made the vocabulary TREE-WIDE and found three more
 *                          in `utils/supplyUnits.ts` with fifteen sites,
 *                          one of them a write. Read `deriveBinarySurface`.
 *   token-branch           `units.volume === 'L' ? km : miles`, which collapses
 *                          DISTANCE out of VOLUME with no system literal
 *                          anywhere.
 *
 * ★ And the category this gate deliberately DOES NOT detect, stated here so the
 * next person does not add it thinking it was forgotten: a resolved-set
 * function that collapses INTERNALLY. `formatVolume(units)` is correct and
 * `formatVolumePerDistance(units)` derives its distance half from
 * `units.volume`, and the two are CALL-SITE IDENTICAL. A name blacklist either
 * keeps rejecting the helper after somebody fixes it or misses the next one, so
 * that category belongs to `units.manifest.json`, which is reviewed rather than
 * matched. Forced-unit sites (`` `${liters} L` ``) have no lexical form at all
 * and belong there too.
 *
 * ★ THE TASK 8 PRECONDITION, CLOSED, AND WHAT CLOSING IT FOUND. Two gaps in the
 * `binary-conversion` leg were known, measured and deliberately left open by
 * task 5. Together they were the R8 defect class one module over, and the
 * clean-room flip could not ship while they were open, because that is the
 * moment this gate starts claiming completeness instead of recording a
 * baseline. Both are closed; the residuals each leaves are named, not implied.
 *
 *   1. CROSS-FILE WAS BLIND, AND IT WAS HIDING A LIVE POPULATION. The
 *      vocabulary came from `decimalSafe.ts` plus whatever the scanned file
 *      declared for itself, so a binary conversion helper declared in any other
 *      module and called from a DIFFERENT file produced zero findings in both.
 *      `deriveBinarySurface` now walks every module under `src/` that mentions
 *      the type. The first run turned up `utils/supplyUnits.ts`:
 *      `canonicalToDisplay`, `displayToCanonical` and `supplyUnitLabel`, all
 *      three taking the collapsed system, fifteen sites under eleven keys
 *      across five files, and `displayToCanonical` WRITES. They are ruled (R3, deferred pending
 *      the D8 amendment that would give supplies a resolved token) rather than
 *      repaired, and the ruling is recorded once at each declaration; see
 *      `declarationExempt` for why the pragma sits there and not on fifteen
 *      sites. RESIDUAL: the walk reads a text prefilter, whose one hole is
 *      an aliased re-export, and that is refused rather than tolerated.
 *
 *   2. THE PREDICATE MATCHED ANNOTATION TEXT EXACTLY. `takesBinarySystem`
 *      compared `p.type.getText().trim()` to the literal `'UnitSystem'`, so an
 *      aliased import (`import type { UnitSystem as Sys }`), a union
 *      (`UnitSystem | undefined`) and a props object holding
 *      `system: UnitSystem` all evaded it; three of the nineteen production
 *      declarations carrying the type were in those shapes, two of them live
 *      components on the supplies path. `typeIsBinarySystem` reads the
 *      annotation as a TYPE now: unions, intersections, parentheses, inline
 *      type literals, and named `type`/`interface` declarations the same file
 *      makes. RESIDUALS, both stated at that function and pinned from the far
 *      side by corpus case S-N18: a binary type inside a generic ARGUMENT
 *      (`Record<string, UnitSystem>`) is a container rather than a decision and
 *      is deliberately not matched, and a props type IMPORTED from another
 *      module is not resolved.
 *
 * ★ WHY THIS IS A SCRIPT AND NOT AN ESLINT SELECTOR (plan ruling R3).
 * `no-restricted-syntax` registers purely syntactic selectors against
 * individual nodes and performs no binding or data-flow analysis at all
 * (`node_modules/eslint/lib/rules/no-restricted-syntax.js`). So
 * `unitSystem === 'imperial'` and `theme === 'imperial'` are AST-identical
 * apart from the identifier's spelling, and the two things the gate must do
 * become mutually unsatisfiable in that engine: match on the literal and you
 * reject `theme`; match on the identifier and you miss `resolvedSystem`, which
 * is how `SettingsSystemTab.tsx:81` actually spells it. Deciding which one is a
 * unit system means resolving what the identifier refers to, so it lives here.
 *
 * The provenance-FREE half (raw conversion constants such as `1609.34`, where
 * a numeric literal means the same thing wherever it appears) stays in
 * `eslint.config.js`, which runs over `src/**` minus three named files.
 *
 * ★ CLEAN-ROOM SINCE PLAN 3b TASK 8. `units.baseline.json` is `[]`, so any
 * finding at all fails. The comparison is unchanged and still keyed by
 * occurrence COUNT rather than set membership (ruling R4), because an empty
 * allowed-map makes "the count rose above zero" and "there is a finding" the
 * same sentence, and keeping the mechanism keeps R4's own mutation able to fire.
 *
 * ★ THE SENTENCE THIS GATE NOW CLAIMS, and it is smaller than "no unit defect
 * exists": NO EXPRESSION UNDER `src/` MATCHES THE DETECTORS `FINDING_KINDS`
 * LISTS, EXCEPT AT THE SITES A `// units-exempt(<kind>):` PRAGMA NAMES, AND THE
 * RUN COUNTS BOTH THE DETECTORS AND THE EXEMPT SITES RATHER THAN NAMING A
 * NUMBER IN PROSE.
 * The phase's own promise is narrower still and is not restored here: all
 * mechanically enumerated modules were dispositioned at a reviewed snapshot, and
 * these named scenarios pass. Two whole defect shapes have no lexical form for
 * any detector to match (a resolved-set helper that collapses INTERNALLY, and a
 * forced-unit template) and are reviewed in `units.manifest.json` instead, which
 * is why the success line says what it says.
 *
 * ★ AND WHAT THE FLIP COST, stated rather than left to be discovered. The
 * manifest gate cross-checks its `<kind> xN (units gate baseline)` findings
 * against this baseline, so while the baseline had entries those findings were
 * held by TWO independent mechanisms. An empty baseline holds none, so every
 * manifest finding now rests on the drift rule alone; `validate-units-manifest.ts`
 * measures and prints that on every run. What survives is `baseline.invented`:
 * no row may claim a gate finding, because the gate has none.
 *
 * `--update` therefore refuses to write the default baseline. Its old failure
 * message used to recommend running it, so leaving it able to re-record would
 * make undoing the flip a one-word command with no diff in the gate at all.
 *
 * It is modelled on `validate-hardcoded-strings.ts`, with one deliberate
 * difference: that script stores `(file, kind, text)` in a `Set`, so
 * adding a SECOND identical `system === 'metric'` to a file that already has
 * one yields the same key and passes. Every key here carries a COUNT and the
 * gate fails when the count RISES. Line numbers stay out of the key so that
 * moving code does not invalidate the baseline.
 *
 * `--report` prints every finding grouped by file. It was phase 3b's work list
 * and is now a listing that should stay empty; it is kept because a gate whose
 * only output is a tick cannot show what it looked at, and because the same
 * command is what a contributor runs after it fails.
 *
 * Proven against a two-sided corpus (`scripts/units_gate_corpus.py`): positives
 * it must reject, including the destructuring rename and both real production
 * spellings, and negatives it must accept, including a module-local
 * `formatDistance` that is correct migrated code. How many of each is
 * deliberately not written here, for the same reason the baseline count is not:
 * the run prints it and a number in prose goes stale. This sentence used to say
 * "eleven positives and five negatives" while the file held thirty-six and
 * sixteen. Every case names a mutation in `scripts/units_gate_selftest.py` that
 * flips it, because a corpus case that passes identically whether or not the
 * rule exists is an assertion true at t=0 one level up. Run both after changing
 * anything below.
 *
 * Escape hatch: `// units-exempt(<kind>): <reason>` on the offending line or the
 * line above. Use it for a genuine non-display branch (parsing a stored legacy
 * key, a preset-selection control, resolved-set dispatch inside the unit layer),
 * never to silence a display conversion. The kind list is task 8's and is not
 * decoration: the bare `// units-exempt:` form silences EVERY kind on its line,
 * including one nobody had considered when they wrote the reason, and after the
 * clean-room flip this pragma is the only suppression the gate has left. On a
 * binary DECLARATION the kind is `binary-conversion` or `formatter-binary`, and
 * that one line silences every call site of it in every module: see
 * `declarationExempt`.
 *
 * Usage:
 *   bun run scripts/validate-units.ts                  # gate
 *   bun run scripts/validate-units.ts --update --baseline <p>   # rewrite THAT baseline
 *       (without --baseline it REFUSES and exits 2: the default one is retired)
 *   bun run scripts/validate-units.ts --report         # phase 3b work list
 *   bun run scripts/validate-units.ts --scan <file>    # JSON, one file (corpus)
 *   bun run scripts/validate-units.ts --baseline <p>   # use another baseline
 *   bun run scripts/validate-units.ts --src <dir>      # walk another tree (selftest)
 *   bun run scripts/validate-units.ts --derived        # print the derived sets
 *   bun run scripts/validate-units.ts --suppressions   # print every suppression
 *
 * ★ `--derived` also prints EXEMPT_BINARY_DECLARATIONS, and the gate's success
 * line counts them. One `// units-exempt:` on a binary declaration silences
 * every call site of it in every module, which no other use of the hatch does,
 * so the number is printed beside the tick rather than buried.
 * Exit code: 1 on any finding. `--update` without `--baseline` exits 2.
 */

import { createRequire } from 'module'
import { readdirSync, readFileSync, statSync, writeFileSync } from 'fs'
import { join, relative } from 'path'
import { ROOT } from './translation-utils'

/**
 * The real TypeScript compiler API, loaded the way Node's resolver would.
 *
 * ★ The precise hazard, because the first version of this comment described it
 * wrongly and a false rationale in a load-bearing comment is how the next
 * person deletes the guard. From inside `frontend/` a bare
 * `import ts from 'typescript'` resolves to the installed package and gives
 * 2248 keys, `createSourceFile` a function, version 6.0.3. Resolution follows
 * the importing file rather than the cwd, so that holds from any working
 * directory. What it does NOT survive is running with no `node_modules` tree
 * above the importing file at all: rather than failing, Bun answers the bare
 * specifier from its auto-install cache stub
 * (`~/.bun/install/cache/typescript@7.0.2@@@1/lib/version.cjs`), which exports
 * exactly `version` and `versionMajorMinor`. `createSourceFile` is then
 * `undefined` and every scan reports zero findings on a tree full of them.
 *
 * Both states were measured rather than assumed, because the first version of
 * this comment named the wrong trigger:
 *   - `node_modules` present, `typescript` missing from it: Bun throws
 *     MODULE_NOT_FOUND, so that state is loud on its own.
 *   - no `node_modules` at all (a CI job that skipped `bun install`, a script
 *     run from outside the tree): the stub answers, silently.
 * The second is not hypothetical. The Translations workflow deliberately
 * skipped `bun install` until this commit.
 *
 * ★ And the sting: the stub reports 7.0.2, NEWER than the installed 6.0.3, so
 * a version check would wave it through. Only an API check catches it. Hence
 * both halves below: resolve through the package's own `main` field rather
 * than the bare specifier, and assert the API before scanning anything.
 */
interface TsNode {
  kind: number
  parent?: TsNode
  text?: string
  left?: TsNode
  right?: TsNode
  operatorToken?: { kind: number }
  expression?: TsNode
  name?: TsNode
  type?: TsNode
  initializer?: TsNode
  /** Class and type-literal members, for the derivations below. */
  members?: TsNode[]
  /** Method and function parameters, likewise. */
  parameters?: TsNode[]
  /** Union and intersection members, for the widened binary-system predicate. */
  types?: TsNode[]
  /** A type reference's name, so `A.B` can be read without its arguments. */
  typeName?: TsNode
  /** An import specifier's ORIGINAL name when it was imported under an alias. */
  propertyName?: TsNode
  modifiers?: { kind: number }[]
  getText: (source?: TsSourceFile) => string
  getStart: (source?: TsSourceFile) => number
}

interface TsDiagnostic {
  messageText: string | { messageText: string }
  start?: number
}

interface TsSourceFile extends TsNode {
  getLineAndCharacterOfPosition: (pos: number) => { line: number; character: number }
  /**
   * Internal to the compiler and absent from its public typings, which is why
   * it is optional here and why `scanSource` treats "the property is missing"
   * as a reason to refuse rather than as an empty list.
   */
  parseDiagnostics?: TsDiagnostic[]
}

interface TsApi {
  SyntaxKind: Record<string, number>
  ScriptTarget: Record<string, number>
  ScriptKind: Record<string, number>
  createSourceFile: (
    name: string,
    text: string,
    target: number,
    setParents: boolean,
    kind: number,
  ) => TsSourceFile
  forEachChild: (node: TsNode, cb: (child: TsNode) => void) => void
}

function loadTypeScript(): TsApi {
  const require = createRequire(import.meta.url)
  const pkgDir = join(ROOT, 'node_modules', 'typescript')
  const main = JSON.parse(readFileSync(join(pkgDir, 'package.json'), 'utf-8')).main as string
  const api = require(join(pkgDir, main)) as TsApi
  if (typeof api.createSourceFile !== 'function' || !api.SyntaxKind?.BinaryExpression) {
    throw new Error(
      'typescript did not expose createSourceFile/SyntaxKind. The scanner would ' +
        'report zero findings for every file. Refusing to run.',
    )
  }
  return api
}

const ts = loadTypeScript()
const SRC_DIR = join(ROOT, 'src')
const DEFAULT_BASELINE = join(ROOT, 'scripts', 'units.baseline.json')

/** The two literals that name a unit system anywhere in this codebase. */
const SYSTEM_LITERALS = new Set(['imperial', 'metric'])

/**
 * Every string literal the unit-system union has ever contained.
 *
 * `'custom'` is in here because phase 1 widened the API-level preference union
 * to admit it, so `type Pref = 'imperial' | 'metric' | 'custom'` is a plausible
 * phase 3b artifact and it is unambiguously a unit-system type.
 */
const UNIT_VOCABULARY = new Set([
  "'imperial'",
  "'metric'",
  "'custom'",
  '"imperial"',
  '"metric"',
  '"custom"',
  // Backticks are the third spelling, and leaving them out was a FAIL-OPEN.
  // `type Sys = ` + '`imperial` | `metric`' + ` compiles clean under --strict and
  // scored zero findings, because STRING_LITERAL_TYPE below RECOGNISES a
  // backtick literal: the member was confidently classified `foreign` instead
  // of falling through to fail-closed `unknown`. The confident
  // misclassification was the bug, not the missing entry. One backtick member
  // was enough to exempt an otherwise correctly-spelled union.
  '`imperial`',
  '`metric`',
  '`custom`',
])

/**
 * Members that carry no value a unit comparison could be about.
 *
 * They are STRIPPED before the remaining members are judged, and that is the
 * whole of round 2's F2 regression: `'imperial' | 'metric' | null` was read as
 * "not every member is unit vocabulary, therefore foreign, therefore exempt",
 * and `UnitSystem | null` is this codebase's own `readStoredUnitSystem` return
 * type. A nullable unit system is a unit system.
 */
const NULLISH_MEMBERS = new Set(['null', 'undefined', 'void', 'never'])

/** A round-1 denylist of NAMES (`UnitSystem|string|any|unknown`) used to sit
 * here. It is gone, not moved: every one of those names is a bare identifier
 * that resolves to no local type alias, and an unresolvable identifier is
 * already classified UNKNOWN and refused an exemption. Keeping the list would
 * have been a guard no mutation could kill, which this phase has now twice
 * ruled is a survivor wearing a guard's name. Verified by corpus cases S-P9,
 * S-P11, S-P12, S-P23 and S-P24, all of which still fail without it. */

const EQUALITY_KINDS = new Set([
  ts.SyntaxKind.EqualsEqualsEqualsToken,
  ts.SyntaxKind.ExclamationEqualsEqualsToken,
  ts.SyntaxKind.EqualsEqualsToken,
  ts.SyntaxKind.ExclamationEqualsToken,
])

const LITERAL_KINDS = new Set([
  ts.SyntaxKind.StringLiteral,
  ts.SyntaxKind.NoSubstitutionTemplateLiteral,
])

/**
 * The escape hatch. It must carry a reason, and it may name the kinds it covers.
 *
 * Round 1 tested `line.includes('units-exempt')`, so a bare marker with no
 * justification silenced a finding while the docstring and the failure message
 * both promised "with the reason". Requiring the comment introducer and a
 * colon also stops the marker matching inside an ordinary string literal.
 *
 * ★ THE OPTIONAL KIND LIST IS TASK 8'S, AND THE OBJECTION IT ANSWERS IS ON THE
 * RECORD. `units.manifest.json` asked for the three `SettingsSystemTab`
 * comparisons to be exempted "structurally or by exact match in the gate rather
 * than with a reason-bearing pragma, which silences anything", and it was right
 * about the pragma: `// units-exempt: reason` silenced every kind on its line,
 * including a kind nobody had thought about when they wrote it. That matters
 * far more after the clean-room flip, because the pragma is then the ONLY
 * suppression left.
 *
 * `// units-exempt(compare): reason` silences the comparison leg on that line
 * and nothing else, so a token branch added beside it is still reported. The
 * bare form still means every kind and is kept for a site that genuinely wants
 * it; nothing in `src/` uses it any more.
 *
 * ★ WHY NOT the exact-match table the manifest offered as the alternative: a
 * table of (file, kind, text) inside the gate is a baseline under another name,
 * with the same failure mode the flip exists to remove. It sits away from the
 * code it excuses, and a future `--update` can regenerate it. A pragma sits on
 * the line, carries its reason into the diff, and cannot be regenerated by
 * anything.
 */
const EXEMPT_PRAGMA = /(?:^|\s)\/\/\s*units-exempt(?:\(([^)]*)\))?:\s*\S/

/** True when one line's pragma covers this finding kind. */
function lineExempts(line: string, kind: string): boolean {
  // ★ A LINE THAT MERELY MENTIONS THE PRAGMA IS NOT ONE. `EXEMPT_PRAGMA` allows
  // any whitespace before the `//`, so a JSDoc continuation line DESCRIBING the
  // hatch exempted whatever came after it. `utils/units.ts` has two such lines
  // and they were inert only because a backtick happens to sit before the `//`
  // in both, which is luck rather than a rule. A `*` in the leading whitespace
  // is a block comment's continuation and cannot be a line comment.
  if (/^\s*\*/.test(line)) return false
  const match = EXEMPT_PRAGMA.exec(line)
  if (match === null) return false
  const scope = match[1]
  if (scope === undefined) return true
  return scope.split(',').map((k) => k.trim()).includes(kind)
}

/**
 * True when a line, or the line above it, exempts this kind with a reason.
 *
 * One rule, two callers: `record()` uses it on the line a finding sits on, and
 * `declarationExempt` uses it on the line a declaration starts on. Keeping it
 * as one function is what stops the two drifting into two different escape
 * hatches with one name.
 */
function exemptedAtLine(lines: string[], line: number, kind: string): boolean {
  return lineExempts(lines[line - 1] ?? '', kind) || lineExempts(lines[line - 2] ?? '', kind)
}

/**
 * The WHOLE text of a parsed source, as lines.
 *
 * ★ NOT `source.getText()`, and the difference is not cosmetic. `getText()` on
 * a node returns the text from its `getStart()` to its end, and a SourceFile's
 * start is AFTER its leading trivia, so on a module opening with a docstring it
 * silently returns fewer lines than the file has: `supplyUnits.ts` gave 82 for
 * a 140-line file. Every line lookup was then off by the size of the header and
 * two of the three declaration exemptions below did not fire, while the third
 * did, which is the shape of bug that gets shipped. `text` is the source's own
 * full string and is checked rather than defaulted, because a build that did
 * not expose it would put the offset back without a word.
 */
function sourceLines(source: TsSourceFile): string[] {
  if (typeof source.text !== 'string') {
    throw new Error(
      'this TypeScript build exposes no SourceFile.text, so the line lookup behind ' +
        'every `// units-exempt:` pragma would silently read the wrong lines. Refusing ' +
        'to run.',
    )
  }
  return source.text.split('\n')
}

/**
 * True when a binary DECLARATION is exempted where it is declared.
 *
 * ★ THIS ONE PRAGMA SILENCES A CALL-SITE POPULATION IN OTHER FILES, which is
 * unlike every other use of the hatch and is the reason it is spelled out here
 * rather than folded in quietly. Task 8 made the conversion and formatter
 * vocabularies TREE-WIDE, so `supplyUnits.ts`'s three exported helpers stopped
 * being invisible and their fifteen sites across five files became findings in
 * one step. Those fifteen are one ruling (R3, deferred pending the
 * D8 amendment that would give supplies a resolved token), and one ruling
 * belongs at one site. Marking the DECLARATION keeps the reason where the
 * decision was actually made, and deleting that one line lights them all back
 * up.
 *
 * The cost is real and is not hidden: the gate's success line prints how many
 * declarations are exempted this way, and `--derived` names them, so the hatch
 * cannot grow without the number moving.
 *
 * The pragma must sit on the declaration's own first line or the line directly
 * above it, which for a documented export means between the closing `*\/` and
 * the `export` keyword.
 */
function declarationExempt(
  node: TsNode,
  source: TsSourceFile,
  lines: string[],
  kind: string,
): boolean {
  const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1
  return exemptedAtLine(lines, line, kind)
}

// ---------------------------------------------------------------------------
// Derived vocabularies (plan 3b ruling R8, and exit criterion 2)
// ---------------------------------------------------------------------------
/**
 * ★ EVERY SET BELOW IS DERIVED FROM THE REAL SOURCE, NEVER TRANSCRIBED.
 *
 * Round 1 of this workstream hand-counted "about 21 binary formatter calls
 * across nine files". Round 2 asked the AST and got 73 calls across 18 files.
 * The hand count was not merely low: it was low in a SHAPED way, because a
 * human enumerating "formatters" writes down the `format*` methods and forgets
 * the label selectors (`getDistanceUnit`, `getFuelEconomyUnit`,
 * `getCostPerDistanceLabel`), which take the same binary `UnitSystem` and are
 * just as wrong for a `{volume:'L', distance:'mi'}` user. So the rule here is
 * structural rather than lexical: **a method is binary when one of its
 * parameters is a `UnitSystem`**, whatever it is called.
 *
 * The same reasoning applies one file over. `toCanonicalKm`, `toCanonicalKg`
 * and `toCanonicalMeters` were binary unit APIs that WROTE canonical values
 * (R8); task 5 deleted all three, and a `toCanonicalFathoms` added next month
 * would be invisible to a transcribed list on the day it lands. Deriving is
 * what makes the successor findable rather than the predecessors, which is
 * exactly why the derivation outlives the names that motivated it.
 *
 * Each derivation is fail-loud when it comes back empty, for the same reason
 * `loadTypeScript` is: a detector whose vocabulary is empty reports zero
 * findings on a tree full of them, and a gate that cannot fire is worse than
 * no gate because it is believed.
 *
 * ★ ONE EXCEPTION, and it is stated here rather than only at its own function
 * because the sentence above is the one a reader trusts. R8's conversion
 * vocabulary may legitimately be EMPTY: task 5 deleted the last binary
 * conversion helper, so zero findings is the truth and not a blindness. That
 * derivation therefore fails loud on the walk coming back with no exported
 * function AT ALL, which still separates a broken derivation from a finished
 * migration. Read `deriveBinaryConversionHelpers` before changing it.
 */
const UNITS_SOURCE = join(SRC_DIR, 'utils', 'units.ts')
const CONVERSION_SOURCE = join(SRC_DIR, 'utils', 'decimalSafe.ts')
const QUANTITY_SOURCE = join(SRC_DIR, 'types', 'units.ts')
const SCHEMA_SOURCE = join(SRC_DIR, 'types', 'api.generated.ts')

/** The binary type whose presence in a signature makes an API binary. */
const BINARY_SYSTEM_TYPE = 'UnitSystem'

/** The class whose static surface the formatter leg watches. */
const FORMATTER_CLASS = 'UnitFormatter'

function parseForDerivation(path: string): TsSourceFile {
  let text: string
  try {
    text = readFileSync(path, 'utf-8')
  } catch {
    throw new Error(
      `${relative(ROOT, path)} is missing, so the vocabulary derived from it would ` +
        'be empty and the detector that uses it would report zero findings. Refusing to run.',
    )
  }
  return ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
}

function requireNonEmpty<T>(values: Set<T>, what: string, where: string): Set<T> {
  if (values.size === 0) {
    throw new Error(
      `derived no ${what} from ${relative(ROOT, where)}. The matching detector would ` +
        'report zero findings for every file, which this gate would report as clean. ' +
        'Refusing to run. Fix the source, or fix the derivation.',
    )
  }
  return values
}

function isStatic(node: TsNode): boolean {
  return (node.modifiers ?? []).some((m) => m.kind === ts.SyntaxKind.StaticKeyword)
}

function isExported(node: TsNode): boolean {
  return (node.modifiers ?? []).some((m) => m.kind === ts.SyntaxKind.ExportKeyword)
}

/**
 * Every local spelling of the binary system type, plus the file's own type names.
 *
 * ★ TASK 8 PRECONDITION, HALF 2. Until this existed `takesBinarySystem`
 * compared `p.type.getText().trim()` to the literal `'UnitSystem'`, so three
 * shapes evaded it and three of the nineteen production declarations carrying
 * the type were already in them:
 *
 *   import type { UnitSystem as Sys }   an aliased import
 *   system: UnitSystem | undefined      a union
 *   ({ system }: LedgerRowProps)        a props object, named or inline
 *
 * The third is the one that mattered: `SupplyHistoryModal.tsx` spells it three
 * times, twice as an inline type literal and once through a named interface,
 * and `ServiceVisitForm.tsx` once more. A predicate that reads only the
 * annotation's own text cannot see any of them.
 *
 * `names` holds the spellings that MEAN the binary type here: the type's own
 * name, every alias an import gave it, and every local `type X = UnitSystem`.
 * `local` holds this file's `type` and `interface` bodies so a parameter
 * annotated with a props type can be resolved to the members it declares.
 */
interface BinaryTypeContext {
  names: Set<string>
  local: Map<string, TsNode>
}

/** The last segment of a type reference's name, so `U.UnitSystem` reads as `UnitSystem`. */
function referenceName(type: TsNode, source: TsSourceFile): string | null {
  if (type.kind !== ts.SyntaxKind.TypeReference) return null
  const text = (type.typeName ?? type).getText(source).trim()
  const last = text.split('.').pop() ?? ''
  return last.length > 0 ? last : null
}

function binaryTypeContext(source: TsSourceFile): BinaryTypeContext {
  const names = new Set<string>([BINARY_SYSTEM_TYPE])
  const local = new Map<string, TsNode>()
  const aliasBodies = new Map<string, TsNode>()
  const walk = (node: TsNode): void => {
    if (node.kind === ts.SyntaxKind.ImportSpecifier) {
      const original = (node.propertyName ?? node.name)?.text ?? ''
      const localName = node.name?.text ?? ''
      if (original === BINARY_SYSTEM_TYPE && localName.length > 0) names.add(localName)
    }
    if (node.kind === ts.SyntaxKind.TypeAliasDeclaration && node.name?.text && node.type) {
      local.set(node.name.text, node.type)
      aliasBodies.set(node.name.text, node.type)
    }
    if (node.kind === ts.SyntaxKind.InterfaceDeclaration && node.name?.text) {
      local.set(node.name.text, node)
    }
    ts.forEachChild(node, walk)
  }
  walk(source)
  // `type Sys = UnitSystem` is a third spelling, and it can chain. Iterate to a
  // fixpoint rather than one hop, with a bound so a cycle terminates.
  for (let pass = 0; pass < 8; pass += 1) {
    let grew = false
    for (const [name, body] of aliasBodies) {
      if (names.has(name)) continue
      const referenced = referenceName(body, source)
      if (referenced !== null && names.has(referenced)) {
        names.add(name)
        grew = true
      }
    }
    if (!grew) break
  }
  return { names, local }
}

/**
 * True when a type annotation names the binary system type ANYWHERE inside it.
 *
 * ★ WHAT IS DELIBERATELY OUT, stated rather than left to be discovered:
 * generic type ARGUMENTS (`Record<string, UnitSystem>`), array and tuple
 * element types, and indexed accesses (`Props['system']`). Each of them is a
 * container of the type rather than a parameter that decides on one, and
 * widening to them would make `(rows: Map<string, UnitSystem>)` a binary API,
 * which it is not. None of the nineteen production declarations is in one of
 * those shapes; a helper that hides a `UnitSystem` inside a generic argument
 * would still evade this, and that is the residual.
 *
 * Props objects ARE in, both inline and through a named `type`/`interface`
 * declared in the same file: that is the shape two live components on the
 * supplies path already use, and a React component taking `{ system }` decides
 * on it exactly as a positional parameter would. A props type IMPORTED from
 * another module is not resolved, and is the second residual.
 *
 * ★ AND THE OTHER TWO IN THE SAME LIST, because a residual list split across
 * two functions is half an inventory. `helperDeclarationsIn` does not collect a
 * class property arrow (`class C { convert = (v, s: UnitSystem) => ... }`) or an
 * object-literal method (`{ conv(v, s: UnitSystem) {...} }`); see its docstring
 * for why they are stated rather than closed. Four residuals, then, and none of
 * them has an instance under `src/`.
 */
function typeIsBinarySystem(
  type: TsNode | undefined,
  source: TsSourceFile,
  ctx: BinaryTypeContext,
  depth = 0,
  seen: Set<string> = new Set(),
): boolean {
  if (type === undefined || depth > 8) return false
  if (type.kind === ts.SyntaxKind.UnionType || type.kind === ts.SyntaxKind.IntersectionType) {
    return (type.types ?? []).some((t) => typeIsBinarySystem(t, source, ctx, depth + 1, seen))
  }
  if (type.kind === ts.SyntaxKind.ParenthesizedType) {
    return typeIsBinarySystem(type.type, source, ctx, depth + 1, seen)
  }
  if (
    type.kind === ts.SyntaxKind.TypeLiteral ||
    type.kind === ts.SyntaxKind.InterfaceDeclaration
  ) {
    return (type.members ?? []).some((m) =>
      typeIsBinarySystem(m.type, source, ctx, depth + 1, seen),
    )
  }
  if (type.kind === ts.SyntaxKind.TypeReference) {
    const name = referenceName(type, source)
    if (name === null) return false
    if (ctx.names.has(name)) return true
    if (seen.has(name)) return false
    const body = ctx.local.get(name)
    if (body === undefined) return false
    seen.add(name)
    return typeIsBinarySystem(body, source, ctx, depth + 1, seen)
  }
  return ctx.names.has(type.getText(source).trim())
}

function takesBinarySystem(
  node: TsNode,
  source: TsSourceFile,
  ctx: BinaryTypeContext,
): boolean {
  return (node.parameters ?? []).some((p) => typeIsBinarySystem(p.type, source, ctx))
}

/**
 * The binary type itself still exists, checked DIRECTLY rather than by accident.
 *
 * ★ THE HOLE THIS CLOSES, found in task 5's review and owned by nobody. Every
 * vocabulary below is derived by `takesBinarySystem`, which compares an
 * annotation's TEXT to the literal `'UnitSystem'`. Rename that type and all of
 * them come back empty at once: the formatter leg loses its vocabulary, the
 * conversion leg loses its, and both detectors then report zero findings on a
 * tree full of them while this gate prints a tick.
 *
 * Today `deriveBinaryFormatterMethods` catches that as a SIDE EFFECT, because
 * `requireNonEmpty` refuses when its own set comes back empty. That cover is
 * temporary by construction. The formatter surface shrinks with every task that
 * migrates its call sites (task 2 retired seven, task 3 one, task 6 two more),
 * and on the day the last one goes, an empty set becomes the TRUTH rather than
 * a symptom, `requireNonEmpty` has to go with it exactly as it already did for
 * the conversion leg, and the rename becomes invisible. A task whose action
 * removes a check supplies its replacement, so the replacement lands now rather
 * than on the day the window opens.
 *
 * It costs one walk and it does not expire.
 */
function requireBinarySystemType(): void {
  const source = parseForDerivation(UNITS_SOURCE)
  let declared = false
  const walk = (node: TsNode): void => {
    if (
      node.kind === ts.SyntaxKind.TypeAliasDeclaration &&
      node.name?.text === BINARY_SYSTEM_TYPE
    ) {
      declared = true
    }
    ts.forEachChild(node, walk)
  }
  walk(source)
  if (!declared) {
    throw new Error(
      `${relative(ROOT, UNITS_SOURCE)} declares no type named ${BINARY_SYSTEM_TYPE}. ` +
        'Every vocabulary this gate derives is matched by that annotation, so all of ' +
        'them would come back empty and every binary leg would report zero findings on ' +
        'a tree full of them. Refusing to run. If the type was renamed, rename ' +
        'BINARY_SYSTEM_TYPE with it; if it is gone, the binary legs are gone too and ' +
        'should be deleted rather than left silently reporting nothing.',
    )
  }
}

/**
 * The static methods one source declares on a class, split by shape.
 *
 * `binary` is the formatter vocabulary; `statics` is everything the walk
 * visited, which is what lets an empty `binary` be told apart from a walk that
 * ran over nothing. Exactly the receipt `conversionHelpersIn` returns one leg
 * over, and it is here for the same reason.
 *
 * ★ `onlyClass` is what separates the two callers. The DERIVATION reads the
 * production `UnitFormatter` and nothing else, because that is the class whose
 * surface ruling R2 governs. A SCANNED FILE contributes any class it declares
 * for itself, mirroring the conversion leg's `conversionHelpersIn(sf)`: a
 * method taking a `UnitSystem` is a binary formatter API whatever its class is
 * called, and a file that declares one and calls it is making the D8-collapsed
 * decision inside its own module where nothing else can see it.
 *
 * ★ INSTANCE METHODS COUNT SINCE FIX ROUND 1. The walk required
 * `StaticKeyword`, which was the formatter leg's half of the same floor the
 * conversion leg had: `this.format(km, system)` is the identical decision and
 * the leg's receiver requirement already matches it. Nothing in `src/` declares
 * one today, and that is the point of closing it now rather than on the day one
 * lands.
 */
function formatterMethodsIn(
  source: TsSourceFile,
  onlyClass: string | null,
): { binary: Set<string>; statics: Set<string>; exempt: Set<string> } {
  const ctx = binaryTypeContext(source)
  const lines = sourceLines(source)
  const binary = new Set<string>()
  const statics = new Set<string>()
  const exempt = new Set<string>()
  const walk = (node: TsNode): void => {
    if (
      node.kind === ts.SyntaxKind.ClassDeclaration &&
      (onlyClass === null || node.name?.text === onlyClass)
    ) {
      for (const member of node.members ?? []) {
        if (member.kind !== ts.SyntaxKind.MethodDeclaration) continue
        if (!member.name) continue
        // `statics` stays STATIC-only: it is the receipt over the surface
        // ruling R2 governs, and `requireNonEmpty` guards it. `binary` covers
        // instance methods too, because `this.format(x, system)` is the same
        // D8-collapsed decision as `C.format(x, system)` and the leg's
        // receiver requirement already matches both.
        if (isStatic(member)) statics.add(member.name.getText(source))
        if (!takesBinarySystem(member, source, ctx)) continue
        if (declarationExempt(member, source, lines, 'formatter-binary'))
          exempt.add(member.name.getText(source))
        else binary.add(member.name.getText(source))
      }
    }
    ts.forEachChild(node, walk)
  }
  walk(source)
  return { binary, statics, exempt }
}

/**
 * Every static `UnitFormatter` method that decides on a binary `UnitSystem`.
 *
 * ★ THIS SET IS EMPTY TODAY, AND EMPTY IS THE GOAL STATE RATHER THAN A BROKEN
 * DERIVATION. Plan 3b task 7 migrated the last two call sites of the last two
 * such methods, `unitsBinaryApiSurface.test.ts` reported both as dead exactly
 * as designed, and they went. So `requireNonEmpty` guards `statics`, not
 * `binary`: the walk still has to come back holding the static methods
 * `UnitFormatter` does declare (`formatVolume`, `getVolumeUnit` and the rest),
 * which is what a gutted file or a changed AST shape would fail. This is the
 * same move `deriveBinaryConversionHelpers` made when task 5 emptied ITS
 * vocabulary, and the docstring one function up predicted the day it would be
 * needed: "on the day the last one goes, an empty set becomes the TRUTH rather
 * than a symptom, and `requireNonEmpty` has to go with it".
 *
 * The other way `binary` could empty is `BINARY_SYSTEM_TYPE` ceasing to match,
 * and that is checked directly by `requireBinarySystemType`, which runs before
 * either derivation and does not expire.
 */
function deriveBinaryFormatterMethods(): Set<string> {
  const { binary, statics } = formatterMethodsIn(parseForDerivation(UNITS_SOURCE), FORMATTER_CLASS)
  requireNonEmpty(statics, `static ${FORMATTER_CLASS} method`, UNITS_SOURCE)
  return binary
}

/**
 * Every module under `src/` that could possibly DECLARE a binary unit API.
 *
 * ★ A TEXT PREFILTER, AND WHY IT IS SOUND RATHER THAN A SHORTCUT. Parsing all
 * 337 production modules costs 221 ms, which the gate could afford once but the
 * corpus cannot: it runs `--scan` 53 times and the selftest runs the corpus
 * once per mutation, so a full parse per invocation adds roughly fourteen
 * minutes to a run that already takes eleven. The prefilter costs 3 ms and
 * keeps 8 files.
 *
 * It is sound because the binary type has exactly ONE declaration site
 * (`utils/units.ts`, and `supplyUnits.ts`'s header records the commit that
 * deleted the second copy), so any module declaring a parameter of that type
 * must name the identifier to import it: directly, under an alias
 * (`import type { UnitSystem as Sys }`, whose import line still spells it), or
 * through a namespace (`U.UnitSystem`, likewise).
 *
 * ★ THE ONE HOLE, CLOSED BY REFUSAL RATHER THAN BY HOPE. An ALIASED RE-EXPORT
 * (`export type { UnitSystem as Sys } from './units'`) would let the next
 * module import `Sys` while containing no occurrence of the real name, and the
 * prefilter would skip it silently. So the walk refuses when it sees one. A
 * plain re-export is fine: its consumers still spell the original name.
 */
function binaryDeclarationSources(): string[] {
  return walkDir(SRC_DIR).filter((path) => readFileSync(path, 'utf-8').includes(BINARY_SYSTEM_TYPE))
}

/** What one tree-wide walk of the binary declaration surface found. */
interface BinarySurface {
  /** Static methods, on any class, taking a binary system: the formatter leg. */
  formatters: Set<string>
  /** Exported function declarations taking one: the R8 conversion leg. */
  helpers: Set<string>
  /**
   * Every declaration a reason-bearing pragma removed, as `path::name`.
   *
   * ★ PER DECLARATION, NOT PER NAME, and the difference bit once already. The
   * first version of this was a name-keyed Set because the VOCABULARY is one,
   * so `formatQuantity` declared in both `SupplyHistoryModal.tsx` and
   * `SuppliesUsedTab.tsx` collapsed to a single entry and the success line said
   * 11 where 12 declarations carry a pragma. A census is a count of things, not
   * of their spellings.
   */
  exemptSites: string[]
  /**
   * The exempt names another module could reach: what a call site elsewhere
   * would have to match for the hatch to be hiding it.
   */
  exemptExported: Set<string>
  /** The walk's own receipt: how many modules the prefilter kept. */
  files: number
}

/**
 * The binary unit API declared ANYWHERE under `src/`, not just in two files.
 *
 * ★ THIS IS TASK 8'S PRECONDITION, HALF 1, AND WHAT IT FOUND. Until now the
 * conversion vocabulary was derived from `decimalSafe.ts` alone plus whatever
 * the scanned file declared for itself, so a binary conversion helper declared
 * in any OTHER module and called from a DIFFERENT file produced zero findings
 * in both. Task 5 emptied `decimalSafe.ts`, which left that leg with no
 * population at all and made the blindness total.
 *
 * Closing it surfaced a live one immediately: `utils/supplyUnits.ts` exports
 * `canonicalToDisplay`, `displayToCanonical` and `supplyUnitLabel`, all three
 * taking the collapsed `UnitSystem`, with fifteen sites under eleven keys
 * across five files, and `displayToCanonical` is a WRITE. That is R8's defect class one module
 * over, exactly as the precondition predicted, and it was invisible to every
 * leg of this gate for the whole of phase 3b. It is ruled (R3, deferred
 * pending the D8 amendment) rather than repaired, and the ruling is recorded
 * at the three declarations with `// units-exempt:` so the fifteen sites do
 * not each need their own copy of it. See `declarationExempt`.
 *
 * The formatter leg gets the same widening in the same walk. It adds nothing
 * today (no class outside `units.ts` declares a static binary method), and
 * that is the point: the hole was symmetric and closing only the half with a
 * population is how the other half becomes next year's finding.
 */
function deriveBinarySurface(): BinarySurface {
  const formatters = new Set<string>()
  const helpers = new Set<string>()
  const exemptExported = new Set<string>()
  const exemptSites: string[] = []
  const paths = binaryDeclarationSources()
  for (const path of paths) {
    const source = parseForDerivation(path)
    refuseAliasedReExport(source, path)
    const rel = relative(ROOT, path)
    const methods = formatterMethodsIn(source, null)
    for (const name of methods.binary) formatters.add(name)
    for (const name of methods.exempt) {
      // A class member is reachable through any receiver, so it counts as
      // exported for the purpose of "what could a call site elsewhere match".
      exemptExported.add(name)
      exemptSites.push(`${rel}::${name}`)
    }
    const functions = conversionHelpersIn(source)
    // Exported only: a module-local helper cannot be called from another file,
    // and its NAME is not unique across the tree. `scanSource` adds the scanned
    // file's own locals; see `conversionHelpersIn`.
    for (const name of functions.exportedBinary) helpers.add(name)
    for (const name of functions.exempt) exemptSites.push(`${rel}::${name}`)
    for (const name of functions.exemptExported) exemptExported.add(name)
  }
  if (paths.length === 0) {
    throw new Error(
      `no module under ${relative(ROOT, SRC_DIR)} mentions ${BINARY_SYSTEM_TYPE}, so the ` +
        'tree-wide binary vocabulary would be empty and both binary legs would report ' +
        'zero findings for every file. Refusing to run: the type is declared in ' +
        `${relative(ROOT, UNITS_SOURCE)}, so at minimum that module must be here.`,
    )
  }
  return { formatters, helpers, exemptExported, exemptSites: exemptSites.sort(), files: paths.length }
}

/**
 * Refuse an aliased re-export of the binary type, which would blind the prefilter.
 *
 * `export type { UnitSystem as Sys } from './units'` is legal and would make
 * `binaryDeclarationSources` skip every module importing `Sys`, silently. The
 * codebase has none today and `supplyUnits.ts`'s header explains why it must
 * not gain one; this is that prose made executable.
 */
function refuseAliasedReExport(source: TsSourceFile, path: string): void {
  // ★ TWO SPELLINGS, AND THE SECOND IS THE IDIOMATIC ONE. Until fix round 1
  // this walked `ExportSpecifier` only, so it covered
  // `export type { UnitSystem as Sys } from './units'` and missed
  // `export type Sys = UnitSystem`, which is a TypeAliasDeclaration and is what
  // anybody would actually write. A three-file chain through the alias passed
  // the gate with exit 0: the prefilter skips both modules because neither
  // spells the real name, and `binaryTypeContext` would not have resolved `Sys`
  // even without the prefilter, since it only follows import specifiers whose
  // ORIGINAL name matches. `names` below is that same fixpoint alias walk, so
  // the resolution is shared rather than reimplemented.
  const names = binaryTypeContext(source).names
  const refuse = (exposed: string, how: string): never => {
    throw new Error(
      `${relative(ROOT, path)} ${how} ${BINARY_SYSTEM_TYPE} as ${exposed}. A module ` +
        `importing ${exposed} would never spell ${BINARY_SYSTEM_TYPE}, so the text ` +
        'prefilter in binaryDeclarationSources would skip it and any binary API it ' +
        'declares would be invisible to both binary legs. Refusing to run. Import the ' +
        'type from where it is declared, or drop the prefilter and parse the whole tree.',
    )
  }
  const walk = (node: TsNode): void => {
    if (node.kind === ts.SyntaxKind.ExportSpecifier) {
      const original = (node.propertyName ?? node.name)?.text ?? ''
      const exposed = node.name?.text ?? ''
      if (original === BINARY_SYSTEM_TYPE && exposed !== BINARY_SYSTEM_TYPE) {
        refuse(exposed, 're-exports')
      }
    }
    if (node.kind === ts.SyntaxKind.TypeAliasDeclaration && isExported(node)) {
      const exposed = node.name?.text ?? ''
      // `names` holds every local spelling that RESOLVES to the binary type,
      // chains included, and the type's own declaration is not a re-export.
      if (exposed !== BINARY_SYSTEM_TYPE && names.has(exposed)) {
        refuse(exposed, 'exports a type alias of')
      }
    }
    ts.forEachChild(node, walk)
  }
  walk(source)
}

/**
 * True when a value declaration is exported, including `export const f = ...`.
 *
 * A `const` carries its `export` on the enclosing VariableStatement, two levels
 * above the VariableDeclaration, so asking the declaration itself always
 * answered no. 52 exported arrow consts exist under `src/` today.
 */
function isExportedDeclaration(node: TsNode): boolean {
  if (isExported(node)) return true
  const statement = node.parent?.parent
  return statement !== undefined && isExported(statement)
}

/** One named function-like value declaration, and where its pragma may sit. */
interface HelperDeclaration {
  name: string
  /** The node carrying the parameter list. */
  signature: TsNode
  /** The node whose first line a `// units-exempt(...)` may sit on or above. */
  anchor: TsNode
  exported: boolean
}

/**
 * The function declarations and function-valued consts one source declares.
 *
 * ★ THAT SENTENCE IS THE POPULATION, AND IT USED TO READ "every named
 * function-like value declaration", which this is not. The walk takes a
 * `FunctionDeclaration` and a `VariableDeclaration` whose initialiser is an
 * arrow or a function expression, and TWO NAMED FUNCTION-LIKE VALUE
 * DECLARATIONS FALL OUTSIDE IT, neither of which `formatterMethodsIn` catches
 * either, because that requires a `MethodDeclaration` inside a
 * `ClassDeclaration`:
 *
 *   class C { convert = (v: number, s: UnitSystem) => ... }   a PropertyDeclaration
 *   const helpers = { conv(v: number, s: UnitSystem) {...} }  a method outside a class
 *
 * Both are measured, not reasoned: the gate exits 0 on each. They are STATED
 * here rather than closed, and the reasoning is the same one that keeps generic
 * type arguments out of `typeIsBinarySystem`: neither spelling exists anywhere
 * under `src/` today, so widening buys no live coverage, and a widening carries
 * a corpus case and a mutation with it. Read this residual list with
 * `typeIsBinarySystem`'s two; together they are the honest population.
 *
 * ★ A docstring naming a population that is a floor, in the function whose
 * whole subject is that defect, is why the first line above states a RULE
 * narrow enough to be true instead of a claim wide enough to be wrong.
 *
 * ★ THE FLOOR THIS REPLACES, AND IT WAS THE PHASE'S SIGNATURE DEFECT AGAIN.
 * Until fix round 1 this walked `FunctionDeclaration` gated on `isExported`, so
 * three spellings of one decision never entered the vocabulary and NEITHER the
 * call leg nor the value-reference leg could report them: a module-local
 * `function`, an exported arrow or function-expression const, and (one leg
 * over) an instance method. FIVE were live on the supplies path at the time,
 * carrying ten call sites, and two of them are the exact lines task 8's report
 * celebrated catching through the value-reference leg: the gate saw the fourth
 * ARGUMENT of `convertSupplyUsages` and could not see `convertSupplyUsages`,
 * which is the local binary helper that consumes it.
 *
 * By this gate's own rule, a shape that is the same decision spelled
 * differently gets closed:
 * `function formatMagnitude(v, s, system: UnitSystem)` is character-identical
 * to `export function canonicalToDisplay(v, t, system: UnitSystem)` minus one
 * keyword.
 */
function helperDeclarationsIn(source: TsSourceFile): HelperDeclaration[] {
  const found: HelperDeclaration[] = []
  const walk = (node: TsNode): void => {
    if (node.kind === ts.SyntaxKind.FunctionDeclaration && node.name) {
      found.push({
        name: node.name.getText(source),
        signature: node,
        anchor: node,
        exported: isExportedDeclaration(node),
      })
    }
    if (
      node.kind === ts.SyntaxKind.VariableDeclaration &&
      node.name?.kind === ts.SyntaxKind.Identifier &&
      node.initializer !== undefined &&
      (node.initializer.kind === ts.SyntaxKind.ArrowFunction ||
        node.initializer.kind === ts.SyntaxKind.FunctionExpression)
    ) {
      found.push({
        name: node.name.getText(source),
        signature: node.initializer,
        // The pragma goes above `export const f = ...`, so the anchor is the
        // STATEMENT when there is one: `node.getStart()` lands on `f`, which is
        // the same line only while the spelling stays on one line.
        anchor: node.parent?.parent ?? node,
        exported: isExportedDeclaration(node),
      })
    }
    ts.forEachChild(node, walk)
  }
  walk(source)
  return found
}

/**
 * The binary conversion helpers one source declares, split by reach.
 *
 * ★ EXPORTED AND LOCAL ARE KEPT APART ON PURPOSE, and it is not tidiness. The
 * vocabulary is keyed by NAME and the legs match an identifier's text, so
 * putting a module-LOCAL `formatQuantity` into the tree-wide set would flag an
 * unrelated `formatQuantity` in another module. A local helper can only be
 * called where it is declared, and `scanSource` parses that file anyway, so
 * locals belong to the per-file augmentation and exported ones to the tree.
 *
 * `exported` is the receipt: everything the walk visited that another module
 * could call, which is what lets an empty `exportedBinary` be told apart from a
 * walk that ran over nothing.
 */
function conversionHelpersIn(source: TsSourceFile): {
  exportedBinary: Set<string>
  localBinary: Set<string>
  exported: Set<string>
  exempt: Set<string>
  exemptExported: Set<string>
} {
  const ctx = binaryTypeContext(source)
  const lines = sourceLines(source)
  const exportedBinary = new Set<string>()
  const localBinary = new Set<string>()
  const exported = new Set<string>()
  const exempt = new Set<string>()
  const exemptExported = new Set<string>()
  for (const decl of helperDeclarationsIn(source)) {
    if (decl.exported) exported.add(decl.name)
    if (!takesBinarySystem(decl.signature, source, ctx)) continue
    if (declarationExempt(decl.anchor, source, lines, 'binary-conversion')) {
      exempt.add(decl.name)
      if (decl.exported) exemptExported.add(decl.name)
      continue
    }
    if (decl.exported) exportedBinary.add(decl.name)
    else localBinary.add(decl.name)
  }
  return { exportedBinary, localBinary, exported, exempt, exemptExported }
}

/**
 * Every exported conversion helper `decimalSafe.ts` declares that decides on a
 * binary `UnitSystem` (R8).
 *
 * ★ THIS SET IS EMPTY TODAY, AND EMPTY IS THE GOAL STATE RATHER THAN A BROKEN
 * DERIVATION. Task 5 took R8's deletion branch: all three helpers are gone, so
 * "no call site anywhere" is the truth rather than the silence of a detector
 * that lost its vocabulary. `requireNonEmpty` therefore guards `exported`, not
 * `binary`: the walk still has to come back holding the resolved-set converters
 * R8 kept, which is what a gutted file or a changed AST shape would fail.
 *
 * The other way `binary` could empty is `BINARY_SYSTEM_TYPE` ceasing to match.
 * That used to rest on a side effect one function up, and only for as long as
 * the FORMATTER set stayed non-empty. It is checked directly by
 * `requireBinarySystemType` now, which runs before either derivation and does
 * not expire when the last binary formatter retires. See its docstring.
 */
function deriveBinaryConversionHelpers(): Set<string> {
  const { exportedBinary, exported } = conversionHelpersIn(parseForDerivation(CONVERSION_SOURCE))
  requireNonEmpty(exported, 'exported conversion helper', CONVERSION_SOURCE)
  return exportedBinary
}

/**
 * The ten convertible quantities, read from the list the compiler proves complete.
 *
 * `UNIT_QUANTITIES` is `satisfies readonly UnitQuantity[]` on one side and
 * `UNIT_QUANTITIES_ARE_COMPLETE` on the other, so a quantity added to `UnitSet`
 * and forgotten here stops the build. That makes it a better source than any
 * list this script could keep.
 *
 * ★ It also deliberately EXCLUDES `secondary_gallon`, and that exclusion is the
 * structural exemption R1 asks for rather than a prose rule: the gallon flavour
 * is a choice between units with no quantity to convert, so
 * `units.secondary_gallon === 'uk'` is not a display conversion and the gate
 * must not learn to call it one.
 */
function deriveQuantityNames(): Set<string> {
  const source = parseForDerivation(QUANTITY_SOURCE)
  const found = new Set<string>()
  const walk = (node: TsNode): void => {
    if (
      node.kind === ts.SyntaxKind.VariableDeclaration &&
      node.name?.getText(source) === 'UNIT_QUANTITIES' &&
      node.initializer
    ) {
      collectStringLiterals(node.initializer, found)
    }
    ts.forEachChild(node, walk)
  }
  walk(source)
  return requireNonEmpty(found, 'unit quantity name', QUANTITY_SOURCE)
}

function collectStringLiterals(node: TsNode, into: Set<string>): void {
  if (LITERAL_KINDS.has(node.kind) && typeof node.text === 'string') into.add(node.text)
  ts.forEachChild(node, (child) => collectStringLiterals(child, into))
}

/**
 * Each quantity's resolved-token vocabulary, read from the generated schema.
 *
 * The schema is the single source of truth the api-freshness gate keeps in
 * step with the backend, so a token the backend adds arrives here without
 * anybody remembering to add it.
 */
function deriveQuantityTokens(): Map<string, Set<string>> {
  const quantities = deriveQuantityNames()
  const source = parseForDerivation(SCHEMA_SOURCE)
  const tokens = new Map<string, Set<string>>()
  const walk = (node: TsNode): void => {
    if (
      node.kind === ts.SyntaxKind.PropertySignature &&
      node.name?.getText(source) === 'UnitSet' &&
      node.type?.kind === ts.SyntaxKind.TypeLiteral
    ) {
      for (const member of node.type.members ?? []) {
        if (member.kind !== ts.SyntaxKind.PropertySignature || !member.name || !member.type) continue
        const quantity = member.name.getText(source)
        if (!quantities.has(quantity)) continue
        const vocabulary = new Set<string>()
        collectStringLiterals(member.type, vocabulary)
        if (vocabulary.size > 0) tokens.set(quantity, vocabulary)
      }
    }
    ts.forEachChild(node, walk)
  }
  walk(source)
  // No requireNonEmpty here: `missing` subsumes it. An empty `tokens` means
  // every quantity is missing, and this message names which, where a bare
  // "derived nothing" would not.
  const missing = [...quantities].filter((q) => !tokens.has(q))
  if (missing.length > 0) {
    throw new Error(
      `no token vocabulary for ${missing.join(', ')} in ${relative(ROOT, SCHEMA_SOURCE)}. ` +
        'A quantity with no vocabulary is a quantity the token-branch leg cannot see. ' +
        'Refusing to run.',
    )
  }
  return tokens
}

requireBinarySystemType()
// The two single-file derivations stay, and they are not redundant with the
// tree-wide one: each carries a `requireNonEmpty` RECEIPT over the file whose
// surface a ruling governs (`UnitFormatter`'s statics under R2,
// `decimalSafe.ts`'s exports under R8), so a gutted file or a changed AST shape
// still fails loudly instead of shrinking the tree-wide set by two.
deriveBinaryFormatterMethods()
deriveBinaryConversionHelpers()
const BINARY_SURFACE = deriveBinarySurface()
const BINARY_FORMATTER_METHODS = BINARY_SURFACE.formatters
const BINARY_CONVERSION_HELPERS = BINARY_SURFACE.helpers
const EXEMPT_BINARY_SITES = BINARY_SURFACE.exemptSites
const EXEMPT_BINARY_EXPORTED = BINARY_SURFACE.exemptExported
const QUANTITY_TOKENS = deriveQuantityTokens()

export interface Finding {
  file: string
  line: number
  kind: string
  text: string
}

/**
 * Every kind this gate can report, declared once so the claim can count them.
 *
 * ★ THE SUCCESS LINE USED TO SAY "five detectors" AS A WORD. That is the defect
 * this file's own header records against itself two screens up: an earlier
 * version said "~53" while the baseline twelve lines away said 43. A number in
 * the gate's central claim is the worst place in the repo for one, because it is
 * the sentence people quote and the one nothing was checking.
 *
 * So the count is `FINDING_KINDS.length` and `record()` refuses a kind that is
 * not in here, which makes a sixth leg register itself or fail loudly on its
 * first finding. `units_gate_selftest.py`'s clean-room proof reads the kinds
 * back out of the `record(...)` CALL SITES independently and asserts the two
 * agree, so neither half can drift alone, and it demands a corpus positive for
 * each one.
 */
const FINDING_KINDS = [
  'compare',
  'switch-case',
  'formatter-binary',
  'binary-conversion',
  'token-branch',
] as const

/**
 * How many findings a `// units-exempt:` pragma removed on this run.
 *
 * ★ Counted rather than described, because after the flip the pragma is the
 * only suppression left and a clean-room tick that does not say how many sites
 * it is silent about is claiming more than it checks. Printed beside the tick
 * and reset per run so `--scan` (one file) and the tree walk each report their
 * own number.
 */
let exemptedFindings = 0

/**
 * How many sites the DECLARATION hatch hid on this run, and how many the
 * structural placeholder exemption suppressed.
 *
 * ★ Both exist because the success line named a number that was not
 * proportional to what it stood for. "3 binary declaration(s) exempt" said
 * nothing about the fifteen call sites those three lines removed, and the R5
 * placeholder exemption suppressed a finding while incrementing no counter at
 * all, so the accounting beside a clean-room tick was incomplete in the one
 * direction that matters. A suppression nobody counts is a suppression nobody
 * notices growing.
 */
let hiddenByDeclaration = 0
let structurallyExempt = 0

/**
 * Where the line-level pragmas are, as `path::kind`, so they can be PINNED.
 *
 * ★ The review's judgement on task 8's own concern 5: printing a count is
 * necessary and not sufficient. The twelve declaration exemptions are held by
 * an exact-list equality test, so a thirteenth fails a test rather than moving
 * an integer nothing asserts on; the line-level ones had only the integer. `--suppressions` prints this so the same pin can be put on them.
 */
const pragmaSuppressed = new Map<string, number>()

interface BaselineEntry {
  file: string
  kind: string
  text: string
  count: number
}

/** True when the node is the string `'imperial'` or `'metric'`. */
function isSystemLiteral(node: TsNode | undefined): boolean {
  return (
    node !== undefined &&
    LITERAL_KINDS.has(node.kind) &&
    typeof node.text === 'string' &&
    SYSTEM_LITERALS.has(node.text)
  )
}

/**
 * Index every declaration in the file by name, remembering its annotation.
 *
 * Deliberately flat rather than scope-aware: when a name is declared more than
 * once, an operand is only exempted if EVERY declaration of that name is
 * foreign. A scope-aware lookup that picked the nearest declaration would let a
 * shadowing `const theme: Theme` in one function silence a real unit-system
 * `theme` in another.
 */
interface FileIndex {
  /** Declared name to every type annotation it is declared with, null when bare. */
  declared: Map<string, (string | null)[]>
  /** Local `type X = ...` aliases, so a named union can be resolved to members. */
  aliases: Map<string, string>
}

function indexDeclarations(source: TsSourceFile): FileIndex {
  const declared = new Map<string, (string | null)[]>()
  const aliases = new Map<string, string>()
  const DECL_KINDS = new Set([
    ts.SyntaxKind.VariableDeclaration,
    ts.SyntaxKind.Parameter,
    ts.SyntaxKind.PropertyDeclaration,
    ts.SyntaxKind.PropertySignature,
    ts.SyntaxKind.BindingElement,
  ])
  const walk = (node: TsNode): void => {
    if (DECL_KINDS.has(node.kind) && node.name?.kind === ts.SyntaxKind.Identifier) {
      const name = node.name.text ?? ''
      const annotation = node.type ? node.type.getText(source) : null
      declared.set(name, [...(declared.get(name) ?? []), annotation])
    }
    if (node.kind === ts.SyntaxKind.TypeAliasDeclaration && node.name && node.type) {
      aliases.set(node.name.text ?? '', node.type.getText(source))
    }
    ts.forEachChild(node, walk)
  }
  walk(source)
  return { declared, aliases }
}

/**
 * Strip balanced surrounding parentheses, repeatedly.
 *
 * `type Sys = ('imperial' | 'metric')` is one of the five shapes that walked
 * past round 2. Only a paren that closes at the very end is stripped, so
 * `(typeof SYSTEMS)[number]` keeps its shape and stays UNKNOWN rather than
 * being mangled into something that looks resolvable.
 */
function stripOuterParens(text: string): string {
  let out = text.trim()
  while (out.startsWith('(') && out.endsWith(')')) {
    let depth = 0
    let balanced = true
    for (let i = 0; i < out.length; i += 1) {
      if (out[i] === '(') depth += 1
      else if (out[i] === ')') {
        depth -= 1
        if (depth === 0 && i !== out.length - 1) balanced = false
      }
    }
    if (!balanced || depth !== 0) break
    out = out.slice(1, -1).trim()
  }
  return out
}

/**
 * Split a union on TOP-LEVEL `|` only.
 *
 * A naive `text.split('|')` tears `Record<string, 'a' | 'b'>` in half and then
 * judges the halves, so the nesting depth is tracked through `<`, `(`, `[`, `{`
 * and both quote styles.
 */
function splitUnion(text: string): string[] {
  const parts: string[] = []
  let depth = 0
  let quote = ''
  let current = ''
  for (const ch of text) {
    if (quote) {
      current += ch
      if (ch === quote) quote = ''
      continue
    }
    if (ch === "'" || ch === '"' || ch === '`') {
      quote = ch
      current += ch
      continue
    }
    if ('<([{'.includes(ch)) depth += 1
    else if ('>)]}'.includes(ch)) depth -= 1
    if (ch === '|' && depth <= 0) {
      parts.push(current)
      current = ''
      continue
    }
    current += ch
  }
  parts.push(current)
  return parts.map((s) => s.trim()).filter((s) => s.length > 0)
}

/**
 * What one type expression is, as far as this gate can tell.
 *
 * `unknown` is the fail-closed class and it is doing most of the work: an
 * imported alias, `(typeof SYSTEMS)[number]`, a generic, or the bare word
 * `string` all land here, and none of them earns an exemption.
 */
type MemberClass = 'unit' | 'foreign' | 'nullish' | 'unknown'

const STRING_LITERAL_TYPE = /^(?:'[^']*'|"[^"]*"|`[^`]*`|-?\d+(?:\.\d+)?|true|false)$/
const BARE_IDENTIFIER = /^[A-Za-z_$][\w$]*$/

function classifyMember(
  member: string,
  aliases: Map<string, string>,
  depth: number,
): MemberClass {
  const m = stripOuterParens(member)
  if (UNIT_VOCABULARY.has(m)) return 'unit'
  if (NULLISH_MEMBERS.has(m)) return 'nullish'
  if (STRING_LITERAL_TYPE.test(m)) return 'foreign'
  if (BARE_IDENTIFIER.test(m)) {
    const body = aliases.get(m)
    // Fail-closed on a name this file does not declare, and on an alias cycle.
    if (body === undefined || depth >= 8) return 'unknown'
    return classifyAnnotation(body, aliases, depth + 1)
  }
  return 'unknown'
}

/**
 * Classify a whole annotation by classifying its members INDIVIDUALLY.
 *
 * ★ Round 2 judged the annotation's whole text and asked "are all members unit
 * vocabulary?", so a single member outside the vocabulary made the entire
 * annotation foreign, and foreign means exempt. Five shapes walked past,
 * including `'imperial' | 'metric' | null`, which round 1 had caught. Deciding
 * per member is the fix.
 *
 * The order of the three tests below is the whole rule:
 *
 *  1. any UNKNOWN member and the annotation earns nothing. That is what stops
 *     an imported alias, an indexed access, or the bare word `string` being a
 *     rename away from silence;
 *  2. nullish members are dropped, because a nullable unit system is a unit
 *     system;
 *  3. of what remains, a member that is a literal OUTSIDE the vocabulary makes
 *     the annotation foreign.
 *
 * ★ Test 3 is a DELIBERATE divergence from the reviewer's wording, which was
 * "foreign only when NO member is a unit system". Taken literally that flags
 * `type Theme = 'light' | 'dark' | 'imperial'`, and R2 requires that case to be
 * ACCEPTED while R3 names it as the case this whole leg exists to distinguish.
 * A type carrying members no unit system has ever contained is a different enum
 * that happens to share a spelling.
 *
 * ★ WHERE THAT BOUNDARY SITS, because it is wider than the Theme case and the
 * next reader should not have to discover it: ANY recognised literal outside
 * the vocabulary exempts the union, so `'imperial' | 'metric' | 0` is exempt
 * too. That is the rounding working as designed rather than a second bypass:
 * `0` is a literal type this scanner can read and no unit system has ever
 * contained, so the union is treated as a different enum. The rule is
 * "recognised non-vocabulary literal means foreign", not "string literal means
 * foreign", and a member it CANNOT read is `unknown` and fail-closed instead.
 * If that ever needs to change, change it here and expect S-N2 and S-N6 to
 * flip, which is what `M38-any-unit-member-flags` measures. Every probe in the review's bypass table is
 * still closed, and the control still fires; only Theme differs, and Theme is
 * the corpus negative. Pinned from the other side by `M38-any-unit-member-flags`,
 * which implements the literal reading and flips exactly that case.
 */
function classifyAnnotation(
  text: string,
  aliases: Map<string, string>,
  depth = 0,
): MemberClass {
  const members = splitUnion(stripOuterParens(text))
  if (members.length === 0) return 'unknown'
  const classes = members.map((m) => classifyMember(m, aliases, depth))
  if (classes.includes('unknown')) return 'unknown'
  const significant = classes.filter((c) => c !== 'nullish')
  if (significant.length === 0) return 'nullish'
  if (significant.includes('foreign')) return 'foreign'
  return 'unit'
}

/** True when an annotation proves the operand is NOT a unit system. */
function isForeignAnnotation(annotation: string, aliases: Map<string, string>): boolean {
  const verdict = classifyAnnotation(annotation, aliases)
  return verdict === 'foreign' || verdict === 'nullish'
}

/**
 * True when the operand is provably NOT a unit system.
 *
 * This is the whole reason the comparison rule cannot be an ESLint selector:
 * it needs the operand's DECLARATION, not its spelling. The rule is
 * fail-closed: an operand that cannot be resolved to a local declaration
 * carrying a foreign type annotation is treated as a unit system, because the
 * cost of a spurious baseline entry is a line of review and the cost of a miss
 * is the defect class this whole phase exists to remove.
 */
function hasForeignProvenance(operand: TsNode, index: FileIndex): boolean {
  if (operand.kind !== ts.SyntaxKind.Identifier) return false
  const annotations = index.declared.get(operand.text ?? '')
  if (annotations === undefined || annotations.length === 0) return false
  return annotations.every((a) => a !== null && isForeignAnnotation(a, index.aliases))
}

/**
 * True when the comparison sits inside a `placeholder` JSX attribute.
 *
 * Ruling R5: a placeholder is a plausible EXAMPLE value, not a converted
 * quantity, and there is nothing canonical to convert, so
 * `placeholder={system === 'imperial' ? '45000' : '72420'}` is correct code and
 * a gate that flags it is flagging correct code.
 */
function isPlaceholderAttribute(node: TsNode): boolean {
  for (let cur = node.parent; cur; cur = cur.parent) {
    if (cur.kind === ts.SyntaxKind.JsxAttribute) {
      return cur.name?.text === 'placeholder'
    }
  }
  return false
}

/** Collapse runs of whitespace so a wrapped expression keys the same as a flat one. */
function normalize(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

/**
 * The name a call expression invokes, ignoring what it is invoked on.
 *
 * `toCanonicalKm(v, system)` and `helpers.toCanonicalKm(v, system)` are the
 * same decision, and an import alias must not be an escape hatch.
 */
function calleeName(callee: TsNode | undefined, source: TsSourceFile): string {
  if (!callee) return ''
  if (callee.kind === ts.SyntaxKind.Identifier) return callee.text ?? ''
  if (callee.kind === ts.SyntaxKind.PropertyAccessExpression) {
    return callee.name?.getText(source) ?? ''
  }
  return ''
}

/**
 * True when an identifier is a USE of a name rather than a binding of it.
 *
 * ★ WHY THIS EXISTS, AND IT WAS FOUND BY CHECKING A NUMBER RATHER THAN BY
 * REASONING. The `binary-conversion` leg matched a CallExpression whose callee
 * is in the vocabulary, so `displayToCanonical(v, t, system)` was a finding and
 * `convertSupplyUsages(usages, byId, system, displayToCanonical)` was not:
 * passing the helper as a VALUE evaded the leg completely, and the callee then
 * makes the D8-collapsed decision one frame down where nothing looks. Both
 * spellings are live in `ServiceVisitForm.tsx` (lines 249 and 344), and the
 * second one is the WRITE path.
 *
 * That is the same class as the destructuring rename (S-P7) and the aliased
 * formatter receiver (S-P35): one decision, different punctuation. It is
 * therefore CLOSED rather than declared as a residual, which is the line this
 * gate draws between a shape spelled differently and a genuinely different
 * thing (a `Record<string, UnitSystem>` is the latter, and stays out).
 *
 * The exclusions below are all bindings rather than uses: an import or export
 * specifier names the symbol without deciding anything, a declaration's own
 * name is the declaration, and a call is already reported by the leg above, so
 * counting it here would double every finding it makes. A qualified
 * `helpers.toCanonicalKm` IS a use unless it is that call's callee, because an
 * import alias must not be an escape hatch here either.
 */
function isValueReference(node: TsNode): boolean {
  const parent = node.parent
  if (parent === undefined) return false
  const K = ts.SyntaxKind
  if (parent.kind === K.ImportSpecifier || parent.kind === K.ExportSpecifier) return false
  if (parent.kind === K.FunctionDeclaration) return false
  if (parent.name === node) {
    // The name half of any declaration, binding or member.
    return false
  }
  if (parent.kind === K.CallExpression && parent.expression === node) return false
  if (parent.kind === K.PropertyAccessExpression) {
    const grand = parent.parent
    if (grand?.kind === K.CallExpression && grand.expression === parent) return false
    return true
  }
  return true
}

/**
 * The `UnitSet` quantity an operand names, or null.
 *
 * Both spellings count: the property access `units.volume` and the bare
 * `volume` a destructure leaves behind. Keying on the property access alone
 * would make `const { volume } = units` a one-line bypass, which is the same
 * shape as the destructuring rename the comparison leg already defends against
 * (corpus S-P7).
 */
function quantityNameOf(operand: TsNode | undefined, source: TsSourceFile): string | null {
  if (!operand) return null
  const name =
    operand.kind === ts.SyntaxKind.PropertyAccessExpression
      ? (operand.name?.getText(source) ?? '')
      : operand.kind === ts.SyntaxKind.Identifier
        ? (operand.text ?? '')
        : ''
  return QUANTITY_TOKENS.has(name) ? name : null
}

/**
 * The quantity a raw resolved-token comparison decides, or null.
 *
 * This is scope category 4's second half: `units.volume === 'L' ? km : miles`
 * collapses DISTANCE out of VOLUME with no `imperial` or `metric` literal
 * anywhere, so the comparison leg is blind to it by construction. Live today at
 * `PropaneRecordList`, `Analytics` (twice) and inside `units.ts` itself.
 *
 * The literal must belong to THAT quantity's own vocabulary, so `mass === 'psi'`
 * and a `size === 'L'` on a shirt are both left alone.
 */
function quantityBranchOf(node: TsNode, source: TsSourceFile): string | null {
  for (const [operand, literal] of [
    [node.left, node.right],
    [node.right, node.left],
  ] as [TsNode | undefined, TsNode | undefined][]) {
    if (!literal || !LITERAL_KINDS.has(literal.kind) || typeof literal.text !== 'string') continue
    const quantity = quantityNameOf(operand, source)
    if (quantity !== null && QUANTITY_TOKENS.get(quantity)?.has(literal.text)) return quantity
  }
  return null
}

/**
 * A source file thrown away by the parser is worse than a missing gate.
 *
 * Round 1 hardcoded `ScriptKind.TSX` for every file. `const x = <string>raw` is
 * an angle-bracket type assertion: legal TypeScript in a `.ts` file, illegal in
 * TSX. Under the wrong ScriptKind the parser dropped the enclosing subtree, the
 * scan returned nothing for the file, the gate exited 0, and it printed
 * "3 fixed, run --update to shrink the baseline", inviting the blindness to be
 * baked into the baseline. Two halves to the fix and both are needed: choose
 * the ScriptKind by extension, and REFUSE TO SCAN a file the parser complained
 * about, rather than reporting the wreckage as a clean file. Same fail-loud
 * posture as `loadTypeScript`, one layer in.
 */
export function scanSource(source: string, rel: string): Finding[] {
  const kind = rel.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS
  const sf = ts.createSourceFile(rel, source, ts.ScriptTarget.Latest, true, kind)
  const diagnostics = sf.parseDiagnostics
  if (diagnostics === undefined) {
    throw new Error(
      `${rel}: this TypeScript build exposes no parseDiagnostics, so a file the ` +
        'parser rejected would be indistinguishable from a clean one. Refusing to scan.',
    )
  }
  if (diagnostics.length > 0) {
    const first = diagnostics[0]
    const message =
      typeof first.messageText === 'string' ? first.messageText : first.messageText.messageText
    const at =
      first.start === undefined
        ? ''
        : ` (line ${sf.getLineAndCharacterOfPosition(first.start).line + 1})`
    throw new Error(
      `${rel}: parsed as ${rel.endsWith('.tsx') ? 'TSX' : 'TS'} with ` +
        `${diagnostics.length} parse error(s)${at}: ${message}\n` +
        'A file the parser rejects yields zero findings, which this gate would ' +
        'otherwise report as migration progress. Fix the file, or fix the gate.',
    )
  }
  // ★ The vocabulary is every EXPORTED binary helper in the tree, plus every
  // one this file declares for itself, exported or not. A local helper cannot
  // be called from anywhere else, so this is the only place it can be seen, and
  // its name is not unique enough to go in the tree-wide set.
  //
  // ★ THIS COMMENT USED TO NAME THE POPULATION and the number was a floor: it
  // said "the only two files declaring such a helper are `decimalSafe.ts` and
  // `supplyUnits.ts`" while five files declared one, because the walk behind it
  // required `export` on a top-level `function`. That is an inventory that is a
  // floor, written inside the artifact whose subject is that defect, and the
  // replacement deliberately states a RULE rather than a count: any count here
  // goes stale the day somebody adds a file, and `--derived` prints the real
  // one on demand.
  // ★ A RENAMING IMPORT IS NOT AN ESCAPE HATCH, on the callee either.
  // `calleeName`'s docstring has said "an import alias must not be an escape
  // hatch" since task 5 and the formatter leg defends against
  // `import { UnitFormatter as UF }`, but that closed it on the RECEIVER only:
  // `import { revConvert as rc }` then `rc(v, system)` keyed the local text
  // against the vocabulary and matched nothing, in the call form AND the value
  // form. The namespace form (`ns.revConvert`) was caught all along, which is
  // what made the gap easy to miss. Both legs resolve through this map now.
  const importAliases = new Map<string, string>()
  const collectAliases = (node: TsNode): void => {
    if (node.kind === ts.SyntaxKind.ImportSpecifier && node.propertyName?.text && node.name?.text) {
      importAliases.set(node.name.text, node.propertyName.text)
    }
    ts.forEachChild(node, collectAliases)
  }
  collectAliases(sf)
  /** The name a local binding refers to in the module that exported it. */
  const resolveAlias = (name: string): string => importAliases.get(name) ?? name

  const here = conversionHelpersIn(sf)
  const binaryHelpersHere = new Set([
    ...BINARY_CONVERSION_HELPERS,
    ...here.exportedBinary,
    ...here.localBinary,
  ])
  // What the declaration hatch took OUT of that set, so the success line can
  // say how many sites those pragmas hide rather than only how many there are.
  // Same construction as the vocabulary above, one set over: names another
  // module can reach, plus this file's own.
  const exemptHere = new Set([...EXEMPT_BINARY_EXPORTED, ...here.exempt])
  // ★ The formatter leg gets the same treatment, and it is not symmetry for
  // its own sake. `UnitFormatter`'s binary surface is EMPTY since task 7, so a
  // vocabulary derived from `units.ts` alone can no longer fire at all, and a
  // leg that cannot fire is one nothing can prove still works: the two-sided
  // corpus that pins it (`units_gate_corpus.py`) had to spell a live
  // production method name, and it has now been renamed three times as each
  // one retired. Reading the scanned file's OWN class declarations makes the
  // corpus fixtures self-owned, exactly as the conversion leg's already are,
  // and closes a real same-file blindness at the same time: a component that
  // declares a static `format(x, system: UnitSystem)` on a class of its own and
  // calls it is making the D8-collapsed decision where neither the comparison
  // leg (the comparison is in the callee) nor the derived leg (the method is
  // not on `UnitFormatter`) could see it.
  const binaryFormattersHere = new Set([
    ...BINARY_FORMATTER_METHODS,
    ...formatterMethodsIn(sf, null).binary,
  ])
  const lines = source.split('\n')
  const index = indexDeclarations(sf)
  const findings: Finding[] = []

  const record = (node: TsNode, kind_: string, text: string): void => {
    if (!(FINDING_KINDS as readonly string[]).includes(kind_)) {
      throw new Error(
        `${rel}: reported a finding of kind ${JSON.stringify(kind_)}, which is not in ` +
          `FINDING_KINDS (${FINDING_KINDS.join(', ')}). The success line counts that list, ` +
          'so an unregistered leg would be detected and then not counted, and the claim ' +
          'would name fewer detectors than the gate runs. Refusing to scan. Add the kind ' +
          'to the list, and give it a corpus positive: the clean-room proof requires one.',
      )
    }
    const line = sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1
    // Escape hatch: the offending line or the line directly above it, and it
    // has to name this kind or name none.
    if (exemptedAtLine(lines, line, kind_)) {
      exemptedFindings += 1
      const key = `${rel}::${kind_}`
      pragmaSuppressed.set(key, (pragmaSuppressed.get(key) ?? 0) + 1)
      return
    }
    findings.push({ file: rel, line, kind: kind_, text })
  }

  const walk = (node: TsNode): void => {
    if (node.kind === ts.SyntaxKind.BinaryExpression && node.operatorToken) {
      if (EQUALITY_KINDS.has(node.operatorToken.kind)) {
        const rightIsLiteral = isSystemLiteral(node.right)
        const leftIsLiteral = isSystemLiteral(node.left)
        // ★ RULING R5 APPLIES TO BOTH LEGS, and until task 8 it was wired to
        // one. A placeholder is a plausible EXAMPLE value with nothing
        // canonical behind it to convert, which is exactly as true of
        // `placeholder={units.distance === 'mi' ? '45000' : '72420'}` as of the
        // `system === 'imperial'` spelling the exemption was written for.
        // `FuelRecordForm.tsx:1029` is that line, and it sat in the baseline as
        // migration work for the whole of phase 3b because the token-branch leg
        // did not ask.
        const inPlaceholder = isPlaceholderAttribute(node)
        if (rightIsLiteral || leftIsLiteral) {
          // Yoda comparisons put the literal on the left; the operand is
          // whichever side is not the literal.
          const operand = (rightIsLiteral ? node.left : node.right) as TsNode
          if (!hasForeignProvenance(operand, index)) {
            if (inPlaceholder) structurallyExempt += 1
            else record(node, 'compare', normalize(node.getText(sf)))
          }
        }
        const quantity = quantityBranchOf(node, sf)
        if (quantity !== null) {
          if (inPlaceholder) structurallyExempt += 1
          else record(node, 'token-branch', `${quantity}: ${normalize(node.getText(sf))}`)
        }
      }
    }
    if (node.kind === ts.SyntaxKind.CaseClause && isSystemLiteral(node.expression)) {
      const literal = node.expression as TsNode
      record(literal, 'switch-case', `case ${normalize(literal.getText(sf))}`)
    }
    if (node.kind === ts.SyntaxKind.CallExpression) {
      const callee = node.expression
      const called = resolveAlias(calleeName(callee, sf))
      // A static method is only ever reachable through a receiver, so requiring
      // one is what separates `UnitFormatter.formatDistance(km, system)` from a
      // module-local `formatDistance(meters, units)`. That distinction is load
      // bearing rather than cosmetic: three local helpers spell that name today
      // and `POICard`'s is CORRECT migrated code taking a resolved `UnitSet`.
      // Matching on the name alone flagged all three, and a gate that reports
      // correct code is the one people learn to run --update against.
      // Keying on the receiver's SPELLING instead would make
      // `import { UnitFormatter as UF }` a one-line bypass, so the object is
      // required but not read.
      if (callee?.kind === ts.SyntaxKind.PropertyAccessExpression) {
        if (binaryFormattersHere.has(called)) {
          record(node, 'formatter-binary', `${normalize(callee.getText(sf))}(...)`)
        } else if (exemptHere.has(called)) {
          hiddenByDeclaration += 1
        }
      }
      // The conversion helpers are module functions, so the mirror of the rule
      // above applies: a bare call IS the shape, and a namespace import is not
      // an escape hatch either.
      if (binaryHelpersHere.has(called)) {
        record(node, 'binary-conversion', `${called}(...)`)
      } else if (exemptHere.has(called)) {
        hiddenByDeclaration += 1
      }
    }
    // ★ AND THE SAME HELPER PASSED AS A VALUE, which the call form above cannot
    // see. See `isValueReference` for what found this and why it is closed
    // rather than declared. The text says `as a value` so the two spellings key
    // separately and a site cannot be silenced by the other one's pragma.
    if (
      node.kind === ts.SyntaxKind.Identifier &&
      binaryHelpersHere.has(resolveAlias(node.text ?? '')) &&
      isValueReference(node)
    ) {
      // ★ A JSX element IS a call site, so it is not described as a value. Fix
      // round 1's widening put component declarations into the vocabulary (a
      // props object holding `system: UnitSystem` is a binary API, which is the
      // rule the precondition set), and `<PurchaseRow system={system} />` is
      // where a collapsed system is handed across that boundary. Calling that
      // "as a value" would be the finding text lying about the shape it found.
      const jsx =
        node.parent?.kind === ts.SyntaxKind.JsxSelfClosingElement ||
        node.parent?.kind === ts.SyntaxKind.JsxOpeningElement
      record(
        node,
        'binary-conversion',
        jsx ? `<${node.text ?? ''} ...>` : `${node.text ?? ''} (as a value)`,
      )
    } else if (
      node.kind === ts.SyntaxKind.Identifier &&
      exemptHere.has(resolveAlias(node.text ?? '')) &&
      isValueReference(node)
    ) {
      hiddenByDeclaration += 1
    }
    ts.forEachChild(node, walk)
  }

  walk(sf)
  return findings
}

/** Every production source file under `src`, tests excluded as in the sibling gates. */
function walkDir(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      if (entry === '__tests__' || entry === 'node_modules') continue
      walkDir(full, out)
    } else if (
      (entry.endsWith('.ts') || entry.endsWith('.tsx')) &&
      !entry.endsWith('.test.ts') &&
      !entry.endsWith('.test.tsx') &&
      !entry.endsWith('.d.ts')
    ) {
      out.push(full)
    }
  }
  return out
}

function scanFile(path: string): Finding[] {
  return scanSource(readFileSync(path, 'utf-8'), relative(ROOT, path))
}

/**
 * Stable identity for a finding: file, kind and expression, never the line.
 *
 * The separator is written as an escape rather than a raw control character so
 * the file stays textual: a literal NUL byte makes git and grep treat the
 * source as binary. A space would be worse than either, because the expression
 * text contains spaces and splitting a space-joined key back apart truncates
 * every comparison to its first token.
 */
const KEY_SEP = '\u0000'

function keyOf(f: { file: string; kind: string; text: string }): string {
  return [f.file, f.kind, f.text].join(KEY_SEP)
}

/** Split a key back into its parts. Inverse of keyOf(). */
function partsOf(key: string): { file: string; kind: string; text: string } {
  const [file, kind, text] = key.split(KEY_SEP)
  return { file, kind, text }
}

function countByKey(findings: Finding[]): Map<string, number> {
  const counts = new Map<string, number>()
  for (const f of findings) counts.set(keyOf(f), (counts.get(keyOf(f)) ?? 0) + 1)
  return counts
}

function printReport(findings: Finding[]): void {
  const byFile = new Map<string, Finding[]>()
  for (const f of findings) byFile.set(f.file, [...(byFile.get(f.file) ?? []), f])
  console.log(
    `\n${findings.length} unit-system branch(es) across ${byFile.size} file(s):\n`,
  )
  for (const [file, hits] of [...byFile].sort((a, b) => b[1].length - a[1].length)) {
    console.log(`  ${String(hits.length).padStart(4)}  ${file}`)
  }
  console.log('')
  for (const [file, hits] of [...byFile].sort((a, b) => a[0].localeCompare(b[0]))) {
    console.log(`  ${file}`)
    for (const h of hits) console.log(`      :${String(h.line).padEnd(5)} [${h.kind}]  ${h.text}`)
  }
  console.log('')
}

/**
 * What the tick does NOT cover, printed beside it.
 *
 * A gate's success line is the sentence people quote, so the one suppression
 * that reaches ACROSS files is counted in it rather than left to `--derived`.
 * Task 8 made the binary vocabularies tree-wide, and one `// units-exempt:` on
 * a declaration then silences every call site of that declaration everywhere;
 * the number moving is what stops that growing quietly.
 */
function exemptionCensus(): string {
  const parts: string[] = []
  if (exemptedFindings > 0) parts.push(`${exemptedFindings} by a pragma on the line`)
  if (structurallyExempt > 0) {
    parts.push(`${structurallyExempt} structurally (R5 placeholders)`)
  }
  if (EXEMPT_BINARY_SITES.length > 0) {
    parts.push(
      `${hiddenByDeclaration} by ${EXEMPT_BINARY_SITES.length} pragma(s) on a binary declaration`,
    )
  }
  if (parts.length === 0) return ''
  return `\n  Suppressed, and NOT counted above: ${parts.join('; ')}.`
}

function main(): void {
  const argv = process.argv.slice(2)
  const args = new Set(argv)

  // ★ The derived sets, printable. The report for this change quoted them "from
  // the gate's own constants" and there was no command that printed them: the
  // block came from a scratchpad script, so a future reader could not reproduce
  // it and the numbers would go stale exactly the way this file's own "the run
  // prints it, prose goes stale" rule exists to prevent.
  if (args.has('--derived')) {
    console.log(
      `BINARY_FORMATTER_METHODS (${BINARY_FORMATTER_METHODS.size}): ` +
        [...BINARY_FORMATTER_METHODS].sort().join(', '),
    )
    console.log(
      `BINARY_CONVERSION_HELPERS (${BINARY_CONVERSION_HELPERS.size}): ` +
        [...BINARY_CONVERSION_HELPERS].sort().join(', '),
    )
    console.log(
      `EXEMPT_BINARY_DECLARATIONS (${EXEMPT_BINARY_SITES.length}): ` +
        EXEMPT_BINARY_SITES.join(', '),
    )
    console.log(`BINARY_DECLARATION_SOURCES (${BINARY_SURFACE.files})`)
    console.log(`QUANTITY_TOKENS (${QUANTITY_TOKENS.size}):`)
    for (const [quantity, tokens] of [...QUANTITY_TOKENS].sort()) {
      console.log(`   ${quantity.padEnd(14)}${[...tokens].sort().join(' ')}`)
    }
    return
  }

  const scanIdx = argv.indexOf('--scan')
  if (scanIdx !== -1) {
    const target = argv[scanIdx + 1]
    if (!target) {
      console.error('✗ --scan requires a file path')
      process.exit(2)
    }
    // ★ The prefilter refusal applies to a single scanned file too, and not
    // only for symmetry: a module that re-exports the binary type under another
    // name is exactly as blinding whether the tree walk or `--scan` meets it,
    // and this is the path the selftest can point at a fixture without writing
    // one into `src/`, which is where the corpus learned not to put fixtures.
    const scanned = scanSource(readFileSync(target, 'utf-8'), target)
    refuseAliasedReExport(
      ts.createSourceFile(
        target,
        readFileSync(target, 'utf-8'),
        ts.ScriptTarget.Latest,
        true,
        target.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
      ),
      target,
    )
    console.log(JSON.stringify({ file: target, findings: scanned }, null, 1))
    return
  }

  const baseIdx = argv.indexOf('--baseline')
  const baselinePath = baseIdx === -1 ? DEFAULT_BASELINE : (argv[baseIdx + 1] ?? DEFAULT_BASELINE)

  // `--src` exists so the selftest can walk a fixture tree it owns instead of
  // this repo's `src`. Round 1's probes wrote fixtures INTO `src`, where an
  // interrupted run left a file that failed validate-reachability.ts. A gate
  // whose own tests can break the working tree is not one anybody will wire
  // into CI, so the directory is a parameter.
  const srcIdx = argv.indexOf('--src')
  const srcDir = srcIdx === -1 ? SRC_DIR : (argv[srcIdx + 1] ?? SRC_DIR)

  exemptedFindings = 0
  hiddenByDeclaration = 0
  structurallyExempt = 0
  pragmaSuppressed.clear()
  const findings = walkDir(srcDir).flatMap(scanFile)
  const observed = countByKey(findings)

  // ★ EVERY SUPPRESSION THIS RUN APPLIED, ENUMERATED SO IT CAN BE PINNED.
  // The count on the success line says how much is suppressed; this says
  // WHERE, which is what a test can assert an exact list against. Both halves
  // are printed together because they are one question: what is this gate
  // silent about, and did a human sign for it.
  if (args.has('--suppressions')) {
    const sites = [...pragmaSuppressed].sort((a, b) => a[0].localeCompare(b[0]))
    console.log(`PRAGMA_SUPPRESSED (${exemptedFindings} finding(s), ${sites.length} site(s)):`)
    for (const [key, count] of sites) console.log(`   ${key} x${count}`)
    console.log(`EXEMPT_BINARY_DECLARATIONS (${EXEMPT_BINARY_SITES.length}):`)
    for (const site of EXEMPT_BINARY_SITES) console.log(`   ${site}`)
    console.log(`HIDDEN_BY_DECLARATION (${hiddenByDeclaration})`)
    console.log(`STRUCTURALLY_EXEMPT (${structurallyExempt})`)
    return
  }

  if (args.has('--update')) {
    // ★ THE ONE-WORD UNDO, REFUSED. Task 8 emptied `units.baseline.json` and
    // made this gate clean-room, and the failure message it replaced used to
    // end with "Do NOT run --update to silence a new finding" -- advice, in a
    // message a person reads at the moment they are looking for a way out.
    // Re-recording a finding there would restore the mode the flip removed,
    // with no diff in this file and none in any test. So the default path is
    // not writable: fix the finding, or exempt the line and say why.
    //
    // `--update --baseline <path>` still writes another file. That is how this
    // gate's own selftest builds the fixtures for its baseline and walk proofs,
    // and it is the only remaining caller.
    if (baseIdx === -1) {
      console.error(
        `✗ --update refuses to rewrite ${relative(ROOT, DEFAULT_BASELINE)}.\n\n` +
          'Plan 3b task 8 retired that baseline: it is `[]` and this gate is CLEAN-ROOM,\n' +
          'so any finding is a failure. Re-recording one here would undo the flip in a\n' +
          'single word, and nothing in the gate or its tests would change to say so.\n\n' +
          'Fix the finding, or mark its line `// units-exempt(<kind>): <reason>` and let\n' +
          'the run count it. `--update --baseline <path>` still writes another file.\n',
      )
      process.exit(2)
    }
    const payload: BaselineEntry[] = [...observed]
      .map(([key, count]) => {
        const { file, kind, text } = partsOf(key)
        return { file, kind, text, count }
      })
      .sort((a, b) =>
        a.file === b.file
          ? a.kind === b.kind
            ? a.text.localeCompare(b.text)
            : a.kind.localeCompare(b.kind)
          : a.file.localeCompare(b.file),
      )
    writeFileSync(baselinePath, `${JSON.stringify(payload, null, 1)}\n`)
    const total = payload.reduce((n, e) => n + e.count, 0)
    console.log(`✓ units baseline rewritten: ${total} occurrence(s), ${payload.length} key(s)`)
    return
  }

  let baseline: BaselineEntry[] = []
  try {
    baseline = JSON.parse(readFileSync(baselinePath, 'utf-8'))
  } catch {
    console.error(`✗ units baseline missing at ${relative(ROOT, baselinePath)}, run --update`)
    process.exit(1)
  }
  const allowed = new Map(baseline.map((e) => [keyOf(e), e.count]))

  if (args.has('--report')) printReport(findings)

  const risen = [...observed]
    .filter(([key, count]) => count > (allowed.get(key) ?? 0))
    .map(([key, count]) => ({ key, count, was: allowed.get(key) ?? 0 }))

  if (risen.length > 0) {
    const fresh = risen.reduce((n, r) => n + (r.count - r.was), 0)
    // "new" and "allowed" were baseline words and the baseline is retired, so
    // they are gone from the message a person actually reads when this fires.
    // The counts stay printed: `--baseline <path>` still runs the comparison
    // for this gate's own selftest, and there `was` is not always zero.
    console.error(`\n✗ ${fresh} unit-system branch(es):\n`)
    for (const r of risen) {
      const { file, kind, text } = partsOf(r.key)
      const sites = findings
        .filter((f) => keyOf(f) === r.key)
        .map((f) => f.line)
        .join(', ')
      console.error(`  ${file}  [${kind}]  ${text}`)
      console.error(
        `      ${r.count} found, line(s) ${sites}${r.was === 0 ? '' : `, ${r.was} recorded`}`,
      )
    }
    console.error(
      '\nRoute the decision through useUnitFormat() (or makeUnitFormat() outside a\n' +
        'component) so the quantity is converted and labelled by the resolved unit\n' +
        'set rather than a binary system. If the branch genuinely is not a display\n' +
        'conversion, mark the line `// units-exempt(<kind>): <reason>`, naming the\n' +
        'kind below so the pragma cannot silence a leg nobody considered.\n\n' +
        '  [formatter-binary]   a static UnitFormatter method taking a UnitSystem.\n' +
        '                       Use the matching u.<quantity> adapter instead: the\n' +
        '                       binary argument collapses ten quantities into one.\n' +
        '  [binary-conversion]  a helper taking a UnitSystem and WRITING canonical.\n' +
        '                       Convert through the resolved set on submit, and use\n' +
        '                       the origin-preserving pair so an untouched save does\n' +
        '                       not reconvert the rounded display value.\n' +
        '  [token-branch]       a resolved token read as a proxy for a whole system.\n' +
        '                       Read the quantity you actually mean: deriving the\n' +
        '                       distance half from units.volume is the defect.\n\n' +
        'This gate is CLEAN-ROOM: there is no baseline to record a finding in, and\n' +
        '--update refuses to write one. The pragma is the only suppression there is,\n' +
        'it has to name the kind above, and every run counts how many sites use it.\n',
    )
    process.exit(1)
  }

  // `relative` climbs out of the repo for a scan of somewhere else (the
  // selftest points `--src` at a temp tree), and six `../` say less than the
  // path does.
  const within = relative(ROOT, srcDir)
  const scope = within === '' ? 'src' : within.startsWith('..') ? srcDir : within
  // ★ THE CLAIM, AND IT IS DELIBERATELY SMALLER THAN A TICK. Two sentences,
  // because the second is the one that stops the first being read as "there are
  // no unit defects". The phase withdrew that claim on purpose and the flip must
  // not restore it by tone. The detector count is derived, not written: see
  // FINDING_KINDS.
  console.log(
    `✓ ${scope}: no unsuppressed expression matches this gate's ` +
      `${FINDING_KINDS.length} detectors.${exemptionCensus()}`,
  )
  console.log(
    '  That is not a claim that no unit defect exists. A resolved-set helper that\n' +
      '  collapses INTERNALLY and a forced-unit template have no lexical form here;\n' +
      '  they are reviewed in scripts/units.manifest.json, which is what the phase\n' +
      '  promises instead.',
  )
}

main()
