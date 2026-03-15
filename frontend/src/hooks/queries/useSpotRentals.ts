import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type { SpotRental } from '@/types/spotRental'

interface SpotRentalListResponse {
  spot_rentals: SpotRental[]
  total: number
}

export function useSpotRentals(vin: string) {
  return useQuery({
    queryKey: ['spotRentals', vin],
    queryFn: async () => {
      const { data } = await api.get<SpotRentalListResponse>(
        `/vehicles/${vin}/spot-rentals`
      )
      return data
    },
    enabled: !!vin,
  })
}

export function useDeleteSpotRental(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (rentalId: number) => {
      await api.delete(`/vehicles/${vin}/spot-rentals/${rentalId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['spotRentals', vin] })
    },
  })
}
