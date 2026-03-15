import { describe, it, expect } from 'vitest'
import { odometerRecordSchema } from '../odometer'

describe('Odometer Record Schema', () => {
  const validOdometer = {
    date: '2024-03-01',
    mileage: 52340,
  }

  it('validates valid odometer record', () => {
    const result = odometerRecordSchema.safeParse(validOdometer)
    expect(result.success).toBe(true)
  })

  it('validates with optional notes', () => {
    const result = odometerRecordSchema.safeParse({
      ...validOdometer,
      notes: 'Recorded at oil change',
    })
    expect(result.success).toBe(true)
  })

  it('requires date', () => {
    const result = odometerRecordSchema.safeParse({ mileage: 52340 })
    expect(result.success).toBe(false)
  })

  it('requires mileage', () => {
    const result = odometerRecordSchema.safeParse({ date: '2024-03-01' })
    expect(result.success).toBe(false)
  })

  it('requires date in YYYY-MM-DD format', () => {
    const result = odometerRecordSchema.safeParse({
      ...validOdometer,
      date: 'March 1, 2024',
    })
    expect(result.success).toBe(false)
  })

  it('rejects negative mileage', () => {
    const result = odometerRecordSchema.safeParse({
      ...validOdometer,
      mileage: -1,
    })
    expect(result.success).toBe(false)
  })

  it('rejects non-integer mileage', () => {
    const result = odometerRecordSchema.safeParse({
      ...validOdometer,
      mileage: 52340.5,
    })
    expect(result.success).toBe(false)
  })

  it('rejects mileage exceeding max', () => {
    const result = odometerRecordSchema.safeParse({
      ...validOdometer,
      mileage: 10000000,
    })
    expect(result.success).toBe(false)
  })
})
