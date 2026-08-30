import { describe, it, expect } from 'vitest'
import { execFileSync } from 'node:child_process'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import * as ts from 'typescript'

/**
 * No binary unit API outlives its last production caller.
 *
 * ★ WHY THIS IS A TEST AND NOT A COMMENT. Plan 3b ruling R2 keeps
 * `utils/units.ts` and asks for a decision PER OCCURRENCE: migrate the
 * internals, or exempt with a stated reason. Sixteen of the units gate's 43
 * comparison occurrences live here, and they are not sixteen scattered
 * ternaries: each one is the body of exactly one static `UnitFormatter` method
 * whose parameter is a `UnitSystem`. So the decision per occurrence is really a
 * decision per method, and there are only two honest answers.
 *
 * A method with production callers is exempt for as long as it has them, and
 * the units gate already reports every one of those call sites under its
 * `formatter-binary` leg, so the migration is somebody's tracked work. A method
 * with NO production callers is not exempt: it is a loaded trap. `system` is
 * collapsed from VOLUME (spec D8, `useUnitPreference.ts:98`), so the next
 * developer who reaches for `UnitFormatter.formatTemperature(c, system)` gets
 * degrees Celsius for a `{volume:'L', temperature:'f'}` user, and neither gate
 * leg complains: the comparison is in here, not at their call site, and their
 * call site is a brand-new `formatter-binary` finding that only shows up as
 * baseline growth long after they wrote it.
 *
 * So the exemption carries a CONDITION, and this test is the condition. R1 asks
 * for exemptions that are structural rather than prose, because the gate's
 * `// units-exempt(<kind>):` pragma accepts any reason-bearing comment
 * (`EXEMPT_PRAGMA` in `validate-units.ts`). The pragmas on the survivors say why; this says
 * when they expire. When task 6 migrates the last `formatDistance(km, system)`
 * call site, this test fails and the method has to go.
 *
 * ★ AST, NOT `grep`, and the difference is not theoretical. `TireList.tsx:410`
 * carries the comment "Through the adapter, not UnitFormatter.formatPressure",
 * and `unitAdapters.ts:171` says "`UnitFormatter.getTemperatureUnit` still
 * does". A text scan reads both as call sites and reports two dead methods as
 * live, which is this test failing open on exactly the two methods it exists to
 * catch. Property accesses come from the parser, so a mention in prose is not a
 * caller.
 */

const FRONTEND = resolve(__dirname, '../../..')
const SRC = resolve(FRONTEND, 'src')
const UNITS = resolve(SRC, 'utils/units.ts')
const DECIMAL_SAFE = resolve(SRC, 'utils/decimalSafe.ts')

/** The class whose binary surface this test polices. */
const FORMATTER_CLASS = 'UnitFormatter'


/**
 * ★ THE REIMPLEMENTED PREDICATE THAT USED TO SIT HERE IS DELETED, and why is
 * fix round 1's main lesson. This file carried a second copy of the gate's
 * `takesBinarySystem` plus its alias resolution, its props-type walk and its
 * pragma reader, and asserted PARITY between the two. That reads like
 * independence and was not: both copies gated on `ExportKeyword` +
 * `isFunctionDeclaration`, so both were blind to module-local helpers, exported
 * arrow consts and instance methods, and they agreed because they shared one
 * floor. Five such declarations were live on the supplies path with ten call
 * sites while the parity assertion printed a tick.
 *
 * Two derivations agreeing because they share one floor is a parity check that
 * cannot fail. What replaced it is a COMMITTED FIXTURE SET (see
 * `what the units gate is silent about` below): the gate's own enumeration,
 * pinned to exact lists written by hand, plus a cross-check against the
 * manifest, which a different program maintains and validates.
 *
 * What survives here are the two RECEIPTS, and they need no predicate: the
 * exact list of static methods `UnitFormatter` declares and the exact list of
 * functions `decimalSafe.ts` exports. Those are what make the gate's empty
 * vocabulary mean something rather than mean nothing.
 */

