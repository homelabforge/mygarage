/**
 * Read one of this person's display preferences: the account's value when
 * signed in, else this browser's copy (auth mode none), narrowed to a value the
 * app knows. The reading half of `useSavePersonalPreference`.
 *
 * Signed-in readers move when the save refreshes AuthContext. Browser-only
 * readers listen for the `storage` event the save fires, so an open page
 * follows a change made in Quick Settings. Another preference's event re-reads
 * an unchanged value, which renders nothing.
 */

import { useEffect, useState } from 'react'
import { useAuth } from '@/contexts/AuthContext'
import type { PersonalPreferenceField } from './useSavePersonalPreference'

type Narrow<T> = (value: string | null | undefined) => T

function readStored<T>(storageKey: string, narrow: Narrow<T>): T {
  try {
    return narrow(localStorage.getItem(storageKey))
  } catch {
    // Storage blocked (private window, site data off): the default it is.
    return narrow(null)
  }
}

/**
 * @param field The account field the preference is saved as.
 * @param storageKey Where it is kept in this browser when there is no account.
 * @param narrow Turns a stored or transmitted string into a known value.
 * @returns The preference in effect.
 */
export function usePersonalPreference<T>(
  field: PersonalPreferenceField,
  storageKey: string,
  narrow: Narrow<T>
): T {
  const { user, isAuthenticated } = useAuth()
  const [stored, setStored] = useState<T>(() => readStored(storageKey, narrow))

  useEffect(() => {
    const onStorage = (): void => setStored(readStored(storageKey, narrow))
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [storageKey, narrow])

  if (isAuthenticated && user) {
    // A boolean preference (inspection_auto_schedule) travels as 'true' /
    // 'false', the same shape localStorage hands back for it.
    const raw = user[field]
    return narrow(typeof raw === 'boolean' ? String(raw) : raw)
  }
  return stored
}
