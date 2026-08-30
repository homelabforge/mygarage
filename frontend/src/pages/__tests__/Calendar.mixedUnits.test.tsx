/**
 * The calendar's distance read sites, for a client whose choices disagree.
 *
 * ★ WHY THIS FILE EXISTS AT ALL. `Calendar.tsx` had NO test of any kind, and
 * FOUR of task 6's twenty-seven call sites live in it, across three places a
 * reader looks:
 *
 *   the upcoming-list mileage badge          `formatDistance`      1 site
 *   the remaining-distance badge             `getDistanceUnit` +
 *                                            `kmToMiles`, behind a
 *                                            `system === 'imperial'`
 *                                            comparison              2 sites
 *   the notes drawer's "due at"              `formatDistance`      1 site
 *
 * ★ ALL THREE ARE DRIVEN, and the third one is why this sentence is a list
 * rather than a number. An earlier revision of this docstring named all three
 * and the test opened only two: the notes drawer never rendered, because the
 * fixture carried `notes: null` and the button that opens it is conditional on
 * notes existing. Half an inventory inside a docstring whose whole job is to
 * state the scope. The fixture now carries notes and the third case clicks
 * through to the drawer.
 *
 * Its manifest row rested entirely on findings the migration closes, so closing
 * them left an `audited` row with no evidence at all. This is the evidence.
 *
 * ★ `system` is D8-collapsed from VOLUME, so a `{volume:'L', distance:'mi'}`
 * client read `'metric'` and saw kilometres on all four. Both directions are
 * asserted, because a fix that merely inverted the branch satisfies one.
 *
 * Schedule-X is stubbed out: this page renders its month grid through a third
 * party that owns its own DOM, and none of the four sites is inside it. The
 * upcoming list beside it, and the drawer it opens, are ordinary JSX.
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
vi.mock('../../hooks/useTimeFormat', () => ({ useTimeFormat: () => ({ timeFormat: 24 }) }))
vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => 'en-US' }))

/** `system` DERIVED from the set, exactly as the real hook derives it. */
const unitPrefMock = vi.hoisted(() => ({ units: null as unknown as UnitSet }))
vi.mock('../../hooks/useUnitPreference', async () => {
  const { binarySystemFor } = await import('@/types/units')
  return {
    useUnitPreference: () => ({
      system: binarySystemFor(unitPrefMock.units.volume),
      showBoth: false,
      gallonStandard: unitPrefMock.units.secondary_gallon,
      units: unitPrefMock.units,
    }),
  }
})

// The two badges interpolate their distance into a key, and the global
// setup.ts mock discards options, so it would render the same string either way.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      options && 'distance' in options ? `${key} ${String(options.distance)}` : key,
    i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}))

import { IMPERIAL_UNITS, METRIC_UNITS } from '../../__tests__/factories'
import CalendarPage from '../Calendar'

/** Litres, but miles. `binarySystemFor('L')` is `'metric'`, so `system` lies. */
const LITRES_MILES: UnitSet = { ...METRIC_UNITS, distance: 'mi', speed: 'mph' }
/** The mirror: gallons, but kilometres. */
const GALLONS_KM: UnitSet = { ...IMPERIAL_UNITS, distance: 'km', speed: 'kmh' }

/**
 * Five days out, so the event lands inside the upcoming list's own 30-day
 * window. A fixed future date is a calendar bomb in the other direction: the
 * list drops anything more than thirty days away, so a hardcoded year would
 * make every assertion below vacuous the moment it was written.
 */
const IN_FIVE_DAYS = new Date(Date.now() + 5 * 24 * 60 * 60 * 1000)
  .toISOString()
  .slice(0, 10)

/** 80467 km is exactly 50000 mi; 16093.4 km is exactly 10000 mi. */
const EVENT = {
  id: 'reminder-1',
  title: 'Oil change',
  date: IN_FIVE_DAYS,
  type: 'maintenance',
  category: 'reminder',
  urgency: 'medium',
  vehicle_vin: 'V1',
  vehicle_nickname: 'Test Car',
  due_mileage_km: '80467',
  km_until_due: '16093.4',
  status: 'due_soon',
  is_recurring: false,
  is_estimated: false,
  // Load bearing: the notes button is conditional on this, and the drawer it
  // opens holds the fourth call site.
  notes: 'synthetic oil only',
}

beforeEach(() => {
  vi.clearAllMocks()
  unitPrefMock.units = METRIC_UNITS
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

describe('Calendar distance badges follow units.distance, not the collapsed system', () => {
  it('a litres-and-miles client reads miles in both badges, where `system` says metric', async () => {
    unitPrefMock.units = LITRES_MILES
    render(<CalendarPage />)

    // The due-mileage badge: 80467 km / 1.60934 = 50000 mi.
    await waitFor(() => expect(screen.getByText('50,000 mi')).toBeInTheDocument())
    // The remaining-distance badge: 16093.4 km / 1.60934 = 10000 mi. It also
    // carried the `system === 'imperial'` comparison and the raw kmToMiles call.
    expect(screen.getByText('calendar.misc.distanceLeft 10,000 mi')).toBeInTheDocument()
    expect(screen.queryByText('80,467 km')).not.toBeInTheDocument()
  })

  it('a gallons-and-kilometres client reads kilometres, where `system` says imperial', async () => {
    unitPrefMock.units = GALLONS_KM
    render(<CalendarPage />)

    await waitFor(() => expect(screen.getByText('80,467 km')).toBeInTheDocument())
    expect(screen.getByText('calendar.misc.distanceLeft 16,093 km')).toBeInTheDocument()
    expect(screen.queryByText('50,000 mi')).not.toBeInTheDocument()
  })

  it('the notes drawer reads the due mileage in the same unit as the badge behind it', async () => {
    // The fourth site, and the one that most needed driving: it is behind a
    // click, on a button that only exists when the event carries notes, so it
    // is the site a docstring is most likely to claim and a test least likely
    // to reach. Same 80467 km, same account, so the drawer and the list must
    // agree; disagreeing between them is the shape this whole phase removes.
    unitPrefMock.units = LITRES_MILES
    render(<CalendarPage />)

    const notes = await screen.findByTitle('calendar.misc.viewNotes')
    fireEvent.click(notes)

    expect(await screen.findByText('calendar.misc.dueAt 50,000 mi')).toBeInTheDocument()
    expect(screen.queryByText('calendar.misc.dueAt 80,467 km')).not.toBeInTheDocument()
  })
})
