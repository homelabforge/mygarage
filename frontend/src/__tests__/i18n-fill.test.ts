import { describe, it, expect } from 'vitest'
import { assertOnlyChanged, buildChunks, mergeChunk, type Chunk, type ChunkOutput } from '../../scripts/i18n-fill'
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
const flat = (d: Record<string, unknown>): Record<string, unknown> =>
  Object.fromEntries(flattenKeys(d).map((k) => [k, getNestedValue(d, k)]))

const chunkFor = (lang: string, data: Record<string, unknown>, records: Record<string, string> = {}): Chunk => {
  const chunks = buildChunks(lang, 'common', enKeys, enValues, data, records, 400)
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
    const chunks = buildChunks('pl', 'common', enKeys, enValues, {}, {}, 3)
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
    expect(reasons(r).saved).toMatch(/^placeholders/)
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
    expect(reasons(r)).toMatchObject({ saved: 'nesting', restore: 'not-a-string', suffix: 'empty', brand: 'copy' })
  })

  it('refuses a same with no reason', () => {
    const r = merge(deChunk, ok({ ...goodDe, brand: { same: '' } }), DE_DATA)
    expect(reasons(r).brand).toBe('same-without-reason')
  })

  it('refuses the wrong Cyrillic script', () => {
    const uk = chunkFor('uk', {})
    const r = merge(uk, ok({ title: 'Мой гараж ы' }, uk), {})
    expect(reasons(r).title).toBe('wrong-script')
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
