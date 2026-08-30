#!/usr/bin/env bun
/**
 * The entry/storage boundary, enumerated IN BOTH DIRECTIONS.
 *
 * ★ WHY BOTH DIRECTIONS, WHICH IS THE WHOLE DESIGN. A unit-bearing form field
 * crosses the boundary twice: a stored canonical value is SEEDED into it, and
 * whatever it holds is READ back out. Getting one side right and not the other
 * is not half a fix, it is the original defect wearing a fix's name, and this
 * workstream has now shipped that shape twice. Plan 3b's ruling R4 says so
 * outright: "seeding an origin while still submitting through
 * `toCanonicalLiters` reconverts the rounded display and the shift survives,
 * and every seeding-only test passes while it does."
 *
 * So this does not count "sites". It counts SEEDS and READS separately, per
 * file, and prints any file that has one without the other. A file that seeds
 * an origin and never reads it back is exactly the half-migration, and a file
 * that reads an origin nothing seeded cannot compile, so the asymmetry is
 * one-directional and worth naming.
 *
 * ★ AND IT RESOLVES THE RETIRED VOCABULARY TOO. `toCanonicalLiters` and the
 * exported `priceToCanonical` were the two functions that converted a DISPLAY
 * value straight to canonical, which is the read half done wrong. They are
 * looked up in their declaring module and reported as DELETED, which is a proof
 * rather than a blindness: a function that does not exist cannot be called. If
 * one is ever re-exported, it resolves as present and its call sites are counted
 * beside the protocol's, so the two idioms appear side by side rather than one
 * hiding behind the other's total.
 *
 * ★ AST, NOT `grep`, AND BOTH. A parser cannot see a mention in a comment, and
 * five files here name these functions in prose only: `schemas/hours.ts`,
 * `schemas/odometer.ts` and `schemas/shared.ts` explain what the SUBMIT path
 * does, and `HoursRecordForm.tsx` explains what it does not do. A text count
 * reports them as call sites. But "the AST found fewer" is only evidence if you
 * can see what it dropped, so the text floor is printed beside the AST answer
 * and every line the two disagree on is classified.
 *
 * Usage:
 *   bun run scripts/enumerate-unit-entry-grid.ts          # the enumeration
 *   bun run scripts/enumerate-unit-entry-grid.ts --json   # machine-readable
 * Exit code: 0 always. This is a measuring instrument, not a gate. What gates
 * this boundary is `utils/__tests__/unitsBinaryApiSurface.test.ts`, which fails
 * on the DECLARATION of a helper that writes canonical values the wrong way.
 */

import { createRequire } from 'module'
import { readdirSync, readFileSync, statSync } from 'fs'
import { join, relative, sep } from 'path'
import type * as TS from 'typescript'
import { ROOT } from './translation-utils'

/**
 * The real TypeScript compiler API, resolved through the package's own `main`.
 *
 * Same hazard and same fix as `scripts/validate-units.ts:loadTypeScript`: with
 * no `node_modules` above the importing file, Bun answers a bare `typescript`
 * specifier from an auto-install cache stub that exports only `version`,
 * `createSourceFile` is `undefined`, and every scan reports zero findings on a
 * tree full of them.
 *
 * @returns The compiler API, proven to expose the parts used below.
 */
function loadTypeScript(): typeof TS {
  const require = createRequire(import.meta.url)
  const pkgDir = join(ROOT, 'node_modules', 'typescript')
  const main = JSON.parse(readFileSync(join(pkgDir, 'package.json'), 'utf-8')).main as string
  const api = require(join(pkgDir, main)) as typeof TS
  if (typeof api.createSourceFile !== 'function' || !api.SyntaxKind?.CallExpression) {
    throw new Error(
      'typescript did not expose createSourceFile/SyntaxKind. Every file would ' +
        'enumerate zero call sites. Refusing to run.',
    )
  }
  return api
}

const ts = loadTypeScript()
const SRC = join(ROOT, 'src')

/**
 * Which way a value is crossing the boundary.
 *
 * `display` is the third: a conversion that is CORRECT for a read and is the
 * R4 defect when it seeds a field, so its direction is decided by where it is
 * called rather than by its name. See `SEED_POSITION` below.
 */
type Direction = 'seed' | 'read' | 'display'

/** One name the enumeration looks for, and where it is declared. */
interface Vocabulary {
  name: string
  module: string
  direction: Direction
  /** True for a name whose presence would be a REGRESSION rather than the norm. */
  retired: boolean
  why: string
}

