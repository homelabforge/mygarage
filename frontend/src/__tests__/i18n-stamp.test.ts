import { afterEach, describe, expect, it } from 'vitest'
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import { dirname, join, resolve } from 'path'
import { spawnSync, type SpawnSyncReturns } from 'child_process'
import { hash8, sourceState } from '../../scripts/translation-utils'

// The stamp CLI hardcodes its paths off its own location, so each test copies
// it into a throwaway git repo with the same layout and runs it there.
const SCRIPTS = resolve(import.meta.dirname, '../../scripts')
const roots: string[] = []

// keep the host's git env (GIT_DIR and friends) from pointing at the real repo
const gitEnv = (): NodeJS.ProcessEnv =>
  Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.startsWith('GIT_')))

interface Fixture {
  root: string
  write: (rel: string, data: unknown) => void
  writeRecords: (data: Record<string, string>) => void
  read: (rel: string) => Record<string, string>
  raw: (rel: string) => string | null
  git: (...args: string[]) => string
  commit: (msg: string) => string
  stamp: (...args: string[]) => SpawnSyncReturns<string>
}

function fixture(): Fixture {
  const root = mkdtempSync(join(tmpdir(), 'i18n-stamp-'))
  roots.push(root)
  mkdirSync(join(root, 'frontend', 'scripts', 'translation-sources'), { recursive: true })
  for (const f of ['i18n-stamp.ts', 'translation-utils.ts']) copyFileSync(join(SCRIPTS, f), join(root, 'frontend', 'scripts', f))

  const git = (...args: string[]): string => {
    const res = spawnSync('git', ['-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false', ...args], {
      cwd: root,
      encoding: 'utf-8',
      env: gitEnv(),
    })
    if (res.status !== 0) throw new Error(`git ${args.join(' ')}: ${res.stderr}`)
    return res.stdout.trim()
  }
  git('init', '-q', '-b', 'main')

  const write = (rel: string, data: unknown): void => {
    mkdirSync(dirname(join(root, rel)), { recursive: true })
    writeFileSync(join(root, rel), JSON.stringify(data, null, 2) + '\n')
  }
  // records go in compact, so any rewrite by the CLI changes the bytes
  const writeRecords = (data: Record<string, string>): void => writeFileSync(join(root, REC), JSON.stringify(data))
  const raw = (rel: string): string | null => (existsSync(join(root, rel)) ? readFileSync(join(root, rel), 'utf-8') : null)
  return {
    root,
    write,
    writeRecords,
    raw,
    read: (rel: string): Record<string, string> => JSON.parse(raw(rel) ?? '{}') as Record<string, string>,
    git,
    commit: (msg: string): string => {
      git('add', '-A')
      git('commit', '-q', '-m', msg)
      return git('rev-parse', 'HEAD')
    },
    stamp: (...args: string[]): SpawnSyncReturns<string> =>
      spawnSync('bun', [join(root, 'frontend', 'scripts', 'i18n-stamp.ts'), ...args], {
        cwd: join(root, 'frontend'),
        encoding: 'utf-8',
        env: gitEnv(),
      }),
  }
}

afterEach(() => {
  for (const r of roots.splice(0)) rmSync(r, { recursive: true, force: true })
})

const EN = 'frontend/src/locales/en/common.json'
const DE = 'frontend/public/locales/de/common.json'
const DE_NAV = 'frontend/public/locales/de/nav.json'
const REC = 'frontend/scripts/translation-sources/de.json'

const OPEN_OLD = 'Open the garage'
const OPEN_NEW = 'Open your garage'
const CLOSE = 'Close the garage'
const DE_OPEN = 'Garage öffnen'
const DE_CLOSE = 'Garage schließen'

/**
 * The reviewer's checklist: `close` was translated long ago and never
 * recorded, the contributor branched at `base`, main then moved the English
 * of `open`, and the PR translates `open` against the old English.
 */
