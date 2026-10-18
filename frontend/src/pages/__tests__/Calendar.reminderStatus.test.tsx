/**
 * The upcoming list's reminder detail: the "Snoozed" chip and the low-tread
 * line (batch 4, Task 3).
 *
 * The backend now sends a reminder's due status as is, "snoozed" included, so
 * the chip needs its own label: it used to fall through to "On Track". A
 * low-tread event carries its tread and minimum in mm (D7a); the item and the
 * notes drawer show them in the account's tread unit.
 *
 * Schedule-X is stubbed, as in Calendar.mixedUnits.test.tsx: none of this is
 * inside its grid.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import type { UnitSet } from '@/types/units'

vi.mock('@schedule-x/react', () => ({
  useCalendarApp: () => ({}),
  ScheduleXCalendar: () => null,
}))
vi.mock('@schedule-x/calendar', () => ({
  createViewDay: () => ({ name: 'day' }),
  createViewWeek: () => ({ name: 'week' }),
  createViewMonthGrid: () => ({ name: 'month-grid' }),
}))
vi.mock('@schedule-x/events-service', () => ({
  createEventsServicePlugin: () => ({ set: vi.fn(), getAll: () => [] }),
}))
vi.mock('@schedule-x/calendar-controls', () => ({
  createCalendarControlsPlugin: () => ({ setLocale: vi.fn(), setDate: vi.fn(), setView: vi.fn() }),
}))

const apiGet = vi.fn()
vi.mock('../../services/api', () => ({
  default: { get: (...args: unknown[]) => apiGet(...args), post: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ householdTimeZone: null, refreshPublicSettings: vi.fn() }),
}))
vi.mock('../../hooks/useTimeFormat', () => ({ useTimeFormat: () => ({ timeFormat: 24 }) }))
vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => 'en-US' }))

const unitPrefMock = vi.hoisted(() => ({ units: null as unknown as UnitSet }))
vi.mock('../../hooks/useUnitPreference', async () => {
  const { binarySystemFor } = await import('@/types/units')
  const pref = () => ({
    system: binarySystemFor(unitPrefMock.units.volume),
    showBoth: false,
    gallonStandard: unitPrefMock.units.secondary_gallon,
    units: unitPrefMock.units,
  })
  return { useUnitPreference: pref, useAccountUnitPreference: pref }
})

// The tread line interpolates two figures; the global mock discards options.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      options && 'tread' in options
        ? `${key} ${String(options.tread)} | ${String(options.minimum)}`
        : key,
    i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}))

import { IMPERIAL_UNITS, METRIC_UNITS } from '../../__tests__/factories'
import CalendarPage from '../Calendar'

/** Inside the upcoming list's 30-day window. */
const IN_FIVE_DAYS = new Date(Date.now() + 5 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10)

const BASE = {
  date: IN_FIVE_DAYS,
  type: 'maintenance',
  category: 'maintenance',
  vehicle_vin: 'V1',
  vehicle_nickname: 'Test Car',
  is_recurring: false,
  is_estimated: false,
  notes: null,
}

function serve(events: object[]): void {
  apiGet.mockImplementation((url: string) => {
    if (url === '/vehicles') return Promise.resolve({ data: [] })
    return Promise.resolve({
      data: {
        events,
        summary: { total: events.length, overdue: 0, upcoming_7_days: 0, upcoming_30_days: events.length },
      },
    })
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  unitPrefMock.units = METRIC_UNITS
})

describe('Calendar reminder status chip', () => {
  it('a snoozed reminder reads Snoozed, not On Track', async () => {
    serve([{ ...BASE, id: 'reminder-1', title: 'Snoozed oil', urgency: 'low', status: 'snoozed' }])
    render(<CalendarPage />)

    expect(await screen.findByText('calendar.misc.statusSnoozed')).toBeInTheDocument()
    expect(screen.queryByText('calendar.misc.statusOnTrack')).not.toBeInTheDocument()
  })
})

describe('Calendar low-tread line', () => {
  const TREAD = {
    ...BASE,
    id: 'reminder-2',
    title: 'Tire tread low (FL)',
    urgency: 'high',
    status: 'due_soon',
    tread_depth_mm: '1.50',
    tread_threshold_mm: '3.00',
    notes: 'measured at the inner groove',
  }

  it('shows the tread against its minimum in the tread unit', async () => {
    serve([TREAD])
    render(<CalendarPage />)

    await waitFor(() =>
      expect(screen.getByText('calendar.misc.treadLine 1.50 mm | 3.00 mm')).toBeInTheDocument()
    )
  })

  it('follows an imperial tread unit, in the item and the notes drawer', async () => {
    unitPrefMock.units = IMPERIAL_UNITS
    serve([TREAD])
    render(<CalendarPage />)

    const line = 'calendar.misc.treadLine 2/32 in | 4/32 in'
    await waitFor(() => expect(screen.getByText(line)).toBeInTheDocument())
    fireEvent.click(await screen.findByTitle('calendar.misc.viewNotes'))
    await waitFor(() => expect(screen.getAllByText(line)).toHaveLength(2))
  })

  it('leaves other reminders without a tread line', async () => {
    // Control: passes on main by design (main has no tread line at all).
    serve([{ ...BASE, id: 'reminder-3', title: 'Wipers', urgency: 'high', status: 'due_soon' }])
    render(<CalendarPage />)

    await screen.findByText('Wipers')
    expect(screen.queryByText(/calendar\.misc\.treadLine/)).not.toBeInTheDocument()
  })
})
