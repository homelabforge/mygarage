/**
 * Shared pieces for the ReminderList tests (RD-9): a reminder and vehicle
 * factory, and the values the hook mocks hand back.
 *
 * vitest hoists `vi.mock` above the imports, so each test file keeps its own
 * `vi.mock(...)` lines and only calls these from inside the factories. That
 * works because a factory runs when the mocked module is first imported,
 * after this module has loaded.
 */
import type { ReactNode } from 'react'
import { vi } from 'vitest'
import type { Reminder } from '../../../types/reminder'
import type { Vehicle } from '../../../types/vehicle'
import type { UnitSet } from '../../../__tests__/factories'

/** A pending mileage reminder with every optional field empty; override what a case needs. */
export function makeReminder(over: Partial<Reminder> = {}): Reminder {
  return {
    id: 1, vin: 'V1', title: 'Oil change', reminder_type: 'mileage', status: 'pending',
    due_date: null, due_mileage_km: null, due_hours: null,
    estimated_due_date: null, projected_usage_date: null, snoozed_until: null,
    notes: null, line_item_id: null, last_notified_at: null,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    due_status: null, progress: null, progress_basis: null,
    days_until_due: null, km_until_due: null, hours_until_due: null,
    ...over,
  }
}

/** The vehicle ReminderList is handed, a distance-only car on VIN V1. */
export function makeVehicle(over: Partial<Vehicle> = {}): Vehicle {
  // `satisfies` keeps the base checked against Vehicle; the cast only covers
  // the fields a test never reads.
  const base = {
    vin: 'V1', nickname: 'Test Car', vehicle_type: 'Car',
    usage_unit: 'distance', secondary_usage_enabled: false,
    archived_visible: true, location_tracking_enabled: false,
    created_at: '2026-01-01T00:00:00Z',
  } satisfies Partial<Vehicle>
  return { ...base, ...over } as Vehicle
}

type HookMocks = Record<string, (...args: never[]) => unknown>

/**
 * The `hooks/useReminders` module as ReminderList and its dialogs call it:
 * no rows, no groups, no packs, mutations that resolve. Pass the hooks a case
 * drives.
 */
export function reminderHooks(over: HookMocks = {}): HookMocks {
  return {
    useReminders: () => ({ data: [], isLoading: false }),
    useMarkReminderDone: () => ({ mutateAsync: vi.fn().mockResolvedValue(undefined) }),
    useMarkReminderDismissed: () => ({ mutateAsync: vi.fn().mockResolvedValue(undefined) }),
    useDeleteReminder: () => ({ mutateAsync: vi.fn().mockResolvedValue(undefined) }),
    useReminderDuplicates: () => ({ data: [] }),
    useReminderPacks: () => ({ data: [] }),
    useDeletePack: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useSnoozeReminder: () => ({ mutateAsync: vi.fn().mockResolvedValue(undefined), isPending: false }),
    useUnsnoozeReminder: () => ({ mutateAsync: vi.fn().mockResolvedValue(undefined), isPending: false }),
    ...over,
  }
}

/**
 * The `ReminderForm` module with a stand-in form but its real exports, since
 * ReminderList reads the type chip's label from `REMINDER_TYPE_DEFS` there.
 * Use as `vi.mock('../ReminderForm', (importOriginal) => reminderFormModule(importOriginal, Form))`.
 */
export async function reminderFormModule(
  importOriginal: () => Promise<unknown>,
  Form: (props: never) => ReactNode,
): Promise<Record<string, unknown>> {
  return { ...(await importOriginal() as Record<string, unknown>), default: Form }
}

/** No reading yet, for `useLatestMileage` and `useLatestHours`. */
export const NO_READING = { data: null }

/** What `useUnitPreference` returns for a resolved unit set. */
export function unitPreference(units: UnitSet, system: 'metric' | 'imperial'): {
  system: 'metric' | 'imperial'
  showBoth: boolean
  gallonStandard: 'us'
  units: UnitSet
} {
  return { system, showBoth: false, gallonStandard: 'us', units }
}
