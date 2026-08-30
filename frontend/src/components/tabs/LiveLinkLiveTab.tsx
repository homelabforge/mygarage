/**
 * LiveLink Live Tab - Real-time telemetry gauges and status
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Radio,
  Wifi,
  WifiOff,
  Gauge,
  Thermometer,
  Zap,
  Battery,
  AlertTriangle,
  RefreshCw,
  Activity,
  Car,
} from 'lucide-react'
import { livelinkService } from '@/services/livelinkService'
import type { VehicleLiveLinkStatus, TelemetryLatestValue } from '@/types/livelink'
import { useUnitFormat } from '@/hooks/useUnitFormat'
import { useTimeFormat } from '@/hooks/useTimeFormat'
import { convertTelemetryValue, getParamDisplayName } from '@/utils/telemetryUnits'
import type { UnitFormat } from '@/utils/unitFormat'
import { formatTime } from '@/utils/parseAPITimestamp'
import { Card, Mono, EmptyState } from '../ui'

interface LiveLinkLiveTabProps {
  vin: string
}

export default function LiveLinkLiveTab({ vin }: LiveLinkLiveTabProps) {
  const { t } = useTranslation('vehicles')
  const [status, setStatus] = useState<VehicleLiveLinkStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date())
  const unitFormat = useUnitFormat()
  const { timeFormat } = useTimeFormat()

  const fetchStatus = useCallback(async () => {
    try {
      const data = await livelinkService.getVehicleStatus(vin)
      setStatus(data)
      setError(null)
      setLastRefresh(new Date())
    } catch (err) {
      console.error('Failed to fetch LiveLink status:', err)
      setError(t('livelink.fetchStatusError'))
    } finally {
      setLoading(false)
    }
  }, [vin, t])

  // Initial fetch and polling every 5 seconds while the tab is visible.
  // We pause when the document is hidden because (a) the user isn't watching,
  // (b) backgrounded polling competes with foreground requests through the
  // service worker, and (c) mobile browsers throttle setInterval anyway —
  // doing it explicitly here keeps behavior predictable across browsers.
  useEffect(() => {
    let interval: ReturnType<typeof setInterval> | null = null

    const startPolling = () => {
      if (interval !== null) return
      fetchStatus()
      interval = setInterval(fetchStatus, 5000)
    }
    const stopPolling = () => {
      if (interval !== null) {
        clearInterval(interval)
        interval = null
      }
    }
    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        startPolling()
      } else {
        stopPolling()
      }
    }

    if (document.visibilityState === 'visible') {
      startPolling()
    }
    document.addEventListener('visibilitychange', handleVisibility)

    return () => {
      document.removeEventListener('visibilitychange', handleVisibility)
      stopPolling()
    }
  }, [fetchStatus])

  const getStatusColor = (deviceStatus: string, ecuStatus: string) => {
    if (deviceStatus !== 'online') return 'danger'
    if (ecuStatus === 'online') return 'success'
    return 'info'
  }

  const getStatusText = (deviceStatus: string, ecuStatus: string) => {
    if (deviceStatus !== 'online') return t('livelink.wicanOffline')
    if (ecuStatus === 'online') return t('livelink.vehicleRunning')
    return t('livelink.vehicleParked')
  }

  const formatDuration = (seconds: number | null | undefined) => {
    if (seconds == null) return '--'
    const hours = Math.floor(seconds / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    const secs = seconds % 60
    if (hours > 0) return `${hours}h ${minutes}m`
    if (minutes > 0) return `${minutes}m ${secs}s`
    return `${secs}s`
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <RefreshCw aria-hidden="true" className="w-8 h-8 text-text-mute animate-spin" />
      </div>
    )
  }

  if (error || !status) {
    return (
      <EmptyState
        icon={Radio}
        title={error || t('livelink.noData')}
        description={t('livelink.ensureDeviceLinked')}
      />
    )
  }

  const statusColor = getStatusColor(status.device_status, status.ecu_status)
  const statusText = getStatusText(status.device_status, status.ecu_status)

  return (
    <div className="space-y-6">
      {/* Status Bar */}
      <Card padding="sm">
        <div className="flex flex-wrap items-center gap-2 md:gap-4">
          {/* Connection Status */}
          <div className="flex items-center gap-2">
            <span
              aria-hidden="true"
              className={`w-3 h-3 rounded-full ${
                statusColor === 'success' ? 'bg-success' : statusColor === 'info' ? 'bg-info' : 'bg-danger'
              }`}
            />
            <span className="text-text font-medium">{statusText}</span>
          </div>

          {/* WiFi Signal */}
          {status.rssi !== null && (
            <div className="flex items-center gap-1 text-text-mute">
              {status.device_status === 'online' ? (
                <Wifi aria-hidden="true" className="w-4 h-4" />
              ) : (
                <WifiOff aria-hidden="true" className="w-4 h-4" />
              )}
              <span className="text-sm">{status.rssi} dBm</span>
            </div>
          )}

          {/* Current Session */}
          {status.current_session_id && (
            <div className="flex items-center gap-1 text-success">
              <Activity aria-hidden="true" className="w-4 h-4" />
              <span className="text-sm">
                {t('livelink.session')}: {formatDuration(status.session_duration_seconds)}
              </span>
            </div>
          )}

          {/* Last Update */}
          <div className="ml-auto text-sm text-text-mute">
            {t('livelink.lastUpdate')}: {formatTime(lastRefresh, timeFormat, { seconds: true })}
          </div>
        </div>
      </Card>

      {/* Live Gauges Grid */}
      {(status.latest_values?.length ?? 0) > 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {status.latest_values?.map((value) => (
            <GaugeCard key={value.param_key} value={value} unitFormat={unitFormat} />
          ))}
        </div>
      ) : (
        <EmptyState icon={Car} title={t('livelink.noTelemetry')} description={t('livelink.telemetryWillAppear')} />
      )}
    </div>
  )
}

