/**
 * #192: a pending reminder's bar, chip and order move with the vehicle's
 * readings, and the hero counts the same reminders. So every write that adds or
 * changes a reading, a reminder, a service visit or a tire refreshes both the
 * reminders list and the hero's detail-stats.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import {
  useCreateOdometerRecord,
  useUpdateOdometerRecord,
  useDeleteOdometerRecord,
  useImportOdometerCSV,
} from '../useOdometerRecords'
import { useCreateHoursRecord, useUpdateHoursRecord, useDeleteHoursRecord } from '../useHoursRecords'
import {
  useCreateFuelRecord,
  useUpdateFuelRecord,
  useDeleteFuelRecord,
  useImportFuelCSV,
} from '../useFuelRecords'
import { useCreateDEFRecord, useUpdateDEFRecord, useDeleteDEFRecord } from '../useDEFRecords'
import {
  useCreatePropaneRecord,
  useUpdatePropaneRecord,
  useDeletePropaneRecord,
} from '../usePropaneRecords'
import { useCreateServiceVisit } from '../useServiceVisits'
import { useCreateTire } from '../useTires'
import {
  invalidateMaintenanceQueries,
  useApplyPack,
  useCompleteReminder,
  useCreateReminder,
  useDeleteReminder,
  useMarkReminderDismissed,
  useMarkReminderDone,
  useReconcileDuplicates,
  useSnoozeReminder,
  useUnsnoozeReminder,
  useUpdateReminder,
} from '../../useReminders'
import api from '../../../services/api'

vi.mock('../../../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

const VIN = '1HGCM82633A004352'
const LIST = { queryKey: ['reminders', VIN] }
const HERO = { queryKey: ['vehicleDetailStats', VIN] }

beforeEach(() => {
  vi.clearAllMocks()
  for (const verb of ['post', 'put', 'delete'] as const) {
    vi.mocked(api[verb]).mockResolvedValue({ data: {} } as { data: unknown })
  }
})

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyMutationHook = (vin: string) => { mutateAsync: (arg: any) => Promise<unknown> }

const CASES: [string, AnyMutationHook, unknown][] = [
  ['odometer create', useCreateOdometerRecord, { date: '2026-10-01', odometer_km: 1000 }],
  ['odometer update', useUpdateOdometerRecord, { id: 1, odometer_km: 1000 }],
  ['odometer delete', useDeleteOdometerRecord, 1],
  ['odometer import', useImportOdometerCSV, new FormData()],
  ['hours create', useCreateHoursRecord, { date: '2026-10-01', engine_hours: 10 }],
  ['hours update', useUpdateHoursRecord, { id: 1, engine_hours: 10 }],
  ['hours delete', useDeleteHoursRecord, 1],
  ['fuel create', useCreateFuelRecord, { date: '2026-10-01' }],
  ['fuel update', useUpdateFuelRecord, { id: 1 }],
  ['fuel delete', useDeleteFuelRecord, 1],
  ['fuel import', useImportFuelCSV, { formData: new FormData() }],
  ['DEF create', useCreateDEFRecord, { date: '2026-10-01', odometer_km: 1000 }],
  ['DEF update', useUpdateDEFRecord, { id: 1, odometer_km: 1000 }],
  ['DEF delete', useDeleteDEFRecord, 1],
  ['propane create', useCreatePropaneRecord, { date: '2026-10-01' }],
  ['propane update', useUpdatePropaneRecord, { id: 1 }],
  ['propane delete', useDeletePropaneRecord, 1],
  ['service visit create', useCreateServiceVisit, { date: '2026-10-01' }],
  ['tire create', useCreateTire, { brand: 'Test' }],
]

// Reminder writes: the hero's counts move with the list, by key, with no
// callback from the list up to the page.
const REMINDER_CASES: [string, AnyMutationHook, unknown][] = [
  ['reminder create', useCreateReminder, { title: 'Oil', reminder_type: 'date' }],
  ['reminder update', useUpdateReminder, { id: 1, title: 'Oil' }],
  ['reminder delete', useDeleteReminder, 1],
  ['reminder done', useMarkReminderDone, 1],
  ['reminder dismiss', useMarkReminderDismissed, 1],
  ['reminder snooze', useSnoozeReminder, { id: 1, until: '2026-11-01' }],
  ['reminder unsnooze', useUnsnoozeReminder, 1],
  ['reminder complete', useCompleteReminder, { id: 1, completed_date: '2026-10-01' }],
  ['pack apply', useApplyPack, { packId: 'basic' }],
  ['duplicates reconcile', useReconcileDuplicates, { keepId: 1, supersedeIds: [2] }],
]

describe.each([...CASES, ...REMINDER_CASES])('%s', (_name, useHook, arg) => {
  it('refreshes the reminders list and the hero', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
    const spy = vi.spyOn(qc, 'invalidateQueries')
    const Wrap = ({ children }: { children: React.ReactNode }): React.ReactElement =>
      React.createElement(QueryClientProvider, { client: qc }, children)
    const { result } = renderHook(() => useHook(VIN), { wrapper: Wrap })
    await result.current.mutateAsync(arg)
    expect(spy).toHaveBeenCalledWith(LIST)
    expect(spy).toHaveBeenCalledWith(HERO)
  })
})

// Fuel and DEF writes sync odometer (and fuel, hours) rows on the server, so
// every reading write refreshes the same set of reading views.
const READING_VIEWS = [
  'reminders',
  'vehicleDetailStats',
  'odometerRecords',
  'latestMileage',
  'hoursRecords',
  'latestHours',
]

describe.each(CASES.filter(([name]) => !name.startsWith('service visit')))(
  '%s',
  (_name, useHook, arg) => {
    it('refreshes every view a reading moves', async () => {
      const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
      const spy = vi.spyOn(qc, 'invalidateQueries')
      const Wrap = ({ children }: { children: React.ReactNode }): React.ReactElement =>
        React.createElement(QueryClientProvider, { client: qc }, children)
      const { result } = renderHook(() => useHook(VIN), { wrapper: Wrap })
      await result.current.mutateAsync(arg)
      for (const key of READING_VIEWS) {
        expect(spy).toHaveBeenCalledWith({ queryKey: [key, VIN] })
      }
    })
  },
)

describe('invalidateMaintenanceQueries, which every reminder mutation calls', () => {
  it('refreshes the hero along with the list', () => {
    const qc = new QueryClient()
    const spy = vi.spyOn(qc, 'invalidateQueries')
    invalidateMaintenanceQueries(qc, VIN)
    expect(spy).toHaveBeenCalledWith(LIST)
    expect(spy).toHaveBeenCalledWith(HERO)
  })
})