/**
 * The runtime to re-run the gate under.
 *
 * `bun run test:run` makes `process.execPath` the bun binary, which is the one
 * CI uses; the bare name is the fallback for any other runner.
 */
const BUN = /(?:^|[\\/])bun(?:\.exe)?$/.test(process.execPath) ? process.execPath : 'bun'

/**
 * The same set, derived a second time by `scripts/validate-units.ts --derived`.
 *
 * ★ WHY PARITY AND NOT "DERIVE ONE FROM THE OTHER". This file walks the AST of
 * `units.ts` and so does `validate-units.ts:deriveBinaryFormatterMethods`, in a
 * different language, and two implementations of one rule with nothing tying
 * them together is the shape this workstream has spent twenty-two instances
 * learning to distrust. Consuming the gate's answer here would remove the
 * duplication but also the independence: a change that narrowed the GATE's
 * derivation would narrow this test in the same breath and nothing would say
 * so. Asserting they AGREE catches drift in either direction, which is the
 * property actually wanted, and the run costs 0.2 s.
 *
 * @returns The method names the gate derives, sorted.
 */
function gateDerivedSet(label: string): string[] {
  const out = execFileSync(BUN, ['run', 'scripts/validate-units.ts', '--derived'], {
    cwd: FRONTEND,
    encoding: 'utf-8',
  })
  const line = new RegExp(`^${label} \\((\\d+)\\): (.*)$`, 'm').exec(out)
  if (line === null) {
    // A silent zero here would make the parity assertion vacuously true, which
    // is the failure this file exists one level down to prevent. It also covers
    // the empty conversion set: the gate prints `(0): ` and that line still has
    // to BE THERE, so a gate that stopped deriving the set at all is not
    // mistaken for one that derived it and found nothing.
    throw new Error(`could not read the gate's ${label} from:\n${out}`)
  }
  const names = line[2]
    .split(',')
    .map((name) => name.trim())
    .filter((name) => name.length > 0)
  if (names.length !== Number(line[1])) {
    throw new Error(`the gate said ${line[1]} ${label} and listed ${names.length}`)
  }
  return [...names].sort()
}

/**
 * Parse one file, refusing to report a file the parser choked on as clean.
 *
 * Same fail-loud posture as `scripts/validate-units.ts:scanSource`: a rejected
 * file yields no property accesses at all, which this test would otherwise read
 * as "nobody calls anything in here".
 */
function parse(path: string): ts.SourceFile {
  const text = readFileSync(path, 'utf-8')
  const kind = path.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS
  const source = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, kind)
  // `parseDiagnostics` is real but internal, so it is not on the public type.
  // Narrowed rather than cast to `any`, and absent is a HARD failure: a build
  // that exposes none would make a rejected file look like a clean one, which
  // is the same trap `validate-units.ts:loadTypeScript` refuses to walk into.
  const { parseDiagnostics } = source as ts.SourceFile & {
    parseDiagnostics?: readonly ts.Diagnostic[]
  }
  if (parseDiagnostics === undefined) {
    throw new Error('this TypeScript build exposes no parseDiagnostics; refusing to scan')
  }
  if (parseDiagnostics.length > 0) {
    throw new Error(`${relative(FRONTEND, path)}: ${parseDiagnostics.length} parse error(s)`)
  }
  return source
}

/**
 * The static method names `UnitFormatter` declares.
 *
 * ★ A RECEIPT, NOT A PREDICATE. It enumerates the class's whole static surface
 * by name and asks nothing about types, so it cannot share a floor with the
 * gate: a walk that had silently stopped visiting the class returns an empty
 * list and the assertion below fails first, with a name to look at.
 */
function formatterStatics(): string[] {
  const source = parse(UNITS)
  const statics = new Set<string>()
  const walk = (node: ts.Node): void => {
    if (ts.isClassDeclaration(node) && node.name?.text === FORMATTER_CLASS) {
      for (const member of node.members) {
        if (!ts.isMethodDeclaration(member)) continue
        if ((member.modifiers ?? []).some((m) => m.kind === ts.SyntaxKind.StaticKeyword)) {
          statics.add(member.name.getText(source))
        }
      }
    }
    ts.forEachChild(node, walk)
  }
  walk(source)
  return [...statics].sort()
}

