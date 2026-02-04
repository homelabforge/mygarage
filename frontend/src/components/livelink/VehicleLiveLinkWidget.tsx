/**
 * Vehicle LiveLink Widget - Compact status display for dashboard cards
 */

import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { Radio, Activity, Car, Thermometer } from 'lucide-react'
import { livelinkService } from '@/services/livelinkService'
import type { VehicleLiveLinkStatus } from '@/types/livelink'
import { useUnitPreference } from '@/hooks/useUnitPreference'
import { convertTelemetryValue } from '@/utils/telemetryUnits'

interface VehicleLiveLinkWidgetProps {
  vin: string
}

export default function VehicleLiveLinkWidget({ vin }: VehicleLiveLinkWidgetProps) {
  const navigate = useNavigate()
  const [status, setStatus] = useState<VehicleLiveLinkStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [hasDevice, setHasDevice] = useState(false)
  const { system: unitSystem } = useUnitPreference()

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const data = await livelinkService.getVehicleStatus(vin)
        setStatus(data)
        setHasDevice(data.device_id !== null)
      } catch {
        // No LiveLink device or error - don't show widget
        setHasDevice(false)
      } finally {
        setLoading(false)
      }
    }

    fetchStatus()

    // Poll every 30 seconds for dashboard view (less aggressive than detail view)
    const interval = setInterval(fetchStatus, 30000)
    return () => clearInterval(interval)
  }, [vin])

  // Helper to find a parameter value from the array
  const findParam = (key: string) => {
    return status?.latest_values?.find(v => v.param_key.toUpperCase() === key)
  }

  // Get key metrics from latest values (hooks must be before early return)
  const speed = findParam('SPEED')
  const rpm = findParam('ENGINE_RPM')
  const coolant = findParam('COOLANT_TMP')

  // Convert values based on unit preference (hooks must be before early return)
  const convertedSpeed = useMemo(() => {
    if (!speed) return null
    return convertTelemetryValue(speed.value, 'SPEED', speed.unit, unitSystem)
  }, [speed, unitSystem])

  const convertedCoolant = useMemo(() => {
    if (!coolant) return null
    return convertTelemetryValue(coolant.value, 'COOLANT_TMP', coolant.unit, unitSystem)
  }, [coolant, unitSystem])

  // Don't render if no device or loading
  if (loading || !hasDevice || !status) {
    return null
  }

  const isRunning = status.ecu_status === 'online'
  const isOnline = status.device_status === 'online'

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    navigate(`/vehicles/${vin}?tab=live`)
  }

  return (
    <div
      onClick={handleClick}
      className={`mt-3 p-3 rounded-lg border cursor-pointer transition-all ${
        isRunning
          ? 'bg-green-500/10 border-green-500/30 hover:border-green-500/50'
          : isOnline
            ? 'bg-blue-500/10 border-blue-500/30 hover:border-blue-500/50'
            : 'bg-garage-bg border-garage-border hover:border-garage-text-muted'
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Radio className={`w-4 h-4 ${isRunning ? 'text-green-500' : isOnline ? 'text-blue-500' : 'text-garage-text-muted'}`} />
          <span className="text-xs font-medium text-garage-text">LiveLink</span>
        </div>
        <span className={`text-xs px-2 py-0.5 rounded ${
          isRunning
            ? 'bg-green-500/20 text-green-500'
            : isOnline
              ? 'bg-blue-500/20 text-blue-500'
              : 'bg-garage-bg text-garage-text-muted'
        }`}>
          {isRunning ? 'Running' : isOnline ? 'Parked' : 'Offline'}
        </span>
      </div>

      {isRunning && (
        <div className="grid grid-cols-3 gap-2 mt-2">
          {convertedSpeed && (
            <div className="text-center">
              <Activity className="w-3 h-3 mx-auto mb-1 text-garage-text-muted" />
              <div className="text-xs font-bold text-garage-text">{Math.round(convertedSpeed.value)}</div>
              <div className="text-[10px] text-garage-text-muted">{convertedSpeed.unit.toUpperCase()}</div>
            </div>
          )}
          {rpm !== undefined && (
            <div className="text-center">
              <Car className="w-3 h-3 mx-auto mb-1 text-garage-text-muted" />
              <div className="text-xs font-bold text-garage-text">{rpm.value.toFixed(0)}</div>
              <div className="text-[10px] text-garage-text-muted">RPM</div>
            </div>
          )}
          {convertedCoolant && coolant && (
            <div className="text-center">
              <Thermometer className={`w-3 h-3 mx-auto mb-1 ${coolant.in_warning ? 'text-red-500' : 'text-garage-text-muted'}`} />
              <div className={`text-xs font-bold ${coolant.in_warning ? 'text-red-500' : 'text-garage-text'}`}>
                {Math.round(convertedCoolant.value)}{convertedCoolant.unit}
              </div>
              <div className="text-[10px] text-garage-text-muted">Coolant</div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
