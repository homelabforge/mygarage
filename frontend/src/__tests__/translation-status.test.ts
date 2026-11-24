import { describe, it, expect } from 'vitest'
import { mkdtempSync, readFileSync, statSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'
import { renderStatus, statusDrift, writeStatus } from '../../scripts/generate-translation-status'
import { analyzeLocale, discoverLanguages, discoverNamespaces, loadEnglishData } from '../../scripts/translation-utils'

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
  it('shows each language its count of unreviewed machine drafts', () => {
    const md = renderStatus()['TRANSLATIONS.md']
    expect(md).toContain('| | Language | Code | Progress | Keys | Drafts |')
    const namespaces = discoverNamespaces()
    const english = loadEnglishData(namespaces)
    for (const lang of discoverLanguages()) {
      const drafts = analyzeLocale(lang, namespaces, english).issues.filter((i) => i.type === 'draft').length
      const row = md.split('\n').find((l) => l.includes(`| \`${lang}\` |`))
      expect(row?.trim().endsWith(`| ${drafts} |`)).toBe(true)
    }
  })
})