/**
 * The names `decimalSafe.ts` exports as functions. The conversion leg's receipt,
 * for the same reason and with the same independence.
 */
function decimalSafeExports(): string[] {
  return exportedFunctions(DECIMAL_SAFE)
}

/**
 * Every production `.ts`/`.tsx` under `src/`, minus tests and units.ts itself.
 *
 * units.ts is excluded because a method calling a sibling on its own class is
 * not a production CALLER of the binary API: `formatVolumeTotal` delegating to
 * `formatVolumeShort` would keep a dead method looking alive.
 */
function productionSources(): string[] {
  const out: string[] = []
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir).sort()) {
      if (entry === '__tests__' || entry === 'node_modules') continue
      const path = join(dir, entry)
      if (statSync(path).isDirectory()) {
        walk(path)
        continue
      }
      if (!/\.tsx?$/.test(entry) || /\.test\.tsx?$/.test(entry)) continue
      if (path === UNITS) continue
      out.push(path)
    }
  }
  walk(SRC)
  return out
}

/** Files where `<className>.<method>` is actually accessed, by method. */
function callersByMethod(methods: string[], className = FORMATTER_CLASS): Map<string, string[]> {
  const wanted = new Set(methods)
  const callers = new Map<string, string[]>(methods.map((m) => [m, []]))
  for (const path of productionSources()) {
    const source = parse(path)
    const walk = (node: ts.Node): void => {
      if (
        ts.isPropertyAccessExpression(node) &&
        ts.isIdentifier(node.expression) &&
        node.expression.text === className &&
        wanted.has(node.name.text)
      ) {
        const seen = callers.get(node.name.text)!
        const rel = relative(FRONTEND, path)
        if (!seen.includes(rel)) seen.push(rel)
      }
      ts.forEachChild(node, walk)
    }
    walk(source)
  }
  return callers
}

/** The class holding the instance-driven gallon and MPG factors. */
const CONVERTER_CLASS = 'UnitConverter'

/** The two mutable statics that carry defect L1's mechanism. */
const MUTABLE_GALLON_FACTORS = ['gallonsToLitersFactor', 'mpgToL100kmFactor']

/** Every exported function DECLARATION of one module, sorted. */
function exportedFunctions(path: string): string[] {
  const source = parse(path)
  const names = new Set<string>()
  const walk = (node: ts.Node): void => {
    if (
      ts.isFunctionDeclaration(node) &&
      node.name !== undefined &&
      (node.modifiers ?? []).some((m) => m.kind === ts.SyntaxKind.ExportKeyword)
    ) {
      names.add(node.name.text)
    }
    ts.forEachChild(node, walk)
  }
  walk(source)
  return [...names].sort()
}

/**
 * Every `UnitConverter` static that touches the mutable gallon factors.
 *
 * ★ TRANSITIVELY, and that is the whole reason this is derived rather than
 * listed. `lPer100kmToMpg` names neither factor: it delegates to
 * `l100kmToMpg`, which does. A list built by grepping the factor names is a
 * FLOOR, and this workstream has produced sixteen of those; a list built by
 * hand is worse. So a method touches the factors when it names one OR calls a
 * sibling that does, iterated to a fixpoint.
 */
