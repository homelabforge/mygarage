import { useQuery } from '@tanstack/react-query'
import api from '@/services/api'
import type { VehicleCompliance } from '@/types/compliance'

/**
 * What the vehicle's country asks of it (#211): the low-emission-zone class,
 * the next periodic inspection, the Euro class. Read-only and cheap; it is
 * refetched when the vehicle or its reminders change (the callers invalidate
 * `['vehicle-compliance', vin]`).
 */
export function useVehicleCompliance(vin: string | null | undefined) {
  return useQuery({
    queryKey: ['vehicle-compliance', vin ?? null],
    queryFn: async () => {
      const { data } = await api.get<VehicleCompliance>(`/vehicles/${vin}/compliance`)
      return data
    },
    enabled: !!vin,
  })
}
