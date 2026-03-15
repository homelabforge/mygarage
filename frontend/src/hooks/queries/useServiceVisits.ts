import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type { ServiceVisitListResponse } from '@/types/serviceVisit'

export function useServiceVisits(vin: string) {
  return useQuery({
    queryKey: ['serviceVisits', vin],
    queryFn: async () => {
      const { data } = await api.get<ServiceVisitListResponse>(
        `/vehicles/${vin}/service-visits`
      )
      return data
    },
    enabled: !!vin,
  })
}

export function useDeleteServiceVisit(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (visitId: number) => {
      await api.delete(`/vehicles/${vin}/service-visits/${visitId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['serviceVisits', vin] })
    },
  })
}
