/**
 * Every consumption and fuel-rate RENDERING on the analytics page, pinned.
 *
 * ★ WHY THIS FILE EXISTS, and it is a coverage hole rather than a new subject.
 * Task 6b migrated 31 read sites onto the resolved tokens, and 18 of them are in
 * `Analytics.tsx`. Its mutation table contributed two mutants for that file, both
 * on chart DATA, so the thirteen TEXT renderings were unpinned: review round 1
 * rerouted them from `u.consumption` to `u.volume` in four batches, which changes
 * both the number and the label a reader sees (`9.42 L/100km` becomes
 * `2.49 gal`), and every batch compiled clean and left the suite at exactly
 * 1979/1979. Correct code, no guard. This file is the guard.
 *
 * ★ ONE DISTINCT CANONICAL VALUE PER SITE. Sixteen sites all rendering `8.50`
 * would be pinned by a single assertion and the other fifteen could be deleted
 * unnoticed, which is the same defect one level up. Every figure below is
 * unique, so each `getByText` names exactly one rendering, and the two that
 * SHARE a value (the summary card and the details card both read
 * `average_l_per_100km`) are asserted with `getAllByText` and a count.
 *
 * ★ THE SET IS `{volume:'gal_us', consumption:'l_100km'}`, which no binary
 * system can express. `binarySystemFor('gal_us')` is `'imperial'`, so anything
 * deriving consumption from the volume token, or from the collapsed system,
 * answers MPG here. The mirror block uses litres with MPG so that no assertion
 * can be satisfied by a branch that simply always answers one of them.
 *
 * ★ THE CHART LABELS, THE LEGEND NAMES AND THE TOOLTIPS ARE CAPTURED, not read
 * from the DOM. `recharts` renders 0x0 in jsdom, so this file stubs the same
 * component boundary `Analytics.hours.test.tsx` does and additionally records
 * `YAxis`, `Line` and `Tooltip` props. A tooltip's `content` is a function, so
 * it is INVOKED with a payload and its output rendered; a stub that returned
 * null would leave three more sites unpinned.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { ReactNode, ReactElement } from 'react'
import type { VehicleAnalytics } from '../../types/analytics'

/** Everything the recharts stubs record, for assertions the DOM cannot reach. */
const captured = vi.hoisted(() => ({
  yAxes: [] as { yAxisId?: string; label?: { value?: unknown } }[],
  lines: [] as { dataKey?: string; name?: unknown }[],
  tooltips: [] as { content?: unknown }[],
}))

vi.mock('recharts', () => {
  const Pass = ({ children }: { children?: ReactNode }) => <>{children}</>
  return {
    ResponsiveContainer: Pass,
    LineChart: ({ children }: { children?: ReactNode }) => <>{children}</>,
    BarChart: Pass,
    PieChart: Pass,
    RadarChart: Pass,
    Line: (props: { dataKey?: string; name?: unknown }) => {
      captured.lines.push(props)
      return null
    },
    Bar: () => null,
    Pie: () => null,
    Cell: () => null,
    Radar: () => null,
    PolarGrid: () => null,
    PolarAngleAxis: () => null,
    PolarRadiusAxis: () => null,
    XAxis: () => null,
    YAxis: (props: { yAxisId?: string; label?: { value?: unknown } }) => {
      captured.yAxes.push(props)
      return null
    },
    CartesianGrid: () => null,
    Tooltip: (props: { content?: unknown }) => {
      captured.tooltips.push(props)
      return null
    },
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

// LOCAL i18n mock that RETAINS interpolated values. The global `t: (key) => key`
// renders `vehicle.recentBaseline` whatever the two figures inside it are, so a
// DOM assertion against it cannot tell 6.11 L/100km from 1.61 gal or from a
// dropped interpolation entirely. `defaultValue` wins, matching i18next for a
// key no bundle holds.
//
// ★ `t` and `i18n` are HOISTED to module scope, not rebuilt per call. `setup.ts`
// documents why at length: this page lists `t` in effect dependency arrays, so a
// fresh `t` per render re-fires the analytics fetch forever, the page sits in its
// loading branch, and a controlled input loses the value a test just typed into
// it. The first draft of this file did exactly that and the compare request was
// never sent.
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

import { IMPERIAL_UNITS, METRIC_UNITS } from '@/__tests__/factories'
import type { UnitSet } from '@/types/units'
import { binarySystemFor } from '@/types/units'

const unitPreferenceMock = vi.fn()
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => unitPreferenceMock(),
}))
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US' }),
}))
vi.mock('../../hooks/useCurrencySymbol', () => ({ useCurrencySymbol: () => '$' }))
vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => 'en-US' }))

