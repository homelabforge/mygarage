#!/usr/bin/env bun
/**
 * The binary-distance read sites: an enumerator, not a transcription.
 *
 * ★ WHY THIS EXISTS AS A COMMITTED TOOL. Plan 3b task 6 migrates the call sites
 * that read a DISTANCE through an API whose decision is a binary `UnitSystem`,
 * and `system` is collapsed from VOLUME (spec D8), so a
 * `{volume:'L', distance:'mi'}` account reads kilometres. Three separate hand
 * counts of that universe were produced before this file existed and no two
 * agreed:
 *
 *   task 3's report        10 files / 26 sites. It dropped VehicleStatisticsCard,
 *                          which its own manifest row already recorded.
 *   the brief, attempt 1   12 files, because `LiveLinkTripsTab.tsx:122` names
 *                          `UnitFormatter.formatDistance` INSIDE A COMMENT.
 *   the brief, attempt 2   11 files / 27 sites.
 *
 * Every one of those was measured honestly and reported as the whole. So the
 * count lives in a program that can be re-run, and the answer is PRINTED rather
 * than written down: a number in prose goes stale, and this workstream has paid
 * for that lesson often enough to stop writing them.
 *
 * ★ AST, NOT `grep`, AND BOTH, WHICH IS THE POINT. A parser cannot see a
 * mention in a comment, which is exactly the defect that produced the 12. But
 * "the AST found fewer" is only evidence if you can see what it dropped and
 * why, so this prints the TEXT floor beside the AST answer and classifies every
 * line the two disagree on. Half an inventory is worse than none: a reader
 * shown only the smaller number cannot tell a correct exclusion from a miss.
 *
 * ★ THE VOCABULARY IS RESOLVED AGAINST THE SOURCE, NEVER ASSUMED. Each name
 * below is looked up as a static member of its class in `src/utils/units.ts`.
 * A name that is DELETED contributes zero sites, and that zero is a proof
 * rather than a blindness: an API that does not exist cannot be called. A class
 * whose static members cannot be read at all is a hard refusal, because a
 * vocabulary that silently emptied would report a clean tree.
 *
 * Usage:
 *   bun run scripts/enumerate-binary-distance.ts            # the enumeration
 *   bun run scripts/enumerate-binary-distance.ts --json     # machine-readable
 * Exit code: 0 always. This is a measuring instrument, not a gate; the gate is
 * `scripts/validate-units.ts`, whose baseline this enumeration is a slice of.
 */

import { createRequire } from 'module'
import { readdirSync, readFileSync, statSync } from 'fs'
import { join, relative, sep } from 'path'
import type * as TS from 'typescript'
import { ROOT } from './translation-utils'

/**
 * The real TypeScript compiler API, resolved through the package's own `main`.
 *
 * Same hazard and same fix as `scripts/validate-units.ts:loadTypeScript`, which
 * documents it at length: with no `node_modules` above the importing file, Bun
 * answers a bare `typescript` specifier from an auto-install cache stub that
 * exports only `version`, `createSourceFile` is `undefined`, and every scan
 * reports zero findings on a tree full of them. The stub even reports a NEWER
 * version than the installed compiler, so only an API check catches it.
 *
 * @returns The compiler API, proven to expose the parts used below.
 */
function loadTypeScript(): typeof TS {
  const require = createRequire(import.meta.url)
  const pkgDir = join(ROOT, 'node_modules', 'typescript')
  const main = JSON.parse(readFileSync(join(pkgDir, 'package.json'), 'utf-8')).main as string
  const api = require(join(pkgDir, main)) as typeof TS
  if (typeof api.createSourceFile !== 'function' || !api.SyntaxKind?.BinaryExpression) {
    throw new Error(
      'typescript did not expose createSourceFile/SyntaxKind. Every file would ' +
        'enumerate zero call sites. Refusing to run.',
    )
  }
  return api
}

const ts = loadTypeScript()
const SRC = join(ROOT, 'src')
const UNITS_SOURCE = join(SRC, 'utils', 'units.ts')

