import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import api from '../services/api'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { Car, Wrench, Fuel, Shield, FileText, HelpCircle, Droplets, Landmark } from 'lucide-react'
import {
  ResponsiveContainer,
  PieChart as RechartsPieChart,
  Pie,
  Cell,
  Tooltip,
  ComposedChart,
  Bar,
  XAxis,
  YAxis,
  Legend,
  Line,
} from 'recharts'
import type { GarageAnalytics } from '../types/analytics'
import GarageAnalyticsHelpDrawer from '../components/GarageAnalyticsHelpDrawer'
import ExportMenu from '../components/ExportMenu'
import { Button } from '../components/ui'
import { formatCurrencyZero as formatCurrency } from '../utils/formatUtils'
import { trailingAverage } from '../utils/rollingAverage'
import { useCurrencyPreference } from '../hooks/useCurrencyPreference'
import { useTimeFormat } from '../hooks/useTimeFormat'
import { formatDateTime } from '../utils/parseAPITimestamp'

// Colors for pie chart categories (10 categories: Maintenance, Upgrades, Inspection, Collision, Detailing, Fuel, DEF, Insurance, Taxes, Financing)
const COLORS = ['#3B82F6', '#8B5CF6', '#F59E0B', '#EF4444', '#10B981', '#06B6D4', '#14B8A6', '#EC4899', '#6B7280', '#84CC16']

// Running-cost total for one month: service, fuel and DEF. Financing has its
// own bar/legend entry but is excluded here, same as it's excluded from
// total_cost/cost-per-distance elsewhere. A lease payment isn't a cost of
// driving the vehicle.
const monthlyTrendTotal = (trend: GarageAnalytics['monthly_trends'][number]) =>
  parseFloat(trend.service) + parseFloat(trend.fuel) + parseFloat(trend.def_cost)

// The API always sends the last 12 months, zeros and all, so a row count can't
// tell a quiet garage apart. Anything the chart plots counts, financing too.
const hasTrend = (trends: GarageAnalytics['monthly_trends']): boolean =>
  trends.some((trend) => monthlyTrendTotal(trend) > 0 || parseFloat(trend.financing) > 0)

