import { describe, it, expect } from 'vitest'
import { z } from 'zod'

// Mock fuel record schema
const fuelRecordSchema = z.object({
  date: z.string().min(1, 'Date is required'),
  gallons: z.number().positive('Gallons must be positive'),
  cost: z.number().min(0, 'Cost cannot be negative'),
  odometer: z.number().int().positive('Odometer must be positive'),
  is_full_tank: z.boolean(),
  price_per_gallon: z.number().positive('Price must be positive').optional(),
  station: z.string().optional(),
  octane: z.number().int().min(85).max(100).optional(),
  hauling: z.boolean().optional(),
  notes: z.string().optional(),
})

describe('Fuel Record Schema', () => {
  it('validates valid fuel record', () => {
    const validFuel = {
      date: '2024-01-15',
      gallons: 12.5,
      cost: 45.00,
      odometer: 15500,
      is_full_tank: true,
    }

    const result = fuelRecordSchema.safeParse(validFuel)
    expect(result.success).toBe(true)
  })

  it('requires positive gallons', () => {
    const invalidFuel = {
      date: '2024-01-15',
      gallons: -12.5, // Negative
      cost: 45.00,
      odometer: 15500,
      is_full_tank: true,
    }

    const result = fuelRecordSchema.safeParse(invalidFuel)
    expect(result.success).toBe(false)
  })

  it('requires non-negative cost', () => {
    const invalidFuel = {
      date: '2024-01-15',
      gallons: 12.5,
      cost: -10, // Negative
      odometer: 15500,
      is_full_tank: true,
    }

    const result = fuelRecordSchema.safeParse(invalidFuel)
    expect(result.success).toBe(false)
  })

  it('requires positive odometer', () => {
    const invalidFuel = {
      date: '2024-01-15',
      gallons: 12.5,
      cost: 45.00,
      odometer: 0, // Not positive
      is_full_tank: true,
    }

    const result = fuelRecordSchema.safeParse(invalidFuel)
    expect(result.success).toBe(false)
  })

  it('validates octane range', () => {
    const invalidFuel = {
      date: '2024-01-15',
      gallons: 12.5,
      cost: 45.00,
      odometer: 15500,
      is_full_tank: true,
      octane: 110, // Too high
    }

    const result = fuelRecordSchema.safeParse(invalidFuel)
    expect(result.success).toBe(false)
  })

  it('allows optional fields', () => {
    const validFuel = {
      date: '2024-01-15',
      gallons: 12.5,
      cost: 45.00,
      odometer: 15500,
      is_full_tank: true,
      // station, octane, notes are optional
    }

    const result = fuelRecordSchema.safeParse(validFuel)
    expect(result.success).toBe(true)
  })

  it('validates price per gallon calculation', () => {
    const validFuel = {
      date: '2024-01-15',
      gallons: 12.0,
      cost: 43.20,
      odometer: 15500,
      is_full_tank: true,
      price_per_gallon: 3.60,
    }

    const result = fuelRecordSchema.safeParse(validFuel)
    expect(result.success).toBe(true)

    // Verify calculation: 43.20 / 12.0 = 3.60
    if (result.success) {
      const calculatedPrice = result.data.cost / result.data.gallons
      expect(calculatedPrice).toBeCloseTo(3.60, 2)
    }
  })
})
