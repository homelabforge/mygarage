/**
 * Hook to access the user's date-format preference (day-first or month-first).
 *
 * Read through `usePersonalPreference`: the account's value when signed in,
 * else this browser's copy, else 'mdy' (the order English dates have always
 * used in the app).
 */

import type { DateFormat } from '@/constants/i18n'
import { usePersonalPreference } from './usePersonalPreference'

export type { DateFormat }

/**
 * Narrow an unvalidated date-format string.
 *
 * `users.date_format` is a plain VARCHAR, so the generated schema types it as
 * `string`. Anything that is not exactly 'dmy' is month-first, the default.
 *
 * @param value A stored or transmitted preference, possibly absent.
 * @returns The narrowed preference.
 */
export function asDateFormat(value: string | null | undefined): DateFormat {
  return value === 'dmy' ? 'dmy' : 'mdy'
}

/**
 * Get the user's date-format preference from AuthContext or localStorage.
 *
 * @returns Object containing dateFormat ('mdy' | 'dmy')
 */
export function useDateFormat(): { dateFormat: DateFormat } {
  return { dateFormat: usePersonalPreference('date_format', 'date_format', asDateFormat) }
}
