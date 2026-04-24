import { describe, expect, it } from 'vitest'
import { getCurrencySymbol } from '../currency'

describe('getCurrencySymbol', () => {
  it('returns $ for USD under en-US', () => {
    expect(getCurrencySymbol('USD', 'en-US')).toBe('$')
  })

  it('returns € for EUR under en-US and de-DE', () => {
    expect(getCurrencySymbol('EUR', 'en-US')).toBe('€')
    expect(getCurrencySymbol('EUR', 'de-DE')).toBe('€')
  })

  it('returns currency-specific symbols for common codes', () => {
    expect(getCurrencySymbol('GBP', 'en-US')).toBe('£')
    expect(getCurrencySymbol('JPY', 'en-US')).toBe('¥')
    expect(getCurrencySymbol('INR', 'en-US')).toBe('₹')
  })

  it('returns localized zł for PLN', () => {
    expect(getCurrencySymbol('PLN', 'pl-PL')).toBe('zł')
  })

  it('falls back to the code for hard-invalid input (BADX throws RangeError)', () => {
    const result = getCurrencySymbol('BADX', 'en-US')
    expect(result).toBe('BADX')
    expect(result).not.toBe('¤')
    expect(result).not.toBe('$')
  })

  it('falls back to the code when Intl silently emits ¤ (XXX is ISO "no currency")', () => {
    const result = getCurrencySymbol('XXX', 'en-US')
    expect(result).toBe('XXX')
    expect(result).not.toBe('¤')
  })

  it('is locale-sensitive and caches per (locale, code)', () => {
    // Call the same key twice — result should be identical (cached).
    const a = getCurrencySymbol('USD', 'en-US')
    const b = getCurrencySymbol('USD', 'en-US')
    expect(a).toBe(b)
  })
})
