/**
 * The Calendar's upcoming-event item: finishing a text selection on it doesn't
 * navigate, and it opens from the keyboard (issue #179).
 *
 * jsdom has no layout and no long-press, so these pin HANDLERS and STRUCTURE:
 * the item's click ignores a selection-end click and a click that started in
 * Notes or Quick complete, and a real focusable button opens the event. Whether
 * the text is actually selectable on a phone is the E2E task's half.
 *
 * The render harness is Calendar.householdZone.test.tsx's, plus a partial
 * react-router-dom mock so `navigate` can be watched.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient } from '@tanstack/react-query'
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

// A reminder with notes, so the item carries both Notes and Quick complete.
const EVENT = {
  id: 'reminder-1',
  title: 'Oil change',
  date: '2026-09-20',
  type: 'maintenance',
  category: 'maintenance',
  urgency: 'medium',
  vehicle_vin: 'V1',
  vehicle_nickname: 'Test Car',
  status: 'due_soon',
  notes: 'Bring the coupon',
  is_completed: false,
}

const EVENT_PATH = '/vehicles/V1?tab=service'

function selectSomeText(): void {
  vi.spyOn(window, 'getSelection').mockReturnValue({
    isCollapsed: false,
    toString: () => 'Oil change',
  } as unknown as Selection)
}

beforeEach(() => {
  vi.clearAllMocks()
  setHouseholdTimeZone('UTC')
  vi.useFakeTimers({ now: new Date('2026-09-17T11:00:00Z'), toFake: ['Date'] })
  apiGet.mockImplementation((url: string) => {
    if (url === '/vehicles') return Promise.resolve({ data: [] })
    return Promise.resolve({
      data: {
        events: [EVENT],
        summary: { total: 1, overdue: 0, upcoming_7_days: 1, upcoming_30_days: 1 },
      },
    })
  })
  apiPost.mockResolvedValue({ data: {} })
})

afterEach(() => {
  vi.restoreAllMocks()
  setHouseholdTimeZone(null)
  vi.useRealTimers()
})

describe('Calendar upcoming event: selecting its text (#179)', () => {
  it('ending a selection on an event does not navigate', async () => {
    // RED today: the item's onClick navigates on any click, including the one
    // that lets go of a selection.
    render(<CalendarPage />)
    const title = await screen.findByText('Oil change')

    selectSomeText()
    fireEvent.click(title)
    expect(mockNavigate).not.toHaveBeenCalled()

    // Selection gone, a plain click still opens it.
    vi.mocked(window.getSelection).mockRestore()
    fireEvent.click(title)
    expect(mockNavigate).toHaveBeenCalledTimes(1)
    expect(mockNavigate).toHaveBeenCalledWith(EVENT_PATH)
  })

  it('the event opens from its focusable button', async () => {
    // RED today: the item is a bare div with a click handler, so a keyboard
    // user can't reach it at all.
    const user = userEvent.setup()
    render(<CalendarPage />)
    await screen.findByText('Oil change')

    const open = screen.getByRole('button', { name: 'calendar.openEvent' })
    open.focus()
    await user.keyboard('{Enter}')
    expect(mockNavigate).toHaveBeenCalledTimes(1)
    expect(mockNavigate).toHaveBeenLastCalledWith(EVENT_PATH)

    await user.keyboard(' ')
    expect(mockNavigate).toHaveBeenCalledTimes(2)
  })

  it('Notes and Quick complete do their own thing and do not open the event', async () => {
    // Guard: they stopped propagation before; now the item's own
    // cameFromNestedControl check is what keeps it out of their clicks.
    // Mutant that kills it: drop cameFromNestedControl from the item's onClick.
    const user = userEvent.setup()
    render(<CalendarPage />)
    await screen.findByText('Oil change')

    // By click.
    fireEvent.click(screen.getByRole('button', { name: 'calendar.misc.viewNotes' }))
    expect(screen.getByText('calendar.eventNotes')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'calendar.misc.close' }))

    fireEvent.click(screen.getByRole('button', { name: 'calendar.misc.markComplete' }))
    expect(apiPost).toHaveBeenCalledWith('/vehicles/V1/reminders/1/done')

    expect(mockNavigate).not.toHaveBeenCalled()

    // By Enter and Space, which a browser turns into a click on the button.
    screen.getByRole('button', { name: 'calendar.misc.viewNotes' }).focus()
    await user.keyboard('{Enter}')
    expect(screen.getByText('calendar.eventNotes')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'calendar.misc.close' }))

    screen.getByRole('button', { name: 'calendar.misc.markComplete' }).focus()
    await user.keyboard(' ')
    expect(apiPost).toHaveBeenCalledTimes(2)

    expect(mockNavigate).not.toHaveBeenCalled()
  })
})

describe('Calendar completes refresh the vehicle page (#192)', () => {
  // The calendar posts reminder completions itself, so the vehicle page's
  // reminders list and hero must be refreshed by key, or they show the row as
  // pending until their cache goes stale.
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('a quick complete refreshes the reminders list and the hero for its vehicle', async () => {
    const invalidate = vi.spyOn(QueryClient.prototype, 'invalidateQueries')
    render(<CalendarPage />)
    await screen.findByText('Oil change')
    fireEvent.click(screen.getByRole('button', { name: 'calendar.misc.markComplete' }))
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ['reminders', 'V1'] }))
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['vehicleDetailStats', 'V1'] })
  })

  it('a bulk complete refreshes them too', async () => {
    const invalidate = vi.spyOn(QueryClient.prototype, 'invalidateQueries')
    render(<CalendarPage />)
    await screen.findByText('Oil change')
    fireEvent.click(screen.getByRole('button', { name: 'calendar.bulkMode' }))
    fireEvent.click(screen.getByRole('button', { name: 'calendar.selectEvent' }))
    fireEvent.click(screen.getByRole('button', { name: 'calendar.completeSelected' }))
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/vehicles/V1/reminders/1/done'))
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ['reminders', 'V1'] }))
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['vehicleDetailStats', 'V1'] })
  })
})

describe('Calendar month grid and bulk mode (G7 fold-in)', () => {
  it('a reminder clicked in the month grid opens it, like the upcoming list', async () => {
    // RED today: the grid's onEventClick has its own switch with no case for
    // a reminder- id, so the click does nothing. Mutant that kills it: give
    // the grid back its own switch instead of openEvent.
    render(<CalendarPage />)
    await waitFor(() => expect(capturedCalendarConfig.current).not.toBeNull())
    const callbacks = capturedCalendarConfig.current?.callbacks as {
      onEventClick: (calendarEvent: { _customData?: unknown }) => void
    }

    callbacks.onEventClick({ _customData: EVENT })

    expect(mockNavigate).toHaveBeenCalledTimes(1)
    expect(mockNavigate).toHaveBeenCalledWith(EVENT_PATH)
  })

  it('in bulk mode the focusable button selects the event, by click, Enter and Space', async () => {
    // RED today: bulk mode renders no focusable control on the item at all,
    // so selecting from the keyboard is impossible.
    const user = userEvent.setup()
    render(<CalendarPage />)
    await screen.findByText('Oil change')
    fireEvent.click(screen.getByRole('button', { name: 'calendar.bulkMode' }))

    const select = screen.getByRole('button', { name: 'calendar.selectEvent' })
    expect(select).toHaveAttribute('aria-pressed', 'false')

    select.focus()
    await user.keyboard('{Enter}')
    expect(select).toHaveAttribute('aria-pressed', 'true')
    await user.keyboard(' ')
    expect(select).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(select)
    expect(select).toHaveAttribute('aria-pressed', 'true')
    expect(mockNavigate).not.toHaveBeenCalled()

    // Out of bulk mode it's the open button again, with no pressed state.
    fireEvent.click(screen.getByRole('button', { name: 'calendar.bulkMode' }))
    const open = screen.getByRole('button', { name: 'calendar.openEvent' })
    expect(open).not.toHaveAttribute('aria-pressed')
  })

  it("in bulk mode a click on the item's body toggles its selection and doesn't navigate", async () => {
    // Guard: passes today. The item's click still has its bulk branch after
    // the selection guard went in front of it. Mutant that kills it: drop the
    // bulk branch so the item always calls openEvent.
    render(<CalendarPage />)
    const title = await screen.findByText('Oil change')
    fireEvent.click(screen.getByRole('button', { name: 'calendar.bulkMode' }))
    const select = screen.getByRole('button', { name: 'calendar.selectEvent' })
    expect(select).toHaveAttribute('aria-pressed', 'false')

    fireEvent.click(title)
    expect(select).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(title)
    expect(select).toHaveAttribute('aria-pressed', 'false')

    expect(mockNavigate).not.toHaveBeenCalled()
  })
})
