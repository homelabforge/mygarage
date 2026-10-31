import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import type { ReactNode } from 'react'

// ─────────────────────────────────────────────────────────────────────────────
// recharts renders 0×0 in jsdom, so stub the chart boundary (mirrors
// Analytics.hours.test.tsx). ComposedChart CAPTURES its `data` prop so we can
// prove the Monthly-Spending-Trend rolling averages have NO leading null at
// index 0 when the first month has running costs (the "connect the lines
// through every month" fix), and are null on months with only insurance or
// financing. Line renders its dataKey so a test can see which lines mount.
// After the redesign
// the only categorical chart on the page is the trend chart, and it is a
// ComposedChart (Recharts v3 only renders <Line> inside a ComposedChart).
// ─────────────────────────────────────────────────────────────────────────────
const captured = vi.hoisted(() => ({ barCharts: [] as unknown[] }))
vi.mock('recharts', () => {
  const Pass = ({ children }: { children?: ReactNode }) => <>{children}</>
  return {
    ResponsiveContainer: Pass,
    PieChart: Pass,
    Pie: Pass,
    Cell: () => null,
    ComposedChart: ({ data, children }: { data: unknown; children?: ReactNode }) => {
      captured.barCharts.push(data)
      return <>{children}</>
    },
    Bar: () => null,
    Line: ({ dataKey }: { dataKey?: string }) => <span data-testid="trend-line">{dataKey}</span>,
    XAxis: () => null,
    YAxis: () => null,
    CartesianGrid: () => null,
    Tooltip: () => null,
    Legend: () => null,
  }
})