// Gauge Card Component
interface GaugeCardProps {
  value: TelemetryLatestValue
  unitFormat: UnitFormat
}

function GaugeCard({ value, unitFormat }: GaugeCardProps) {
  const { t } = useTranslation('vehicles')
  const { timeFormat } = useTimeFormat()
  const IconComponent = useMemo(() => {
    const key = value.param_key.toLowerCase()
    if (key.includes('rpm') || key.includes('engine')) return Gauge
    if (key.includes('temp') || key.includes('coolant')) return Thermometer
    if (key.includes('volt') || key.includes('battery')) return Battery
    if (key.includes('speed')) return Activity
    return Zap
  }, [value.param_key])

  // Convert through the shared adapter. `unit` is the resolved label, or the
  // unknown-unit marker when the reading establishes no unit at all (a custom
  // odometer PID); `converted.unverified` says which of the two it is.
  const converted = useMemo(() => {
    return convertTelemetryValue(value.value, value.param_key, value.unit ?? null, unitFormat, t)
  }, [value.value, value.param_key, value.unit, unitFormat, t])

  // Format the display name
  const displayName = useMemo(() => {
    return getParamDisplayName(value.param_key, value.display_name ?? null)
  }, [value.param_key, value.display_name])

  return (
    <div
      className={`rounded-card border p-4 ${
        value.in_warning ? 'bg-danger/10 border-danger/30' : 'bg-surface border-border'
      }`}
    >
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <IconComponent aria-hidden="true" className={`w-5 h-5 ${value.in_warning ? 'text-danger' : 'text-text-mute'}`} />
          <span className="text-sm text-text-mute truncate">{displayName}</span>
        </div>
        {value.in_warning && <AlertTriangle aria-hidden="true" className="w-4 h-4 text-danger" />}
      </div>
      <Mono as="div" size="2xl" weight="bold" tone={value.in_warning ? 'danger' : 'default'}>
        {converted.text}
        {converted.unit && <span className="text-sm font-normal text-text-mute ml-1">{converted.unit}</span>}
      </Mono>
      <div className="text-xs text-text-mute mt-1">
        {formatTime(value.timestamp, timeFormat, { seconds: true })}
      </div>
    </div>
  )
}
