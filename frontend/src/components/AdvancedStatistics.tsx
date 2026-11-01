import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { BarChart3 } from 'lucide-react'
import { Card, Tabs, Toggle } from './ui'
import { useAccountUnitPreference } from '../hooks/useUnitPreference'
import { useUnitFormat } from '../hooks/useUnitFormat'
import { useCurrencyPreference } from '../hooks/useCurrencyPreference'
import { useCurrencySymbol } from '../hooks/useCurrencySymbol'
import { formatCurrencyZero as formatCurrency } from '../utils/formatUtils'
import {
  formatAtPrecision,
  formatCostPerSingleDistanceUnit,
  formatDistancePerCurrencyUnit,
  formatPricePerVolumeUnit,
  formatVolumeWithUnit,
  singleDistanceUnitLabel,
  singleVolumeUnitLabel,
} from '../utils/unitFormat'
import type { OwnershipStatistics } from '../types/analytics'

/** Per-browser memory of whether the block is open. Collapsed unless opened once. */
export const ADVANCED_STATS_STORAGE_KEY = 'mygarage.analytics.advancedStatistics'

function readOpen(): boolean {
  try {
    return window.localStorage.getItem(ADVANCED_STATS_STORAGE_KEY) === 'open'
  } catch {
    return false
  }
}

function writeOpen(open: boolean): void {
  try {
    window.localStorage.setItem(ADVANCED_STATS_STORAGE_KEY, open ? 'open' : 'closed')
  } catch {
    // Storage can be blocked (private window, cleared site data); the switch still works.
  }
}

/** Per-browser memory of how insurance is counted. Over the days in force unless changed. */
export const ADVANCED_STATS_BASIS_KEY = 'mygarage.analytics.advancedStatistics.insurance'

type InsuranceBasis = 'accrued' | 'paid'

function readBasis(): InsuranceBasis {
  try {
    return window.localStorage.getItem(ADVANCED_STATS_BASIS_KEY) === 'paid' ? 'paid' : 'accrued'
  } catch {
    return 'accrued'
  }
}

function writeBasis(basis: InsuranceBasis): void {
  try {
    window.localStorage.setItem(ADVANCED_STATS_BASIS_KEY, basis)
  } catch {
    // Storage can be blocked; the choice still applies for this visit.
  }
}

const num = (v: string | number | null | undefined): number | null => {
  if (v === null || v === undefined) return null
  const n = typeof v === 'number' ? v : parseFloat(v)
  return Number.isNaN(n) ? null : n
}

function StatCard({
  title,
  className = '',
  testId,
  children,
}: {
  title: string
  className?: string
  testId: string
  children: ReactNode
}) {
  return (
    <section
      data-testid={testId}
      className={`border border-border rounded-lg p-4 ${className}`}
    >
      <h3 className="text-sm font-semibold uppercase tracking-wide text-text-mute border-b border-border pb-2 mb-2">
        {title}
      </h3>
      {children}
    </section>
  )
}

/**
 * Optional, collapsed-by-default ownership statistics: Overall, Fuel-Ups and
 * Services & Expenses. Purely additive - it reads `analytics.statistics` and
 * touches none of the cards around it.
 *
 * Insurance can be counted two ways: spread over the days a policy is in force
 * (the default), or in full once a term has started, the way a tracker that
 * logs the whole premium on the day it is paid reads. The server sends both
 * blocks; this component only picks which to show, and offers the choice only
 * when the two differ.
 */