function factorTouchers(): string[] {
  const source = parse(UNITS)
  const mentions = new Map<string, boolean>()
  const calls = new Map<string, Set<string>>()
  const walk = (node: ts.Node): void => {
    if (ts.isClassDeclaration(node) && node.name?.text === CONVERTER_CLASS) {
      for (const member of node.members) {
        if (!ts.isMethodDeclaration(member)) continue
        if (!(member.modifiers ?? []).some((m) => m.kind === ts.SyntaxKind.StaticKeyword)) continue
        const name = member.name.getText(source)
        let direct = false
        const siblings = new Set<string>()
        const body = (child: ts.Node): void => {
          if (ts.isIdentifier(child) && MUTABLE_GALLON_FACTORS.includes(child.text)) direct = true
          if (
            ts.isPropertyAccessExpression(child) &&
            (child.expression.kind === ts.SyntaxKind.ThisKeyword ||
              (ts.isIdentifier(child.expression) && child.expression.text === CONVERTER_CLASS))
          ) {
            siblings.add(child.name.text)
          }
          ts.forEachChild(child, body)
        }
        ts.forEachChild(member, body)
        mentions.set(name, direct)
        calls.set(name, siblings)
      }
    }
    ts.forEachChild(node, walk)
  }
  walk(source)
  if (mentions.size === 0) {
    throw new Error(`walked ${CONVERTER_CLASS} and saw no static method; refusing to conclude`)
  }
  for (let pass = 0; pass < mentions.size; pass += 1) {
    let grew = false
    for (const [name, touches] of mentions) {
      if (touches) continue
      if ([...(calls.get(name) ?? [])].some((s) => mentions.get(s) === true)) {
        mentions.set(name, true)
        grew = true
      }
    }
    if (!grew) break
  }
  return [...mentions].filter(([, t]) => t).map(([n]) => n).sort()
}

describe('the mutable gallon statics (plan 3b task 8)', () => {
  it('★ keeps the converter-gallon subscription deleted', () => {
    // ★ THE RE-ADD MUTATION, and the receipt that makes it fire. Task 8 deleted
    // a closed loop: `hooks/useResolvedGallonSync.ts` wrote the factors below,
    // `subscribeToConverterGallon` / `getConverterGallon` /
    // `getConverterGallonServerSnapshot` published them, and one
    // `useSyncExternalStore` in `useUnitPreference` subscribed and discarded the
    // value. Nothing has rendered off those factors since task 6b, so the sync
    // ran on every load and nothing read what it wrote.
    //
    // Neither units gate can see a subscription, so nothing else would notice it
    // coming back. This enumerates the module's whole exported-function surface,
    // which is what makes re-adding any of the three fail here.
    expect(exportedFunctions(UNITS)).toEqual(['detectUnitSystemFromTimezone'])
  })

  it('★ leaves NO production caller on the factor surface at all', () => {
    // ★ DEFECT L1's MECHANISM, enumerated rather than asserted about. These are
    // the statics whose answer moves with the INSTANCE gallon setting, which is
    // what made a `gal_uk` account store 10 gal as 37.85 L.
    //
    // ★ THE LIST WAS `['setGallonStandard']` UNTIL PHASE 4 TASK 5, and the one
    // caller was `utils/gallonStandardStore.ts`, which wrote these factors from
    // the instance setting while nothing read them. Task 5 deleted that store
    // and `hooks/useGallonStandardSync.ts` with it, so the mutable fields below
    // now have no writer in production and the six methods that read them no
    // caller: the whole apparatus is dead to the app and live only to the tests
    // that still set a flavour before asserting a conversion.
    //
    // ★ WHICH LEAVES A STATED RESIDUAL rather than a silent one. Deleting the
    // mutable statics and their six methods outright rewrites nine unrelated
    // test files whose `UnitConverter.setGallonStandard('us')` lines are
    // deliberate defect-L1 guards, so task 5 stopped at the store and recorded
    // the emptiness here instead. `[]` is not a weaker assertion than the old
    // one: a name reappearing on this line is a module that has started
    // rendering off process-global state again, which is the defect rather than
    // a style point, and it is also the day the deleted repaint loop would be
    // needed again.
    const touchers = factorTouchers()
    expect(touchers).toEqual([
      'gallonsToLiters',
      'getGallonStandard',
      'l100kmToMpg',
      'lPer100kmToMpg',
      'litersToGallons',
      'mpgToL100km',
      'setGallonStandard',
      'toCanonicalMetricString',
    ])
    const live = [...callersByMethod(touchers, CONVERTER_CLASS)]
      .filter(([, files]) => files.length > 0)
      .map(([name]) => name)
    expect(live).toEqual([])

    // ★ AND THE RECEIPT THE EMPTY LIST NEEDS, because emptying it took this
    // file's only one away. While the pin read `['setGallonStandard']` the
    // NON-empty answer was itself the proof that `productionSources()` walks
    // anything and that `callersByMethod` finds a caller: make either return
    // nothing and the assertion above still passes, along with every other case
    // in this file. So the same walk and the same scan are pointed at the class
    // that emphatically still has callers. `[]` above means "nothing calls the
    // factor surface" only while this passes; without it, it means "the scanner
    // is broken" just as readily.
    expect(productionSources().length).toBeGreaterThan(200)
    const formatterCallers = [...callersByMethod(formatterStatics())]
      .filter(([, files]) => files.length > 0)
      .map(([name]) => name)
    expect(formatterCallers.length).toBeGreaterThan(0)
  })
})


