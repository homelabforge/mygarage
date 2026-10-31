import { describe, expect, it } from 'vitest'

import { num } from '../wireNumber'

// guard: the six component copies behaved exactly like this before they moved here.
describe('num', () => {
  it('reads null, undefined and a blank string as no value', () => {
    expect(num(null)).toBeNull()
    expect(num(undefined)).toBeNull()
    expect(num('')).toBeNull()
  })

  it('reads a wire decimal string as its number', () => {
    expect(num('47000.00')).toBe(47000)
    expect(num('2.50')).toBe(2.5)
    expect(num('0')).toBe(0)
    expect(num('-1.25')).toBe(-1.25)
  })

  it('passes a number through untouched', () => {
    expect(num(0)).toBe(0)
    expect(num(8.4)).toBe(8.4)
  })

  it('keeps Number() semantics for anything else, as the copies did', () => {
    expect(num(' ')).toBe(0)
    expect(num('abc')).toBeNaN()
  })
})