export default function AdvancedStatistics({
  statistics,
  statisticsAsPaid = null,
}: {
  statistics: OwnershipStatistics
  statisticsAsPaid?: OwnershipStatistics | null
}) {
  const { t } = useTranslation('analytics')
  const { units: accountUnits } = useAccountUnitPreference()
  const u = useUnitFormat()
  const { currencyCode, locale } = useCurrencyPreference()
  const currencySymbol = useCurrencySymbol()
  const [open, setOpen] = useState(readOpen)
  const [basis, setBasis] = useState<InsuranceBasis>(readBasis)
  // Only insurance differs between the two blocks, and it flows into the running,
  // ownership and expenses totals alike, so the running total is enough to tell
  // whether the switch has anything to show. Compared as numbers, not strings.
  const basisDiffers =
    statisticsAsPaid !== null &&
    num(statisticsAsPaid.total_running_cost) !== num(statistics.total_running_cost)
  const s = basis === 'paid' && statisticsAsPaid !== null ? statisticsAsPaid : statistics

  const na = t('vehicle.notAvailable')
  const money = (v: string | number | null | undefined) => {
    const n = num(v)
    return n === null ? na : formatCurrency(n, { currencyCode, locale, fractionDigits: 2 })
  }
  const perDistance = (v: string | null | undefined) => {
    const n = num(v)
    return n === null ? na : formatCostPerSingleDistanceUnit(accountUnits, n, currencyCode, locale)
  }
  const distance = (v: string | null | undefined) => {
    const n = num(v)
    return n === null ? na : u.distance.format(n)
  }
  const economy = (v: string | null | undefined) => {
    const n = num(v)
    return n === null ? na : u.consumption.format(n)
  }
  const price = (v: string | null | undefined) => {
    const n = num(v)
    return n === null ? na : formatPricePerVolumeUnit(accountUnits, n, currencyCode, locale)
  }
  const volume = (v: string | null | undefined, digits = 2) => {
    const n = num(v)
    return n === null ? na : formatVolumeWithUnit(accountUnits, n, digits)
  }
  const distUnit = singleDistanceUnitLabel(accountUnits)
  const volUnit = singleVolumeUnitLabel(accountUnits)
  const days = s.days_owned ?? null
  const duration =
    days === null
      ? na
      : t('vehicle.statsDuration', { years: Math.floor(days / 365), months: Math.floor((days % 365) / 30) })
  const perCurrency = num(s.km_per_currency_unit)
  const daysPerFillup = num(s.avg_days_per_fillup)

  const row = (label: string, value: string, strong = false) => (
    <div key={label} className="flex items-baseline justify-between gap-4 py-1">
      <span className="text-sm text-text-mute">{label}</span>
      <span className={`text-sm text-right text-text ${strong ? 'font-semibold' : ''}`}>{value}</span>
    </div>
  )
  const gap = <div className="h-3" />
  // Fuel-Ups is one slim list, so the page stays two columns wide. The figures come in
  // two blocks: averages and best first, then the latest and the extremes, with a
  // faint rule between. Each block is a few small groups, spaced like the rest.
  const groupsOf = (groups: ReactNode[][]) =>
    groups.map((rows, i) => (
      <div key={i} className={i > 0 ? 'mt-3' : ''}>
        {rows}
      </div>
    ))

  const averages: ReactNode[][] = [
    [
      row(t('vehicle.statsAvgEconomy'), economy(s.avg_l_per_100km), true),
      row(t('vehicle.statsBestEconomy'), economy(s.best_l_per_100km)),
    ],
    [
      row(t('vehicle.statsAvgPrice', { unit: volUnit }), price(s.avg_price_per_liter)),
      row(t('vehicle.statsMinPrice', { unit: volUnit }), price(s.min_price_per_liter)),
    ],
    [
      row(t('vehicle.statsFuelPerUnit', { unit: distUnit }), perDistance(s.fuel_cost_per_km)),
      row(
        t('vehicle.statsUnitsPerCurrency', { unit: distUnit, currency: currencySymbol }),
        perCurrency === null ? na : formatDistancePerCurrencyUnit(accountUnits, perCurrency)
      ),
      row(t('vehicle.statsVolumePerFillup', { unit: volUnit }), volume(s.avg_liters_per_fillup)),
      row(t('vehicle.statsDaysPerFillup'), daysPerFillup === null ? na : formatAtPrecision(daysPerFillup, 1)),
    ],
    [row(t('vehicle.statsFuelTotal'), money(s.fuel_total_cost), true)],
  ]
  const latest: ReactNode[][] = [
    [
      row(t('vehicle.statsLastEconomy'), economy(s.recent_l_per_100km)),
      row(t('vehicle.statsWorstEconomy'), economy(s.worst_l_per_100km)),
    ],
    [
      row(t('vehicle.statsLastPrice', { unit: volUnit }), price(s.last_price_per_liter)),
      row(t('vehicle.statsMaxPrice', { unit: volUnit }), price(s.max_price_per_liter)),
    ],
    [
      row(t('vehicle.statsFuelPerDay'), money(s.fuel_cost_per_day)),
      row(t('vehicle.statsPerFillup'), money(s.avg_cost_per_fillup)),
      row(t('vehicle.statsDistancePerFillup', { unit: distUnit }), distance(s.avg_km_per_fillup)),
      row(t('vehicle.statsVolumePerDay', { unit: volUnit }), volume(s.liters_per_day)),
    ],
    [row(t('vehicle.statsFuelVolume', { unit: volUnit }), volume(s.fuel_total_liters, 1))],
  ]

  const toggle = (next: boolean) => {
    setOpen(next)
    writeOpen(next)
  }
  const chooseBasis = (id: string) => {
    const next: InsuranceBasis = id === 'paid' ? 'paid' : 'accrued'
    setBasis(next)
    writeBasis(next)
  }

  return (
    <Card className="mb-8">
      <div className="flex items-center gap-3">
        <BarChart3 className="w-5 h-5 text-text-mute" />
        <h2 className="text-xl font-bold text-text">{t('vehicle.statsTitle')}</h2>
        <Toggle label={t('vehicle.statsToggle')} hideLabel checked={open} onChange={toggle} />
      </div>

      {open && (
        <>
        {basisDiffers && (
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <span className="text-sm text-text-mute">{t('vehicle.statsBasisLabel')}</span>
            <Tabs
              variant="segmented"
              label={t('vehicle.statsBasisLabel')}
              activeId={basis}
              onChange={chooseBasis}
              items={[
                { id: 'accrued', label: t('vehicle.statsBasisAccrued') },
                { id: 'paid', label: t('vehicle.statsBasisPaid') },
              ]}
            />
          </div>
        )}
        <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)] gap-4 mt-4">
          <div className="flex flex-col gap-4">
            <StatCard title={t('vehicle.statsOverall')} testId="stats-overall">
              {row(t('vehicle.statsTotalRunning'), money(s.total_running_cost), true)}
              {row(t('vehicle.statsRunningPerDay'), money(s.running_cost_per_day))}
              {row(t('vehicle.statsRunningPerUnit', { unit: distUnit }), perDistance(s.running_cost_per_km))}
              {row(t('vehicle.statsDistancePerDay'), distance(s.km_per_day))}
              {gap}
              {row(t('vehicle.statsPurchase'), money(s.purchase_price))}
              {s.sold_price != null && row(t('vehicle.statsSelling'), money(s.sold_price))}
              {row(t('vehicle.statsOwnership'), money(s.total_ownership_cost), true)}
              {row(t('vehicle.statsOwnershipPerDay'), money(s.ownership_cost_per_day))}
              {row(t('vehicle.statsOwnershipPerUnit', { unit: distUnit }), perDistance(s.ownership_cost_per_km))}
              {gap}
              {row(t('vehicle.statsTotalDistance'), distance(s.km_driven))}
              {row(t('vehicle.statsTotalTime'), duration)}
            </StatCard>
            <StatCard title={t('vehicle.statsExpenses')} testId="stats-expenses">
              {row(t('vehicle.statsExpensesTotal'), money(s.expenses_total_cost), true)}
              {row(t('vehicle.statsExpensesPerDay'), money(s.expenses_cost_per_day))}
              {row(t('vehicle.statsExpensesPerUnit', { unit: distUnit }), perDistance(s.expenses_cost_per_km))}
              <p className="text-xs text-text-mute mt-4">{basis === 'paid' ? t('vehicle.statsNotePaid') : t('vehicle.statsNote')}</p>
            </StatCard>
          </div>

          <StatCard
            title={t('vehicle.statsFuelUps', { count: s.fuel_count })}
            testId="stats-fuel"
          >
            {groupsOf(averages)}
            <div className="border-t border-dashed border-border my-3" />
            {groupsOf(latest)}
          </StatCard>

        </div>
        </>
      )}
    </Card>
  )
}
