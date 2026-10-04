import { useQuery } from '@tanstack/react-query'
import vehicleService from '@/services/vehicleService'

/**
 * The hero and key-facts read-aggregation for one vehicle (`/detail-stats`).
 *
 * A query rather than page state, so any write that moves these numbers can
 * refresh them by key, `['vehicleDetailStats', vin]` (#192): the reminder,
 * service-visit and tire invalidation helpers, and every reading write.
 */
export function useVehicleDetailStats(vin: string) {
  return useQuery({
    queryKey: ['vehicleDetailStats', vin],
    queryFn: () => vehicleService.getDetailStats(vin),
    enabled: !!vin,
  })
}
