import { describe, it, expect } from 'vitest'
import {
  SUPPORTED_COUNTRY_CODES,
  EU_MEMBER_STATES,
  asCountryCode,
  countryName,
  countryOptions,
} from '../countries'

describe('SUPPORTED_COUNTRY_CODES', () => {
  it('holds the 249 assigned ISO 3166-1 alpha-2 codes, each once', () => {
    expect(SUPPORTED_COUNTRY_CODES).toHaveLength(249)
    expect(new Set(SUPPORTED_COUNTRY_CODES).size).toBe(249)
    for (const code of SUPPORTED_COUNTRY_CODES) expect(code).toMatch(/^[A-Z]{2}$/)
  })

  it('names every code in English and in French', () => {
    for (const code of SUPPORTED_COUNTRY_CODES) {
      expect(countryName(code, 'en-US')).not.toBe(code)
      expect(countryName(code, 'fr-FR')).not.toBe(code)
    }
  })

  it('lists the 27 EU member states, all supported', () => {
    expect(EU_MEMBER_STATES).toHaveLength(27)
    for (const code of EU_MEMBER_STATES) expect(SUPPORTED_COUNTRY_CODES).toContain(code)
  })
})

describe('asCountryCode', () => {
  it('trims and uppercases a known code', () => {
    expect(asCountryCode(' fr ')).toBe('FR')
    expect(asCountryCode('LU')).toBe('LU')
  })

  it('reads anything else as not set', () => {
    expect(asCountryCode('XX')).toBeNull()
    expect(asCountryCode('FRA')).toBeNull()
    expect(asCountryCode('')).toBeNull()
    expect(asCountryCode(null)).toBeNull()
    expect(asCountryCode(undefined)).toBeNull()
  })
})

describe('countryOptions', () => {
  it('sorts by the localised name', () => {
    const fr = countryOptions('fr-FR')
    expect(fr.map((o) => o.label)).toEqual([...fr.map((o) => o.label)].sort((a, b) => a.localeCompare(b, 'fr-FR')))
    expect(fr.find((o) => o.value === 'DE')?.label).toBe('Allemagne')
    expect(countryOptions('en-US').find((o) => o.value === 'DE')?.label).toBe('Germany')
  })
})
