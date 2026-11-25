import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
const captured = vi.hoisted(() => ({
  barCharts: [] as unknown[],
  pies: [] as unknown[],
  tooltips: {} as Record<string, (props: unknown) => ReactNode>,
}))
vi.mock('recharts', async () => {
  const { createContext, useContext } = await import('react')
  // Which chart a Tooltip sits in, so a test can call the right content().
  const ChartKind = createContext('')
  const Pass = ({ children }: { children?: ReactNode }) => <>{children}</>
  return {
    ResponsiveContainer: Pass,
    PieChart: ({ children }: { children?: ReactNode }) => <ChartKind.Provider value="pie">{children}</ChartKind.Provider>,
    Pie: ({ data, children }: { data?: unknown; children?: ReactNode }) => {
      captured.pies.push(data)
      return <>{children}</>
    },
    Cell: ({ fill }: { fill?: string }) => <span data-testid="pie-cell" data-fill={fill} />,
    ComposedChart: ({ data, children }: { data: unknown; children?: ReactNode }) => {
      captured.barCharts.push(data)
      return <ChartKind.Provider value="trend">{children}</ChartKind.Provider>
    },
    Bar: ({ dataKey, fill }: { dataKey?: string; fill?: string }) => <span data-testid="trend-bar" data-key={dataKey} data-fill={fill} />,
    Line: ({ dataKey, stroke }: { dataKey?: string; stroke?: string }) => <span data-testid="trend-line" data-stroke={stroke}>{dataKey}</span>,
    XAxis: () => null,
    YAxis: () => null,
    CartesianGrid: () => null,
    Tooltip: ({ content }: { content?: (props: unknown) => ReactNode }) => {
      const kind = useContext(ChartKind)
      if (content) captured.tooltips[kind] = content
      return null
    },
    Legend: () => null,
  }
})

