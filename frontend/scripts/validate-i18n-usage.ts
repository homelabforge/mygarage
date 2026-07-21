#!/usr/bin/env bun
/**
 * i18n usage validation — checks CODE against the locale files.
 *
 * Two checks, both in the direction validate-translations.ts cannot see. That
 * script checks each language AGAINST English, so English is its reference:
 *
 *  1. Every literal `t('...')` in src/ must resolve in en/<namespace>.json.
 *     A key missing from English is invisible to a language-vs-English diff,
 *     and the vitest mock is `t: (key) => key`, so component tests can't see it
 *     either. `t('installPrompt.title')` shipped through both blind spots and
 *     rendered raw to users.
 *
 *  2. Every `labelKey` / `descriptionKey` on an option-list constant must
 *     resolve too. Those are read back as t(option.labelKey) at the render
 *     site, so check 1's literal scan cannot see them — an unmerged or
 *     mistyped key ships a raw "forms:taxTypes.tolls" straight into a
 *     <select> with nothing to catch it. Such constants usually live in schema
 *     modules that never call useTranslation, so their keys must be written
 *     namespace-qualified; a bare one is reported.
 *
 *  3. Every directory in public/locales must be a language the app can load.
 *     Languages are DISCOVERED from disk, so an orphan directory is reported and
 *     translated forever while being unreachable. public/locales/pt was exactly
 *     that: ~1400 keys, absent from supportedLngs and both allowlists, never
 *     fetched, and contributing 50 phantom "missing keys" to every report.
 *
 * Usage: bun run scripts/validate-i18n-usage.ts
 * Exit code: 1 on either. Unlike a missing translation (which falls back to
 * English), a key missing from English has no fallback — i18next renders the
 * raw key. Both are always bugs, so they block.
 */

import { readdirSync, readFileSync, statSync } from 'fs'
import { join, relative } from 'path'
import { SUPPORTED_LANGUAGES } from '../src/constants/i18n'
import {
  EN_DIR,
  LOCALES_DIR,
  ROOT,
  discoverLanguages,
  discoverNamespaces,
  flattenKeys,
  loadJson,
} from './translation-utils'

/** i18n.ts sets defaultNS: 'common' — a bare useTranslation() resolves there. */
const DEFAULT_NS = 'common'

const SRC = join(ROOT, 'src')
const SKIP_DIRS = new Set(['__tests__', 'locales', 'node_modules'])

function walk(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      if (!SKIP_DIRS.has(entry)) out.push(...walk(full))
    } else if (/\.(ts|tsx)$/.test(entry) && !/\.test\.tsx?$/.test(entry)) {
      out.push(full)
    }
  }
  return out
}

