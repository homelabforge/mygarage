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
import { useUnitPreference } from '@/hooks/useUnitPreference'
import {
  convertTelemetryValue,
  formatTelemetryValue,
  getParamDisplayName,
} from '@/utils/telemetryUnits'
import type { UnitSystem } from '@/utils/units'
import { formatAPITimestamp } from '@/utils/parseAPITimestamp'

interface LiveLinkLiveTabProps {
  vin: string
}

export default function LiveLinkLiveTab({ vin }: LiveLinkLiveTabProps) {
  const { t } = useTranslation('vehicles')
  const [status, setStatus] = useState<VehicleLiveLinkStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date())
  const { system: unitSystem } = useUnitPreference()

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

  // Initial fetch and polling every 5 seconds
  useEffect(() => {
    fetchStatus()
    const interval = setInterval(fetchStatus, 5000)
    return () => clearInterval(interval)
  }, [fetchStatus])

  const getStatusColor = (deviceStatus: string, ecuStatus: string) => {
    if (deviceStatus !== 'online') return 'red'
    if (ecuStatus === 'online') return 'green'
    return 'blue'
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
        <RefreshCw className="w-8 h-8 text-primary animate-spin" />
      </div>
    )
  }

  if (error || !status) {
    return (
      <div className="bg-garage-surface rounded-lg border border-garage-border p-6 text-center">
        <Radio className="w-12 h-12 mx-auto mb-3 text-garage-text-muted opacity-50" />
        <p className="text-garage-text-muted">{error || t('livelink.noData')}</p>
        <p className="text-sm text-garage-text-muted mt-2">
          {t('livelink.ensureDeviceLinked')}
        </p>
      </div>
    )
  }

  const statusColor = getStatusColor(status.device_status, status.ecu_status)
  const statusText = getStatusText(status.device_status, status.ecu_status)

  return (
    <div className="space-y-6">
      {/* Status Bar */}
      <div className="bg-garage-surface rounded-lg border border-garage-border p-4">
        <div className="flex flex-wrap items-center gap-2 md:gap-4">
          {/* Connection Status */}
          <div className="flex items-center gap-2">
            <div
              className={`w-3 h-3 rounded-full ${
                statusColor === 'green'
                  ? 'bg-green-500'
                  : statusColor === 'blue'
                  ? 'bg-blue-500'
                  : 'bg-red-500'
              }`}
            />
            <span className="text-garage-text font-medium">{statusText}</span>
          </div>

          {/* WiFi Signal */}
          {status.rssi !== null && (
            <div className="flex items-center gap-1 text-garage-text-muted">
              {status.device_status === 'online' ? (
                <Wifi className="w-4 h-4" />
              ) : (
                <WifiOff className="w-4 h-4" />
              )}
              <span className="text-sm">{status.rssi} dBm</span>
            </div>
          )}

          {/* Current Session */}
          {status.current_session_id && (
            <div className="flex items-center gap-1 text-green-500">
              <Activity className="w-4 h-4" />
              <span className="text-sm">{t('livelink.session')}: {formatDuration(status.session_duration_seconds)}</span>
            </div>
          )}

          {/* Last Update */}
          <div className="ml-auto text-sm text-garage-text-muted">
            {t('livelink.lastUpdate')}: {lastRefresh.toLocaleTimeString()}
          </div>
        </div>
      </div>

      {/* Live Gauges Grid */}
      {(status.latest_values?.length ?? 0) > 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {status.latest_values?.map((value) => (
            <GaugeCard key={value.param_key} value={value} unitSystem={unitSystem} />
          ))}
        </div>
      ) : (
        <div className="bg-garage-surface rounded-lg border border-garage-border p-8 text-center">
          <Car className="w-12 h-12 mx-auto mb-3 text-garage-text-muted opacity-50" />
          <p className="text-garage-text-muted">{t('livelink.noTelemetry')}</p>
          <p className="text-sm text-garage-text-muted mt-2">
            {t('livelink.telemetryWillAppear')}
          </p>
        </div>
      )}

      {/* Active DTCs Summary */}
      {/* This would show a quick summary of active DTCs, if any */}
    </div>
  )
}

// Gauge Card Component
interface GaugeCardProps {
  value: TelemetryLatestValue
  unitSystem: UnitSystem
}

function GaugeCard({ value, unitSystem }: GaugeCardProps) {
  const IconComponent = useMemo(() => {
    const key = value.param_key.toLowerCase()
    if (key.includes('rpm') || key.includes('engine')) return Gauge
    if (key.includes('temp') || key.includes('coolant')) return Thermometer
    if (key.includes('volt') || key.includes('battery')) return Battery
    if (key.includes('speed')) return Activity
    return Zap
  }, [value.param_key])

  // Convert value based on unit preference
  const converted = useMemo(() => {
    return convertTelemetryValue(value.value, value.param_key, value.unit ?? null, unitSystem)
  }, [value.value, value.param_key, value.unit, unitSystem])

  // Format the display name
  const displayName = useMemo(() => {
    return getParamDisplayName(value.param_key, value.display_name ?? null)
  }, [value.param_key, value.display_name])

  const getBgColor = () => {
    if (value.in_warning) return 'bg-red-500/10 border-red-500/30'
    return 'bg-garage-surface border-garage-border'
  }

  const getTextColor = () => {
    if (value.in_warning) return 'text-red-500'
    return 'text-garage-text'
  }

  return (
    <div className={`rounded-lg border p-4 ${getBgColor()}`}>
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <IconComponent className={`w-5 h-5 ${value.in_warning ? 'text-red-500' : 'text-primary'}`} />
          <span className="text-sm text-garage-text-muted truncate">
            {displayName}
          </span>
        </div>
        {value.in_warning && <AlertTriangle className="w-4 h-4 text-red-500" />}
      </div>
      <div className={`text-2xl font-bold ${getTextColor()}`}>
        {formatTelemetryValue(converted.value, value.param_key)}
        {converted.unit && (
          <span className="text-sm font-normal text-garage-text-muted ml-1">{converted.unit}</span>
        )}
      </div>
      <div className="text-xs text-garage-text-muted mt-1">
        {formatAPITimestamp(value.timestamp, (d) => d.toLocaleTimeString())}
      </div>
    </div>
  )
}
