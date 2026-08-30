#!/usr/bin/env bun
/**
 * i18n usage validation — checks CODE against the locale files.
 *
 * Two checks, both in the direction validate-translations.ts cannot see. That
 * script checks each language AGAINST English, so English is its reference:
 *
 *  1. Every literal `t('...')` in src/ must resolve in en/<namespace>.json.
 *     A key held in a module-level constant is resolved through that constant
 *     (`t(UNKNOWN_UNIT_KEY)`); the literal-only scan used to miss those
 *     entirely, so deleting the English string left this gate green.
 *     A key missing from English is invisible to a language-vs-English diff,
 *     and the vitest mock is `t: (key) => key`, so component tests can't see it
 *     either. `t('installPrompt.title')` shipped through both blind spots and
 *     rendered raw to users.
 *
 *  2. Every `labelKey` / `descriptionKey` on an option-list constant, AND every
 *     `negativeKey` / `tooLargeKey` / `invalidKey` / `requiredKey` /
 *     `integerKey` passed to `makeNumericField` (schemas/shared.ts), must
 *     resolve too. Both are read back as t(...) at the render/validation
 *     site — option labels via t(option.labelKey), numeric-field messages via
 *     t(opts.negativeKey) etc. inside makeNumericField's superRefine — so
 *     check 1's literal scan cannot see either: an unmerged or mistyped key
 *     ships a raw "forms:taxTypes.tolls" straight into a <select>, or a raw
 *     "common:validation.amount.negative" straight into a form error, with
 *     nothing to catch it. Such constants usually live in schema modules that
 *     never call useTranslation, so their keys must be written
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

/**
 * Module-level `const NAME = 'literal'` bindings, so `t(NAME)` can be resolved.
 *
 * Check 1 used to extract only a literal inside `t(...)`, which made a key held
 * in a constant invisible: `utils/telemetryUnits.ts` spells its key once as
 * `UNKNOWN_UNIT_KEY` and passes the const at both call sites, so deleting the
 * English string left this gate GREEN while the marker it names is the whole
 * user-visible half of a deliverable. That is the same failure mode
 * `installPrompt.title` produced, reintroduced through indirection rather than
 * through a bare key, and namespace-qualifying the key does not close it.
 *
 * Anchored at column 0 (`^`, with an optional `export`), so ONLY module-level
 * constants are collected. That restriction is what makes a regex sound here:
 * this script has no scope model, and an indented `const key = '...'` inside a
 * function could shadow a module name or hold something that is not a key at
 * all. A function-scoped indirection stays invisible, exactly as before.
 */
function stringConstsFor(text: string): Map<string, string> {
  const out = new Map<string, string>()
  for (const m of text.matchAll(
    /^(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*(?::[^=\n]+)?=\s*'([^'\\\n]*)'/gm
  )) {
    out.set(m[1], m[2])
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
  /** How the key is written in source — a field key never appears as t('...'). */
  via: 'call' | 'field'
  /** The field name for a `via: 'field'` violation (e.g. 'labelKey', 'negativeKey'). Unused for 'call'. */
  field?: string
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
  field?: string,
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
    field,
    via,
  })
}

for (const file of walk(SRC)) {
  const text = readFileSync(file, 'utf-8')
  const bound = namespacesFor(text)
  const consts = stringConstsFor(text)

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
  const scanCall = (rawKey: string, opts: string, index: number): void => {
    if (opts.includes('defaultValue')) return

    // i18next takes the namespace two ways: the 'ns:key' prefix, and an
    // { ns: 'forms' } option. Only honouring the prefix made every
    // { ns } call a false positive once its defaultValue was removed —
    // the key exists, just not in the namespace this file binds.
    const nsOpt = opts.match(/\bns:\s*'([^']+)'/)
    const scope = nsOpt && !rawKey.includes(':') ? [nsOpt[1]] : bound

    if (scope.length === 0 && !rawKey.includes(':')) {
      violations.push({
        file: relative(ROOT, file),
        line: text.slice(0, index).split('\n').length,
        key: rawKey,
        searched: ['<no useTranslation in this file — qualify the key as "ns:key">'],
        via: 'call',
      })
      return
    }

    record(file, text, index, rawKey, scope, 'call')
  }

  for (const m of text.matchAll(/\bt\(\s*'([^']+)'\s*(,\s*\{[^}]*\})?\s*\)/g)) {
    scanCall(m[1], m[2] ?? '', m.index ?? 0)
  }

  // The same call, with the key held in a module-level constant. Resolved
  // through `stringConstsFor` and then treated exactly as a literal would be,
  // so a const-held key gets the namespace rules, the defaultValue skip and the
  // bound-less report identically. An identifier this file does not declare at
  // module level (a parameter, a local, a field lookup) is not in the map and is
  // skipped, which is what the scan did with all of them before.
  for (const m of text.matchAll(/\bt\(\s*([A-Za-z_$][\w$]*)\s*(,\s*\{[^}]*\})?\s*\)/g)) {
    const resolved = consts.get(m[1])
    if (resolved === undefined) continue
    scanCall(resolved, m[2] ?? '', m.index ?? 0)
  }

  // `labelKey` / `descriptionKey` fields on option-list constants (resolved at
  // the render site as t(option.labelKey)), and `negativeKey` / `tooLargeKey` /
  // `invalidKey` / `requiredKey` / `integerKey` passed to `makeNumericField`
  // (resolved inside its superRefine as t(opts.negativeKey) etc.). Both
  // indirections are invisible to the t('literal') scan above, so a typo or
  // an unmerged key ships a raw "forms:taxTypes.tolls" into a <select>, or a
  // raw "common:validation.amount.negative" into a form error, with nothing
  // to catch it.
  //
  // These constants/factory calls often live in schema modules that never
  // call useTranslation, so a bare key there has no namespace to resolve
  // against and is reported — such a key MUST be written namespace-qualified.
  for (const m of text.matchAll(
    /\b(labelKey|descriptionKey|negativeKey|tooLargeKey|invalidKey|requiredKey|integerKey):\s*['"]([^'"]+)['"]/g
  )) {
    const field = m[1]
    const rawKey = m[2]
    if (bound.length === 0 && !rawKey.includes(':')) {
      violations.push({
        file: relative(ROOT, file),
        line: text.slice(0, m.index ?? 0).split('\n').length,
        key: rawKey,
        searched: ['<no useTranslation in this file — qualify the key as "ns:key">'],
        via: 'field',
        field,
      })
      continue
    }
    record(file, text, m.index ?? 0, rawKey, bound, 'field', field)
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
    const shown = v.via === 'call' ? `t('${v.key}')` : `${v.field ?? 'labelKey'}: '${v.key}'`
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
