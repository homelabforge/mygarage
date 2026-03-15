import { describe, it, expect } from 'vitest'
import { tollTagSchema, TOLL_SYSTEMS } from '../tollTag'

describe('Toll Tag Schema', () => {
  const validTag = {
    toll_system: 'EZ TAG' as const,
    tag_number: 'TAG-12345',
    status: 'active' as const,
  }

  it('validates valid toll tag', () => {
    const result = tollTagSchema.safeParse(validTag)
    expect(result.success).toBe(true)
  })

  it('requires toll_system to be a valid enum', () => {
    const result = tollTagSchema.safeParse({
      ...validTag,
      toll_system: 'InvalidSystem',
    })
    expect(result.success).toBe(false)
  })

  it('accepts all valid toll systems', () => {
    for (const system of TOLL_SYSTEMS) {
      const result = tollTagSchema.safeParse({ ...validTag, toll_system: system })
      expect(result.success).toBe(true)
    }
  })

  it('requires tag_number', () => {
    const result = tollTagSchema.safeParse({
      toll_system: 'EZ TAG',
      status: 'active',
    })
    expect(result.success).toBe(false)
  })

  it('rejects tag_number over 50 characters', () => {
    const result = tollTagSchema.safeParse({
      ...validTag,
      tag_number: 'A'.repeat(51),
    })
    expect(result.success).toBe(false)
  })

  it('requires status to be active or inactive', () => {
    const result = tollTagSchema.safeParse({
      ...validTag,
      status: 'suspended',
    })
    expect(result.success).toBe(false)
  })
})
