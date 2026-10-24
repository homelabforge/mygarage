import { useEffect, useState } from 'react'
import api from '@/services/api'
import type { PublicSetting } from '@/utils/publicUnitDefaults'

/**
 * The `/settings/public` rows as a key-to-value map, fetched once per mount.
 *
 * Empty while the request is in flight and after it fails, so a caller reads
 * a missing key and gets its own fallback: `isSettingOn(values.x, true)` for a
 * switch the backend treats as on when unset. A failed fetch therefore never
 * hides an action the backend would allow; the backend's own check (a 409) is
 * the enforcement, and this only keeps the UI from offering what will fail.
 */
export function usePublicSettings(): Readonly<Record<string, string | null | undefined>> {
  const [values, setValues] = useState<Record<string, string | null | undefined>>({})

  useEffect(() => {
    let cancelled = false
    const load = async (): Promise<void> => {
      try {
        const response = await api.get<{ settings?: PublicSetting[] }>('/settings/public')
        const rows = response?.data?.settings
        if (cancelled || !Array.isArray(rows)) return
        setValues(Object.fromEntries(rows.map((row) => [row.key, row.value])))
      } catch {
        // Keep the empty map: every caller falls back to its own default.
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [])

  return values
}
