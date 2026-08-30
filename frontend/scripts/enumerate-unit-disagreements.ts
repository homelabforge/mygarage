#!/usr/bin/env bun
/**
 * Where one screen renders two quantities that disagree about who decides.
 *
 * ★ WHAT A DISAGREEMENT IS. Phase 3b migrates the frontend off a binary
 * `UnitSystem` (collapsed from VOLUME, spec D8) onto per-quantity resolved
 * tokens, one family at a time. Mid-migration, a file can hold both: task 6
 * moved DISTANCE and left consumption, so `VehicleStatisticsCard.tsx` rendered
 * an odometer through `u.distance` and a fuel-economy row through
 * `formatFuelEconomy(l, system)` as adjacent `ListRow`s on ONE card. For a
 * `{volume:'L', distance:'mi'}` account that card said `12,345 mi` above
 * `7.2 L/100km`: two unit systems, one card, and neither reading wrong on its
 * own. That is the defect this enumerator measures.
 *
 * ★ WHY IT CONSUMES THE GATE RATHER THAN RE-DERIVING IT. The binary half of
 * the question is exactly `scripts/validate-units.ts`'s work list, and this
 * workstream has paid repeatedly for two implementations of one rule. So the
 * binary side comes from the gate itself, through its own `--report` and
 * `--scan` output, and the run is a receipt: the file list is cross-checked
 * against the gate's own total and a mismatch is a hard refusal, because a
 * parse that silently read nothing would report a tree with no disagreements.
 *
 * ★ THE SYMMETRIC DERIVATION IS THE POINT. The gate calls an API binary when a
 * parameter's type is `UnitSystem`. This calls one RESOLVED when a parameter's
 * type is `UnitSet`, read out of the same two source files. Neither list is
 * typed out here, so an API added to either side appears without anybody
 * remembering to add it, and a derivation that emptied fails loudly instead of
 * reporting a clean tree.
 *
 * ★ TWO ANSWERS, BOTH PRINTED, BECAUSE HALF AN INVENTORY IS WORSE THAN NONE.
 * The FILE answer is exact: one module rendering both. The SCREEN answer is a
 * deliberate over-approximation: every module transitively imported by a page
 * counts as on that screen, whether or not it is mounted on any given render.
 * A superset is the safe direction for a work list, and the two are labelled so
 * a reader can tell an exact hit from a reachable one.
 *
 * Usage:
 *   bun run scripts/enumerate-unit-disagreements.ts          # the enumeration
 *   bun run scripts/enumerate-unit-disagreements.ts --json   # machine-readable
 * Exit code: 0 always. A measuring instrument, not a gate.
 */

import { execFileSync } from 'child_process'
import { createRequire } from 'module'
import { readdirSync, readFileSync, statSync, existsSync } from 'fs'
import { join, relative, resolve, dirname, sep } from 'path'
import type * as TS from 'typescript'
import { ROOT } from './translation-utils'

/**
 * The real TypeScript compiler API, resolved through the package's own `main`.
 *
 * Same hazard and same fix as `scripts/validate-units.ts:loadTypeScript`: a
 * bare `typescript` specifier can resolve to an auto-install stub whose
 * `createSourceFile` is `undefined`, and every scan then reports zero.
 *
 * @returns The compiler API, proven to expose the parts used below.
 */
function loadTypeScript(): typeof TS {
  const require = createRequire(import.meta.url)
  const pkgDir = join(ROOT, 'node_modules', 'typescript')
  const main = JSON.parse(readFileSync(join(pkgDir, 'package.json'), 'utf-8')).main as string
  const api = require(join(pkgDir, main)) as typeof TS
  if (typeof api.createSourceFile !== 'function' || !api.SyntaxKind?.BinaryExpression) {
    throw new Error('typescript did not expose createSourceFile/SyntaxKind. Refusing to run.')
  }
  return api
}

const ts = loadTypeScript()
const SRC = join(ROOT, 'src')
const PAGES = join(SRC, 'pages')
const UNITS_SOURCE = join(SRC, 'utils', 'units.ts')
const FORMAT_SOURCE = join(SRC, 'utils', 'unitFormat.ts')
const QUANTITY_SOURCE = join(SRC, 'types', 'units.ts')
const GATE = 'scripts/validate-units.ts'

/** The parameter annotation that makes an API a RESOLVED per-quantity one. */
const RESOLVED_SET_TYPE = 'UnitSet'