vi.mock('../../services/api', () => ({ default: { get: vi.fn() } }))
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US' }),
}))
vi.mock('../../hooks/useTimeFormat', () => ({ useTimeFormat: () => ({ timeFormat: '12h' }) }))
vi.mock('../../components/GarageAnalyticsHelpDrawer', () => ({ default: () => null }))
vi.mock('../../components/ExportMenu', () => ({ default: () => null }))
// t() returns the key (deterministic); data values render as themselves.
// Real react-i18next keeps `t` stable. A new one per render re-runs the page's
// [t] fetch effect, which flips it back to loading and remounts the header.
vi.mock('react-i18next', () => {
  const stableT = (key: string) => key
  return {
    useTranslation: () => ({
      t: stableT,
      i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
    }),
    Trans: ({ children }: { children: ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

import api from '../../services/api'
import GarageAnalytics from '../GarageAnalytics'

const mockedGet = vi.mocked(api).get

// Category total = 13,200 → avg/vehicle (÷3) = 4,400. DEF 100/13200 = 0.76% → "<1%".
const GARAGE = {
  vehicle_count: 3,
  total_costs: {
    total_garage_value: '50000.00',
    total_maintenance: '3000.00',
    total_upgrades: '5000.00',
    total_inspection: '0.00',
    total_collision: '1000.00',
    total_detailing: '200.00',
    total_fuel: '1500.00',
    total_def: '100.00',
    total_insurance: '2000.00',
    total_taxes: '400.00',
    total_financing: '0.00',
  },
  cost_breakdown_by_category: [
    { category: 'Maintenance', amount: '3000.00' },
    { category: 'Upgrades', amount: '5000.00' },
    { category: 'Collision', amount: '1000.00' },
    { category: 'Detailing', amount: '200.00' },
    { category: 'Fuel', amount: '1500.00' },
    { category: 'DEF', amount: '100.00' },
    { category: 'Insurance', amount: '2000.00' },
    { category: 'Taxes', amount: '400.00' },
  ],
  cost_by_vehicle: [
    { vin: 'V1', name: '2022 Ram 1500', nickname: 'Ram', purchase_price: '40000', total_maintenance: '1000', total_upgrades: '5000', total_inspection: '0', total_collision: '1000', total_detailing: '100', total_fuel: '800', total_def: '100', total_financing: '0', total_cost: '8000.00' },
    { vin: 'V2', name: '2020 Mitsubishi Mirage', nickname: 'Mirage', purchase_price: '15000', total_maintenance: '1500', total_upgrades: '0', total_inspection: '0', total_collision: '0', total_detailing: '50', total_fuel: '500', total_def: '0', total_financing: '0', total_cost: '2050.00' },
    { vin: 'V3', name: '2021 Polaris Sportsman', nickname: 'Sportsman', purchase_price: '8000', total_maintenance: '500', total_upgrades: '0', total_inspection: '0', total_collision: '0', total_detailing: '50', total_fuel: '200', total_def: '0', total_financing: '0', total_cost: '750.00' },
  ],
  monthly_trends: [
    { month: 'Jan 2026', service: '100', fuel: '50', def_cost: '0', financing: '0', total: '150' },
    { month: 'Feb 2026', service: '200', fuel: '60', def_cost: '10', financing: '0', total: '270' },
    { month: 'Mar 2026', service: '0', fuel: '40', def_cost: '0', financing: '0', total: '40' },
  ],
}

beforeEach(() => {
  captured.barCharts = []
  mockedGet.mockReset()
  mockedGet.mockResolvedValue({ data: GARAGE })
})

describe('GarageAnalytics — Cost by Category donut + sidebar', () => {
  it('shows the donut center TOTAL = sum of category amounts', async () => {
    render(<GarageAnalytics />)
    // $13,200.00 is the category sum — unique on the page (garage value is $50k).
    expect(await screen.findByText('$13,200.00')).toBeInTheDocument()
    expect(screen.getByText('garage.donutTotal')).toBeInTheDocument()
  })

  it('renders the sidebar list with every category and a "<1%" for the tiny DEF share', async () => {
    render(<GarageAnalytics />)
    await screen.findByText('$13,200.00')
    // Insurance appears ONLY in the sidebar (the top card uses an i18n key, the
    // table has no insurance column) — proves the sidebar list rendered.
    expect(screen.getByText('Insurance')).toBeInTheDocument()
    // DEF is 100/13,200 = 0.76% → rounded label "<1%" (formatPercent edge).
    expect(screen.getByText('<1%')).toBeInTheDocument()
  })

  it('does not render the Largest or Avg/vehicle tiles (removed)', async () => {
    render(<GarageAnalytics />)
    await screen.findByText('$13,200.00')
    expect(screen.queryByText('garage.largest')).not.toBeInTheDocument()
    expect(screen.queryByText('garage.avgPerVehicle')).not.toBeInTheDocument()
    // Avg-per-vehicle value (13,200/3) is gone; Upgrades shows only in the sidebar now.
    expect(screen.queryByText('$4,400.00')).not.toBeInTheDocument()
    expect(screen.getAllByText('Upgrades')).toHaveLength(1)
  })
})

describe('GarageAnalytics — Running Costs by Vehicle', () => {
  it('renders the vehicle bar list (nickname in both the bar list and the table)', async () => {
    render(<GarageAnalytics />)
    await screen.findByText('$13,200.00')
    // Nickname shows once in the bar list and once in the table row.
    expect(screen.getAllByText('Mirage')).toHaveLength(2)
    expect(screen.getAllByText('Ram')).toHaveLength(2)
  })

  it('keeps all 9 table columns, including Inspection and Detailing', async () => {
    render(<GarageAnalytics />)
    await screen.findByText('$13,200.00')
    // The two columns a trimmed 7-column table would drop.
    expect(screen.getByText('garage.table.inspection')).toBeInTheDocument()
    expect(screen.getByText('garage.table.detailing')).toBeInTheDocument()
    expect(screen.getByText('garage.table.total')).toBeInTheDocument()
  })
})

describe('GarageAnalytics — Monthly Spending Trend rolling averages', () => {
  it('gives the trend chart a rolling average at index 0 (no leading null → the line spans the full width)', async () => {
    render(<GarageAnalytics />)
    await screen.findByText('$13,200.00')
    const trend = captured.barCharts.find(
      (d): d is Array<{ avg3?: number }> =>
        Array.isArray(d) && d.length > 0 && typeof d[0] === 'object' && d[0] !== null && 'avg3' in d[0]
    )
    expect(trend).toBeDefined()
    // Jan total = 100+50+0 = 150; trailing avg over 1 month = 150 (NOT null).
    expect(trend![0].avg3).toBe(150)
    expect(trend![0].avg3).not.toBeNull()
  })

  it('skips months with only insurance or financing instead of averaging them in as zero', async () => {
    // Fuel in Jan/Mar/May; Feb has only insurance, Apr only a lease payment.
    mockedGet.mockResolvedValue({
      data: {
        ...GARAGE,
        monthly_trends: [
          { month: 'Jan 2026', service: '0', fuel: '100', def_cost: '0', insurance: '0', financing: '0', total: '100' },
          { month: 'Feb 2026', service: '0', fuel: '0', def_cost: '0', insurance: '80', financing: '0', total: '80' },
          { month: 'Mar 2026', service: '0', fuel: '300', def_cost: '0', insurance: '0', financing: '0', total: '300' },
          { month: 'Apr 2026', service: '0', fuel: '0', def_cost: '0', insurance: '0', financing: '450', total: '0' },
          { month: 'May 2026', service: '0', fuel: '500', def_cost: '0', insurance: '0', financing: '0', total: '500' },
        ],
      },
    })
    render(<GarageAnalytics />)
    await screen.findByText('$13,200.00')
    const trend = captured.barCharts.find(
      (d): d is Array<{ avg3?: number | null; avg6?: number | null }> =>
        Array.isArray(d) && d.length > 0 && typeof d[0] === 'object' && d[0] !== null && 'avg3' in d[0]
    )
    expect(trend).toBeDefined()
    // Counting Feb and Apr as zero gives May (300 + 0 + 500) / 3 = 266.67.
    expect(trend![4].avg3).toBe(300)
    expect(trend![4].avg6).toBe(300)
    expect(trend![1].avg3).toBeNull()
    expect(trend![3].avg3).toBeNull()
  })

  it('starts the lines at the first running-cost month when the first month has only insurance', async () => {
    mockedGet.mockResolvedValue({
      data: {
        ...GARAGE,
        monthly_trends: [
          { month: 'Jan 2026', service: '0', fuel: '0', def_cost: '0', insurance: '80', financing: '0', total: '80' },
          { month: 'Feb 2026', service: '0', fuel: '100', def_cost: '0', insurance: '80', financing: '0', total: '180' },
          { month: 'Mar 2026', service: '0', fuel: '200', def_cost: '0', insurance: '80', financing: '0', total: '280' },
        ],
      },
    })
    render(<GarageAnalytics />)
    await screen.findByText('$13,200.00')
    const trend = captured.barCharts.find(
      (d): d is Array<{ avg3?: number | null }> =>
        Array.isArray(d) && d.length > 0 && typeof d[0] === 'object' && d[0] !== null && 'avg3' in d[0]
    )
    expect(trend![0].avg3).toBeNull()
    expect(trend![1].avg3).toBe(100)
    expect(trend![2].avg3).toBe(150)
  })

  it('mounts the 3-month line only once there are three running-cost months', async () => {
    // Three rows, but two carry only insurance: one running-cost month.
    mockedGet.mockResolvedValue({
      data: {
        ...GARAGE,
        monthly_trends: [
          { month: 'Jan 2026', service: '0', fuel: '0', def_cost: '0', insurance: '80', financing: '0', total: '80' },
          { month: 'Feb 2026', service: '0', fuel: '0', def_cost: '0', insurance: '80', financing: '0', total: '80' },
          { month: 'Mar 2026', service: '0', fuel: '100', def_cost: '0', insurance: '80', financing: '0', total: '180' },
        ],
      },
    })
    render(<GarageAnalytics />)
    await screen.findByText('$13,200.00')
    expect(screen.queryAllByTestId('trend-line').map((el) => el.textContent)).not.toContain('avg3')
  })

  it('formats month labels with a two-digit year (Jan 26, not Jan 2026)', async () => {
    render(<GarageAnalytics />)
    await screen.findByText('$13,200.00')
    const trend = captured.barCharts.find(
      (d): d is Array<{ month?: string }> =>
        Array.isArray(d) && d.length > 0 && typeof d[0] === 'object' && d[0] !== null && 'month' in d[0]
    )
    expect(trend).toBeDefined()
    expect(trend![0].month).toContain('26')
    expect(trend![0].month).not.toContain('2026')
  })
})

describe('GarageAnalytics: optional cost cards show only when they carry money', () => {
  const withCosts = (overrides: Partial<typeof GARAGE.total_costs>) => ({
    ...GARAGE,
    total_costs: { ...GARAGE.total_costs, ...overrides },
  })

  it('hides the Insurance and Taxes cards at $0', async () => {
    mockedGet.mockResolvedValue({
      data: withCosts({ total_insurance: '0.00', total_taxes: '0.00' }),
    })
    render(<GarageAnalytics />)
    await screen.findByText('garage.cards.fuel')
    expect(screen.queryByText('garage.cards.insurance')).not.toBeInTheDocument()
    expect(screen.queryByText('garage.cards.taxes')).not.toBeInTheDocument()
    // The core three still show.
    expect(screen.getByText('garage.cards.garageValue')).toBeInTheDocument()
    expect(screen.getByText('garage.cards.maintenance')).toBeInTheDocument()
  })

  it('shows the core three at $0 too (guard)', async () => {
    mockedGet.mockResolvedValue({
      data: withCosts({ total_garage_value: '0.00', total_maintenance: '0.00', total_fuel: '0.00' }),
    })
    render(<GarageAnalytics />)
    expect(await screen.findByText('garage.cards.garageValue')).toBeInTheDocument()
    expect(screen.getByText('garage.cards.maintenance')).toBeInTheDocument()
    expect(screen.getByText('garage.cards.fuel')).toBeInTheDocument()
  })

  it('shows the Insurance and Taxes cards with their amounts above zero (guard)', async () => {
    render(<GarageAnalytics />)
    const insurance = (await screen.findByText('garage.cards.insurance')).closest('div')!.parentElement!
    const taxes = screen.getByText('garage.cards.taxes').closest('div')!.parentElement!
    expect(within(insurance).getByText('$2,000.00')).toBeInTheDocument()
    expect(within(taxes).getByText('$400.00')).toBeInTheDocument()
  })
})

// The API sends the last 12 calendar months, zeros included.
const TWELVE_MONTHS = [
  'Nov 2025', 'Dec 2025', 'Jan 2026', 'Feb 2026', 'Mar 2026', 'Apr 2026',
  'May 2026', 'Jun 2026', 'Jul 2026', 'Aug 2026', 'Sep 2026', 'Oct 2026',
]
const zeroMonth = (month: string) => ({
  month, service: '0.00', fuel: '0.00', def_cost: '0.00', insurance: '0.00', financing: '0.00', total: '0.00',
})

describe('GarageAnalytics: fixed 12-month trend window', () => {
  it('renders all 12 months and the averages skip the zero ones (guard)', async () => {
    // Fuel in Jan, Mar and May 2026 only; the other nine months are zero.
    const fuel: Record<string, string> = { 'Jan 2026': '100.00', 'Mar 2026': '300.00', 'May 2026': '500.00' }
    mockedGet.mockResolvedValue({
      data: {
        ...GARAGE,
        monthly_trends: TWELVE_MONTHS.map((month) =>
          fuel[month] ? { ...zeroMonth(month), fuel: fuel[month], total: fuel[month] } : zeroMonth(month)
        ),
      },
    })
    render(<GarageAnalytics />)
    await screen.findByText('$13,200.00')
    const trend = captured.barCharts.find(
      (d): d is Array<{ month: string; avg3: number | null }> =>
        Array.isArray(d) && d.length > 0 && typeof d[0] === 'object' && d[0] !== null && 'avg3' in d[0]
    )
    expect(trend).toBeDefined()
    expect(trend!).toHaveLength(12)
    expect(trend![0].month).toBe('Nov 25')
    expect(trend![11].month).toBe('Oct 26')
    // Averaging the zero months in would give May (300 + 0 + 500) / 3.
    expect(trend![6].avg3).toBe(300)
    expect(trend![0].avg3).toBeNull()
    expect(trend![3].avg3).toBeNull()
    expect(trend![11].avg3).toBeNull()
    expect(screen.queryAllByTestId('trend-line').map((el) => el.textContent)).toContain('avg3')
  })

  it('hides the trend chart when every month is zero', async () => {
    mockedGet.mockResolvedValue({ data: { ...GARAGE, monthly_trends: TWELVE_MONTHS.map(zeroMonth) } })
    render(<GarageAnalytics />)
    await screen.findByText('$13,200.00')
    expect(screen.queryByText('garage.monthlySpendingTrend')).not.toBeInTheDocument()
    expect(captured.barCharts).toHaveLength(0)
  })

  it('shows the trend chart when one month carries running costs (guard)', async () => {
    mockedGet.mockResolvedValue({
      data: {
        ...GARAGE,
        monthly_trends: TWELVE_MONTHS.map((month) =>
          month === 'Jun 2026' ? { ...zeroMonth(month), service: '75.00', total: '75.00' } : zeroMonth(month)
        ),
      },
    })
    render(<GarageAnalytics />)
    await screen.findByText('$13,200.00')
    expect(screen.getByText('garage.monthlySpendingTrend')).toBeInTheDocument()
    expect(captured.barCharts.at(-1)).toHaveLength(12)
  })
})
