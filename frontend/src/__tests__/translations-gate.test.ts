import { describe, it, expect } from 'vitest'
import { createInstance } from 'i18next'
import {
  PROTECTED,
  compareNamespace,
  deleteNestedKey,
  englishDashes,
  discoverNamespaces,
  loadEnglishData,
  protectedSpans,
  sortToEnglish,
  type LocaleIssueType,
} from '../../scripts/translation-utils'

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

  it('calls a plural-looking key with no English base an extra', () => {
    expect(keysOf('ru', { ...full, gone_few: 'x' }, 'extra')).toEqual(['gone_few'])
  })

  it('takes a fully populated ms bundle to 100%', () => {
    const ms = { title: 'Garaj Saya', saved: 'Disimpan {{count, number}} baris untuk {{name}}', vin: 'VIN', days_other: '{{count}} hari' }
    const r = compare('ms', ms)
    expect(r.issues).toEqual([])
    expect(r.translated).toBe(r.total)
  })
})

describe('translation gate: placeholders', () => {
  it('fails a dropped formatted placeholder', () => {
    const de = { ...full, saved: 'Gespeichert für {{name}}', days_one: '{{count}} Tag', days_other: '{{count}} Tage' }
    expect(compare('de', de).issues.find((i) => i.type === 'interpolation')?.detail).toBe('missing {{count, number}}')
  })

  it('fails a placeholder English never passes', () => {
    const de = { ...full, title: 'Meine {{garage}}', days_one: '{{count}} Tag', days_other: '{{count}} Tage' }
    expect(compare('de', de).issues.find((i) => i.type === 'interpolation')?.detail).toBe('unknown {{garage}}')
  })

  // German renders 12.345 with the formatter and 12345 without, so a dropped
  // formatter is a real bug, not a style choice.
  it('fails a dropped formatter on the same variable', () => {
    const de = { ...full, saved: '{{count}} Zeilen für {{name}}', days_one: '{{count}} Tag', days_other: '{{count}} Tage' }
    expect(compare('de', de).issues.find((i) => i.type === 'interpolation')?.detail).toBe(
      'missing {{count, number}}; unknown {{count}}',
    )
  })

  it('ignores spacing inside a placeholder', () => {
    const de = { ...full, saved: '{{ count , number }} Zeilen für {{name}}', days_one: '{{count}} Tag', days_other: '{{count}} Tage' }
    expect(keysOf('de', de, 'interpolation')).toEqual([])
  })
})

describe('translation gate: wrong script', () => {
  const pl = { ...full, days_one: '{{count}} dzień', days_few: '{{count}} dni', days_many: '{{count}} dni', days_other: '{{count}} dni' }

  it('fails Cyrillic in a Latin-script language', () => {
    expect(keysOf('pl', { ...pl, title: '{{count}} запис(-ів)' }, 'script')).toEqual(['title'])
    expect(keysOf('de', { ...full, title: 'Meine Garaжe', days_one: 'x', days_other: 'x' }, 'script')).toEqual(['title'])
  })

  it('fails Russian-only letters in uk and Ukrainian-only letters in ru', () => {
    const uk = { ...full, title: 'Мой гараж ы', days_one: 'x', days_few: 'x', days_many: 'x', days_other: 'x' }
    const ru = { ...full, title: 'Мій гараж ї', days_one: 'x', days_few: 'x', days_many: 'x', days_other: 'x' }
    expect(keysOf('uk', uk, 'script')).toEqual(['title'])
    expect(keysOf('ru', ru, 'script')).toEqual(['title'])
  })

  it('passes clean text in each script', () => {
    expect(keysOf('pl', { ...pl, title: 'Mój garaż' }, 'script')).toEqual([])
    expect(keysOf('uk', { ...full, title: 'Мій гараж', days_one: 'x', days_few: 'x', days_many: 'x', days_other: 'x' }, 'script')).toEqual([])
    expect(keysOf('ru', { ...full, title: 'Мой гараж', days_one: 'x', days_few: 'x', days_many: 'x', days_other: 'x' }, 'script')).toEqual([])
  })
})

describe('translation gate: protected spans', () => {
  const CMD = 'Run python tools/fix.py --device-id {{id}} --apply, then set MYGARAGE_SECRET_KEY. Use smtp.example.com:587 or https://ntfy.sh, or send /fuel. Costs {{v}}/day.'

  it('derives command, env, host and slash-command spans but not unit suffixes', () => {
    expect(protectedSpans('common:x', CMD, {})).toEqual([
      'https://ntfy.sh',
      '--device-id',
      '--apply',
      'MYGARAGE_SECRET_KEY',
      'tools/fix.py',
      'ntfy.sh',
      'smtp.example.com:587',
      '/fuel',
    ])
  })

  it('adds the registry literal whole', () => {
    expect(protectedSpans('common:x', 'run foo -d <db> now', { 'common:x': 'foo -d <db>' })).toEqual(['<db>', 'foo -d <db>'])
  })

  it('fails a translation that changes a protected span', () => {
    const en = new Map<string, unknown>([['cmd', 'Set MYGARAGE_SECRET_KEY and add --apply.']])
    const ok = compareNamespace('de', 'common', ['cmd'], en, { cmd: 'Setze MYGARAGE_SECRET_KEY und füge --apply hinzu.' })
    const bad = compareNamespace('de', 'common', ['cmd'], en, { cmd: 'Setze MYGARAGE_SECRET_KEY und füge –apply hinzu.' })
    expect(ok.issues).toEqual([])
    expect(bad.issues.map((i) => [i.type, i.detail])).toEqual([['protected', 'missing "--apply"']])
  })
})

