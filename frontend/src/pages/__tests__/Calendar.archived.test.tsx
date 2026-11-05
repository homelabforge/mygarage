/**
 * The calendar's vehicle filter lists only vehicles still in service (D17).
 * The API hides an archived vehicle's events, so a chip for it would filter
 * down to nothing. `/vehicles` returns archived ones too, so the page drops
 * them itself. The render harness is Calendar.search.test.tsx's.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'

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
vi.mock('../../hooks/useTimeFormat', () => ({ useTimeFormat: () => ({ timeFormat: 24 }) }))
vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => 'en-US' }))
vi.mock('../../hooks/useUnitPreference', async () => {
  const { METRIC_UNITS } = await import('../../__tests__/factories')
  const pref = () => ({
    system: 'metric',
    showBoth: false,
    gallonStandard: 'us',
    units: METRIC_UNITS,
  })
  return { useUnitPreference: pref, useAccountUnitPreference: pref }
})
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ householdTimeZone: 'UTC', refreshPublicSettings: vi.fn() }),
}))

import CalendarPage from '../Calendar'

const ACTIVE = { vin: '1FTFW1E50NFA00001', nickname: 'Daily Driver', archived_at: null }
const ARCHIVED = { vin: '1FTFW1E50NFA00002', nickname: 'Old Truck', archived_at: '2026-01-15T12:00:00Z' }

function serveVehicles(vehicles: unknown[]): void {
  apiGet.mockImplementation((url: string) => {
    if (url === '/vehicles') return Promise.resolve({ data: { vehicles } })
    return Promise.resolve({
      data: { events: [], summary: { total: 0, overdue: 0, upcoming_7_days: 0, upcoming_30_days: 0 } },
    })
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('Calendar vehicle filter skips archived vehicles (D17)', () => {
  it('offers the active vehicle and not the archived one', async () => {
    serveVehicles([ACTIVE, ARCHIVED])
    render(<CalendarPage />)

    expect(await screen.findByRole('button', { name: 'Daily Driver' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Old Truck' })).not.toBeInTheDocument()
  })
})
