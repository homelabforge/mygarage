import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type {
  TollTransactionListResponse,
  TollTagListResponse,
  TollTransactionSummary,
  TollTagCreate,
  TollTagUpdate,
  TollTransactionCreate,
  TollTransactionUpdate,
} from '@/types/toll'

export function useTollTransactions(vin: string) {
  return useQuery({
    queryKey: ['tollTransactions', vin],
    queryFn: async () => {
      const { data } = await api.get<TollTransactionListResponse>(
        `/vehicles/${vin}/toll-transactions`
      )
      return data
    },
    enabled: !!vin,
  })
}

export function useTollTransactionSummary(vin: string) {
  return useQuery({
    queryKey: ['tollTransactionSummary', vin],
    queryFn: async () => {
      const { data } = await api.get<TollTransactionSummary>(
        `/vehicles/${vin}/toll-transactions/summary/statistics`
      )
      return data
    },
    enabled: !!vin,
  })
}

export function useTollTags(vin: string) {
  return useQuery({
    queryKey: ['tollTags', vin],
    queryFn: async () => {
      const { data } = await api.get<TollTagListResponse>(
        `/vehicles/${vin}/toll-tags`
      )
      return data
    },
    enabled: !!vin,
  })
}

export function useCreateTollTag(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: TollTagCreate) => {
      const { data } = await api.post(`/vehicles/${vin}/toll-tags`, payload)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tollTags', vin] })
    },
  })
}

export function useUpdateTollTag(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }: TollTagUpdate & { id: number }) => {
      const { data } = await api.put(`/vehicles/${vin}/toll-tags/${id}`, payload)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tollTags', vin] })
    },
  })
}

export function useCreateTollTransaction(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: TollTransactionCreate) => {
      const { data } = await api.post(`/vehicles/${vin}/toll-transactions`, payload)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tollTransactions', vin] })
      queryClient.invalidateQueries({ queryKey: ['tollTransactionSummary', vin] })
    },
  })
}

export function useUpdateTollTransaction(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }: TollTransactionUpdate & { id: number }) => {
      const { data } = await api.put(`/vehicles/${vin}/toll-transactions/${id}`, payload)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tollTransactions', vin] })
      queryClient.invalidateQueries({ queryKey: ['tollTransactionSummary', vin] })
    },
  })
}

export function useDeleteTollTransaction(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (transactionId: number) => {
      await api.delete(`/vehicles/${vin}/toll-transactions/${transactionId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tollTransactions', vin] })
      queryClient.invalidateQueries({ queryKey: ['tollTransactionSummary', vin] })
    },
  })
}

export function useDeleteTollTag(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (tagId: number) => {
      await api.delete(`/vehicles/${vin}/toll-tags/${tagId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tollTags', vin] })
    },
  })
}
