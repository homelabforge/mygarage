import { describe, expect, it } from 'vitest'
import { formatCurrency, formatCurrencyZero } from '../formatUtils'

describe('formatCurrency', () => {
  it('formats USD values with default locale', () => {
    expect(formatCurrency(42, { currencyCode: 'USD' })).toContain('$')
    expect(formatCurrency(42, { currencyCode: 'USD' })).toContain('42.00')
  })

  it('formats EUR under en-US with the € symbol', () => {
    const out = formatCurrency(42, { currencyCode: 'EUR' })
    expect(out).toContain('€')
  })

  it('returns fallback for null / undefined / 0 by default', () => {
    expect(formatCurrency(null, { currencyCode: 'USD' })).toBe('-')
    expect(formatCurrency(undefined, { currencyCode: 'USD' })).toBe('-')
    expect(formatCurrency(0, { currencyCode: 'USD' })).toBe('-')
  })

  it('formats 0 when zeroIsValid is true', () => {
    const out = formatCurrency(0, { currencyCode: 'USD', zeroIsValid: true })
    expect(out).toContain('$')
    expect(out).toContain('0.00')
  })

  it('handles whole-dollar formatting', () => {
    const out = formatCurrency(1234.56, { currencyCode: 'USD', wholeDollars: true })
    // whole-dollar mode drops the cents
    expect(out).toContain('$')
    expect(out).not.toContain('.')
  })

  it('swaps ¤ for the currency code when Intl silently emits the generic sign (XXX)', () => {
    const out = formatCurrency(42, { currencyCode: 'XXX' })
    expect(out).not.toContain('¤')
    expect(out).toContain('XXX')
  })

  it('falls back to code-prefixed decimal when Intl throws on a hard-invalid code', () => {
    const out = formatCurrency(42, { currencyCode: 'BADX' })
    expect(out).toContain('BADX')
    expect(out).toContain('42.00')
    expect(out).not.toContain('¤')
    expect(out).not.toContain('$')
  })

  it('returns fallback when input string is not parseable', () => {
    expect(formatCurrency('not-a-number', { currencyCode: 'USD' })).toBe('-')
  })
})

describe('formatCurrencyZero', () => {
  it('falls back to zero-formatted value when input is null', () => {
    const zero = formatCurrencyZero(null, { currencyCode: 'USD' })
    expect(zero).toContain('$')
    expect(zero).toContain('0.00')
  })

  it('uses the correct currency symbol for non-USD', () => {
    const out = formatCurrencyZero(null, { currencyCode: 'EUR' })
    expect(out).toContain('€')
  })

  it('never leaks ¤ for XXX', () => {
    const out = formatCurrencyZero(null, { currencyCode: 'XXX' })
    expect(out).not.toContain('¤')
  })

  it('falls back cleanly on a hard-invalid code', () => {
    const out = formatCurrencyZero(null, { currencyCode: 'BADX' })
    expect(out).toContain('BADX')
    expect(out).not.toContain('¤')
  })
})
