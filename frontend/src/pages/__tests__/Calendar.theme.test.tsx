/**
 * Calendar colours follow the app theme (G2a-22).
 *
 * The React adapter builds the Schedule-X app once, in a mount-only effect,
 * and ignores config after that. So a theme switch has to reach the mounted
 * instance through setTheme, and the event colours have to be tokens that
 * flip with html.light rather than hex baked in at mount.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, screen } from '@testing-library/react'
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
vi.mock('../../services/api', () => ({
  default: {
    get: (url: string) =>
      Promise.resolve(
        url === '/vehicles'
          ? { data: { vehicles: [] } }
          : { data: { events: [], summary: { total: 0, overdue: 0, upcoming_7_days: 0, upcoming_30_days: 0 } } },
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
