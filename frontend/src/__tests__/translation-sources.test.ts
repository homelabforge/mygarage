import { describe, it, expect } from 'vitest'
import {
  acceptRecords,
  compareNamespace,
  hash8,
  pruneRecords,
  sourceState,
  type AcceptEntry,
} from '../../scripts/translation-utils'

// One key's life: English v1, a German translation, then edits on either side.
const EN1 = 'Save the visit'
const EN2 = 'Save this visit'
const DE1 = 'Besuch speichern'
const DE2 = 'Diesen Besuch speichern'

const entry = (value: unknown, enBase: unknown = EN1, nsKey = 'common:save'): AcceptEntry => ({ nsKey, enBase, value })
const accept = (records: Record<string, string>, entries: AcceptEntry[], mode: 'bulk' | 'key' = 'key') =>
  acceptRecords(records, entries, mode)

describe('translation sources: states', () => {
  it('reads current right after an accept', () => {
    const rec = accept({}, [entry(DE1)])
    expect(sourceState(rec['common:save'], EN1, DE1)).toBe('current')
  })

  it('goes stale when English changes and the translation does not', () => {
    const rec = accept({}, [entry(DE1)])
    expect(sourceState(rec['common:save'], EN2, DE1)).toBe('stale')
  })

  it('goes unrecorded, not current, when the translation changes', () => {
    const rec = accept({}, [entry(DE1)])
    expect(sourceState(rec['common:save'], EN1, DE2)).toBe('unrecorded')
  })

  it('stays unrecorded when a contributor edit is followed by an English edit before any stamp', () => {
    const rec = accept({}, [entry(DE1)])
    // Contributor retranslates against EN1, then English moves to EN2, nobody stamps.
    expect(sourceState(rec['common:save'], EN2, DE2)).toBe('unrecorded')
  })

  it('reads unrecorded with no record at all', () => {
    expect(sourceState(undefined, EN1, DE1)).toBe('unrecorded')
  })
})

describe('translation sources: accepting', () => {
  // The case R1-H1 and F-1 were about: the PR translated against EN1, main has
  // EN2 by the time the maintainer accepts. Hashing the merge-base English
  // keeps the key stale instead of certifying it against EN2.
  it('records the base English, so a key English moved past reads stale at once', () => {
    const rec = accept({}, [entry(DE2, EN1)])
    expect(sourceState(rec['common:save'], EN2, DE2)).toBe('stale')
  })

  it('bulk accept records unrecorded keys only, leaving stale keys stale and skipping English copies', () => {
    const start = accept({}, [entry(DE1, EN1, 'common:a')])
    const rec = accept(
      start,
      [
        entry(DE1, EN2, 'common:a'), // stale: record says EN1, English is EN2 now
        entry(DE1, EN1, 'common:b'), // unrecorded
        entry(EN1, EN1, 'common:c'), // a copy of English
      ],
      'bulk',
    )
    expect(rec['common:a']).toBe(start['common:a'])
    expect(sourceState(rec['common:b'], EN1, DE1)).toBe('current')
    expect(rec['common:c']).toBeUndefined()
  })

  it("writes '=' for a value identical to English on a per-key accept", () => {
    const rec = accept({}, [entry(EN1)])
    expect(rec['common:save']).toBe(`${hash8(EN1)}:=`)
    expect(sourceState(rec['common:save'], EN1, EN1)).toBe('current')
  })

  it("lets '=' go stale on an English edit", () => {
    const rec = accept({}, [entry(EN1)])
    expect(sourceState(rec['common:save'], EN2, EN1)).toBe('stale')
  })

  it('per-key accept touches exactly that key', () => {
    const start = accept({}, [entry(DE1, EN1, 'common:a'), entry(DE1, EN1, 'common:b')])
    const rec = accept(start, [entry(DE2, EN2, 'common:a')])
    expect(sourceState(rec['common:a'], EN2, DE2)).toBe('current')
    expect(rec['common:b']).toBe(start['common:b'])
  })

  it('reads a draft as draft until someone accepts it', () => {
    const draft = { 'common:save': `${hash8(EN1)}:${hash8(DE1)}:d` }
    expect(sourceState(draft['common:save'], EN1, DE1)).toBe('draft')
    const rec = accept(draft, [entry(DE1)])
    expect(rec['common:save']).toBe(`${hash8(EN1)}:${hash8(DE1)}`)
    expect(sourceState(rec['common:save'], EN1, DE1)).toBe('current')
  })

  it("bulk accept leaves drafts alone (they're recorded, not unrecorded)", () => {
    const draft = { 'common:save': `${hash8(EN1)}:${hash8(DE1)}:d` }
    expect(accept(draft, [entry(DE1)], 'bulk')).toEqual(draft)
  })
})

describe('translation sources: pruning and coverage', () => {
  it('drops records for keys that no longer exist, and nothing else', () => {
    const rec = { 'common:a': 'aaaaaaaa:bbbbbbbb', 'common:gone': 'cccccccc:dddddddd' }
    expect(pruneRecords(rec, new Set(['common:a']))).toEqual({ 'common:a': 'aaaaaaaa:bbbbbbbb' })
  })

  it('counts an approved identical value as translated, and an unapproved one as not', () => {
    const en = new Map<string, unknown>([['brand', 'Tesla Model 3 Long Range']])
    const data = { brand: 'Tesla Model 3 Long Range' }
    expect(compareNamespace('de', 'common', ['brand'], en, data).translated).toBe(0)
    const records = { 'common:brand': `${hash8('Tesla Model 3 Long Range')}:=` }
    expect(compareNamespace('de', 'common', ['brand'], en, data, records).translated).toBe(1)
  })
})
