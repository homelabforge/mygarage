/**
 * Calendar colours follow the app theme (G2a-22).
 *
 * The React adapter builds the Schedule-X app once, in a mount-only effect,
 * and ignores config after that. So a theme switch has to reach the mounted
 * instance through setTheme, and the event colours have to be tokens that
 * flip with html.light rather than hex baked in at mount.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, fireEvent, screen } from '@testing-library/react'
import type { ReactElement } from 'react'
import { render } from '../../__tests__/test-utils'
import { ThemeProvider, useTheme } from '../../contexts/ThemeContext'
import { setHouseholdTimeZone } from '../../constants/i18n'

// One stable fake app, handed out the way the real hook does it: null on the
// first render, then whatever its mount effect built. `creates` counts builds.
const sx = vi.hoisted(() => ({ creates: 0, app: { setTheme: vi.fn() } }))
vi.mock('@schedule-x/react', async () => {
  const { useEffect, useState } = await import('react')
  return {
    useCalendarApp: (): unknown => {
      const [app, setApp] = useState<unknown>(null)
      useEffect(() => {
        sx.creates += 1
        setApp(sx.app)
      }, [])
      return app
    },
    ScheduleXCalendar: () => null,
  }
})
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
const feed = vi.hoisted(() => ({
  events: [] as unknown[],
  summary: { total: 0, overdue: 0, upcoming_7_days: 0, upcoming_30_days: 0 },
}))
vi.mock('../../services/api', () => ({
  default: {
    get: (url: string) =>
      Promise.resolve(
        url === '/vehicles'
          ? { data: { vehicles: [] } }
          : { data: { events: feed.events, summary: feed.summary } },
      ),
    post: vi.fn(),
  },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../../hooks/useTimeFormat', () => ({ useTimeFormat: () => ({ timeFormat: 24 }) }))
vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => 'en-US' }))
vi.mock('../../hooks/useUnitPreference', async () => {
  const { METRIC_UNITS } = await import('../../__tests__/factories')
  const pref = () => ({ system: 'metric', showBoth: false, gallonStandard: 'us', units: METRIC_UNITS })
  return { useUnitPreference: pref, useAccountUnitPreference: pref }
})
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ householdTimeZone: 'UTC', refreshPublicSettings: vi.fn() }),
}))

import CalendarPage, { EVENT_CALENDARS } from '../Calendar'

function ThemeFlip(): ReactElement {
  const { toggleTheme } = useTheme()
  return (
    <button type="button" onClick={toggleTheme}>
      flip theme
    </button>
  )
}

beforeEach(() => {
  feed.events = []
  feed.summary = { total: 0, overdue: 0, upcoming_7_days: 0, upcoming_30_days: 0 }
  sx.creates = 0
  sx.app.setTheme.mockClear()
  setHouseholdTimeZone('UTC')
  localStorage.setItem('theme', 'light')
})

afterEach(() => {
  setHouseholdTimeZone(null)
  localStorage.removeItem('theme')
  document.documentElement.classList.remove('light', 'dark')
})

describe('Calendar theme', () => {
  it('EVENT_CALENDARS has no hex', () => {
    // RED before G2a-22: both palettes were hex picked for a dark page.
    const colours = Object.values(EVENT_CALENDARS).flatMap((calendar) => [
      ...Object.values(calendar.lightColors),
      ...Object.values(calendar.darkColors),
    ])
    expect(colours).toHaveLength(4 * 2 * 3)
    for (const colour of colours) expect(colour).toMatch(/^var\(--color-cal-/)
  })

  it('a theme switch reaches the mounted calendar', async () => {
    // RED before G2a-22: isDark was read from <html> once, at mount, and the
    // adapter never looks at config again.
    render(
      <ThemeProvider>
        <ThemeFlip />
        <CalendarPage />
      </ThemeProvider>,
    )
    const flip = await screen.findByRole('button', { name: 'flip theme' })
    expect(sx.creates).toBe(1)

    act(() => flip.click())
    expect(sx.app.setTheme).toHaveBeenLastCalledWith('dark')

    act(() => flip.click())
    expect(sx.app.setTheme).toHaveBeenLastCalledWith('light')

    const calls = sx.app.setTheme.mock.calls.map(([theme]) => theme)
    expect(calls.slice(calls.indexOf('dark'))).toEqual(['dark', 'light'])
    // Same instance the whole way: no remount, so the selected date and view stay put.
    expect(sx.creates).toBe(1)
  })
})

/** Two days out, so every event lands in the upcoming list. */
function soon(): string {
  return new Date(Date.now() + 2 * 86_400_000).toISOString().split('T')[0]
}

