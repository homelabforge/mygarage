import { useQuery } from '@tanstack/react-query'
import api from '@/services/api'

interface OdometerListResponse {
  latest_odometer_km: number | string | null
}

/**
 * Fetch the latest odometer reading for a vehicle.
 * Returns the canonical km value (Decimal serialised as string is coerced
 * to number) or null if no records exist.
 */
export function useLatestMileage(vin: string) {
  return useQuery({
    queryKey: ['latestMileage', vin],
    queryFn: async () => {
      const { data } = await api.get<OdometerListResponse>(
        `/vehicles/${vin}/odometer`,
        { params: { limit: 1 } },
      )
      const raw = data.latest_odometer_km
      if (raw == null) return null
      const num = typeof raw === 'string' ? parseFloat(raw) : raw
      return isNaN(num) ? null : num
    },
    enabled: !!vin,
    staleTime: 60_000,
  })
}
