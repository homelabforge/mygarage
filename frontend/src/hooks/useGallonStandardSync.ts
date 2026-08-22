/**
 * Sync imperial gallon standard (US/UK) from settings into localStorage + UnitConverter.
 */

import { useEffect } from 'react'
import api from '@/services/api'
import { UnitConverter, type GallonStandard } from '@/utils/units'

export function useGallonStandardSync() {
  useEffect(() => {
    let cancelled = false

    const sync = async () => {
      try {
        const response = await api.get('/settings')
        const settings: Array<{ key: string; value?: string | null }> = response.data?.settings || []
        const row = settings.find((s) => s.key === 'imperial_gallon_standard')
        const standard: GallonStandard = row?.value === 'uk' ? 'uk' : 'us'
        if (cancelled) return
        localStorage.setItem('imperial_gallon_standard', standard)
        UnitConverter.setGallonStandard(standard)
      } catch {
        const stored = localStorage.getItem('imperial_gallon_standard') === 'uk' ? 'uk' : 'us'
        UnitConverter.setGallonStandard(stored)
      }
    }

    void sync()
    return () => {
      cancelled = true
    }
  }, [])
}
