#!/usr/bin/env bun
/**
 * Translation validation script.
 *
 * Compares each non-English language's JSON keys against the canonical
 * English reference in src/locales/en/. Reports missing, extra, and
 * empty-value keys.
 *
 * Usage: bun run scripts/validate-translations.ts
 * Exit code: 1 if any missing keys found, 0 otherwise.
 */

import { readdirSync, readFileSync, existsSync } from 'fs'
import { join, resolve } from 'path'

const ROOT = resolve(import.meta.dirname, '..')
const EN_DIR = join(ROOT, 'src', 'locales', 'en')
const LOCALES_DIR = join(ROOT, 'public', 'locales')

interface Issue {
  lang: string
  namespace: string
  type: 'missing' | 'extra' | 'empty' | 'interpolation'
  key: string
  detail?: string
}

/** Extract {{variable}} interpolation placeholders from a string. */
function extractInterpolations(value: string): Set<string> {
  const matches = value.match(/\{\{(\w+)\}\}/g) || []
  return new Set(matches)
}

/** Recursively flatten a nested JSON object into dot-separated keys. */
function flattenKeys(obj: Record<string, unknown>, prefix = ''): string[] {
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
function getNestedValue(obj: Record<string, unknown>, path: string): unknown {
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

function loadJson(path: string): Record<string, unknown> {
  return JSON.parse(readFileSync(path, 'utf-8'))
}

// Discover namespaces from English canonical files
const namespaces = readdirSync(EN_DIR)
  .filter(f => f.endsWith('.json'))
  .map(f => f.replace('.json', ''))

// Discover non-English languages
const languages = existsSync(LOCALES_DIR)
  ? readdirSync(LOCALES_DIR).filter(d => {
      const full = join(LOCALES_DIR, d)
      try { return Bun.file(full).size === undefined || readdirSync(full).length > 0 } catch { return false }
    })
  : []

const issues: Issue[] = []

console.log('Translation Validation Report')
console.log('═'.repeat(50))
console.log(`Canonical language: en (${namespaces.length} namespaces)`)
console.log(`Target languages: ${languages.join(', ') || 'none'}`)
console.log()

for (const ns of namespaces) {
  const enPath = join(EN_DIR, `${ns}.json`)
  const enData = loadJson(enPath)
  const enKeys = flattenKeys(enData)
  for (const lang of languages) {
    const langPath = join(LOCALES_DIR, lang, `${ns}.json`)

    if (!existsSync(langPath)) {
      // Entire namespace file missing
      for (const key of enKeys) {
        issues.push({ lang, namespace: ns, type: 'missing', key })
      }
      continue
    }

    const langData = loadJson(langPath)
    const langKeys = new Set(flattenKeys(langData))

    // Check for missing keys
    for (const key of enKeys) {
      if (!langKeys.has(key)) {
        issues.push({ lang, namespace: ns, type: 'missing', key })
      } else {
        const val = getNestedValue(langData, key)
        // Check if value is empty or same as English (placeholder)
        const enVal = getNestedValue(enData, key)
        if (val === '' || val === null) {
          issues.push({ lang, namespace: ns, type: 'empty', key })
        } else if (val === enVal) {
          // Same as English — likely a placeholder (not counted as translated)
        }

        // Check interpolation variables are preserved
        if (typeof enVal === 'string' && typeof val === 'string') {
          const enVars = extractInterpolations(enVal)
          const trVars = extractInterpolations(val)
          if (enVars.size > 0) {
            const missing: string[] = []
            for (const v of enVars) {
              if (!trVars.has(v)) missing.push(v)
            }
            if (missing.length > 0) {
              issues.push({
                lang, namespace: ns, type: 'interpolation', key,
                detail: `missing {{${missing.join('}}, {{')}}}`
              })
            }
          }
        }
      }
    }

    // Check for extra keys not in English
    for (const key of langKeys) {
      if (!enKeys.includes(key)) {
        issues.push({ lang, namespace: ns, type: 'extra', key })
      }
    }
  }
}

// Print per-language summary
for (const lang of languages) {
  const langIssues = issues.filter(i => i.lang === lang)
  const missing = langIssues.filter(i => i.type === 'missing')
  const empty = langIssues.filter(i => i.type === 'empty')
  const extra = langIssues.filter(i => i.type === 'extra')
  const interpolation = langIssues.filter(i => i.type === 'interpolation')

  const totalEnKeys = namespaces.reduce((sum: number, ns: string) => {
    const enData = loadJson(join(EN_DIR, `${ns}.json`))
    return sum + flattenKeys(enData).length
  }, 0)

  // Count actually translated keys (not same as English, not missing, not empty)
  let actuallyTranslated = 0
  for (const ns of namespaces) {
    const enPath2 = join(EN_DIR, `${ns}.json`)
    const langPath2 = join(LOCALES_DIR, lang, `${ns}.json`)
    if (!existsSync(langPath2)) continue
    const enData2 = loadJson(enPath2)
    const langData2 = loadJson(langPath2)
    for (const key of flattenKeys(enData2)) {
      const enVal = getNestedValue(enData2, key)
      const langVal = getNestedValue(langData2, key)
      if (langVal && langVal !== '' && langVal !== enVal) actuallyTranslated++
    }
  }

  const pct = totalEnKeys > 0 ? Math.round((actuallyTranslated / totalEnKeys) * 100) : 0

  console.log(`[${lang}] ${pct}% translated (${actuallyTranslated}/${totalEnKeys} keys)`)

  if (missing.length > 0) {
    console.log(`  Missing (${missing.length}):`)
    for (const i of missing.slice(0, 10)) {
      console.log(`    - ${i.namespace}:${i.key}`)
    }
    if (missing.length > 10) console.log(`    ... and ${missing.length - 10} more`)
  }
  if (empty.length > 0) {
    console.log(`  Empty values (${empty.length}):`)
    for (const i of empty.slice(0, 5)) {
      console.log(`    - ${i.namespace}:${i.key}`)
    }
    if (empty.length > 5) console.log(`    ... and ${empty.length - 5} more`)
  }
  if (extra.length > 0) {
    console.log(`  Extra keys (${extra.length}):`)
    for (const i of extra.slice(0, 5)) {
      console.log(`    - ${i.namespace}:${i.key}`)
    }
  }
  if (interpolation.length > 0) {
    console.log(`  Missing interpolation variables (${interpolation.length}):`)
    for (const i of interpolation.slice(0, 10)) {
      console.log(`    - ${i.namespace}:${i.key} — ${i.detail}`)
    }
    if (interpolation.length > 10) console.log(`    ... and ${interpolation.length - 10} more`)
  }
  console.log()
}

const missingCount = issues.filter(i => i.type === 'missing').length
const interpolationCount = issues.filter(i => i.type === 'interpolation').length
if (missingCount > 0 || interpolationCount > 0) {
  if (missingCount > 0) console.log(`⚠ ${missingCount} missing key(s) found across all languages.`)
  if (interpolationCount > 0) console.log(`⚠ ${interpolationCount} interpolation variable(s) missing across all languages.`)
  process.exit(1)
} else {
  console.log('✓ All translation keys present across all languages.')
  process.exit(0)
}
