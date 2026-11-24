/**
 * Shared utilities for translation scripts.
 */

import { createHash } from 'crypto'
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'fs'
import { dirname, join, resolve } from 'path'

export const ROOT = resolve(import.meta.dirname, '..')
export const PROJECT_ROOT = resolve(ROOT, '..')
export const EN_DIR = join(ROOT, 'src', 'locales', 'en')
export const LOCALES_DIR = join(ROOT, 'public', 'locales')

export const LANGUAGE_NAMES: Record<string, string> = {
  pl: 'Polish',
  uk: 'Ukrainian',
  ru: 'Russian',
  de: 'German',
  es: 'Spanish',
  fr: 'French',
  it: 'Italian',
  ja: 'Japanese',
  ko: 'Korean',
  ms: 'Malay',
  nl: 'Dutch',
  'pt-BR': 'Brazilian Portuguese',
  sv: 'Swedish',
  zh: 'Chinese (Simplified)',
}

export const LANGUAGE_FLAGS: Record<string, string> = {
  pl: '🇵🇱',
  uk: '🇺🇦',
  ru: '🇷🇺',
  de: '🇩🇪',
  es: '🇪🇸',
  fr: '🇫🇷',
  it: '🇮🇹',
  ja: '🇯🇵',
  ko: '🇰🇷',
  ms: '🇲🇾',
  nl: '🇳🇱',
  'pt-BR': '🇧🇷',
  sv: '🇸🇪',
  zh: '🇨🇳',
}

/** Recursively flatten a nested JSON object into dot-separated keys. */
export function flattenKeys(obj: Record<string, unknown>, prefix = ''): string[] {
  const keys: string[] = []
  for (const [k, v] of Object.entries(obj)) {
    const fullKey = prefix ? `${prefix}.${k}` : k
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      keys.push(...flattenKeys(v as Record<string, unknown>, fullKey))
    } else {
      keys.push(fullKey)
    }
  }
  return keys
}

/** Get value at a dot-separated path from a nested object. */
export function getNestedValue(obj: Record<string, unknown>, path: string): unknown {
  const parts = path.split('.')
  let current: unknown = obj
  for (const part of parts) {
    if (current && typeof current === 'object') {
      current = (current as Record<string, unknown>)[part]
    } else {
      return undefined
    }
  }
  return current
}

export function loadJson(path: string): Record<string, unknown> {
  return JSON.parse(readFileSync(path, 'utf-8'))
}

/** Write a locale file the way they're all formatted: 2-space JSON, trailing newline. */
export function writeJson(path: string, data: Record<string, unknown>): void {
  mkdirSync(dirname(path), { recursive: true })
  writeFileSync(path, JSON.stringify(data, null, 2) + '\n')
}

/** Delete a dotted key, then any parent objects it leaves empty. */
export function deleteNestedKey(obj: Record<string, unknown>, path: string): boolean {
  const parts = path.split('.')
  const parents: Record<string, unknown>[] = [obj]
  let current = obj
  for (const part of parts.slice(0, -1)) {
    const next = current[part]
    if (!next || typeof next !== 'object' || Array.isArray(next)) return false
    current = next as Record<string, unknown>
    parents.push(current)
  }
  const leaf = parts[parts.length - 1]
  if (!(leaf in current)) return false
  delete current[leaf]
  for (let i = parents.length - 1; i > 0; i--) {
    if (Object.keys(parents[i]).length > 0) break
    delete parents[i - 1][parts[i - 1]]
  }
  return true
}

/**
 * Tokens that are correctly identical in every language: product and protocol
 * names, abbreviations, document field codes and unit abbreviations. See
 * "Things NOT to Translate" in TRANSLATING.md.
 */
export const UNTRANSLATABLE_TOKENS = new Set([
  // Abbreviations and document field codes.
  'ABRP', 'API', 'CO', 'CSV', 'CV', 'DEF', 'DOT', 'DTC', 'E', 'ECU', 'HIN',
  'ID', 'INV', 'JSON', 'NHTSA', 'OBD', 'OBD2', 'OIDC', 'PDF', 'PKCE', 'PO', 'V',
  'VIN', 'WO',
  // Product, protocol and brand names.
  'AutoRef', 'CarComplaints', 'Drivvo', 'Euro', 'Fuelio', 'LiveLink', 'Matrix',
  'Mirage', 'Mitsubishi', 'MyGarage', 'OpenAI', 'OpenRouter', 'RappelConso',
  'Tesla',
])

