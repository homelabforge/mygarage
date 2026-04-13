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

import { existsSync } from 'fs'
import { join } from 'path'
import {
  LOCALES_DIR,
  discoverLanguages,
  discoverNamespaces,
  flattenKeys,
  getNestedValue,
  loadEnglishData,
  loadJson,
} from './translation-utils'

/** Extract {{variable}} interpolation placeholders from a string. */
function extractInterpolations(value: string): Set<string> {
  const matches = value.match(/\{\{(\w+)\}\}/g) || []
  return new Set(matches)
}

interface Issue {
  lang: string
  namespace: string
  type: 'missing' | 'extra' | 'empty' | 'interpolation'
  key: string
  detail?: string
}

const namespaces = discoverNamespaces()
const languages = discoverLanguages()
const { totalKeys, keysByNamespace, valuesByNamespace } = loadEnglishData(namespaces)
const issues: Issue[] = []

console.log('Translation Validation Report')
console.log('═'.repeat(50))
console.log(`Canonical language: en (${namespaces.length} namespaces)`)
console.log(`Target languages: ${languages.join(', ') || 'none'}`)
console.log()

for (const ns of namespaces) {
  const enKeys = keysByNamespace.get(ns)!
  const enValues = valuesByNamespace.get(ns)!

  for (const lang of languages) {
    const langPath = join(LOCALES_DIR, lang, `${ns}.json`)

    if (!existsSync(langPath)) {
      for (const key of enKeys) {
        issues.push({ lang, namespace: ns, type: 'missing', key })
      }
      continue
    }

    const langData = loadJson(langPath)
    const langKeys = new Set(flattenKeys(langData))

    for (const key of enKeys) {
      if (!langKeys.has(key)) {
        issues.push({ lang, namespace: ns, type: 'missing', key })
      } else {
        const val = getNestedValue(langData, key)
        const enVal = enValues.get(key)
        if (val === '' || val === null) {
          issues.push({ lang, namespace: ns, type: 'empty', key })
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

  // Count actually translated keys (not same as English, not missing, not empty)
  let actuallyTranslated = 0
  for (const ns of namespaces) {
    const enKeys = keysByNamespace.get(ns)!
    const enValues = valuesByNamespace.get(ns)!
    const langPath = join(LOCALES_DIR, lang, `${ns}.json`)
    if (!existsSync(langPath)) continue
    const langData = loadJson(langPath)
    for (const key of enKeys) {
      const enVal = enValues.get(key)
      const langVal = getNestedValue(langData, key)
      if (langVal && langVal !== '' && langVal !== enVal) actuallyTranslated++
    }
  }

  const pct = totalKeys > 0 ? Math.round((actuallyTranslated / totalKeys) * 100) : 0

  console.log(`[${lang}] ${pct}% translated (${actuallyTranslated}/${totalKeys} keys)`)

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
