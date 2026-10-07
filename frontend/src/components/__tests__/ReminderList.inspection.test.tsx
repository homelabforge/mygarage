/**
 * The automatic inspection reminder in the list (#211): its chip and hint,
 * the "can be done from" window, and shipped pack names read from the bundle.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import type { Reminder } from '../../types/reminder'
import { IMPERIAL_UNITS } from '../../__tests__/factories'
import { makeVehicle, reminderFormModule, reminderHooks } from './helpers/reminderListHarness'

// The window line carries its date through interpolation, so this file swaps
// the global key-only mock for one that appends the options (the dueStatus
// test's convention). Module scope: a fresh `t` per render re-fires effects.
const i18nMock = vi.hoisted(() => ({
  t: (key: string, options?: Record<string, unknown>): string =>
    options ? [key, ...Object.values(options).map(String)].join('|') : key,
  i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
}))
vi.mock('react-i18next', () => ({
  useTranslation: () => i18nMock,
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}))

const useRemindersMock = vi.fn()
const useReminderPacksMock = vi.fn()
vi.mock('../../hooks/useReminders', () =>
  reminderHooks({
    useReminders: () => useRemindersMock(),
    useReminderPacks: () => useReminderPacksMock(),
  }),
)
vi.mock('../CompleteReminderDialog', () => ({ default: () => null }))
vi.mock('../ReminderForm', (importOriginal) => reminderFormModule(importOriginal, () => null))
vi.mock('../../hooks/useLatestMileage', () => ({ useLatestMileage: () => ({ data: null }) }))
vi.mock('../../hooks/useLatestHours', () => ({ useLatestHours: () => ({ data: null }) }))
vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => 'en-US' }))
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: 'imperial',
    showBoth: false,
    gallonStandard: 'us',
    units: IMPERIAL_UNITS,
  }),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import ReminderList from '../ReminderList'

const base = {
  id: 8, vin: 'V1', title: 'Contrôle technique', reminder_type: 'date', status: 'pending',
  due_date: '2027-03-12', due_mileage_km: null, estimated_due_date: null, notes: null,
  line_item_id: null, last_notified_at: null, due_status: 'on_track',
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  source: 'inspection',
  anchor_kind: 'baseline', anchor_date: '2023-03-12',
  rule_id: 1,
  rule: { id: 1, title: 'Contrôle technique', maintenance_type: 'state_inspection', interval_months: 48, lead_days: 180, source: 'inspection', is_active: true },
} as unknown as Reminder

beforeEach(() => {
  vi.clearAllMocks()
  useRemindersMock.mockReturnValue({ data: [base], isLoading: false })
  useReminderPacksMock.mockReturnValue({ data: [] })
})

describe('ReminderList — automatic inspection (#211)', () => {
  it('shows the Automatic chip with the registration-date hint on a baseline-anchored reminder', () => {
    render(<ReminderList vehicle={makeVehicle()} />)
    const chip = screen.getByText('reminderList.automaticInspection')
    expect(chip.closest('span[title]')?.getAttribute('title')).toBe('reminderList.inspectionFromRegistration')
  })

  it('says it counts from the last inspection once anchored on a service, and names a re-test', () => {
    useRemindersMock.mockReturnValue({
      data: [{ ...base, anchor_kind: 'service', anchor_date: '2026-02-10', due_date: '2028-02-10' }],
      isLoading: false,
    })
    const { unmount } = render(<ReminderList vehicle={makeVehicle()} />)
    expect(screen.getByText('reminderList.automaticInspection').closest('span[title]')?.getAttribute('title'))
      .toBe('reminderList.inspectionFromLast')
    unmount()

    useRemindersMock.mockReturnValue({
      data: [{ ...base, anchor_kind: 'service', rule: { ...base.rule, interval_months: 2 } }],
      isLoading: false,
    })
    render(<ReminderList vehicle={makeVehicle()} />)
    expect(screen.getByText('reminderList.automaticInspection').closest('span[title]')?.getAttribute('title'))
      .toBe('reminderList.inspectionRetest')
  })

  it('shows when the window opens: the due date minus the rule lead days', () => {
    render(<ReminderList vehicle={makeVehicle()} />)
    // 2027-03-12 minus 180 days is 2026-09-13, rendered by the date formatter
    // (the test i18n prints a key's interpolated value after a pipe).
    expect(screen.getByText('reminderList.inspectionWindowOpen|Sep 13, 2026')).toBeInTheDocument()
  })

  it('a reminder a person made has neither the chip nor a window', () => {
    useRemindersMock.mockReturnValue({
      data: [{ ...base, source: null, rule: { ...base.rule, source: 'manual', lead_days: null } }],
      isLoading: false,
    })
    render(<ReminderList vehicle={makeVehicle()} />)
    expect(screen.queryByText('reminderList.automaticInspection')).not.toBeInTheDocument()
    expect(screen.queryByText(/reminderList\.inspectionWindowOpen/)).not.toBeInTheDocument()
  })

  it('names a shipped pack from the bundle and a saved pack as typed', () => {
    useReminderPacksMock.mockReturnValue({
      data: [
        { id: 'oil_and_filter', name: 'Oil & Filter Service', description: '', reminder_count: 2, vehicle_types: [], is_custom: false, can_edit: false },
        { id: 'custom-abc', name: 'My pack', description: '', reminder_count: 1, vehicle_types: [], is_custom: true, can_edit: true },
      ],
    })
    render(<ReminderList vehicle={makeVehicle()} />)
    const select = screen.getByLabelText('reminderList.applyPackAria') as HTMLSelectElement
    const labels = Array.from(select.options).map((o) => o.textContent)
    // The bundle key with the file's name as `defaultValue` (appended by this file's t).
    expect(labels).toContain('vehicles:reminderPacks.oil_and_filter.name|Oil & Filter Service')
    expect(labels).toContain('My pack (packList.saved)')
  })
})
