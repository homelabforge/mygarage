#!/usr/bin/env bun
/**
 * Translated copy that NAMES a unit, in every locale bundle there is.
 *
 * ★ WHY THIS IS A DEFECT CLASS AND NOT A STYLE NOTE. Phase 3b resolves units
 * PER QUANTITY, so `fuel.mpgTip` telling every reader "MPG is only calculated
 * for full tank fill-ups" is the app naming a unit the reader may not use, in
 * a sentence about a figure they read in L/100km. Interpolating the resolved
 * label costs one argument; leaving it is the same defect the formatters had,
 * relocated into prose where no gate can see it. `validate-units.ts` parses
 * TypeScript and never opens a `.json`, so this is the only mechanical view of
 * that surface.
 *
 * ★ THE BUNDLE LIST IS ENUMERATED, NEVER TYPED. `src/locales/en/` is bundled
 * and `public/locales/<lang>/` is lazy-loaded, which is exactly the kind of
 * split a hand-written list gets wrong: this task's own brief was handed six
 * bundles by a controller who had missed Polish, and `CLAUDE.md` makes the
 * same off-by-one with a different language (it says six supported languages
 * and there are seven bundles on disk). So the directories come off the
 * filesystem, the count is printed, and a run that finds no `en` bundle or
 * fewer than two bundles refuses rather than reporting a clean tree.
 *
 * ★ THE SYMBOL HALF OF THE VOCABULARY IS DERIVED FROM THE APP'S OWN TABLE.
 * Every label in `UNIT_ADAPTERS` is a unit this app renders, so a label
 * appearing in prose is prose competing with the adapter that owns it. The
 * PROSE half ("miles", "gallons", "imperial") cannot be derived from anything
 * and is stated below with its reasoning, because a vocabulary you cannot
 * derive is one you have to be able to audit.
 *
 * ★ IT REPORTS CANDIDATES, NOT VERDICTS, and that distinction is deliberate.
 * Some hits are correct: a units SETTING names both systems because they are
 * the choice on offer, and a US window sticker is a reproduction of a
 * document that is imperial by law. A tool that pretended to decide those
 * would be one people learn to override. Every hit is printed with its
 * bundle, namespace, key and value; the decision is a human's.
 *
 * Usage:
 *   bun run scripts/enumerate-unit-copy.ts           # the enumeration
 *   bun run scripts/enumerate-unit-copy.ts --json    # machine-readable
 *   bun run scripts/enumerate-unit-copy.ts --en      # the en bundle alone
 * Exit code: 0 always. A measuring instrument, not a gate.
 */

import { createRequire } from 'module'
import { readdirSync, readFileSync, statSync, existsSync } from 'fs'
import { join, relative, sep } from 'path'
import type * as TS from 'typescript'
import { ROOT } from './translation-utils'

/**
 * The real TypeScript compiler API, resolved through the package's own `main`.
 *
 * Same hazard and same fix as `scripts/validate-units.ts:loadTypeScript`.
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
const ADAPTERS_SOURCE = join(SRC, 'utils', 'unitAdapters.ts')

/**
 * Prose unit names, which no table declares.
 *
 * ★ STATED, NOT DERIVED, AND THAT IS THE HONEST PART. `UNIT_ADAPTERS` holds
 * symbols (`mi`, `gal`, `MPG`); English prose spells them out, and no artifact
 * in this repo maps one to the other. A derived-looking list that was really
 * hand-written would be worse than this, so the hand-written part is labelled.
 *
 * Only ENGLISH prose is listed. The other six bundles are translations of the
 * same sentences, and a Polish reader's word for "miles" is not something this
 * file can guess; what carries across untranslated is the SYMBOL half above,
 * which is why symbols are matched in every bundle and prose is reported with
 * its bundle so a reader can see the coverage is uneven.
 */
const PROSE = [
  'imperial',
  'metric',
  'mile',
  'miles',
  'mileage',
  'gallon',
  'gallons',
  'litre',
  'litres',
  'liter',
  'liters',
  'kilometre',
  'kilometres',
  'kilometer',
  'kilometers',
  'pound',
  'pounds',
  'inch',
  'inches',
  'fahrenheit',
  'celsius',
]

/**
 * Compound spellings that no adapter label and no single prose word covers.
 *
 * `kWh/100mi` is the electric analogue of MPG and appears nowhere in
 * `UNIT_ADAPTERS`: energy consumption is not one of the ten quantities. It is
 * still copy naming a unit the reader may not use, so it is matched here
 * rather than left out for want of a table to derive it from.
 */
const COMPOUNDS = ['kWh/100mi', 'kWh/100km', 'mpg', '100k miles', '100,000 miles']