function prScenario(): { f: Fixture; base: string } {
  const f = fixture()
  f.write(EN, { open: OPEN_OLD, close: CLOSE })
  f.write('frontend/src/locales/en/nav.json', { home: 'Home' })
  f.write(DE, { close: DE_CLOSE })
  f.writeRecords({})
  const base = f.commit('base')
  f.write(EN, { open: OPEN_NEW, close: CLOSE })
  f.commit('main moves English')
  f.write(DE, { open: DE_OPEN, close: DE_CLOSE })
  return { f, base }
}

describe('i18n-stamp --accept <lang> (bulk)', () => {
  it('accepts only translations the PR changed, against the base English, and lists the rest', () => {
    const { f, base } = prScenario()
    const res = f.stamp('--accept', 'de', '--base', base)
    expect(res.status).toBe(0)
    const rec = f.read(REC)
    expect(rec['common:open']).toBe(`${hash8(OPEN_OLD)}:${hash8(DE_OPEN)}`)
    // English moved after the branch, so it reads stale, not current
    expect(sourceState(rec['common:open'], OPEN_NEW, DE_OPEN)).toBe('stale')
    expect(rec['common:close']).toBeUndefined()
    expect(res.stdout).toContain('common:close')
  })

  it('counts every key of a namespace file the base did not have as changed', () => {
    const { f, base } = prScenario()
    f.write(DE_NAV, { home: 'Startseite' })
    expect(f.stamp('--accept', 'de', '--base', base).status).toBe(0)
    expect(f.read(REC)['nav:home']).toBe(`${hash8('Home')}:${hash8('Startseite')}`)
  })
})

describe('i18n-stamp: a bad --base', () => {
  it('exits non-zero and leaves the records alone on an unknown ref (bulk)', () => {
    const { f } = prScenario()
    const before = f.raw(REC)
    const res = f.stamp('--accept', 'de', '--base', 'no-such-ref')
    expect(res.status).not.toBe(0)
    expect(res.stderr).toContain('no-such-ref is not a commit')
    expect(f.raw(REC)).toBe(before)
  })

  it('exits non-zero and leaves the records alone on an unknown ref (per key)', () => {
    const { f } = prScenario()
    const before = f.raw(REC)
    const res = f.stamp('--accept', 'de:common:open', '--base', 'no-such-ref')
    expect(res.status).not.toBe(0)
    expect(res.stderr).toContain('no-such-ref is not a commit')
    expect(f.raw(REC)).toBe(before)
  })

  it('exits non-zero when --base has no value', () => {
    const { f } = prScenario()
    const before = f.raw(REC)
    expect(f.stamp('--accept', 'de', '--base').status).not.toBe(0)
    expect(f.raw(REC)).toBe(before)
  })

  it('treats a git failure on a file that exists at the ref as an error, not as absent', () => {
    const { f, base } = prScenario()
    // drop the blob of the base's de/common.json, so git show fails on a path the tree has
    const blob = f.git('rev-parse', `${base}:${DE}`)
    rmSync(join(f.root, '.git', 'objects', blob.slice(0, 2), blob.slice(2)), { force: true })
    const before = f.raw(REC)
    expect(f.stamp('--accept', 'de', '--base', base).status).not.toBe(0)
    expect(f.raw(REC)).toBe(before)
  })
})

describe('i18n-stamp --list', () => {
  it('rejects an unknown state', () => {
    const { f } = prScenario()
    const res = f.stamp('--list', 'bogus', 'de')
    expect(res.status).toBe(1)
    expect(res.stderr).toContain('Usage')
  })

  it('rejects an unknown or missing language', () => {
    const { f } = prScenario()
    expect(f.stamp('--list', 'draft', 'xx').status).toBe(1)
    expect(f.stamp('--list', 'draft').status).toBe(1)
  })

  it('lists one state for a known language', () => {
    const { f } = prScenario()
    const res = f.stamp('--list', 'unrecorded', 'de')
    expect(res.status).toBe(0)
    expect(res.stdout.trim().split('\n').sort()).toEqual(['common:close', 'common:open'])
  })
})