/** The bun binary to re-run the gate under, matching `unitsBinaryApiSurface`. */
const BUN = /(?:^|[\\/])bun(?:\.exe)?$/.test(process.execPath) ? process.execPath : 'bun'

/**
 * POSIX-style path relative to the frontend root.
 *
 * @param absolute An absolute path inside the tree.
 * @returns The relative path, with forward slashes on every platform.
 */
function rel(absolute: string): string {
  return relative(ROOT, absolute).split(sep).join('/')
}

/**
 * Parse one file, refusing to report a file the parser choked on as clean.
 *
 * @param path The file to parse.
 * @returns The parsed source file.
 */
function parse(path: string): TS.SourceFile {
  const text = readFileSync(path, 'utf-8')
  const kind = path.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS
  const source = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, kind)
  const { parseDiagnostics } = source as TS.SourceFile & {
    parseDiagnostics?: readonly TS.Diagnostic[]
  }
  if (parseDiagnostics === undefined) {
    throw new Error(`${rel(path)}: this TypeScript build exposes no parseDiagnostics`)
  }
  if (parseDiagnostics.length > 0) {
    throw new Error(`${rel(path)}: ${parseDiagnostics.length} parse error(s)`)
  }
  return source
}

/**
 * The ten quantity names, read out of `types/units.ts`'s own list.
 *
 * @returns Every name `UNIT_QUANTITIES` declares.
 */
function quantityNames(): Set<string> {
  const source = parse(QUANTITY_SOURCE)
  const names = new Set<string>()
  const walk = (node: TS.Node): void => {
    if (
      ts.isVariableDeclaration(node) &&
      ts.isIdentifier(node.name) &&
      node.name.text === 'UNIT_QUANTITIES' &&
      node.initializer !== undefined
    ) {
      const collect = (n: TS.Node): void => {
        if (ts.isStringLiteralLike(n)) names.add(n.text)
        ts.forEachChild(n, collect)
      }
      collect(node.initializer)
    }
    ts.forEachChild(node, walk)
  }
  walk(source)
  if (names.size === 0) {
    throw new Error(
      `${rel(QUANTITY_SOURCE)} yielded no UNIT_QUANTITIES names. Every u.<quantity> read ` +
        'would go unseen and the tree would look fully binary. Refusing to run.',
    )
  }
  return names
}

/**
 * Whether a declaration takes a resolved `UnitSet` parameter.
 *
 * The mirror of `validate-units.ts:takesBinarySystem`, and deliberately the
 * same shape: the two sides of this enumeration are "who decides", and both
 * answers are spelled in a parameter's type.
 *
 * @param node The declaration to test.
 * @param source The enclosing source file.
 * @returns True when some parameter is annotated `UnitSet`.
 */
function takesResolvedSet(
  node: { parameters?: TS.NodeArray<TS.ParameterDeclaration> },
  source: TS.SourceFile,
): boolean {
  return (node.parameters ?? []).some(
    (p) => p.type?.getText(source).trim() === RESOLVED_SET_TYPE,
  )
}

/**
 * Every API that decides through a resolved `UnitSet`, by name.
 *
 * Two sources, because the migration has two destinations: the surviving
 * `UnitFormatter` statics that already take a set (`formatVolume`,
 * `getMassUnit`, ...) and the composition layer's exported functions
 * (`formatVolumePerDistance`, `volumePerDistanceLabel`, ...).
 *
 * @returns The resolved API names, and a per-file receipt of the walk.
 */
