/**
 * The collapsible "Advanced statistics" block on the vehicle analytics page.
 *
 * It must be opt-in: closed on first load, remembered per browser once opened,
 * and it must still work when browser storage is unavailable. Figures are
 * checked in imperial units so a unit conversion that goes missing shows up.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { setActiveLocale } from '@/constants/i18n'
import type { OwnershipStatistics } from '../../types/analytics'

vi.mock('react-i18next', () => {
  const t = (key: string, options?: Record<string, unknown>): string => {
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

import { IMPERIAL_UNITS } from '@/__tests__/factories'

vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({ showBoth: false, units: IMPERIAL_UNITS }),
  useAccountUnitPreference: () => ({ units: IMPERIAL_UNITS }),
}))
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US' }),
}))
vi.mock('../../hooks/useCurrencySymbol', () => ({ useCurrencySymbol: () => '$' }))

import AdvancedStatistics, {
  ADVANCED_STATS_BASIS_KEY,
  ADVANCED_STATS_STORAGE_KEY,
} from '../AdvancedStatistics'

const STATS: OwnershipStatistics = {
  total_running_cost: '308.00',
  purchase_price: '1000.00',
  sold_price: null,
  total_ownership_cost: '1308.00',
  days_owned: 400,
  km_driven: '1609.344',
  km_per_day: '4.02',
  running_cost_per_day: '0.77',
  running_cost_per_km: '0.1914',
  ownership_cost_per_day: '3.27',
  ownership_cost_per_km: '0.8127',
  fuel_count: 4,
  avg_l_per_100km: null,
  best_l_per_100km: null,
  worst_l_per_100km: null,
  recent_l_per_100km: null,
  avg_price_per_liter: '1.125',
  min_price_per_liter: '1.00',
  max_price_per_liter: '1.20',
  last_price_per_liter: '1.20',
  fuel_total_cost: '127.00',
  fuel_total_liters: '115.000',
  fuel_cost_per_km: '0.0789',
  fuel_cost_per_day: '0.32',
  km_per_currency_unit: '12.67',
  avg_cost_per_fillup: '31.75',
  avg_liters_per_fillup: '28.75',
  avg_km_per_fillup: '402.34',
  avg_days_per_fillup: '28.3',
  liters_per_day: '1.35',
  expenses_total_cost: '181.00',
  expenses_cost_per_day: '0.45',
  expenses_cost_per_km: '0.1125',
}

describe('AdvancedStatistics', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('is collapsed on first load, with only the header and switch showing', () => {
    render(<AdvancedStatistics statistics={STATS} />)
    expect(screen.getByText('vehicle.statsTitle')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'vehicle.statsToggle' })).not.toBeChecked()
    expect(screen.queryByTestId('stats-overall')).not.toBeInTheDocument()
    expect(screen.queryByTestId('stats-fuel')).not.toBeInTheDocument()
    expect(screen.queryByTestId('stats-expenses')).not.toBeInTheDocument()
  })

  it('opens into the three cards and shows converted figures', () => {
    render(<AdvancedStatistics statistics={STATS} />)
    fireEvent.click(screen.getByRole('checkbox', { name: 'vehicle.statsToggle' }))

    const overall = within(screen.getByTestId('stats-overall'))
    expect(overall.getByText('$308.00')).toBeInTheDocument() // total running costs
    expect(overall.getByText('$1,308.00')).toBeInTheDocument() // total cost of ownership
    // 1609.344 km is exactly 1,000 mi
    expect(overall.getByText('1,000 mi')).toBeInTheDocument()

    const fuel = within(screen.getByTestId('stats-fuel'))
    expect(fuel.getByText('$127.00')).toBeInTheDocument()
    expect(within(screen.getByTestId('stats-expenses')).getByText('$181.00')).toBeInTheDocument()
  })

  it('stacks Overall and Services & Expenses in one column, Fuel-Ups in the other', () => {
    render(<AdvancedStatistics statistics={STATS} />)
    fireEvent.click(screen.getByRole('checkbox', { name: 'vehicle.statsToggle' }))
    const overall = screen.getByTestId('stats-overall')
    const expenses = screen.getByTestId('stats-expenses')
    const fuel = screen.getByTestId('stats-fuel')
    expect(overall.parentElement).toBe(expenses.parentElement)
    expect(fuel.parentElement).not.toBe(overall.parentElement)
    // Overall sits above Services & Expenses
    expect(overall.compareDocumentPosition(expenses) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('keeps the page to two columns, with Fuel-Ups as one slim stacked list', () => {
    render(<AdvancedStatistics statistics={STATS} />)
    fireEvent.click(screen.getByRole('checkbox', { name: 'vehicle.statsToggle' }))
    const fuel = screen.getByTestId('stats-fuel')
    // Two columns on the page (Overall + Expenses | Fuel-Ups), the right one narrower.
    const page = fuel.parentElement as HTMLElement
    expect(page).toHaveClass('lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]')
    expect(page.children).toHaveLength(2)
    // No columns inside the card: no grid, one label/value row after another.
    expect(fuel.querySelector('.grid')).toBeNull()
    const labels = Array.from(fuel.querySelectorAll('span.text-text-mute')).map((el) => el.textContent)
    expect(labels).toHaveLength(18)
    expect(new Set(labels).size).toBe(18)
    // Averages and best come first, a rule, then the latest and the extremes.
    expect(labels[0]).toBe('vehicle.statsAvgEconomy')
    expect(labels.indexOf('vehicle.statsFuelTotal')).toBe(8)
    expect(labels[9]).toBe('vehicle.statsLastEconomy')
    expect(labels[17]).toBe('vehicle.statsFuelVolume (gal)')
    expect(fuel.querySelectorAll('.border-dashed')).toHaveLength(1)
  })

  it('shows the selling price row only when the vehicle was sold', () => {
    const { rerender } = render(<AdvancedStatistics statistics={STATS} />)
    fireEvent.click(screen.getByRole('checkbox', { name: 'vehicle.statsToggle' }))
    expect(screen.queryByText('vehicle.statsSelling')).not.toBeInTheDocument()
    rerender(<AdvancedStatistics statistics={{ ...STATS, sold_price: '400.00' }} />)
    expect(screen.getByText('vehicle.statsSelling')).toBeInTheDocument()
  })

  it('turns days owned into years and months', () => {
    // 400 days = 1 year (365) + 35 days = 1 month (30) with the remainder dropped;
    // the mocked `t` lists the interpolated values as `years | months`.
    render(<AdvancedStatistics statistics={STATS} />)
    fireEvent.click(screen.getByRole('checkbox', { name: 'vehicle.statsToggle' }))
    expect(
      within(screen.getByTestId('stats-overall')).getByText('vehicle.statsDuration (1 | 1)')
    ).toBeInTheDocument()
  })

  it('writes the days-per-fill-up figure in the reader\'s locale', () => {
    setActiveLocale('de')
    try {
      render(<AdvancedStatistics statistics={STATS} />)
      fireEvent.click(screen.getByRole('checkbox', { name: 'vehicle.statsToggle' }))
      expect(within(screen.getByTestId('stats-fuel')).getByText('28,3')).toBeInTheDocument()
    } finally {
      setActiveLocale('en')
    }
  })

  it('writes every volume figure in the reader\'s locale, one call site at a time', () => {
    setActiveLocale('de')
    try {
      render(<AdvancedStatistics statistics={STATS} />)
      fireEvent.click(screen.getByRole('checkbox', { name: 'vehicle.statsToggle' }))
      const fuel = within(screen.getByTestId('stats-fuel'))
      // 28.75 L per fill-up, 1.35 L per day and 115 L in total, in gallons
      expect(fuel.getByText('7,59 gal')).toBeInTheDocument()
      expect(fuel.getByText('0,36 gal')).toBeInTheDocument()
      expect(fuel.getByText('30,4 gal')).toBeInTheDocument()
      // and none of them fell back to a decimal point
      expect(fuel.queryAllByText(/\d\.\d+ gal$/)).toHaveLength(0)
    } finally {
      setActiveLocale('en')
    }
  })

  it('remembers the choice for the next visit', () => {
    const first = render(<AdvancedStatistics statistics={STATS} />)
    fireEvent.click(screen.getByRole('checkbox', { name: 'vehicle.statsToggle' }))
    expect(window.localStorage.getItem(ADVANCED_STATS_STORAGE_KEY)).toBe('open')
    first.unmount()

    render(<AdvancedStatistics statistics={STATS} />)
    expect(screen.getByRole('checkbox', { name: 'vehicle.statsToggle' })).toBeChecked()
    expect(screen.getByTestId('stats-overall')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('checkbox', { name: 'vehicle.statsToggle' }))
    expect(window.localStorage.getItem(ADVANCED_STATS_STORAGE_KEY)).toBe('closed')
    expect(screen.queryByTestId('stats-overall')).not.toBeInTheDocument()
  })

  it('still works when browser storage throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    render(<AdvancedStatistics statistics={STATS} />)
    fireEvent.click(screen.getByRole('checkbox', { name: 'vehicle.statsToggle' }))
    expect(screen.getByTestId('stats-overall')).toBeInTheDocument()
  })

  describe('insurance basis', () => {
    // Same vehicle with the whole 180 premium counted instead of the 101 accrued.
    const PAID: OwnershipStatistics = {
      ...STATS,
      total_running_cost: '387.00',
      total_ownership_cost: '1387.00',
      expenses_total_cost: '260.00',
    }
    const open = () =>
      fireEvent.click(screen.getByRole('checkbox', { name: 'vehicle.statsToggle' }))

    it('offers no choice when there is no as-paid block', () => {
      render(<AdvancedStatistics statistics={STATS} />)
      open()
      expect(screen.queryByRole('tab', { name: 'vehicle.statsBasisPaid' })).not.toBeInTheDocument()
    })

    it('offers no choice when both ways give the same figures', () => {
      render(<AdvancedStatistics statistics={STATS} statisticsAsPaid={{ ...STATS }} />)
      open()
      expect(screen.queryByRole('tab', { name: 'vehicle.statsBasisPaid' })).not.toBeInTheDocument()
    })

    it('starts over the days in force and switches to the whole premium', () => {
      render(<AdvancedStatistics statistics={STATS} statisticsAsPaid={PAID} />)
      open()
      const overall = () => within(screen.getByTestId('stats-overall'))
      const expenses = () => within(screen.getByTestId('stats-expenses'))

      expect(screen.getByRole('tab', { name: 'vehicle.statsBasisAccrued' })).toHaveAttribute(
        'aria-selected',
        'true'
      )
      expect(overall().getByText('$308.00')).toBeInTheDocument()
      expect(expenses().getByText('vehicle.statsNote')).toBeInTheDocument()

      fireEvent.click(screen.getByRole('tab', { name: 'vehicle.statsBasisPaid' }))
      expect(overall().getByText('$387.00')).toBeInTheDocument()
      expect(overall().getByText('$1,387.00')).toBeInTheDocument()
      expect(expenses().getByText('$260.00')).toBeInTheDocument()
      expect(expenses().getByText('vehicle.statsNotePaid')).toBeInTheDocument()
      // fuel does not move with the basis
      expect(within(screen.getByTestId('stats-fuel')).getByText('$127.00')).toBeInTheDocument()
    })

    it('remembers the choice for the next visit', () => {
      const first = render(<AdvancedStatistics statistics={STATS} statisticsAsPaid={PAID} />)
      open()
      fireEvent.click(screen.getByRole('tab', { name: 'vehicle.statsBasisPaid' }))
      expect(window.localStorage.getItem(ADVANCED_STATS_BASIS_KEY)).toBe('paid')
      first.unmount()

      render(<AdvancedStatistics statistics={STATS} statisticsAsPaid={PAID} />)
      expect(
        within(screen.getByTestId('stats-overall')).getByText('$387.00')
      ).toBeInTheDocument()
    })
  })
})
