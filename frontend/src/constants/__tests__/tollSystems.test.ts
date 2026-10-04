import { describe, it, expect } from 'vitest'
import { TOLL_COUNTRIES } from '../tollSystems'
import { SUPPORTED_CURRENCIES, SUPPORTED_LANGUAGES } from '../i18n'
import { TOLL_OTHER, listedTollSystem, tidyTollSystem, tollSystemMatchKey } from '../../utils/tollSystems'

// Contributors add rows here, so these checks are the review a PR gets for free.
const regionName = new Intl.DisplayNames(['en'], { type: 'region', fallback: 'none' })

describe('TOLL_COUNTRIES', () => {
  // Catches typos and lower case, not strict ISO membership: ICU names some
  // reserved codes too. "Unknown Region" is what it says for a code it can't place.
  it('uses each country code once, and only two-letter codes the browser can name', () => {
    const codes = TOLL_COUNTRIES.map((c) => c.country)
    expect(new Set(codes).size).toBe(codes.length)
    const unknown = regionName.of('ZZ')
    for (const code of codes) {
      expect(code, code).toMatch(/^[A-Z]{2}$/)
      expect(regionName.of(code), code).toBeDefined()
      expect(regionName.of(code), code).not.toBe(unknown)
    }
  })

  it('guesses only from currencies and languages the app supports', () => {
    const currencies = new Set(SUPPORTED_CURRENCIES.map((c) => c.code))
    const languages = new Set(SUPPORTED_LANGUAGES.map((l) => l.code))
    for (const c of TOLL_COUNTRIES) {
      for (const code of c.currencies) expect(currencies.has(code), `${c.country} ${code}`).toBe(true)
      for (const code of c.languages) expect(languages.has(code), `${c.country} ${code}`).toBe(true)
    }
  })

  it('lists at least one system per country, each once, tidy and within the 50 the API stores', () => {
    for (const c of TOLL_COUNTRIES) {
      expect(c.systems.length, c.country).toBeGreaterThan(0)
      expect(new Set(c.systems).size, c.country).toBe(c.systems.length)
      for (const s of c.systems) {
        expect(tidyTollSystem(s), s).toBe(s)
        expect(s.length, s).toBeGreaterThan(0)
        expect(s.length, s).toBeLessThanOrEqual(50)
        expect(tollSystemMatchKey(s), s).not.toBe('')
      }
    }
  })

  it('spells a system the same everywhere, so no two spellings share a match key', () => {
    const seen = new Map<string, string>()
    for (const c of TOLL_COUNTRIES) {
      for (const s of c.systems) {
        const key = tollSystemMatchKey(s)
        const earlier = seen.get(key)
        if (earlier !== undefined) expect(s, `"${s}" vs "${earlier}"`).toBe(earlier)
        seen.set(key, s)
      }
    }
  })

  it('keeps the old literal "Other" and the select sentinel off the list', () => {
    expect(listedTollSystem('Other')).toBeNull()
    for (const c of TOLL_COUNTRIES) {
      expect(c.country).not.toBe(TOLL_OTHER)
      expect(c.systems).not.toContain(TOLL_OTHER)
    }
  })
})
