/**
 * LiveLink Sessions Tab - Drive session history
 */

import { useState, useEffect, useCallback } from 'react'
import { toast } from 'sonner'
import {
  Clock,
  MapPin,
  Gauge,
  Thermometer,
  ChevronDown,
  ChevronUp,
  Calendar,
  RefreshCw,
  Activity,
} from 'lucide-react'
import { livelinkService } from '@/services/livelinkService'
import type { DriveSession, DriveSessionListResponse } from '@/types/livelink'
import { useUnitPreference } from '@/hooks/useUnitPreference'

interface LiveLinkSessionsTabProps {
  vin: string
}

export default function LiveLinkSessionsTab({ vin }: LiveLinkSessionsTabProps) {
  const [sessions, setSessions] = useState<DriveSessionListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [expandedSession, setExpandedSession] = useState<number | null>(null)
  const { system: unitSystem } = useUnitPreference()

  const fetchSessions = useCallback(async () => {
    setLoading(true)
    try {
      const data = await livelinkService.getSessions(vin, { limit: 50 })
      setSessions(data)
    } catch (err) {
      console.error('Failed to fetch sessions:', err)
      toast.error('Failed to load drive sessions')
    } finally {
      setLoading(false)
    }
  }, [vin])

  useEffect(() => {
    fetchSessions()
  }, [fetchSessions])

  const formatDuration = (seconds: number | null) => {
    if (seconds === null) return '--'
    const hours = Math.floor(seconds / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    if (hours > 0) return `${hours}h ${minutes}m`
    return `${minutes}m`
  }

  // Odometer and distance values from sessions are raw OBD2 values
  // They match the user's locale (miles for US, km for metric)
  // No conversion needed - just display with the appropriate unit label
  const formatOdometer = (value: number | null) => {
    if (value === null) return '--'
    const label = unitSystem === 'imperial' ? 'mi' : 'km'
    return `${Math.round(value).toLocaleString()} ${label}`
  }

  const formatSpeed = (kmh: number | null) => {
    if (kmh === null) return '--'
    if (unitSystem === 'imperial') {
      const mph = kmh * 0.621371
      return `${mph.toFixed(0)} mph`
    }
    return `${kmh.toFixed(0)} km/h`
  }

  const formatTemp = (celsius: number | null) => {
    if (celsius === null) return '--'
    if (unitSystem === 'imperial') {
      const fahrenheit = (celsius * 9) / 5 + 32
      return `${fahrenheit.toFixed(0)}°F`
    }
    return `${celsius.toFixed(0)}°C`
  }

  const toggleExpanded = (sessionId: number) => {
    setExpandedSession(expandedSession === sessionId ? null : sessionId)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <RefreshCw className="w-8 h-8 text-primary animate-spin" />
      </div>
    )
  }

  if (!sessions || sessions.sessions.length === 0) {
    return (
      <div className="bg-garage-surface rounded-lg border border-garage-border p-8 text-center">
        <Clock className="w-12 h-12 mx-auto mb-3 text-garage-text-muted opacity-50" />
        <p className="text-garage-text">No drive sessions recorded</p>
        <p className="text-sm text-garage-text-muted mt-2">
          Sessions are automatically detected when your vehicle's ECU comes online
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Session Count */}
      <div className="flex items-center justify-between text-sm text-garage-text-muted">
        <span>{sessions.total} sessions recorded</span>
      </div>

      {/* Session List */}
      {sessions.sessions.map((session) => (
        <SessionCard
          key={session.id}
          session={session}
          isExpanded={expandedSession === session.id}
          onToggle={() => toggleExpanded(session.id)}
          formatDuration={formatDuration}
          formatOdometer={formatOdometer}
          formatSpeed={formatSpeed}
          formatTemp={formatTemp}
        />
      ))}
    </div>
  )
}

