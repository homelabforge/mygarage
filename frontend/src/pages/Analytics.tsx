/**
 * Analytics Page - Vehicle Reports and Analytics
 */

import { useState, useEffect, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import api from '../services/api'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitFormatter } from '../utils/units'
import {
  ArrowLeft,
  TrendingUp,
  TrendingDown,
  Minus,
  DollarSign,
  Fuel,
  Wrench,
  Calendar,
  BarChart3,
  PieChart,
  LineChart,
  AlertTriangle,
  Download,
  HelpCircle,
} from 'lucide-react'
import {
  LineChart as RechartsLineChart,
  Line,
  BarChart as RechartsBarChart,
  Bar,
  PieChart as RechartsPieChart,
  Pie,
  Cell,
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import type { PieLabelRenderProps, TooltipContentProps } from 'recharts'
import type { Payload } from 'recharts/types/component/DefaultTooltipContent'
import type {
  FuelAlertSeverity,
  VehicleAnalytics,
  VendorAnalyticsSummary,
  SeasonalAnalyticsSummary,
  PeriodComparison,
} from '../types/analytics'
import AnalyticsHelpModal from '../components/AnalyticsHelpModal'

export default function Analytics() {
  const { vin } = useParams<{ vin: string }>()
  const { system, showBoth } = useUnitPreference()
  const [analytics, setAnalytics] = useState<VehicleAnalytics | null>(null)
  const [vendorAnalytics, setVendorAnalytics] = useState<VendorAnalyticsSummary | null>(null)
  const [seasonalAnalytics, setSeasonalAnalytics] = useState<SeasonalAnalyticsSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [fromCache, setFromCache] = useState(false)

  // Period comparison state
  const [showComparison, setShowComparison] = useState(false)
  const [period1Start, setPeriod1Start] = useState('')
  const [period1End, setPeriod1End] = useState('')
  const [period2Start, setPeriod2Start] = useState('')
  const [period2End, setPeriod2End] = useState('')
  const [comparisonData, setComparisonData] = useState<PeriodComparison | null>(null)
  const [comparisonLoading, setComparisonLoading] = useState(false)

  // Help modal state
  const [showHelpModal, setShowHelpModal] = useState(false)

  // Check if vehicle is motorized (not a trailer, fifth wheel, or travel trailer)
  const isMotorized = analytics?.vehicle_type &&
    !['Trailer', 'FifthWheel', 'TravelTrailer'].includes(analytics.vehicle_type)

  // Check if vehicle is a fifth wheel, travel trailer, or RV (for propane and spot rental tracking)
  const hasPropane = analytics?.vehicle_type &&
    ['RV', 'FifthWheel', 'TravelTrailer'].includes(analytics.vehicle_type)

  const fetchAnalytics = useCallback(async () => {
    if (!vin) return

    const cacheKey = `analytics-cache-${vin}`

    try {
      setLoading(true)
      setError(null)
      setFromCache(false)
      const response = await api.get(`/analytics/vehicles/${vin}`)
      const data: VehicleAnalytics = response.data
      setAnalytics(data)
      localStorage.setItem(cacheKey, JSON.stringify({ timestamp: Date.now(), data }))
      setError(null)
    } catch (error) {
      if (!navigator.onLine) {
        const cached = localStorage.getItem(cacheKey)
        if (cached) {
          const parsed = JSON.parse(cached)
          setAnalytics(parsed.data)
          setFromCache(true)
          setError('Offline: showing cached analytics snapshot.')
          setLoading(false)
          return
        }
      }
      setError(error instanceof Error ? error.message : 'An error occurred')
    } finally {
      setLoading(false)
    }
  }, [vin])

  useEffect(() => {
    fetchAnalytics()
  }, [fetchAnalytics])

  const fetchVendorAnalytics = useCallback(async () => {
    if (!vin) return

    try {
      const response = await api.get(`/analytics/vehicles/${vin}/vendors`)
      setVendorAnalytics(response.data)
    } catch (error) {
      console.error('Failed to fetch vendor analytics:', error)
    }
  }, [vin])

  const fetchSeasonalAnalytics = useCallback(async () => {
    if (!vin) return

    try {
      const response = await api.get(`/analytics/vehicles/${vin}/seasonal`)
      setSeasonalAnalytics(response.data)
    } catch (error) {
      console.error('Failed to fetch seasonal analytics:', error)
    }
  }, [vin])

  useEffect(() => {
    if (vin) {
      fetchVendorAnalytics()
      fetchSeasonalAnalytics()
    }
  }, [vin, fetchVendorAnalytics, fetchSeasonalAnalytics])

  const handleCompare = async () => {
    if (!vin || !period1Start || !period1End || !period2Start || !period2End) {
      alert('Please fill in all date fields')
      return
    }

    try {
      setComparisonLoading(true)
      const params = new URLSearchParams({
        period1_start: period1Start,
        period1_end: period1End,
        period2_start: period2Start,
        period2_end: period2End,
      })
      const response = await api.get(`/analytics/vehicles/${vin}/compare?${params}`)
      setComparisonData(response.data)
    } catch (error) {
      console.error('Failed to fetch comparison data:', error)
      alert('Failed to fetch comparison data')
    } finally {
      setComparisonLoading(false)
    }
  }

  const exportToCSV = () => {
    if (!analytics) return

    const rows = []

    // Header
    rows.push(['MyGarage Analytics Export'])
    rows.push(['Vehicle:', analytics.vehicle_name])
    rows.push(['VIN:', analytics.vin])
    rows.push(['Export Date:', new Date().toLocaleDateString()])
    rows.push([]) // Empty row

    // Cost Analysis Summary
    rows.push(['Cost Analysis Summary'])
    rows.push(['Total Cost', formatCurrency(cost_analysis.total_cost)])
    rows.push(['Average Monthly Cost', formatCurrency(cost_analysis.average_monthly_cost)])
    rows.push(['Months Tracked', cost_analysis.months_tracked.toString()])
    rows.push(['Service Count', cost_analysis.service_count.toString()])
    rows.push(['Fuel Count', cost_analysis.fuel_count.toString()])
    if (cost_analysis.cost_per_mile) {
      rows.push(['Cost Per Mile', formatCurrency(cost_analysis.cost_per_mile)])
    }
    rows.push([]) // Empty row

    // Rolling Averages
    if (cost_analysis.rolling_avg_3m || cost_analysis.rolling_avg_6m || cost_analysis.rolling_avg_12m) {
      rows.push(['Rolling Averages'])
      if (cost_analysis.rolling_avg_3m) rows.push(['3-Month', formatCurrency(cost_analysis.rolling_avg_3m)])
      if (cost_analysis.rolling_avg_6m) rows.push(['6-Month', formatCurrency(cost_analysis.rolling_avg_6m)])
      if (cost_analysis.rolling_avg_12m) rows.push(['12-Month', formatCurrency(cost_analysis.rolling_avg_12m)])
      rows.push(['Trend Direction', cost_analysis.trend_direction])
      rows.push([]) // Empty row
    }

    // Monthly Breakdown
    rows.push(['Monthly Breakdown'])
    rows.push(['Month', 'Year', 'Service Cost', 'Fuel Cost', 'Total Cost', 'Service Count', 'Fuel Count'])
    cost_analysis.monthly_breakdown.forEach(month => {
      rows.push([
        month.month_name,
        month.year.toString(),
        month.total_service_cost,
        month.total_fuel_cost,
        month.total_cost,
        month.service_count.toString(),
        month.fuel_count.toString(),
      ])
    })
    rows.push([]) // Empty row

    // Service Type Breakdown
    if (cost_analysis.service_type_breakdown.length > 0) {
      rows.push(['Service Type Breakdown'])
      rows.push(['Service Type', 'Total Cost', 'Count', 'Average Cost'])
      cost_analysis.service_type_breakdown.forEach(service => {
        rows.push([
          service.service_type,
          service.total_cost,
          service.count.toString(),
          service.average_cost,
        ])
      })
      rows.push([]) // Empty row
    }

    // Vendor Analysis
    if (vendorAnalytics && vendorAnalytics.vendors.length > 0) {
      rows.push(['Vendor Analysis'])
      rows.push(['Total Vendors', vendorAnalytics.total_vendors.toString()])
      if (vendorAnalytics.most_used_vendor) rows.push(['Most Used Vendor', vendorAnalytics.most_used_vendor])
      if (vendorAnalytics.highest_spending_vendor) rows.push(['Highest Spending Vendor', vendorAnalytics.highest_spending_vendor])
      rows.push([]) // Empty row
      rows.push(['Vendor Name', 'Total Spent', 'Service Count', 'Average Cost', 'Service Types', 'Last Service Date'])
      vendorAnalytics.vendors.forEach(vendor => {
        rows.push([
          vendor.vendor_name,
          vendor.total_spent,
          vendor.service_count.toString(),
          vendor.average_cost,
          vendor.service_types.join(', '),
          vendor.last_service_date || 'N/A',
        ])
      })
      rows.push([]) // Empty row
    }

    // Seasonal Analysis
    if (seasonalAnalytics && seasonalAnalytics.seasons.length > 0) {
      rows.push(['Seasonal Analysis'])
      rows.push(['Annual Average', formatCurrency(seasonalAnalytics.annual_average)])
      if (seasonalAnalytics.highest_cost_season) rows.push(['Highest Cost Season', seasonalAnalytics.highest_cost_season])
      if (seasonalAnalytics.lowest_cost_season) rows.push(['Lowest Cost Season', seasonalAnalytics.lowest_cost_season])
      rows.push([]) // Empty row
      rows.push(['Season', 'Total Cost', 'Average Cost', 'Service Count', 'Variance from Annual', 'Common Services'])
      seasonalAnalytics.seasons.forEach(season => {
        rows.push([
          season.season,
          season.total_cost,
          season.average_cost,
          season.service_count.toString(),
          season.variance_from_annual + '%',
          season.common_services.join(', '),
        ])
      })
    }

    // Convert to CSV string
    const csvContent = rows.map(row =>
      row.map(cell => `"${cell.toString().replace(/"/g, '""')}"`).join(',')
    ).join('\n')

    // Create download
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = `mygarage-analytics-${analytics.vin}-${new Date().toISOString().split('T')[0]}.csv`
    link.click()
  }

  const formatCurrency = (value: string | number | null): string => {
    if (value === null || value === undefined) return '$0.00'
    const num = typeof value === 'string' ? parseFloat(value) : value
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(num)
  }

  const formatDate = (dateString: string | null): string => {
    if (!dateString) return 'N/A'
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  }

  const getTrendIcon = (trend: string) => {
    switch (trend) {
      case 'improving':
        return <TrendingUp className="w-5 h-5 text-green-500" />
      case 'declining':
        return <TrendingDown className="w-5 h-5 text-red-500" />
      default:
        return <Minus className="w-5 h-5 text-yellow-500" />
    }
  }

  const getConfidenceBadge = (confidence: string) => {
    const colors = {
      high: 'bg-green-100 text-green-800 border-green-300',
      medium: 'bg-yellow-100 text-yellow-800 border-yellow-300',
      low: 'badge-neutral border-gray-300',
    }
    return (
      <span className={`px-2 py-1 text-xs font-medium rounded border ${colors[confidence as keyof typeof colors] || colors.low}`}>
        {confidence.toUpperCase()}
      </span>
    )
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="w-12 h-12 border-4 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (error || !analytics) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="bg-danger/10 border border-danger rounded-lg p-6 text-center">
          <p className="text-danger mb-4">{error || 'Analytics not found'}</p>
          <Link
            to={`/vehicles/${vin}`}
            className="inline-flex items-center space-x-2 px-4 py-2 bg-garage-surface border border-garage-border rounded-lg hover:bg-garage-bg transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            <span>Back to Vehicle</span>
          </Link>
        </div>
      </div>
    )
  }

  const { cost_analysis, cost_projection, fuel_economy, fuel_alerts, service_history, predictions } = analytics

  return (
    <div className="container mx-auto px-4 py-8 max-w-7xl">
      {/* Header */}
      <div className="mb-6">
        <Link
          to={`/vehicles/${vin}`}
          className="inline-flex items-center space-x-2 text-primary hover:text-primary-dark mb-4"
        >
          <ArrowLeft className="w-4 h-4" />
          <span>Back to Vehicle</span>
        </Link>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-garage-text mb-2">
              Analytics & Reports
            </h1>
            <p className="text-garage-text-muted">{analytics.vehicle_name}</p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setShowHelpModal(true)}
              className="px-4 py-2 bg-garage-surface border border-garage-border text-garage-text rounded-lg hover:bg-garage-surface-light transition-colors flex items-center gap-2"
            >
              <HelpCircle className="w-4 h-4" />
              Help
            </button>
            <button
              onClick={exportToCSV}
              className="px-4 py-2 bg-garage-surface border border-garage-border text-garage-text rounded-lg hover:bg-garage-surface-light transition-colors flex items-center gap-2"
            >
              <Download className="w-4 h-4" />
              CSV
            </button>
            <button
              onClick={() => window.open(`/api/analytics/vehicles/${vin}/export`, '_blank')}
              className="px-4 py-2 bg-garage-surface border border-garage-border text-garage-text rounded-lg hover:bg-garage-surface-light transition-colors flex items-center gap-2"
            >
              <Download className="w-4 h-4" />
              PDF
            </button>
          </div>
        </div>
        {fromCache && (
          <div className="mt-2 inline-flex items-center gap-2 text-xs text-amber-500">
            <AlertTriangle className="w-4 h-4" />
            <span>Offline: showing cached analytics snapshot.</span>
          </div>
        )}
      </div>

      {/* Cost Projection & Fuel Alerts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-8">
        <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-garage-text">Cost Projection</h3>
            <DollarSign className="w-5 h-5 text-garage-text-muted" />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <p className="text-xs text-garage-text-muted">Monthly Avg</p>
              <p className="text-xl font-semibold text-garage-text">{formatCurrency(cost_projection.monthly_average)}</p>
            </div>
            <div>
              <p className="text-xs text-garage-text-muted">Next 6 Months</p>
              <p className="text-xl font-semibold text-garage-text">{formatCurrency(cost_projection.six_month_projection)}</p>
            </div>
            <div>
              <p className="text-xs text-garage-text-muted">Next 12 Months</p>
              <p className="text-xl font-semibold text-garage-text">{formatCurrency(cost_projection.twelve_month_projection)}</p>
            </div>
          </div>
          <p className="text-xs text-garage-text-muted mt-4">{cost_projection.assumptions}</p>
        </div>

        {isMotorized && (
          <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-garage-text">Fuel Efficiency Alerts</h3>
              <Fuel className="w-5 h-5 text-garage-text-muted" />
            </div>
            {(!fuel_alerts || fuel_alerts.length === 0) && (
              <p className="text-sm text-garage-text-muted">No fuel efficiency concerns detected.</p>
            )}
            <div className="space-y-3">
              {fuel_alerts?.map((alert, idx) => (
                <div
                  key={`${alert.title}-${idx}`}
                  className={`border rounded-lg p-4 ${getAlertStyles(alert.severity)}`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <p className="text-sm font-semibold">{alert.title}</p>
                    <span className="text-xs uppercase tracking-wide">{alert.severity}</span>
                  </div>
                  <p className="text-sm">{alert.message}</p>
                  {(alert.recent_mpg || alert.baseline_mpg) && (
                    <p className="text-xs mt-2">
                      Recent: {alert.recent_mpg ? UnitFormatter.formatFuelEconomy(parseFloat(alert.recent_mpg), system, showBoth) : '—'} • Baseline: {alert.baseline_mpg ? UnitFormatter.formatFuelEconomy(parseFloat(alert.baseline_mpg), system, showBoth) : '—'}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Spending Anomaly Alerts */}
        <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-garage-text">Spending Anomalies</h3>
            <AlertTriangle className="w-5 h-5 text-garage-text-muted" />
          </div>
          {(!cost_analysis.anomalies || cost_analysis.anomalies.length === 0) && (
            <p className="text-sm text-garage-text-muted">No unusual spending patterns detected.</p>
          )}
          <div className="space-y-3">
            {cost_analysis.anomalies?.map((alert, idx) => (
              <div
                key={`${alert.month}-${idx}`}
                className={`border rounded-lg p-4 ${
                  alert.severity === 'critical'
                    ? 'bg-red-50 border-red-300 text-red-900'
                    : 'bg-yellow-50 border-yellow-300 text-yellow-900'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <p className="text-sm font-semibold">{alert.month}</p>
                  <span className="text-xs uppercase tracking-wide">{alert.severity}</span>
                </div>
                <p className="text-sm">{alert.message}</p>
                <p className="text-xs mt-2">
                  Spent: ${parseFloat(alert.amount).toFixed(2)} • Avg: ${parseFloat(alert.baseline).toFixed(2)} • Deviation: {parseFloat(alert.deviation_percent).toFixed(1)}%
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
        <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium text-garage-text-muted">Total Cost</h3>
            <DollarSign className="w-5 h-5 text-garage-text-muted" />
          </div>
          <p className="text-2xl font-bold text-garage-text">
            {formatCurrency(cost_analysis.total_cost)}
          </p>
          <p className="text-xs text-garage-text-muted mt-1">
            {cost_analysis.months_tracked} months tracked
          </p>
        </div>

        <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium text-garage-text-muted">Avg Monthly</h3>
            <BarChart3 className="w-5 h-5 text-garage-text-muted" />
          </div>
          <p className="text-2xl font-bold text-garage-text">
            {formatCurrency(cost_analysis.average_monthly_cost)}
          </p>
          <p className="text-xs text-garage-text-muted mt-1">
            {cost_analysis.service_count + cost_analysis.fuel_count} records
          </p>
        </div>

        {isMotorized && (
          <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-medium text-garage-text-muted">Avg Fuel Economy</h3>
              <Fuel className="w-5 h-5 text-garage-text-muted" />
            </div>
            <p className="text-2xl font-bold text-garage-text">
              {fuel_economy.average_mpg ? UnitFormatter.formatFuelEconomy(parseFloat(fuel_economy.average_mpg), system, showBoth) : 'N/A'}
            </p>
            <div className="flex items-center gap-2 mt-1">
              {getTrendIcon(fuel_economy.trend)}
              <p className="text-xs text-garage-text-muted capitalize">{fuel_economy.trend}</p>
            </div>
          </div>
        )}

        {isMotorized && (
          <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-medium text-garage-text-muted">Cost Per Mile</h3>
              <LineChart className="w-5 h-5 text-garage-text-muted" />
            </div>
            <p className="text-2xl font-bold text-garage-text">
              {cost_analysis.cost_per_mile ? formatCurrency(cost_analysis.cost_per_mile) : 'N/A'}
            </p>
            {analytics.total_miles_driven && (
              <p className="text-xs text-garage-text-muted mt-1">
                {UnitFormatter.formatDistance(analytics.total_miles_driven, system, showBoth)} driven
              </p>
            )}
          </div>
        )}
      </div>

      {/* Rolling Averages & Trends */}
      {(cost_analysis.rolling_avg_3m || cost_analysis.rolling_avg_6m || cost_analysis.rolling_avg_12m) && (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-6 mb-8">
          <div className="flex items-center gap-2 mb-4">
            <TrendingUp className="w-5 h-5 text-garage-text-muted" />
            <h2 className="text-xl font-bold text-garage-text">Spending Trends</h2>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {cost_analysis.rolling_avg_3m && (
              <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
                <h3 className="text-sm font-medium text-garage-text-muted mb-2">
                  3-Month Rolling Average
                </h3>
                <p className="text-2xl font-bold text-garage-text">
                  {formatCurrency(cost_analysis.rolling_avg_3m)}
                </p>
                <p className="text-xs text-garage-text-muted mt-1">
                  Recent short-term trend
                </p>
              </div>
            )}

            {cost_analysis.rolling_avg_6m && (
              <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
                <h3 className="text-sm font-medium text-garage-text-muted mb-2">
                  6-Month Rolling Average
                </h3>
                <p className="text-2xl font-bold text-garage-text">
                  {formatCurrency(cost_analysis.rolling_avg_6m)}
                </p>
                <p className="text-xs text-garage-text-muted mt-1">
                  Smoothed medium-term trend
                </p>
              </div>
            )}

            {cost_analysis.rolling_avg_12m && (
              <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
                <h3 className="text-sm font-medium text-garage-text-muted mb-2">
                  12-Month Rolling Average
                </h3>
                <p className="text-2xl font-bold text-garage-text">
                  {formatCurrency(cost_analysis.rolling_avg_12m)}
                </p>
                <p className="text-xs text-garage-text-muted mt-1">
                  Annual trend analysis
                </p>
              </div>
            )}
          </div>

          <div className="mt-4 p-4 bg-garage-bg border border-garage-border rounded-lg">
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2">
                {cost_analysis.trend_direction === 'increasing' && (
                  <>
                    <TrendingUp className="w-5 h-5 text-danger" />
                    <span className="font-medium text-danger">Increasing Trend</span>
                  </>
                )}
                {cost_analysis.trend_direction === 'decreasing' && (
                  <>
                    <TrendingDown className="w-5 h-5 text-success" />
                    <span className="font-medium text-success">Decreasing Trend</span>
                  </>
                )}
                {cost_analysis.trend_direction === 'stable' && (
                  <>
                    <Minus className="w-5 h-5 text-garage-text-muted" />
                    <span className="font-medium text-garage-text-muted">Stable Spending</span>
                  </>
                )}
              </div>
              <p className="text-sm text-garage-text-muted">
                {cost_analysis.trend_direction === 'increasing' && 'Your costs are trending upward over time'}
                {cost_analysis.trend_direction === 'decreasing' && 'Your costs are trending downward over time'}
                {cost_analysis.trend_direction === 'stable' && 'Your spending pattern is relatively consistent'}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Trend Line with Rolling Averages Overlay */}
      {cost_analysis.monthly_breakdown.length > 0 && (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-6 mb-8">
          <div className="flex items-center gap-2 mb-4">
            <LineChart className="w-5 h-5 text-garage-text-muted" />
            <h2 className="text-xl font-bold text-garage-text">Cost Trends with Rolling Averages</h2>
          </div>

          <div className="bg-garage-bg rounded-lg p-4">
            <ResponsiveContainer width="100%" height={350}>
              <RechartsLineChart
                data={cost_analysis.monthly_breakdown.slice(-12).map((month, idx, arr) => {
                  // Calculate 3-month rolling average
                  const start3m = Math.max(0, idx - 2)
                  const slice3m = arr.slice(start3m, idx + 1)
                  const avg3m = slice3m.length > 0
                    ? slice3m.reduce((sum, m) => sum + parseFloat(m.total_cost), 0) / slice3m.length
                    : null

                  // Calculate 6-month rolling average
                  const start6m = Math.max(0, idx - 5)
                  const slice6m = arr.slice(start6m, idx + 1)
                  const avg6m = slice6m.length > 0
                    ? slice6m.reduce((sum, m) => sum + parseFloat(m.total_cost), 0) / slice6m.length
                    : null

                  return {
                    month: `${month.month_name.slice(0, 3)} ${month.year}`,
                    actualCost: parseFloat(month.total_cost),
                    rollingAvg3m: avg3m,
                    rollingAvg6m: avg6m,
                  }
                })}
                margin={{ top: 5, right: 20, left: 10, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                <XAxis
                  dataKey="month"
                  stroke="#9E9E9E"
                  style={{ fontSize: '12px' }}
                  angle={-45}
                  textAnchor="end"
                  height={80}
                />
                <YAxis
                  stroke="#9E9E9E"
                  style={{ fontSize: '12px' }}
                  label={{ value: 'Cost ($)', angle: -90, position: 'insideLeft', fill: '#9E9E9E' }}
                />
                <Tooltip
                  cursor={false}
                  wrapperStyle={{ outline: 'none' }}
                  content={(tooltipProps: TooltipContentProps<number, string>) => {
                    const { active, payload, label } = tooltipProps
                    if (active && payload && payload.length) {
                      return (
                        <div style={{ backgroundColor: '#1a1f28', border: '1px solid #3a4050', borderRadius: '8px', padding: '12px', color: '#e4e6eb' }}>
                          <p style={{ fontWeight: '600', marginBottom: '8px' }}>{label}</p>
                          {payload.map((entry: Payload<number, string>, index: number) => {
                            const entryName = entry.name?.toString() ?? entry.dataKey?.toString() ?? 'Value'
                            const rawValue = Array.isArray(entry.value) ? entry.value[0] : entry.value
                            const numericValue = typeof rawValue === 'number' ? rawValue : Number(rawValue ?? 0)
                            if (numericValue === 0 || numericValue === null) return null
                            return (
                              <div key={(entry.dataKey ?? index).toString()} style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: index > 0 ? '4px' : '0' }}>
                                <div style={{ width: '12px', height: '12px', borderRadius: '50%', backgroundColor: entry.color || '#3B82F6' }} />
                                <p style={{ fontSize: '14px', margin: 0 }}>
                                  {entryName}: {formatCurrency(numericValue)}
                                </p>
                              </div>
                            )
                          })}
                        </div>
                      )
                    }
                    return null
                  }}
                />
                <Legend
                  wrapperStyle={{ paddingTop: '10px', fontSize: '12px' }}
                />
                <Line
                  type="monotone"
                  dataKey="actualCost"
                  stroke="#3B82F6"
                  strokeWidth={3}
                  dot={{ fill: '#3B82F6', r: 5 }}
                  activeDot={{ r: 7 }}
                  name="Actual Monthly Cost"
                />
                <Line
                  type="monotone"
                  dataKey="rollingAvg3m"
                  stroke="#10B981"
                  strokeWidth={2}
                  strokeDasharray="5 5"
                  dot={false}
                  name="3-Month Rolling Avg"
                />
                <Line
                  type="monotone"
                  dataKey="rollingAvg6m"
                  stroke="#F59E0B"
                  strokeWidth={2}
                  strokeDasharray="3 3"
                  dot={false}
                  name="6-Month Rolling Avg"
                />
              </RechartsLineChart>
            </ResponsiveContainer>
          </div>

          <div className="mt-4 p-4 bg-garage-bg rounded-lg">
            <h3 className="text-sm font-semibold text-garage-text mb-2">Chart Legend</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm text-garage-text-muted">
              <div className="flex items-center gap-2">
                <div className="w-4 h-0.5 bg-primary"></div>
                <span>Actual monthly cost (solid blue)</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-4 h-0.5 bg-success border-dashed"></div>
                <span>3-month average (dashed green)</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-4 h-0.5 bg-warning border-dashed"></div>
                <span>6-month average (dashed orange)</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Maintenance Predictions */}
      {predictions.length > 0 && (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-6 mb-8">
          <div className="flex items-center gap-2 mb-4">
            <Calendar className="w-5 h-5 text-garage-text-muted" />
            <h2 className="text-xl font-bold text-garage-text">Maintenance Predictions</h2>
          </div>
          <div className="space-y-3">
            {predictions.slice(0, 5).map((prediction, idx) => (
              <div
                key={idx}
                className="flex items-center justify-between p-4 bg-garage-bg border border-garage-border rounded-lg"
              >
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-2">
                    <h3 className="font-semibold text-garage-text text-lg">{prediction.service_type}</h3>
                    {getConfidenceBadge(prediction.confidence)}
                    {prediction.has_manual_reminder && (
                      <span className="px-2 py-1 text-xs rounded bg-purple-100 dark:bg-purple-900 text-purple-800 dark:text-purple-200 border border-purple-300 dark:border-purple-700">
                        REMINDER SET
                      </span>
                    )}
                  </div>
                  <div className="space-y-2">
                    {/* AI Prediction */}
                    <div className="flex items-center gap-4 text-sm">
                      <span className="font-medium text-blue-600 dark:text-blue-400">AI predicts:</span>
                      {prediction.predicted_date && (
                        <span className="text-garage-text-muted">{formatDate(prediction.predicted_date)}</span>
                      )}
                      {prediction.predicted_mileage && (
                        <span className="text-garage-text-muted">@ {UnitFormatter.formatDistance(prediction.predicted_mileage, system, false)}</span>
                      )}
                    </div>
                    {/* Manual Reminder if exists */}
                    {prediction.has_manual_reminder && (
                      <div className="flex items-center gap-4 text-sm">
                        <span className="font-medium text-purple-600 dark:text-purple-400">You set:</span>
                        {prediction.manual_reminder_date && (
                          <span className="text-garage-text-muted">{formatDate(prediction.manual_reminder_date)}</span>
                        )}
                        {prediction.manual_reminder_mileage && (
                          <span className="text-garage-text-muted">@ {UnitFormatter.formatDistance(prediction.manual_reminder_mileage, system, false)}</span>
                        )}
                      </div>
                    )}
                  </div>
                </div>
                <div className="text-right">
                  {prediction.days_until_due !== null && (
                    <p className={`text-sm font-medium ${
                      prediction.days_until_due < 30 ? 'text-danger' :
                      prediction.days_until_due < 60 ? 'text-warning' :
                      'text-garage-text-muted'
                    }`}>
                      {prediction.days_until_due < 0 ? 'Overdue' :
                       prediction.days_until_due === 0 ? 'Due today' :
                       `${prediction.days_until_due} days`}
                    </p>
                  )}
                  {prediction.miles_until_due !== null && (
                    <p className="text-xs text-garage-text-muted mt-1">
                      {prediction.miles_until_due < 0 ? 'Past mileage' : UnitFormatter.formatDistance(prediction.miles_until_due, system, false)}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Cost Breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-8">
        {/* Service Type Breakdown */}
        <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
          <div className="flex items-center gap-2 mb-4">
            <PieChart className="w-5 h-5 text-garage-text-muted" />
            <h2 className="text-xl font-bold text-garage-text">Cost by Service Type</h2>
          </div>

          {/* Pie Chart */}
          <div className="mb-6">
            <ResponsiveContainer width="100%" height={300}>
              <RechartsPieChart>
                <Pie
                  data={cost_analysis.service_type_breakdown.slice(0, 6).map(item => ({
                    name: item.service_type,
                    value: parseFloat(item.total_cost),
                  }))}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={(props: PieLabelRenderProps) => {
                    const { name, percent } = props
                    if (typeof percent !== 'number') {
                      return name?.toString() ?? ''
                    }
                    const labelName = name?.toString() ?? 'Other'
                    return `${labelName} ${(percent * 100).toFixed(0)}%`
                  }}
                  outerRadius={100}
                  fill="#8884d8"
                  dataKey="value"
                >
                  {cost_analysis.service_type_breakdown.slice(0, 6).map((_item, index) => {
                    const COLORS = ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899']
                    return <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  })}
                </Pie>
                <Tooltip
                  cursor={false}
                  wrapperStyle={{ outline: 'none' }}
                  content={(tooltipProps: TooltipContentProps<number, string>) => {
                    const { active, payload } = tooltipProps
                    if (active && payload && payload.length) {
                      const dataPoint = payload[0]
                      const dataName = dataPoint.name?.toString() ?? 'Total'
                      const rawValue = Array.isArray(dataPoint.value) ? dataPoint.value[0] : dataPoint.value
                      const numericValue = typeof rawValue === 'number' ? rawValue : Number(rawValue ?? 0)

                      return (
                        <div style={{ backgroundColor: '#1a1f28', border: '1px solid #3a4050', borderRadius: '8px', padding: '12px', color: '#e4e6eb' }}>
                          <p style={{ fontWeight: '600', marginBottom: '4px' }}>{dataName}</p>
                          <p style={{ fontSize: '14px', color: '#9ca3af' }}>{formatCurrency(numericValue)}</p>
                        </div>
                      )
                    }
                    return null
                  }}
                />
              </RechartsPieChart>
            </ResponsiveContainer>
          </div>

          {/* List View */}
          <div className="space-y-3">
            {cost_analysis.service_type_breakdown.slice(0, 8).map((item, idx) => (
              <div key={idx} className="flex items-center justify-between">
                <div className="flex-1">
                  <p className="font-medium text-garage-text">{item.service_type}</p>
                  <p className="text-xs text-garage-text-muted">
                    {item.count} service{item.count !== 1 ? 's' : ''} • Avg: {formatCurrency(item.average_cost)}
                  </p>
                </div>
                <p className="font-bold text-garage-text">{formatCurrency(item.total_cost)}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Monthly Cost Trend */}
        <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
          <div className="flex items-center gap-2 mb-4">
            <BarChart3 className="w-5 h-5 text-garage-text-muted" />
            <h2 className="text-xl font-bold text-garage-text">Monthly Cost Trend</h2>
          </div>

          {/* Bar Chart */}
          <div className="mb-6">
            <ResponsiveContainer width="100%" height={300}>
              <RechartsBarChart
                data={cost_analysis.monthly_breakdown.slice(-12).map(month => ({
                  month: `${month.month_name.slice(0, 3)} ${month.year}`,
                  Service: parseFloat(month.total_service_cost),
                  Fuel: parseFloat(month.total_fuel_cost),
                  ...(hasPropane ? { 'Spot Rental': parseFloat(month.total_spot_rental_cost) } : {})
                }))}
                margin={{ top: 5, right: 20, left: 10, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                <XAxis
                  dataKey="month"
                  stroke="#9E9E9E"
                  style={{ fontSize: '12px' }}
                  angle={-45}
                  textAnchor="end"
                  height={80}
                />
                <YAxis
                  stroke="#9E9E9E"
                  style={{ fontSize: '12px' }}
                  label={{ value: 'Cost ($)', angle: -90, position: 'insideLeft', fill: '#9E9E9E' }}
                />
                <Tooltip
                  cursor={false}
                  wrapperStyle={{ outline: 'none' }}
                  content={(tooltipProps: TooltipContentProps<number, string>) => {
                    const { active, payload, label } = tooltipProps
                    if (active && payload && payload.length) {
                      return (
                        <div style={{ backgroundColor: '#1a1f28', border: '1px solid #3a4050', borderRadius: '8px', padding: '12px', color: '#e4e6eb' }}>
                          <p style={{ fontWeight: '600', marginBottom: '8px' }}>{label}</p>
                          {payload.map((entry: Payload<number, string>, index: number) => {
                            const entryName = entry.name?.toString() ?? entry.dataKey?.toString() ?? 'Value'
                            const rawValue = Array.isArray(entry.value) ? entry.value[0] : entry.value
                            const numericValue = typeof rawValue === 'number' ? rawValue : Number(rawValue ?? 0)
                            return (
                              <div key={(entry.dataKey ?? index).toString()} style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: index > 0 ? '4px' : '0' }}>
                                <div style={{ width: '12px', height: '12px', borderRadius: '50%', backgroundColor: entry.color || '#3B82F6' }} />
                                <p style={{ fontSize: '14px', margin: 0 }}>
                                  {entryName}: {formatCurrency(numericValue)}
                                </p>
                              </div>
                            )
                          })}
                        </div>
                      )
                    }
                    return null
                  }}
                />
                <Legend
                  wrapperStyle={{ paddingTop: '10px', fontSize: '12px' }}
                />
                <Bar dataKey="Service" fill="#3B82F6" stackId="a" />
                <Bar dataKey="Fuel" fill="#10B981" stackId="a" />
                {hasPropane && <Bar dataKey="Spot Rental" fill="#F59E0B" stackId="a" />}
              </RechartsBarChart>
            </ResponsiveContainer>
          </div>

          {/* List View */}
          <div className="space-y-3">
            {cost_analysis.monthly_breakdown.slice(-6).reverse().map((month, idx) => (
              <div key={idx} className="flex items-center justify-between">
                <div className="flex-1">
                  <p className="font-medium text-garage-text">
                    {month.month_name} {month.year}
                  </p>
                  <p className="text-xs text-garage-text-muted">
                    Service: {formatCurrency(month.total_service_cost)} • Fuel: {formatCurrency(month.total_fuel_cost)}
                    {parseFloat(month.total_spot_rental_cost) > 0 && ` • Spot Rental: ${formatCurrency(month.total_spot_rental_cost)}`}
                  </p>
                </div>
                <p className="font-bold text-garage-text">{formatCurrency(month.total_cost)}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Fuel Economy Details */}
      {isMotorized && fuel_economy.data_points.length > 0 && (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-6 mb-8">
          <div className="flex items-center gap-2 mb-4">
            <Fuel className="w-5 h-5 text-garage-text-muted" />
            <h2 className="text-xl font-bold text-garage-text">Fuel Economy Analysis</h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
            <div className="text-center p-4 bg-garage-bg rounded-lg">
              <p className="text-sm text-garage-text-muted mb-1">Average</p>
              <p className="text-2xl font-bold text-garage-text">{fuel_economy.average_mpg ? UnitFormatter.formatFuelEconomy(parseFloat(fuel_economy.average_mpg), system, showBoth) : 'N/A'}</p>
            </div>
            <div className="text-center p-4 bg-garage-bg rounded-lg">
              <p className="text-sm text-garage-text-muted mb-1">Best</p>
              <p className="text-2xl font-bold text-green-500">{fuel_economy.best_mpg ? UnitFormatter.formatFuelEconomy(parseFloat(fuel_economy.best_mpg), system, showBoth) : 'N/A'}</p>
            </div>
            <div className="text-center p-4 bg-garage-bg rounded-lg">
              <p className="text-sm text-garage-text-muted mb-1">Worst</p>
              <p className="text-2xl font-bold text-red-500">{fuel_economy.worst_mpg ? UnitFormatter.formatFuelEconomy(parseFloat(fuel_economy.worst_mpg), system, showBoth) : 'N/A'}</p>
            </div>
            <div className="text-center p-4 bg-garage-bg rounded-lg">
              <p className="text-sm text-garage-text-muted mb-1">Latest Fill-Up</p>
              <p className="text-2xl font-bold text-primary">{fuel_economy.recent_mpg ? UnitFormatter.formatFuelEconomy(parseFloat(fuel_economy.recent_mpg), system, showBoth) : 'N/A'}</p>
            </div>
          </div>

          {/* Fuel Economy Trend Chart */}
          <div className="mb-6 bg-garage-bg rounded-lg p-4">
            <h3 className="text-sm font-medium text-garage-text-muted mb-4">Fuel Economy Trend Over Time</h3>
            <ResponsiveContainer width="100%" height={300}>
              <RechartsLineChart
                data={fuel_economy.data_points.map(point => ({
                  date: new Date(point.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
                  mpg: parseFloat(point.mpg),
                  mileage: point.mileage,
                }))}
                margin={{ top: 5, right: 20, left: 10, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                <XAxis
                  dataKey="date"
                  stroke="#9E9E9E"
                  style={{ fontSize: '12px' }}
                />
                <YAxis
                  stroke="#9E9E9E"
                  style={{ fontSize: '12px' }}
                  label={{ value: UnitFormatter.getFuelEconomyUnit(system), angle: -90, position: 'insideLeft', fill: '#9E9E9E' }}
                />
                <Tooltip
                  cursor={false}
                  wrapperStyle={{ outline: 'none' }}
                  content={({ active, payload, label }) => {
                    if (active && payload && payload.length) {
                      return (
                        <div style={{ backgroundColor: '#1a1f28', border: '1px solid #3a4050', borderRadius: '8px', padding: '12px', color: '#e4e6eb' }}>
                          <p style={{ fontWeight: '600', marginBottom: '8px' }}>{label}</p>
                          <p style={{ fontSize: '14px', color: '#9ca3af' }}>
                            {UnitFormatter.formatFuelEconomy(payload[0].value as number, system, showBoth)}
                          </p>
                          {payload[0].payload.mileage && (
                            <p style={{ fontSize: '12px', color: '#9ca3af', marginTop: '4px' }}>
                              {UnitFormatter.formatDistance(payload[0].payload.mileage, system, false)}
                            </p>
                          )}
                        </div>
                      );
                    }
                    return null;
                  }}
                />
                <Legend
                  wrapperStyle={{ paddingTop: '10px', fontSize: '12px', color: '#9E9E9E' }}
                />
                <Line
                  type="monotone"
                  dataKey="mpg"
                  stroke="#3B82F6"
                  strokeWidth={2}
                  dot={{ fill: '#3B82F6', r: 4 }}
                  activeDot={{ r: 6 }}
                  name="Miles Per Gallon"
                />
              </RechartsLineChart>
            </ResponsiveContainer>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-garage-border">
                  <th className="text-left py-2 px-4 text-sm font-medium text-garage-text-muted">Date</th>
                  <th className="text-right py-2 px-4 text-sm font-medium text-garage-text-muted">Fuel Economy</th>
                  <th className="text-right py-2 px-4 text-sm font-medium text-garage-text-muted">Mileage ({UnitFormatter.getDistanceUnit(system)})</th>
                  <th className="text-right py-2 px-4 text-sm font-medium text-garage-text-muted">Volume ({UnitFormatter.getVolumeUnit(system)})</th>
                  <th className="text-right py-2 px-4 text-sm font-medium text-garage-text-muted">Cost</th>
                </tr>
              </thead>
              <tbody>
                {fuel_economy.data_points.slice(-10).reverse().map((point, idx) => (
                  <tr key={idx} className="border-b border-garage-border/50">
                    <td className="py-2 px-4 text-sm text-garage-text">{formatDate(point.date)}</td>
                    <td className="py-2 px-4 text-sm text-garage-text text-right font-medium">{UnitFormatter.formatFuelEconomy(parseFloat(point.mpg), system, showBoth)}</td>
                    <td className="py-2 px-4 text-sm text-garage-text text-right">{UnitFormatter.formatDistance(point.mileage, system, false)}</td>
                    <td className="py-2 px-4 text-sm text-garage-text text-right">{UnitFormatter.formatVolume(parseFloat(point.gallons), system, false)}</td>
                    <td className="py-2 px-4 text-sm text-garage-text text-right">{formatCurrency(point.cost)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Propane Analysis for Fifth Wheels and RVs */}
      {hasPropane && analytics.propane_analysis && analytics.propane_analysis.record_count > 0 && (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-6 mb-8">
          <div className="flex items-center gap-2 mb-4">
            <Fuel className="w-5 h-5 text-garage-text-muted" />
            <h2 className="text-xl font-bold text-garage-text">Propane Analysis</h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            <div className="text-center p-4 bg-garage-bg rounded-lg">
              <p className="text-sm text-garage-text-muted mb-1">Total Spent</p>
              <p className="text-2xl font-bold text-garage-text">
                {formatCurrency(analytics.propane_analysis.total_spent)}
              </p>
            </div>
            <div className="text-center p-4 bg-garage-bg rounded-lg">
              <p className="text-sm text-garage-text-muted mb-1">Total Gallons</p>
              <p className="text-2xl font-bold text-garage-text">
                {analytics.propane_analysis.total_gallons} gal
              </p>
            </div>
            <div className="text-center p-4 bg-garage-bg rounded-lg">
              <p className="text-sm text-garage-text-muted mb-1">Avg Price/Gallon</p>
              <p className="text-2xl font-bold text-primary">
                {analytics.propane_analysis.avg_price_per_gallon
                  ? formatCurrency(analytics.propane_analysis.avg_price_per_gallon)
                  : 'N/A'}
              </p>
            </div>
          </div>

          {/* Propane Cost Trend Chart */}
          {analytics.propane_analysis.monthly_trend && analytics.propane_analysis.monthly_trend.length > 0 && (
            <div className="mb-6 bg-garage-bg rounded-lg p-4">
              <h3 className="text-sm font-medium text-garage-text-muted mb-4">Monthly Propane Costs</h3>
              <ResponsiveContainer width="100%" height={300}>
                <RechartsBarChart data={analytics.propane_analysis.monthly_trend}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="month_name" stroke="#9CA3AF" />
                  <YAxis stroke="#9CA3AF" />
                  <Tooltip
                    cursor={false}
                    wrapperStyle={{ outline: 'none' }}
                    content={({ active, payload, label }) => {
                      if (active && payload && payload.length) {
                        return (
                          <div style={{ backgroundColor: '#1a1f28', border: '1px solid #3a4050', borderRadius: '8px', padding: '12px', color: '#e4e6eb' }}>
                            <p style={{ fontWeight: '600', marginBottom: '8px' }}>{label}</p>
                            {payload.map((entry, index) => (
                              <p key={index} style={{ fontSize: '14px', color: '#9ca3af' }}>
                                {entry.name}: {formatCurrency(entry.value as number)}
                              </p>
                            ))}
                          </div>
                        )
                      }
                      return null
                    }}
                  />
                  <Legend />
                  <Bar dataKey="total_cost" fill="#3B82F6" name="Total Cost" />
                </RechartsBarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}

      {/* Spot Rental Analysis for Fifth Wheels and RVs */}
      {hasPropane && analytics.spot_rental_analysis && analytics.spot_rental_analysis.billing_count > 0 && (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-6 mb-8">
          <div className="flex items-center gap-2 mb-4">
            <DollarSign className="w-5 h-5 text-garage-text-muted" />
            <h2 className="text-xl font-bold text-garage-text">Spot Rental Analysis</h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            <div className="text-center p-4 bg-garage-bg rounded-lg">
              <p className="text-sm text-garage-text-muted mb-1">Total Cost</p>
              <p className="text-2xl font-bold text-garage-text">
                {formatCurrency(analytics.spot_rental_analysis.total_cost)}
              </p>
            </div>
            <div className="text-center p-4 bg-garage-bg rounded-lg">
              <p className="text-sm text-garage-text-muted mb-1">Billing Periods</p>
              <p className="text-2xl font-bold text-garage-text">
                {analytics.spot_rental_analysis.billing_count}
              </p>
            </div>
            <div className="text-center p-4 bg-garage-bg rounded-lg">
              <p className="text-sm text-garage-text-muted mb-1">Monthly Average</p>
              <p className="text-2xl font-bold text-primary">
                {formatCurrency(analytics.spot_rental_analysis.monthly_average)}
              </p>
            </div>
          </div>

          {/* Spot Rental Cost Trend Chart */}
          {analytics.spot_rental_analysis.monthly_trend && analytics.spot_rental_analysis.monthly_trend.length > 0 && (
            <div className="bg-garage-bg rounded-lg p-4">
              <h3 className="text-sm font-medium text-garage-text-muted mb-4">Monthly Spot Rental Costs</h3>
              <ResponsiveContainer width="100%" height={300}>
                <RechartsBarChart data={analytics.spot_rental_analysis.monthly_trend}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="month_name" stroke="#9CA3AF" />
                  <YAxis stroke="#9CA3AF" />
                  <Tooltip
                    cursor={false}
                    wrapperStyle={{ outline: 'none' }}
                    content={({ active, payload, label }) => {
                      if (active && payload && payload.length) {
                        const labels: Record<string, string> = {
                          total_cost: 'Total',
                          monthly_rate: 'Monthly Rate',
                          electric: 'Electric',
                          water: 'Water',
                          waste: 'Waste',
                        }
                        return (
                          <div style={{ backgroundColor: '#1a1f28', border: '1px solid #3a4050', borderRadius: '8px', padding: '12px', color: '#e4e6eb' }}>
                            <p style={{ fontWeight: '600', marginBottom: '8px' }}>{label}</p>
                            {payload.map((entry, index) => (
                              <p key={index} style={{ fontSize: '14px', color: '#9ca3af' }}>
                                {labels[entry.dataKey as string] || entry.name}: {formatCurrency(entry.value as number)}
                              </p>
                            ))}
                          </div>
                        )
                      }
                      return null
                    }}
                  />
                  <Legend />
                  <Bar dataKey="monthly_rate" stackId="a" fill="#3B82F6" name="Monthly Rate" />
                  <Bar dataKey="electric" stackId="a" fill="#FBBF24" name="Electric" />
                  <Bar dataKey="water" stackId="a" fill="#10B981" name="Water" />
                  <Bar dataKey="waste" stackId="a" fill="#8B5CF6" name="Waste" />
                </RechartsBarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}

      {/* Service History Summary */}
      {service_history.length > 0 && (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-6 mb-8">
          <div className="flex items-center gap-2 mb-4">
            <Wrench className="w-5 h-5 text-garage-text-muted" />
            <h2 className="text-xl font-bold text-garage-text">Service History Summary</h2>
          </div>
          <div className="space-y-3">
            {service_history.slice(0, 10).map((item, idx) => (
              <div key={idx} className="flex items-start justify-between p-4 bg-garage-bg border border-garage-border rounded-lg">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="font-semibold text-garage-text">{item.service_type}</h3>
                    <span className="text-xs text-garage-text-muted">
                      {formatDate(item.date)}
                    </span>
                  </div>
                  {item.description && (
                    <p className="text-sm text-garage-text-muted mb-2">{item.description}</p>
                  )}
                  <div className="flex items-center gap-4 text-xs text-garage-text-muted">
                    {item.mileage && <span>{UnitFormatter.formatDistance(item.mileage, system, false)}</span>}
                    {item.vendor_name && <span>{item.vendor_name}</span>}
                    {item.days_since_last && (
                      <span className="text-primary">
                        {item.days_since_last} days since last {item.service_type.toLowerCase()}
                      </span>
                    )}
                    {item.miles_since_last && (
                      <span className="text-primary">
                        {UnitFormatter.formatDistance(item.miles_since_last, system, false)} since last
                      </span>
                    )}
                  </div>
                </div>
                {item.cost && (
                  <p className="font-bold text-garage-text ml-4">{formatCurrency(item.cost)}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Vendor Analysis */}
      {vendorAnalytics && vendorAnalytics.vendors.length > 0 && (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-6 mb-8">
          <div className="flex items-center gap-2 mb-4">
            <Wrench className="w-5 h-5 text-garage-text-muted" />
            <h2 className="text-xl font-bold text-garage-text">Vendor Analysis</h2>
          </div>

          {/* Summary cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
              <h3 className="text-sm font-medium text-garage-text-muted mb-2">Total Vendors</h3>
              <p className="text-2xl font-bold text-garage-text">{vendorAnalytics.total_vendors}</p>
            </div>
            {vendorAnalytics.most_used_vendor && (
              <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
                <h3 className="text-sm font-medium text-garage-text-muted mb-2">Most Used</h3>
                <p className="text-lg font-bold text-garage-text">{vendorAnalytics.most_used_vendor}</p>
              </div>
            )}
            {vendorAnalytics.highest_spending_vendor && (
              <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
                <h3 className="text-sm font-medium text-garage-text-muted mb-2">Highest Spending</h3>
                <p className="text-lg font-bold text-garage-text">{vendorAnalytics.highest_spending_vendor}</p>
              </div>
            )}
          </div>

          {/* Vendor Spending Bar Chart */}
          <div className="mb-6 bg-garage-bg rounded-lg p-4">
            <h3 className="text-sm font-medium text-garage-text-muted mb-4">Spending by Vendor</h3>
            <ResponsiveContainer width="100%" height={300}>
              <RechartsBarChart
                data={vendorAnalytics.vendors
                  .slice(0, 10)
                  .map(vendor => ({
                    vendor: vendor.vendor_name.length > 15
                      ? vendor.vendor_name.substring(0, 15) + '...'
                      : vendor.vendor_name,
                    spending: parseFloat(vendor.total_spent),
                    services: vendor.service_count,
                  }))}
                layout="vertical"
                margin={{ top: 5, right: 30, left: 120, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                <XAxis
                  type="number"
                  stroke="#9E9E9E"
                  style={{ fontSize: '12px' }}
                  label={{ value: 'Total Spent ($)', position: 'insideBottom', offset: -5, fill: '#9E9E9E' }}
                />
                <YAxis
                  type="category"
                  dataKey="vendor"
                  stroke="#9E9E9E"
                  style={{ fontSize: '12px' }}
                  width={120}
                />
                <Tooltip
                  cursor={false}
                  wrapperStyle={{ outline: 'none' }}
                  content={(tooltipProps: TooltipContentProps<number, string>) => {
                    const { active, payload } = tooltipProps
                    if (active && payload && payload.length) {
                      const data = payload[0].payload
                      return (
                        <div style={{ backgroundColor: '#1a1f28', border: '1px solid #3a4050', borderRadius: '8px', padding: '12px', color: '#e4e6eb' }}>
                          <p style={{ fontWeight: '600', marginBottom: '8px' }}>{data.vendor}</p>
                          <p style={{ fontSize: '14px', color: '#9ca3af', marginBottom: '4px' }}>
                            Total: {formatCurrency(data.spending)}
                          </p>
                          <p style={{ fontSize: '14px', color: '#9ca3af' }}>
                            Services: {data.services}
                          </p>
                        </div>
                      )
                    }
                    return null
                  }}
                />
                <Bar dataKey="spending" fill="#3B82F6" radius={[0, 4, 4, 0]} />
              </RechartsBarChart>
            </ResponsiveContainer>
          </div>

          {/* Vendor list */}
          <div className="space-y-3">
            {vendorAnalytics.vendors.map((vendor, idx) => (
              <div key={idx} className="flex items-center justify-between p-4 bg-garage-bg border border-garage-border rounded-lg">
                <div className="flex-1">
                  <h3 className="font-semibold text-garage-text mb-1">{vendor.vendor_name}</h3>
                  <div className="flex items-center gap-4 text-sm text-garage-text-muted">
                    <span>{vendor.service_count} services</span>
                    <span>Avg: {formatCurrency(vendor.average_cost)}</span>
                    {vendor.last_service_date && (
                      <span>Last visit: {formatDate(vendor.last_service_date)}</span>
                    )}
                  </div>
                  {vendor.service_types.length > 0 && (
                    <div className="flex flex-wrap gap-2 mt-2">
                      {vendor.service_types.map((type, i) => (
                        <span key={i} className="px-2 py-1 text-xs rounded-full bg-garage-surface border border-garage-border text-garage-text">
                          {type}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <p className="font-bold text-garage-text ml-4 text-lg">{formatCurrency(vendor.total_spent)}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Seasonal Analysis */}
      {seasonalAnalytics && seasonalAnalytics.seasons.length > 0 && (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-6 mb-8">
          <div className="flex items-center gap-2 mb-4">
            <Calendar className="w-5 h-5 text-garage-text-muted" />
            <h2 className="text-xl font-bold text-garage-text">Seasonal Spending Patterns</h2>
          </div>

          {/* Summary */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
              <h3 className="text-sm font-medium text-garage-text-muted mb-2">Annual Average</h3>
              <p className="text-2xl font-bold text-garage-text">{formatCurrency(seasonalAnalytics.annual_average)}</p>
            </div>
            {seasonalAnalytics.highest_cost_season && (
              <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
                <h3 className="text-sm font-medium text-garage-text-muted mb-2">Highest Cost Season</h3>
                <p className="text-lg font-bold text-danger">{seasonalAnalytics.highest_cost_season}</p>
              </div>
            )}
            {seasonalAnalytics.lowest_cost_season && (
              <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
                <h3 className="text-sm font-medium text-garage-text-muted mb-2">Lowest Cost Season</h3>
                <p className="text-lg font-bold text-success">{seasonalAnalytics.lowest_cost_season}</p>
              </div>
            )}
          </div>

          {/* Seasonal Pattern Radar Chart */}
          <div className="mb-6 bg-garage-bg rounded-lg p-4">
            <h3 className="text-sm font-medium text-garage-text-muted mb-4">Seasonal Cost Distribution</h3>
            <ResponsiveContainer width="100%" height={400}>
              <RadarChart
                data={seasonalAnalytics.seasons.map(season => ({
                  season: season.season,
                  cost: parseFloat(season.total_cost),
                  services: season.service_count,
                  avgCost: parseFloat(season.average_cost),
                }))}
                margin={{ top: 20, right: 80, bottom: 20, left: 80 }}
              >
                <PolarGrid stroke="#333" />
                <PolarAngleAxis
                  dataKey="season"
                  stroke="#9E9E9E"
                  style={{ fontSize: '14px', fontWeight: '600' }}
                />
                <PolarRadiusAxis
                  angle={90}
                  domain={[0, 'auto']}
                  stroke="#9E9E9E"
                  style={{ fontSize: '12px' }}
                />
                <Radar
                  name="Total Cost"
                  dataKey="cost"
                  stroke="#3B82F6"
                  fill="#3B82F6"
                  fillOpacity={0.5}
                  strokeWidth={2}
                />
                <Radar
                  name="Service Count"
                  dataKey="services"
                  stroke="#10B981"
                  fill="#10B981"
                  fillOpacity={0.3}
                  strokeWidth={2}
                />
                <Tooltip
                  wrapperStyle={{ outline: 'none' }}
                  content={(tooltipProps: TooltipContentProps<number, string>) => {
                    const { active, payload } = tooltipProps
                    if (active && payload && payload.length) {
                      const data = payload[0].payload
                      return (
                        <div style={{ backgroundColor: '#1a1f28', border: '1px solid #3a4050', borderRadius: '8px', padding: '12px', color: '#e4e6eb' }}>
                          <p style={{ fontWeight: '600', marginBottom: '8px' }}>{data.season}</p>
                          <p style={{ fontSize: '14px', color: '#9ca3af', marginBottom: '4px' }}>
                            Total Cost: {formatCurrency(data.cost)}
                          </p>
                          <p style={{ fontSize: '14px', color: '#9ca3af', marginBottom: '4px' }}>
                            Average Cost: {formatCurrency(data.avgCost)}
                          </p>
                          <p style={{ fontSize: '14px', color: '#9ca3af' }}>
                            Services: {data.services}
                          </p>
                        </div>
                      )
                    }
                    return null
                  }}
                />
                <Legend
                  wrapperStyle={{ paddingTop: '20px', fontSize: '12px' }}
                />
              </RadarChart>
            </ResponsiveContainer>
          </div>

          {/* Seasonal breakdown */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {seasonalAnalytics.seasons.map((season, idx) => (
              <div key={idx} className="p-4 bg-garage-bg border border-garage-border rounded-lg">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-lg font-semibold text-garage-text">{season.season}</h3>
                  <p className="text-xl font-bold text-garage-text">{formatCurrency(season.total_cost)}</p>
                </div>
                <div className="space-y-2 text-sm text-garage-text-muted">
                  <div className="flex justify-between">
                    <span>Average Cost:</span>
                    <span className="font-medium text-garage-text">{formatCurrency(season.average_cost)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Services:</span>
                    <span className="font-medium text-garage-text">{season.service_count}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>vs Annual Avg:</span>
                    <span className={`font-medium ${
                      parseFloat(season.variance_from_annual) > 0 ? 'text-danger' : 'text-success'
                    }`}>
                      {parseFloat(season.variance_from_annual) > 0 ? '+' : ''}
                      {season.variance_from_annual}%
                    </span>
                  </div>
                </div>
                {season.common_services.length > 0 && (
                  <div className="mt-3">
                    <p className="text-xs text-garage-text-muted mb-2">Common Services:</p>
                    <div className="flex flex-wrap gap-2">
                      {season.common_services.slice(0, 3).map((service, i) => (
                        <span key={i} className="px-2 py-1 text-xs rounded-full bg-garage-surface border border-garage-border text-garage-text">
                          {service}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Period Comparison */}
      <div className="bg-garage-surface border border-garage-border rounded-lg p-6 mb-8">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Calendar className="w-5 h-5 text-garage-text-muted" />
            <h2 className="text-xl font-bold text-garage-text">Period Comparison</h2>
          </div>
          <button
            onClick={() => setShowComparison(!showComparison)}
            className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-dark transition-colors"
          >
            {showComparison ? 'Hide' : 'Compare Periods'}
          </button>
        </div>

        {showComparison && (
          <div className="space-y-6">
            {/* Date Range Selectors */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Period 1 */}
              <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
                <h3 className="text-lg font-semibold text-garage-text mb-4">Period 1</h3>
                <div className="space-y-3">
                  <div>
                    <label className="block text-sm font-medium text-garage-text-muted mb-1">
                      Start Date
                    </label>
                    <input
                      type="date"
                      value={period1Start}
                      onChange={(e) => setPeriod1Start(e.target.value)}
                      className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-garage-text-muted mb-1">
                      End Date
                    </label>
                    <input
                      type="date"
                      value={period1End}
                      onChange={(e) => setPeriod1End(e.target.value)}
                      className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
                    />
                  </div>
                </div>
              </div>

              {/* Period 2 */}
              <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
                <h3 className="text-lg font-semibold text-garage-text mb-4">Period 2</h3>
                <div className="space-y-3">
                  <div>
                    <label className="block text-sm font-medium text-garage-text-muted mb-1">
                      Start Date
                    </label>
                    <input
                      type="date"
                      value={period2Start}
                      onChange={(e) => setPeriod2Start(e.target.value)}
                      className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-garage-text-muted mb-1">
                      End Date
                    </label>
                    <input
                      type="date"
                      value={period2End}
                      onChange={(e) => setPeriod2End(e.target.value)}
                      className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
                    />
                  </div>
                </div>
              </div>
            </div>

            {/* Compare Button */}
            <div className="text-center">
              <button
                onClick={handleCompare}
                disabled={comparisonLoading}
                className="px-6 py-3 bg-primary text-white rounded-lg hover:bg-primary-dark transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {comparisonLoading ? 'Comparing...' : 'Run Comparison'}
              </button>
            </div>

            {/* Comparison Results */}
            {comparisonData && (
              <div className="mt-6 space-y-6">
                {/* Summary Cards */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* Period 1 Summary */}
                  <div className="p-6 bg-garage-bg border-2 border-primary rounded-lg">
                    <h3 className="text-lg font-semibold text-garage-text mb-4">
                      {comparisonData.period1_label}
                    </h3>
                    <div className="space-y-3">
                      <div className="flex justify-between">
                        <span className="text-garage-text-muted">Total Cost:</span>
                        <span className="font-bold text-garage-text text-xl">
                          {formatCurrency(comparisonData.period1_total_cost)}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-garage-text-muted">Services:</span>
                        <span className="font-medium text-garage-text">
                          {comparisonData.period1_service_count}
                        </span>
                      </div>
                      {comparisonData.period1_avg_mpg && (
                        <div className="flex justify-between">
                          <span className="text-garage-text-muted">Avg Fuel Economy:</span>
                          <span className="font-medium text-garage-text">
                            {UnitFormatter.formatFuelEconomy(parseFloat(comparisonData.period1_avg_mpg), system, showBoth)}
                          </span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Period 2 Summary */}
                  <div className="p-6 bg-garage-bg border-2 border-success rounded-lg">
                    <h3 className="text-lg font-semibold text-garage-text mb-4">
                      {comparisonData.period2_label}
                    </h3>
                    <div className="space-y-3">
                      <div className="flex justify-between">
                        <span className="text-garage-text-muted">Total Cost:</span>
                        <span className="font-bold text-garage-text text-xl">
                          {formatCurrency(comparisonData.period2_total_cost)}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-garage-text-muted">Services:</span>
                        <span className="font-medium text-garage-text">
                          {comparisonData.period2_service_count}
                        </span>
                      </div>
                      {comparisonData.period2_avg_mpg && (
                        <div className="flex justify-between">
                          <span className="text-garage-text-muted">Avg Fuel Economy:</span>
                          <span className="font-medium text-garage-text">
                            {UnitFormatter.formatFuelEconomy(parseFloat(comparisonData.period2_avg_mpg), system, showBoth)}
                          </span>
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                {/* Change Summary */}
                <div className="p-6 bg-garage-bg border border-garage-border rounded-lg">
                  <h3 className="text-lg font-semibold text-garage-text mb-4">Overall Changes</h3>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="text-center p-4 bg-garage-surface rounded-lg">
                      <p className="text-sm text-garage-text-muted mb-1">Cost Change</p>
                      <p className={`text-2xl font-bold ${
                        parseFloat(comparisonData.cost_change_percent) > 0
                          ? 'text-danger'
                          : 'text-success'
                      }`}>
                        {parseFloat(comparisonData.cost_change_percent) > 0 ? '+' : ''}
                        {comparisonData.cost_change_percent}%
                      </p>
                      <p className="text-xs text-garage-text-muted mt-1">
                        {formatCurrency(comparisonData.cost_change_amount)}
                      </p>
                    </div>

                    <div className="text-center p-4 bg-garage-surface rounded-lg">
                      <p className="text-sm text-garage-text-muted mb-1">Service Count Change</p>
                      <p className={`text-2xl font-bold ${
                        comparisonData.service_count_change > 0
                          ? 'text-warning'
                          : 'text-garage-text'
                      }`}>
                        {comparisonData.service_count_change > 0 ? '+' : ''}
                        {comparisonData.service_count_change}
                      </p>
                    </div>

                    {comparisonData.mpg_change_percent && (
                      <div className="text-center p-4 bg-garage-surface rounded-lg">
                        <p className="text-sm text-garage-text-muted mb-1">Fuel Economy Change</p>
                        <p className={`text-2xl font-bold ${
                          parseFloat(comparisonData.mpg_change_percent) > 0
                            ? 'text-success'
                            : 'text-danger'
                        }`}>
                          {parseFloat(comparisonData.mpg_change_percent) > 0 ? '+' : ''}
                          {comparisonData.mpg_change_percent}%
                        </p>
                      </div>
                    )}
                  </div>
                </div>

                {/* Category Breakdown */}
                {comparisonData.category_changes.length > 0 && (
                  <div className="p-6 bg-garage-bg border border-garage-border rounded-lg">
                    <h3 className="text-lg font-semibold text-garage-text mb-4">
                      Cost Changes by Category
                    </h3>
                    <div className="space-y-3">
                      {comparisonData.category_changes.map((category, idx) => (
                        <div key={idx} className="flex items-center justify-between p-4 bg-garage-surface rounded-lg">
                          <div className="flex-1">
                            <h4 className="font-semibold text-garage-text mb-1">
                              {category.category}
                            </h4>
                            <div className="flex items-center gap-4 text-sm text-garage-text-muted">
                              <span>
                                Period 1: {formatCurrency(category.period1_value)}
                              </span>
                              <span>→</span>
                              <span>
                                Period 2: {formatCurrency(category.period2_value)}
                              </span>
                            </div>
                          </div>
                          <div className="text-right ml-4">
                            <p className={`text-lg font-bold ${
                              parseFloat(category.change_percent) > 0
                                ? 'text-danger'
                                : 'text-success'
                            }`}>
                              {parseFloat(category.change_percent) > 0 ? '+' : ''}
                              {category.change_percent}%
                            </p>
                            <p className="text-xs text-garage-text-muted">
                              {formatCurrency(category.change_amount)}
                            </p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Help Modal */}
      <AnalyticsHelpModal
        isOpen={showHelpModal}
        onClose={() => setShowHelpModal(false)}
      />
    </div>
  )
}
  const getAlertStyles = (severity: FuelAlertSeverity) => {
    switch (severity) {
      case 'critical':
        return 'bg-red-50 border-red-200 text-red-800'
      case 'warning':
        return 'bg-amber-50 border-amber-200 text-amber-800'
      default:
        return 'bg-blue-50 border-blue-200 text-blue-800'
    }
  }
