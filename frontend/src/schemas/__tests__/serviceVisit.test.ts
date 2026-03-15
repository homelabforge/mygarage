import { describe, it, expect } from 'vitest'
import {
  serviceVisitSchema,
  serviceVisitSchemaRefined,
  serviceLineItemSchema,
  SERVICE_CATEGORIES,
} from '../serviceVisit'

describe('Service Line Item Schema', () => {
  const validLineItem = {
    description: 'Oil and filter change',
  }

  it('validates valid line item with required fields', () => {
    const result = serviceLineItemSchema.safeParse(validLineItem)
    expect(result.success).toBe(true)
  })

  it('requires description', () => {
    const result = serviceLineItemSchema.safeParse({})
    expect(result.success).toBe(false)
  })

  it('rejects description over 200 characters', () => {
    const result = serviceLineItemSchema.safeParse({
      description: 'A'.repeat(201),
    })
    expect(result.success).toBe(false)
  })

  it('validates with cost and notes', () => {
    const result = serviceLineItemSchema.safeParse({
      ...validLineItem,
      cost: 89.99,
      notes: 'Used synthetic oil',
    })
    expect(result.success).toBe(true)
  })

  it('accepts inspection fields', () => {
    const result = serviceLineItemSchema.safeParse({
      ...validLineItem,
      is_inspection: true,
      inspection_result: 'passed',
      inspection_severity: 'green',
    })
    expect(result.success).toBe(true)
  })

  it('rejects invalid inspection_result', () => {
    const result = serviceLineItemSchema.safeParse({
      ...validLineItem,
      is_inspection: true,
      inspection_result: 'maybe',
    })
    expect(result.success).toBe(false)
  })
})

describe('Service Visit Schema', () => {
  const validVisit = {
    date: '2024-06-15',
    line_items: [{ description: 'Oil and filter change' }],
  }

  it('validates valid service visit', () => {
    const result = serviceVisitSchema.safeParse(validVisit)
    expect(result.success).toBe(true)
  })

  it('validates visit with all optional fields', () => {
    const result = serviceVisitSchema.safeParse({
      ...validVisit,
      vendor_id: 5,
      mileage: 55000,
      notes: 'Regular maintenance visit',
      service_category: 'Maintenance',
      insurance_claim_number: 'CLM-2024-001',
    })
    expect(result.success).toBe(true)
  })

  it('requires at least one line item', () => {
    const result = serviceVisitSchema.safeParse({
      date: '2024-06-15',
      line_items: [],
    })
    expect(result.success).toBe(false)
  })

  it('requires date in YYYY-MM-DD format', () => {
    const result = serviceVisitSchema.safeParse({
      ...validVisit,
      date: '06/15/2024',
    })
    expect(result.success).toBe(false)
  })

  it('accepts all valid service categories', () => {
    for (const cat of SERVICE_CATEGORIES) {
      const result = serviceVisitSchema.safeParse({
        ...validVisit,
        service_category: cat,
      })
      expect(result.success).toBe(true)
    }
  })

  it('allows empty string service_category', () => {
    const result = serviceVisitSchema.safeParse({
      ...validVisit,
      service_category: '',
    })
    expect(result.success).toBe(true)
  })

  it('transforms NaN vendor_id to undefined', () => {
    const result = serviceVisitSchema.safeParse({
      ...validVisit,
      vendor_id: NaN,
    })
    expect(result.success).toBe(true)
    if (result.success) {
      expect(result.data.vendor_id).toBeUndefined()
    }
  })
})

describe('Service Visit Schema (Refined)', () => {
  it('rejects inspection line item without inspection_result', () => {
    const result = serviceVisitSchemaRefined.safeParse({
      date: '2024-06-15',
      line_items: [
        {
          description: 'Brake inspection',
          is_inspection: true,
          // missing inspection_result
        },
      ],
    })
    expect(result.success).toBe(false)
  })

  it('accepts inspection line item with inspection_result', () => {
    const result = serviceVisitSchemaRefined.safeParse({
      date: '2024-06-15',
      line_items: [
        {
          description: 'Brake inspection',
          is_inspection: true,
          inspection_result: 'passed',
        },
      ],
    })
    expect(result.success).toBe(true)
  })
})
