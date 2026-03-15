import { describe, it, expect } from 'vitest'
import { recallSchema } from '../recall'

describe('Recall Schema', () => {
  const validRecall = {
    component: 'Fuel Pump',
    summary: 'Fuel pump may fail causing engine stall without warning.',
    is_resolved: false,
  }

  it('validates valid recall with required fields', () => {
    const result = recallSchema.safeParse(validRecall)
    expect(result.success).toBe(true)
  })

  it('validates recall with all optional fields', () => {
    const result = recallSchema.safeParse({
      ...validRecall,
      nhtsa_campaign_number: '24V-123',
      consequence: 'Engine stall increases risk of crash.',
      remedy: 'Dealers will replace fuel pump free of charge.',
      date_announced: '2024-02-10',
      notes: 'Parts on backorder until March 2024',
    })
    expect(result.success).toBe(true)
  })

  it('requires component', () => {
    const { component: _component, ...missing } = validRecall
    const result = recallSchema.safeParse(missing)
    expect(result.success).toBe(false)
  })

  it('requires summary', () => {
    const { summary: _summary, ...missing } = validRecall
    const result = recallSchema.safeParse(missing)
    expect(result.success).toBe(false)
  })

  it('requires is_resolved boolean', () => {
    const { is_resolved: _is_resolved, ...missing } = validRecall
    const result = recallSchema.safeParse(missing)
    expect(result.success).toBe(false)
  })

  it('rejects component over 200 characters', () => {
    const result = recallSchema.safeParse({
      ...validRecall,
      component: 'A'.repeat(201),
    })
    expect(result.success).toBe(false)
  })

  it('rejects summary over 2000 characters', () => {
    const result = recallSchema.safeParse({
      ...validRecall,
      summary: 'A'.repeat(2001),
    })
    expect(result.success).toBe(false)
  })

  it('rejects invalid date_announced format', () => {
    const result = recallSchema.safeParse({
      ...validRecall,
      date_announced: 'February 10, 2024',
    })
    expect(result.success).toBe(false)
  })
})
