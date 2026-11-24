import { describe, it, expect } from 'vitest'
import { compareNamespace, deleteNestedKey, type LocaleIssueType } from '../../scripts/translation-utils'

const EN: Record<string, string> = {
  title: 'My Garage',
  days_one: '{{count}} day',
  days_other: '{{count}} days',
  saved: 'Saved {{count, number}} rows for {{name}}',
  vin: 'VIN',
}
const enKeys = Object.keys(EN)
const enValues = new Map<string, unknown>(Object.entries(EN))

const compare = (lang: string, data: Record<string, unknown>) =>
  compareNamespace(lang, 'common', enKeys, enValues, data)

const keysOf = (lang: string, data: Record<string, unknown>, type: LocaleIssueType): string[] =>
  compare(lang, data).issues.filter((i) => i.type === type).map((i) => i.key)

const full = {
  title: 'x',
  saved: 'x {{count, number}} {{name}}',
  vin: 'VIN',
}

describe('translation gate: plural sets follow the language', () => {
  it("doesn't call ru's _few and _many extras", () => {
    const ru = { ...full, days_one: '{{count}} день', days_few: '{{count}} дня', days_many: '{{count}} дней', days_other: '{{count}} дня' }
    expect(keysOf('ru', ru, 'extra')).toEqual([])
    expect(keysOf('ru', ru, 'missing')).toEqual([])
  })

  it('reports a pl set without _few and _many as missing', () => {
    const pl = { ...full, days_one: '{{count}} dzień', days_other: '{{count}} dni' }
    expect(keysOf('pl', pl, 'missing')).toEqual(['days_few', 'days_many'])
  })

  it("calls ms's _one an extra, since ms only reads _other", () => {
    const ms = { ...full, days_one: '{{count}} hari', days_other: '{{count}} hari' }
    expect(keysOf('ms', ms, 'extra')).toEqual(['days_one'])
    expect(keysOf('ms', ms, 'missing')).toEqual([])
  })

  it('counts the expanded set as the total', () => {
    expect(compare('pl', {}).total).toBe(3 + 4)
    expect(compare('de', {}).total).toBe(3 + 2)
  })

  it('still reports a key English dropped as an extra', () => {
    expect(keysOf('de', { ...full, gone: 'weg' }, 'extra')).toEqual(['gone'])
  })
})

describe('translation gate: placeholders', () => {
  it('fails a dropped formatted placeholder', () => {
    const de = { ...full, saved: 'Gespeichert für {{name}}', days_one: '{{count}} Tag', days_other: '{{count}} Tage' }
    expect(compare('de', de).issues.find((i) => i.type === 'interpolation')?.detail).toBe('missing {{count}}')
  })

  it('fails a placeholder English never passes', () => {
    const de = { ...full, title: 'Meine {{garage}}', days_one: '{{count}} Tag', days_other: '{{count}} Tage' }
    expect(compare('de', de).issues.find((i) => i.type === 'interpolation')?.detail).toBe('unknown {{garage}}')
  })

  it('accepts a format change on the same variable', () => {
    const de = { ...full, saved: '{{count}} Zeilen für {{name}}', days_one: '{{count}} Tag', days_other: '{{count}} Tage' }
    expect(keysOf('de', de, 'interpolation')).toEqual([])
  })
})

describe('translation gate: what counts as translated', () => {
  it("doesn't count a copy of English, but does count an invariant one", () => {
    const de = { title: 'My Garage', saved: 'x {{count, number}} {{name}}', vin: 'VIN', days_one: '{{count}} Tag', days_other: '{{count}} Tage' }
    // title is an English copy; vin is invariant.
    expect(compare('de', de).translated).toBe(4)
  })
})

describe('deleteNestedKey', () => {
  it('drops the key and any parent it leaves empty, nothing else', () => {
    const data: Record<string, unknown> = { a: { b: { c: 'x' } }, d: { e: 'y', f: 'z' } }
    expect(deleteNestedKey(data, 'a.b.c')).toBe(true)
    expect(deleteNestedKey(data, 'd.e')).toBe(true)
    expect(data).toEqual({ d: { f: 'z' } })
  })

  it('leaves the object alone for a key that is not there', () => {
    const data: Record<string, unknown> = { a: { b: 'x' } }
    expect(deleteNestedKey(data, 'a.c')).toBe(false)
    expect(deleteNestedKey(data, 'a.b.c')).toBe(false)
    expect(data).toEqual({ a: { b: 'x' } })
  })
})
