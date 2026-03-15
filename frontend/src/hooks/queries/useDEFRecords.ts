import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type { DEFRecordListResponse, DEFAnalytics, DEFRecordCreate, DEFRecordUpdate } from '@/types/def'

export function useDEFRecords(vin: string) {
  return useQuery({
    queryKey: ['defRecords', vin],
    queryFn: async () => {
      const { data } = await api.get<DEFRecordListResponse>(
        `/vehicles/${vin}/def`
      )
      return data
    },
    enabled: !!vin,
  })
}

export function useDEFAnalytics(vin: string) {
  return useQuery({
    queryKey: ['defAnalytics', vin],
    queryFn: async () => {
      const { data } = await api.get<DEFAnalytics>(
        `/vehicles/${vin}/def/analytics`
      )
      return data
    },
    enabled: !!vin,
  })
}

export function useCreateDEFRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: DEFRecordCreate) => {
      const { data } = await api.post(`/vehicles/${vin}/def`, payload)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['defRecords', vin] })
      queryClient.invalidateQueries({ queryKey: ['defAnalytics', vin] })
    },
  })
}

export function useUpdateDEFRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }: DEFRecordUpdate & { id: number }) => {
      const { data } = await api.put(`/vehicles/${vin}/def/${id}`, payload)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['defRecords', vin] })
      queryClient.invalidateQueries({ queryKey: ['defAnalytics', vin] })
    },
  })
}

export function useDeleteDEFRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (recordId: number) => {
      await api.delete(`/vehicles/${vin}/def/${recordId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['defRecords', vin] })
      queryClient.invalidateQueries({ queryKey: ['defAnalytics', vin] })
    },
  })
}
