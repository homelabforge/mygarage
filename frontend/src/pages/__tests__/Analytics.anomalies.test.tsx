import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, cleanup } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { ReactNode } from 'react'
import type { VehicleAnalytics, AnomalyAlert } from '../../types/analytics'
import { METRIC_UNITS } from '../../__tests__/factories'

// ─────────────────────────────────────────────────────────────────────────────
// Issue #131 regression: the vehicle Analytics page rendered `alert.message`,
// a sentence the BACKEND composes with a hardcoded "$" and untranslated
// English (analytics.py:294). With PLN selected every other value on the page
// formatted as zł and that one line still said "$3400.00".
//
// This file needs its own react-i18next mock: the global one in
// __tests__/setup.ts is `t: key => key` and DISCARDS interpolation, so under it
// the currency-formatted values never reach the DOM and an assertion about
// them cannot fail. Here `t` appends the options, so the test can see exactly
// what was interpolated. vi.mock is file-scoped, so this does not disturb
// Analytics.hours.test.tsx.
// ─────────────────────────────────────────────────────────────────────────────
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key}|${JSON.stringify(opts)}` : key,
    i18n: { language: 'pl', changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}))

vi.mock('recharts', () => {
  const Pass = ({ children }: { children?: ReactNode }) => <>{children}</>
  return {
    ResponsiveContainer: Pass, LineChart: Pass, BarChart: Pass, PieChart: Pass,
    RadarChart: Pass, Line: () => null, Bar: () => null, Pie: () => null,
    Cell: () => null, Radar: () => null, PolarGrid: () => null,
    PolarAngleAxis: () => null, PolarRadiusAxis: () => null, XAxis: () => null,
    YAxis: () => null, CartesianGrid: () => null, Tooltip: () => null, Legend: () => null,
  }
})

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(), post: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    defaults: { headers: { common: {} } },
  },
}))

vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: 'metric',
    showBoth: false,
    gallonStandard: 'us',
    // The RESOLVED set, not just the collapsed system: this component reads
    // its distance through `useUnitFormat()`, which closes over `units`.
    units: METRIC_UNITS,
  }),
}))
// The reporter's configuration: Polish złoty.
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: 'PLN', locale: 'pl-PL' }),
}))
vi.mock('../../hooks/useCurrencySymbol', () => ({ useCurrencySymbol: () => 'zł' }))
vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => 'pl-PL' }))

import api from '../../services/api'
import Analytics from '../Analytics'

const mockedApiGet = vi.mocked(api).get

/** The exact shape analytics.py emits, including the hardcoded-$ message. */
const ABOVE: AnomalyAlert = {
  month: '2025-08',
  amount: '3400.00',
  baseline: '1028.62',
  deviation_percent: '230.53',
  severity: 'critical',
  message: 'Spending in August 2025 was $3400.00, 230.5% above your average of $1028.62.',
} as unknown as AnomalyAlert

const BELOW: AnomalyAlert = {
  month: '2025-03',
  amount: '120.00',
  baseline: '1028.62',
  deviation_percent: '-88.33',
  severity: 'warning',
  message: 'Spending in March 2025 was $120.00, 88.3% below your average of $1028.62.',
} as unknown as AnomalyAlert

function analyticsWith(anomalies: AnomalyAlert[]): VehicleAnalytics {
  return {
    vehicle_name: 'Ram', vehicle_type: 'Truck', vin: 'V1', days_owned: 100,
    total_km_driven: null, average_km_per_month: null,
    cost_analysis: {
      total_cost: '0.00', average_monthly_cost: '0.00', months_tracked: 0,
      service_count: 0, fuel_count: 0, def_count: 0, cost_per_km: null,
      rolling_avg_3m: null, rolling_avg_6m: null, rolling_avg_12m: null,
      trend_direction: 'stable', total_service_cost: '0.00',
      total_fuel_cost: '0.00', total_def_cost: '0.00',
      monthly_breakdown: [], service_type_breakdown: [], anomalies,
    },
    cost_projection: {
      monthly_average: '0.00', six_month_projection: '0.00',
      twelve_month_projection: '0.00', assumptions: '',
    },
    fuel_economy: {
      average_l_per_100km: null, best_l_per_100km: null, worst_l_per_100km: null,
      recent_l_per_100km: null, trend: 'stable', data_points: [],
    },
    hours_economy: {
      average_l_per_hr: null, average_cost_per_hr: null, best_l_per_hr: null,
      worst_l_per_hr: null, recent_l_per_hr: null, recent_cost_per_hr: null,
      trend: 'stable', data_points: [],
    },
    hours_accumulated: [], fuel_alerts: [], service_history: [], predictions: [],
    propane_analysis: null, spot_rental_analysis: null, def_analysis: null,
  } as unknown as VehicleAnalytics
}

function renderWith(anomalies: AnomalyAlert[]): void {
  mockedApiGet.mockImplementation((url: string) => {
    if (url.endsWith('/vendors')) return Promise.reject(new Error('no vendors'))
    if (url.endsWith('/seasonal')) return Promise.reject(new Error('no seasonal'))
    return Promise.resolve({ data: analyticsWith(anomalies) })
  })
  render(
    <MemoryRouter initialEntries={['/vehicles/V1/analytics']}>
      <Routes>
        <Route path="/vehicles/:vin/analytics" element={<Analytics />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => vi.clearAllMocks())
afterEach(() => cleanup())

describe('Analytics — spending anomalies (issue #131)', () => {
  it('never renders the backend-composed message, which carries a hardcoded $', async () => {
    renderWith([ABOVE])
    await waitFor(() => expect(screen.getByText('vehicle.spendingAnomalies')).toBeInTheDocument())

    // The literal defect: this sentence must not reach the DOM.
    expect(screen.queryByText(/Spending in August 2025 was/)).not.toBeInTheDocument()
    expect(document.body.textContent).not.toContain('$')
  })

  it('formats the anomaly figures in the configured currency', async () => {
    renderWith([ABOVE])
    const sentence = await screen.findByText(/vehicle\.anomalyAbove/)

    // formatCurrency(PLN, pl-PL) — assert on the symbol, not exact spacing:
    // pl-PL uses a non-breaking space as the group separator.
    expect(sentence.textContent).toMatch(/zł/)
    expect(sentence.textContent).not.toMatch(/\$/)
    // Both figures come through, not just the total.
    expect(sentence.textContent).toMatch(/3400/)
    expect(sentence.textContent).toMatch(/1028/)
  })

  it('picks the above/below variant from the sign and interpolates an absolute deviation', async () => {
    renderWith([ABOVE, BELOW])
    await waitFor(() => expect(screen.getByText('vehicle.spendingAnomalies')).toBeInTheDocument())

    const above = screen.getByText(/vehicle\.anomalyAbove/)
    expect(above.textContent).toMatch(/"deviation":"230\.5"/)

    // Negative deviation must select `anomalyBelow` AND drop the sign — the
    // direction is carried by the wording, so "-88.3% below" would double it.
    const below = screen.getByText(/vehicle\.anomalyBelow/)
    expect(below.textContent).toMatch(/"deviation":"88\.3"/)
    expect(below.textContent).not.toMatch(/-88/)
  })

  it('localises the month heading and translates the severity chip', async () => {
    renderWith([ABOVE])
    await waitFor(() => expect(screen.getByText('vehicle.spendingAnomalies')).toBeInTheDocument())

    // "2025-08" -> a localised month/year, never the raw ISO fragment.
    expect(screen.queryByText('2025-08')).not.toBeInTheDocument()
    expect(screen.getByText(/2025/)).toBeInTheDocument()
    // Severity goes through t() rather than rendering the raw enum. Regex,
    // not exact text: this file's `t` mock appends the options object, so the
    // node reads `vehicle.severity.critical|{"defaultValue":"critical"}`.
    expect(screen.getByText(/^vehicle\.severity\.critical/)).toBeInTheDocument()
    expect(screen.queryByText('critical')).not.toBeInTheDocument()
  })
})
