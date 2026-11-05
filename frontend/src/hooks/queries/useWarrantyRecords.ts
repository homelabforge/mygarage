import { useQuery, useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type { WarrantyRecord, WarrantyRecordCreate, WarrantyRecordUpdate } from '@/types/warranty'

/** Visit items show their warranty, and a deleted warranty drops off its item. */
function invalidateWarrantyWrite(queryClient: QueryClient, vin: string): void {
  void queryClient.invalidateQueries({ queryKey: ['warranties', vin] })
  void queryClient.invalidateQueries({ queryKey: ['serviceVisits', vin] })
}

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

export function useCreateWarrantyRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: WarrantyRecordCreate) => {
      const { data } = await api.post(`/vehicles/${vin}/warranties`, payload)
      return data
    },
    onSuccess: () => invalidateWarrantyWrite(queryClient, vin),
  })
}

export function useUpdateWarrantyRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }: WarrantyRecordUpdate & { id: number }) => {
      const { data } = await api.put(`/vehicles/${vin}/warranties/${id}`, payload)
      return data
    },
    onSuccess: () => invalidateWarrantyWrite(queryClient, vin),
  })
}

export function useDeleteWarrantyRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (recordId: number) => {
      await api.delete(`/vehicles/${vin}/warranties/${recordId}`)
    },
    onSuccess: () => invalidateWarrantyWrite(queryClient, vin),
  })
}
