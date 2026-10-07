/**
 * Save one of this person's display preferences: to the account when signed
 * in (`PUT /auth/me`, then reload the user so every reader moves), or to this
 * browser when there is no account (auth mode none).
 *
 * The browser write is announced with a `storage` event, since the real one
 * only reaches OTHER tabs and readers such as `useTimeFormat` listen for it. It
 * carries what a real one does: the key keeps unrelated listeners (the
 * unit-preference store) from re-reading on every change, and without the new
 * value and storage area a storage-syncing listener (TanStack Query Devtools)
 * reads it as a removal and deletes the value just written.
 */

import { useCallback } from 'react'
import { useAuth } from '@/contexts/AuthContext'
import api from '@/services/api'

/** The `PUT /auth/me` fields a display preference is saved as. */
export type PersonalPreferenceField =
  | 'time_format'
  | 'language'
  | 'currency_code'
  | 'dashboard_sort'
  | 'country'
  | 'inspection_auto_schedule'

export function useSavePersonalPreference(): (
  field: PersonalPreferenceField,
  value: string,
  storageKey: string
) => Promise<void> {
  const { isAuthenticated, refreshUser } = useAuth()
  return useCallback(
    async (field: PersonalPreferenceField, value: string, storageKey: string): Promise<void> => {
      if (isAuthenticated) {
        await api.put('/auth/me', { [field]: value })
        await refreshUser()
        return
      }
      localStorage.setItem(storageKey, value)
      window.dispatchEvent(
        new StorageEvent('storage', { key: storageKey, newValue: value, storageArea: localStorage })
      )
    },
    [isAuthenticated, refreshUser]
  )
}