function resolvedApiNames(): { names: Set<string>; byFile: Record<string, string[]> } {
  const byFile: Record<string, string[]> = {}
  const names = new Set<string>()

  const unitsSource = parse(UNITS_SOURCE)
  const fromUnits: string[] = []
  const walkUnits = (node: TS.Node): void => {
    if (
      ts.isMethodDeclaration(node) &&
      (node.modifiers ?? []).some((m) => m.kind === ts.SyntaxKind.StaticKeyword) &&
      takesResolvedSet(node, unitsSource)
    ) {
      fromUnits.push(node.name.getText(unitsSource))
    }
    ts.forEachChild(node, walkUnits)
  }
  walkUnits(unitsSource)

  // Exported only: `quantityFormat` is module-local scaffolding for
  // `makeUnitFormat` and no call site outside the file can name it, so counting
  // it would inflate the vocabulary with something nothing can call.
  const formatSource = parse(FORMAT_SOURCE)
  const fromFormat: string[] = []
  const walkFormat = (node: TS.Node): void => {
    if (
      ts.isFunctionDeclaration(node) &&
      node.name !== undefined &&
      (node.modifiers ?? []).some((m) => m.kind === ts.SyntaxKind.ExportKeyword) &&
      takesResolvedSet(node, formatSource)
    ) {
      fromFormat.push(node.name.text)
    }
    ts.forEachChild(node, walkFormat)
  }
  walkFormat(formatSource)

  for (const n of [...fromUnits, ...fromFormat]) names.add(n)
  byFile[rel(UNITS_SOURCE)] = [...new Set(fromUnits)].sort()
  byFile[rel(FORMAT_SOURCE)] = [...new Set(fromFormat)].sort()

  // The receipt. Either walk coming back empty means the predicate stopped
  // matching, and every resolved read in the tree would then be invisible: a
  // fully-binary app, reported by a scanner that had lost half its subject.
  for (const [file, found] of Object.entries(byFile)) {
    if (found.length === 0) {
      throw new Error(
        `${file} declares no API taking a ${RESOLVED_SET_TYPE}. Refusing to run.`,
      )
    }
  }
  return { names, byFile }
}

/** One place a file reads a quantity through the resolved set. */
interface ResolvedRead {
  file: string
  line: number
  text: string
}

/**
 * Every resolved read in one file.
 *
 * Two shapes, both of which are "the resolved set decided this":
 * `u.<quantity>.<anything>(...)`, the `useUnitFormat()` / `makeUnitFormat()`
 * per-quantity formatter, and a call to any name in the resolved API set.
 *
 * @param path The file to scan.
 * @param quantities The ten quantity names.
 * @param resolvedApis The names of APIs taking a `UnitSet`.
 * @returns One entry per resolved read.
 */
function resolvedReadsIn(
  path: string,
  quantities: Set<string>,
  resolvedApis: Set<string>,
): ResolvedRead[] {
  const source = parse(path)
  const out: ResolvedRead[] = []
  const record = (node: TS.Node): void => {
    const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1
    out.push({
      file: rel(path),
      line,
      text: node.getText(source).replace(/\s+/g, ' ').slice(0, 100),
    })
  }
  const walk = (node: TS.Node): void => {
    if (ts.isCallExpression(node)) {
      const callee = node.expression
      // `<expr>.<quantity>.<member>(...)`
      if (
        ts.isPropertyAccessExpression(callee) &&
        ts.isPropertyAccessExpression(callee.expression) &&
        quantities.has(callee.expression.name.text)
      ) {
        record(node)
      } else if (
        ts.isPropertyAccessExpression(callee) &&
        resolvedApis.has(callee.name.text)
      ) {
        record(node)
      } else if (ts.isIdentifier(callee) && resolvedApis.has(callee.text)) {
        record(node)
      }
    }
    // `u.<quantity>.label` and `u.<quantity>.step` are reads too, and a label
    // interpolated into a translated string is exactly how a migrated header
    // states its unit. Counting only calls would miss them.
    if (
      ts.isPropertyAccessExpression(node) &&
      ts.isPropertyAccessExpression(node.expression) &&
      quantities.has(node.expression.name.text) &&
      !ts.isCallExpression(node.parent)
    ) {
      record(node)
    }
    ts.forEachChild(node, walk)
  }
  walk(source)
  return out
}

/** One binary finding, as the gate reports it. */
interface GateFinding {
  file: string
  line: number
  kind: string
  text: string
}

/**
 * The gate's own work list, with a receipt that the parse read all of it.
 *
 * `--report` prints a per-file summary whose counts are parsed here and then
 * re-fetched exactly through `--scan`, which emits JSON. The header's total is
 * compared against the sum: a summary block this parse failed to read would
 * otherwise come back as "no binary sites at all".
 *
 * @returns Every finding the gate reports, across every file it names.
 */
