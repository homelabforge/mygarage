// Financing on the garage analytics page: summary card, table column, trend bar, CSV export.

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import type { ReactNode } from 'react'

const captured = vi.hoisted(() => ({ charts: [] as unknown[] }))
vi.mock('recharts', () => {
  const Pass = ({ children }: { children?: ReactNode }) => <>{children}</>
  return {
    ResponsiveContainer: Pass,
    PieChart: Pass,
    Pie: Pass,
    Cell: () => null,
    ComposedChart: ({ data, children }: { data: unknown; children?: ReactNode }) => {
      captured.charts.push(data)
      return <>{children}</>
    },
    Bar: ({ name }: { name?: string }) => <span data-testid="trend-bar">{`series:${name}`}</span>,
    Line: () => null,
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
import type { GarageAnalytics as GarageAnalyticsData } from '../../types/analytics'

const mockedGet = vi.mocked(api).get

const ZERO = '0.00'

function vehicle(
  vin: string,
  nickname: string,
  overrides: Partial<GarageAnalyticsData['cost_by_vehicle'][number]> = {}
): GarageAnalyticsData['cost_by_vehicle'][number] {
  return {
    vin,
    name: `2024 ${nickname}`,
    nickname,
    purchase_price: ZERO,
    total_maintenance: ZERO,
    total_upgrades: ZERO,
    total_inspection: ZERO,
    total_collision: ZERO,
    total_detailing: ZERO,
    total_fuel: ZERO,
    total_def: ZERO,
    total_insurance: ZERO,
    total_financing: ZERO,
    total_cost: ZERO,
    ...overrides,
  }
}

const GARAGE: GarageAnalyticsData = {
  vehicle_count: 2,
  total_costs: {
    total_garage_value: '0.00',
    total_maintenance: ZERO,
    total_upgrades: ZERO,
    total_inspection: ZERO,
    total_collision: ZERO,
    total_detailing: ZERO,
    total_fuel: '500.00',
    total_def: ZERO,
    total_insurance: ZERO,
    total_taxes: ZERO,
    total_financing: '1450.00',
  },
  cost_breakdown_by_category: [
    { category: 'Fuel', amount: '500.00' },
    { category: 'Financing', amount: '1450.00' },
  ],
  cost_by_vehicle: [
    vehicle('V1', 'Van', { total_fuel: '400.00', total_financing: '1450.00', total_cost: '1850.00' }),
    vehicle('V2', 'Bike', { total_fuel: '100.00', total_cost: '100.00' }),
  ],
  monthly_trends: [
    { month: 'Jan 2026', service: ZERO, fuel: '50.00', def_cost: ZERO, insurance: ZERO, financing: '450.00', total: '50.00' },
    { month: 'Feb 2026', service: ZERO, fuel: '50.00', def_cost: ZERO, insurance: ZERO, financing: '1000.00', total: '50.00' },
  ],
}

const NO_FINANCING: GarageAnalyticsData = {
  ...GARAGE,
  total_costs: { ...GARAGE.total_costs, total_financing: ZERO },
  cost_breakdown_by_category: [{ category: 'Fuel', amount: '500.00' }],
  cost_by_vehicle: [vehicle('V1', 'Van', { total_fuel: '400.00', total_cost: '400.00' })],
  monthly_trends: [
    { month: 'Jan 2026', service: ZERO, fuel: '50.00', def_cost: ZERO, insurance: ZERO, financing: ZERO, total: '50.00' },
  ],
}

beforeEach(() => {
  captured.charts = []
  mockedGet.mockReset()
  mockedGet.mockResolvedValue({ data: GARAGE })
})

describe('GarageAnalytics — financing summary card', () => {
  it('shows a Financing card with the garage-wide financing total', async () => {
    render(<GarageAnalytics />)
    const card = (await screen.findByText('garage.cards.financing')).closest('div')!.parentElement!
    expect(within(card).getByText('$1,450.00')).toBeInTheDocument()
  })

  it('hides the Financing card when nothing is financed', async () => {
    mockedGet.mockResolvedValue({ data: NO_FINANCING })
    render(<GarageAnalytics />)
    await screen.findByText('garage.cards.fuel')
    expect(screen.queryByText('garage.cards.financing')).not.toBeInTheDocument()
  })
})

describe('GarageAnalytics — financing in the per-vehicle table', () => {
  it('has a Financing column so each row adds up to its Total', async () => {
    render(<GarageAnalytics />)
    await screen.findByText('garage.table.financing')

    const vanRow = screen.getAllByText('Van').map((el) => el.closest('tr')).find(Boolean)!
    const cells = within(vanRow).getAllByRole('cell').map((c) => c.textContent)
    expect(cells.slice(-4)).toEqual(['$400.00', '$0.00', '$1,450.00', '$1,850.00'])
  })
})

describe('GarageAnalytics — financing in the monthly trend', () => {
  it('adds a Financing bar series', async () => {
    render(<GarageAnalytics />)
    await screen.findByText('garage.table.financing')
    const series = screen.getAllByTestId('trend-bar').map((el) => el.textContent)
    expect(series).toContain('series:garage.cards.financing')
  })

  it('includes financing in the chart data but excludes it from the rolling averages', async () => {
    render(<GarageAnalytics />)
    await screen.findByText('garage.table.financing')
    const trend = captured.charts.find(
      (d): d is Array<{ Financing?: number; avg3?: number }> =>
        Array.isArray(d) && d.length > 0 && typeof d[0] === 'object' && d[0] !== null && 'avg3' in d[0]
    )
    expect(trend).toBeDefined()
    expect(trend![0].Financing).toBe(450)
    expect(trend![1].Financing).toBe(1000)
    // Rolling average is fuel-only here (service/def_cost are both zero in
    // both months): Jan = 50, Feb = avg(50, 50) = 50. Financing (450, 1000)
    // must not shift these — a lease/loan payment isn't a running cost.
    expect(trend![0].avg3).toBe(50)
    expect(trend![1].avg3).toBe(50)
  })
})

describe('GarageAnalytics — financing in the category legend', () => {
  it('gives every category, including the tenth, its own colour', async () => {
    const CATEGORIES = [
      'Maintenance', 'Upgrades', 'Inspection', 'Collision', 'Detailing',
      'Fuel', 'DEF', 'Insurance', 'Taxes', 'Financing',
    ]
    mockedGet.mockResolvedValue({
      data: {
        ...GARAGE,
        cost_breakdown_by_category: CATEGORIES.map((category) => ({ category, amount: '10.00' })),
      },
    })
    render(<GarageAnalytics />)
    await screen.findByText('Financing')

    const swatchColor = (label: string) => {
      const swatch = screen.getByText(label).querySelector('span')!
      return swatch.style.backgroundColor
    }
    const colors = CATEGORIES.map(swatchColor)
    // Each category needs its own colour.
    expect(new Set(colors).size).toBe(CATEGORIES.length)
  })
})

describe('GarageAnalytics — financing in the CSV export', () => {
  it('exports the financing total, the per-vehicle column and the monthly column', async () => {
    const blobs: Blob[] = []
    const createObjectURL = vi
      .spyOn(URL, 'createObjectURL')
      .mockImplementation((blob: Blob | MediaSource) => {
        blobs.push(blob as Blob)
        return 'blob:mock'
      })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    try {
      render(<GarageAnalytics />)
      await screen.findByText('garage.table.financing')
      // One fetch: a second one remounts the header and closes the menu.
      expect(mockedGet).toHaveBeenCalledTimes(1)
      fireEvent.click(screen.getByRole('button', { name: /export/i }))
      fireEvent.click(await screen.findByRole('menuitem', { name: 'CSV' }))
      await waitFor(() => expect(blobs).toHaveLength(1))
      const csv = await blobs[0].text()

      expect(csv).toContain('Financing,1450.00')
      expect(csv).toContain('Fuel,DEF,Financing,Running Costs')
      expect(csv).toContain('"2024 Van",0.00,0.00,0.00,0.00,0.00,0.00,400.00,0.00,1450.00,1850.00')
      expect(csv).toContain('Month,Service,Fuel,DEF,Financing,Total')
      // Total excludes financing (Fuel only): 50.00, not 1050.00.
      expect(csv).toContain('Feb 2026,0.00,50.00,0.00,1000.00,50.00')
    } finally {
      createObjectURL.mockRestore()
      click.mockRestore()
    }
  })
})

describe('GarageAnalytics: trend rows in the CSV export', () => {
  // The API now always sends 12 months, so an all-zero window has to read as no trend.
  const exportCsv = async (data: GarageAnalyticsData): Promise<string> => {
    const blobs: Blob[] = []
    const createObjectURL = vi
      .spyOn(URL, 'createObjectURL')
      .mockImplementation((blob: Blob | MediaSource) => {
        blobs.push(blob as Blob)
        return 'blob:mock'
      })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    try {
      mockedGet.mockResolvedValue({ data })
      render(<GarageAnalytics />)
      await screen.findByText('garage.table.financing')
      fireEvent.click(screen.getByRole('button', { name: /export/i }))
      fireEvent.click(await screen.findByRole('menuitem', { name: 'CSV' }))
      await waitFor(() => expect(blobs).toHaveLength(1))
      return await blobs[0].text()
    } finally {
      createObjectURL.mockRestore()
      click.mockRestore()
    }
  }

  const months = Array.from({ length: 12 }, (_, i) => `M${String(i + 1).padStart(2, '0')} 2026`)
  const zeroMonth = (month: string): GarageAnalyticsData['monthly_trends'][number] => ({
    month, service: ZERO, fuel: ZERO, def_cost: ZERO, insurance: ZERO, financing: ZERO, total: ZERO,
  })

  it('leaves the trend rows out when every month is zero', async () => {
    const csv = await exportCsv({ ...GARAGE, monthly_trends: months.map(zeroMonth) })
    expect(csv).toContain('Cost by Vehicle')
    expect(csv).not.toContain('Monthly Spending Trends')
    expect(csv).not.toContain('M01 2026')
  })

  it('keeps the trend rows for a financing-only window', async () => {
    const csv = await exportCsv({
      ...GARAGE,
      monthly_trends: months.map((month) =>
        month === 'M04 2026' ? { ...zeroMonth(month), financing: '450.00' } : zeroMonth(month)
      ),
    })
    expect(csv).toContain('Monthly Spending Trends')
    expect(csv).toContain('M01 2026,0.00,0.00,0.00,0.00,0.00')
    // Total is running costs only, so the lease payment leaves it at zero.
    expect(csv).toContain('M04 2026,0.00,0.00,0.00,450.00,0.00')
  })

  it('keeps all 12 rows, zeros included, when one month has running costs (guard)', async () => {
    const csv = await exportCsv({
      ...GARAGE,
      monthly_trends: months.map((month) =>
        month === 'M06 2026' ? { ...zeroMonth(month), fuel: '40.00', total: '40.00' } : zeroMonth(month)
      ),
    })
    expect(csv).toContain('Monthly Spending Trends')
    expect(csv).toContain('M01 2026,0.00,0.00,0.00,0.00,0.00')
    expect(csv).toContain('M06 2026,0.00,40.00,0.00,0.00,40.00')
    expect(csv).toContain('M12 2026,0.00,0.00,0.00,0.00,0.00')
  })
})
