/**
 * The offline copy of a vehicle's analytics that the Analytics page falls back
 * to when the network is down.
 *
 * Kept per account as well as per vehicle. A VIN-only key let the next account
 * on the same browser read the last one's analytics offline, even for a vehicle
 * the server would never show it. Logout clears every copy, and the old
 * VIN-only keys are never read. Every access is guarded: storage throws in a
 * private window or with site data blocked.
 */

import type { VehicleAnalytics } from '../types/analytics'

const PREFIX = 'analytics-cache-'

/** Whose copy this is: the user's id, `local` with sign-in off, null while nobody's known. */
export type AnalyticsCacheOwner = string | null

/**
 * The owner for the signed-in account.
 *
 * @param authMode The auth mode the app loaded (`none` means sign-in is off).
 * @param userId The signed-in user's id, if one has loaded.
 * @returns The owner, or null when there's no account to file a copy under.
 */
export function analyticsCacheOwner(authMode: string, userId: number | null | undefined): AnalyticsCacheOwner {
  if (authMode === 'none') return 'local'
  return userId == null ? null : String(userId)
}

const keyFor = (owner: string, vin: string): string => `${PREFIX}${owner}-${vin}`

/**
 * Store `data` as the owner's offline copy for `vin`.
 *
 * @param owner From {@link analyticsCacheOwner}; null stores nothing.
 * @param vin The VIN as the route spells it.
 * @param data The analytics to remember.
 */
export function rememberAnalytics(owner: AnalyticsCacheOwner, vin: string, data: VehicleAnalytics): void {
  if (owner === null) return
  try {
    localStorage.setItem(keyFor(owner, vin), JSON.stringify({ timestamp: Date.now(), data }))
  } catch {
    // Quota exceeded on a small device: the cache is a convenience, and
    // failing to write it must not surface as a load error.
  }
}

/**
 * The owner's offline copy for `vin`, or null when there's none or it won't parse.
 *
 * @param owner From {@link analyticsCacheOwner}; null finds nothing.
 * @param vin The VIN as the route spells it.
 * @returns The cached analytics, or null.
 */
export function readCachedAnalytics(owner: AnalyticsCacheOwner, vin: string): VehicleAnalytics | null {
  if (owner === null) return null
  try {
    const raw = localStorage.getItem(keyFor(owner, vin))
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    const data = (parsed as { data?: unknown } | null)?.data
    return typeof data === 'object' && data !== null ? (data as VehicleAnalytics) : null
  } catch {
    // Unreadable or junk: the error panel is a better answer than a crash.
    return null
  }
}

/** Drop every offline analytics copy, any account's and the old VIN-only ones. */
export function forgetAllAnalytics(): void {
  try {
    const keys: string[] = []
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (key?.startsWith(PREFIX)) keys.push(key)
    }
    keys.forEach((key) => localStorage.removeItem(key))
  } catch {
    // Storage we can't reach holds nothing we could leak.
  }
}
