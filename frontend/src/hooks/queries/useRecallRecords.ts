import { useQuery, useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type { RecallListResponse, RecallCheckResponse, RecallCreate, RecallUpdate } from '@/types/recall'

/** Visit items show their recall's campaign, and a deleted recall drops off its item. */
function invalidateRecallWrite(queryClient: QueryClient, vin: string): void {
  void queryClient.invalidateQueries({ queryKey: ['recalls', vin] })
  void queryClient.invalidateQueries({ queryKey: ['serviceVisits', vin] })
}

export function useRecallRecords(vin: string, statusFilter: 'all' | 'active' | 'resolved' = 'all') {
  return useQuery({
    queryKey: ['recalls', vin, statusFilter],
    queryFn: async () => {
      const params = statusFilter !== 'all' ? `?status=${statusFilter}` : ''
      const { data } = await api.get<RecallListResponse>(
        `/vehicles/${vin}/recalls${params}`
      )
      return data
    },
    enabled: !!vin,
  })
}

export function useCreateRecallRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: RecallCreate) => {
      const { data } = await api.post(`/vehicles/${vin}/recalls`, payload)
      return data
    },
    onSuccess: () => invalidateRecallWrite(queryClient, vin),
  })
}

export function useUpdateRecallRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }: RecallUpdate & { id: number }) => {
      const { data } = await api.put(`/vehicles/${vin}/recalls/${id}`, payload)
      return data
    },
    onSuccess: () => invalidateRecallWrite(queryClient, vin),
  })
}

export function useDeleteRecallRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (recordId: number) => {
      await api.delete(`/vehicles/${vin}/recalls/${recordId}`)
    },
    onSuccess: () => invalidateRecallWrite(queryClient, vin),
  })
}

export function useCheckNHTSA(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      await api.post(`/vehicles/${vin}/recalls/check-nhtsa`)
    },
    onSuccess: () => invalidateRecallWrite(queryClient, vin),
  })
}

/**
 * Every source that covers the vehicle's country (#211): NHTSA where no
 * country profile says otherwise, RappelConso in France. The answer names
 * the sources asked, how many recalls were new, and any source that failed.
 */
export function useCheckRecalls(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const { data } = await api.post<RecallCheckResponse>(`/vehicles/${vin}/recalls/check`)
      return data
    },
    onSuccess: () => invalidateRecallWrite(queryClient, vin),
  })
}

export function useToggleRecallResolved(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ recallId, isResolved }: { recallId: number; isResolved: boolean }) => {
      await api.put(`/vehicles/${vin}/recalls/${recallId}`, {
        is_resolved: isResolved,
      })
    },
    onSuccess: () => invalidateRecallWrite(queryClient, vin),
  })
}
