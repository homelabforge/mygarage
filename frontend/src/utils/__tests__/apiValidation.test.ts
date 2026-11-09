import { describe, it, expect } from 'vitest'
import { parseValidationErrors, isValidationProblemArray } from '@/utils/apiValidation'

describe('parseValidationErrors', () => {
  it('maps a body field to a bare field name', () => {
    // verbatim shape from the issue #140 container log
    const detail = [
      { type: 'decimal_parsing', loc: ['body', 'premium_amount'], msg: 'Input should be a valid decimal', input: '528,25' },
      { type: 'decimal_parsing', loc: ['body', 'deductible'], msg: 'Input should be a valid decimal', input: '' },
    ]
    expect(parseValidationErrors(detail)).toEqual([
      { field: 'premium_amount', message: 'Input should be a valid decimal', type: 'decimal_parsing' },
      { field: 'deductible', message: 'Input should be a valid decimal', type: 'decimal_parsing' },
    ])
  })

  it('renders nested and indexed locs in react-hook-form path syntax', () => {
    const detail = [{ type: 'missing', loc: ['body', 'items', 0, 'qty'], msg: 'Field required' }]
    expect(parseValidationErrors(detail)[0].field).toBe('items.0.qty')
  })

  it('keeps non-body locs distinguishable rather than colliding with form fields', () => {
    const detail = [{ type: 'missing', loc: ['query', 'vin'], msg: 'Field required' }]
    expect(parseValidationErrors(detail)[0].field).toBe('query.vin')
  })

  it('ignores a bare body loc with no field', () => {
    expect(parseValidationErrors([{ type: 'missing', loc: ['body'], msg: 'Field required' }])).toEqual([])
  })

  it('returns empty for shapes that are not validation arrays', () => {
    expect(parseValidationErrors('Not found')).toEqual([])
    expect(parseValidationErrors(undefined)).toEqual([])
    expect(parseValidationErrors({ detail: 'oops' })).toEqual([])
    expect(parseValidationErrors([{ nope: true }])).toEqual([])
  })
})

describe('isValidationProblemArray', () => {
  it('accepts a well-formed array and rejects a string detail', () => {
    expect(isValidationProblemArray([{ type: 'missing', loc: ['body', 'x'], msg: 'r' }])).toBe(true)
    expect(isValidationProblemArray('Vehicle not found')).toBe(false)
  })

  it('rejects an empty array, which carries no problem to show', () => {
    expect(isValidationProblemArray([])).toBe(false)
  })

  it('rejects a loc holding anything but strings and numbers', () => {
    expect(isValidationProblemArray([{ type: 'missing', loc: ['body', { x: 1 }], msg: 'r' }])).toBe(false)
    expect(isValidationProblemArray([{ type: 'missing', loc: ['body', null], msg: 'r' }])).toBe(false)
    // Indexed paths stay legal.
    expect(isValidationProblemArray([{ type: 'missing', loc: ['body', 'items', 0], msg: 'r' }])).toBe(true)
  })
})
