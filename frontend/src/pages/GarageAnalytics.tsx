import { useState, useEffect } from 'react'
import api from '../services/api'
import { Car, Wrench, Fuel, Shield, FileText, Download, HelpCircle, Droplets } from 'lucide-react'
import {
  ResponsiveContainer,
  PieChart as RechartsPieChart,
  Pie,
  Sector,
  Tooltip,
  BarChart as RechartsBarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Legend,
  Line,
} from 'recharts'
import type { PieLabelRenderProps, SectorProps } from 'recharts'
import type { GarageAnalytics, GarageMonthlyTrend } from '../types/analytics'
import GarageAnalyticsHelpModal from '../components/GarageAnalyticsHelpModal'
import { formatCurrencyZero as formatCurrency } from '../utils/formatUtils'

// Colors for pie chart categories (9 categories: Maintenance, Upgrades, Inspection, Collision, Detailing, Fuel, DEF, Insurance, Taxes)
const COLORS = ['#3B82F6', '#8B5CF6', '#F59E0B', '#EF4444', '#10B981', '#06B6D4', '#14B8A6', '#EC4899', '#6B7280']

export default function GarageAnalytics() {
  const [analytics, setAnalytics] = useState<GarageAnalytics | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [fromCache, setFromCache] = useState(false)
  const [showHelpModal, setShowHelpModal] = useState(false)

  const exportToCSV = () => {
    if (!analytics) return

    const rows: string[] = []

    // Header
    rows.push('MyGarage Garage Analytics Export')
    rows.push(`Generated: ${new Date().toLocaleString()}`)
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
    rows.push('Vehicle,Purchase Price,Maintenance,Upgrades,Inspection,Collision,Detailing,Fuel,DEF,Running Costs')
    analytics.cost_by_vehicle.forEach((vehicle) => {
      rows.push(
        `"${vehicle.name}",${vehicle.purchase_price},${vehicle.total_maintenance},${vehicle.total_upgrades},${vehicle.total_inspection},${vehicle.total_collision},${vehicle.total_detailing},${vehicle.total_fuel},${vehicle.total_def},${vehicle.total_cost}`
      )
    })
    rows.push('')

    // Monthly Trends
    if (analytics.monthly_trends.length > 0) {
      rows.push('Monthly Spending Trends')
      rows.push('Month,Maintenance,Fuel,DEF,Total')
      analytics.monthly_trends.forEach((trend) => {
        const total = (parseFloat(trend.maintenance) + parseFloat(trend.fuel) + parseFloat(trend.def_cost)).toFixed(2)
        rows.push(`${trend.month},${trend.maintenance},${trend.fuel},${trend.def_cost},${total}`)
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
      alert('Failed to export PDF. Please try again.')
    }
  }

  const calculateRollingAverage = (data: GarageMonthlyTrend[], period: number) => {
    return data.map((_, idx) => {
      if (idx < period - 1) return null
      const slice = data.slice(idx - period + 1, idx + 1)
      const sum = slice.reduce(
        (acc, item) => acc + parseFloat(item.maintenance) + parseFloat(item.fuel) + parseFloat(item.def_cost),
        0
      )
      return sum / period
    })
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
        const errorMessage = err instanceof Error ? err.message : 'An error occurred'
        setError(errorMessage)

        // If offline, try to load from cache
        if (!navigator.onLine) {
          const cached = localStorage.getItem(cacheKey)
          if (cached) {
            try {
              const parsed = JSON.parse(cached)
              setAnalytics(parsed.data)
              setFromCache(true)
              setError('Offline: showing cached analytics snapshot.')
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
  }, [])

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
        <div className="flex items-center justify-center py-16" role="status" aria-label="Loading analytics">
          <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
          <span className="sr-only">Loading garage analytics...</span>
        </div>
      </div>
    )
  }

  if (!analytics || analytics.vehicle_count === 0) {
    return (
      <div className="container mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold mb-2 text-garage-text">Garage Analytics</h1>
        <p className="text-garage-text-muted mb-8">
          Comprehensive cost analysis across all vehicles
        </p>

        <div className="bg-garage-surface rounded-lg border border-garage-border text-center py-16">
          <Car className="w-16 h-16 text-garage-text-muted mx-auto mb-4 opacity-50" />
          <h3 className="text-xl font-semibold mb-2 text-garage-text">No Vehicles Yet</h3>
          <p className="text-garage-text-muted mb-6">
            Add vehicles to your garage to start tracking garage-wide analytics
          </p>
        </div>
      </div>
    )
  }

  const { total_costs, cost_breakdown_by_category, cost_by_vehicle, monthly_trends } = analytics

  // Prepare chart data
  const pieData = cost_breakdown_by_category
    .map((item) => ({
      name: item.category,
      value: parseFloat(item.amount),
    }))
    .filter((item) => item.value > 0)

  const barData = cost_by_vehicle.slice(0, 10).map((vehicle) => ({
    name: vehicle.nickname,
    totalCost: parseFloat(vehicle.total_cost),
  }))

  // Pre-calculate rolling averages
  const rollingAvg3 = calculateRollingAverage(monthly_trends, 3)
  const rollingAvg6 = calculateRollingAverage(monthly_trends, 6)

  const trendData = monthly_trends.map((trend, idx) => ({
    month: trend.month,
    Maintenance: parseFloat(trend.maintenance),
    Fuel: parseFloat(trend.fuel),
    DEF: parseFloat(trend.def_cost),
    avg3: rollingAvg3[idx],
    avg6: rollingAvg6[idx],
  }))

  return (
    <div className="container mx-auto px-4 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold mb-2 text-garage-text">Garage Analytics</h1>
          <p className="text-garage-text-muted">
            Comprehensive cost analysis across {analytics.vehicle_count} vehicle
            {analytics.vehicle_count !== 1 ? 's' : ''}
          </p>
          {fromCache && error && (
            <p className="text-warning text-sm mt-1">{error}</p>
          )}
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
            onClick={exportToPDF}
            className="px-4 py-2 bg-garage-surface border border-garage-border text-garage-text rounded-lg hover:bg-garage-surface-light transition-colors flex items-center gap-2"
          >
            <Download className="w-4 h-4" />
            PDF
          </button>
        </div>
      </div>

      {/* Total Cost Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4 mb-8">
        <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium text-garage-text-muted">Garage Value</h3>
            <Car className="w-5 h-5 text-primary" />
          </div>
          <p className="text-2xl font-bold text-garage-text">
            {formatCurrency(total_costs.total_garage_value)}
          </p>
        </div>

        <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium text-garage-text-muted">Maintenance</h3>
            <Wrench className="w-5 h-5 text-primary" />
          </div>
          <p className="text-2xl font-bold text-garage-text">
            {formatCurrency(total_costs.total_maintenance)}
          </p>
        </div>

        <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium text-garage-text-muted">Fuel</h3>
            <Fuel className="w-5 h-5 text-success-500" />
          </div>
          <p className="text-2xl font-bold text-garage-text">
            {formatCurrency(total_costs.total_fuel)}
          </p>
        </div>

        {parseFloat(total_costs.total_def) > 0 && (
          <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-medium text-garage-text-muted">DEF</h3>
              <Droplets className="w-5 h-5 text-teal-500" />
            </div>
            <p className="text-2xl font-bold text-garage-text">
              {formatCurrency(total_costs.total_def)}
            </p>
          </div>
        )}

        <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium text-garage-text-muted">Insurance</h3>
            <Shield className="w-5 h-5 text-warning-500" />
          </div>
          <p className="text-2xl font-bold text-garage-text">
            {formatCurrency(total_costs.total_insurance)}
          </p>
        </div>

        <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium text-garage-text-muted">Taxes</h3>
            <FileText className="w-5 h-5 text-danger-500" />
          </div>
          <p className="text-2xl font-bold text-garage-text">
            {formatCurrency(total_costs.total_taxes)}
          </p>
        </div>
      </div>

      {/* Cost Breakdown Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        {/* Pie Chart - Cost by Category */}
        <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
          <h2 className="text-xl font-bold mb-4 text-garage-text">Cost by Category</h2>
          {pieData.length > 0 ? (
            <>
              <ResponsiveContainer width="100%" height={300}>
                <RechartsPieChart>
                  <Pie
                    data={pieData}
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
                    dataKey="value"
                    shape={(props: SectorProps & { index?: number }) => (
                      <Sector {...props} fill={COLORS[(props.index ?? 0) % COLORS.length]} />
                    )}
                  />
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
                              {formatCurrency(data.value)}
                            </p>
                          </div>
                        )
                      }
                      return null
                    }}
                  />
                </RechartsPieChart>
              </ResponsiveContainer>
              <div className="mt-4 space-y-2">
                {cost_breakdown_by_category.map((item, index) => (
                  <div key={index} className="flex items-center justify-between text-sm">
                    <div className="flex items-center gap-2">
                      <div
                        className="w-3 h-3 rounded-full"
                        style={{ backgroundColor: COLORS[index % COLORS.length] }}
                      />
                      <span className="text-garage-text">{item.category}</span>
                    </div>
                    <span className="text-garage-text-muted font-medium">
                      {formatCurrency(item.amount)}
                    </span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <p className="text-garage-text-muted text-center py-8">No cost data available</p>
          )}
        </div>

        {/* Bar Chart - Running Costs by Vehicle */}
        <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
          <h2 className="text-xl font-bold mb-4 text-garage-text">Running Costs by Vehicle</h2>
          {barData.length > 0 ? (
            <>
              <ResponsiveContainer width="100%" height={Math.max(150, barData.length * 50)}>
                <RechartsBarChart
                  data={barData}
                  layout="vertical"
                  margin={{ top: 5, right: 30, left: 20, bottom: 5 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#333" horizontal={false} />
                  <XAxis
                    type="number"
                    stroke="#9E9E9E"
                    style={{ fontSize: '12px' }}
                    tickFormatter={(value) => `$${value.toLocaleString()}`}
                  />
                  <YAxis
                    type="category"
                    dataKey="name"
                    stroke="#9E9E9E"
                    style={{ fontSize: '12px' }}
                    width={150}
                  />
                  <Tooltip
                    cursor={false}
                    wrapperStyle={{ outline: 'none' }}
                    content={({ active, payload }) => {
                      if (active && payload && payload.length) {
                        const data = payload[0]
                        return (
                          <div style={customTooltipStyle}>
                            <p style={{ fontWeight: '600', marginBottom: '4px' }}>
                              {data.payload.name}
                            </p>
                            <p style={{ fontSize: '14px', color: '#9ca3af' }}>
                              Running Costs: {formatCurrency(data.value)}
                            </p>
                          </div>
                        )
                      }
                      return null
                    }}
                  />
                  <Bar dataKey="totalCost" fill="#3B82F6" />
                </RechartsBarChart>
              </ResponsiveContainer>

              {/* Vehicle Cost Breakdown Table */}
              <div className="mt-6 overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-garage-border">
                      <th className="text-left py-2 px-3 text-sm font-medium text-garage-text-muted">
                        Vehicle
                      </th>
                      <th className="text-right py-2 px-3 text-sm font-medium text-garage-text-muted">
                        Maint.
                      </th>
                      <th className="text-right py-2 px-3 text-sm font-medium text-garage-text-muted">
                        Upgrades
                      </th>
                      <th className="text-right py-2 px-3 text-sm font-medium text-garage-text-muted">
                        Insp.
                      </th>
                      <th className="text-right py-2 px-3 text-sm font-medium text-garage-text-muted">
                        Collision
                      </th>
                      <th className="text-right py-2 px-3 text-sm font-medium text-garage-text-muted">
                        Detail.
                      </th>
                      <th className="text-right py-2 px-3 text-sm font-medium text-garage-text-muted">
                        Fuel
                      </th>
                      <th className="text-right py-2 px-3 text-sm font-medium text-garage-text-muted">
                        DEF
                      </th>
                      <th className="text-right py-2 px-3 text-sm font-medium text-garage-text-muted">
                        Total
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {cost_by_vehicle.map((vehicle, index) => (
                      <tr key={index} className="border-b border-garage-border/50 hover:bg-garage-surface-light transition-colors">
                        <td className="py-2 px-3 text-sm text-garage-text">{vehicle.nickname}</td>
                        <td className="py-2 px-3 text-sm text-garage-text text-right">
                          {formatCurrency(vehicle.total_maintenance)}
                        </td>
                        <td className="py-2 px-3 text-sm text-garage-text text-right">
                          {formatCurrency(vehicle.total_upgrades)}
                        </td>
                        <td className="py-2 px-3 text-sm text-garage-text text-right">
                          {formatCurrency(vehicle.total_inspection)}
                        </td>
                        <td className="py-2 px-3 text-sm text-garage-text text-right">
                          {formatCurrency(vehicle.total_collision)}
                        </td>
                        <td className="py-2 px-3 text-sm text-garage-text text-right">
                          {formatCurrency(vehicle.total_detailing)}
                        </td>
                        <td className="py-2 px-3 text-sm text-garage-text text-right">
                          {formatCurrency(vehicle.total_fuel)}
                        </td>
                        <td className="py-2 px-3 text-sm text-garage-text text-right">
                          {formatCurrency(vehicle.total_def)}
                        </td>
                        <td className="py-2 px-3 text-sm text-garage-text text-right font-semibold">
                          {formatCurrency(vehicle.total_cost)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <p className="text-garage-text-muted text-center py-8">No vehicle data available</p>
          )}
        </div>
      </div>

      {/* Monthly Spending Trend */}
      {trendData.length > 0 && (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-6 mb-8">
          <h2 className="text-xl font-bold mb-4 text-garage-text">Monthly Spending Trend</h2>
          <ResponsiveContainer width="100%" height={300}>
            <RechartsBarChart data={trendData} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
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
                content={({ active, payload }) => {
                  if (active && payload && payload.length) {
                    return (
                      <div style={customTooltipStyle}>
                        <p style={{ fontWeight: '600', marginBottom: '8px' }}>
                          {payload[0].payload.month}
                        </p>
                        {payload.map((entry: { name: string; value: number }, index: number) => (
                          <p
                            key={index}
                            style={{ fontSize: '14px', color: '#9ca3af', marginBottom: '4px' }}
                          >
                            {entry.name}: {formatCurrency(entry.value)}
                          </p>
                        ))}
                      </div>
                    )
                  }
                  return null
                }}
              />
              <Legend wrapperStyle={{ paddingTop: '10px', fontSize: '12px' }} />
              <Bar dataKey="Maintenance" fill="#3B82F6" stackId="a" />
              <Bar dataKey="Fuel" fill="#10B981" stackId="a" />
              <Bar dataKey="DEF" fill="#14B8A6" stackId="a" />

              {/* Rolling average trend lines - data from trendData via chart's data prop */}
              {trendData.length >= 3 && (
                <Line
                  type="monotone"
                  dataKey="avg3"
                  stroke="#10B981"
                  strokeWidth={2}
                  strokeDasharray="5 5"
                  dot={false}
                  name="3-Month Avg"
                  connectNulls={false}
                />
              )}
              {trendData.length >= 6 && (
                <Line
                  type="monotone"
                  dataKey="avg6"
                  stroke="#8B5CF6"
                  strokeWidth={2}
                  strokeDasharray="5 5"
                  dot={false}
                  name="6-Month Avg"
                  connectNulls={false}
                />
              )}
            </RechartsBarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Help Modal */}
      <GarageAnalyticsHelpModal isOpen={showHelpModal} onClose={() => setShowHelpModal(false)} />
    </div>
  )
}
