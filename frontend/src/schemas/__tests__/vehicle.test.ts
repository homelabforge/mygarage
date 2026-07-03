import { describe, it, expect } from 'vitest'
import { z } from 'zod'
import { vehicleEditSchema } from '../vehicle'

// Mock vehicle schema based on typical structure
const vehicleSchema = z.object({
  vin: z.string().length(17, 'VIN must be 17 characters'),
  year: z.number().int().min(1900).max(new Date().getFullYear() + 1),
  make: z.string().min(1, 'Make is required'),
  model: z.string().min(1, 'Model is required'),
  trim: z.string().optional(),
  nickname: z.string().optional(),
  license_plate: z.string().optional(),
  current_odometer: z.number().int().min(0).optional(),
  purchase_date: z.string().optional(),
  purchase_price: z.number().min(0).optional(),
})

describe('Vehicle Schema', () => {
  it('validates valid vehicle object', () => {
    const validVehicle = {
      vin: '1HGBH41JXMN109186',
      year: 2018,
      make: 'Honda',
      model: 'Accord',
    }

    const result = vehicleSchema.safeParse(validVehicle)
    expect(result.success).toBe(true)
  })

  it('requires 17-character VIN', () => {
    const invalidVehicle = {
      vin: 'SHORT',
      year: 2018,
      make: 'Honda',
      model: 'Accord',
    }

    const result = vehicleSchema.safeParse(invalidVehicle)
    expect(result.success).toBe(false)
    if (!result.success) {
      expect(result.error.issues[0].message).toContain('17 characters')
    }
  })

  it('requires make and model', () => {
    const invalidVehicle = {
      vin: '1HGBH41JXMN109186',
      year: 2018,
      make: '',
      model: '',
    }

    const result = vehicleSchema.safeParse(invalidVehicle)
    expect(result.success).toBe(false)
  })

  it('validates year range', () => {
    const invalidVehicle = {
      vin: '1HGBH41JXMN109186',
      year: 1800, // Too old
      make: 'Honda',
      model: 'Accord',
    }

    const result = vehicleSchema.safeParse(invalidVehicle)
    expect(result.success).toBe(false)
  })

  it('validates positive odometer', () => {
    const invalidVehicle = {
      vin: '1HGBH41JXMN109186',
      year: 2018,
      make: 'Honda',
      model: 'Accord',
      current_odometer: -100, // Negative
    }

    const result = vehicleSchema.safeParse(invalidVehicle)
    expect(result.success).toBe(false)
  })

  it('allows optional fields', () => {
    const validVehicle = {
      vin: '1HGBH41JXMN109186',
      year: 2018,
      make: 'Honda',
      model: 'Accord',
      // trim, nickname, etc. are optional
    }

    const result = vehicleSchema.safeParse(validVehicle)
    expect(result.success).toBe(true)
  })
})

// Task 3 (frontend fuel-type hardening): the real vehicleEditSchema used by
// VehicleWizard/VehicleEdit. fuel_type must transform blank/missing input to
// an explicit `null`, not `undefined` — the vehicle update endpoint uses
// Pydantic's `model_dump(exclude_unset=True)`, so an `undefined` key gets
// dropped by JSON.stringify and the backend treats it as "unchanged" rather
// than "clear this field".
describe('vehicleEditSchema — fuel_type null-vs-undefined', () => {
  it('passes through a valid canonical fuel_type value unchanged', () => {
    const result = vehicleEditSchema.parse({ fuel_type: 'diesel' })
    expect(result.fuel_type).toBe('diesel')
  })

  it('transforms the empty-option selection ("") to null', () => {
    const result = vehicleEditSchema.parse({ fuel_type: '' })
    expect(result.fuel_type).toBeNull()
  })

  it('transforms an omitted fuel_type to null', () => {
    const result = vehicleEditSchema.parse({})
    expect(result.fuel_type).toBeNull()
  })

  it('transforms a null fuel_type (as loaded from an unset vehicle record) to null', () => {
    const result = vehicleEditSchema.parse({ fuel_type: null })
    expect(result.fuel_type).toBeNull()
  })

  it('serializes to a `"fuel_type":null` key, unlike undefined which JSON.stringify drops', () => {
    const result = vehicleEditSchema.parse({ fuel_type: '' })
    const roundTripped = JSON.parse(JSON.stringify(result))
    expect(roundTripped).toHaveProperty('fuel_type', null)
  })
})