/** Namespaces a file binds via useTranslation('x') / useTranslation(['x','y']) / useTranslation(). */
function namespacesFor(text: string): string[] {
  const found = new Set<string>()
  for (const m of text.matchAll(/useTranslation\(\s*'([^']+)'/g)) found.add(m[1])
  for (const m of text.matchAll(/useTranslation\(\s*\[([^\]]+)\]/g)) {
    for (const q of m[1].matchAll(/'([^']+)'/g)) found.add(q[1])
  }
  if (/useTranslation\(\s*\)/.test(text)) found.add(DEFAULT_NS)
  return [...found]
}

const namespaces = discoverNamespaces()
const englishKeys = new Map<string, Set<string>>()
for (const ns of namespaces) {
  englishKeys.set(ns, new Set(flattenKeys(loadJson(join(EN_DIR, `${ns}.json`)))))
}

interface Violation {
  file: string
  line: number
  key: string
  searched: string[]
  /** How the key is written in source — a labelKey never appears as t('...'). */
  via: 'call' | 'field'
}

const violations: Violation[] = []

/** Resolve one key literal against the namespaces available to its file. */
function record(
  file: string,
  text: string,
  index: number,
  rawKey: string,
  bound: string[],
  via: 'call' | 'field',
): void {
  let key = rawKey
  let searched = bound
  if (rawKey.includes(':')) {
    const [ns, ...rest] = rawKey.split(':')
    key = rest.join(':')
    searched = [ns]
  }

  if (searched.some(ns => englishKeys.get(ns)?.has(key))) return

  violations.push({
    file: relative(ROOT, file),
    line: text.slice(0, index).split('\n').length,
    key: rawKey,
    searched,
    via,
  })
}

for (const file of walk(SRC)) {
  const text = readFileSync(file, 'utf-8')
  const bound = namespacesFor(text)

  // Literal t('key') / t('key', { ... }) only. Template literals are dynamic and
  // every one in the codebase carries a defaultValue, so they can't render raw.
  //
  // Note this runs even when the file binds no namespace. Skipping bound-less
  // files was a silent hole: the Zod schema factories take `t` as a parameter
  // and never call useTranslation, so every `t('common:validation.…')` in them
  // went unchecked — the entire factory-schema effort was invisible to this
  // gate. A namespace-qualified key carries its own scope and needs no binding;
  // only a BARE key in a bound-less file is genuinely unresolvable, and that is
  // reported rather than skipped.
  for (const m of text.matchAll(/\bt\(\s*'([^']+)'\s*(,\s*\{[^}]*\})?\s*\)/g)) {
    const [, rawKey, opts = ''] = m
    if (opts.includes('defaultValue')) continue

    // i18next takes the namespace two ways: the 'ns:key' prefix, and an
    // { ns: 'forms' } option. Only honouring the prefix made every
    // { ns } call a false positive once its defaultValue was removed —
    // the key exists, just not in the namespace this file binds.
    const nsOpt = opts.match(/\bns:\s*'([^']+)'/)
    const scope = nsOpt && !rawKey.includes(':') ? [nsOpt[1]] : bound

    if (scope.length === 0 && !rawKey.includes(':')) {
      violations.push({
        file: relative(ROOT, file),
        line: text.slice(0, m.index ?? 0).split('\n').length,
        key: rawKey,
        searched: ['<no useTranslation in this file — qualify the key as "ns:key">'],
        via: 'call',
      })
      continue
    }

    record(file, text, m.index ?? 0, rawKey, scope, 'call')
  }

  // `labelKey` / `descriptionKey` fields on option-list constants, resolved at
  // the render site as t(option.labelKey). That indirection is invisible to the
  // t('literal') scan above, so a typo or an unmerged key ships a raw
  // "forms:taxTypes.tolls" into a <select> with nothing to catch it.
  //
  // These constants often live in schema modules that never call
  // useTranslation, so a bare key there has no namespace to resolve against and
  // is reported — such a key MUST be written namespace-qualified.
  for (const m of text.matchAll(/\b(?:labelKey|descriptionKey):\s*['"]([^'"]+)['"]/g)) {
    const rawKey = m[1]
    if (bound.length === 0 && !rawKey.includes(':')) {
      violations.push({
        file: relative(ROOT, file),
        line: text.slice(0, m.index ?? 0).split('\n').length,
        key: rawKey,
        searched: ['<no useTranslation in this file — qualify the key as "ns:key">'],
        via: 'field',
      })
      continue
    }
    record(file, text, m.index ?? 0, rawKey, bound, 'field')
  }
}

// Check 2: every shipped locale directory must be a language the app can load.
// `en` lives in src/ (bundled), so it is never a public/locales directory.
const loadable = new Set(SUPPORTED_LANGUAGES.map(l => l.code).filter(c => c !== 'en'))
const orphans = discoverLanguages().filter(lang => !loadable.has(lang))

let failed = false

if (violations.length > 0) {
  failed = true
  console.log(`✗ ${violations.length} translation key(s) used in code but missing from English:\n`)
  for (const v of violations) {
    console.log(`  ${v.file}:${v.line}`)
    const shown = v.via === 'call' ? `t('${v.key}')` : `labelKey: '${v.key}'`
    console.log(`    ${shown} — not in ${v.searched.map(n => `${n}.json`).join(' or ')}`)
  }
  console.log('\nThese render as the raw key to users — English has no fallback.')
  console.log(`Add them to ${relative(ROOT, EN_DIR)}/<namespace>.json.`)
}

if (orphans.length > 0) {
  failed = true
  console.log(`\n✗ ${orphans.length} locale director(ies) the app can never load:\n`)
  for (const lang of orphans) {
    console.log(`  ${relative(ROOT, join(LOCALES_DIR, lang))}`)
  }
  console.log('\nSUPPORTED_LANGUAGES in src/constants/i18n.ts does not list them, so')
  console.log('i18next never requests them. Either add the language there (and to')
  console.log("backend/app/constants/i18n.py + i18n.ts's supportedLngs), or delete it.")
}

if (failed) process.exit(1)

console.log('✓ All translation keys used in code exist in English.')
console.log('✓ All locale directories are loadable languages.')
process.exit(0)
