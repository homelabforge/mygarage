import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import { IMPERIAL_UNITS } from '../../__tests__/factories'
import { NO_READING, makeReminder, makeVehicle, reminderHooks, reminderFormModule, unitPreference } from './helpers/reminderListHarness'

// G3a-21: a low-tread reminder carries its tread in columns, and the list
// renders them in the reader's unit, with imperial units and a t that shows its values.

const useRemindersMock = vi.fn()
vi.mock('../../hooks/useReminders', () => reminderHooks({ useReminders: () => useRemindersMock() }))
vi.mock('../../hooks/useLatestMileage', () => ({ useLatestMileage: () => NO_READING }))
vi.mock('../../hooks/useLatestHours', () => ({ useLatestHours: () => NO_READING }))
vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => 'en-US' }))
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => unitPreference(IMPERIAL_UNITS, 'imperial'),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../ReminderForm', (importOriginal) =>
  reminderFormModule(importOriginal, () => <div>reminder-form-open</div>),
)

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

const lowTread = makeReminder({
  id: 31, title: 'Tire tread low (FL)', reminder_type: 'date', due_date: '2026-06-01',
  source: 'low_tread', tire_id: 4, tread_depth_mm: '1.50', tread_threshold_mm: '2.00',
})

beforeEach(() => {
  vi.clearAllMocks()
  useRemindersMock.mockReturnValue({ data: [], isLoading: false })
})

describe('ReminderList: the low-tread line (G3a-21)', () => {
  it("renders the reminder's tread in the reader's unit", () => {
    useRemindersMock.mockReturnValue({ data: [lowTread], isLoading: false })
    render(<ReminderList vehicle={makeVehicle()} />)
    expect(screen.getByText('reminderList.lowTreadLine|2/32 in|3/32 in')).toBeInTheDocument()
  })

  it('renders nothing for a reminder a person wrote', () => {
    useRemindersMock.mockReturnValue({
      data: [{ ...lowTread, source: null }],
      isLoading: false,
    })
    render(<ReminderList vehicle={makeVehicle()} />)
    expect(screen.queryByText(/reminderList\.lowTreadLine/)).not.toBeInTheDocument()
  })
})
