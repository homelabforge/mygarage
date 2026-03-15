import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type { RecallListResponse } from '@/types/recall'

export function useRecallRecords(vin: string) {
  return useQuery({
    queryKey: ['recalls', vin],
    queryFn: async () => {
      const { data } = await api.get<RecallListResponse>(
        `/vehicles/${vin}/recalls`
      )
      return data
    },
    enabled: !!vin,
  })
}

export function useDeleteRecallRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (recordId: number) => {
      await api.delete(`/vehicles/${vin}/recalls/${recordId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recalls', vin] })
    },
  })
}
