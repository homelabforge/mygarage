import { afterEach, describe, it, expect, vi } from 'vitest'
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'
import {
  assertOnlyChanged,
  buildChunks,
  exportAll,
  mergeAll,
  mergeChunk,
  type Chunk,
  type ChunkOutput,
  type FillRoots,
} from '../../scripts/i18n-fill'
import { flattenKeys, getNestedValue, hash8 } from '../../scripts/translation-utils'

const EN: Record<string, string> = {
  title: 'My Garage',
  saved: 'Saved {{count, number}} rows',
  restore: 'Run pg_restore --clean -d <dbname> now',
  suffix: ' / month',
  brand: 'Tesla Model 3 Long Range',
  days: '{{count}} days',
  days_one: '{{count}} day',
  days_other: '{{count}} days',
}
const enKeys = Object.keys(EN)
const enValues = new Map<string, unknown>(Object.entries(EN))
const RUN = 'run00001'
const flat = (d: Record<string, unknown>): Record<string, unknown> =>
  Object.fromEntries(flattenKeys(d).map((k) => [k, getNestedValue(d, k)]))

const chunkFor = (lang: string, data: Record<string, unknown>, records: Record<string, string> = {}): Chunk => {
  const chunks = buildChunks(lang, 'common', enKeys, enValues, data, records, 400, RUN)
  expect(chunks).toHaveLength(1)
  return chunks[0]
}
const merge = (chunk: Chunk, out: ChunkOutput, data: Record<string, unknown>, records: Record<string, string> = {}) =>
  mergeChunk(chunk, out, EN, data, records)

// German has a translation for `title` already and nothing else.
const DE_DATA = { title: 'Meine Garage' }
const deChunk = chunkFor('de', DE_DATA)
const goodDe = {
  saved: '{{count, number}} Zeilen gespeichert',
  restore: 'Führe jetzt pg_restore --clean -d <dbname> aus',
  suffix: ' / Monat',
  days: '{{count}} Tage',
  days_one: '{{count}} Tag',
  days_other: '{{count}} Tage',
}
const ok = (entries: ChunkOutput['entries'], chunk = deChunk): ChunkOutput => ({ chunkId: chunk.chunkId, entries })
const reasons = (r: ReturnType<typeof merge>) => Object.fromEntries(r.report.rejected.map((x) => [x.key, x.reason]))

describe('i18n-fill export', () => {
  it('exports only missing keys and copies of English, never an existing translation', () => {
    const keys = deChunk.entries.map((e) => e.key)
    expect(keys).not.toContain('title')
    expect(keys).toEqual(['saved', 'restore', 'suffix', 'brand', 'days', 'days_one', 'days_other'])
  })

  it('carries English hash, placeholders and protected spans per entry', () => {
    const e = deChunk.entries.find((x) => x.key === 'restore')!
    expect(e.enHash).toBe(hash8(EN.restore))
    expect(e.protected).toContain('<dbname>')
    expect(e.protected).toContain('--clean')
    expect(deChunk.entries.find((x) => x.key === 'saved')!.placeholders).toEqual(['{{count, number}}'])
  })

  it("exports pl's whole plural set with the language's categories", () => {
    const pl = chunkFor('pl', {})
    expect(pl.entries.filter((e) => e.plural).map((e) => e.key)).toEqual(['days_one', 'days_few', 'days_many', 'days_other'])
  })

  it('skips an approved identical value on the next export', () => {
    const data = { ...DE_DATA, brand: EN.brand }
    const rec = { 'common:brand': `${hash8(EN.brand)}:=` }
    expect(chunkFor('de', data, rec).entries.map((e) => e.key)).not.toContain('brand')
  })

  it('keeps a plural set in one chunk when chunks split', () => {
    const chunks = buildChunks('pl', 'common', enKeys, enValues, {}, {}, 3, RUN)
    const where = (k: string) => chunks.findIndex((c) => c.entries.some((e) => e.key === k))
    expect(new Set(['days_one', 'days_few', 'days_many', 'days_other'].map(where)).size).toBe(1)
  })
})

