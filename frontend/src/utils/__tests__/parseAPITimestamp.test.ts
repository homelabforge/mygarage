import { describe, expect, it } from 'vitest'
import {
  formatAPITimestamp,
  parseAPITimestamp,
  parseAPITimestampMs,
} from '../parseAPITimestamp'

describe('parseAPITimestamp', () => {
  it('returns null for null / undefined / empty', () => {
    expect(parseAPITimestamp(null)).toBeNull()
    expect(parseAPITimestamp(undefined)).toBeNull()
    expect(parseAPITimestamp('')).toBeNull()
  })

  it('returns null for unparseable input', () => {
    expect(parseAPITimestamp('not a date')).toBeNull()
    expect(parseAPITimestamp('2026-13-45')).toBeNull()
  })

  it('treats tz-less string as UTC', () => {
    const d = parseAPITimestamp('2026-04-19T14:30:00')
    expect(d).not.toBeNull()
    expect(d!.toISOString()).toBe('2026-04-19T14:30:00.000Z')
  })

  it('preserves Z suffix', () => {
    const d = parseAPITimestamp('2026-04-19T14:30:00Z')
    expect(d!.toISOString()).toBe('2026-04-19T14:30:00.000Z')
  })

  it('preserves lowercase z suffix', () => {
    const d = parseAPITimestamp('2026-04-19T14:30:00z')
    expect(d!.toISOString()).toBe('2026-04-19T14:30:00.000Z')
  })

  it('preserves +00:00 offset', () => {
    const d = parseAPITimestamp('2026-04-19T14:30:00+00:00')
    expect(d!.toISOString()).toBe('2026-04-19T14:30:00.000Z')
  })

  it('preserves non-UTC colon offset', () => {
    const d = parseAPITimestamp('2026-04-19T14:30:00-05:00')
    expect(d!.toISOString()).toBe('2026-04-19T19:30:00.000Z')
  })

  it('preserves compact offset +0530', () => {
    const d = parseAPITimestamp('2026-04-19T14:30:00+0530')
    expect(d!.toISOString()).toBe('2026-04-19T09:00:00.000Z')
  })

  it('returns null for bare-hour offset (ECMAScript Date cannot parse)', () => {
    // ISO 8601 allows -05 but ECMAScript Date constructor does not.
    // If the backend ever emits this form, add a normalization step.
    expect(parseAPITimestamp('2026-04-19T14:30:00-05')).toBeNull()
  })
})

describe('parseAPITimestampMs', () => {
  it('returns null for null/invalid', () => {
    expect(parseAPITimestampMs(null)).toBeNull()
    expect(parseAPITimestampMs('nope')).toBeNull()
  })

  it('returns epoch ms for valid input', () => {
    expect(parseAPITimestampMs('2026-04-19T14:30:00Z')).toBe(Date.UTC(2026, 3, 19, 14, 30, 0))
  })
})

describe('formatAPITimestamp', () => {
  it('returns fallback for null input', () => {
    expect(formatAPITimestamp(null, (d) => d.toISOString())).toBe('')
    expect(formatAPITimestamp(null, (d) => d.toISOString(), '—')).toBe('—')
  })

  it('applies the formatter for valid input', () => {
    expect(formatAPITimestamp('2026-04-19T14:30:00Z', (d) => d.toISOString())).toBe(
      '2026-04-19T14:30:00.000Z',
    )
  })
})