describe('i18n-stamp --accept-drafts', () => {
  const draftScenario = (): Fixture => {
    const f = fixture()
    f.write(EN, { a: 'Alpha', b: 'Bravo', c: 'Charlie Model 3', d: 'Delta' })
    f.write(DE, { a: 'Alfa', b: 'Brabo', c: 'Charlie Model 3', d: 'Delte' })
    f.writeRecords({
      'common:a': `${hash8('Alpha')}:${hash8('Alfa')}:d`, // a current draft
      'common:b': `${hash8('Bravo old')}:${hash8('Brabo')}:d`, // a draft English moved past: stale
      'common:c': `${hash8('Charlie Model 3')}:=:d`, // a machine draft that kept English
    }) // d is unrecorded
    f.commit('drafts')
    return f
  }

  it('approves every current draft and leaves stale and unrecorded keys alone', () => {
    const f = draftScenario()
    const res = f.stamp('--accept-drafts', 'de')
    expect(res.status).toBe(0)
    expect(res.stdout).toContain('2')
    expect(f.read(REC)).toEqual({
      'common:a': `${hash8('Alpha')}:${hash8('Alfa')}`,
      'common:b': `${hash8('Bravo old')}:${hash8('Brabo')}:d`,
      'common:c': `${hash8('Charlie Model 3')}:=`,
    })
  })

  it('approves only the listed keys', () => {
    const f = draftScenario()
    expect(f.stamp('--accept-drafts', 'de', 'common:c').status).toBe(0)
    const rec = f.read(REC)
    expect(rec['common:a']).toBe(`${hash8('Alpha')}:${hash8('Alfa')}:d`)
    expect(rec['common:c']).toBe(`${hash8('Charlie Model 3')}:=`)
  })

  it('refuses a listed key that is not a draft and writes nothing', () => {
    const f = draftScenario()
    const before = f.raw(REC)
    for (const key of ['common:b', 'common:d', 'common:nope']) {
      const res = f.stamp('--accept-drafts', 'de', 'common:a', key)
      expect(res.status).toBe(1)
      expect(res.stderr).toContain(key)
    }
    expect(f.raw(REC)).toBe(before)
  })

  it('rejects an unknown language', () => {
    const f = draftScenario()
    expect(f.stamp('--accept-drafts', 'xx').status).toBe(1)
  })
})

