import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type { RecallListResponse, RecallCreate, RecallUpdate } from '@/types/recall'

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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recalls', vin] })
    },
  })
}

export function useUpdateRecallRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }: RecallUpdate & { id: number }) => {
      const { data } = await api.put(`/vehicles/${vin}/recalls/${id}`, payload)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recalls', vin] })
    },
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

export function useCheckNHTSA(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      await api.post(`/vehicles/${vin}/recalls/check-nhtsa`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recalls', vin] })
    },
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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recalls', vin] })
    },
  })
}