function gateFindings(): GateFinding[] {
  const report = execFileSync(BUN, ['run', GATE, '--report'], { cwd: ROOT, encoding: 'utf-8' })
  const header = /^(\d+) unit-system branch\(es\) across (\d+) file\(s\)/m.exec(report)
  if (header === null) {
    throw new Error(`could not read the gate's summary header from:\n${report}`)
  }
  const files = new Map<string, number>()
  for (const m of report.matchAll(/^ {2,}(\d+) {2}(src\/\S+\.tsx?)$/gm)) {
    files.set(m[2], Number(m[1]))
  }
  const claimed = Number(header[1])
  const counted = [...files.values()].reduce((n, c) => n + c, 0)
  if (files.size !== Number(header[2]) || counted !== claimed) {
    throw new Error(
      `parsed ${files.size} file(s) / ${counted} site(s) from a report claiming ` +
        `${header[2]} / ${claimed}. Refusing to run on a half-read work list.`,
    )
  }

  const out: GateFinding[] = []
  for (const file of [...files.keys()].sort()) {
    const scanned = execFileSync(BUN, ['run', GATE, '--scan', file], {
      cwd: ROOT,
      encoding: 'utf-8',
    })
    const parsed = JSON.parse(scanned) as { file: string; findings: GateFinding[] }
    if (parsed.findings.length !== files.get(file)) {
      throw new Error(
        `${file}: --report said ${files.get(file)} and --scan said ${parsed.findings.length}`,
      )
    }
    for (const f of parsed.findings) out.push({ ...f, file })
  }
  return out
}

/**
 * Every production `.ts`/`.tsx` under `src`.
 *
 * @returns Absolute paths, sorted.
 */
function universe(): string[] {
  const out: string[] = []
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir).sort()) {
      const full = join(dir, entry)
      if (statSync(full).isDirectory()) {
        if (entry === '__tests__' || entry === 'node_modules') continue
        walk(full)
        continue
      }
      if (!/\.tsx?$/.test(entry) || /\.test\.tsx?$/.test(entry) || entry.endsWith('.d.ts')) continue
      out.push(full)
    }
  }
  walk(SRC)
  return out
}

/** Extensions an import specifier may resolve through, in order. */
const EXTENSIONS = ['.tsx', '.ts', '/index.tsx', '/index.ts']

/**
 * Resolve one import specifier to a file inside `src`, or null.
 *
 * Only relative and `@/`-aliased specifiers can name a source file; a bare
 * package specifier is outside the tree by definition.
 *
 * @param spec The specifier as written.
 * @param from The importing file.
 * @returns The absolute path, or null when it is not a `src` file.
 */
function resolveImport(spec: string, from: string): string | null {
  let base: string
  if (spec.startsWith('@/')) base = join(SRC, spec.slice(2))
  else if (spec.startsWith('.')) base = resolve(dirname(from), spec)
  else return null
  for (const ext of ['', ...EXTENSIONS]) {
    const candidate = base + ext
    if (existsSync(candidate) && statSync(candidate).isFile()) return candidate
  }
  return null
}

/**
 * The import edges of one file, restricted to `src`.
 *
 * @param path The importing file.
 * @param source Its parsed AST.
 * @returns Absolute paths of the `src` modules it pulls in.
 */
function importsOf(path: string, source: TS.SourceFile): string[] {
  const out = new Set<string>()
  const walk = (node: TS.Node): void => {
    let spec: string | null = null
    if (ts.isImportDeclaration(node) && ts.isStringLiteralLike(node.moduleSpecifier)) {
      spec = node.moduleSpecifier.text
    } else if (
      ts.isExportDeclaration(node) &&
      node.moduleSpecifier !== undefined &&
      ts.isStringLiteralLike(node.moduleSpecifier)
    ) {
      spec = node.moduleSpecifier.text
    } else if (
      ts.isCallExpression(node) &&
      node.expression.kind === ts.SyntaxKind.ImportKeyword &&
      ts.isStringLiteralLike(node.arguments[0])
    ) {
      spec = node.arguments[0].text
    }
    if (spec !== null) {
      const target = resolveImport(spec, path)
      if (target !== null) out.add(target)
    }
    ts.forEachChild(node, walk)
  }
  walk(source)
  return [...out]
}

