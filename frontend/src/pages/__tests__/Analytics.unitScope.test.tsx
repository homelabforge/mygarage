/**
 * The vehicle analytics page scopes itself to the vehicle's odometer unit
 * (#172) from the analytics response, so it loads once behind one spinner.
 * Ported from the old route wrapper's test, which fetched the whole vehicle
 * first just to read `distance_unit`.
 *
 * The account here is metric throughout, and every vehicle that should read in
 * miles is a `mi` vehicle, so a page that falls back to the account shows km
 * and fails.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, render, screen, cleanup, fireEvent } from '@testing-library/react'
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom'
import type { ReactNode } from 'react'
import type { VehicleAnalytics } from '../../types/analytics'
import { METRIC_UNITS } from '../../__tests__/factories'

vi.mock('recharts', () => {
  const Pass = ({ children }: { children?: ReactNode }) => <>{children}</>
  return {
    ResponsiveContainer: Pass,
    LineChart: Pass,
    BarChart: Pass,
    PieChart: Pass,
    RadarChart: Pass,
    Line: () => null,
    Bar: () => null,
    Pie: () => null,
    Cell: () => null,
    Radar: () => null,
    PolarGrid: () => null,
    PolarAngleAxis: () => null,
    PolarRadiusAxis: () => null,
    XAxis: () => null,
    YAxis: () => null,
    CartesianGrid: () => null,
    Tooltip: () => null,
    Legend: () => null,
  }
})

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    defaults: { headers: { common: {} } },
  },
}))

// Keeps interpolated values, so the distance line shows its unit. `t` lives at
// module scope because the page lists it in effect deps.
vi.mock('react-i18next', () => {
  const t = (key: string, options?: Record<string, unknown>): string => {
    if (options?.defaultValue !== undefined) return String(options.defaultValue)
    const values = Object.entries(options ?? {}).map(([, v]) => String(v))
    return values.length > 0 ? `${key} (${values.join(' | ')})` : key
  }
  const i18n = { language: 'en', changeLanguage: () => Promise.resolve() }
  return {
    useTranslation: () => ({ t, i18n }),
    Trans: ({ children }: { children: ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

// The real unit hooks run against a metric account.
const authValue = {
  user: { unit_preference: 'metric', show_both_units: false, resolved_units: METRIC_UNITS },
  isAuthenticated: true,
  defaultUnitPrefs: null,
}
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => authValue }))
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US' }),
}))
vi.mock('../../hooks/useCurrencySymbol', () => ({ useCurrencySymbol: () => '$' }))
vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => 'en-US' }))

import api from '../../services/api'
import Analytics from '../Analytics'

const mockedApiGet = vi.mocked(api).get

// 160.9344 km is exactly 100 mi, and reads 161 km on the account.
const MI_LINE = 'vehicle.distanceDriven (100 mi)'
const KM_LINE = 'vehicle.distanceDriven (161 km)'

function baseAnalytics(overrides: Partial<VehicleAnalytics> = {}): VehicleAnalytics {
  return {
    vehicle_name: 'Test Car',
    vehicle_type: 'Car',
    distance_unit: null,
    vin: 'V1',
    days_owned: 100,
    total_km_driven: '160.9344',
    average_km_per_month: null,
    cost_analysis: {
      total_cost: '100.00',
      average_monthly_cost: '10.00',
      months_tracked: 10,
      service_count: 0,
      fuel_count: 2,
      def_count: 0,
      cost_per_km: '0.02',
      rolling_avg_3m: null,
      rolling_avg_6m: null,
      rolling_avg_12m: null,
      trend_direction: 'stable',
      total_service_cost: '0.00',
      total_fuel_cost: '100.00',
      total_def_cost: '0.00',
      total_financing_cost: '0.00',
      monthly_breakdown: [],
      service_type_breakdown: [],
      anomalies: [],
    },
    cost_projection: {
      monthly_average: '10.00',
      six_month_projection: '60.00',
      twelve_month_projection: '120.00',
      assumptions: 'Projection assumes spending remains at recent averages.',
    },
    fuel_economy: {
      average_l_per_100km: null,
      best_l_per_100km: null,
      worst_l_per_100km: null,
      recent_l_per_100km: null,
      trend: 'stable',
      data_points: [],
    },
    hours_economy: {
      average_l_per_hr: null,
      average_cost_per_hr: null,
      best_l_per_hr: null,
      worst_l_per_hr: null,
      recent_l_per_hr: null,
      recent_cost_per_hr: null,
      trend: 'stable',
      data_points: [],
    },
    hours_accumulated: [],
    fuel_alerts: [],
    service_history: [],
    predictions: [],
    propane_analysis: null,
    spot_rental_analysis: null,
    def_analysis: null,
    ...overrides,
  } satisfies VehicleAnalytics
}

/** Answers the analytics request; vendors and seasonal fail, which the page shrugs off. */
function respondWith(analytics: VehicleAnalytics): void {
  mockedApiGet.mockImplementation((url: string) => {
    if (url === `/analytics/vehicles/${analytics.vin}`) return Promise.resolve({ data: analytics })
    return Promise.reject(new Error(`unmocked ${url}`))
  })
}

