#!/usr/bin/env bun
/**
 * Generate translation status badge JSON and TRANSLATIONS.md.
 *
 * Reads the canonical English keys and compares against each target
 * language, then writes:
 *   - .github/badges/translations.json  (shields.io endpoint badge)
 *   - TRANSLATIONS.md                    (detailed status page)
 *
 * Usage: bun run scripts/generate-translation-status.ts           write both
 *        bun run scripts/generate-translation-status.ts --check   exit 1 on drift, write nothing
 *
 * --check is a maintainer tool on purpose: it's not in CI or bin/ci-check, so a
 * translation PR never fails over generated files.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'fs'
import { dirname, join } from 'path'
import {
  LANGUAGE_FLAGS,
  LANGUAGE_NAMES,
  PROJECT_ROOT,
  analyzeLocale,
  discoverLanguages,
  discoverNamespaces,
  loadEnglishData,
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

export interface StatusFiles {
  /** Path relative to the project root, to file content. */
  [relPath: string]: string
}

const BADGE = join('.github', 'badges', 'translations.json')
const STATUS_MD = 'TRANSLATIONS.md'

/** Render the badge JSON and TRANSLATIONS.md in memory. */
export function renderStatus(): StatusFiles {
  const namespaces = discoverNamespaces()
  const languages = discoverLanguages()
  const english = loadEnglishData(namespaces)
  const { totalKeys } = english

  // Per-language stats, from the same comparison the gate uses.
  const stats: LanguageStats[] = languages.map(lang => {
    const report = analyzeLocale(lang, namespaces, english)
    const { translated, total } = report
    return {
      code: lang,
      name: LANGUAGE_NAMES[lang] ?? lang,
      flag: LANGUAGE_FLAGS[lang] ?? '🏳️',
      translated,
      total,
      percentage: total > 0 ? Math.round((translated / total) * 100) : 0,
      missing: report.issues.filter(i => i.type === 'missing').length,
      empty: report.issues.filter(i => i.type === 'empty').length,
    }
  }).sort((a, b) => {
    // Primary: completion descending. Secondary: language code ascending for
    // deterministic ordering when languages tie (avoids CI/local drift in
    // TRANSLATIONS.md when readdir() orders differ across filesystems).
    if (b.percentage !== a.percentage) return b.percentage - a.percentage
    return a.code.localeCompare(b.code)
  })

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

  const badgeJson = {
    schemaVersion: 1,
    label: 'Translations',
    message: `${overallPct}%`,
    color: badgeColor(overallPct),
  }

  // Generate TRANSLATIONS.md
  function progressBar(pct: number): string {
    const filled = Math.round(pct / 5)
    const remainder = 20 - filled
    return '█'.repeat(filled) + '░'.repeat(remainder)
  }

  const md = `# Translation Status

MyGarage supports multiple languages through community contributions.

## Overview

| | Language | Code | Progress | Keys |
|---|----------|------|----------|------|
| 🇺🇸 | English | \`en\` | \`${progressBar(100)}\` 100% | ${totalKeys}/${totalKeys} |
${stats.map(s =>
  `| ${s.flag} | ${s.name} | \`${s.code}\` | \`${progressBar(s.percentage)}\` ${s.percentage}% | ${s.translated}/${s.total} |`
).join('\n')}

**Overall: ${overallPct}%** average completion across ${languages.length} translated language${languages.length !== 1 ? 's' : ''}; English is the source (100%)

---

## Contributing

Want to add or improve a language? See [TRANSLATING.md](TRANSLATING.md).

---

## Contributors

Thank you to everyone who has contributed translations!

| Contributor | Languages |
|-------------|-----------|
| [Antonio (f0rZzZ)](https://github.com/f0rZzZ) | 🇵🇱 Polish, 🇷🇺 Russian, 🇺🇦 Ukrainian |
| [FabioCastilho](https://github.com/FabioCastilho) | 🇧🇷 Brazilian Portuguese |
| [Faizi2k](https://github.com/Faizi2k) | 🇲🇾 Malay |
| [Konstantin Grachev (grachevko)](https://github.com/grachevko) | 🇷🇺 Russian |
| [marcomatrella](https://github.com/marcomatrella) | 🇮🇹 Italian |
| [roondar](https://github.com/roondar) | 🇫🇷 French |
| [SCDT95](https://github.com/SCDT95) | 🇩🇪 German |
`

  return { [BADGE]: JSON.stringify(badgeJson, null, 2) + '\n', [STATUS_MD]: md }
}

/** Generated files whose content on disk differs from `files`. Reads only. */
export function statusDrift(root: string, files: StatusFiles): string[] {
  return Object.entries(files)
    .filter(([rel, content]) => {
      const path = join(root, rel)
      return !existsSync(path) || readFileSync(path, 'utf-8') !== content
    })
    .map(([rel]) => rel)
}

export function writeStatus(root: string, files: StatusFiles): void {
  for (const [rel, content] of Object.entries(files)) {
    mkdirSync(dirname(join(root, rel)), { recursive: true })
    writeFileSync(join(root, rel), content)
  }
}

function main(): void {
  const files = renderStatus()
  if (process.argv.includes('--check')) {
    const drift = statusDrift(PROJECT_ROOT, files)
    if (drift.length > 0) {
      console.log(`✗ Out of date: ${drift.join(', ')}. Run bun run generate:translation-status.`)
      process.exit(1)
    }
    console.log('✓ Translation status files are up to date.')
    return
  }
  writeStatus(PROJECT_ROOT, files)
  console.log(`Written: ${BADGE}, ${STATUS_MD}`)
}

if (import.meta.main) main()
