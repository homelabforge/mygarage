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
 * Exit code: 1 if any {{interpolation}} placeholder (formatter included) is
 * broken, a protected span (a command, flag, env name or URL) is missing, or
 * an English value uses an em-dash or en-dash; 0 otherwise.
 * Missing keys are reported as a non-blocking warning (they fall back to
 * English), so this can gate PRs without blocking new English strings.
 */

import {
  analyzeLocale,
  discoverLanguages,
  discoverNamespaces,
  englishDashes,
  loadEnglishData,
  type LocaleIssue,
} from './translation-utils'

function main(): void {

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
    const protectedSpans = langIssues.filter(i => i.type === 'protected')

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
    if (protectedSpans.length > 0) {
      console.log(`  Changed commands, flags or names (${protectedSpans.length}):`)
      for (const i of protectedSpans) console.log(`    - ${i.namespace}:${i.key}: ${i.detail}`)
    }
    console.log()
  }

  const missingCount = issues.filter(i => i.type === 'missing').length
  const interpolationCount = issues.filter(i => i.type === 'interpolation').length
  const protectedCount = issues.filter(i => i.type === 'protected').length
  const dashes = englishDashes(english.valuesByNamespace)

  // The hard failures: a broken placeholder or a changed command is a real bug
  // in a provided translation (a raw {{x}}, or a command that won't paste), and
  // a dash in English breaks house style. Missing keys only warn: they fall back
  // to English, so new English strings can land before every language catches up.
  if (dashes.length > 0) {
    console.log(`✗ ${dashes.length} English value(s) use an em-dash or en-dash (house style is none):`)
    for (const key of dashes) console.log(`    - ${key}`)
  }
  if (interpolationCount > 0 || protectedCount > 0 || dashes.length > 0) {
    if (interpolationCount > 0) {
      console.log(`✗ ${interpolationCount} broken interpolation variable(s): these break rendering.`)
    }
    if (protectedCount > 0) {
      console.log(`✗ ${protectedCount} translation(s) changed a command, flag or name that has to stay verbatim.`)
    }
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
}

if (import.meta.main) main()