// Task 19 (fold-in fix): the same null-vs-undefined bug documented above for
// fuel_type also affects every other optional string field on this schema
// (nickname, trim, make, model, etc. — all backed by optionalStringSchema).
// Clearing one of these fields in the UI must submit an explicit `null`, not
// `undefined` (which JSON.stringify drops, and which the backend's
// `exclude_unset=True` partial update then reads as "leave unchanged").
describe('vehicleEditSchema — sibling optional-string fields null-vs-undefined', () => {
  it('passes through a set nickname unchanged', () => {
    const result = vehicleEditSchema.parse({ nickname: 'My Truck' })
    expect(result.nickname).toBe('My Truck')
  })

  it('transforms a blanked-out nickname ("") to null', () => {
    const result = vehicleEditSchema.parse({ nickname: '' })
    expect(result.nickname).toBeNull()
  })

  it('transforms an omitted nickname to null', () => {
    const result = vehicleEditSchema.parse({})
    expect(result.nickname).toBeNull()
  })

  it('transforms a null nickname to null', () => {
    const result = vehicleEditSchema.parse({ nickname: null })
    expect(result.nickname).toBeNull()
  })

  // JSON.stringify's null-vs-undefined serialization behavior is already
  // locked in by the fuel_type round-trip test above; nickname goes through
  // the same `nullOnBlank` transform, so re-asserting it here would only
  // re-test JSON.stringify itself, not new schema logic.

  it('transforms a blanked-out trim ("") to null (spot-check a second sibling field)', () => {
    const result = vehicleEditSchema.parse({ trim: '' })
    expect(result.trim).toBeNull()
  })
})

// Task 19 extension: the same null-on-clear bug affects the date fields
// (purchase_date, sold_date via optionalDateSchema) — clearing a
// previously-set date in the edit form must submit explicit `null`, not
// `undefined`.
describe('vehicleEditSchema — date fields null-on-clear', () => {
  it('passes through a set purchase_date unchanged', () => {
    const result = vehicleEditSchema.parse({ purchase_date: '2020-03-15' })
    expect(result.purchase_date).toBe('2020-03-15')
  })

  it('transforms a blanked-out purchase_date ("") to null', () => {
    const result = vehicleEditSchema.parse({ purchase_date: '' })
    expect(result.purchase_date).toBeNull()
  })

  it('transforms a null purchase_date to null', () => {
    const result = vehicleEditSchema.parse({ purchase_date: null })
    expect(result.purchase_date).toBeNull()
  })

  it('transforms a blanked-out sold_date ("") to null', () => {
    const result = vehicleEditSchema.parse({ sold_date: '' })
    expect(result.sold_date).toBeNull()
  })
})

// Task 19 extension: the numeric fields (purchase_price, sold_price, year,
// doors, cylinders) collapsed a blanked input — which react-hook-form's
// `valueAsNumber` turns into NaN — to `undefined`, same silent no-op against
// `exclude_unset=True`. Clearing must yield `null`. A legitimate zero (e.g.
// a free vehicle, or 0 doors on a trailer) must survive as 0, not become
// null: the backend accepts 0 (no `ge` constraint on prices).
describe('vehicleEditSchema — numeric fields null-on-clear (blank vs. zero)', () => {
  it('transforms a blanked-out purchase_price (NaN) to null', () => {
    const result = vehicleEditSchema.parse({ purchase_price: NaN })
    expect(result.purchase_price).toBeNull()
  })

  it('transforms a null purchase_price to null', () => {
    const result = vehicleEditSchema.parse({ purchase_price: null })
    expect(result.purchase_price).toBeNull()
  })

  it('preserves a zero purchase_price as 0 (not null)', () => {
    const result = vehicleEditSchema.parse({ purchase_price: 0 })
    expect(result.purchase_price).toBe(0)
  })

  it('passes through a set purchase_price unchanged', () => {
    const result = vehicleEditSchema.parse({ purchase_price: 15000 })
    expect(result.purchase_price).toBe(15000)
  })

  it('transforms a blanked-out sold_price (NaN) to null', () => {
    const result = vehicleEditSchema.parse({ sold_price: NaN })
    expect(result.sold_price).toBeNull()
  })

  it('transforms a blanked-out year (NaN) to null', () => {
    const result = vehicleEditSchema.parse({ year: NaN })
    expect(result.year).toBeNull()
  })

  it('transforms a blanked-out doors (NaN) to null but preserves zero', () => {
    expect(vehicleEditSchema.parse({ doors: NaN }).doors).toBeNull()
    expect(vehicleEditSchema.parse({ doors: 0 }).doors).toBe(0)
  })

  it('transforms a blanked-out cylinders (NaN) to null but preserves zero', () => {
    expect(vehicleEditSchema.parse({ cylinders: NaN }).cylinders).toBeNull()
    expect(vehicleEditSchema.parse({ cylinders: 0 }).cylinders).toBe(0)
  })
})
