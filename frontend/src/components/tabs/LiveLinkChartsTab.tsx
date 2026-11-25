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
import { CHART_AXIS, CHART_GRID, CHART_OTHER, TOOLTIP_CONTENT_STYLE, TOOLTIP_ITEM_STYLE, chartLegendText, chartSeries } from '../charts/chartTheme'

interface LiveLinkChartsTabProps {
  vin: string
}

type TimeRange = '1h' | '6h' | '24h' | '7d' | '30d'

const TIME_RANGES: TimeRange[] = ['1h', '6h', '24h', '7d', '30d']

/**
 * Give a newly picked parameter the lowest chart slot nobody is wearing, so
 * dropping one never repaints the others. Past 8 picks it wraps; at that point
 * the chart wants fewer lines anyway.
 */
function withSlot(slots: Readonly<Record<string, number>>, paramKey: string): Record<string, number> {
  if (slots[paramKey] !== undefined) return { ...slots }
  const taken = new Set(Object.values(slots))
  let slot = 0
  while (taken.has(slot) && slot < 8) slot++
  return { ...slots, [paramKey]: slot < 8 ? slot : Object.keys(slots).length }
}

export default function LiveLinkChartsTab({ vin }: LiveLinkChartsTabProps) {
  const { t } = useTranslation('vehicles')
  const [loading, setLoading] = useState(true)
  const [parameters, setParameters] = useState<LiveLinkParameter[]>([])
  // The picked params and their chart slots move together in one state, so
  // a toggle can never update one from a stale copy of the other.
  const [picked, setPicked] = useState<{ keys: string[]; slots: Record<string, number> }>({ keys: [], slots: {} })
  const selectedParams = picked.keys
  const slots = picked.slots
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
          const initial = chartableParams.slice(0, 3).map((p) => p.param_key)
          setPicked({ keys: initial, slots: initial.reduce<Record<string, number>>(withSlot, {}) })
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
    setPicked((prev) => {
      if (!prev.keys.includes(paramKey)) return { keys: [...prev.keys, paramKey], slots: withSlot(prev.slots, paramKey) }
      const slotsLeft = { ...prev.slots }
      delete slotsLeft[paramKey]
      return { keys: prev.keys.filter((p) => p !== paramKey), slots: slotsLeft }
    })
  }

  // A series with no slot (a stale refetch) goes grey rather than borrowing slot 1.
  const seriesColor = (paramKey: string): string =>
    slots[paramKey] === undefined ? CHART_OTHER : chartSeries(slots[paramKey])

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
            // A picked chip shows its line colour as a dot and border. White
            // text on a filled series colour fails contrast on half the palette.
            return (
              <button
                key={param.param_key}
                type="button"
                aria-pressed={isSelected}
                onClick={() => toggleParam(param.param_key)}
                className={`ui-focus-ring ui-motion inline-flex items-center rounded-chip border px-3 py-1.5 text-sm font-medium bg-surface-2 ${
                  isSelected ? 'text-text' : 'text-text-mute hover:text-text border-border'
                }`}
                style={isSelected ? { borderColor: seriesColor(param.param_key) } : {}}
              >
                {isSelected && (
                  <span
                    data-testid="series-swatch"
                    aria-hidden="true"
                    className="mr-1.5 h-2 w-2 shrink-0 rounded-full"
                    style={{ backgroundColor: seriesColor(param.param_key) }}
                  />
                )}
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
                <CartesianGrid stroke={CHART_GRID} />
                <XAxis dataKey="timestamp" tickFormatter={formatXAxis} stroke={CHART_AXIS} fontSize={12} />
                <YAxis stroke={CHART_AXIS} fontSize={12} />
                <Tooltip
                  contentStyle={TOOLTIP_CONTENT_STYLE}
                  itemStyle={TOOLTIP_ITEM_STYLE}
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
                <Legend formatter={chartLegendText} />
                {selectedParams.map((paramKey) => {
                  const param = parameters.find((p) => p.param_key === paramKey)
                  return (
                    <Line key={paramKey} type="monotone" dataKey={paramKey} name={param?.display_name || paramKey} stroke={seriesColor(paramKey)} dot={false} strokeWidth={2} />
                  )
                })}
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Stats Summary */}
          {telemetry && (
            <div className="mt-4 pt-4 border-t border-border">
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                {telemetry.series.map((series) => (
                  <div
                    key={series.param_key}
                    className="bg-surface-2 rounded-control p-3"
                    style={{ borderLeft: `3px solid ${seriesColor(series.param_key)}` }}
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
