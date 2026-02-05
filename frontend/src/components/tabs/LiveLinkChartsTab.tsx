/**
 * LiveLink Charts Tab - Historical telemetry charts
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import { toast } from 'sonner'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import { BarChart3, RefreshCw, Download, Calendar } from 'lucide-react'
import { livelinkService } from '@/services/livelinkService'
import type { TelemetryQueryResponse, LiveLinkParameter } from '@/types/livelink'
// Unit preference hook available for future unit conversion
// import { useUnitPreference } from '@/hooks/useUnitPreference'

interface LiveLinkChartsTabProps {
  vin: string
}

type TimeRange = '1h' | '6h' | '24h' | '7d' | '30d'

const TIME_RANGES: { value: TimeRange; label: string }[] = [
  { value: '1h', label: '1 Hour' },
  { value: '6h', label: '6 Hours' },
  { value: '24h', label: '24 Hours' },
  { value: '7d', label: '7 Days' },
  { value: '30d', label: '30 Days' },
]

// Chart colors
const CHART_COLORS = [
  '#3b82f6', // blue
  '#10b981', // green
  '#f59e0b', // amber
  '#ef4444', // red
  '#8b5cf6', // purple
  '#ec4899', // pink
  '#06b6d4', // cyan
  '#84cc16', // lime
]

export default function LiveLinkChartsTab({ vin }: LiveLinkChartsTabProps) {
  const [loading, setLoading] = useState(true)
  const [parameters, setParameters] = useState<LiveLinkParameter[]>([])
  const [selectedParams, setSelectedParams] = useState<string[]>([])
  const [timeRange, setTimeRange] = useState<TimeRange>('24h')
  const [telemetry, setTelemetry] = useState<TelemetryQueryResponse | null>(null)
  // Unit conversion can be added here if needed
  // const { system: unitSystem } = useUnitPreference()

  // Fetch available parameters
  useEffect(() => {
    const fetchParameters = async () => {
      try {
        const data = await livelinkService.getParameters()
        // Show all parameters except archive_only (charts should allow any parameter)
        const chartableParams = data.parameters.filter((p) => !p.archive_only)
        setParameters(chartableParams)
        // Default select first 3 parameters
        if (chartableParams.length > 0) {
          setSelectedParams(chartableParams.slice(0, 3).map((p) => p.param_key))
        }
      } catch (err) {
        console.error('Failed to fetch parameters:', err)
      } finally {
        setLoading(false)
      }
    }
    fetchParameters()
  }, [])

  // Calculate time range
  const getTimeRange = useCallback(() => {
    const now = new Date()
    const start = new Date()

    switch (timeRange) {
      case '1h':
        start.setHours(start.getHours() - 1)
        break
      case '6h':
        start.setHours(start.getHours() - 6)
        break
      case '24h':
        start.setDate(start.getDate() - 1)
        break
      case '7d':
        start.setDate(start.getDate() - 7)
        break
      case '30d':
        start.setDate(start.getDate() - 30)
        break
    }

    return {
      start: start.toISOString(),
      end: now.toISOString(),
    }
  }, [timeRange])

  // Fetch telemetry data
  const fetchTelemetry = useCallback(async () => {
    if (selectedParams.length === 0) {
      setTelemetry(null)
      return
    }

    setLoading(true)
    try {
      const { start, end } = getTimeRange()
      // Downsample for longer time ranges
      const intervalSeconds = timeRange === '30d' ? 3600 : timeRange === '7d' ? 900 : undefined
      const data = await livelinkService.getTelemetry(
        vin,
        start,
        end,
        selectedParams,
        intervalSeconds
      )
      setTelemetry(data)
    } catch (err) {
      console.error('Failed to fetch telemetry:', err)
      toast.error('Failed to load telemetry data')
    } finally {
      setLoading(false)
    }
  }, [vin, selectedParams, timeRange, getTimeRange])

  useEffect(() => {
    fetchTelemetry()
  }, [fetchTelemetry])

  // Transform telemetry data for Recharts
  const chartData = useMemo(() => {
    if (!telemetry || telemetry.series.length === 0) return []

    // Create a map of timestamp -> values
    const dataMap = new Map<string, Record<string, number>>()

    telemetry.series.forEach((series) => {
      series.data.forEach((point) => {
        const key = point.timestamp
        const existing = dataMap.get(key) || { timestamp: new Date(point.timestamp).getTime() }
        existing[series.param_key] = point.value
        dataMap.set(key, existing)
      })
    })

    // Convert to array and sort by timestamp
    return Array.from(dataMap.values()).sort((a, b) => a.timestamp - b.timestamp)
  }, [telemetry])

  const toggleParam = (paramKey: string) => {
    setSelectedParams((prev) =>
      prev.includes(paramKey) ? prev.filter((p) => p !== paramKey) : [...prev, paramKey]
    )
  }

  const handleExport = () => {
    if (!telemetry) return
    const { start, end } = getTimeRange()
    const url = livelinkService.getTelemetryExportUrl(vin, start, end, 'csv', selectedParams)
    window.open(url, '_blank')
  }

  const formatXAxis = (timestamp: number) => {
    const date = new Date(timestamp)
    if (timeRange === '1h' || timeRange === '6h') {
      return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
    }
    if (timeRange === '24h') {
      return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
    }
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  }

  if (loading && parameters.length === 0) {
    return (
      <div className="flex items-center justify-center py-12">
        <RefreshCw className="w-8 h-8 text-primary animate-spin" />
      </div>
    )
  }

  if (parameters.length === 0) {
    return (
      <div className="bg-garage-surface rounded-lg border border-garage-border p-8 text-center">
        <BarChart3 className="w-12 h-12 mx-auto mb-3 text-garage-text-muted opacity-50" />
        <p className="text-garage-text">No telemetry parameters available</p>
        <p className="text-sm text-garage-text-muted mt-2">
          Parameters will appear here once your WiCAN device starts sending data
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Controls */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        {/* Time Range Selector */}
        <div className="flex items-center gap-2">
          <Calendar className="w-5 h-5 text-garage-text-muted" />
          <div className="flex gap-1">
            {TIME_RANGES.map((range) => (
              <button
                key={range.value}
                onClick={() => setTimeRange(range.value)}
                className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                  timeRange === range.value
                    ? 'bg-primary text-white'
                    : 'bg-garage-surface text-garage-text-muted hover:text-garage-text border border-garage-border'
                }`}
              >
                {range.label}
              </button>
            ))}
          </div>
        </div>

        {/* Export Button */}
        <button
          onClick={handleExport}
          disabled={!telemetry || telemetry.total_points === 0}
          className="flex items-center gap-2 px-4 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text hover:bg-garage-bg disabled:opacity-50"
        >
          <Download className="w-4 h-4" />
          Export CSV
        </button>
      </div>

      {/* Parameter Selector */}
      <div className="bg-garage-surface rounded-lg border border-garage-border p-4">
        <p className="text-sm text-garage-text-muted mb-3">Select parameters to chart:</p>
        <div className="flex flex-wrap gap-2">
          {parameters.map((param) => {
            const isSelected = selectedParams.includes(param.param_key)
            const color = CHART_COLORS[selectedParams.indexOf(param.param_key) % CHART_COLORS.length]

            return (
              <button
                key={param.param_key}
                onClick={() => toggleParam(param.param_key)}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                  isSelected
                    ? 'text-white'
                    : 'bg-garage-bg text-garage-text-muted hover:text-garage-text border border-garage-border'
                }`}
                style={isSelected ? { backgroundColor: color } : {}}
              >
                {param.display_name || param.param_key}
                {param.unit && <span className="ml-1 opacity-75">({param.unit})</span>}
              </button>
            )
          })}
        </div>
      </div>

      {/* Chart */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <RefreshCw className="w-8 h-8 text-primary animate-spin" />
        </div>
      ) : chartData.length > 0 ? (
        <div className="bg-garage-surface rounded-lg border border-garage-border p-4">
          <ResponsiveContainer width="100%" height={400}>
            <LineChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#3a4050" />
              <XAxis
                dataKey="timestamp"
                tickFormatter={formatXAxis}
                stroke="#9ca3af"
                fontSize={12}
              />
              <YAxis stroke="#9ca3af" fontSize={12} />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1a1f28',
                  border: '1px solid #3a4050',
                  borderRadius: '8px',
                }}
                labelFormatter={(value) => new Date(value).toLocaleString()}
                formatter={(value, name) => {
                  const param = parameters.find((p) => p.param_key === name)
                  const displayValue = typeof value === 'number' ? value.toFixed(2) : 'N/A'
                  return [`${displayValue} ${param?.unit || ''}`, param?.display_name || name || '']
                }}
              />
              <Legend />
              {selectedParams.map((paramKey, index) => {
                const param = parameters.find((p) => p.param_key === paramKey)
                const color = CHART_COLORS[index % CHART_COLORS.length]

                return (
                  <Line
                    key={paramKey}
                    type="monotone"
                    dataKey={paramKey}
                    name={param?.display_name || paramKey}
                    stroke={color}
                    dot={false}
                    strokeWidth={2}
                  />
                )
              })}
            </LineChart>
          </ResponsiveContainer>

          {/* Stats Summary */}
          {telemetry && (
            <div className="mt-4 pt-4 border-t border-garage-border">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                {telemetry.series.map((series, index) => (
                  <div
                    key={series.param_key}
                    className="bg-garage-bg rounded-lg p-3"
                    style={{ borderLeft: `3px solid ${CHART_COLORS[index % CHART_COLORS.length]}` }}
                  >
                    <p className="text-garage-text-muted text-xs mb-1">
                      {series.display_name || series.param_key}
                    </p>
                    <div className="flex justify-between text-garage-text">
                      <span>
                        Min: {series.min_value?.toFixed(1)} {series.unit}
                      </span>
                      <span>
                        Max: {series.max_value?.toFixed(1)} {series.unit}
                      </span>
                    </div>
                    <p className="text-garage-text-muted text-xs mt-1">
                      Avg: {series.avg_value?.toFixed(1)} {series.unit}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="bg-garage-surface rounded-lg border border-garage-border p-8 text-center">
          <BarChart3 className="w-12 h-12 mx-auto mb-3 text-garage-text-muted opacity-50" />
          <p className="text-garage-text">No data available for the selected time range</p>
          <p className="text-sm text-garage-text-muted mt-2">
            Try selecting a different time range or parameters
          </p>
        </div>
      )}

      {/* Data Points Info */}
      {telemetry && telemetry.total_points > 0 && (
        <p className="text-xs text-garage-text-muted text-right">
          {telemetry.total_points.toLocaleString()} data points
        </p>
      )}
    </div>
  )
}