vi.mock('../../services/api', () => ({ default: { get: vi.fn() } }))
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US' }),
}))
vi.mock('../../hooks/useTimeFormat', () => ({ useTimeFormat: () => ({ timeFormat: '12h' }) }))
vi.mock('../../components/GarageAnalyticsHelpDrawer', () => ({ default: () => null }))
vi.mock('../../components/ExportMenu', () => ({
  default: ({ onExportPDF }: { onExportPDF: () => void }) => (
    <button type="button" onClick={onExportPDF}>
      export-pdf
    </button>
  ),
}))
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
import { toast } from 'sonner'
import GarageAnalytics from '../GarageAnalytics'
import { setActiveDateFormat } from '../../constants/i18n'

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
    total_running_cost: '10800.00',
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
  captured.pies = []
  captured.tooltips = {}
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
    expect(screen.getByText('garage.cards.fuel')).toBeInTheDocument()
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

  it('shows the trend bars for a financing-only window, with no average lines', async () => {
    mockedGet.mockResolvedValue({
      data: {
        ...GARAGE,
        monthly_trends: TWELVE_MONTHS.map((month) =>
          month === 'Mar 2026' || month === 'Apr 2026'
            ? { ...zeroMonth(month), financing: '450.00' }
            : zeroMonth(month)
        ),
      },
    })
    render(<GarageAnalytics />)
    await screen.findByText('$13,200.00')
    expect(screen.getByText('garage.monthlySpendingTrend')).toBeInTheDocument()
    const trend = captured.barCharts.at(-1) as Array<{ Financing: number; avg3: number | null }>
    expect(trend).toHaveLength(12)
    expect(trend[4].Financing).toBe(450)
    // Financing isn't a running cost, so the averages have nothing to run over.
    expect(trend.every((row) => row.avg3 === null)).toBe(true)
    expect(screen.queryAllByTestId('trend-line')).toHaveLength(0)
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

describe('GarageAnalytics PDF export', () => {
  it('asks for the date order the page shows (#278)', async () => {
    Object.defineProperty(window.URL, 'createObjectURL', { value: vi.fn(() => 'blob:x'), writable: true, configurable: true })
    Object.defineProperty(window.URL, 'revokeObjectURL', { value: vi.fn(), writable: true, configurable: true })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    setActiveDateFormat('dmy')
    try {
      render(<GarageAnalytics />)
      fireEvent.click(await screen.findByRole('button', { name: 'export-pdf' }))
      await waitFor(() =>
        expect(mockedGet).toHaveBeenCalledWith('/analytics/garage/export', {
          responseType: 'blob',
          params: { currency_code: 'USD', locale: 'en-US', date_format: 'dmy' },
        })
      )
    } finally {
      setActiveDateFormat('mdy')
    }
  })

  it('says a failed export in a toast, not a native alert', async () => {
    const toastError = vi.spyOn(toast, 'error').mockImplementation(() => 0)
    mockedGet.mockImplementation((url: string) =>
      url === '/analytics/garage/export' ? Promise.reject(new Error('boom')) : Promise.resolve({ data: GARAGE }),
    )
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      render(<GarageAnalytics />)

      fireEvent.click(await screen.findByRole('button', { name: 'export-pdf' }))

      await waitFor(() => expect(toastError).toHaveBeenCalledWith('garage.exportPdfFailed'))
    } finally {
      toastError.mockRestore()
      consoleError.mockRestore()
    }
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// Chart colours: each category keeps its own slot whatever order the API sends,
// and the three without one fold into a single grey Other slice.
// ─────────────────────────────────────────────────────────────────────────────
type Slice = { name: string; value: number; color: string; folded?: Array<{ category: string; amount: string }> }

const ALL_TEN = [
  { category: 'Maintenance', amount: '3000.00' },
  { category: 'Upgrades', amount: '5000.00' },
  { category: 'Inspection', amount: '150.00' },
  { category: 'Collision', amount: '1000.00' },
  { category: 'Detailing', amount: '200.00' },
  { category: 'Fuel', amount: '1500.00' },
  { category: 'DEF', amount: '100.00' },
  { category: 'Insurance', amount: '2000.00' },
  { category: 'Taxes', amount: '400.00' },
  { category: 'Financing', amount: '900.00' },
]

function withCategories(categories: Array<{ category: string; amount: string }>): typeof GARAGE {
  return { ...GARAGE, cost_breakdown_by_category: categories }
}

async function donut(categories: Array<{ category: string; amount: string }>): Promise<Slice[]> {
  mockedGet.mockResolvedValue({ data: withCategories(categories) })
  const view = render(<GarageAnalytics />)
  await screen.findByText('garage.donutTotal')
  const slices = captured.pies.at(-1) as Slice[]
  const fills = screen.getAllByTestId('pie-cell').map((el) => el.getAttribute('data-fill'))
  // the Cell fills are what paints, so check they follow the slice data
  expect(fills).toEqual(slices.map((s) => s.color))
  view.unmount()
  return slices
}

const fillsByName = (slices: Slice[]): Record<string, string> =>
  Object.fromEntries(slices.map((s) => [s.name, s.color]))

describe('GarageAnalytics: category colours and the Other fold', () => {
  it('draws 8 slices for 10 categories: 7 coloured plus one Other', async () => {
    const slices = await donut(ALL_TEN)
    expect(slices).toHaveLength(8)
    const other = slices.filter((s) => s.color === 'var(--color-chart-other)')
    expect(other.map((s) => s.name)).toEqual(['vehicle.other'])
    const coloured = slices.filter((s) => s.color !== 'var(--color-chart-other)')
    expect(coloured).toHaveLength(7)
    expect(new Set(coloured.map((s) => s.color)).size).toBe(7)
    for (const s of coloured) expect(s.color).toMatch(/^var\(--color-chart-[1-8]\)$/)
    // the fold adds up: 150 + 1000 + 200
    expect(other[0].value).toBe(1350)
  })

  it('keeps a sidebar row for all 10, the folded ones on the Other swatch', async () => {
    mockedGet.mockResolvedValue({ data: withCategories(ALL_TEN) })
    render(<GarageAnalytics />)
    await screen.findByText('garage.donutTotal')
    const rows = screen.getAllByTestId('category-row')
    expect(rows.map((r) => r.getAttribute('data-category')).sort()).toEqual(ALL_TEN.map((c) => c.category).sort())
    for (const row of rows) {
      const swatch = within(row).getByTestId('category-swatch').getAttribute('style') ?? ''
      const folded = ['Inspection', 'Collision', 'Detailing'].includes(row.getAttribute('data-category') ?? '')
      expect(swatch, row.getAttribute('data-category') ?? '').toContain(folded ? 'var(--color-chart-other)' : 'var(--color-chart-')
      if (!folded) expect(swatch).not.toContain('chart-other')
    }
    // no amount goes missing: Collision's $1,000 still has a row of its own
    expect(within(rows.find((r) => r.getAttribute('data-category') === 'Collision')!).getByText('$1,000.00')).toBeInTheDocument()
  })

  it('names each folded category and its amount in the Other tooltip', async () => {
    const slices = await donut(ALL_TEN)
    const other = slices.find((s) => s.name === 'vehicle.other')!
    const content = captured.tooltips.pie
    expect(content).toBeTypeOf('function')
    render(<>{content({ active: true, payload: [{ name: other.name, value: other.value, payload: other }] })}</>)
    const box = screen.getByTestId('chart-tooltip')
    expect(within(box).getByText('vehicle.other')).toBeInTheDocument()
    expect(within(box).getByText(/Inspection/)).toHaveTextContent('$150.00')
    expect(within(box).getByText(/Collision/)).toHaveTextContent('$1,000.00')
    expect(within(box).getByText(/Detailing/)).toHaveTextContent('$200.00')
  })

  it('keeps every survivor on its colour when the order changes or Taxes drops out', async () => {
    const base = fillsByName(await donut(ALL_TEN))
    const reversed = fillsByName(await donut([...ALL_TEN].reverse()))
    expect(reversed).toEqual(base)
    const noTaxes = fillsByName(await donut(ALL_TEN.filter((c) => c.category !== 'Taxes')))
    expect(Object.keys(noTaxes)).not.toContain('Taxes')
    for (const [name, colour] of Object.entries(noTaxes)) expect(colour, name).toBe(base[name])
  })

  it('tooltips are theme tokens, not the old dark box', async () => {
    mockedGet.mockResolvedValue({ data: withCategories(ALL_TEN) })
    render(<GarageAnalytics />)
    await screen.findByText('garage.donutTotal')
    const payload = [{ name: 'Fuel', dataKey: 'Fuel', value: 50, payload: { name: 'Fuel', value: 50, month: 'Jan 26' } }]
    for (const kind of ['pie', 'trend']) {
      const view = render(<>{captured.tooltips[kind]({ active: true, payload })}</>)
      const box = within(view.container).getByTestId('chart-tooltip')
      expect(box.style.backgroundColor, kind).not.toBe('rgb(26, 31, 40)')
      expect(box.getAttribute('style') ?? '', kind).not.toContain('#1a1f28')
      expect(box.className, kind).toContain('bg-surface-2')
      expect(view.container.innerHTML, kind).not.toContain('156, 163, 175')
      expect(view.container.querySelector('.text-text-mute'), kind).not.toBeNull()
      view.unmount()
    }
  })

  it('trend bars follow the category map: Service rides Maintenance blue', async () => {
    mockedGet.mockResolvedValue({ data: withCategories(ALL_TEN) })
    render(<GarageAnalytics />)
    await screen.findByText('garage.donutTotal')
    const bars = Object.fromEntries(
      screen.getAllByTestId('trend-bar').map((b) => [b.getAttribute('data-key'), b.getAttribute('data-fill')])
    )
    expect(bars).toEqual({
      Service: 'var(--color-chart-1)',
      Fuel: 'var(--color-chart-2)',
      DEF: 'var(--color-chart-3)',
      Financing: 'var(--color-chart-6)',
    })
  })
})