describe('i18n-fill merge: accepts', () => {
  it('writes accepted values, records them as drafts, and keeps the existing translation', () => {
    const r = merge(deChunk, ok({ ...goodDe, brand: { same: 'model name' } }), DE_DATA)
    expect(r.report.rejected).toEqual([])
    expect(flat(r.data)).toMatchObject({ title: 'Meine Garage', saved: goodDe.saved, brand: EN.brand })
    expect(r.records['common:saved']).toBe(`${hash8(EN.saved)}:${hash8(goodDe.saved)}:d`)
    expect(r.records['common:brand']).toBe(`${hash8(EN.brand)}:=:d`)
    expect(r.report.same).toEqual([{ key: 'brand', reason: 'model name' }])
  })

  it('writes in English key order', () => {
    const r = merge(deChunk, ok(goodDe), DE_DATA)
    expect(Object.keys(r.data)).toEqual(['title', 'saved', 'restore', 'suffix', 'days', 'days_one', 'days_other'])
  })
})

describe('i18n-fill merge: refusals', () => {
  it('refuses the whole output for a wrong or missing chunkId', () => {
    expect(() => merge(deChunk, { chunkId: 'fr-common-0', entries: goodDe }, DE_DATA)).toThrow(/chunkId/)
    expect(() => merge(deChunk, { entries: goodDe } as unknown as ChunkOutput, DE_DATA)).toThrow(/chunkId/)
  })

  it('refuses a key outside the chunk, including an existing translation', () => {
    const r = merge(deChunk, ok({ ...goodDe, title: 'Garage', 'nope.key': 'x' }), DE_DATA)
    expect(reasons(r)).toMatchObject({ title: 'not-writable', 'nope.key': 'not-writable' })
    expect(flat(r.data).title).toBe('Meine Garage')
  })

  it('refuses an entry whose English changed since export', () => {
    const moved = { ...EN, saved: 'Stored {{count, number}} rows' }
    const r = mergeChunk(deChunk, ok(goodDe), moved, DE_DATA, {})
    expect(reasons(r).saved).toBe('english-changed')
  })

  it('refuses broken placeholders, formatter included', () => {
    const r = merge(deChunk, ok({ ...goodDe, saved: '{{count}} Zeilen gespeichert' }), DE_DATA)
    expect(reasons(r).saved).toMatch(/^interpolation: missing \{\{count, number\}\}/)
  })

  it('refuses an altered command, flag or token', () => {
    const r = merge(deChunk, ok({ ...goodDe, restore: 'Führe pg_restore –clean -d <dbname> aus' }), DE_DATA)
    expect(reasons(r).restore).toMatch(/^protected/)
  })

  it('refuses changed edge whitespace', () => {
    const r = merge(deChunk, ok({ ...goodDe, suffix: '/ Monat' }), DE_DATA)
    expect(reasons(r).suffix).toBe('whitespace')
  })

  it('refuses $t( nesting, non-strings, empties and unapproved copies', () => {
    const r = merge(deChunk, ok({ ...goodDe, saved: '$t(x) {{count, number}}', restore: 42 as unknown as string, suffix: '', brand: EN.brand }), DE_DATA)
    expect(reasons(r).saved).toMatch(/nesting \$t\(/)
    expect(reasons(r)).toMatchObject({ restore: 'not-a-string', suffix: 'empty', brand: 'copy' })
  })

  it('refuses a same with no reason', () => {
    const r = merge(deChunk, ok({ ...goodDe, brand: { same: '' } }), DE_DATA)
    expect(reasons(r).brand).toBe('same-without-reason')
  })

  it('refuses the wrong Cyrillic script', () => {
    const uk = chunkFor('uk', {})
    const r = merge(uk, ok({ title: 'Мой гараж ы' }, uk), {})
    expect(reasons(r).title).toBe('script')
  })

  it('reports keys the agent never returned', () => {
    const r = merge(deChunk, ok({ saved: goodDe.saved }), DE_DATA)
    expect(reasons(r).restore).toBe('not-returned')
  })

  it('rejects a plural set as a whole when one member fails', () => {
    const pl = chunkFor('pl', {})
    const out = ok({ days: '{{count}} dni', days_one: '{{count}} dzień', days_few: '{{count}} dni', days_other: '{{count}} dni' }, pl)
    const r = merge(pl, out, {})
    expect(reasons(r).days_many).toBe('not-returned')
    expect(reasons(r).days_one).toBe('plural-set')
    expect(flat(r.data).days_one).toBeUndefined()
    expect(flat(r.data).days).toBe('{{count}} dni')
  })
})

describe('i18n-fill merge: existing plural members', () => {
  it('keeps a translated member and fills only the missing ones', () => {
    const data = { days_one: '{{count}} dzień', days_other: '{{count}} dni' }
    const pl = chunkFor('pl', data)
    expect(pl.entries.filter((e) => e.plural).map((e) => e.key)).toEqual(['days_few', 'days_many'])
    expect(pl.entries.find((e) => e.key === 'days_few')!.plural!.existing).toEqual({ one: '{{count}} dzień', other: '{{count}} dni' })
    const r = merge(pl, ok({ days_few: '{{count}} dni', days_many: '{{count}} dni', days: '{{count}} dni' }, pl), data)
    expect(r.report.rejected.filter((x) => x.key.startsWith('days'))).toEqual([])
    expect(flat(r.data)).toMatchObject({ days_one: '{{count}} dzień', days_few: '{{count}} dni', days_many: '{{count}} dni' })
  })

  it('rewrites a member that is a copy of English', () => {
    const data = { days_one: EN.days_one, days_other: '{{count}} dni' }
    const pl = chunkFor('pl', data)
    expect(pl.entries.filter((e) => e.plural).map((e) => e.key)).toEqual(['days_one', 'days_few', 'days_many'])
  })
})

describe('i18n-fill merge: the whole-file invariant', () => {
  it('throws when anything it does not own changes, disappears or appears', () => {
    const before = { a: 'x', n: { b: 'y' } }
    expect(() => assertOnlyChanged(before, { a: 'x2', n: { b: 'y' } }, new Set())).toThrow(/change a/)
    expect(() => assertOnlyChanged(before, { a: 'x' }, new Set())).toThrow(/change n\.b/)
    expect(() => assertOnlyChanged(before, { ...before, c: 'z' }, new Set())).toThrow(/add c/)
    expect(() => assertOnlyChanged(before, { a: 'x2', n: { b: 'y' }, c: 'z' }, new Set(['a', 'c']))).not.toThrow()
  })
})

describe('i18n-fill merge: the locale moved since export', () => {
  it('keeps a translation someone added after export', () => {
    const now = { ...DE_DATA, saved: '{{count, number}} Zeilen von Hand' }
    const r = merge(deChunk, ok(goodDe), now)
    expect(reasons(r).saved).toBe('changed-since-export')
    expect(flat(r.data).saved).toBe(now.saved)
    expect(r.records['common:saved']).toBeUndefined()
    expect(flat(r.data).restore).toBe(goodDe.restore)
  })

  it('keeps an English copy someone approved after export', () => {
    const now = { ...DE_DATA, brand: EN.brand }
    const rec = { 'common:brand': `${hash8(EN.brand)}:=` }
    const r = merge(deChunk, ok({ ...goodDe, brand: 'Tesla Modell 3' }), now, rec)
    expect(reasons(r).brand).toBe('changed-since-export')
    expect(flat(r.data).brand).toBe(EN.brand)
    expect(r.records['common:brand']).toBe(rec['common:brand'])
  })

  it('still fills a key that became a plain English copy after export', () => {
    const r = merge(deChunk, ok(goodDe), { ...DE_DATA, saved: EN.saved })
    expect(reasons(r).saved).toBeUndefined()
    expect(flat(r.data).saved).toBe(goodDe.saved)
  })

  it('rejects a plural set whose translated sibling disappeared', () => {
    const data = { days_one: '{{count}} dzień', days_other: '{{count}} dni' }
    const pl = chunkFor('pl', data)
    const r = merge(pl, ok({ days_few: '{{count}} dni', days_many: '{{count}} dni', days: '{{count}} dni' }, pl), { days_one: data.days_one })
    expect(reasons(r)).toMatchObject({ days_few: 'changed-since-export', days_many: 'changed-since-export' })
    expect(flat(r.data).days_few).toBeUndefined()
    expect(flat(r.data).days_many).toBeUndefined()
    expect(flat(r.data).days).toBe('{{count}} dni')
  })

  it('rejects a plural set whose translated _zero disappeared', () => {
    const en = { n_zero: 'No rows', n_one: '{{count}} row', n_other: '{{count}} rows' }
    const ev = new Map<string, unknown>(Object.entries(en))
    const data = { n_zero: 'Keine Zeilen' }
    const [chunk] = buildChunks('de', 'common', Object.keys(en), ev, data, {}, 400, RUN)
    expect(chunk.entries[0].plural?.existing).toEqual({ zero: 'Keine Zeilen' })
    const out = { chunkId: chunk.chunkId, entries: { n_one: '{{count}} Zeile', n_other: '{{count}} Zeilen' } }
    const r = mergeChunk(chunk, out, en, {}, {})
    expect(Object.fromEntries(r.report.rejected.map((x) => [x.key, x.reason]))).toMatchObject({
      n_one: 'changed-since-export',
      n_other: 'changed-since-export',
    })
  })

  it('rejects a plural set whose translated sibling changed', () => {
    const data = { days_one: '{{count}} dzień', days_other: '{{count}} dni' }
    const pl = chunkFor('pl', data)
    const r = merge(pl, ok({ days_few: '{{count}} dni', days_many: '{{count}} dni' }, pl), { ...data, days_other: '{{count}} dnia' })
    expect(reasons(r)).toMatchObject({ days_few: 'changed-since-export', days_many: 'changed-since-export' })
    expect(flat(r.data).days_few).toBeUndefined()
  })

  it('rejects the whole plural set when one member got translated after export', () => {
    const pl = chunkFor('pl', {})
    const out = ok({ days_one: '{{count}} dzień', days_few: '{{count}} dni', days_many: '{{count}} dni', days_other: '{{count}} dni' }, pl)
    const r = merge(pl, out, { days_one: '{{count}} dzionek' })
    expect(reasons(r)).toMatchObject({ days_one: 'changed-since-export', days_few: 'changed-since-export', days_other: 'changed-since-export' })
    expect(flat(r.data).days_one).toBe('{{count}} dzionek')
    expect(flat(r.data).days_few).toBeUndefined()
  })
})

describe('i18n-fill: outputs are bound to their export', () => {
  it("refuses an earlier export's output for a re-export's chunk with the same lang, ns and index", () => {
    const old = buildChunks('de', 'common', enKeys, enValues, DE_DATA, {}, 400, 'old00001')[0]
    const fresh = buildChunks('de', 'common', enKeys, enValues, DE_DATA, {}, 400, 'new00002')[0]
    expect(fresh.chunkId).not.toBe(old.chunkId)
    expect(fresh.runId).toBe('new00002')
    expect(() => merge(fresh, ok(goodDe, old), DE_DATA)).toThrow(/chunkId/)
  })
})

// A throwaway en / locales / sources tree plus a fill dir, so export and merge run end to end.
const tmpDirs: string[] = []
afterEach(() => {
  for (const d of tmpDirs.splice(0)) rmSync(d, { recursive: true, force: true })
  vi.restoreAllMocks()
})
const fixture = (): { roots: FillRoots; dir: string; localePath: string; sourcesPath: string } => {
  vi.spyOn(console, 'log').mockImplementation(() => {})
  const base = mkdtempSync(join(tmpdir(), 'mygarage-i18n-fill-'))
  tmpDirs.push(base)
  const roots: FillRoots = { enDir: join(base, 'en'), localesDir: join(base, 'locales'), sourcesDir: join(base, 'sources') }
  for (const d of [roots.enDir, join(roots.localesDir, 'de'), roots.sourcesDir, join(base, 'fill')]) mkdirSync(d, { recursive: true })
  writeFileSync(join(roots.enDir, 'common.json'), JSON.stringify(EN, null, 2) + '\n')
  const localePath = join(roots.localesDir, 'de', 'common.json')
  writeFileSync(localePath, JSON.stringify(DE_DATA, null, 2) + '\n')
  return { roots, dir: join(base, 'fill'), localePath, sourcesPath: join(roots.sourcesDir, 'de.json') }
}
const writeOut = (dir: string, chunkId: string, body: unknown): void =>
  writeFileSync(join(dir, `${chunkId}.out.json`), typeof body === 'string' ? body : JSON.stringify(body))
const chunkFile = (dir: string, chunkId: string): Chunk => JSON.parse(readFileSync(join(dir, `${chunkId}.chunk.json`), 'utf-8')) as Chunk
const pick = (chunk: Chunk): ChunkOutput['entries'] =>
  Object.fromEntries(chunk.entries.map((e) => [e.key, (goodDe as Record<string, string>)[e.key] ?? { same: 'model name' }]))

describe('i18n-fill export and merge on disk', () => {
  it("export refuses a directory holding an earlier run's files and leaves them alone", () => {
    const { roots, dir } = fixture()
    writeOut(dir, 'de-common-0', { chunkId: 'de-common-0', entries: {} })
    expect(() => exportAll(dir, ['de'], 400, roots)).toThrow(/earlier/)
    expect(readdirSync(dir)).toEqual(['de-common-0.out.json'])
  })

  it("merge refuses an earlier run's output dropped into a re-export's dir, and writes nothing", () => {
    const { roots, dir, localePath, sourcesPath } = fixture()
    const [old] = exportAll(dir, ['de'], 400, roots)
    const oldOut = { chunkId: old.chunkId, entries: pick(old) }
    rmSync(dir, { recursive: true })
    mkdirSync(dir)
    const [fresh] = exportAll(dir, ['de'], 400, roots)
    writeOut(dir, fresh.chunkId, oldOut)
    expect(() => mergeAll(dir, roots)).toThrow(/chunkId/)
    expect(JSON.parse(readFileSync(localePath, 'utf-8'))).toEqual(DE_DATA)
    expect(existsSync(sourcesPath)).toBe(false)
  })

  it("merge refuses a dir mixing two exports' chunks, and writes nothing", () => {
    const { roots, dir, localePath, sourcesPath } = fixture()
    const [old] = exportAll(dir, ['de'], 400, roots)
    const oldChunk = readFileSync(join(dir, `${old.chunkId}.chunk.json`), 'utf-8')
    rmSync(dir, { recursive: true })
    mkdirSync(dir)
    const [fresh] = exportAll(dir, ['de'], 400, roots)
    writeFileSync(join(dir, `${old.chunkId}.chunk.json`), oldChunk)
    for (const c of [old, fresh]) writeOut(dir, c.chunkId, { chunkId: c.chunkId, entries: pick(c) })
    expect(() => mergeAll(dir, roots)).toThrow(/mixes runs/)
    expect(JSON.parse(readFileSync(localePath, 'utf-8'))).toEqual(DE_DATA)
    expect(existsSync(sourcesPath)).toBe(false)
  })

  it('a malformed later output leaves no writes at all', () => {
    const { roots, dir, localePath, sourcesPath } = fixture()
    const chunks = exportAll(dir, ['de'], 3, roots)
    expect(chunks.length).toBeGreaterThanOrEqual(2)
    writeOut(dir, chunks[0].chunkId, { chunkId: chunks[0].chunkId, entries: pick(chunks[0]) })
    writeOut(dir, chunks[1].chunkId, '{ "chunkId": "oops", ')
    expect(() => mergeAll(dir, roots)).toThrow(chunks[1].chunkId)
    expect(JSON.parse(readFileSync(localePath, 'utf-8'))).toEqual(DE_DATA)
    expect(existsSync(sourcesPath)).toBe(false)
  })

  it('a later output with the wrong shape leaves no writes at all', () => {
    const { roots, dir, localePath, sourcesPath } = fixture()
    const chunks = exportAll(dir, ['de'], 3, roots)
    writeOut(dir, chunks[0].chunkId, { chunkId: chunks[0].chunkId, entries: pick(chunks[0]) })
    writeOut(dir, chunks[1].chunkId, { chunkId: chunks[1].chunkId, entries: 'not an object' })
    expect(() => mergeAll(dir, roots)).toThrow(/entries/)
    expect(JSON.parse(readFileSync(localePath, 'utf-8'))).toEqual(DE_DATA)
    expect(existsSync(sourcesPath)).toBe(false)
  })

  it('writes every accepted value together with its draft record', () => {
    const { roots, dir, localePath, sourcesPath } = fixture()
    const chunks = exportAll(dir, ['de'], 3, roots)
    for (const c of chunks) writeOut(dir, c.chunkId, { chunkId: c.chunkId, entries: pick(c) })
    const reports = mergeAll(dir, roots)
    expect(reports.every((r) => r.rejected.length === 0)).toBe(true)
    const data = JSON.parse(readFileSync(localePath, 'utf-8')) as Record<string, unknown>
    const records = JSON.parse(readFileSync(sourcesPath, 'utf-8')) as Record<string, string>
    const written = chunks.flatMap((c) => c.entries.map((e) => e.key))
    expect(written.length).toBeGreaterThan(0)
    for (const key of written) {
      expect(records[`common:${key}`]).toMatch(/:d$/)
      expect(getNestedValue(data, key)).toBeDefined()
    }
    expect(data.title).toBe('Meine Garage')
    expect(chunkFile(dir, chunks[0].chunkId).runId).toBe(chunks[0].runId)
  })
})
