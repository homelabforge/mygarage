import { useQuery } from '@tanstack/react-query'
import api from '../../services/api'

export interface QuickEntryVehicle {
  vin: string
  nickname: string
  year: number | null
  make: string | null
  model: string | null
  vehicle_type: string
  thumbnail_url: string | null
}

interface QuickEntryVehicleListResponse {
  vehicles: QuickEntryVehicle[]
}

/**
 * Writable, non-archived vehicles for the Quick Entry page.
 *
 * Uses the shared QueryClient defaults (retry + refetchOnWindowFocus), so a
 * transient failure right after a cold launch recovers on its own instead of
 * dead-ending — the failure mode behind #114.
 */
export function useQuickEntryVehicles() {
  return useQuery({
    queryKey: ['quickEntryVehicles'],
    queryFn: async (): Promise<QuickEntryVehicle[]> => {
      const { data } = await api.get<QuickEntryVehicleListResponse>('/quick-entry/vehicles')
      return data.vehicles
    },
  })
}