/**
 * The boundary's vocabulary, with its retired half named rather than omitted.
 *
 * ★ THE RETIRED ENTRIES ARE THE POINT OF LISTING ANYTHING AT ALL. An enumerator
 * that only knows the current idiom reports a clean tree on the day somebody
 * reintroduces the old one. Both halves resolve against their declaring module,
 * so a retired name contributes zero sites BECAUSE IT DOES NOT EXIST, and the
 * run says so, rather than because nothing was looking for it.
 *
 * ★ AND THE `display` HALF, WHICH IS THE PART THIS FILE USED TO ARGUE AWAY.
 * `priceToDisplay` and `UnitConverter.litersToVolumeUnit` are live display
 * conversions with real read-only callers (list columns, cards), so reporting
 * every call would report correct code, and a tool that reports correct code is
 * one people learn to ignore. What made them dangerous was being used to SEED a
 * field with no origin: every writer form did exactly that until task 7.
 *
 * An earlier version of this comment said that was "a property of the call site
 * rather than of the name, which is the category `units.manifest.json` carries
 * and no lexical rule can". The first half is right and the conclusion was not.
 * This IS an AST walk over call sites, so a call-site property is precisely
 * what it can decide, and answering with prose in a file that owns the
 * mechanism is guard-by-convention. `SEED_POSITION` below is the rule instead:
 * a call inside a `defaultValues` object literal, or passed as an argument to
 * `setValue`, is a SEED, and every other call is a read. Today that reports
 * zero seeds, which is a measurement rather than a claim.
 */
const VOCABULARY: readonly Vocabulary[] = [
  {
    name: 'seedUnitField',
    module: 'src/utils/unitFormat.ts',
    direction: 'seed',
    retired: false,
    why: 'populates a quantity field and records the canonical value behind it',
  },
  {
    name: 'canonicalFromUnitField',
    module: 'src/utils/unitFormat.ts',
    direction: 'read',
    retired: false,
    why: 'reads a quantity field back, returning the origin when untouched',
  },
  {
    name: 'seedPriceField',
    module: 'src/utils/decimalSafe.ts',
    direction: 'seed',
    retired: false,
    why: 'the price mirror: price is not a quantity and carries a basis',
  },
  {
    name: 'canonicalFromPriceField',
    module: 'src/utils/decimalSafe.ts',
    direction: 'read',
    retired: false,
    why: 'the price mirror of the read half, basis compared as well as value',
  },
  {
    name: 'toCanonicalLiters',
    module: 'src/utils/decimalSafe.ts',
    direction: 'read',
    retired: true,
    why: 'converted a display volume straight to canonical: the R4 shift',
  },
  {
    name: 'priceToCanonical',
    module: 'src/utils/decimalSafe.ts',
    direction: 'read',
    retired: true,
    why: 'converted a display price straight to canonical: the R4 shift',
  },
  {
    name: 'priceToDisplay',
    module: 'src/utils/decimalSafe.ts',
    direction: 'display',
    retired: false,
    why: 'correct for a list cell; the R4 defect when it seeds a field',
  },
  {
    name: 'litersToVolumeUnit',
    module: 'src/utils/units.ts',
    direction: 'display',
    retired: false,
    why: 'correct for a card; the R4 defect when it seeds a field',
  },
]

/**
 * Where a `display` conversion becomes a SEED.
 *
 * Two shapes, both measured off the real writers rather than imagined: every
 * form seeded either from a `defaultValues` object literal (the six
 * react-hook-form writers) or through `setValue` (the receipt and OBC accept
 * paths). A call in either position lands a converted value into a FIELD, which
 * is the act that needs an origin beside it.
 *
 * Deliberately NOT a whole-file rule: `FuelRecordList` calls `priceToDisplay`
 * in a table cell and that is correct, so a name-only or file-only rule would
 * report it.
 */
const SEED_POSITION = {
  /** The property whose object literal holds a react-hook-form seed. */
  defaultsProperty: 'defaultValues',
  /** The setter that writes one field after mount. */
  setter: 'setValue',
} as const

/**
 * Directories excluded from the universe, with the reason.
 *
 * `src/utils/` holds the DECLARATIONS. A declaration is not a call site, and
 * counting one would make the boundary look permanently unfinished.
 */
const EXCLUDED_DIRS = [join(SRC, 'utils')]

/** One vocabulary entry, as its declaring module currently answers for it. */
interface Resolution extends Vocabulary {
  /** True when the module still EXPORTS a function of that name. */
  present: boolean
}

/**
 * Resolve every vocabulary entry against its module, with a walk receipt.
 *
 * A module whose exported functions cannot be read at all is a hard refusal:
 * a vocabulary that silently emptied would report a clean tree.
 *
 * @returns One resolution per vocabulary entry.
 */
