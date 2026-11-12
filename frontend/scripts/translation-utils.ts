/**
 * Shared utilities for translation scripts.
 */

import { existsSync, readdirSync, readFileSync } from 'fs'
import { join, resolve } from 'path'

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
