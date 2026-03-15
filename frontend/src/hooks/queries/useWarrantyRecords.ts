import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type { WarrantyRecord } from '@/types/warranty'

export function useWarrantyRecords(vin: string) {
  return useQuery({
    queryKey: ['warranties', vin],
    queryFn: async () => {
      const { data } = await api.get<WarrantyRecord[]>(
        `/vehicles/${vin}/warranties`
      )
      return data
    },
    enabled: !!vin,
  })
}

export function useDeleteWarrantyRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (recordId: number) => {
      await api.delete(`/vehicles/${vin}/warranties/${recordId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['warranties', vin] })
    },
  })
}