/**
 * Whether an English value contains nothing that should be translated: only
 * {{placeholders}}, numbers, punctuation and allowlisted tokens. Such a value
 * is already correct when a locale copies it verbatim, so it counts towards
 * coverage instead of being reported as untranslated.
 */
export function isTranslationInvariant(value: unknown): boolean {
  if (typeof value !== 'string' || value.trim() === '') return false
  const tokens = value.replace(/\{\{\s*\w+\s*\}\}/g, ' ').match(/[A-Za-z][A-Za-z0-9]*/g) ?? []
  return tokens.every(token => UNTRANSLATABLE_TOKENS.has(token))
}

/** Discover namespace names from English canonical files. */
export function discoverNamespaces(): string[] {
  return readdirSync(EN_DIR)
    .filter((f: string) => f.endsWith('.json'))
    .map((f: string) => f.replace('.json', ''))
}

/** Discover non-English language codes with at least one file. */
export function discoverLanguages(): string[] {
  if (!existsSync(LOCALES_DIR)) return []
  return readdirSync(LOCALES_DIR).filter((d: string) => {
    try { return readdirSync(join(LOCALES_DIR, d)).length > 0 } catch { return false }
  })
}

/** Load and cache all English namespace data: keys and key→value maps. */
export function loadEnglishData(namespaces: string[]): {
  totalKeys: number
  keysByNamespace: Map<string, string[]>
  valuesByNamespace: Map<string, Map<string, unknown>>
} {
  const keysByNamespace = new Map<string, string[]>()
  const valuesByNamespace = new Map<string, Map<string, unknown>>()
  let totalKeys = 0

  for (const ns of namespaces) {
    const enData = loadJson(join(EN_DIR, `${ns}.json`))
    const keys = flattenKeys(enData)
    const values = new Map<string, unknown>()
    for (const key of keys) {
      values.set(key, getNestedValue(enData, key))
    }
    keysByNamespace.set(ns, keys)
    valuesByNamespace.set(ns, values)
    totalKeys += keys.length
  }

  return { totalKeys, keysByNamespace, valuesByNamespace }
}

/**
 * The plural categories a language actually asks i18next for. A locale that's
 * missing one falls back to ENGLISH for that count, not to its own `_other`
 * (checked 2026-11: pl with only one/other rendered English for 2, 5 and 22).
 */
export function pluralCategories(lang: string): string[] {
  return new Intl.PluralRules(lang).resolvedOptions().pluralCategories
}

const PLURAL_SUFFIX = /^(.*)_(zero|one|two|few|many|other)$/

/** The plural base of `key` when English has `<base>_other`, else null. */
export function pluralBase(key: string, enKeys: ReadonlySet<string>): string | null {
  const m = key.match(PLURAL_SUFFIX)
  return m && enKeys.has(`${m[1]}_other`) ? m[1] : null
}

export interface ExpectedKey {
  key: string
  /** The English text this key translates (a plural form reads `_other` when English lacks it). */
  enValue: unknown
}

/**
 * The keys one language must carry for a namespace: English's, in English
 * order, with each plural set swapped for the language's own categories.
 */
export function expectedKeys(
  enKeys: readonly string[],
  enValues: ReadonlyMap<string, unknown>,
  lang: string,
): ExpectedKey[] {
  const enSet = new Set(enKeys)
  const done = new Set<string>()
  const out: ExpectedKey[] = []
  for (const key of enKeys) {
    const base = pluralBase(key, enSet)
    if (base === null) {
      out.push({ key, enValue: enValues.get(key) })
      continue
    }
    if (done.has(base)) continue
    done.add(base)
    for (const cat of pluralCategories(lang)) {
      out.push({
        key: `${base}_${cat}`,
        enValue: enValues.get(`${base}_${cat}`) ?? enValues.get(`${base}_other`),
      })
    }
  }
  return out
}

