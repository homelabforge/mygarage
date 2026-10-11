import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import type { Reminder } from '../../types/reminder'
import { IMPERIAL_UNITS } from '../../__tests__/factories'

// G3a-21: a low-tread reminder carries its tread in columns, and the list
// renders them in the reader's unit. Mocks copied from ReminderList.hours.test.tsx,
// with imperial units and a t that shows its values.

const useRemindersMock = vi.fn()
vi.mock('../../hooks/useReminders', () => ({
  useReminders: () => useRemindersMock(),
  useMarkReminderDone: () => ({ mutateAsync: vi.fn().mockResolvedValue(undefined) }),
  useMarkReminderDismissed: () => ({ mutateAsync: vi.fn().mockResolvedValue(undefined) }),
  useDeleteReminder: () => ({ mutateAsync: vi.fn().mockResolvedValue(undefined) }),
  useReminderDuplicates: () => ({ data: [] }),
  useReminderPacks: () => ({ data: [] }),
  useDeletePack: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))
vi.mock('../../hooks/useLatestMileage', () => ({ useLatestMileage: () => ({ data: null }) }))
const useLatestHoursMock = vi.fn(() => ({ data: null as number | null }))
vi.mock('../../hooks/useLatestHours', () => ({ useLatestHours: () => useLatestHoursMock() }))
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
const reminderFormProps = vi.hoisted(() => ({ currentHours: 'UNSET' as unknown }))
vi.mock('../ReminderForm', () => ({
  default: (props: { currentHours?: number | null }) => {
    reminderFormProps.currentHours = props.currentHours
    return <div>reminder-form-open</div>
  },
}))

// Hoisted so t keeps one identity across renders, like the global mock.
const i18n = vi.hoisted(() => ({
  t: (key: string, params?: Record<string, unknown>): string =>
    params ? `${key}|${Object.values(params).join('|')}` : key,
}))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: i18n.t, i18n: { language: 'en', changeLanguage: () => Promise.resolve() } }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}))

import ReminderList from '../ReminderList'

const lowTread = {
  id: 31, vin: 'V1', title: 'Tire tread low (FL)', reminder_type: 'date', status: 'pending',
  due_date: '2026-06-01', due_mileage_km: null, due_hours: null, estimated_due_date: null, notes: null,
  line_item_id: null, last_notified_at: null, source: 'low_tread', tire_id: 4,
  tread_depth_mm: '1.50', tread_threshold_mm: '2.00',
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
} as unknown as Reminder

beforeEach(() => {
  vi.clearAllMocks()
  useLatestHoursMock.mockReturnValue({ data: null })
  reminderFormProps.currentHours = 'UNSET'
  useRemindersMock.mockReturnValue({ data: [], isLoading: false })
})

describe('ReminderList: the low-tread line (G3a-21)', () => {
  it("renders the reminder's tread in the reader's unit", () => {
    useRemindersMock.mockReturnValue({ data: [lowTread], isLoading: false })
    render(<ReminderList vin="V1" />)
    expect(screen.getByText('reminderList.lowTreadLine|2/32 in|3/32 in')).toBeInTheDocument()
  })

  it('renders nothing for a reminder a person wrote', () => {
    useRemindersMock.mockReturnValue({
      data: [{ ...lowTread, source: null } as unknown as Reminder],
      isLoading: false,
    })
    render(<ReminderList vin="V1" />)
    expect(screen.queryByText(/reminderList\.lowTreadLine/)).not.toBeInTheDocument()
  })
})
