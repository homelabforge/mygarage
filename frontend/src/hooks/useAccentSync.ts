/**
 * Applies the authenticated user's saved UI accent to the AccentContext.
 *
 * The server→client half of per-account accent persistence (the write half
 * lives in the picker, which PUTs /auth/me then refreshUser()). Precedence
 * mirrors useLanguageSync: the DB preference wins over the localStorage seed
 * AccentProvider starts from.
 *
 * Deliberately depends ONLY on `user.accent_color`, not on the current
 * `accent`: it re-applies when the DB value changes (login, refreshUser) and
 * stays quiet while the user is clicking swatches locally — so it never fights
 * a fresh selection during the window before refreshUser() lands. Applying the
 * same value twice is a no-op (setAccent is idempotent).
 *
 * Mount under both AccentProvider and AuthProvider (see App.tsx).
 */
import { useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { useAccent } from '../contexts/AccentContext'
import { ACCENT_KEYS, type AccentKey } from '../constants/accents'

export function useAccentSync(): void {
  const { user } = useAuth()
  const { setAccent } = useAccent()

  useEffect(() => {
    const dbAccent = user?.accent_color
    if (dbAccent && ACCENT_KEYS.includes(dbAccent as AccentKey)) {
      setAccent(dbAccent as AccentKey)
    }
  }, [user?.accent_color, setAccent])
}