/**
 * Every unit label the app renders, read out of `unitAdapters.ts`'s own table.
 *
 * @returns The distinct labels, sorted longest-first so `L/100km` is matched
 *   before `L`.
 */
function adapterLabels(): string[] {
  const text = readFileSync(ADAPTERS_SOURCE, 'utf-8')
  const source = ts.createSourceFile(
    ADAPTERS_SOURCE,
    text,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TS,
  )
  const labels = new Set<string>()
  const walk = (node: TS.Node): void => {
    // `linear('mi', 'mi', 0, ...)` / `inverse('mpg_us', 'MPG', 1, ...)`: the
    // SECOND argument is the label, by both builders' signatures.
    if (
      ts.isCallExpression(node) &&
      ts.isIdentifier(node.expression) &&
      (node.expression.text === 'linear' || node.expression.text === 'inverse') &&
      node.arguments.length >= 2 &&
      ts.isStringLiteralLike(node.arguments[1])
    ) {
      labels.add(node.arguments[1].text)
    }
    ts.forEachChild(node, walk)
  }
  walk(source)
  if (labels.size === 0) {
    throw new Error(
      `${relative(ROOT, ADAPTERS_SOURCE)} yielded no adapter labels. Every symbol in ` +
        'every bundle would go unseen and the copy would look clean. Refusing to run.',
    )
  }
  return [...labels].sort((a, b) => b.length - a.length)
}

/** One locale bundle on disk. */
interface Bundle {
  /** The language tag, e.g. `'pt-BR'`. */
  lang: string
  /** Absolute path to the bundle directory. */
  dir: string
  /** Where it is loaded from: bundled with the app, or fetched at runtime. */
  loading: 'bundled' | 'lazy'
}

/**
 * Every locale bundle on disk, enumerated rather than listed.
 *
 * @returns One entry per bundle directory, `en` first.
 */
function bundles(): Bundle[] {
  const out: Bundle[] = []
  const roots: { base: string; loading: Bundle['loading'] }[] = [
    { base: join(SRC, 'locales'), loading: 'bundled' },
    { base: join(ROOT, 'public', 'locales'), loading: 'lazy' },
  ]
  for (const { base, loading } of roots) {
    if (!existsSync(base)) continue
    for (const entry of readdirSync(base).sort()) {
      const dir = join(base, entry)
      if (statSync(dir).isDirectory()) out.push({ lang: entry, dir, loading })
    }
  }
  if (!out.some((b) => b.lang === 'en')) {
    throw new Error('no `en` bundle found. The canonical language is missing; refusing to run.')
  }
  if (out.length < 2) {
    throw new Error(
      `found ${out.length} bundle(s). A single bundle means the walk lost the lazy-loaded ` +
        'ones, and six languages of unconditional copy would be reported clean. Refusing to run.',
    )
  }
  return out
}

/** One string in one bundle that names a unit. */
interface Hit {
  lang: string
  loading: Bundle['loading']
  namespace: string
  key: string
  value: string
  /** Which vocabulary entries matched, so a hit can be judged without guessing. */
  matched: string[]
}

/**
 * Flatten one namespace's JSON into dotted key paths.
 *
 * @param node The parsed JSON node.
 * @param prefix The dotted prefix so far.
 * @returns One entry per leaf string.
 */
function flatten(node: unknown, prefix = ''): { key: string; value: string }[] {
  if (typeof node === 'string') return [{ key: prefix, value: node }]
  if (node === null || typeof node !== 'object') return []
  const out: { key: string; value: string }[] = []
  for (const [k, v] of Object.entries(node as Record<string, unknown>)) {
    out.push(...flatten(v, prefix === '' ? k : `${prefix}.${k}`))
  }
  return out
}

/**
 * Build the matcher for one vocabulary entry.
 *
 * Word boundaries for alphanumeric entries, so `mi` does not match "milestone"
 * and `m` does not match every word with an m in it. Entries containing a
 * slash or a degree sign are matched literally, because `\b` does not apply
 * either side of a non-word character.
 *
 * ★ SYMBOLS ARE CASE-SENSITIVE, PROSE IS NOT, and the difference is worth 400
 * false positives. A case-insensitive `L` matches the standalone `l` of French
 * and Italian elision (`l'article`), which put 299 hits on the French bundle
 * alone and buried the two real ones. `L` and `l` are different units in every
 * table this app owns, so the symbol half loses the `i` flag; the prose half
 * keeps it, because "Imperial" and "imperial" are the same word.
 *
 * ★ AND THE BOUNDARY IS UNICODE-AWARE, which the first version was not.
 * JavaScript's `\b` is defined over ASCII word characters, so every non-ASCII
 * letter counts as a boundary: `L` matched the L in `Löschen` and `m` matched
 * the m in Portuguese words, which made 9 of German's hits and effectively all
 * of Brazilian Portuguese's false. That is the opposite of the property the
 * seven-bundle framing sells, so the boundary is spelled with `\p{L}\p{N}`
 * lookarounds under the `u` flag instead. The prose half gets the same
 * treatment: `\bmile\b` would otherwise match inside an accented word.
 *
 * @param term The vocabulary entry.
 * @param caseInsensitive Whether case may vary, true only for prose.
 * @returns Its regular expression.
 */
