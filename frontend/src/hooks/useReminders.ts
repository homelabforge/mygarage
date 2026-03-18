/**
 * React Query hooks for vehicle reminders
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { reminderService } from '../services/reminderService'
import type { ReminderCreate, ReminderUpdate } from '../types/reminder'

export function useReminders(vin: string, status?: string) {
  return useQuery({
    queryKey: ['reminders', vin, status],
    queryFn: () => reminderService.list(vin, status),
    enabled: !!vin,
  })
}

export function useCreateReminder(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: ReminderCreate) => reminderService.create(vin, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reminders', vin] })
    },
  })
}

export function useUpdateReminder(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...payload }: ReminderUpdate & { id: number }) =>
      reminderService.update(vin, id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reminders', vin] })
    },
  })
}

export function useDeleteReminder(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => reminderService.remove(vin, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reminders', vin] })
    },
  })
}

export function useMarkReminderDone(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => reminderService.markDone(vin, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reminders', vin] })
    },
  })
}

export function useMarkReminderDismissed(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => reminderService.dismiss(vin, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reminders', vin] })
    },
  })
}
