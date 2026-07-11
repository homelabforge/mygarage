/**
 * Parse a backend *timestamp* (datetime) string with defensive UTC handling.
 *
 * Use this ONLY for fields typed as `datetime` on the backend
 * (e.g. created_at, updated_at, last_used_at, first_seen, transferred_at).
 *
 * DO NOT use this for fields typed as `date` (YYYY-MM-DD) — those represent
 * calendar days, not instants. Use dateUtils.ts helpers instead.
 *
 * Background: MyGarage currently stores naive UTC datetimes and serializes
 * them without a timezone suffix. ECMAScript parses such strings as local
 * time, drifting by the user's UTC offset. Until the backend emits explicit
 * offsets, every frontend consumer of a datetime field MUST route strings
 * through this helper.
 *
 * Behavior:
 *   - null / undefined / empty / unparseable -> null
 *   - string already carries tz ('Z', '+00:00', '-0500') -> passed through
 *   - string lacks tz -> 'Z' appended (treated as UTC)
 *
 * Note: ECMAScript's Date constructor accepts `Z`, `±hhmm`, and `±hh:mm`,
 * but NOT bare `±hh`. The regex reflects that. ISO 8601 allows bare-hour
 * offsets; if a backend ever emits one we'll need to normalize before
 * parsing, but Python/Pydantic and every other mainstream serializer emit
 * one of the three forms Date accepts.
 */
export function parseAPITimestamp(value: string | null | undefined): Date | null {
  if (!value) return null
  const hasTz = /[Zz]$|[+-]\d{2}:?\d{2}$/.test(value)
  const d = new Date(hasTz ? value : value + 'Z')
  return Number.isNaN(d.getTime()) ? null : d
}

/**
 * Convenience wrapper: parse and return Unix milliseconds, or null.
 */
export function parseAPITimestampMs(value: string | null | undefined): number | null {
  const d = parseAPITimestamp(value)
  return d ? d.getTime() : null
}

/**
 * Convenience wrapper: parse and apply a formatter, with a fallback for null/invalid input.
 */
export function formatAPITimestamp(
  value: string | null | undefined,
  formatter: (d: Date) => string,
  fallback = '',
): string {
  const d = parseAPITimestamp(value)
  return d ? formatter(d) : fallback
}

type TimeFormatPref = '12h' | '24h'

/**
 * Normalize a timestamp input to a Date, or null.
 * Accepts an API datetime string (via parseAPITimestamp), epoch milliseconds
 * (e.g. a Recharts tooltip value), or a Date (e.g. a live `lastRefresh` clock).
 */
function toDate(value: string | number | Date | null | undefined): Date | null {
  if (value == null) return null
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
  if (typeof value === 'number') {
    const d = new Date(value)
    return Number.isNaN(d.getTime()) ? null : d
  }
  return parseAPITimestamp(value)
}

/**
 * Format the time-of-day, honoring the 12h/24h preference (e.g. "2:30 PM" vs
 * "14:30"). `seconds` includes a `:ss` component (preserve per call site).
 */
export function formatTime(
  value: string | number | Date | null | undefined,
  timeFormat: TimeFormatPref,
  opts: { seconds?: boolean } = {},
  fallback = '',
): string {
  const d = toDate(value)
  if (!d) return fallback
  return d.toLocaleTimeString(undefined, {
    hour: timeFormat === '12h' ? 'numeric' : '2-digit',
    minute: '2-digit',
    ...(opts.seconds ? { second: '2-digit' } : {}),
    hour12: timeFormat === '12h',
  })
}

/**
 * Format date + time-of-day, honoring the 12h/24h preference. Time component
 * uses the same rules as formatTime.
 */
export function formatDateTime(
  value: string | number | Date | null | undefined,
  timeFormat: TimeFormatPref,
  opts: { seconds?: boolean } = {},
  fallback = '',
): string {
  const d = toDate(value)
  if (!d) return fallback
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: timeFormat === '12h' ? 'numeric' : '2-digit',
    minute: '2-digit',
    ...(opts.seconds ? { second: '2-digit' } : {}),
    hour12: timeFormat === '12h',
  })
}
