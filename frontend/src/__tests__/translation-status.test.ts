import { describe, it, expect } from 'vitest'
import { mkdtempSync, readFileSync, statSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'
import { renderStatus, statusDrift, writeStatus } from '../../scripts/generate-translation-status'

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
