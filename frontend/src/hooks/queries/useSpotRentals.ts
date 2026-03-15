import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type { SpotRental, SpotRentalCreate, SpotRentalUpdate, SpotRentalBillingCreate, SpotRentalBillingUpdate } from '@/types/spotRental'

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

export function useCreateSpotRental(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: SpotRentalCreate) => {
      const { data } = await api.post(`/vehicles/${vin}/spot-rentals`, payload)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['spotRentals', vin] })
    },
  })
}

export function useUpdateSpotRental(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }: SpotRentalUpdate & { id: number }) => {
      const { data } = await api.put(`/vehicles/${vin}/spot-rentals/${id}`, payload)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['spotRentals', vin] })
    },
  })
}

export function useCreateBillingEntry(vin: string, rentalId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: SpotRentalBillingCreate) => {
      const { data } = await api.post(`/vehicles/${vin}/spot-rentals/${rentalId}/billings`, payload)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['spotRentals', vin] })
    },
  })
}

export function useUpdateBillingEntry(vin: string, rentalId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }: SpotRentalBillingUpdate & { id: number }) => {
      const { data } = await api.put(`/vehicles/${vin}/spot-rentals/${rentalId}/billings/${id}`, payload)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['spotRentals', vin] })
    },
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
