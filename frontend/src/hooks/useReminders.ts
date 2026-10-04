/**
 * React Query hooks for vehicle reminders and the maintenance lifecycle.
 *
 * A completion writes a service visit and a reading as well as reminders, so
 * the completion, pack and reconcile mutations invalidate the visit and
 * reading queries too; the visit mutations (`queries/useServiceVisits`)
 * invalidate reminders in return, since a typed service moves them.
 */

import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import {
  reminderService,
  type AnchorChoices,
  type IntervalOverrides,
} from '../services/reminderService'
import type {
  ReminderCompleteRequest,
  ReminderCreate,
  ReminderUpdate,
  SavePackBody,
} from '../types/reminder'

/** Every query a maintenance write can move. */
export function invalidateMaintenanceQueries(queryClient: QueryClient, vin: string): void {
  invalidateReadingViews(queryClient, vin)
  for (const key of ['reminderDuplicates', 'maintenanceRules', 'packPreview', 'serviceVisits']) {
    void queryClient.invalidateQueries({ queryKey: [key, vin] })
  }
}

/**
 * Everything a new or changed reading moves (#192): the reading lists and the
 * latest readings, each pending reminder's progress, chip and order, and the
 * hero's counts and latest reading. One set for every reading write, since the
 * server syncs odometer and hours rows from fuel, DEF, service and tire writes.
 */
export function invalidateReadingViews(queryClient: QueryClient, vin: string): void {
  for (const key of [
    'odometerRecords',
    'hoursRecords',
    'latestMileage',
    'latestHours',
    'reminders',
    'vehicleDetailStats',
  ]) {
    void queryClient.invalidateQueries({ queryKey: [key, vin] })
  }
}

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
    onSuccess: () => invalidateMaintenanceQueries(queryClient, vin),
  })
}

export function useUpdateReminder(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...payload }: ReminderUpdate & { id: number }) =>
      reminderService.update(vin, id, payload),
    onSuccess: () => invalidateMaintenanceQueries(queryClient, vin),
  })
}

export function useDeleteReminder(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => reminderService.remove(vin, id),
    onSuccess: () => invalidateMaintenanceQueries(queryClient, vin),
  })
}

export function useMarkReminderDone(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => reminderService.markDone(vin, id),
    onSuccess: () => invalidateMaintenanceQueries(queryClient, vin),
  })
}

export function useMarkReminderDismissed(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => reminderService.dismiss(vin, id),
    onSuccess: () => invalidateMaintenanceQueries(queryClient, vin),
  })
}

export function useSnoozeReminder(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, until }: { id: number; until: string }) =>
      reminderService.snooze(vin, id, until),
    onSuccess: () => invalidateMaintenanceQueries(queryClient, vin),
  })
}

export function useUnsnoozeReminder(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => reminderService.unsnooze(vin, id),
    onSuccess: () => invalidateMaintenanceQueries(queryClient, vin),
  })
}

export function useCompleteReminder(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...payload }: ReminderCompleteRequest & { id: number }) =>
      reminderService.complete(vin, id, payload),
    onSuccess: () => invalidateMaintenanceQueries(queryClient, vin),
  })
}

export function useMaintenanceRules(vin: string, enabled = true) {
  return useQuery({
    queryKey: ['maintenanceRules', vin],
    queryFn: () => reminderService.listRules(vin),
    enabled: !!vin && enabled,
  })
}

export function useReminderPacks(vehicleType: string | null | undefined) {
  return useQuery({
    queryKey: ['reminderPacks', vehicleType ?? ''],
    queryFn: () => reminderService.listPacks(vehicleType),
  })
}

export function usePackPreview(
  vin: string,
  packId: string | null,
  anchors: AnchorChoices,
  overrides: IntervalOverrides = {},
) {
  return useQuery({
    // TanStack hashes plain objects with sorted keys, so the choice order is irrelevant.
    queryKey: ['packPreview', vin, packId, anchors, overrides],
    queryFn: () => reminderService.previewPack(vin, packId as string, anchors, overrides),
    enabled: !!vin && !!packId,
    staleTime: 0,
    // One preview is a fan-out of per-item queries, and the app refetches on
    // focus by default. Tabbing away and back does not change the plan, so it
    // does not need to pay for it again.
    refetchOnWindowFocus: false,
    // An override changes the plan, not just a displayed number: the anchor
    // proposal and any skip reason are recomputed. Keeping the last plan on
    // screen while the next one loads stops the dialog flashing empty on every
    // keystroke, and the dialog disables Apply until it settles.
    placeholderData: (previous) => previous,
  })
}

export function useApplyPack(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      packId,
      anchors,
      overrides,
    }: {
      packId: string
      anchors?: AnchorChoices
      overrides?: IntervalOverrides
    }) => reminderService.applyPack(vin, packId, anchors, overrides),
    onSuccess: () => invalidateMaintenanceQueries(queryClient, vin),
  })
}

/** Saving, renaming, overwriting and deleting a pack all change the LIST, which
 *  is instance-wide rather than per-vehicle, so they invalidate that key and not
 *  the maintenance queries of whichever vehicle happened to be on screen. */
function usePackListMutation<TArgs>(fn: (args: TArgs) => Promise<unknown>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['reminderPacks'] }),
  })
}

export function useSavePack() {
  return usePackListMutation((body: SavePackBody) => reminderService.savePack(body))
}

export function useOverwritePack() {
  return usePackListMutation(({ packId, body }: { packId: string; body: SavePackBody }) =>
    reminderService.overwritePack(packId, body),
  )
}

export function useRenamePack() {
  return usePackListMutation(({ packId, name }: { packId: string; name: string }) =>
    reminderService.renamePack(packId, name),
  )
}

export function useDeletePack() {
  return usePackListMutation((packId: string) => reminderService.deletePack(packId))
}

export function useReminderDuplicates(vin: string) {
  return useQuery({
    queryKey: ['reminderDuplicates', vin],
    queryFn: () => reminderService.duplicates(vin),
    enabled: !!vin,
  })
}

export function useReconcileDuplicates(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ keepId, supersedeIds }: { keepId: number; supersedeIds: number[] }) =>
      reminderService.reconcileDuplicates(vin, keepId, supersedeIds),
    onSuccess: () => invalidateMaintenanceQueries(queryClient, vin),
  })
}

export function useMaintenanceTypes() {
  return useQuery({
    queryKey: ['maintenanceTypes'],
    queryFn: () => reminderService.maintenanceTypes(),
    staleTime: 24 * 60 * 60 * 1000,
  })
}