function resolveVocabulary(): Resolution[] {
  const exportsByModule = new Map<string, Set<string>>()
  for (const module of new Set(VOCABULARY.map((v) => v.module))) {
    const path = join(ROOT, module)
    const source = parse(path, readFileSync(path, 'utf-8'))
    const found = new Set<string>()
    const walk = (node: TS.Node): void => {
      if (
        ts.isFunctionDeclaration(node) &&
        node.name !== undefined &&
        (node.modifiers ?? []).some((m) => m.kind === ts.SyntaxKind.ExportKeyword)
      ) {
        found.add(node.name.text)
      }
      // Static class members too: `litersToVolumeUnit` lives on `UnitConverter`
      // rather than being a bare export, and a resolver that could not see it
      // would report a live name as DELETED, which is the same false clean this
      // function's refusal below exists to prevent.
      if (ts.isMethodDeclaration(node) && node.name !== undefined) {
        const isStatic = (node.modifiers ?? []).some(
          (m) => m.kind === ts.SyntaxKind.StaticKeyword,
        )
        if (isStatic) found.add(node.name.getText(source))
      }
      ts.forEachChild(node, walk)
    }
    walk(source)
    if (found.size === 0) {
      throw new Error(
        `${module} declares no exported function and no static method. Every name ` +
          'below would resolve as deleted and the enumeration would report zero call ' +
          'sites for a reason that is not true. Refusing to run.',
      )
    }
    exportsByModule.set(module, found)
  }
  return VOCABULARY.map((v) => ({
    ...v,
    present: exportsByModule.get(v.module)?.has(v.name) ?? false,
  }))
}