import api from '../../services/api'
import Analytics from '../Analytics'

const mockedApiGet = vi.mocked(api).get

/** Gallons for volume, L/100km for consumption. No binary system says this. */
const GALLONS_L100KM: UnitSet = { ...IMPERIAL_UNITS, consumption: 'l_100km' }
/** The mirror: litres for volume, MPG for consumption. */
const LITRES_MPG: UnitSet = { ...METRIC_UNITS, consumption: 'mpg_us' }

/**
 * One distinct canonical L/100km per rendering, so each assertion names one site.
 *
 * Two decimals in `l_100km`, one in `mpg_us`. The MPG column is hand-computed as
 * 235.214 / value and is what the mirror block asserts.
 *
 *   6.11 -> 38.5 MPG   6.22 -> 37.8   6.33 -> 37.2   6.44 -> 36.5
 *   6.55 -> 35.9       6.66 -> 35.3   6.77 -> 34.7   6.88 -> 34.2
 */
const ALERT_RECENT = '6.11'
const ALERT_BASELINE = '6.22'
const AVERAGE = '6.33'
const BEST = '6.44'
const WORST = '6.55'
const LATEST = '6.66'
const POINT = '6.77'
const PERIOD1 = '6.88'
const PERIOD2 = '6.99'

function baseAnalytics(overrides: Partial<VehicleAnalytics> = {}): VehicleAnalytics {
  return {
    vehicle_name: 'Test Car',
    vehicle_type: 'Car',
    vin: 'V1',
    days_owned: 100,
    total_km_driven: null,
    average_km_per_month: null,
    cost_analysis: {
      total_cost: '0.00',
      average_monthly_cost: '0.00',
      months_tracked: 0,
      service_count: 0,
      fuel_count: 0,
      def_count: 0,
      cost_per_km: null,
      rolling_avg_3m: null,
      rolling_avg_6m: null,
      rolling_avg_12m: null,
      trend_direction: 'stable',
      total_service_cost: '0.00',
      total_fuel_cost: '0.00',
      total_def_cost: '0.00',
      // Empty on purpose: the cost-trend chart must not mount, so every
      // captured YAxis / Line / Tooltip below belongs to a chart under test.
      monthly_breakdown: [],
      service_type_breakdown: [],
      anomalies: [],
    },
    cost_projection: {
      monthly_average: '0.00',
      six_month_projection: '0.00',
      twelve_month_projection: '0.00',
      assumptions: 'Projection assumes spending remains at recent averages.',
    },
    fuel_economy: {
      average_l_per_100km: AVERAGE,
      best_l_per_100km: BEST,
      worst_l_per_100km: WORST,
      recent_l_per_100km: LATEST,
      trend: 'stable',
      data_points: [
        { date: '2026-07-01', l_per_100km: POINT, odometer_km: '1000', liters: '40', cost: '60.00' },
      ],
    },
    hours_economy: {
      average_l_per_hr: '3.80',
      average_cost_per_hr: '2.75',
      best_l_per_hr: '3.80',
      worst_l_per_hr: '3.80',
      recent_l_per_hr: '3.80',
      recent_cost_per_hr: '2.75',
      trend: 'stable',
      data_points: [
        { date: '2026-07-01', engine_hours: '810.0', l_per_hr: '3.80', cost_per_hr: '2.75', liters: '19.00', cost: '13.68' },
      ],
    },
    hours_accumulated: [],
    fuel_alerts: [
      {
        code: 'economy_drop',
        severity: 'warning',
        title: 'Economy drop',
        message: 'Economy dropped',
        percent: 12,
        recent_l_per_100km: ALERT_RECENT,
        baseline_l_per_100km: ALERT_BASELINE,
      },
    ],
    service_history: [],
    predictions: [],
    propane_analysis: null,
    spot_rental_analysis: null,
    def_analysis: null,
    ...overrides,
  } as unknown as VehicleAnalytics
}