function main(): void {
  const quantities = quantityNames()
  const { names: resolvedApis, byFile: resolvedByFile } = resolvedApiNames()
  const findings = gateFindings()
  const paths = universe()

  const binaryByFile = new Map<string, GateFinding[]>()
  for (const f of findings) binaryByFile.set(f.file, [...(binaryByFile.get(f.file) ?? []), f])

  const resolvedByPath = new Map<string, ResolvedRead[]>()
  const edges = new Map<string, string[]>()
  for (const path of paths) {
    const source = parse(path)
    const reads = resolvedReadsIn(path, quantities, resolvedApis)
    if (reads.length > 0) resolvedByPath.set(rel(path), reads)
    edges.set(path, importsOf(path, source))
  }

  // The EXACT answer: one module rendering both.
  const perFile = [...binaryByFile.keys()]
    .filter((file) => resolvedByPath.has(file))
    .sort()

  // The over-approximation: every module a page transitively imports.
  //
  // ★ `src/utils/` and `src/types/` are excluded from the SCREEN half, and the
  // exclusion is the same one `validate-units.ts` makes for its own definitions
  // rather than a convenience. Every page reaches `utils/units.ts`,
  // `types/units.ts` and `publicUnitDefaults.ts` through the preference hook,
  // and each carries `token-branch` findings INSIDE the vocabulary: a branch in
  // a converter is not a rendered quantity, so counting them makes every page
  // in the app a hit and the answer stops distinguishing anything. The counts
  // WITHOUT the exclusion are printed beside each screen, so this is a stated
  // narrowing rather than a hidden filter.
  const rendering = (file: string): boolean =>
    !file.startsWith('src/utils/') && !file.startsWith('src/types/')
  const pages = paths.filter((p) => p.startsWith(PAGES + sep))
  const screens = pages.map((page) => {
    const seen = new Set<string>()
    const queue = [page]
    while (queue.length > 0) {
      const file = queue.pop()!
      if (seen.has(file)) continue
      seen.add(file)
      for (const next of edges.get(file) ?? []) if (!seen.has(next)) queue.push(next)
    }
    const reached = [...seen].map(rel)
    const allBinary = reached.filter((f) => binaryByFile.has(f)).sort()
    return {
      page: rel(page),
      binary: allBinary.filter(rendering),
      vocabularyOnly: allBinary.filter((f) => !rendering(f)),
      resolved: reached.filter((f) => resolvedByPath.has(f) && rendering(f)).sort(),
    }
  })
  const mixedScreens = screens.filter((s) => s.binary.length > 0 && s.resolved.length > 0)

  if (process.argv.includes('--json')) {
    console.log(
      JSON.stringify(
        { resolvedApis: [...resolvedApis].sort(), findings, perFile, screens: mixedScreens },
        null,
        1,
      ),
    )
    return
  }

  console.log('\nSCOPE: modules and pages under src/ (excluding __tests__, *.test.*, *.d.ts)')
  console.log('  that render a unit BOTH through a binary UnitSystem and through the')
  console.log('  resolved UnitSet, at this commit.')
  console.log(`  ${paths.length} file(s) walked; the binary half is ${GATE}'s own answer.\n`)

  console.log('  resolved vocabulary, derived by parameter type (takes a UnitSet):')
  for (const [file, found] of Object.entries(resolvedByFile)) {
    console.log(`    ${file}  (${found.length}): ${found.join(', ')}`)
  }
  console.log(`    plus u.<quantity>.* for ${quantities.size} quantities.\n`)

  console.log(`  EXACT — ${perFile.length} module(s) render both:\n`)
  for (const file of perFile) {
    const binary = binaryByFile.get(file)!
    const resolved = resolvedByPath.get(file)!
    console.log(`  ${file}`)
    console.log(`      ${binary.length} binary, ${resolved.length} resolved`)
    for (const b of binary) console.log(`        binary   :${String(b.line).padEnd(5)} [${b.kind}]  ${b.text}`)
    for (const r of resolved.slice(0, 4)) console.log(`        resolved :${String(r.line).padEnd(5)} ${r.text}`)
    if (resolved.length > 4) console.log(`        resolved ... and ${resolved.length - 4} more`)
  }
  if (perFile.length === 0) console.log('  (none)')

  console.log(`\n  REACHABLE — ${mixedScreens.length} of ${pages.length} page(s) can reach both,`)
  console.log('  counting only rendering modules (not src/utils, src/types):\n')
  for (const s of mixedScreens) {
    console.log(`  ${s.page}`)
    console.log(`      binary in:   ${s.binary.join(', ')}`)
    console.log(`      resolved in: ${s.resolved.join(', ')}`)
    console.log(`      (plus vocabulary-internal: ${s.vocabularyOnly.join(', ') || 'none'})`)
  }
  if (mixedScreens.length === 0) console.log('  (none)')
  console.log('')
}

main()
