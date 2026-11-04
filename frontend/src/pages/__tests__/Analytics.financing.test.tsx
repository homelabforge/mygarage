// Financing on the per-vehicle analytics page: bar series, monthly list suffix, CSV column.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { ReactNode } from 'react'
import type { MonthlyCostSummary, VehicleAnalytics } from '../../types/analytics'
import { setActiveDateFormat } from '../../constants/i18n'

const captured = vi.hoisted(() => ({ barCharts: [] as unknown[], lineCharts: [] as unknown[] }))
vi.mock('recharts', () => {
  const Pass = ({ children }: { children?: ReactNode }) => <>{children}</>
  return {
    ResponsiveContainer: Pass,
    LineChart: ({ data, children }: { data: unknown; children?: ReactNode }) => {
      captured.lineCharts.push(data)
      return <>{children}</>
    },
    BarChart: ({ data, children }: { data: unknown; children?: ReactNode }) => {
      captured.barCharts.push(data)
      return <>{children}</>
    },
    PieChart: Pass,
    RadarChart: Pass,
    Line: () => null,
    Bar: ({ name }: { name?: string }) => <span data-testid="bar-series">{name}</span>,
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

import { METRIC_UNITS } from '@/__tests__/factories'

vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({ system: 'metric', showBoth: false, units: METRIC_UNITS }),
  useAccountUnitPreference: () => ({ system: 'metric', showBoth: false, units: METRIC_UNITS }),
}))
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US' }),
}))
vi.mock('../../hooks/useCurrencySymbol', () => ({ useCurrencySymbol: () => '$' }))
vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => 'en-US' }))

import api from '../../services/api'
import Analytics from '../Analytics'

const mockedApiGet = vi.mocked(api).get

function month(overrides: Partial<MonthlyCostSummary>): MonthlyCostSummary {
  return {
    year: 2026,
    month: 1,
    month_name: 'January',
    total_service_cost: '0.00',
    total_fuel_cost: '0.00',
    total_def_cost: '0.00',
    total_spot_rental_cost: '0.00',
    total_financing_cost: '0.00',
    total_cost: '0.00',
    service_count: 0,
    fuel_count: 0,
    def_count: 0,
    spot_rental_count: 0,
    financing_count: 0,
    ...overrides,
  }
}