/**
 * The four binary DISTANCE APIs, by declaring class.
 *
 * ★ STATED WITH ITS BOUNDARY, because that is what a scope is. These are the
 * APIs through which a canonical kilometre reaches a reader as a distance
 * without that reader's own `units.distance` token being consulted: two
 * formatters whose parameter IS a binary `UnitSystem`, and the two raw
 * converters a call site reaches for when it makes that decision itself.
 *
 * `formatCostPerDistance` and `getCostPerDistanceLabel` carried a distance too
 * and were deliberately OUT: their subject is a currency rate quoted over a
 * chosen number of distance units, which was a separate composition question on
 * a separate work list, task 7. That task migrated both onto `units.distance`
 * and deleted them, so naming them here would resolve two more `DELETED` rows.
 * They stay named rather than removed, because the boundary this file drew was
 * a statement about scope and deleting the statement leaves a gap where a
 * decision used to be.
 */
const VOCABULARY: readonly { className: string; method: string }[] = [
  { className: 'UnitFormatter', method: 'formatDistance' },
  { className: 'UnitFormatter', method: 'getDistanceUnit' },
  { className: 'UnitConverter', method: 'kmToMiles' },
  { className: 'UnitConverter', method: 'milesToKm' },
]

/**
 * Directories excluded from the universe, with the reason.
 *
 * `src/utils/` holds the DEFINITIONS: `units.ts` declares all four and
 * `unitAdapters.ts` is the replacement they migrate onto. A definition is not a
 * call site, and counting them would make the migration look permanently
 * unfinished.
 */
const EXCLUDED_DIRS = [join(SRC, 'utils')]

/**
 * Whether one class member is `static`.
 *
 * @param member The class member to test.
 * @returns True when it carries the `static` modifier.
 */
function isStatic(member: TS.ClassElement): boolean {
  return (member.modifiers ?? []).some((m) => m.kind === ts.SyntaxKind.StaticKeyword)
}

/** One vocabulary entry, as `units.ts` currently answers for it. */
interface Resolution {
  className: string
  method: string
  /** True when `units.ts` still declares it as a static member of its class. */
  present: boolean
}

/**
 * Resolve every vocabulary entry against `units.ts`, with a walk receipt.
 *
 * @returns One resolution per vocabulary entry.
 */
function resolveVocabulary(): Resolution[] {
  const text = readFileSync(UNITS_SOURCE, 'utf-8')
  const source = ts.createSourceFile(
    UNITS_SOURCE,
    text,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TS,
  )
  const seen = new Map<string, Set<string>>()
  const walk = (node: TS.Node): void => {
    if (ts.isClassDeclaration(node) && node.name !== undefined) {
      const members = seen.get(node.name.text) ?? new Set<string>()
      for (const member of node.members) {
        if (!ts.isMethodDeclaration(member) || !isStatic(member)) continue
        members.add(member.name.getText(source))
      }
      seen.set(node.name.text, members)
    }
    ts.forEachChild(node, walk)
  }
  walk(source)

  // The receipt. A walk that stopped visiting the file, or a class renamed
  // wholesale, comes back with no static members at all, and every name would
  // then resolve as "deleted, therefore zero call sites": a clean tree reported
  // by a scanner that had lost its subject.
  for (const className of new Set(VOCABULARY.map((v) => v.className))) {
    if ((seen.get(className)?.size ?? 0) === 0) {
      throw new Error(
        `${relative(ROOT, UNITS_SOURCE)} declares no static members on ${className}. ` +
          'Every name below would resolve as deleted and the enumeration would report ' +
          'zero call sites for a reason that is not true. Refusing to run.',
      )
    }
  }

  return VOCABULARY.map(({ className, method }) => ({
    className,
    method,
    present: seen.get(className)?.has(method) ?? false,
  }))
}

/** One call site the enumeration counts. */
interface Site {
  file: string
  line: number
  method: string
  /** How the call reaches the method: through a receiver, or as a bare name. */
  shape: 'receiver' | 'bare'
  text: string
}