/**
 * Placeholders with their formatter, spacing normalised: `{{ count , number }}`
 * comes back as `{{count, number}}`. The formatter matters, German shows
 * 12.345 with `number` and 12345 without.
 */
export function placeholderTokens(value: string): Set<string> {
  return new Set(
    [...value.matchAll(/\{\{\s*(\w+)\s*(?:,\s*([^}]*?)\s*)?\}\}/g)].map(m =>
      m[2] ? `{{${m[1]}, ${m[2]}}}` : `{{${m[1]}}}`,
    ),
  )
}

/**
 * Whole command lines a user pastes into a shell. The pattern spans below only
 * catch their pieces, so these have to come through verbatim as one string.
 */
export const PROTECTED: Readonly<Record<string, string>> = {
  'settings:backupTab.postgresRestoreMessage':
    'pg_restore --clean --if-exists --no-owner --no-privileges -d <dbname> mygarage.pgdump',
  'forms:modal.livelink.odometerUnitTorqueMiRepair':
    'python tools/repair_wican_odometer_unit.py --device-id {{deviceId}} --key TORQUE_ODOMETER --to km',
}

// Bits of English that are code, not copy. Placeholders get swapped for a NUL
// first so `{{unit}}/day` doesn't read as a /day command.
const SPAN_PATTERNS: readonly RegExp[] = [
  /\bhttps?:\/\/[^\s)'"\0]*[^\s)'".,;:!?\0]/g,
  /<[^<>\s\0]+>/g,
  /(?<![\w-])--[a-z][\w-]*/g,
  /\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b/g,
  /\b[\w./-]*\w\.(?:py|pgdump|sql|db|sqlite|json|ya?ml|env|sh|csv|toml|log)\b/g,
  /\b[\w-]+(?:\.[\w-]+)+:\d{2,5}\b/g,
  /(?<=^|[\s"'(\u00ab\u201c])\/[a-z][a-z0-9_]*\b(?!\/)/g,
]

/** Substrings of an English value a translation has to keep verbatim. */
export function protectedSpans(
  nsKey: string,
  enValue: string,
  registry: Readonly<Record<string, string>> = PROTECTED,
): string[] {
  const masked = enValue.replace(/\{\{[^}]*\}\}/g, '\0')
  const spans: string[] = []
  for (const re of SPAN_PATTERNS) {
    for (const m of masked.matchAll(re)) if (!spans.includes(m[0])) spans.push(m[0])
  }
  const literal = registry[nsKey]
  if (literal !== undefined && !spans.includes(literal)) spans.push(literal)
  return spans
}

export type LocaleIssueType =
  | 'missing'
  | 'extra'
  | 'empty'
  | 'interpolation'
  | 'protected'
  | 'script'
  | 'stale'
  | 'unrecorded'
  | 'draft'

export interface LocaleIssue {
  lang: string
  namespace: string
  type: LocaleIssueType
  key: string
  detail?: string
}

export interface LocaleReport {
  lang: string
  /** Keys this language should carry (English's, plural sets expanded). */
  total: number
  /** Present, non-empty, and not a copy of English that has something to translate. */
  translated: number
  issues: LocaleIssue[]
}

/** True when a present value still reads as English (nothing was translated). */
export function isEnglishCopy(value: unknown, enValue: unknown): boolean {
  return value === enValue && !isTranslationInvariant(enValue)
}

// ── Translation sources ─────────────────────────────────────────────────────
// scripts/translation-sources/<lang>.json maps "ns:key" to
// "<enHash8>:<trHash8>[:d]": this translation was accepted against this
// English. trHash8 is "=" for an approved copy of English, and ":d" marks a
// machine draft nobody has accepted yet. Nothing writes a record on its own;
// see i18n-stamp.ts.

export const SOURCES_DIR = join(ROOT, 'scripts', 'translation-sources')

/** First 8 hex of SHA-256 of the value as the bundle holds it. */
export function hash8(value: unknown): string {
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  return createHash('sha256').update(text).digest('hex').slice(0, 8)
}

export type SourceState = 'unrecorded' | 'stale' | 'draft' | 'current'

interface ParsedRecord {
  en: string
  tr: string
  draft: boolean
}

function parseRecord(raw: string | undefined): ParsedRecord | null {
  if (raw === undefined) return null
  const [en, tr, flag] = raw.split(':')
  if (!en || !tr) return null
  return { en, tr: tr === '=' ? en : tr, draft: flag === 'd' }
}

/**
 * Where a translation stands against its record. A translation that changed
 * since its record is unrecorded, not current: we don't know which English it
 * was made from, so someone has to accept it.
 */
export function sourceState(raw: string | undefined, enValue: unknown, value: unknown): SourceState {
  const rec = parseRecord(raw)
  if (rec === null || hash8(value) !== rec.tr) return 'unrecorded'
  if (hash8(enValue) !== rec.en) return 'stale'
  return rec.draft ? 'draft' : 'current'
}

/** An English copy someone approved (brand, code), still current. */
export function isApprovedSame(raw: string | undefined, enValue: unknown, value: unknown): boolean {
  return value === enValue && raw?.split(':')[1] === '=' && sourceState(raw, enValue, value) !== 'stale'
}

export interface AcceptEntry {
  nsKey: string
  /** English at the base ref: what the translation was made against. */
  enBase: unknown
  value: unknown
}

/**
 * `key` mode records each entry against its base English, whatever its state
 * (that's how a stale key or a draft gets cleared). `bulk` only records keys
 * that are unrecorded and aren't a copy of English, so it can't paper over a
 * stale key or approve an untranslated one.
 */
export function acceptRecords(
  records: Readonly<Record<string, string>>,
  entries: readonly AcceptEntry[],
  mode: 'bulk' | 'key',
): Record<string, string> {
  const out: Record<string, string> = { ...records }
  for (const { nsKey, enBase, value } of entries) {
    if (mode === 'bulk') {
      if (parseRecord(out[nsKey]) !== null && hash8(value) === parseRecord(out[nsKey])!.tr) continue
      if (value === enBase) continue
    }
    out[nsKey] = `${hash8(enBase)}:${value === enBase ? '=' : hash8(value)}`
  }
  return out
}

/** Drop records whose key this language no longer expects. */
export function pruneRecords(records: Readonly<Record<string, string>>, expected: ReadonlySet<string>): Record<string, string> {
  return Object.fromEntries(Object.entries(records).filter(([k]) => expected.has(k)))
}

export function loadSourceRecords(lang: string): Record<string, string> {
  const path = join(SOURCES_DIR, `${lang}.json`)
  return existsSync(path) ? (JSON.parse(readFileSync(path, 'utf-8')) as Record<string, string>) : {}
}

const isPlainObject = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

/**
 * A locale object re-keyed into English order, so diffs line up across
 * languages. Plural members sit where English's do, in this language's
 * category order. Keys English doesn't have keep going at the end; no value
 * changes.
 */
export function sortToEnglish(
  en: Record<string, unknown>,
  data: Record<string, unknown>,
  lang: string,
): Record<string, unknown> {
  const cats = pluralCategories(lang)
  const enKeys = Object.keys(en)
  const out: Record<string, unknown> = {}
  const place = (k: string): void => {
    if (!(k in data) || k in out) return
    const [e, v] = [en[k], data[k]]
    out[k] = isPlainObject(e) && isPlainObject(v) ? sortToEnglish(e, v, lang) : v
  }
  for (const k of enKeys) {
    const m = k.match(/^(.*)_(?:zero|one|two|few|many|other)$/)
    if (m && enKeys.includes(`${m[1]}_other`)) for (const c of cats) place(`${m[1]}_${c}`)
    place(k)
  }
  for (const k of Object.keys(data)) place(k)
  return out
}

/**
 * English values holding an em-dash or en-dash, as `ns:key`. House style is
 * no dashes in English copy; locales keep their own typography.
 */
export function englishDashes(valuesByNamespace: ReadonlyMap<string, ReadonlyMap<string, unknown>>): string[] {
  const out: string[] = []
  for (const [ns, values] of valuesByNamespace) {
    for (const [key, value] of values) if (typeof value === 'string' && /[\u2013\u2014]/.test(value)) out.push(`${ns}:${key}`)
  }
  return out
}

// Letters that can't belong in a language: Cyrillic in a Latin-script locale,
// Russian-only letters in uk and Ukrainian-only ones in ru. A pl string once
// shipped in Ukrainian, so this blocks.
const LATIN = /\p{Script=Cyrillic}/u
export const WRONG_SCRIPT: Readonly<Record<string, RegExp>> = {
  de: LATIN,
  fr: LATIN,
  it: LATIN,
  ms: LATIN,
  pl: LATIN,
  'pt-BR': LATIN,
  uk: /[ыэъёЫЭЪЁ]/,
  ru: /[іїєґІЇЄҐ]/,
}

/**
 * Compare one namespace of one language against English. Pure, so the gate's
 * tests can hand it fixtures.
 */
export function compareNamespace(
  lang: string,
  ns: string,
  enKeys: readonly string[],
  enValues: ReadonlyMap<string, unknown>,
  langData: Record<string, unknown>,
  records?: Readonly<Record<string, string>>,
): LocaleReport {
  const issues: LocaleIssue[] = []
  let translated = 0
  const expected = expectedKeys(enKeys, enValues, lang)
  const langKeys = new Set(flattenKeys(langData))
  const expectedSet = new Set(expected.map(e => e.key))

  for (const { key, enValue } of expected) {
    if (!langKeys.has(key)) {
      issues.push({ lang, namespace: ns, type: 'missing', key })
      continue
    }
    const value = getNestedValue(langData, key)
    if (value === '' || value === null) {
      issues.push({ lang, namespace: ns, type: 'empty', key })
      continue
    }
    if (typeof enValue === 'string' && typeof value === 'string') {
      const enTokens = placeholderTokens(enValue)
      const trTokens = placeholderTokens(value)
      const lost = [...enTokens].filter(v => !trTokens.has(v))
      const added = [...trTokens].filter(v => !enTokens.has(v))
      if (lost.length > 0 || added.length > 0) {
        const parts: string[] = []
        if (lost.length > 0) parts.push(`missing ${lost.join(', ')}`)
        if (added.length > 0) parts.push(`unknown ${added.join(', ')}`)
        issues.push({ lang, namespace: ns, type: 'interpolation', key, detail: parts.join('; ') })
      }
      if (WRONG_SCRIPT[lang]?.test(value)) issues.push({ lang, namespace: ns, type: 'script', key })
      const dropped = protectedSpans(`${ns}:${key}`, enValue).filter(span => !value.includes(span))
      if (dropped.length > 0) {
        issues.push({ lang, namespace: ns, type: 'protected', key, detail: dropped.map(d => `missing "${d}"`).join('; ') })
      }
    }
    const raw = records?.[`${ns}:${key}`]
    if (records !== undefined && !isEnglishCopy(value, enValue)) {
      const state = sourceState(raw, enValue, value)
      if (state !== 'current') issues.push({ lang, namespace: ns, type: state, key })
    }
    if (!isEnglishCopy(value, enValue) || isApprovedSame(raw, enValue, value)) translated++
  }

  for (const key of langKeys) {
    if (!expectedSet.has(key)) issues.push({ lang, namespace: ns, type: 'extra', key })
  }
  return { lang, total: expected.length, translated, issues }
}

/**
 * Compare one language against English, every namespace. Shared by
 * validate-translations.ts and generate-translation-status.ts so the gate and
 * the badge can't disagree.
 */
export function analyzeLocale(
  lang: string,
  namespaces: readonly string[],
  english: ReturnType<typeof loadEnglishData>,
): LocaleReport {
  const report: LocaleReport = { lang, total: 0, translated: 0, issues: [] }
  // No record file yet means nobody has started tracking this language, so
  // there's nothing to call stale or unrecorded.
  const records = existsSync(join(SOURCES_DIR, `${lang}.json`)) ? loadSourceRecords(lang) : undefined
  for (const ns of namespaces) {
    const langPath = join(LOCALES_DIR, lang, `${ns}.json`)
    const part = compareNamespace(
      lang,
      ns,
      english.keysByNamespace.get(ns)!,
      english.valuesByNamespace.get(ns)!,
      existsSync(langPath) ? loadJson(langPath) : {},
      records,
    )
    report.total += part.total
    report.translated += part.translated
    report.issues.push(...part.issues)
  }
  return report
}