/** Every path the page requested, exactly as passed to api.get. */
function requestedPaths(): string[] {
  return mockedApiGet.mock.calls.map(([url]) => String(url))
}

function renderAt(vin: string): ReturnType<typeof render> {
  return render(
    <MemoryRouter initialEntries={[`/vehicles/${vin}/analytics`]}>
      <Link to="/vehicles/B/analytics">go to B</Link>
      <Routes>
        <Route path="/vehicles/:vin/analytics" element={<Analytics />} />
      </Routes>
    </MemoryRouter>,
  )
}

function setOnline(value: boolean): void {
  Object.defineProperty(navigator, 'onLine', { value, configurable: true })
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  setOnline(true)
})

afterEach(() => {
  cleanup()
  setOnline(true)
})

describe('Analytics: the vehicle unit comes from the analytics response', () => {
  it('a mi vehicle reads in miles on a metric account, from one request', async () => {
    respondWith(baseAnalytics({ distance_unit: 'mi' }))
    renderAt('V1')

    expect(screen.getByRole('status')).toBeInTheDocument()
    expect(await screen.findByText(MI_LINE)).toBeInTheDocument()
    expect(screen.queryByText(KM_LINE)).not.toBeInTheDocument()

    // Exact paths: the page also asks for /vendors and /seasonal under the same prefix.
    const paths = requestedPaths()
    expect(paths.filter((p) => p === '/analytics/vehicles/V1')).toHaveLength(1)
    expect(paths.filter((p) => p === '/vehicles/V1')).toHaveLength(0)
  })

  it('a vehicle with no unit follows the account', async () => {
    respondWith(baseAnalytics({ distance_unit: null }))
    renderAt('V1')

    expect(await screen.findByText(KM_LINE)).toBeInTheDocument()
    expect(screen.queryByText(MI_LINE)).not.toBeInTheDocument()
  })

  it('offline, the cached copy scopes the page from its own distance_unit', async () => {
    mockedApiGet.mockRejectedValue(new Error('offline'))
    setOnline(false)
    localStorage.setItem(
      'analytics-cache-V1',
      JSON.stringify({ timestamp: Date.now(), data: baseAnalytics({ distance_unit: 'mi' }) }),
    )
    renderAt('V1')

    expect(await screen.findByText(MI_LINE)).toBeInTheDocument()
    expect(screen.getByText('vehicle.offlineCached')).toBeInTheDocument()
    expect(screen.queryByText(KM_LINE)).not.toBeInTheDocument()
  })

  it('offline, a cached copy from before the field existed reads in account units', async () => {
    mockedApiGet.mockRejectedValue(new Error('offline'))
    setOnline(false)
    // Written before distance_unit rode along, so the key is missing outright.
    const { distance_unit: _dropped, ...legacy } = baseAnalytics()
    localStorage.setItem('analytics-cache-V1', JSON.stringify({ timestamp: Date.now(), data: legacy }))
    renderAt('V1')

    expect(await screen.findByText(KM_LINE)).toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.queryByText(MI_LINE)).not.toBeInTheDocument()
  })

  it("A's late response never sets B's unit", async () => {
    // A is km and B is mi on a km account. If A's late report replaced B's scope,
    // B would drop to the account's km and this would fail.
    const deferred = new Map<string, (data: VehicleAnalytics) => void>()
    mockedApiGet.mockImplementation((url: string) => {
      if (url === '/analytics/vehicles/A' || url === '/analytics/vehicles/B') {
        return new Promise((resolve) => {
          deferred.set(url, (data) => resolve({ data }))
        })
      }
      return Promise.reject(new Error(`unmocked ${url}`))
    })
    renderAt('A')
    expect(deferred.has('/analytics/vehicles/A')).toBe(true)

    fireEvent.click(screen.getByText('go to B'))
    expect(deferred.has('/analytics/vehicles/B')).toBe(true)

    await act(async () => {
      deferred.get('/analytics/vehicles/B')?.(
        baseAnalytics({ vin: 'B', distance_unit: 'mi', total_km_driven: '160.9344' }),
      )
    })
    expect(await screen.findByText(MI_LINE)).toBeInTheDocument()

    await act(async () => {
      deferred.get('/analytics/vehicles/A')?.(
        baseAnalytics({ vin: 'A', distance_unit: 'km', total_km_driven: '1000' }),
      )
    })
    expect(screen.getByText(MI_LINE)).toBeInTheDocument()
    expect(screen.queryByText(KM_LINE)).not.toBeInTheDocument()
    expect(screen.queryByText(/vehicle\.distanceDriven \(1,000 km\)/)).not.toBeInTheDocument()
  })
})