/** One name-match the enumeration deliberately does NOT count, and why. */
interface Rejected {
  file: string
  line: number
  method: string
  reason: string
  text: string
}

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
 * Every production `.ts`/`.tsx` under `src`, minus tests and the definitions.
 *
 * @returns Absolute paths, sorted.
 */
function universe(): string[] {
  const out: string[] = []
  const walk = (dir: string): void => {
    if (EXCLUDED_DIRS.includes(dir)) return
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

/**
 * Parse one file, refusing to report a file the parser choked on as clean.
 *
 * Same fail-loud posture as both units gates: a rejected file yields no call
 * expressions at all, which reads exactly like a migrated one.
 *
 * @param path The file's path, for the message.
 * @param text Its contents.
 * @returns The parsed source file.
 */
function parse(path: string, text: string): TS.SourceFile {
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
 * The member name a callee invokes, and how it reaches it.
 *
 * A receiver is REQUIRED for the `receiver` shape but never READ, exactly as
 * `validate-units.ts` argues: keying on the receiver's spelling would make
 * `import { UnitFormatter as UF }` a one-line bypass, while requiring one is
 * what separates the static API from a module-local helper of the same name.
 * `X['formatDistance']()` is the same decision spelled differently, so it is
 * matched too.
 *
 * @param callee The call expression's callee.
 * @param source The enclosing source file.
 * @returns The invoked name and its shape, or null when neither applies.
 */
function memberOf(
  callee: TS.Expression,
  source: TS.SourceFile,
): { name: string; shape: Site['shape'] } | null {
  if (ts.isPropertyAccessExpression(callee)) {
    return { name: callee.name.getText(source), shape: 'receiver' }
  }
  if (ts.isElementAccessExpression(callee) && ts.isStringLiteralLike(callee.argumentExpression)) {
    return { name: callee.argumentExpression.text, shape: 'receiver' }
  }
  if (ts.isIdentifier(callee)) {
    return { name: callee.text, shape: 'bare' }
  }
  return null
}

/**
 * Names a file declares or imports for itself, so a local helper is not a hit.
 *
 * Three files declare a local `formatDistance` today and `POICard.tsx`'s is
 * CORRECT migrated code taking a resolved `UnitSet`. A name-only match reports
 * all three, and a tool that reports correct code is one people learn to ignore.
 *
 * @param source The parsed file.
 * @returns Every name bound inside it.
 */
function locallyDeclared(source: TS.SourceFile): Set<string> {
  const declared = new Set<string>()
  const walk = (node: TS.Node): void => {
    if (ts.isFunctionDeclaration(node) && node.name !== undefined) declared.add(node.name.text)
    if (
      (ts.isVariableDeclaration(node) || ts.isBindingElement(node)) &&
      ts.isIdentifier(node.name)
    ) {
      declared.add(node.name.text)
    }
    if (ts.isImportSpecifier(node)) declared.add(node.name.text)
    ts.forEachChild(node, walk)
  }
  walk(source)
  return declared
}

/**
 * Walk the universe for calls to the live vocabulary.
 *
 * @param paths The files to scan.
 * @param live The vocabulary entries `units.ts` still declares.
 * @returns The call sites, and the name-matches deliberately not counted.
 */
function scan(paths: string[], live: Set<string>): { sites: Site[]; rejected: Rejected[] } {
  const sites: Site[] = []
  const rejected: Rejected[] = []
  for (const path of paths) {
    const source = parse(path, readFileSync(path, 'utf-8'))
    const declared = locallyDeclared(source)
    const walk = (node: TS.Node): void => {
      if (ts.isCallExpression(node)) {
        const member = memberOf(node.expression, source)
        if (member !== null && live.has(member.name)) {
          const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1
          const text = node.getText(source).replace(/\s+/g, ' ').slice(0, 110)
          if (member.shape === 'receiver') {
            sites.push({ file: rel(path), line, method: member.name, shape: 'receiver', text })
          } else if (declared.has(member.name)) {
            rejected.push({
              file: rel(path),
              line,
              method: member.name,
              reason: 'module-local declaration of the same name, not the static API',
              text,
            })
          } else {
            // A bare call to a name this file neither declares nor imports
            // cannot be the static member, but it also cannot be explained, so
            // it is COUNTED rather than dropped. Fail-closed, like the gate.
            sites.push({ file: rel(path), line, method: member.name, shape: 'bare', text })
          }
        }
      }
      ts.forEachChild(node, walk)
    }
    walk(source)
  }
  return { sites, rejected }
}

/**
 * The naive text floor: every LINE mentioning a live name, parser blind.
 *
 * This is what a `grep` answers, printed so the difference between it and the
 * AST answer is auditable rather than asserted.
 *
 * @param paths The files to scan.
 * @param live The vocabulary entries `units.ts` still declares.
 * @returns One entry per matching line.
 */
function textFloor(
  paths: string[],
  live: Set<string>,
): { file: string; line: number; text: string }[] {
  const out: { file: string; line: number; text: string }[] = []
  if (live.size === 0) return out
  const pattern = new RegExp(`\\b(?:${[...live].join('|')})\\b`)
  for (const path of paths) {
    readFileSync(path, 'utf-8')
      .split('\n')
      .forEach((text, i) => {
        if (pattern.test(text)) {
          out.push({ file: rel(path), line: i + 1, text: text.trim().slice(0, 110) })
        }
      })
  }
  return out
}

function main(): void {
  const resolutions = resolveVocabulary()
  const live = new Set(resolutions.filter((r) => r.present).map((r) => r.method))
  const paths = universe()
  const { sites, rejected } = scan(paths, live)
  const floor = textFloor(paths, live)

  if (process.argv.includes('--json')) {
    console.log(JSON.stringify({ resolutions, sites, rejected, floor }, null, 1))
    return
  }

  const byFile = new Map<string, Site[]>()
  for (const s of sites) byFile.set(s.file, [...(byFile.get(s.file) ?? []), s])

  console.log('\nSCOPE: the four binary distance APIs, CALLED (not merely named), in')
  console.log('  src/**/*.{ts,tsx}, excluding __tests__, *.test.*, *.d.ts and')
  console.log(`  ${EXCLUDED_DIRS.map(rel).join(', ')} (the definitions).`)
  console.log(`  ${paths.length} file(s) in the universe, all parsed.\n`)

  console.log('  vocabulary, resolved against src/utils/units.ts:')
  for (const r of resolutions) {
    console.log(
      `    ${r.present ? 'present' : 'DELETED '}  ${r.className}.${r.method}` +
        (r.present ? '' : '   (cannot be called: zero sites by construction)'),
    )
  }

  console.log(`\n  ${sites.length} site(s) across ${byFile.size} file(s):\n`)
  for (const [file, hits] of [...byFile].sort((a, b) => a[0].localeCompare(b[0]))) {
    console.log(`  ${String(hits.length).padStart(3)}  ${file}`)
  }
  if (sites.length > 0) console.log('')
  for (const [file, hits] of [...byFile].sort((a, b) => a[0].localeCompare(b[0]))) {
    for (const h of hits) {
      console.log(`  ${file}:${h.line}  [${h.shape}] ${h.method}   ${h.text}`)
    }
  }

  const astLines = new Set(sites.map((s) => `${s.file}:${s.line}`))
  const rejectedLines = new Map(rejected.map((r) => [`${r.file}:${r.line}`, r.reason]))
  const unmatched = floor.filter((f) => !astLines.has(`${f.file}:${f.line}`))
  console.log(`\n  the text floor a grep would report: ${floor.length} line(s).`)
  console.log(`  ${unmatched.length} of them are NOT call sites, each for a reason:\n`)
  for (const f of unmatched) {
    const key = `${f.file}:${f.line}`
    console.log(
      `  ${key}  ${rejectedLines.get(key) ?? 'named but not called here: a comment, a type, an import or a prop'}`,
    )
    console.log(`      ${f.text}`)
  }
  console.log('')
}

main()