/**
 * The gate's own enumeration of everything it is deliberately silent about.
 *
 * @param label The section heading in `--suppressions` output.
 * @returns The indented lines under it, trimmed.
 */
/**
 * The gate's `--suppressions` output, run once per file rather than per call.
 *
 * ★ WHY THIS IS MEMOISED, and it is a correctness-preserving change, not a
 * shortcut. Each call shells out to a FULL units-gate walk of the tree, and
 * this file makes four calls, so the file paid for four whole gate runs. That
 * cost 3.9 s on a fast host and **timed out CI's 5 s budget** on `f5a4106`,
 * failing the Frontend Tests job. The output is a pure function of the tree,
 * which does not change mid-file, so one run answers every caller identically.
 *
 * The receipt this file depends on is unaffected: `gateSuppressions` still
 * throws when the named section is missing, and it throws on the first call
 * exactly as it did before.
 */
let suppressionsOutput: string | null = null

function suppressionsRun(): string {
  suppressionsOutput ??= execFileSync(
    BUN,
    ['run', 'scripts/validate-units.ts', '--suppressions'],
    { cwd: FRONTEND, encoding: 'utf-8' }
  )
  return suppressionsOutput
}

function gateSuppressions(label: string): string[] {
  const out = suppressionsRun()
  const lines = out.split('\n')
  const head = lines.findIndex((l) => l.startsWith(`${label} (`))
  if (head === -1) {
    // A silent empty list here would make every assertion below vacuously
    // true, which is the failure this whole file exists one level down to
    // prevent.
    throw new Error(`--suppressions printed no ${label} section:\n${out}`)
  }
  const body: string[] = []
  for (let i = head + 1; i < lines.length && lines[i].startsWith('   '); i += 1) {
    body.push(lines[i].trim())
  }
  return body
}

/** Files the units manifest has reviewed and dispositioned as `audited`. */
function auditedPaths(): Set<string> {
  const manifest = JSON.parse(
    readFileSync(resolve(FRONTEND, 'scripts/units.manifest.json'), 'utf-8')
  ) as { rows: { path: string; disposition: string }[] }
  const audited = new Set(
    manifest.rows.filter((r) => r.disposition === 'audited').map((r) => r.path)
  )
  if (audited.size === 0) throw new Error('the manifest lists no audited row; refusing to conclude')
  return audited
}

