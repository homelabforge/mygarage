import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type { TireCreate, TireListResponse, TireReadingCreate, Tire } from '@/types/tire'

export function useTires(vin: string) {
  return useQuery({
    queryKey: ['tires', vin],
    queryFn: async () => {
      const { data } = await api.get<TireListResponse>(`/vehicles/${vin}/tires`)
      return data
    },
    enabled: !!vin,
  })
}

export function useUpsertTire(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: TireCreate) => {
      const { data } = await api.post<Tire>(`/vehicles/${vin}/tires`, payload)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tires', vin] })
      queryClient.invalidateQueries({ queryKey: ['reminders', vin] })
    },
  })
}

export function useAddTireReading(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ tireId, ...payload }: TireReadingCreate & { tireId: number }) => {
      const { data } = await api.post<Tire>(
        `/vehicles/${vin}/tires/${tireId}/readings`,
        payload
      )
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tires', vin] })
      queryClient.invalidateQueries({ queryKey: ['reminders', vin] })
    },
  })
}

export function useDeleteTire(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (tireId: number) => {
      await api.delete(`/vehicles/${vin}/tires/${tireId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tires', vin] })
    },
  })
}
