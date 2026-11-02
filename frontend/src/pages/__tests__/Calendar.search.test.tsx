/**
 * The Calendar search (#226): it matches a vehicle's identifier (its VIN, or
 * the serial a tractor has instead), never the generated key. The render
 * harness is Calendar.selection.test.tsx's.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import { setHouseholdTimeZone } from '../../constants/i18n'

const capturedCalendarConfig = vi.hoisted(() => ({ current: null as Record<string, unknown> | null }))
vi.mock('@schedule-x/react', () => ({
  useCalendarApp: (config: Record<string, unknown>) => {
    capturedCalendarConfig.current = config
    return {}
  },
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

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => mockNavigate }
})

const apiGet = vi.fn()
const apiPost = vi.fn()
vi.mock('../../services/api', () => ({
  default: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
  },
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

const Q_KEY = 'QABCDEFGH12345678'
const EVENTS = [
  {
    id: 'reminder-1', title: 'Grease the deck', date: '2026-09-20', type: 'maintenance',
    category: 'maintenance', urgency: 'medium', vehicle_vin: Q_KEY, vehicle_nickname: 'Kubota',
    status: 'due_soon', is_completed: false,
  },
  {
    id: 'reminder-2', title: 'Oil change', date: '2026-09-21', type: 'maintenance',
    category: 'maintenance', urgency: 'medium', vehicle_vin: '1FTFW1E50NFA00001', vehicle_nickname: 'F-150',
    status: 'due_soon', is_completed: false,
  },
]
const VEHICLES = [
  { vin: Q_KEY, nickname: 'Kubota', identifier_type: 'serial', identifier: 'KBT-77', has_vin: false },
  { vin: '1FTFW1E50NFA00001', nickname: 'F-150', identifier_type: 'vin', identifier: null, has_vin: true },
]

beforeEach(() => {
  vi.clearAllMocks()
  setHouseholdTimeZone('UTC')
  vi.useFakeTimers({ now: new Date('2026-09-17T11:00:00Z'), toFake: ['Date'] })
  apiGet.mockImplementation((url: string) => {
    if (url === '/vehicles') return Promise.resolve({ data: { vehicles: VEHICLES } })
    return Promise.resolve({
      data: { events: EVENTS, summary: { total: 2, overdue: 0, upcoming_7_days: 2, upcoming_30_days: 2 } },
    })
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  setHouseholdTimeZone(null)
  vi.useRealTimers()
})

async function search(query: string): Promise<void> {
  render(<CalendarPage />)
  await screen.findByText('Grease the deck')
  await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/vehicles'))
  fireEvent.change(screen.getByPlaceholderText('calendar.searchPlaceholder'), { target: { value: query } })
}

describe('Calendar search matches what identifies a vehicle (#226)', () => {
  it('finds a tractor by its serial', async () => {
    await search('kbt-77')
    await waitFor(() => expect(screen.queryByText('Oil change')).not.toBeInTheDocument())
    expect(screen.getByText('Grease the deck')).toBeInTheDocument()
  })

  it('finds a vehicle by its VIN', async () => {
    await search('nfa00001')
    await waitFor(() => expect(screen.queryByText('Grease the deck')).not.toBeInTheDocument())
    expect(screen.getByText('Oil change')).toBeInTheDocument()
  })

  it('never matches the generated key', async () => {
    await search('qabcdefgh')
    await waitFor(() => expect(screen.queryByText('Grease the deck')).not.toBeInTheDocument())
    expect(screen.queryByText('Oil change')).not.toBeInTheDocument()
  })
})
