/**
 * Pull the imperial gallon standard (US/UK) from settings into the store.
 *
 * The store already initialised itself synchronously from localStorage, so this
 * only reconciles it with the server. It reads /settings/public rather than
 * /settings: the latter is admin-only, so every non-admin took a 403 here and
 * silently stayed on US gallons while the admin had configured UK, showing
 * every volume and MPG about 20 percent wrong.
 */

import { useEffect } from 'react'
import api from '@/services/api'
import type { GallonStandard } from '@/utils/units'
import { setGallonStandard } from '@/utils/gallonStandardStore'

export function useGallonStandardSync() {
  useEffect(() => {
    let cancelled = false

    const sync = async () => {
      try {
        const response = await api.get('/settings/public')
        const settings: Array<{ key: string; value?: string | null }> = response.data?.settings || []
        const row = settings.find((s) => s.key === 'imperial_gallon_standard')
        const standard: GallonStandard = row?.value === 'uk' ? 'uk' : 'us'
        if (cancelled) return
        setGallonStandard(standard)
      } catch {
        // Keep whatever the store loaded from localStorage; a failed reconcile
        // must not reset a user who is correctly on UK.
      }
    }

    void sync()
    return () => {
      cancelled = true
    }
  }, [])
}