describe('i18n-stamp --draft-stale', () => {
  // a current, b stale, c an approved copy of English, d unrecorded, e an old
  // "=" record whose value now equals the new English (reads stale too), g a
  // current draft, n a null value whose record matched old English (empty to
  // --list, so not stale)
  const staleScenario = (): Fixture => {
    const f = fixture()
    f.write(EN, { a: 'Alpha', b: 'Bravo', c: 'Charlie Model 3', d: 'Delta', e: 'Echo new', g: 'Golf', n: 'November' })
    f.write(DE, { a: 'Alfa', b: 'Brabo', c: 'Charlie Model 3', d: 'Delte', e: 'Echo new', g: 'Golfe', n: null })
    f.writeRecords({
      'common:a': `${hash8('Alpha')}:${hash8('Alfa')}`,
      'common:b': `${hash8('Bravo old')}:${hash8('Brabo')}`,
      'common:c': `${hash8('Charlie Model 3')}:=`,
      'common:e': `${hash8('Echo old')}:=`,
      'common:g': `${hash8('Golf')}:${hash8('Golfe')}:d`,
      'common:n': `${hash8('November old')}:${hash8(null)}`,
    })
    f.commit('stale')
    return f
  }
  const lines = (res: SpawnSyncReturns<string>): string[] => res.stdout.trim().split('\n').filter(Boolean).sort()

  it('re-dates every stale key as a draft and leaves the translations alone', () => {
    const f = staleScenario()
    const de = f.raw(DE)
    expect(lines(f.stamp('--list', 'stale', 'de'))).toEqual(['common:b', 'common:e'])
    const res = f.stamp('--draft-stale', 'de')
    expect(res.status).toBe(0)
    expect(res.stdout).toContain('2')
    expect(f.read(REC)['common:b']).toBe(`${hash8('Bravo')}:${hash8('Brabo')}:d`)
    expect(lines(f.stamp('--list', 'stale', 'de'))).toEqual([])
    // b and e joined g, the draft that was already there
    expect(lines(f.stamp('--list', 'draft', 'de'))).toEqual(['common:b', 'common:e', 'common:g'])
    expect(f.raw(DE)).toBe(de)
  })

  it('stamps an old "=" record whose value now equals English as a "=" draft', () => {
    const f = staleScenario()
    expect(f.stamp('--draft-stale', 'de', 'common:e').status).toBe(0)
    expect(f.read(REC)['common:e']).toBe(`${hash8('Echo new')}:=:d`)
    expect(f.read(REC)['common:b']).toBe(`${hash8('Bravo old')}:${hash8('Brabo')}`)
  })

  it('leaves current, approved and unrecorded keys alone', () => {
    const f = staleScenario()
    expect(f.stamp('--draft-stale', 'de').status).toBe(0)
    const rec = f.read(REC)
    expect(rec['common:a']).toBe(`${hash8('Alpha')}:${hash8('Alfa')}`)
    expect(rec['common:c']).toBe(`${hash8('Charlie Model 3')}:=`)
    expect(rec['common:d']).toBeUndefined()
    expect(rec['common:g']).toBe(`${hash8('Golf')}:${hash8('Golfe')}:d`)
    expect(rec['common:n']).toBe(`${hash8('November old')}:${hash8(null)}`)
  })

  it('refuses a listed key that is not stale, says why, and writes nothing', () => {
    const f = staleScenario()
    const before = f.raw(REC)
    for (const [key, reason] of [
      ['common:a', 'common:a: current, not stale'],
      ['common:d', 'common:d: unrecorded, not stale'],
      ['common:g', 'common:g: draft, not stale'],
      ['common:n', 'common:n: missing, not stale'],
      ['common:nope', 'common:nope: not a key de has'],
    ]) {
      const res = f.stamp('--draft-stale', 'de', 'common:b', key)
      expect(res.status).toBe(1)
      expect(res.stderr).toContain(reason)
      expect(res.stderr).not.toContain('unknown option')
    }
    expect(f.raw(REC)).toBe(before)
  })

  it('refuses --base, which only goes with --accept', () => {
    const f = staleScenario()
    const before = f.raw(REC)
    const res = f.stamp('--draft-stale', 'de', '--base', 'HEAD')
    expect(res.status).toBe(1)
    expect(res.stderr).toContain('--base only goes with --accept')
    expect(f.raw(REC)).toBe(before)
  })

  it("doesn't start tracking a language that has no record file", () => {
    const f = fixture()
    f.write(EN, { a: 'Alpha' })
    f.write(DE, { a: 'Alfa' })
    f.commit('untracked')
    for (const mode of ['--draft-stale', '--accept-drafts']) {
      const res = f.stamp(mode, 'de')
      expect(res.status).toBe(0)
      expect(f.raw(REC)).toBeNull()
    }
    // still untracked, so nothing reads unrecorded
    expect(f.stamp('--list', 'unrecorded', 'de').stdout.trim()).toBe('')
  })

  it('rejects an unknown language', () => {
    const f = staleScenario()
    const res = f.stamp('--draft-stale', 'xx')
    expect(res.status).toBe(1)
    expect(res.stderr).toContain('unknown language: xx')
  })
})