const COMPARISON = {
  period1_label: 'Period one',
  period1_total_cost: '100.00',
  period1_service_count: 1,
  period1_avg_l_per_100km: PERIOD1,
  period2_label: 'Period two',
  period2_total_cost: '200.00',
  period2_service_count: 2,
  period2_avg_l_per_100km: PERIOD2,
  cost_change_percent: '10.0',
  cost_change_amount: '100.00',
  service_count_change: 1,
  l_per_100km_change_percent: null,
  category_changes: [],
}

function mockAnalyticsResponse(analytics: VehicleAnalytics): void {
  mockedApiGet.mockImplementation((url: string) => {
    if (url.endsWith('/vendors')) return Promise.reject(new Error('no vendors'))
    if (url.endsWith('/seasonal')) return Promise.reject(new Error('no seasonal'))
    if (url.includes('/compare?')) return Promise.resolve({ data: COMPARISON })
    return Promise.resolve({ data: analytics })
  })
}

function renderAnalytics(): void {
  render(
    <MemoryRouter initialEntries={['/vehicles/V1/analytics']}>
      <Routes>
        <Route path="/vehicles/:vin/analytics" element={<Analytics />} />
      </Routes>
    </MemoryRouter>
  )
}

/** Every captured Y-axis label value, in mount order. */
function axisLabels(): unknown[] {
  return captured.yAxes.map((a) => a.label?.value)
}

/** Every captured `Line` name, in mount order. */
function lineNames(): unknown[] {
  return captured.lines.map((l) => l.name)
}

/**
 * Every captured tooltip's rendered text, for one payload.
 *
 * The payload carries BOTH chart shapes, so neither tooltip has to be invoked
 * with a shape it does not understand: a `try`/`catch` here would swallow a
 * tooltip that had stopped rendering and report the guard as clean.
 */
function tooltipTexts(): string[] {
  const payload = {
    active: true,
    label: 'Jul 1',
    payload: [
      {
        value: 1,
        payload: {
          lPer100km: parseFloat(POINT),
          odometer_km: 1000,
          lPerHr: 3.8,
          costPerHr: 2.75,
        },
      },
    ],
  }
  return captured.tooltips.map((tip) => {
    const content = tip.content as (p: typeof payload) => ReactElement | null
    const node = content(payload)
    if (node === null) return ''
    const { container, unmount } = render(<>{node}</>)
    const text = container.textContent ?? ''
    unmount()
    return text
  })
}

/** Mount the page for one resolved set and wait for the alert card. */
async function mountWith(units: UnitSet): Promise<void> {
  unitPreferenceMock.mockReturnValue({
    system: binarySystemFor(units.volume),
    showBoth: false,
    units,
  })
  mockAnalyticsResponse(baseAnalytics())
  renderAnalytics()
  await waitFor(() => expect(screen.getByText('Economy dropped')).toBeInTheDocument())
}

beforeEach(() => {
  vi.clearAllMocks()
  captured.yAxes = []
  captured.lines = []
  captured.tooltips = []
})

afterEach(() => {
  cleanup()
})