/** One call site the enumeration counts. */
interface Site {
  file: string
  line: number
  name: string
  direction: Direction
  retired: boolean
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
 * Every production `.ts`/`.tsx` under `src`, minus tests and the declarations.
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
 * A rejected file yields no call expressions at all, which reads exactly like a
 * migrated one.
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
 * The name a callee invokes, whether bare or through a namespace.
 *
 * These are module functions, so a bare call IS the shape; a namespace import
 * (`import * as unit from ...; unit.seedUnitField(...)`) is the same decision
 * spelled differently and is matched too.
 *
 * @param callee The call expression's callee.
 * @param source The enclosing source file.
 * @returns The invoked name, or null when neither form applies.
 */
function calleeName(callee: TS.Expression, source: TS.SourceFile): string | null {
  if (ts.isIdentifier(callee)) return callee.text
  if (ts.isPropertyAccessExpression(callee)) return callee.name.getText(source)
  return null
}

/**
 * Walk the universe for calls to the live vocabulary.
 *
 * @param paths The files to scan.
 * @param live The vocabulary entries their modules still export, by name.
 * @returns The call sites.
 */
function scan(paths: string[], live: Map<string, Resolution>): Site[] {
  const sites: Site[] = []
  for (const path of paths) {
    const source = parse(path, readFileSync(path, 'utf-8'))
    /** Ancestors of the node being visited, nearest last. */
    const stack: TS.Node[] = []
    const walk = (node: TS.Node): void => {
      if (ts.isCallExpression(node)) {
        const name = calleeName(node.expression, source)
        const entry = name === null ? undefined : live.get(name)
        if (entry !== undefined) {
          sites.push({
            file: rel(path),
            line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1,
            name: entry.name,
            direction:
              entry.direction === 'display' && inSeedPosition(stack, source)
                ? 'seed'
                : entry.direction,
            retired: entry.retired,
            text: node.getText(source).replace(/\s+/g, ' ').slice(0, 110),
          })
        }
      }
      stack.push(node)
      ts.forEachChild(node, walk)
      stack.pop()
    }
    walk(source)
  }
  return sites
}

/**
 * Whether a call sits where its result lands in a FORM FIELD.
 *
 * Walks the ancestor chain rather than the node, because both shapes are about
 * CONTEXT: the same `priceToDisplay(...)` expression is a correct table cell in
 * one place and an origin-less seed in another. Stops at the enclosing function
 * so a `setValue` three components up cannot claim an unrelated call.
 *
 * @param stack The ancestors of the call, nearest last.
 * @param source The enclosing source file.
 * @returns True when the call is a `defaultValues` entry or a `setValue` argument.
 */
function inSeedPosition(stack: readonly TS.Node[], source: TS.SourceFile): boolean {
  for (let i = stack.length - 1; i >= 0; i -= 1) {
    const node = stack[i]
    if (ts.isFunctionDeclaration(node) || ts.isMethodDeclaration(node)) return false
    if (
      ts.isPropertyAssignment(node) &&
      node.name.getText(source) === SEED_POSITION.defaultsProperty
    ) {
      return true
    }
    if (
      ts.isCallExpression(node) &&
      calleeName(node.expression, source) === SEED_POSITION.setter
    ) {
      return true
    }
  }
  return false
}

/**
 * The naive text floor: every LINE mentioning a live name, parser blind.
 *
 * @param paths The files to scan.
 * @param live The names still declared.
 * @returns One entry per matching line.
 */
function textFloor(
  paths: string[],
  live: Map<string, Resolution>,
): { file: string; line: number; text: string }[] {
  const out: { file: string; line: number; text: string }[] = []
  if (live.size === 0) return out
  const pattern = new RegExp(`\\b(?:${[...live.keys()].join('|')})\\b`)
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
  const live = new Map(resolutions.filter((r) => r.present).map((r) => [r.name, r]))
  const paths = universe()
  const sites = scan(paths, live)
  const floor = textFloor(paths, live)

  // The pairing, which is the reason this file exists in this shape. A file
  // that seeds and never reads back is the half-migration ruling R4 names.
  //
  // ★ `display` IS COUNTED SEPARATELY AND EXCLUDED FROM THE PAIRING, because a
  // list column that renders a price is not half of anything: it reads a stored
  // value and shows it, and there is no field for it to be read back out of. A
  // display call that lands in a FIELD is classified `seed` by `scan`, and THAT
  // one has to pair.
  const seeds = new Map<string, number>()
  const reads = new Map<string, number>()
  const displays = new Map<string, number>()
  const bucket = { seed: seeds, read: reads, display: displays }
  for (const s of sites) bucket[s.direction].set(s.file, (bucket[s.direction].get(s.file) ?? 0) + 1)
  const unpaired = [...new Set([...seeds.keys(), ...reads.keys()])]
    .sort()
    .filter((f) => (seeds.get(f) ?? 0) === 0 || (reads.get(f) ?? 0) === 0)

  if (process.argv.includes('--json')) {
    console.log(JSON.stringify({ resolutions, sites, floor, unpaired }, null, 1))
    return
  }

  console.log('\nSCOPE: the entry/storage boundary, CALLED (not merely named), in')
  console.log('  src/**/*.{ts,tsx}, excluding __tests__, *.test.*, *.d.ts and')
  console.log(`  ${EXCLUDED_DIRS.map(rel).join(', ')} (the declarations).`)
  console.log(`  ${paths.length} file(s) in the universe, all parsed.\n`)

  console.log('  vocabulary, resolved against its declaring module:')
  for (const r of resolutions) {
    const state = r.present ? 'present' : 'DELETED'
    const note = r.retired
      ? r.present
        ? '   ★ RETIRED AND BACK: the R4 shift is reachable again'
        : '   (cannot be called: zero sites by construction)'
      : ''
    console.log(`    ${state.padEnd(8)} [${r.direction}] ${r.name.padEnd(24)}${note}`)
    console.log(`             ${r.why}`)
  }

  const files = [...new Set(sites.map((s) => s.file))].sort()
  console.log(`\n  ${sites.length} site(s) across ${files.length} file(s), BY DIRECTION:\n`)
  console.log('     seed  read  disp  file')
  for (const file of files) {
    console.log(
      `    ${String(seeds.get(file) ?? 0).padStart(5)}` +
        ` ${String(reads.get(file) ?? 0).padStart(5)}` +
        ` ${String(displays.get(file) ?? 0).padStart(5)}  ${file}`,
    )
  }
  const seedingDisplays = sites.filter((s) => s.direction === 'seed' && s.name !== 'seedUnitField' && s.name !== 'seedPriceField')
  console.log(
    `\n  ${displays.size === 0 ? 0 : [...displays.values()].reduce((a, b) => a + b, 0)}` +
      ' display conversion(s), of which ' +
      `${seedingDisplays.length} sit in SEED POSITION (a \`${SEED_POSITION.defaultsProperty}\`` +
      ` entry or a \`${SEED_POSITION.setter}\` argument), which is where they need an origin` +
      (seedingDisplays.length === 0 ? '.' : ':'),
  )
  for (const s of seedingDisplays) {
    console.log(`    ★ ${s.file}:${s.line}  ${s.name}   ${s.text}`)
  }

  console.log('')
  for (const file of files) {
    for (const s of sites.filter((x) => x.file === file)) {
      console.log(`  ${s.file}:${s.line}  [${s.direction}] ${s.name}   ${s.text}`)
    }
  }

  console.log(
    `\n  ${unpaired.length} file(s) cross the boundary in ONE direction only` +
      (unpaired.length === 0 ? '.' : ':'),
  )
  for (const f of unpaired) {
    console.log(`    ${f}  seed=${seeds.get(f) ?? 0} read=${reads.get(f) ?? 0}`)
  }

  const astLines = new Set(sites.map((s) => `${s.file}:${s.line}`))
  const unmatched = floor.filter((f) => !astLines.has(`${f.file}:${f.line}`))
  console.log(`\n  the text floor a grep would report: ${floor.length} line(s).`)
  console.log(`  ${unmatched.length} of them are NOT call sites, each for a reason:\n`)
  for (const f of unmatched) {
    console.log(`  ${f.file}:${f.line}  named but not called here: a comment, a type or an import`)
    console.log(`      ${f.text}`)
  }
  console.log('')
}

main()
