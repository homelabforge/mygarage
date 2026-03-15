import { describe, it, expect } from 'vitest'
import { addressBookSchema } from '../addressBook'

describe('Address Book Schema', () => {
  const validEntry = {
    business_name: 'Joe\'s Auto Repair',
  }

  it('validates valid entry with required fields only', () => {
    const result = addressBookSchema.safeParse(validEntry)
    expect(result.success).toBe(true)
  })

  it('validates entry with all optional fields', () => {
    const result = addressBookSchema.safeParse({
      ...validEntry,
      name: 'Joe Smith',
      email: 'joe@example.com',
      phone: '555-123-4567',
      website: 'https://joesauto.com',
      address: '123 Main St',
      city: 'Houston',
      state: 'TX',
      zip_code: '77001',
      category: 'Service',
      notes: 'Specializes in Ford trucks',
    })
    expect(result.success).toBe(true)
  })

  it('requires business_name', () => {
    const result = addressBookSchema.safeParse({})
    expect(result.success).toBe(false)
  })

  it('rejects business_name over 150 characters', () => {
    const result = addressBookSchema.safeParse({
      business_name: 'A'.repeat(151),
    })
    expect(result.success).toBe(false)
  })

  it('rejects invalid email', () => {
    const result = addressBookSchema.safeParse({
      ...validEntry,
      email: 'not-an-email',
    })
    expect(result.success).toBe(false)
  })

  it('allows empty string email', () => {
    const result = addressBookSchema.safeParse({
      ...validEntry,
      email: '',
    })
    expect(result.success).toBe(true)
  })

  it('rejects invalid URL for website', () => {
    const result = addressBookSchema.safeParse({
      ...validEntry,
      website: 'not-a-url',
    })
    expect(result.success).toBe(false)
  })

  it('allows empty string website', () => {
    const result = addressBookSchema.safeParse({
      ...validEntry,
      website: '',
    })
    expect(result.success).toBe(true)
  })

  it('rejects state over 2 characters', () => {
    const result = addressBookSchema.safeParse({
      ...validEntry,
      state: 'Texas',
    })
    expect(result.success).toBe(false)
  })
})
