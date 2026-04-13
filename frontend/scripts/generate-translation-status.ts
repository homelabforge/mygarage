#!/usr/bin/env bun
/**
 * Generate translation status badge JSON and TRANSLATIONS.md.
 *
 * Reads the canonical English keys and compares against each target
 * language, then writes:
 *   - .github/badges/translations.json  (shields.io endpoint badge)
 *   - TRANSLATIONS.md                    (detailed status page)
 *
 * Usage: bun run scripts/generate-translation-status.ts
 */

import { existsSync, mkdirSync, writeFileSync } from 'fs'
import { join } from 'path'
import {
  LANGUAGE_FLAGS,
  LANGUAGE_NAMES,
  LOCALES_DIR,
  PROJECT_ROOT,
  discoverLanguages,
  discoverNamespaces,
  flattenKeys,
  getNestedValue,
  loadEnglishData,
  loadJson,
} from './translation-utils'

interface LanguageStats {
  code: string
  name: string
  flag: string
  translated: number
  total: number
  percentage: number
  missing: number
  empty: number
}

const namespaces = discoverNamespaces()
const languages = discoverLanguages()
const { totalKeys, keysByNamespace, valuesByNamespace } = loadEnglishData(namespaces)

// Calculate per-language stats
const stats: LanguageStats[] = languages.map(lang => {
  let translated = 0
  let missing = 0
  let empty = 0

  for (const ns of namespaces) {
    const enKeys = keysByNamespace.get(ns)!
    const enValues = valuesByNamespace.get(ns)!
    const langPath = join(LOCALES_DIR, lang, `${ns}.json`)

    if (!existsSync(langPath)) {
      missing += enKeys.length
      continue
    }

    const langData = loadJson(langPath)
    const langKeys = new Set(flattenKeys(langData))

    for (const key of enKeys) {
      if (!langKeys.has(key)) {
        missing++
      } else {
        const enVal = enValues.get(key)
        const langVal = getNestedValue(langData, key)
        if (langVal === '' || langVal === null) {
          empty++
        } else if (langVal !== enVal) {
          translated++
        }
      }
    }
  }

  const percentage = totalKeys > 0 ? Math.round((translated / totalKeys) * 100) : 0

  return {
    code: lang,
    name: LANGUAGE_NAMES[lang] ?? lang,
    flag: LANGUAGE_FLAGS[lang] ?? '🏳️',
    translated,
    total: totalKeys,
    percentage,
    missing,
    empty,
  }
}).sort((a, b) => b.percentage - a.percentage)

// Overall percentage (average across languages)
const overallPct = languages.length > 0
  ? Math.round(stats.reduce((sum, s) => sum + s.percentage, 0) / stats.length)
  : 100

function badgeColor(pct: number): string {
  if (pct >= 95) return 'brightgreen'
  if (pct >= 80) return 'green'
  if (pct >= 60) return 'yellowgreen'
  if (pct >= 40) return 'yellow'
  if (pct >= 20) return 'orange'
  return 'red'
}

// Write badge JSON
const badgeDir = join(PROJECT_ROOT, '.github', 'badges')
if (!existsSync(badgeDir)) mkdirSync(badgeDir, { recursive: true })

const badgeJson = {
  schemaVersion: 1,
  label: 'Translations',
  message: `${overallPct}%`,
  color: badgeColor(overallPct),
}
writeFileSync(join(badgeDir, 'translations.json'), JSON.stringify(badgeJson, null, 2) + '\n')

// Generate TRANSLATIONS.md
function progressBar(pct: number): string {
  const filled = Math.round(pct / 5)
  const remainder = 20 - filled
  return '█'.repeat(filled) + '░'.repeat(remainder)
}

const now = new Date().toISOString().split('T')[0]

const md = `# Translation Status

MyGarage supports multiple languages through community contributions. This page is automatically updated by CI.

> Last updated: ${now}

## Overview

| | Language | Code | Progress | Keys |
|---|----------|------|----------|------|
| 🇺🇸 | English | \`en\` | \`${progressBar(100)}\` 100% | ${totalKeys}/${totalKeys} |
${stats.map(s =>
  `| ${s.flag} | ${s.name} | \`${s.code}\` | \`${progressBar(s.percentage)}\` ${s.percentage}% | ${s.translated}/${s.total} |`
).join('\n')}

**Overall: ${overallPct}%** across ${languages.length} language${languages.length !== 1 ? 's' : ''}

---

## Contributing Translations

We welcome translation contributions! Here's how to help:

1. **Fork** the repository
2. Translation files are in \`frontend/public/locales/{language_code}/\`
3. English source files (the reference) are in \`frontend/src/locales/en/\`
4. Each namespace has its own JSON file: \`common.json\`, \`nav.json\`, \`settings.json\`, \`vehicles.json\`, \`forms.json\`, \`analytics.json\`
5. Copy the English file structure and translate the values (keep the keys the same)
6. Preserve \`{{variable}}\` interpolation placeholders exactly as they appear
7. Run \`bun run validate:translations\` to check your work
8. Submit a **Pull Request**

### Adding a New Language

1. Create a new directory under \`frontend/public/locales/\` with the [ISO 639-1 code](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes) (e.g., \`fr\` for French)
2. Copy all JSON files from \`frontend/src/locales/en/\` into your new directory
3. Translate the values
4. The language will be automatically detected and available in the app

---

## Contributors

Thank you to everyone who has contributed translations!

| Contributor | Languages |
|-------------|-----------|
| [Antonio (f0rZzZ)](https://github.com/f0rZzZ) | 🇵🇱 Polish, 🇷🇺 Russian, 🇺🇦 Ukrainian |
`

writeFileSync(join(PROJECT_ROOT, 'TRANSLATIONS.md'), md)

console.log(`Badge: ${overallPct}% (${badgeColor(overallPct)})`)
console.log(`Languages: ${stats.map(s => `${s.code}=${s.percentage}%`).join(', ')}`)
console.log(`Written: .github/badges/translations.json, TRANSLATIONS.md`)
