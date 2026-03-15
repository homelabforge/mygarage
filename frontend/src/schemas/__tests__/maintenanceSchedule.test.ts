import { describe, it, expect } from 'vitest'
import {
  maintenanceScheduleItemSchema,
  maintenanceScheduleItemSchemaRefined,
  COMPONENT_CATEGORIES,
} from '../maintenanceSchedule'

describe('Maintenance Schedule Item Schema', () => {
  const validItem = {
    name: 'Oil Change',
    component_category: 'Engine' as const,
    item_type: 'service' as const,
    interval_months: 6,
    interval_miles: 5000,
  }

  it('validates valid schedule item', () => {
    const result = maintenanceScheduleItemSchema.safeParse(validItem)
    expect(result.success).toBe(true)
  })

  it('requires name', () => {
    const { name, ...missing } = validItem
    const result = maintenanceScheduleItemSchema.safeParse(missing)
    expect(result.success).toBe(false)
  })

  it('requires component_category to be valid enum', () => {
    const result = maintenanceScheduleItemSchema.safeParse({
      ...validItem,
      component_category: 'Warp Drive',
    })
    expect(result.success).toBe(false)
  })

  it('accepts all valid component categories', () => {
    for (const cat of COMPONENT_CATEGORIES) {
      const result = maintenanceScheduleItemSchema.safeParse({
        ...validItem,
        component_category: cat,
      })
      expect(result.success).toBe(true)
    }
  })

  it('requires item_type to be service or inspection', () => {
    const result = maintenanceScheduleItemSchema.safeParse({
      ...validItem,
      item_type: 'repair',
    })
    expect(result.success).toBe(false)
  })

  it('rejects interval_months below 1', () => {
    const result = maintenanceScheduleItemSchema.safeParse({
      ...validItem,
      interval_months: 0,
    })
    expect(result.success).toBe(false)
  })

  it('rejects interval_months above 120', () => {
    const result = maintenanceScheduleItemSchema.safeParse({
      ...validItem,
      interval_months: 121,
    })
    expect(result.success).toBe(false)
  })

  it('rejects interval_miles below 100', () => {
    const result = maintenanceScheduleItemSchema.safeParse({
      ...validItem,
      interval_miles: 50,
    })
    expect(result.success).toBe(false)
  })

  it('rejects interval_miles above 200000', () => {
    const result = maintenanceScheduleItemSchema.safeParse({
      ...validItem,
      interval_miles: 200001,
    })
    expect(result.success).toBe(false)
  })

  it('transforms NaN interval values to undefined', () => {
    const result = maintenanceScheduleItemSchema.safeParse({
      ...validItem,
      interval_months: NaN,
      interval_miles: NaN,
    })
    expect(result.success).toBe(true)
    if (result.success) {
      expect(result.data.interval_months).toBeUndefined()
      expect(result.data.interval_miles).toBeUndefined()
    }
  })
})

describe('Maintenance Schedule Item Schema (Refined)', () => {
  it('requires at least one interval', () => {
    const result = maintenanceScheduleItemSchemaRefined.safeParse({
      name: 'Oil Change',
      component_category: 'Engine',
      item_type: 'service',
      interval_months: NaN,
      interval_miles: NaN,
    })
    expect(result.success).toBe(false)
  })

  it('accepts months-only interval', () => {
    const result = maintenanceScheduleItemSchemaRefined.safeParse({
      name: 'Oil Change',
      component_category: 'Engine',
      item_type: 'service',
      interval_months: 6,
    })
    expect(result.success).toBe(true)
  })

  it('accepts miles-only interval', () => {
    const result = maintenanceScheduleItemSchemaRefined.safeParse({
      name: 'Oil Change',
      component_category: 'Engine',
      item_type: 'service',
      interval_miles: 5000,
    })
    expect(result.success).toBe(true)
  })
})
