/**
 * LiveLink Charts Tab - Historical telemetry charts
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
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
import { Card, Chip, Button, Mono, EmptyState } from '../ui'
import { livelinkService } from '@/services/livelinkService'
import type { TelemetryQueryResponse, LiveLinkParameter } from '@/types/livelink'
import { parseAPITimestampMs } from '@/utils/parseAPITimestamp'
// Unit preference hook available for future unit conversion
// import { useUnitPreference } from '@/hooks/useUnitPreference'
import { useTimeFormat } from '@/hooks/useTimeFormat'
import { formatTime, formatDateTime } from '@/utils/parseAPITimestamp'
import { getActiveLocale, getActiveDateLocale } from '@/constants/i18n'

interface LiveLinkChartsTabProps {
  vin: string
}

type TimeRange = '1h' | '6h' | '24h' | '7d' | '30d'

const TIME_RANGES: TimeRange[] = ['1h', '6h', '24h', '7d', '30d']

// Chart-series colours (data-encoding, NOT UI semantics). Kept as a literal palette (G4(d) carve-out):
// no chart-palette token exists in the P0 token layer, and the design forbids deriving series colours
// from the status/accent tokens (§4.9). The recharts structural chrome (grid/axis/tooltip) DOES move to
// tokens below; only these per-series data colours stay literal.
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
  const { t } = useTranslation('vehicles')
  const [loading, setLoading] = useState(true)
  const [parameters, setParameters] = useState<LiveLinkParameter[]>([])
  const [selectedParams, setSelectedParams] = useState<string[]>([])
  const [timeRange, setTimeRange] = useState<TimeRange>('24h')
  const [telemetry, setTelemetry] = useState<TelemetryQueryResponse | null>(null)
  // Unit conversion can be added here if needed
  // const { system: unitSystem } = useUnitPreference()
  const { timeFormat } = useTimeFormat()

  const timeRangeLabels: Record<TimeRange, string> = {
    '1h': t('livelinkCharts.range1h'),
    '6h': t('livelinkCharts.range6h'),
    '24h': t('livelinkCharts.range24h'),
    '7d': t('livelinkCharts.range7d'),
    '30d': t('livelinkCharts.range30d'),
  }

  // Fetch the parameters THIS vehicle reports. The fleet-wide catalog would
  // offer a propane trailer engine RPM and coolant temperature, then auto-select
  // three of them and draw "no data" — which is exactly what it did.
  useEffect(() => {
    const fetchParameters = async () => {
      try {
        const data = await livelinkService.getVehicleParameters(vin)
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
  }, [vin])

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
      toast.error(t('livelink.charts.loadError'))
    } finally {
      setLoading(false)
    }
  }, [vin, selectedParams, timeRange, getTimeRange, t])

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
        const ts = parseAPITimestampMs(point.timestamp)
        if (ts == null) return
        const existing = dataMap.get(key) || { timestamp: ts }
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
      return formatTime(date, timeFormat)
    }
    if (timeRange === '24h') {
      return formatTime(date, timeFormat)
    }
    return date.toLocaleDateString(getActiveDateLocale(), { month: 'short', day: 'numeric' })
  }

  if (loading && parameters.length === 0) {
    return (
      <div className="flex items-center justify-center py-12">
        <RefreshCw aria-hidden="true" className="w-8 h-8 text-text-mute animate-spin" />
      </div>
    )
  }

  if (parameters.length === 0) {
    return (
      <EmptyState icon={BarChart3} title={t('livelink.charts.noParams')} description={t('livelink.charts.paramsWillAppear')} />
    )
  }

  return (
    <div className="space-y-6">
      {/* Controls */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        {/* Time Range Selector */}
        <div className="flex items-center gap-2">
          <Calendar aria-hidden="true" className="w-5 h-5 text-text-mute" />
          <div className="flex flex-wrap gap-1">
            {TIME_RANGES.map((range) => (
              <Chip key={range} onClick={() => setTimeRange(range)} selected={timeRange === range}>
                {timeRangeLabels[range]}
              </Chip>
            ))}
          </div>
        </div>

        {/* Export Button */}
        <Button variant="secondary" icon={Download} onClick={handleExport} disabled={!telemetry || telemetry.total_points === 0}>
          {t('livelinkCharts.exportCsv')}
        </Button>
      </div>

      {/* Parameter Selector */}
      <Card padding="sm">
        <p className="text-sm text-text-mute mb-3">{t('livelink.charts.selectParams')}:</p>
        <div className="flex flex-wrap gap-2">
          {parameters.map((param) => {
            const isSelected = selectedParams.includes(param.param_key)
            const color = CHART_COLORS[selectedParams.indexOf(param.param_key) % CHART_COLORS.length]

            return (
              <button
                key={param.param_key}
                type="button"
                aria-pressed={isSelected}
                onClick={() => toggleParam(param.param_key)}
                className={`ui-focus-ring ui-motion rounded-chip px-3 py-1.5 text-sm font-medium ${
                  isSelected ? 'text-(--accent-on-solid)' : 'bg-surface-2 text-text-mute hover:text-text border border-border'
                }`}
                style={isSelected ? { backgroundColor: color } : {}}
              >
                {param.display_name || param.param_key}
                {param.unit && <span className="ml-1 opacity-75">({param.unit})</span>}
              </button>
            )
          })}
        </div>
      </Card>

      {/* Chart */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <RefreshCw aria-hidden="true" className="w-8 h-8 text-text-mute animate-spin" />
        </div>
      ) : chartData.length > 0 ? (
        <Card padding="sm">
          <div className="h-[250px] md:h-[400px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-hair)" />
                <XAxis dataKey="timestamp" tickFormatter={formatXAxis} stroke="var(--color-text-mute)" fontSize={12} />
                <YAxis stroke="var(--color-text-mute)" fontSize={12} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'var(--color-surface-2)',
                    border: '1px solid var(--color-border)',
                    borderRadius: '8px',
                    color: 'var(--color-text)',
                  }}
                  labelFormatter={(label) =>
                    typeof label === 'number' || typeof label === 'string'
                      ? formatDateTime(label, timeFormat, { seconds: true })
                      : label
                  }
                  formatter={(value, name) => {
                    const param = parameters.find((p) => p.param_key === name)
                    const displayValue = typeof value === 'number' ? value.toFixed(2) : t('livelinkCharts.notAvailable')
                    return [`${displayValue} ${param?.unit || ''}`, param?.display_name || name || '']
                  }}
                />
                <Legend />
                {selectedParams.map((paramKey, index) => {
                  const param = parameters.find((p) => p.param_key === paramKey)
                  const color = CHART_COLORS[index % CHART_COLORS.length]

                  return (
                    <Line key={paramKey} type="monotone" dataKey={paramKey} name={param?.display_name || paramKey} stroke={color} dot={false} strokeWidth={2} />
                  )
                })}
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Stats Summary */}
          {telemetry && (
            <div className="mt-4 pt-4 border-t border-border">
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                {telemetry.series.map((series, index) => (
                  <div
                    key={series.param_key}
                    className="bg-surface-2 rounded-control p-3"
                    style={{ borderLeft: `3px solid ${CHART_COLORS[index % CHART_COLORS.length]}` }}
                  >
                    <p className="text-text-mute text-xs mb-1">{series.display_name || series.param_key}</p>
                    <div className="flex justify-between text-text">
                      <span>
                        {t('livelink.charts.min')}: <Mono size="xs">{series.min_value?.toFixed(1)}</Mono> {series.unit}
                      </span>
                      <span>
                        {t('livelink.charts.max')}: <Mono size="xs">{series.max_value?.toFixed(1)}</Mono> {series.unit}
                      </span>
                    </div>
                    <p className="text-text-mute text-xs mt-1">
                      {t('livelink.charts.avg')}: <Mono size="xs">{series.avg_value?.toFixed(1)}</Mono> {series.unit}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Card>
      ) : (
        <EmptyState icon={BarChart3} title={t('livelink.charts.noData')} description={t('livelink.charts.tryDifferentRange')} />
      )}

      {/* Data Points Info */}
      {telemetry && telemetry.total_points > 0 && (
        <p className="text-xs text-text-mute text-right">
          {t('livelink.charts.dataPoints', { count: telemetry.total_points.toLocaleString(getActiveLocale()) })}
        </p>
      )}
    </div>
  )
}
