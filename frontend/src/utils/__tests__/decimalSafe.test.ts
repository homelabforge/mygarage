import { describe, it, expect } from 'vitest'
import {
  toCanonicalKm,
  toCanonicalLiters,
  toCanonicalKg,
  toCanonicalMeters,
  priceToDisplay,
  priceToCanonical,
} from '../decimalSafe'

describe('toCanonical*', () => {
  it('passes metric values through unchanged', () => {
    expect(toCanonicalKm(100, 'metric')).toBe(100)
    expect(toCanonicalLiters(50, 'metric')).toBe(50)
    expect(toCanonicalKg(20, 'metric')).toBe(20)
    expect(toCanonicalMeters(5, 'metric')).toBe(5)
  })

  it('converts imperial values to canonical metric', () => {
    expect(toCanonicalKm(60, 'imperial')).toBeCloseTo(96.56, 2)
    expect(toCanonicalLiters(10, 'imperial')).toBeCloseTo(37.85, 2)
  })

  it('returns null for nullish or NaN input', () => {
    expect(toCanonicalKm(null, 'imperial')).toBeNull()
    expect(toCanonicalLiters(undefined, 'metric')).toBeNull()
    expect(toCanonicalKg(NaN, 'imperial')).toBeNull()
  })
})

describe('priceToDisplay / priceToCanonical (per_volume)', () => {
  it('converts $/L canonical to $/gal for imperial display', () => {
    // Real bug repro: stored $1.136/L should display as $4.30/gal
    expect(priceToDisplay(1.136, 'imperial', 'per_volume')).toBeCloseTo(4.3, 2)
  })

  it('passes $/L through for metric users', () => {
    expect(priceToDisplay(1.136, 'metric', 'per_volume')).toBe(1.136)
  })

  it('converts $/gal back to $/L on submit', () => {
    expect(priceToCanonical(4.3, 'imperial', 'per_volume')).toBeCloseTo(1.136, 3)
  })

  it('round-trips imperial → canonical → display without drift beyond 3 decimals', () => {
    const userTyped = 4.299
    const canonical = priceToCanonical(userTyped, 'imperial', 'per_volume')
    expect(canonical).not.toBeNull()
    const back = priceToDisplay(canonical!, 'imperial', 'per_volume')
    expect(back).toBeCloseTo(userTyped, 2)
  })

  it('accepts string input from API responses', () => {
    expect(priceToDisplay('1.136', 'imperial', 'per_volume')).toBeCloseTo(4.3, 2)
  })
})

describe('priceToDisplay / priceToCanonical (per_weight)', () => {
  it('converts $/kg canonical to $/lb for imperial display', () => {
    // 2.20 $/kg ≈ 1.00 $/lb
    expect(priceToDisplay(2.2046, 'imperial', 'per_weight')).toBeCloseTo(1.0, 2)
  })

  it('converts $/lb back to $/kg on submit', () => {
    // $1/lb means a kg (heavier) costs more: 1 / 0.453592 ≈ $2.205/kg
    expect(priceToCanonical(1.0, 'imperial', 'per_weight')).toBeCloseTo(2.205, 3)
  })
})

describe('priceToDisplay / priceToCanonical (universal bases)', () => {
  it('passes per_kwh through unchanged for both systems', () => {
    expect(priceToDisplay(0.13, 'imperial', 'per_kwh')).toBe(0.13)
    expect(priceToCanonical(0.13, 'imperial', 'per_kwh')).toBe(0.13)
  })

  it('passes per_tank through unchanged', () => {
    expect(priceToDisplay(25, 'imperial', 'per_tank')).toBe(25)
    expect(priceToCanonical(25, 'imperial', 'per_tank')).toBe(25)
  })

  it('passes through when basis is missing or unknown', () => {
    expect(priceToDisplay(1.136, 'imperial', null)).toBe(1.136)
    expect(priceToDisplay(1.136, 'imperial', undefined)).toBe(1.136)
    expect(priceToDisplay(1.136, 'imperial', 'something_else')).toBe(1.136)
  })

  it('returns null for nullish or NaN input', () => {
    expect(priceToDisplay(null, 'imperial', 'per_volume')).toBeNull()
    expect(priceToDisplay(undefined, 'metric', 'per_volume')).toBeNull()
    expect(priceToCanonical(NaN, 'imperial', 'per_volume')).toBeNull()
  })
})
