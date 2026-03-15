import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type { NoteListResponse } from '@/types/note'

export function useNotes(vin: string) {
  return useQuery({
    queryKey: ['notes', vin],
    queryFn: async () => {
      const { data } = await api.get<NoteListResponse>(
        `/vehicles/${vin}/notes`
      )
      return data
    },
    enabled: !!vin,
  })
}

export function useDeleteNote(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (noteId: number) => {
      await api.delete(`/vehicles/${vin}/notes/${noteId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notes', vin] })
    },
  })
}
