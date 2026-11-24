#!/usr/bin/env bun
/**
 * Translation validation script.
 *
 * Compares each non-English language's JSON keys against the canonical
 * English reference in src/locales/en/. Reports missing, extra, and
 * empty-value keys. Plural sets follow the language: pl needs _few and _many
 * on top of English's _one/_other, ms only reads _other. A missing category
 * renders English for that count, so it's reported as missing.
 *
 * Usage: bun run scripts/validate-translations.ts
 * Exit code: 1 if any {{interpolation}} placeholders are broken, 0 otherwise.
 * Missing keys are reported as a non-blocking warning (they fall back to
 * English), so this can gate PRs without blocking new English strings.
 */

import {
  analyzeLocale,
  discoverLanguages,
  discoverNamespaces,
  loadEnglishData,
  type LocaleIssue,
} from './translation-utils'

const namespaces = discoverNamespaces()
const languages = discoverLanguages()
const english = loadEnglishData(namespaces)
const reports = new Map(languages.map(lang => [lang, analyzeLocale(lang, namespaces, english)]))
const issues: LocaleIssue[] = [...reports.values()].flatMap(r => r.issues)

console.log('Translation Validation Report')
console.log('═'.repeat(50))
console.log(`Canonical language: en (${namespaces.length} namespaces)`)
console.log(`Target languages: ${languages.join(', ') || 'none'}`)
console.log()

for (const lang of languages) {
  const langIssues = issues.filter(i => i.lang === lang)
  const missing = langIssues.filter(i => i.type === 'missing')
  const empty = langIssues.filter(i => i.type === 'empty')
  const extra = langIssues.filter(i => i.type === 'extra')
  const interpolation = langIssues.filter(i => i.type === 'interpolation')

  // Count translated keys: values that differ from English, plus values that
  // are correctly identical because they contain nothing translatable.
  const { translated, total } = reports.get(lang)!
  const pct = total > 0 ? Math.round((translated / total) * 100) : 0

  console.log(`[${lang}] ${pct}% translated (${translated}/${total} keys)`)

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
    console.log(`  Broken interpolation variables (${interpolation.length}):`)
    for (const i of interpolation.slice(0, 10)) {
      console.log(`    - ${i.namespace}:${i.key}: ${i.detail}`)
    }
    if (interpolation.length > 10) console.log(`    ... and ${interpolation.length - 10} more`)
  }
  console.log()
}

const missingCount = issues.filter(i => i.type === 'missing').length
const interpolationCount = issues.filter(i => i.type === 'interpolation').length

// Only broken {{interpolation}} placeholders are a hard failure: they're a
// real bug in a provided translation and can't be caught by eye across every
// key. Missing keys are a non-blocking warning; untranslated keys fall back
// to English, which is expected while a language is still in progress and
// lets new English strings land without translating every language first.
if (interpolationCount > 0) {
  console.log(`✗ ${interpolationCount} broken interpolation variable(s): these break rendering.`)
  if (missingCount > 0) {
    console.log(`  (${missingCount} missing key(s) also found; those fall back to English and don't block.)`)
  }
  process.exit(1)
}

if (missingCount > 0) {
  console.log(`⚠ ${missingCount} missing key(s), they will fall back to English (non-blocking).`)
} else {
  console.log('✓ All translation keys present across all languages.')
}
process.exit(0)
