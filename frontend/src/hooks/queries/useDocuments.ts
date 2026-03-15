import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type { DocumentListResponse } from '@/types/document'

export function useDocuments(vin: string) {
  return useQuery({
    queryKey: ['documents', vin],
    queryFn: async () => {
      const { data } = await api.get<DocumentListResponse>(
        `/vehicles/${vin}/documents`
      )
      return data
    },
    enabled: !!vin,
  })
}

export function useUploadDocument(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (formData: FormData) => {
      const { data } = await api.post(`/vehicles/${vin}/documents`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents', vin] })
    },
  })
}

export function useDeleteDocument(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (documentId: number) => {
      await api.delete(`/vehicles/${vin}/documents/${documentId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents', vin] })
    },
  })
}
