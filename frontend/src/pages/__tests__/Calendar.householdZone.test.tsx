/**
 * Codex code-review R1-M1/M2: the calendar follows the household zone.
 *
 * - M1: Schedule-X defaults its internal timezone to UTC, so the Today
 *   button selected the UTC date even though the initial selectedDate was
 *   the household's. The app config must carry the household zone.
 * - M2: the upcoming-events window anchored on todayInHousehold() but was
 *   memoized only on the events array, so a zone refresh (visibilitychange)
 *   left a stale window. A zone change must recompute it without the events
 *   changing.
 *
 * Frozen at 2026-09-17T11:00:00Z: UTC's date is 09-17 while
 * Pacific/Kiritimati (UTC+14) is already on 09-18.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import { setHouseholdTimeZone } from '../../constants/i18n'

const capturedCalendarConfig = vi.hoisted(() => ({ current: null as Record<string, unknown> | null }))
vi.mock('@schedule-x/react', () => ({
  useCalendarApp: (config: Record<string, unknown>) => {
    capturedCalendarConfig.current = config
    return { setTheme: vi.fn() }
  },
  ScheduleXCalendar: () => null,
}))
vi.mock('../../contexts/ThemeContext', () => ({
  useTheme: () => ({ theme: 'dark', toggleTheme: vi.fn(), setTheme: vi.fn() }),
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

const authMock = vi.hoisted(() => ({ zone: null as string | null }))
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    householdTimeZone: authMock.zone,
    refreshPublicSettings: vi.fn(),
  }),
}))

import CalendarPage from '../Calendar'

const EVENT = {
  id: 'reminder-1',
  title: 'Oil change',
  date: '2026-09-17',
  type: 'maintenance',
  category: 'reminder',
  urgency: 'medium',
  vehicle_vin: 'V1',
  vehicle_nickname: 'Test Car',
  status: 'due_soon',
}

function setZone(zone: string | null): void {
  authMock.zone = zone
  setHouseholdTimeZone(zone)
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.useFakeTimers({ now: new Date('2026-09-17T11:00:00Z'), toFake: ['Date'] })
  apiGet.mockImplementation((url: string) => {
    if (url === '/vehicles') return Promise.resolve({ data: [] })
    return Promise.resolve({
      data: {
        events: [EVENT],
        summary: { total: 1, overdue: 0, upcoming_7_days: 0, upcoming_30_days: 1 },
      },
    })
  })
})

afterEach(() => {
  setZone(null)
  vi.useRealTimers()
})

describe('Calendar follows the household zone', () => {
  it('passes the household timezone into the Schedule-X config (R1-M1: without it, Today selects the UTC date)', async () => {
    setZone('Pacific/Kiritimati')
    render(<CalendarPage />)
    await waitFor(() => expect(capturedCalendarConfig.current).not.toBeNull())
    expect(capturedCalendarConfig.current?.timezone).toBe('Pacific/Kiritimati')
  })

  it('recomputes the upcoming window on a zone change without the events changing (R1-M2)', async () => {
    setZone('UTC')
    const { rerender } = render(<CalendarPage />)
    // Household UTC: 2026-09-17 is today, inside the window.
    expect(await screen.findByText('Oil change')).toBeInTheDocument()

    // The zone refresh arrives (visibility refetch): Kiritimati is on 09-18,
    // so a 09-17 event is now in the past and must leave the upcoming list.
    setZone('Pacific/Kiritimati')
    rerender(<CalendarPage />)
    await waitFor(() => expect(screen.queryByText('Oil change')).not.toBeInTheDocument())
  })
})