describe('what the units gate is silent about (plan 3b task 8, fix round 1)', () => {
  /**
   * ★ WHY THIS BLOCK NO LONGER WALKS THE TREE ITSELF, and it is fix round 1's
   * main lesson. It used to run its own AST walk and assert PARITY with the
   * gate's, which reads like independence and was not: both walks gated on
   * `ExportKeyword` + `isFunctionDeclaration`, so both missed module-local
   * helpers, exported arrow consts and instance methods, and they agreed
   * because they shared one floor. Five such declarations were live on the
   * supplies path with ten call sites while this block printed a tick.
   *
   * Two derivations agreeing because they share one floor is a parity check
   * that cannot fail. A second walk written by the same hand from the same
   * mental model is not a second opinion, and a broader walk is not obviously
   * available either: a text scan of parameter annotations misses `PurchaseRow`,
   * whose props type is a named interface one line up.
   *
   * So the shape changed rather than being patched. What is asserted here is a
   * COMMITTED FIXTURE SET: the gate's own enumeration of every suppression it
   * applies, pinned to an exact list. It cannot pass by sharing a floor because
   * there is only one derivation and a hand-written expectation beside it. What
   * it cannot do is see a declaration the GATE never sees, and nothing short of
   * a genuinely independent implementation could; that residual is stated here
   * rather than papered over with a second copy of the same predicate.
   *
   * The independent half is `a reviewed row stands behind every one`: the
   * manifest is maintained by hand and checked by a different program, so a
   * suppression with no reviewed row behind it fails without this file having
   * an opinion about the AST at all.
   */
  it('★ suppresses exactly these binary declarations, and one line silences many files', () => {
    // A `// units-exempt(binary-conversion):` on a DECLARATION removes it from
    // the vocabulary, and with it every reference to it in every module: 29
    // sites for the twelve below, which `--suppressions` prints as
    // HIDDEN_BY_DECLARATION. That is the right shape for one deferred ruling
    // (R3, pending the D8 amendment that would give supplies a resolved token)
    // and the wrong shape to let grow unnoticed.
    //
    // A thirteenth entry is a thirteenth binary API somebody exempted. Read the
    // pragma's reason before widening this list.
    expect(gateSuppressions('EXEMPT_BINARY_DECLARATIONS')).toEqual([
      'src/components/ServiceVisitForm.tsx::convertSupplyUsages',
      'src/components/SuppliesUsedTab.tsx::formatQuantity',
      'src/components/SupplyHistoryModal.tsx::AdjustmentForm',
      'src/components/SupplyHistoryModal.tsx::PurchaseForm',
      'src/components/SupplyHistoryModal.tsx::PurchaseRow',
      'src/components/SupplyHistoryModal.tsx::UsageRow',
      'src/components/SupplyHistoryModal.tsx::formatMagnitude',
      'src/components/SupplyHistoryModal.tsx::formatQuantity',
      'src/components/SupplyHistoryModal.tsx::formatSignedQuantity',
      'src/utils/supplyUnits.ts::canonicalToDisplay',
      'src/utils/supplyUnits.ts::displayToCanonical',
      'src/utils/supplyUnits.ts::supplyUnitLabel',
    ])
  })

  it('★ suppresses exactly these lines, which had only a printed integer before', () => {
    // The review's judgement on the flip's own concern 5: printing a count is
    // necessary and not sufficient. The declarations above were held by an
    // exact list; the line-level pragmas were held by an integer nothing
    // asserted on. Same pin, same reason.
    expect(gateSuppressions('PRAGMA_SUPPRESSED')).toEqual([
      // ★ Phase 4 task 4 moved the settings screen's unit block out of
      // `SettingsSystemTab.tsx` into these two files, and the count went DOWN
      // by one rather than across unchanged. Three comparisons left that file:
      // the gallon panel's visibility, which landed on the card, and the two
      // preset-selection comparisons, which are gone as findings entirely. The
      // tri-state control derives its highlight from `preference === candidate`,
      // an identifier against a loop variable, so there is no unit literal for
      // the gate to see and nothing left to suppress. What is on the editor is
      // the R4 warning's own `pendingPreset === 'imperial'`, which is a
      // question about which button was pressed.
      //
      // ★ AND `UnitPreferencesCard.tsx` HAS NOW LEFT THIS LIST ENTIRELY, in
      // task 5. Its one remaining pragma excused the gallon panel's visibility,
      // and the panel it excused is deleted with the instance setting it wrote:
      // `InstanceUnitDefaultsCard.tsx` writes the whole `default_unit_prefs` set
      // instead, through the same eleven controls, and needs no comparison of a
      // unit token to decide what to show. The count went DOWN by one again,
      // which is the direction this list is supposed to move.
      'src/components/settings/UnitSetEditor.tsx::compare x1',
      'src/types/units.ts::token-branch x1',
      // Phase 4 task 3 MOVED this pair out of `useUnitPreference.ts`, which no
      // longer parses the legacy `unit_preference` key: the browser store owns
      // that read now, and the pragma travelled with the two comparisons it
      // excuses. Same reason, same count, different file.
      'src/utils/publicUnitDefaults.ts::token-branch x2',
      'src/utils/supplyUnits.ts::compare x3',
      'src/utils/unitPrefsStore.ts::compare x2',
      'src/utils/units.ts::token-branch x5',
    ])
  })

  it('★ a reviewed manifest row stands behind every suppression', () => {
    // ★ THE INDEPENDENT HALF, and the replacement for the mechanism the flip
    // retired. Emptying the baseline removed the units gate's cross-check on
    // manifest findings; this restores a two-mechanism hold in the direction
    // the flip actually opened, which is a suppression added in code with no
    // reviewed row behind it. The manifest is maintained by hand and validated
    // by a different program, so this fails without any opinion about the AST.
    const audited = auditedPaths()
    const suppressed = [
      ...gateSuppressions('EXEMPT_BINARY_DECLARATIONS'),
      ...gateSuppressions('PRAGMA_SUPPRESSED'),
    ].map((entry) => entry.split('::')[0])
    expect([...new Set(suppressed)].filter((path) => !audited.has(path)).sort()).toEqual([])
  })
})