describe('translation gate: the real English bundle', () => {
  const english = loadEnglishData(discoverNamespaces())
  const enValue = (nsKey: string): unknown => {
    const [ns, key] = [nsKey.slice(0, nsKey.indexOf(':')), nsKey.slice(nsKey.indexOf(':') + 1)]
    return english.valuesByNamespace.get(ns)?.get(key)
  }

  // A command someone pastes into a shell has to survive whole, and the
  // pattern spans only cover its pieces. Any new one needs a registry entry.
  it('has a registry entry for every English value that reads like a shell command', () => {
    const commandLike = /\b(?:python3?|pg_restore|pg_dump|docker|sqlite3|sudo|curl|bunx?|uv)\s+\S/
    const found: string[] = []
    for (const [ns, values] of english.valuesByNamespace) {
      for (const [key, value] of values) if (typeof value === 'string' && commandLike.test(value)) found.push(`${ns}:${key}`)
    }
    expect(found.sort()).toEqual(Object.keys(PROTECTED).sort())
  })

  it('keeps each registry literal inside its English value', () => {
    expect(String(enValue('settings:backupTab.postgresRestoreMessage'))).toContain(
      'pg_restore --clean --if-exists --no-owner --no-privileges -d <dbname> mygarage.pgdump',
    )
    for (const [nsKey, literal] of Object.entries(PROTECTED)) expect(String(enValue(nsKey))).toContain(literal)
  })
})

// Runs the installed i18next, so the plural facts the gate leans on are
// checked against the library rather than remembered.
describe('i18next plural selection', () => {
  const render = async (lng: string, res: Record<string, string>, count: number): Promise<string> => {
    const i = createInstance()
    await i.init({
      lng,
      fallbackLng: 'en',
      resources: { en: { t: { d_one: 'EN one', d_other: 'EN other' } }, [lng]: { t: res } },
      defaultNS: 't',
      interpolation: { escapeValue: false },
    })
    return i.t('d', { count })
  }
  const full4 = { d_one: 'one', d_few: 'few', d_many: 'many', d_other: 'other' }

  it('picks few and many for pl and uk', async () => {
    for (const lng of ['pl', 'uk']) {
      expect(await render(lng, full4, 2)).toBe('few')
      expect(await render(lng, full4, 5)).toBe('many')
    }
  })

  it('picks many at one million for fr, it and pt-BR', async () => {
    for (const lng of ['fr', 'it', 'pt-BR']) {
      expect(await render(lng, { d_one: 'one', d_many: 'many', d_other: 'other' }, 1_000_000)).toBe('many')
    }
  })

  it('reads _other for one in ms', async () => {
    expect(await render('ms', { d_one: 'one', d_other: 'other' }, 1)).toBe('other')
  })

  it("falls back to the locale's unsuffixed key before English", async () => {
    expect(await render('pl', { d: 'base', d_one: 'one', d_other: 'other' }, 5)).toBe('base')
    expect(await render('pl', { d_one: 'one', d_other: 'other' }, 5)).toBe('EN other')
  })
})

describe('translation gate: what counts as translated', () => {
  it("doesn't count a copy of English, but does count an invariant one", () => {
    const de = { title: 'My Garage', saved: 'x {{count, number}} {{name}}', vin: 'VIN', days_one: '{{count}} Tag', days_other: '{{count}} Tage' }
    // title is an English copy; vin is invariant.
    expect(compare('de', de).translated).toBe(4)
  })
})

describe('translation gate: no dashes in English copy', () => {
  it('lists English values with an em-dash or en-dash, and nothing else', () => {
    const values = new Map<string, Map<string, unknown>>([
      ['common', new Map<string, unknown>([['a', 'Saved, done'], ['b', 'Saved \u2014 done'], ['c', '1\u20135'], ['d', 'well-known']])],
    ])
    expect(englishDashes(values)).toEqual(['common:b', 'common:c'])
  })

  it('finds none in the real English bundle', () => {
    expect(englishDashes(loadEnglishData(discoverNamespaces()).valuesByNamespace)).toEqual([])
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

describe('sortToEnglish', () => {
  const en = { b: { y: '1', x: '2' }, a: 'A', n: '{{count}}', n_one: 'one', n_other: 'other' }

  it('puts keys in English order, nested too, with plural members together in the language order', () => {
    const pl = { a: 'a', n_many: 'm', n_other: 'o', b: { x: '2', y: '1' }, n: 'n', n_one: '1', n_few: 'f' }
    const out = sortToEnglish(en, pl, 'pl')
    expect(JSON.stringify(out)).toBe(
      JSON.stringify({ b: { y: '1', x: '2' }, a: 'a', n: 'n', n_one: '1', n_few: 'f', n_many: 'm', n_other: 'o' }),
    )
  })

  it('keeps keys English lacks, at the end, and loses nothing', () => {
    const de = { zz: 'extra', a: 'a', b: { q: 'q', y: '1' } }
    const out = sortToEnglish(en, de, 'de')
    expect(JSON.stringify(out)).toBe(JSON.stringify({ b: { y: '1', q: 'q' }, a: 'a', zz: 'extra' }))
  })
})
