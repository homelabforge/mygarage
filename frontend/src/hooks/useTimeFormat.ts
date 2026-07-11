/**
 * Hook to access the user's time-format preference (12-hour vs 24-hour clock).
 *
 * Mirrors useUnitPreference, but ALSO subscribes to the `storage` event so the
 * Settings toggle's `window.dispatchEvent(new Event('storage'))` re-renders
 * consumers live for unauthenticated users. (useUnitPreference only reads on
 * render, so its dispatched event is a no-op — this hook fixes that for time.)
 *
 * Authenticated users get reactivity from AuthContext instead: the Settings
 * handler calls refreshUser() after PUT /auth/me, updating user.time_format.
 *
 * Falls back to localStorage for unauthenticated users, or '12h' as the final
 * default (matches the app's US-leaning defaults, e.g. imperial units).
 */

import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'

export type TimeFormat = '12h' | '24h'

/** Read the persisted preference from localStorage, defaulting to 12h. */
function readStored(): TimeFormat {
  return localStorage.getItem('time_format') === '24h' ? '24h' : '12h'
}

/**
 * Get the user's time-format preference from AuthContext or localStorage.
 *
 * @returns Object containing timeFormat ('12h' | '24h')
 *
 * @example
 * const { timeFormat } = useTimeFormat()
 * const label = formatTime(session.started_at, timeFormat)
 */
export function useTimeFormat(): { timeFormat: TimeFormat } {
  const { user, isAuthenticated } = useAuth()
  const [stored, setStored] = useState<TimeFormat>(readStored)

  useEffect(() => {
    const onStorage = (): void => setStored(readStored())
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  if (isAuthenticated && user) {
    return { timeFormat: (user.time_format as TimeFormat) || '12h' }
  }
  return { timeFormat: stored }
}