// ★ THE PER-FILE PARITY ASSERTIONS MOVED UP, RATHER THAN BEING DROPPED. Each
// describe below used to open by comparing its own single-file `binary` set
// against the gate's derived set of the same name. Task 8 made the gate's sets
// TREE-WIDE, so those two comparisons now hold two different universes side by
// side and agree only while both are empty, which is the shape of an assertion
// that stops meaning anything without failing. The tree-wide walk includes both
// of these files, so `the tree-wide binary surface` above asserts strictly more
// than they did. What stays here is what only a single-file walk can say: the
// RECEIPT that the walk visited the file at all, and the emptiness that receipt
// makes meaningful.
describe('the binary UnitFormatter surface', () => {
  it('still reads the static methods, so the empty set below means something', () => {
    // The receipt. Task 2 deleted the seven binary methods that no production
    // file called, leaving nine; task 3 moved PropaneRecordForm onto the mass
    // adapter, which retired `getWeightUnit`; task 6 migrated the twenty-seven
    // call sites of `formatDistance` and `getDistanceUnit`; task 6b the
    // thirty-one of the fuel-economy and fuel-rate family; task 7 the five of
    // `formatCostPerDistance` and `getCostPerDistanceLabel`. Each time this
    // file failed FIRST and the methods followed.
    //
    // What survives on the class is the resolved-set surface, and pinning it is
    // what stops the assertion after this one going vacuous.
    // ★ TWO NAMES LEFT THIS LIST IN FIX ROUND 1, and how they were found is the
    // point. `formatVolumeTotal` and `getCostPerVolumeLabel` each glued an
    // ENGLISH WORD to a unit symbol and rendered in summary cards with no
    // `t()`, so task 7 translated the cost-per-distance caption one card to the
    // right of an untranslated one. The receipt below is where a reader could
    // have seen them: it enumerates this class's whole surviving surface by
    // name, which is what a receipt is for. Every name left returns a number, a
    // currency string or a bare unit symbol; none returns prose.
    expect(formatterStatics()).toEqual([
      'formatCostPerVolume',
      'formatVolume',
      'formatVolumeShort',
      'getMassUnit',
      'getVolumeUnit',
    ])
  })

  it('★ contributes no binary method to the gate\'s vocabulary, and keeps no dead one', () => {
    // ★ EMPTY IS THE GOAL STATE, reached by task 7. Every method on this class
    // now takes the resolved `UnitSet`. A `UnitSystem` parameter added back
    // here puts the method into the gate's derived vocabulary and fails this
    // line one step before a call site can exist.
    //
    // ★ THE ANSWER COMES FROM THE GATE, not from a second walk written here.
    // Fix round 1 deleted this file's copy of the predicate: it agreed with the
    // gate because it shared the gate's floor, which is a parity check that
    // cannot fail. The receipt above is what makes this emptiness mean
    // something, and it needs no predicate to compute.
    const binary = gateDerivedSet('BINARY_FORMATTER_METHODS')
    expect(binary).toEqual([])

    // And the rule that emptied it, kept live for whatever is added next: a
    // binary method with no caller left is not dead code to tidy up later, it
    // is a `system` parameter waiting for somebody to pass it a value collapsed
    // from volume. Delete it, and reach for `useUnitFormat()` /
    // `makeUnitFormat()` instead.
    const callers = callersByMethod(binary)
    const dead = [...callers].filter(([, files]) => files.length === 0).map(([name]) => name)
    expect(dead).toEqual([])
  })
})

