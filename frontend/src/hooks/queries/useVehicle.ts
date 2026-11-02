import { useQuery } from '@tanstack/react-query'
import vehicleService from '@/services/vehicleService'
import type { Vehicle } from '@/types/vehicle'

/** The query key of one vehicle's row; the detail page writes it after a save. */
export const vehicleQueryKey = (vin: string | null | undefined) => ['vehicle', vin ?? null] as const

/**
 * One vehicle's row through the shared query cache, so a form that only needs
 * a field of it (the registration country) does not fetch it again.
 */
export function useVehicle(vin: string | null | undefined) {
  return useQuery<Vehicle>({
    queryKey: vehicleQueryKey(vin),
    queryFn: () => vehicleService.get(vin as string),
    enabled: !!vin,
    staleTime: 60_000,
  })
}
