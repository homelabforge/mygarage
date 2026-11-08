import { queryOptions, useQuery, type UseQueryResult } from '@tanstack/react-query'
import api from '@/services/api'
import type { PublicSetting } from '@/utils/publicUnitDefaults'

/** The `/settings/public` rows as a key-to-value map. */
export type PublicSettingValues = Readonly<Record<string, string | null | undefined>>

/** One GET of `/settings/public`, as rows (none when the payload has no list). Throws on failure. */
export async function fetchPublicSettingRows(): Promise<PublicSetting[]> {
  const response = await api.get<{ settings?: PublicSetting[] }>('/settings/public')
  const rows = response?.data?.settings
  return Array.isArray(rows) ? rows : []
}

/**
 * `/settings/public`, cached once for the whole app. AuthContext and every
 * reader below select from this one query, so a page with several readers
 * asks once, and a refresh anywhere (a save, a restore, a sign-in change)
 * reaches all of them.
 *
 * No retry: a failed read falls back at once, the same as before the cache.
 */
export const publicSettingsQuery = queryOptions({
  queryKey: ['settings', 'public'] as const,
  queryFn: fetchPublicSettingRows,
  // An admin's change refreshes it straight away (see Settings), so this only
  // covers another client's change.
  staleTime: 60_000,
  retry: false,
})

function toValues(rows: PublicSetting[]): PublicSettingValues {
  return Object.fromEntries(rows.map((row) => [row.key, row.value]))
}

const NO_VALUES: PublicSettingValues = Object.freeze({})

/**
 * The shared query with a `select`, for a reader that wants one derived value
 * (a flag) and the loading state. Keep `select` stable (module level), or it
 * re-runs on every render.
 */
export function usePublicSettingsQuery<T>(
  select: (rows: PublicSetting[]) => T,
  options: { enabled?: boolean } = {},
): UseQueryResult<T> {
  return useQuery({ ...publicSettingsQuery, select, enabled: options.enabled ?? true })
}

/**
 * The public settings as a key-to-value map.
 *
 * Empty while the request is in flight and after it fails, so a caller reads
 * a missing key and gets its own fallback: `isSettingOn(values.x, true)` for a
 * switch the backend treats as on when unset. A failed fetch therefore never
 * hides an action the backend would allow; the backend's own check (a 409) is
 * the enforcement, and this only keeps the UI from offering what will fail.
 *
 * `enabled: false` asks for nothing (a closed drawer that stays mounted).
 */
export function usePublicSettings(options: { enabled?: boolean } = {}): PublicSettingValues {
  return usePublicSettingsQuery(toValues, options).data ?? NO_VALUES
}