export default function GarageAnalytics() {
  const { t } = useTranslation('analytics')
  const { currencyCode, locale } = useCurrencyPreference()
  const { timeFormat } = useTimeFormat()
  const [analytics, setAnalytics] = useState<GarageAnalytics | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [fromCache, setFromCache] = useState(false)
  const [showHelp, setShowHelp] = useState(false)

  const exportToCSV = () => {
    if (!analytics) return

    const rows: string[] = []

    // Header
    rows.push('MyGarage Garage Analytics Export')
    rows.push(`Generated: ${formatDateTime(new Date(), timeFormat, { seconds: true })}`)
    rows.push(`Total Vehicles: ${analytics.vehicle_count}`)
    rows.push('')

    // Garage Summary
    rows.push('Garage Cost Summary')
    rows.push('Category,Amount')
    rows.push(`Garage Value,${analytics.total_costs.total_garage_value}`)
    rows.push(`Maintenance,${analytics.total_costs.total_maintenance}`)
    rows.push(`Upgrades,${analytics.total_costs.total_upgrades}`)
    rows.push(`Inspection,${analytics.total_costs.total_inspection}`)
    rows.push(`Collision,${analytics.total_costs.total_collision}`)
    rows.push(`Detailing,${analytics.total_costs.total_detailing}`)
    rows.push(`Fuel,${analytics.total_costs.total_fuel}`)
    rows.push(`DEF,${analytics.total_costs.total_def}`)
    rows.push(`Insurance,${analytics.total_costs.total_insurance}`)
    rows.push(`Taxes,${analytics.total_costs.total_taxes}`)
    rows.push(`Financing,${analytics.total_costs.total_financing}`)
    rows.push('')

    // Cost by Category
    rows.push('Cost Breakdown by Category')
    rows.push('Category,Amount')
    analytics.cost_breakdown_by_category.forEach((cat) => {
      rows.push(`${cat.category},${cat.amount}`)
    })
    rows.push('')

    // Cost by Vehicle
    rows.push('Cost by Vehicle')
    rows.push('Vehicle,Purchase Price,Maintenance,Upgrades,Inspection,Collision,Detailing,Fuel,DEF,Financing,Running Costs')
    analytics.cost_by_vehicle.forEach((vehicle) => {
      rows.push(
        `"${vehicle.name}",${vehicle.purchase_price},${vehicle.total_maintenance},${vehicle.total_upgrades},${vehicle.total_inspection},${vehicle.total_collision},${vehicle.total_detailing},${vehicle.total_fuel},${vehicle.total_def},${vehicle.total_financing},${vehicle.total_cost}`
      )
    })
    rows.push('')

    // Monthly Trends
    if (hasTrend(analytics.monthly_trends)) {
      rows.push('Monthly Spending Trends')
      rows.push('Month,Service,Fuel,DEF,Financing,Total')
      analytics.monthly_trends.forEach((trend) => {
        const total = monthlyTrendTotal(trend).toFixed(2)
        rows.push(`${trend.month},${trend.service},${trend.fuel},${trend.def_cost},${trend.financing},${total}`)
      })
    }

    // Create and download CSV
    const csvContent = rows.join('\n')
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
    const link = document.createElement('a')
    const url = URL.createObjectURL(blob)
    link.setAttribute('href', url)
    link.setAttribute('download', `garage-analytics-${Date.now()}.csv`)
    link.style.visibility = 'hidden'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  const exportToPDF = async () => {
    try {
      const response = await api.get('/analytics/garage/export', {
        responseType: 'blob',
        params: { currency_code: currencyCode, locale },
      })

      const blob = new Blob([response.data], { type: 'application/pdf' })
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `garage-analytics-${Date.now()}.pdf`)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (err) {
      console.error('PDF export failed:', err)
      alert(t('garage.exportPdfFailed'))
    }
  }

  useEffect(() => {
    const fetchAnalytics = async () => {
      const cacheKey = 'garage-analytics-cache'

      try {
        setLoading(true)
        setError(null)
        setFromCache(false)

        const response = await api.get('/analytics/garage')
        const data: GarageAnalytics = response.data
        setAnalytics(data)

        // Cache the data
        localStorage.setItem(
          cacheKey,
          JSON.stringify({
            timestamp: Date.now(),
            data,
          })
        )
      } catch (err) {
        const errorMessage = getActionErrorMessage(err, t('garage.loadAction'))
        setError(errorMessage)

        // If offline, try to load from cache
        if (!navigator.onLine) {
          const cached = localStorage.getItem(cacheKey)
          if (cached) {
            try {
              const parsed = JSON.parse(cached)
              setAnalytics(parsed.data)
              setFromCache(true)
              setError(t('garage.offlineCached'))
            } catch {
              // Invalid cache
            }
          }
        }
      } finally {
        setLoading(false)
      }
    }

    fetchAnalytics()
  }, [t])

  // Custom tooltip styling for charts
  const customTooltipStyle = {
    backgroundColor: '#1a1f28',
    border: '1px solid #3a4050',
    borderRadius: '8px',
    padding: '12px',
    color: '#e4e6eb',
  }

  if (loading) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="flex items-center justify-center py-16" role="status" aria-label={t('garage.loadingAria')}>
          <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
          <span className="sr-only">{t('garage.loading')}</span>
        </div>
      </div>
    )
  }

  if (!analytics || analytics.vehicle_count === 0) {
    return (
      <div className="container mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold mb-2 text-garage-text">{t('garage.title')}</h1>
        <p className="text-garage-text-muted mb-8">{t('garage.subtitle')}</p>

        <div className="bg-garage-surface rounded-lg border border-garage-border text-center py-16">
          <Car className="w-16 h-16 text-garage-text-muted mx-auto mb-4 opacity-50" />
          <h3 className="text-xl font-semibold mb-2 text-garage-text">{t('garage.empty.title')}</h3>
          <p className="text-garage-text-muted mb-6">{t('garage.empty.body')}</p>
        </div>
      </div>
    )
  }

  const { total_costs, cost_breakdown_by_category, cost_by_vehicle, monthly_trends } = analytics

  // Cost-by-category: assign each category a stable colour by its ORIGINAL
  // (backend) order, so a slice's colour stays matched to its sidebar swatch
  // even after we sort largest-first below.
  const categoryMeta = cost_breakdown_by_category
    .map((item, index) => ({
      category: item.category,
      amount: item.amount,
      value: parseFloat(item.amount),
      color: COLORS[index % COLORS.length],
    }))
    .filter((c) => c.value > 0)
  const categoryTotal = categoryMeta.reduce((sum, c) => sum + c.value, 0)
  const sortedCategories = [...categoryMeta]
    .sort((a, b) => b.value - a.value)
    .map((c) => ({ ...c, percent: categoryTotal > 0 ? (c.value / categoryTotal) * 100 : 0 }))
  const formatPercent = (pct: number) => (pct > 0 && pct < 1 ? '<1%' : `${Math.round(pct)}%`)

  // Donut slices follow the sidebar order (largest-first), same stable colour.
  const pieData = sortedCategories.map((c) => ({ name: c.category, value: c.value, color: c.color }))

  // Running costs: nickname + total, top 10. Bar-list widths are relative to
  // the largest running cost.
  const barData = cost_by_vehicle.slice(0, 10).map((vehicle) => ({
    name: vehicle.nickname,
    totalCost: parseFloat(vehicle.total_cost),
  }))
  const maxVehicleCost = barData.reduce((max, v) => Math.max(max, v.totalCost), 0)

  // Monthly trend: trailing averages over the running-cost months only. Empty
  // months, and ones with just insurance or financing, total zero and get
  // skipped like on the vehicle page: null there, bridged by connectNulls, and
  // no line before the first running month or after the last. A $0 record
  // counts now, but it still adds nothing, so the > 0 filter holds.
  const runningCostMonths = monthly_trends.filter((trend) => monthlyTrendTotal(trend) > 0)
  const runningTotals = runningCostMonths.map(monthlyTrendTotal)
  const rollingAvg3 = trailingAverage(runningTotals, 3)
  const rollingAvg6 = trailingAverage(runningTotals, 6)
  const runningIndex = new Map(runningCostMonths.map((trend, idx) => [trend, idx]))

  const formatMonthLabel = (value: string) => {
    const parsed = new Date(`${value} 1`)
    if (Number.isNaN(parsed.getTime())) return value
    return new Intl.DateTimeFormat(locale, { month: 'short', year: '2-digit' }).format(parsed)
  }

  const trendData = monthly_trends.map((trend) => {
    const idx = runningIndex.get(trend)
    return {
      month: formatMonthLabel(trend.month),
      Service: parseFloat(trend.service),
      Fuel: parseFloat(trend.fuel),
      DEF: parseFloat(trend.def_cost),
      Financing: parseFloat(trend.financing),
      avg3: idx === undefined ? null : rollingAvg3[idx],
      avg6: idx === undefined ? null : rollingAvg6[idx],
    }
  })

  return (
    <div className="container mx-auto px-4 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold mb-2 text-garage-text">{t('garage.title')}</h1>
          <p className="text-garage-text-muted">
            {t('garage.subtitleCount', { count: analytics.vehicle_count })}
          </p>
          {fromCache && error && (
            <p className="text-warning text-sm mt-1">{error}</p>
          )}
        </div>

        <div className="flex gap-2">
          <Button variant="secondary" icon={HelpCircle} onClick={() => setShowHelp(true)}>
            {t('garage.help')}
          </Button>
          <ExportMenu onExportCSV={exportToCSV} onExportPDF={exportToPDF} variant="accent" />
        </div>
      </div>

      {/* Total Cost Summary Cards. Garage value, Maintenance and Fuel always show;
          DEF, Financing, Insurance and Taxes only once there's money in them. */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
        <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium text-garage-text-muted">{t('garage.cards.garageValue')}</h3>
            <Car className="w-5 h-5 text-primary" />
          </div>
          <p className="text-2xl font-bold text-garage-text">
            {formatCurrency(total_costs.total_garage_value, { currencyCode, locale })}
          </p>
        </div>

        <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium text-garage-text-muted">{t('garage.cards.maintenance')}</h3>
            <Wrench className="w-5 h-5 text-primary" />
          </div>
          <p className="text-2xl font-bold text-garage-text">
            {formatCurrency(total_costs.total_maintenance, { currencyCode, locale })}
          </p>
        </div>

        <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium text-garage-text-muted">{t('garage.cards.fuel')}</h3>
            <Fuel className="w-5 h-5 text-success-500" />
          </div>
          <p className="text-2xl font-bold text-garage-text">
            {formatCurrency(total_costs.total_fuel, { currencyCode, locale })}
          </p>
        </div>

        {parseFloat(total_costs.total_def) > 0 && (
          <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-medium text-garage-text-muted">{t('garage.cards.def')}</h3>
              <Droplets className="w-5 h-5 text-teal-500" />
            </div>
            <p className="text-2xl font-bold text-garage-text">
              {formatCurrency(total_costs.total_def, { currencyCode, locale })}
            </p>
          </div>
        )}

        {parseFloat(total_costs.total_financing) > 0 && (
          <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-medium text-garage-text-muted">{t('garage.cards.financing')}</h3>
              <Landmark className="w-5 h-5 text-lime-500" />
            </div>
            <p className="text-2xl font-bold text-garage-text">
              {formatCurrency(total_costs.total_financing, { currencyCode, locale })}
            </p>
          </div>
        )}

        {parseFloat(total_costs.total_insurance) > 0 && (
          <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-medium text-garage-text-muted">{t('garage.cards.insurance')}</h3>
              <Shield className="w-5 h-5 text-warning-500" />
            </div>
            <p className="text-2xl font-bold text-garage-text">
              {formatCurrency(total_costs.total_insurance, { currencyCode, locale })}
            </p>
          </div>
        )}

        {parseFloat(total_costs.total_taxes) > 0 && (
          <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-medium text-garage-text-muted">{t('garage.cards.taxes')}</h3>
              <FileText className="w-5 h-5 text-danger-500" />
            </div>
            <p className="text-2xl font-bold text-garage-text">
              {formatCurrency(total_costs.total_taxes, { currencyCode, locale })}
            </p>
          </div>
        )}
      </div>

      {/* Cost Breakdown Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
        {/* Donut - Cost by Category */}
        <div className="bg-garage-surface border border-garage-border rounded-lg p-6 lg:col-span-1">
          <h2 className="text-xl font-bold mb-4 text-garage-text">{t('garage.costByCategory')}</h2>
          {categoryTotal > 0 ? (
            <div className="flex flex-col sm:flex-row lg:flex-col gap-6">
              {/* Donut + summary tiles */}
              <div className="flex flex-col sm:w-1/2 lg:w-full">
                <div className="relative w-full" style={{ height: 200 }}>
                  {/* Numeric height (matches the 200px wrapper). A percentage
                      height on a ResponsiveContainer nested in this flex column
                      is a known Recharts fragility, so pin it. */}
                  <ResponsiveContainer width="100%" height={200}>
                    <RechartsPieChart>
                      <Pie
                        data={pieData}
                        cx="50%"
                        cy="50%"
                        innerRadius={62}
                        outerRadius={90}
                        paddingAngle={2}
                        dataKey="value"
                        stroke="none"
                      >
                        {pieData.map((entry) => (
                          <Cell key={entry.name} fill={entry.color} />
                        ))}
                      </Pie>
                      <Tooltip
                        cursor={false}
                        wrapperStyle={{ outline: 'none' }}
                        content={({ active, payload }) => {
                          if (active && payload && payload.length) {
                            const data = payload[0]
                            return (
                              <div style={customTooltipStyle}>
                                <p style={{ fontWeight: '600', marginBottom: '4px' }}>{data.name}</p>
                                <p style={{ fontSize: '14px', color: '#9ca3af' }}>
                                  {formatCurrency(data.value as number, { currencyCode, locale })}
                                </p>
                              </div>
                            )
                          }
                          return null
                        }}
                      />
                    </RechartsPieChart>
                  </ResponsiveContainer>
                  {/* Center total */}
                  <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                    <span className="text-[11px] uppercase tracking-wide text-garage-text-muted">
                      {t('garage.donutTotal')}
                    </span>
                    <span className="text-lg font-bold text-garage-text">
                      {formatCurrency(categoryTotal, { currencyCode, locale })}
                    </span>
                  </div>
                </div>
              </div>
              {/* Sidebar category list */}
              <div className="sm:w-1/2 lg:w-full space-y-3">
                {sortedCategories.map((c) => (
                  <div key={c.category}>
                    <div className="flex items-center justify-between text-sm mb-1">
                      <span className="flex items-center gap-2 text-garage-text">
                        <span
                          className="w-2.5 h-2.5 rounded-full shrink-0"
                          style={{ backgroundColor: c.color }}
                        />
                        {c.category}
                      </span>
                      <span className="flex items-center gap-2 shrink-0">
                        <span className="text-garage-text-muted tabular-nums">{formatPercent(c.percent)}</span>
                        <span className="text-garage-text font-medium tabular-nums">
                          {formatCurrency(c.amount, { currencyCode, locale })}
                        </span>
                      </span>
                    </div>
                    <div className="h-1.5 rounded-full bg-garage-border/40 overflow-hidden">
                      <div
                        className="h-full rounded-full"
                        style={{ width: `${Math.max(c.percent, 2)}%`, backgroundColor: c.color }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-garage-text-muted text-center py-8">{t('garage.noCostData')}</p>
          )}
        </div>

        {/* Running Costs by Vehicle */}
        <div className="bg-garage-surface border border-garage-border rounded-lg p-6 lg:col-span-2">
          <h2 className="text-xl font-bold mb-4 text-garage-text">{t('garage.runningCostsByVehicle')}</h2>
          {barData.length > 0 ? (
            <>
              {/* Bar list — name + inline total, width relative to the top spender */}
              <div className="space-y-3">
                {barData.map((vehicle) => (
                  <div key={vehicle.name}>
                    <div className="flex items-center justify-between text-sm mb-1">
                      <span className="text-garage-text font-medium">{vehicle.name}</span>
                      <span className="text-garage-text font-semibold tabular-nums">
                        {formatCurrency(vehicle.totalCost, { currencyCode, locale })}
                      </span>
                    </div>
                    <div className="h-2 rounded-full bg-garage-border/40 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-primary"
                        style={{ width: `${maxVehicleCost > 0 ? (vehicle.totalCost / maxVehicleCost) * 100 : 0}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>

              {/* Vehicle Cost Breakdown Table */}
              <div className="mt-6 overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-garage-border">
                      <th className="text-left py-2 px-3 text-sm font-medium text-garage-text-muted">
                        {t('garage.table.vehicle')}
                      </th>
                      <th className="text-right py-2 px-3 text-sm font-medium text-garage-text-muted">
                        {t('garage.table.maintenance')}
                      </th>
                      <th className="text-right py-2 px-3 text-sm font-medium text-garage-text-muted">
                        {t('garage.table.upgrades')}
                      </th>
                      <th className="text-right py-2 px-3 text-sm font-medium text-garage-text-muted">
                        {t('garage.table.inspection')}
                      </th>
                      <th className="text-right py-2 px-3 text-sm font-medium text-garage-text-muted">
                        {t('garage.table.collision')}
                      </th>
                      <th className="text-right py-2 px-3 text-sm font-medium text-garage-text-muted">
                        {t('garage.table.detailing')}
                      </th>
                      <th className="text-right py-2 px-3 text-sm font-medium text-garage-text-muted">
                        {t('garage.table.fuel')}
                      </th>
                      <th className="text-right py-2 px-3 text-sm font-medium text-garage-text-muted">
                        {t('garage.table.def')}
                      </th>
                      <th className="text-right py-2 px-3 text-sm font-medium text-garage-text-muted">
                        {t('garage.table.financing')}
                      </th>
                      <th className="text-right py-2 px-3 text-sm font-medium text-garage-text-muted">
                        {t('garage.table.total')}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {cost_by_vehicle.map((vehicle, index) => (
                      <tr key={index} className="border-b border-garage-border/50 hover:bg-garage-surface-light transition-colors">
                        <td className="py-2 px-3 text-sm text-garage-text">{vehicle.nickname}</td>
                        <td className="py-2 px-3 text-sm text-garage-text text-right">
                          {formatCurrency(vehicle.total_maintenance, { currencyCode, locale })}
                        </td>
                        <td className="py-2 px-3 text-sm text-garage-text text-right">
                          {formatCurrency(vehicle.total_upgrades, { currencyCode, locale })}
                        </td>
                        <td className="py-2 px-3 text-sm text-garage-text text-right">
                          {formatCurrency(vehicle.total_inspection, { currencyCode, locale })}
                        </td>
                        <td className="py-2 px-3 text-sm text-garage-text text-right">
                          {formatCurrency(vehicle.total_collision, { currencyCode, locale })}
                        </td>
                        <td className="py-2 px-3 text-sm text-garage-text text-right">
                          {formatCurrency(vehicle.total_detailing, { currencyCode, locale })}
                        </td>
                        <td className="py-2 px-3 text-sm text-garage-text text-right">
                          {formatCurrency(vehicle.total_fuel, { currencyCode, locale })}
                        </td>
                        <td className="py-2 px-3 text-sm text-garage-text text-right">
                          {formatCurrency(vehicle.total_def, { currencyCode, locale })}
                        </td>
                        <td className="py-2 px-3 text-sm text-garage-text text-right">
                          {formatCurrency(vehicle.total_financing, { currencyCode, locale })}
                        </td>
                        <td className="py-2 px-3 text-sm text-garage-text text-right font-semibold">
                          {formatCurrency(vehicle.total_cost, { currencyCode, locale })}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <p className="text-garage-text-muted text-center py-8">{t('garage.noVehicleData')}</p>
          )}
        </div>
      </div>

      {/* Monthly Spending Trend */}
      {hasTrend(monthly_trends) && (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-6 mb-8">
          <h2 className="text-xl font-bold mb-4 text-garage-text">{t('garage.monthlySpendingTrend')}</h2>
          <ResponsiveContainer width="100%" height={300}>
            {/* ComposedChart, not BarChart: Recharts v3 only renders <Line>
                children inside a ComposedChart, so the rolling-average trend
                lines below are silently dropped by a plain <BarChart>. */}
            <ComposedChart data={trendData} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
              <XAxis
                dataKey="month"
                stroke="#9E9E9E"
                style={{ fontSize: '12px' }}
                tickLine={false}
                axisLine={false}
                height={30}
              />
              <YAxis hide />
              <Tooltip
                cursor={false}
                wrapperStyle={{ outline: 'none' }}
                content={({ active, payload }) => {
                  if (active && payload && payload.length) {
                    return (
                      <div style={customTooltipStyle}>
                        <p style={{ fontWeight: '600', marginBottom: '8px' }}>
                          {payload[0].payload.month}
                        </p>
                        {payload.map((entry, index) =>
                          // A rolling average is null on months with no running costs.
                          entry.value == null ? null : (
                            <p
                              key={index}
                              style={{ fontSize: '14px', color: '#9ca3af', marginBottom: '4px' }}
                            >
                              {entry.name}: {formatCurrency(entry.value as number, { currencyCode, locale })}
                            </p>
                          )
                        )}
                      </div>
                    )
                  }
                  return null
                }}
              />
              <Legend wrapperStyle={{ paddingTop: '10px', fontSize: '12px' }} />
              <Bar dataKey="Service" name={t('garage.cards.maintenance')} fill="#3B82F6" stackId="a" maxBarSize={40} />
              <Bar dataKey="Fuel" name={t('garage.cards.fuel')} fill="#10B981" stackId="a" maxBarSize={40} />
              <Bar dataKey="DEF" name={t('garage.cards.def')} fill="#14B8A6" stackId="a" maxBarSize={40} />
              <Bar dataKey="Financing" name={t('garage.cards.financing')} fill="#84CC16" stackId="a" maxBarSize={40} />

              {/* Rolling average trend lines over the running-cost months; each
                  mounts once there are enough of those months to average. */}
              {runningCostMonths.length >= 3 && (
                <Line
                  type="monotone"
                  dataKey="avg3"
                  stroke="#10B981"
                  strokeWidth={2}
                  strokeDasharray="5 5"
                  dot={false}
                  name={t('garage.rollingAvg3')}
                  connectNulls
                />
              )}
              {runningCostMonths.length >= 6 && (
                <Line
                  type="monotone"
                  dataKey="avg6"
                  stroke="#8B5CF6"
                  strokeWidth={2}
                  strokeDasharray="5 5"
                  dot={false}
                  name={t('garage.rollingAvg6')}
                  connectNulls
                />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Help sidecar */}
      <GarageAnalyticsHelpDrawer open={showHelp} onClose={() => setShowHelp(false)} />
    </div>
  )
}
