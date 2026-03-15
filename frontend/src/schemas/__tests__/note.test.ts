import { describe, it, expect } from 'vitest'
import { noteSchema } from '../note'

describe('Note Schema', () => {
  const validNote = {
    date: '2024-05-20',
    content: 'Noticed a squeak in the front right suspension.',
  }

  it('validates valid note with required fields', () => {
    const result = noteSchema.safeParse(validNote)
    expect(result.success).toBe(true)
  })

  it('validates note with optional title', () => {
    const result = noteSchema.safeParse({
      ...validNote,
      title: 'Suspension Noise',
    })
    expect(result.success).toBe(true)
  })

  it('requires content', () => {
    const result = noteSchema.safeParse({ date: '2024-05-20' })
    expect(result.success).toBe(false)
  })

  it('requires date in YYYY-MM-DD format', () => {
    const result = noteSchema.safeParse({
      ...validNote,
      date: '05/20/2024',
    })
    expect(result.success).toBe(false)
  })

  it('rejects title over 100 characters', () => {
    const result = noteSchema.safeParse({
      ...validNote,
      title: 'A'.repeat(101),
    })
    expect(result.success).toBe(false)
  })

  it('rejects content over 10000 characters', () => {
    const result = noteSchema.safeParse({
      ...validNote,
      content: 'A'.repeat(10001),
    })
    expect(result.success).toBe(false)
  })
})