function reminder(id: number, extra: Record<string, unknown>): Record<string, unknown> {
  return {
    id: `reminder-${id}`,
    title: `Reminder ${id}`,
    date: soon(),
    type: 'maintenance',
    category: 'maintenance',
    urgency: 'medium',
    vehicle_vin: 'V1',
    vehicle_nickname: 'Test Car',
    is_completed: false,
    ...extra,
  }
}

// Tailwind palette steps and white ink read for a dark page only: amber-500 on
// white is about 2:1. Every chip, badge and filter here goes through tokens.
const STATUS_INK = /\btext-(?:warning|danger|success)\b/
const RAW_PALETTE = /\b(?:bg|text|border)-(?:amber|blue|red|purple|gray)-\d{3}(?:\/\d+)?\b|\btext-white\b/

describe('Calendar light-theme contrast', () => {
  it('no chip, badge, filter or card uses a raw palette step or white ink', async () => {
    // RED before the fold: est/mileage badges, filters and status chips were all raw steps.
    feed.summary = { total: 7, overdue: 1, upcoming_7_days: 6, upcoming_30_days: 6 }
    feed.events = [
      reminder(1, { status: 'overdue', km_until_due: '-10', is_estimated: true, due_mileage_km: '120000', notes: 'n' }),
      reminder(2, { status: 'due_soon', km_until_due: '100' }),
      reminder(3, { status: 'never_performed', km_until_due: '5000' }),
      reminder(4, { status: 'on_track' }),
      reminder(5, { status: 'snoozed' }),
      { ...reminder(6, {}), id: 'warranty-6', type: 'warranty', category: 'warranty' },
      { ...reminder(7, {}), id: 'insurance-7', type: 'insurance', category: 'insurance' },
    ]
    render(
      <ThemeProvider>
        <CalendarPage />
      </ThemeProvider>,
    )
    await screen.findByText('Reminder 7')
    // Bulk mode shows its own buttons, and the notes drawer has the Est badge.
    fireEvent.click(screen.getByRole('button', { name: 'calendar.misc.viewNotes' }))
    await screen.findByTestId('drawer')
    // Status words in warning or danger ink fail on white too; only icons keep that colour.
    const seen = (): string[] =>
      [...document.body.querySelectorAll('[class]')]
        .filter((el) => {
          const cls = el.getAttribute('class') ?? ''
          return RAW_PALETTE.test(cls) || (STATUS_INK.test(cls) && el.tagName.toLowerCase() !== 'svg')
        })
        .map((el) => `${el.tagName.toLowerCase()}: ${el.getAttribute('class')}`)
    const inNormalMode = seen()
    fireEvent.click(screen.getByRole('button', { name: 'calendar.misc.close' }))
    fireEvent.click(screen.getByRole('button', { name: 'calendar.bulkMode' }))
    fireEvent.click(screen.getAllByRole('button', { name: 'calendar.selectEvent' })[0])
    expect([...inNormalMode, ...seen()]).toEqual([])
  })

  it('the pattern catches what it is for', () => {
    // Guard the guard: each shape the fold removed is a hit, the tokens aren't.
    for (const cls of ['bg-amber-500/20 text-amber-500', 'bg-blue-600 text-white', 'text-purple-400', 'bg-gray-600']) {
      expect(cls).toMatch(RAW_PALETTE)
    }
    for (const cls of ['bg-warning text-on-status', 'bg-(--accent-soft) text-(--accent-fg)', 'bg-badge-bg text-badge-tx']) {
      expect(cls).not.toMatch(RAW_PALETTE)
    }
  })
})