// Session Card Component
function SessionCard({
  session,
  isExpanded,
  onToggle,
  formatDuration,
  formatOdometer,
  formatSpeed,
  formatTemp,
}: {
  session: DriveSession
  isExpanded: boolean
  onToggle: () => void
  formatDuration: (s: number | null) => string
  formatOdometer: (value: number | null) => string
  formatSpeed: (kmh: number | null) => string
  formatTemp: (c: number | null) => string
}) {
  const isActive = !session.ended_at

  return (
    <div className="bg-garage-surface rounded-lg border border-garage-border overflow-hidden">
      {/* Header - Always Visible */}
      <button
        onClick={onToggle}
        className="w-full p-4 flex items-center justify-between hover:bg-garage-bg/50 transition-colors"
      >
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <Calendar className="w-5 h-5 text-primary" />
            <div className="text-left">
              <div className="text-garage-text font-medium">
                {new Date(session.started_at).toLocaleDateString(undefined, {
                  weekday: 'short',
                  month: 'short',
                  day: 'numeric',
                })}
              </div>
              <div className="text-xs text-garage-text-muted">
                {new Date(session.started_at).toLocaleTimeString(undefined, {
                  hour: '2-digit',
                  minute: '2-digit',
                })}
                {session.ended_at && (
                  <>
                    {' → '}
                    {new Date(session.ended_at).toLocaleTimeString(undefined, {
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </>
                )}
              </div>
            </div>
          </div>
          {isActive && (
            <span className="flex items-center gap-1 px-2 py-1 bg-green-500/20 text-green-500 text-xs rounded">
              <Activity className="w-3 h-3" />
              In Progress
            </span>
          )}
        </div>

        <div className="flex items-center gap-6">
          {/* Quick Stats */}
          <div className="hidden md:flex items-center gap-6 text-sm text-garage-text-muted">
            <div className="flex items-center gap-1">
              <Clock className="w-4 h-4" />
              <span>{formatDuration(session.duration_seconds)}</span>
            </div>
            {session.distance_km !== null && (
              <div className="flex items-center gap-1">
                <MapPin className="w-4 h-4" />
                <span>{formatOdometer(session.distance_km)}</span>
              </div>
            )}
            {session.max_speed !== null && (
              <div className="flex items-center gap-1">
                <Gauge className="w-4 h-4" />
                <span>{formatSpeed(session.max_speed)}</span>
              </div>
            )}
          </div>

          {isExpanded ? (
            <ChevronUp className="w-5 h-5 text-garage-text-muted" />
          ) : (
            <ChevronDown className="w-5 h-5 text-garage-text-muted" />
          )}
        </div>
      </button>

      {/* Expanded Details */}
      {isExpanded && (
        <div className="px-4 pb-4 border-t border-garage-border">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-4">
            {/* Duration */}
            <StatCard
              icon={<Clock className="w-5 h-5 text-primary" />}
              label="Duration"
              value={formatDuration(session.duration_seconds)}
            />

            {/* Distance */}
            <StatCard
              icon={<MapPin className="w-5 h-5 text-primary" />}
              label="Distance"
              value={formatOdometer(session.distance_km)}
            />

            {/* Speed */}
            <StatCard
              icon={<Gauge className="w-5 h-5 text-primary" />}
              label="Avg / Max Speed"
              value={`${formatSpeed(session.avg_speed)} / ${formatSpeed(session.max_speed)}`}
            />

            {/* RPM */}
            {session.avg_rpm !== null && (
              <StatCard
                icon={<Activity className="w-5 h-5 text-primary" />}
                label="Avg / Max RPM"
                value={`${session.avg_rpm?.toFixed(0) || '--'} / ${session.max_rpm?.toFixed(0) || '--'}`}
              />
            )}

            {/* Coolant Temp */}
            {session.avg_coolant_temp !== null && (
              <StatCard
                icon={<Thermometer className="w-5 h-5 text-primary" />}
                label="Avg / Max Coolant"
                value={`${formatTemp(session.avg_coolant_temp)} / ${formatTemp(session.max_coolant_temp)}`}
              />
            )}

            {/* Odometer */}
            {session.start_odometer !== null && (
              <StatCard
                icon={<Gauge className="w-5 h-5 text-primary" />}
                label="Odometer Start / End"
                value={`${formatOdometer(session.start_odometer)} → ${formatOdometer(session.end_odometer)}`}
              />
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// Stat Card Component
function StatCard({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode
  label: string
  value: string
}) {
  return (
    <div className="bg-garage-bg rounded-lg p-3">
      <div className="flex items-center gap-2 mb-1">
        {icon}
        <span className="text-xs text-garage-text-muted">{label}</span>
      </div>
      <div className="text-sm font-medium text-garage-text">{value}</div>
    </div>
  )
}