function matcher(term: string, caseInsensitive: boolean): RegExp {
  const escaped = term.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&')
  const wordish = /^[A-Za-z0-9]+$/.test(term)
  // A ONE-LETTER symbol may not be followed by an apostrophe. `L'` is French
  // and Italian elision (`L'IA`, `L'authentification`), never a unit, and it
  // survived case-sensitivity and the Unicode boundary alike because the
  // apostrophe IS a boundary: 18 of French's 24 remaining hits were that. The
  // exclusion is confined to single-character terms, where elision is the only
  // way the sequence arises; applying it to prose would silently drop an
  // English possessive.
  const trailing = term.length === 1 ? `[\\p{L}\\p{N}'\u2019]` : `[\\p{L}\\p{N}]`
  const pattern = wordish
    ? `(?<![\\p{L}\\p{N}])${escaped}(?!${trailing})`
    : escaped
  return new RegExp(pattern, caseInsensitive ? 'iu' : 'u')
}

function main(): void {
  const labels = adapterLabels()
  const symbols = [...new Set([...labels, ...COMPOUNDS])]
  const vocabulary = [...new Set([...symbols, ...PROSE])]
  const matchers = [
    ...symbols.map((term) => ({ term, re: matcher(term, false) })),
    ...PROSE.filter((term) => !symbols.includes(term)).map((term) => ({
      term,
      re: matcher(term, true),
    })),
  ]
  const found = bundles()
  const enOnly = process.argv.includes('--en')
  const scanned = enOnly ? found.filter((b) => b.lang === 'en') : found

  const hits: Hit[] = []
  let strings = 0
  for (const bundle of scanned) {
    for (const file of readdirSync(bundle.dir).sort()) {
      if (!file.endsWith('.json')) continue
      const namespace = file.replace(/\.json$/, '')
      const parsed = JSON.parse(readFileSync(join(bundle.dir, file), 'utf-8'))
      for (const { key, value } of flatten(parsed)) {
        strings += 1
        const matched = matchers.filter(({ re }) => re.test(value)).map(({ term }) => term)
        if (matched.length > 0) {
          hits.push({ lang: bundle.lang, loading: bundle.loading, namespace, key, value, matched })
        }
      }
    }
  }

  if (process.argv.includes('--json')) {
    console.log(JSON.stringify({ bundles: found, vocabulary, hits }, null, 1))
    return
  }

  console.log('\nSCOPE: every leaf string in every locale bundle on disk, matched against the')
  console.log('  unit vocabulary. CANDIDATES, not verdicts: a units setting names both')
  console.log('  systems because they are the choice, and a US window sticker is imperial')
  console.log('  by law. The decision on each hit is a human\'s.\n')

  console.log(`  ${found.length} bundle(s) enumerated from disk:`)
  for (const b of found) {
    console.log(`    ${b.lang.padEnd(6)} ${b.loading.padEnd(8)} ${relative(ROOT, b.dir).split(sep).join('/')}`)
  }
  console.log(`\n  vocabulary (${vocabulary.length}):`)
  console.log(`    ${labels.length} adapter label(s), derived from src/utils/unitAdapters.ts:`)
  console.log(`      ${labels.join(' ')}`)
  console.log(`    ${COMPOUNDS.length} compound(s), stated: ${COMPOUNDS.join(' ')}`)
  console.log(`    ${PROSE.length} prose term(s), stated, ENGLISH ONLY: ${PROSE.join(' ')}`)

  console.log(`\n  ${strings} string(s) scanned, ${hits.length} hit(s).\n`)
  const byLang = new Map<string, Hit[]>()
  for (const h of hits) byLang.set(h.lang, [...(byLang.get(h.lang) ?? []), h])
  for (const b of scanned) {
    const mine = byLang.get(b.lang) ?? []
    console.log(`  ${String(mine.length).padStart(4)}  ${b.lang}`)
  }
  console.log('')
  for (const b of scanned) {
    for (const h of byLang.get(b.lang) ?? []) {
      console.log(`  [${h.lang}] ${h.namespace}:${h.key}   <${h.matched.join(' ')}>`)
      console.log(`      ${h.value.replace(/\s+/g, ' ')}`)
    }
  }
  console.log('')
}

main()
