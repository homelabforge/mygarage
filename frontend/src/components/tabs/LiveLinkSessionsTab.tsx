/**
 * LiveLink Sessions Tab - Drive session history
 */

import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
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
import { Card, Chip, Mono, EmptyState, Tile } from '../ui'
import { useUnitPreference } from '@/hooks/useUnitPreference'
import { useTimeFormat } from '@/hooks/useTimeFormat'
import { formatAPITimestamp, formatTime } from '@/utils/parseAPITimestamp'
import { getActiveLocale } from '@/constants/i18n'

interface LiveLinkSessionsTabProps {
  vin: string
}

export default function LiveLinkSessionsTab({ vin }: LiveLinkSessionsTabProps) {
  const { t } = useTranslation('vehicles')
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
      toast.error(t('livelink.sessions.loadError'))
    } finally {
      setLoading(false)
    }
  }, [vin, t])

  useEffect(() => {
    fetchSessions()
  }, [fetchSessions])

  const formatDuration = (seconds: number | null | undefined) => {
    if (seconds == null) return '--'
    const hours = Math.floor(seconds / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    if (hours > 0) return `${hours}h ${minutes}m`
    return `${minutes}m`
  }

  // Odometer and distance values from sessions are raw OBD2 values
  // They match the user's locale (miles for US, km for metric)
  // No conversion needed - just display with the appropriate unit label
  const formatOdometer = (value: number | null | undefined) => {
    if (value == null) return '--'
    const label = unitSystem === 'imperial' ? 'mi' : 'km'
    return `${Math.round(value).toLocaleString(getActiveLocale())} ${label}`
  }

  const formatSpeed = (kmh: number | null | undefined) => {
    if (kmh == null) return '--'
    if (unitSystem === 'imperial') {
      const mph = kmh * 0.621371
      return `${mph.toFixed(0)} mph`
    }
    return `${kmh.toFixed(0)} km/h`
  }

  const formatTemp = (celsius: number | null | undefined) => {
    if (celsius == null) return '--'
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
        <RefreshCw aria-hidden="true" className="w-8 h-8 text-text-mute animate-spin" />
      </div>
    )
  }

  if (!sessions || sessions.sessions.length === 0) {
    return (
      <EmptyState icon={Clock} title={t('livelink.sessions.noRecords')} description={t('livelink.sessions.autoDetected')} />
    )
  }

  return (
    <div className="space-y-4">
      {/* Session Count */}
      <div className="flex items-center justify-between text-sm text-text-mute">
        <span>{t('livelink.sessions.sessionCount', { count: sessions.total })}</span>
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
  formatDuration: (s: number | null | undefined) => string
  formatOdometer: (value: number | null | undefined) => string
  formatSpeed: (kmh: number | null | undefined) => string
  formatTemp: (c: number | null | undefined) => string
}) {
  const { t } = useTranslation('vehicles')
  const { timeFormat } = useTimeFormat()
  const isActive = !session.ended_at

  return (
    <Card padding="none" className="overflow-hidden">
      {/* Header - Always Visible */}
      <button onClick={onToggle} className="w-full p-4 flex items-center justify-between hover:bg-surface-2/50 ui-motion">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <Calendar aria-hidden="true" className="w-5 h-5 text-text-mute" />
            <div className="text-left">
              <div className="text-text font-medium">
                {formatAPITimestamp(session.started_at, (d) =>
                  d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }),
                )}
              </div>
              <div className="text-xs text-text-mute">
                {formatTime(session.started_at, timeFormat)}
                {session.ended_at && (
                  <>
                    {' → '}
                    {formatTime(session.ended_at, timeFormat)}
                  </>
                )}
              </div>
            </div>
          </div>
          {isActive && <Chip tone="success" icon={Activity}>{t('livelink.sessions.inProgress')}</Chip>}
        </div>

        <div className="flex items-center gap-6">
          {/* Quick Stats */}
          <div className="hidden md:flex items-center gap-6 text-sm text-text-mute">
            <div className="flex items-center gap-1">
              <Clock aria-hidden="true" className="w-4 h-4" />
              <Mono size="sm">{formatDuration(session.duration_seconds)}</Mono>
            </div>
            {session.distance_km != null && (
              <div className="flex items-center gap-1">
                <MapPin aria-hidden="true" className="w-4 h-4" />
                <Mono size="sm">{formatOdometer(session.distance_km)}</Mono>
              </div>
            )}
            {session.max_speed != null && (
              <div className="flex items-center gap-1">
                <Gauge aria-hidden="true" className="w-4 h-4" />
                <Mono size="sm">{formatSpeed(session.max_speed)}</Mono>
              </div>
            )}
          </div>

          {isExpanded ? (
            <ChevronUp aria-hidden="true" className="w-5 h-5 text-text-mute" />
          ) : (
            <ChevronDown aria-hidden="true" className="w-5 h-5 text-text-mute" />
          )}
        </div>
      </button>

      {/* Expanded Details */}
      {isExpanded && (
        <div className="px-4 pb-4 border-t border-border">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-4">
            <Tile icon={Clock} label={t('livelink.sessions.duration')} value={formatDuration(session.duration_seconds)} />
            <Tile icon={MapPin} label={t('livelink.sessions.distance')} value={formatOdometer(session.distance_km)} />
            <Tile icon={Gauge} label={t('livelink.sessions.avgMaxSpeed')} value={`${formatSpeed(session.avg_speed)} / ${formatSpeed(session.max_speed)}`} />
            {session.avg_rpm != null && (
              <Tile icon={Activity} label={t('livelink.sessions.avgMaxRPM')} value={`${session.avg_rpm?.toFixed(0) || '--'} / ${session.max_rpm?.toFixed(0) || '--'}`} />
            )}
            {session.avg_coolant_temp != null && (
              <Tile icon={Thermometer} label={t('livelink.sessions.avgMaxCoolant')} value={`${formatTemp(session.avg_coolant_temp)} / ${formatTemp(session.max_coolant_temp)}`} />
            )}
            {session.start_odometer != null && (
              <Tile icon={Gauge} label={t('livelink.sessions.odometerStartEnd')} value={`${formatOdometer(session.start_odometer)} → ${formatOdometer(session.end_odometer)}`} />
            )}
            {session.idle_seconds != null && (
              <Tile icon={Clock} label={t('livelink.sessions.idleTime')} value={formatDuration(session.idle_seconds)} />
            )}
            {session.harsh_accel_count != null && (
              <Tile icon={Activity} label={t('livelink.sessions.harshAccel')} value={String(session.harsh_accel_count)} />
            )}
            {session.harsh_brake_count != null && (
              <Tile icon={Gauge} label={t('livelink.sessions.harshBrake')} value={String(session.harsh_brake_count)} />
            )}
          </div>
        </div>
      )}
    </Card>
  )
}
