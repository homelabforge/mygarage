import { useQuery } from '@tanstack/react-query'
import api from '@/services/api'

interface OdometerListResponse {
  latest_mileage: number | null
}

/**
 * Fetch the latest odometer reading for a vehicle.
 * Returns the mileage number or null if no records exist.
 */
export function useLatestMileage(vin: string) {
  return useQuery({
    queryKey: ['latestMileage', vin],
    queryFn: async () => {
      const { data } = await api.get<OdometerListResponse>(
        `/vehicles/${vin}/odometer`,
        { params: { limit: 1 } },
      )
      return data.latest_mileage
    },
    enabled: !!vin,
    staleTime: 60_000,
  })
}
