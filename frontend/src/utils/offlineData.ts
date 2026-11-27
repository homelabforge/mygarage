/**
 * The offline copies of account data this browser keeps, and whose they are.
 *
 * Pages stash server data in localStorage for offline use, and the service
 * worker keeps `/api/` responses. None of that is filed per account, so it all
 * belongs to whoever the owner marker names. Logout drops it, and a different
 * account (or an unmarked leftover from an older build) drops it before the
 * user is set. Preferences like theme and units aren't account data and stay.
 */

import type { AnalyticsCacheOwner } from './analyticsCache'

// Every localStorage copy of server data. analyticsCache.ts writes the first
// two, vehicleCache.ts the third, PhotoGallery the last.
const COPY_PREFIXES = ['analytics-cache-', 'garage-analytics-cache', 'vehicle-cache-', 'photos-cache-'] as const

// sw.js names its runtime cache this plus a version. Its static cache holds
// only the app shell, so it stays.
const RUNTIME_CACHE_PREFIX = 'mygarage-runtime-'

const OWNER_KEY = 'offline-data-owner'

function readOwner(): string | null {
  try {
    return localStorage.getItem(OWNER_KEY)
  } catch {
    // Can't tell whose it is, so treat it as nobody's.
    return null
  }
}

function forgetStoredCopies(): void {
  const doomed: string[] = []
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (key !== null && COPY_PREFIXES.some((prefix) => key.startsWith(prefix))) doomed.push(key)
    }
  } catch {
    // Storage we can't read is storage we can't leak from. Still drop
    // whatever we found before it threw.
  }
  for (const key of doomed) {
    try {
      localStorage.removeItem(key)
    } catch {
      // Keep going, one stuck key shouldn't save the rest.
    }
  }
}

async function forgetCachedResponses(): Promise<void> {
  try {
    // Not there in an insecure context or an old browser.
    if (typeof caches === 'undefined') return
    const names = (await caches.keys()).filter((name) => name.startsWith(RUNTIME_CACHE_PREFIX))
    await Promise.all(
      names.map(async (name) => {
        try {
          const cache = await caches.open(name)
          const requests = await cache.keys()
          const api = requests.filter((request) => new URL(request.url).pathname.includes('/api/'))
          await Promise.all(api.map((request) => cache.delete(request)))
        } catch {
          // One cache we can't open shouldn't stop the others.
        }
      }),
    )
  } catch {
    // Same as above, nothing to report from a logout.
  }
}

/**
 * Drop every offline copy of account data: the localStorage copies first, in
 * one synchronous pass, then the service worker's `/api/` responses. Never throws.
 */
export async function forgetOfflineData(): Promise<void> {
  // Before any await, so a tab closed mid-logout still loses them.
  forgetStoredCopies()
  await forgetCachedResponses()
}

/**
 * File the offline copies under `owner`, dropping them first if someone else
 * (or nobody we know of) left them. Run it before the user gets set.
 *
 * @param owner From `analyticsCacheOwner`; null does nothing.
 */
export async function claimOfflineData(owner: AnalyticsCacheOwner): Promise<void> {
  if (owner === null) return
  if (readOwner() !== owner) await forgetOfflineData()
  try {
    localStorage.setItem(OWNER_KEY, owner)
  } catch {
    // No marker means the next claim wipes again, which is the safe side.
  }
}

/** Forget whose the copies are, so the next sign-in wipes whatever's left. */
export function releaseOfflineData(): void {
  try {
    localStorage.removeItem(OWNER_KEY)
  } catch {
    // Nothing stored, nothing to release.
  }
}