function analyticsWith(monthly: MonthlyCostSummary[], totalFinancing: string): VehicleAnalytics {
  // What the backend derives from the same rows: financing-only months are not tracked and
  // total_cost leaves financing out.
  const tracked = monthly.filter((m) => m.service_count + m.fuel_count + m.def_count + m.spot_rental_count > 0)
  const totalCost = monthly.reduce((sum, m) => sum + parseFloat(m.total_cost), 0).toFixed(2)
  return {
    vehicle_name: 'Test Car',
    vehicle_type: 'Car',
    vin: 'V1',
    days_owned: 100,
    total_km_driven: null,
    average_km_per_month: null,
    cost_analysis: {
      total_cost: totalCost,
      average_monthly_cost: '10.00',
      months_tracked: tracked.length,
      service_count: 0,
      fuel_count: 2,
      def_count: 0,
      cost_per_km: null,
      rolling_avg_3m: null,
      rolling_avg_6m: null,
      rolling_avg_12m: null,
      trend_direction: 'stable',
      total_service_cost: '0.00',
      total_fuel_cost: '100.00',
      total_def_cost: '0.00',
      total_financing_cost: totalFinancing,
      monthly_breakdown: monthly,
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
  } satisfies VehicleAnalytics
}

const WITH_FINANCING = analyticsWith(
  [
    month({ month: 1, month_name: 'January', total_fuel_cost: '40.00', fuel_count: 1, total_cost: '40.00' }),
    month({
      month: 2,
      month_name: 'February',
      total_fuel_cost: '60.00',
      fuel_count: 1,
      total_financing_cost: '450.00',
      financing_count: 1,
      total_cost: '60.00',
    }),
  ],
  '450.00'
)
const WITHOUT_FINANCING = analyticsWith(
  [month({ month: 1, month_name: 'January', total_fuel_cost: '40.00', fuel_count: 1, total_cost: '40.00' })],
  '0.00'
)

// Fuel in Jan/Mar/May, only a lease payment in Feb/Apr. Main (which had no financing rows) and
// the backend's rolling_avg_3m both put May's 3-month average at (100 + 300 + 500) / 3 = 300.
const WITH_LEASE_ONLY_MONTHS = analyticsWith(
  [
    month({ month: 1, month_name: 'January', total_fuel_cost: '100.00', fuel_count: 1, total_cost: '100.00' }),
    month({ month: 2, month_name: 'February', total_financing_cost: '450.00', financing_count: 1 }),
    month({ month: 3, month_name: 'March', total_fuel_cost: '300.00', fuel_count: 1, total_cost: '300.00' }),
    month({ month: 4, month_name: 'April', total_financing_cost: '450.00', financing_count: 1 }),
    month({ month: 5, month_name: 'May', total_fuel_cost: '500.00', fuel_count: 1, total_cost: '500.00' }),
  ],
  '900.00'
)
const FINANCING_ONLY = analyticsWith(
  [month({ month: 1, month_name: 'January', total_financing_cost: '450.00', financing_count: 1 })],
  '450.00'
)

function respondWith(analytics: VehicleAnalytics): void {
  mockedApiGet.mockImplementation((url: string) => {
    if (url.endsWith('/vendors')) return Promise.reject(new Error('no vendors'))
    if (url.endsWith('/seasonal')) return Promise.reject(new Error('no seasonal'))
    return Promise.resolve({ data: analytics })
  })
}

function renderAnalytics(): ReturnType<typeof render> {
  return render(
    <MemoryRouter initialEntries={['/vehicles/V1/analytics']}>
      <Routes>
        <Route path="/vehicles/:vin/analytics" element={<Analytics />} />
      </Routes>
    </MemoryRouter>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  captured.barCharts = []
  captured.lineCharts = []
})

afterEach(() => {
  cleanup()
})

describe('Analytics — financing in the monthly cost trend', () => {
  it('adds a Financing series to the stacked monthly chart when the vehicle has financing', async () => {
    respondWith(WITH_FINANCING)
    renderAnalytics()

    await screen.findByText('vehicle.monthlyCostTrend')
    const series = screen.getAllByTestId('bar-series').map((el) => el.textContent)
    expect(series).toContain('vehicle.categoryFinancing')
  })

  it('feeds the chart the per-month financing amount so the bars add up to the row totals', async () => {
    respondWith(WITH_FINANCING)
    renderAnalytics()

    await screen.findByText('vehicle.monthlyCostTrend')
    const monthly = captured.barCharts.find(
      (d): d is Array<{ month: string; Fuel: number; Financing?: number }> =>
        Array.isArray(d) && d.length > 0 && typeof d[0] === 'object' && d[0] !== null && 'Fuel' in d[0]
    )
    expect(monthly).toBeDefined()
    const feb = monthly!.find((m) => m.month.startsWith('Feb'))
    expect(feb).toMatchObject({ Fuel: 60, Financing: 450 })
  })

  it('omits the Financing series entirely when there is no financing', async () => {
    respondWith(WITHOUT_FINANCING)
    renderAnalytics()

    await screen.findByText('vehicle.monthlyCostTrend')
    const series = screen.getAllByTestId('bar-series').map((el) => el.textContent)
    expect(series).not.toContain('vehicle.categoryFinancing')
  })

  it('names financing in the monthly list row, like DEF and spot rental', async () => {
    respondWith(WITH_FINANCING)
    renderAnalytics()

    // "$60.00" also matches the (unrelated) six-month cost-projection figure, so scope to the
    // bold monthly-row total specifically.
    const totals = await screen.findAllByText('$60.00')
    expect(totals.some((el) => el.className.includes('font-bold'))).toBe(true)
    expect(screen.getByText(/vehicle\.monthFinancingSuffix \(\$450\.00\)/)).toBeInTheDocument()
  })

  it('does not add a financing suffix to months without financing', async () => {
    respondWith(WITH_FINANCING)
    renderAnalytics()

    await screen.findAllByText('$60.00')
    expect(screen.getAllByText(/vehicle\.monthFinancingSuffix/)).toHaveLength(1)
  })
})

describe('Analytics — financing in the CSV export', () => {
  async function exportedCsv(): Promise<string> {
    const blobs: Blob[] = []
    const createObjectURL = vi
      .spyOn(URL, 'createObjectURL')
      .mockImplementation((blob: Blob | MediaSource) => {
        blobs.push(blob as Blob)
        return 'blob:mock'
      })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    try {
      fireEvent.click(screen.getByRole('button', { name: 'exportMenu.export' }))
      fireEvent.click(await screen.findByRole('menuitem', { name: 'CSV' }))
      await waitFor(() => expect(blobs).toHaveLength(1))
      return await blobs[0].text()
    } finally {
      createObjectURL.mockRestore()
      click.mockRestore()
    }
  }

  it('carries the financing total and a per-month Financing Cost column', async () => {
    respondWith(WITH_FINANCING)
    renderAnalytics()
    await screen.findByText('vehicle.monthlyCostTrend')

    const csv = await exportedCsv()
    expect(csv).toContain('"Financing Cost"')
    expect(csv).toContain('"Financing Count"')
    expect(csv).toMatch(/"February","2026","0\.00","60\.00","0\.00","450\.00","60\.00"/)
    expect(csv).toContain('"Total Financing","$450.00"')
  })
})

describe('Analytics — the cost trend line skips financing-only months', () => {
  type TrendPoint = { month: string; rollingAvg3m: number | null; rollingAvg6m: number | null }

  function trendLine(): TrendPoint[] | undefined {
    return captured.lineCharts.find(
      (d): d is TrendPoint[] =>
        Array.isArray(d) && d.length > 0 && typeof d[0] === 'object' && d[0] !== null && 'rollingAvg3m' in d[0]
    )
  }

  it('averages the last three running-cost months, not the last three rows', async () => {
    respondWith(WITH_LEASE_ONLY_MONTHS)
    renderAnalytics()

    await screen.findByText('vehicle.costTrendsTitle')
    // Windowing over the padded rows gives Mar, Apr, May -> (300 + 500) / 2 = 400.
    expect(trendLine()?.find((m) => m.month.startsWith('May'))?.rollingAvg3m).toBe(300)
  })

  it('leaves lease-only months off the trend line', async () => {
    respondWith(WITH_LEASE_ONLY_MONTHS)
    renderAnalytics()

    await screen.findByText('vehicle.costTrendsTitle')
    expect(trendLine()?.map((m) => m.month)).toEqual(['Jan 2026', 'Mar 2026', 'May 2026'])
  })

  it('hides the trend chart when the vehicle only has financing', async () => {
    respondWith(FINANCING_ONLY)
    renderAnalytics()

    await screen.findByText('vehicle.monthlyCostTrend')
    expect(screen.queryByText('vehicle.costTrendsTitle')).not.toBeInTheDocument()
    expect(trendLine()).toBeUndefined()
  })
})

describe('Analytics — PDF export', () => {
  it('asks for the date order the page shows (#278)', async () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    setActiveDateFormat('dmy')
    try {
      respondWith(WITH_FINANCING)
      renderAnalytics()
      fireEvent.click(await screen.findByRole('button', { name: 'exportMenu.export' }))
      fireEvent.click(await screen.findByRole('menuitem', { name: 'PDF' }))
      expect(open).toHaveBeenCalledTimes(1)
      const url = new URL(String(open.mock.calls[0][0]), 'http://x')
      expect(url.pathname).toBe('/api/analytics/vehicles/V1/export')
      expect(url.searchParams.get('date_format')).toBe('dmy')
    } finally {
      setActiveDateFormat('mdy')
      open.mockRestore()
    }
  })
})