describe('Analytics — every consumption rendering reads units.consumption', () => {
  it('★ a gallons-and-L/100km account reads L/100km at all thirteen text sites', async () => {
    await mountWith(GALLONS_L100KM)

    // The fuel-alert card composes both figures into one interpolated sentence.
    expect(
      screen.getByText(`vehicle.recentBaseline (${ALERT_RECENT} L/100km | ${ALERT_BASELINE} L/100km)`)
    ).toBeInTheDocument()

    // The summary card and the fuel-economy-details average card read the SAME
    // field, so the count is what pins both: reroute either and it drops to one.
    expect(screen.getAllByText(`${AVERAGE} L/100km`)).toHaveLength(2)
    expect(screen.getByText(`${BEST} L/100km`)).toBeInTheDocument()
    expect(screen.getByText(`${WORST} L/100km`)).toBeInTheDocument()
    expect(screen.getByText(`${LATEST} L/100km`)).toBeInTheDocument()
    // The data table's economy cell.
    expect(screen.getByText(`${POINT} L/100km`)).toBeInTheDocument()

    // Nothing on this page may render the volume conversion of a consumption
    // figure: 6.33 L through the gal_us adapter is 1.67 gal.
    expect(screen.queryByText('1.67 gal')).not.toBeInTheDocument()
  })

  it('★ the economy chart labels its axis, its line and its tooltip in L/100km', async () => {
    await mountWith(GALLONS_L100KM)

    expect(axisLabels()).toContain('L/100km')
    expect(lineNames()).toContain('vehicle.fuelEconomyUnitLabel (L/100km)')
    expect(tooltipTexts().some((text) => text.includes(`${POINT} L/100km`))).toBe(true)
  })

  it('★ the fuel-rate chart labels its axis, its line and its tooltip in gal/hr', async () => {
    await mountWith(GALLONS_L100KM)

    // 3.80 L/hr / 3.78541 = 1.00 gal/hr.
    expect(axisLabels()).toContain('gal/hr')
    expect(lineNames()).toContain('vehicle.fuelRateUnitLabel (gal/hr)')
    expect(tooltipTexts().some((text) => text.includes('1.00 gal/hr'))).toBe(true)
  })

  it('★ the period-comparison summaries read L/100km', async () => {
    await mountWith(GALLONS_L100KM)

    fireEvent.click(screen.getByText('vehicle.comparePeriods'))
    // The toggle re-renders the page, and the vendor/seasonal fetches this
    // fixture rejects put it briefly back through its loading branch, so the
    // four inputs have to be WAITED for rather than read on the next line.
    await waitFor(() =>
      expect(document.querySelectorAll('input[type="date"]')).toHaveLength(4)
    )
    document.querySelectorAll('input[type="date"]').forEach((input, i) => {
      fireEvent.change(input, { target: { value: `2026-0${i + 1}-01` } })
    })
    fireEvent.click(await screen.findByText('vehicle.runComparison'))
    expect(await screen.findByText(`${PERIOD1} L/100km`)).toBeInTheDocument()
    expect(screen.getByText(`${PERIOD2} L/100km`)).toBeInTheDocument()
  })

  it('★ the MIRROR: a litres-and-MPG account reads MPG everywhere instead', async () => {
    // Without this, every assertion above is satisfied by a branch that always
    // answers L/100km, which is what the metric leg of the retired formatter did.
    await mountWith(LITRES_MPG)

    // 235.214 / 6.11 = 38.5, / 6.22 = 37.8, / 6.33 = 37.2, / 6.44 = 36.5,
    // / 6.66 = 35.3, / 6.77 = 34.7.
    expect(screen.getByText('vehicle.recentBaseline (38.5 MPG | 37.8 MPG)')).toBeInTheDocument()
    expect(screen.getAllByText('37.2 MPG')).toHaveLength(2)
    expect(screen.getByText('36.5 MPG')).toBeInTheDocument()
    expect(screen.getByText('35.9 MPG')).toBeInTheDocument()
    expect(screen.getByText('35.3 MPG')).toBeInTheDocument()
    expect(screen.getByText('34.7 MPG')).toBeInTheDocument()
    expect(screen.queryByText(`${AVERAGE} L/100km`)).not.toBeInTheDocument()

    expect(axisLabels()).toContain('MPG')
    expect(lineNames()).toContain('vehicle.fuelEconomyUnitLabel (MPG)')
    // Volume is litres here, so the rate label follows the volume token, not the
    // consumption one: 3.80 L/hr stays 3.80 L/hr.
    expect(axisLabels()).toContain('L/hr')
    expect(tooltipTexts().some((text) => text.includes('3.80 L/hr'))).toBe(true)
  })
})
