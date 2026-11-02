import { useQuery } from '@tanstack/react-query'
import api from '@/services/api'
import type { components } from '@/types/api.generated'

export type FuelPricesResponse = components['schemas']['FuelPricesResponse']
export type StationPrices = components['schemas']['StationPricesResponse']
export type FuelPrice = components['schemas']['FuelPriceResponse']

/** The source republishes about every ten minutes; the backend caches as long. */
const PRICES_STALE_TIME = 5 * 60_000

/**
 * The pump prices reported at (and right around) a saved station (#211),
 * from the provider the country profile names. Asked only once a station
 * with coordinates is linked and the profile names a source: the answer
 * has `provider: null` when nothing applies, which the hint reads as
 * « nothing to show », never as an error.
 */
export function useFuelPrices(
  stationId: number | null | undefined,
  country: string | null,
  enabled: boolean
) {
  return useQuery({
    queryKey: ['fuel-prices', 'station', stationId ?? null, country],
    queryFn: async (): Promise<FuelPricesResponse> => {
      const { data } = await api.get<FuelPricesResponse>(`/address-book/${stationId}/fuel-prices`, {
        params: country ? { country } : undefined,
      })
      return data
    },
    enabled: enabled && !!stationId,
    staleTime: PRICES_STALE_TIME,
    retry: false,
  })
}