describe('the binary conversion surface', () => {
  it('still reads the exported helpers, so the empty set below means something', () => {
    // The receipt. This list is what a healthy walk over this file sees; if it
    // ever comes back empty, the assertion after it proves nothing at all.
    //
    // ★ IT MOVED IN PLAN 3b TASK 7, AND WHAT MOVED IS A SECOND DEFECT CLASS ON
    // THE SAME FILE. `toCanonicalLiters` and `priceToCanonical` were the two
    // exports that converted a DISPLAY value straight to canonical. That is
    // correct for a field the user edited and is the entry-grid shift (ruling
    // R4) for one they did not: the field had been seeded with a rounded
    // display and the submit reconverted the rounding, moving 16 of 27 measured
    // price combinations and 13 of 27 volume ones. Neither is exported now.
    // Volume goes through the quantity protocol plus `toLitersWirePrecision`,
    // which rounds and does not convert; price goes through `seedPriceField` /
    // `canonicalFromPriceField`, the price mirror of that protocol, behind
    // which the old converter is module-private.
    //
    // ★ THIS RECEIPT IS NOW A FLOOR'S WIDTH NARROWER THAN THE GATE, and saying
    // so is the point. It lists exported FUNCTION declarations, because that is
    // what this file exports; the gate's vocabulary since fix round 1 also
    // covers exported arrow consts and module-local declarations. If
    // `decimalSafe.ts` ever grows one of those, this list will not see it and
    // the committed suppression set above is what would.
    expect(decimalSafeExports()).toEqual([
      'canonicalFromPriceField',
      'priceToDisplay',
      'readNumber',
      'seedPriceField',
      'toLitersWirePrecision',
    ])
  })

  it('contributes no conversion helper that writes canonical off a collapsed system', () => {
    // ★ Ruling R8, and the phase's signature defect in its final form.
    // `toCanonicalKm(value, system)` had no numeric literal and no
    // `UnitFormatter` call at its call site, so the units gate's original two
    // legs were blind to the function WRITING the wrong number: a
    // `{volume:'L', distance:'mi'}` user collapses to `system === 'metric'`,
    // and 500 miles was stored as 500 km instead of 804.67.
    //
    // R8 offered detection or deletion. Task 5 took deletion, because deletion
    // makes the bad call inexpressible rather than merely reported, and this is
    // the assertion that keeps it deleted: re-adding `toCanonicalKm`,
    // `toCanonicalKg`, `toCanonicalMeters` or a `toCanonicalFathoms` nobody has
    // thought of yet fails here on the DECLARATION, one step before a call site
    // can exist.
    //
    // The replacement is the origin-preserving pair in `utils/unitFormat.ts`:
    // `seedUnitField(canonical, quantity)` and
    // `canonicalFromUnitField(typed, origin, quantity)`. `toCanonicalLiters`
    // survives in the same file and is not an oversight: it takes the resolved
    // `UnitSet`, which is the correct shape.
    expect(gateDerivedSet('BINARY_CONVERSION_HELPERS')).toEqual([])
  })
})
