import { describe, it, expect } from 'vitest'
import { mkdtempSync, readFileSync, statSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'
import { renderStatus, statusDrift, writeStatus } from '../../scripts/generate-translation-status'
import {
  LOCALES_DIR,
  SOURCES_DIR,
  discoverLanguages,
  discoverNamespaces,
  expectedKeys,
  getNestedValue,
  hash8,
  loadEnglishData,
  loadJson,
} from '../../scripts/translation-utils'

describe('generate-translation-status --check', () => {
  const files = renderStatus()

  it('renders the badge and TRANSLATIONS.md', () => {
    expect(Object.keys(files).sort()).toEqual(['.github/badges/translations.json', 'TRANSLATIONS.md'])
    expect(files['TRANSLATIONS.md']).toContain('# Translation Status')
  })

  it('reports nothing once the files are written', () => {
    const root = mkdtempSync(join(tmpdir(), 'tstatus-'))
    writeStatus(root, files)
    expect(statusDrift(root, files)).toEqual([])
  })

  it('names a stale or missing file and leaves the disk alone', () => {
    const root = mkdtempSync(join(tmpdir(), 'tstatus-'))
    writeStatus(root, files)
    const md = join(root, 'TRANSLATIONS.md')
    writeFileSync(md, 'old\n')
    const before = statSync(md).mtimeMs
    expect(statusDrift(root, files)).toEqual(['TRANSLATIONS.md'])
    expect(readFileSync(md, 'utf-8')).toBe('old\n')
    expect(statSync(md).mtimeMs).toBe(before)
    expect(statusDrift(mkdtempSync(join(tmpdir(), 'tstatus-')), files)).toEqual([
      '.github/badges/translations.json',
      'TRANSLATIONS.md',
    ])
  })
})

describe('TRANSLATIONS.md drafts column', () => {
  // Machine drafts count as translated, so the percentage alone hides them.
  // Counted here straight from the record files, not through analyzeLocale, so
  // a draft the gate forgets to list (a kept English copy, say) shows up.
  it('shows each language its count of unreviewed machine drafts, kept English copies included', () => {
    const md = renderStatus()['TRANSLATIONS.md']
    expect(md).toContain('| | Language | Code | Progress | Keys | Drafts |')
    const namespaces = discoverNamespaces()
    const english = loadEnglishData(namespaces)
    let copies = 0
    for (const lang of discoverLanguages()) {
      const enByKey = new Map<string, unknown>()
      for (const ns of namespaces) {
        for (const { key, enValue } of expectedKeys(english.keysByNamespace.get(ns)!, english.valuesByNamespace.get(ns)!, lang)) {
          enByKey.set(`${ns}:${key}`, enValue)
        }
      }
      const records = JSON.parse(readFileSync(join(SOURCES_DIR, `${lang}.json`), 'utf-8')) as Record<string, string>
      const data = new Map(namespaces.map((ns) => [ns, loadJson(join(LOCALES_DIR, lang, `${ns}.json`))]))
      let drafts = 0
      for (const [nsKey, raw] of Object.entries(records)) {
        const [enH, trH, flag] = raw.split(':')
        if (flag !== 'd' || !enByKey.has(nsKey)) continue
        const [ns, key] = [nsKey.slice(0, nsKey.indexOf(':')), nsKey.slice(nsKey.indexOf(':') + 1)]
        const value = getNestedValue(data.get(ns)!, key)
        const en = enByKey.get(nsKey)
        if (enH !== hash8(en) || (trH === '=' ? value !== en : trH !== hash8(value))) continue
        drafts++
        if (trH === '=') copies++
      }
      const row = md.split('\n').find((l) => l.includes(`| \`${lang}\` |`))
      expect(row?.trim().endsWith(`| ${drafts} |`), lang).toBe(true)
    }
    // the kept copies are what the column used to miss
    expect(copies).toBeGreaterThan(0)
  })
})
