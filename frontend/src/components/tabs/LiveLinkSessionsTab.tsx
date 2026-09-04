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
import { useUnitFormat } from '@/hooks/useUnitFormat'
import { useTimeFormat } from '@/hooks/useTimeFormat'
import { formatAPITimestamp, formatTime } from '@/utils/parseAPITimestamp'
import { formatAtPrecision } from '@/utils/unitFormat'

/** RPM is a whole number, matching the LiveLink gauge's own classification. */
const RPM_PRECISION = 0

/**
 * Render an RPM figure.
 *
 * RPM is outside the unit system, so nothing converts it, but it is still a
 * number a reader reads: `toFixed` is locale-blind and ungrouped, so this tile
 * rendered "2000" while the LiveLink gauge rendered "2,000" from the same
 * reading.
 *
 * The guard is `== null`, not a truthy test. The line this replaces read
 * `avg_rpm?.toFixed(0) || '--'`, which LOOKS like it swallows a genuine 0 and
 * does not: `(0)?.toFixed(0)` is the STRING "0", which is truthy, so `||` never
 * fired for a real reading. Written explicitly so the next reader does not have
 * to re-derive that, and so a refactor to `value ? ... : '--'` fails a test.
 *
 * Module scope, not a closure: it depends on no hook, and `SessionCard` is a
 * separate component that would otherwise need a fifth formatter prop.
 *
 * @param value The RPM reading, if any.
 * @returns The grouped figure, or the absent marker.
 */
function formatRpm(value: number | null | undefined): string {
  return value == null ? '--' : formatAtPrecision(value, RPM_PRECISION)
}

interface LiveLinkSessionsTabProps {
  vin: string
}

export default function LiveLinkSessionsTab({ vin }: LiveLinkSessionsTabProps) {
  const { t } = useTranslation('vehicles')
  const [sessions, setSessions] = useState<DriveSessionListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [expandedSession, setExpandedSession] = useState<number | null>(null)
  // Sessions in which nothing moved are hidden by default. A parked WiCAN
  // checked in about every 95 minutes and, under the pre-v3.3.0 rule, each
  // check-in opened a session: on a real instance 2,921 of 3,262 never moved at
  // all. They are hidden rather than deleted, because the telemetry needed to
  // rebuild them as real drives was never captured and a release that deleted
  // them removed 2,700 km of genuine distance.
  //
  // Filters on MOVEMENT, not on which rule cut the session. 341 of that same
  // history are pre-v3.3.0 sessions in which the vehicle demonstrably moved,
  // and they are real journeys the user took.
  const [includeStationary, setIncludeStationary] = useState(false)
  const u = useUnitFormat()

  const fetchSessions = useCallback(async () => {
    setLoading(true)
    try {
      const data = await livelinkService.getSessions(vin, {
        limit: 50,
        include_stationary: includeStationary,
      })
      setSessions(data)
    } catch (err) {
      console.error('Failed to fetch sessions:', err)
      toast.error(t('livelink.sessions.loadError'))
    } finally {
      setLoading(false)
    }
  }, [vin, t, includeStationary])

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

  // ★ `distance_km`, `start_odometer` and `end_odometer` are canonical
  // kilometres, and the unverified marker these used to carry has been retired.
  // It existed because `session_service.py::_get_current_odometer` stamped a
  // custom PID's raw reading without recording which unit it held, so no
  // frontend rule could recover the provenance. That is fixed at the source:
  // devices now declare an `odometer_unit` (migration 096) and the service
  // converts on write, so these three columns are metric-canonical like every
  // other quantity and go through the shared adapter.
  //
  // Sessions recorded before that fix were converted in place by
  // `backend/tools/fix_session_odometer_units.py`. Raw telemetry in
  // `vehicle_telemetry_latest` is NOT converted and is still device-native, so
  // `classifyTelemetryParam` keeps marking a bare-PID odometer unverified on
  // the Live tab. That difference is deliberate: it is a claim about a stored
  // column, not about every odometer-shaped number in the product.
  const formatDistance = (value: number | null | undefined): string =>
    value == null ? '--' : u.distance.format(value)

  // Speed and temperature ARE canonical: the session aggregates are km/h and
  // °C, so they go through the shared adapter like every other quantity.
  const formatSpeed = (kmh: number | null | undefined): string =>
    kmh == null ? '--' : u.speed.format(kmh)

  const formatTemp = (celsius: number | null | undefined): string =>
    celsius == null ? '--' : u.temperature.format(celsius)

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
    // Nothing to show because everything on record predates movement detection
    // is a different state from nothing on record at all, and every instance
    // that upgrades lands in the first one. An unexplained blank page there is
    // indistinguishable from a failure.
    if (sessions && !includeStationary && sessions.stationary_total > 0) {
      return (
        <EmptyState
          icon={Clock}
          title={t('livelink.sessions.stationaryHiddenTitle')}
          description={t('livelink.sessions.stationaryHiddenDesc', {
            count: sessions.stationary_total,
          })}
          action={
            <button
              type="button"
              onClick={() => setIncludeStationary(true)}
              className="text-sm font-medium text-primary hover:underline"
            >
              {t('livelink.sessions.showStationary')}
            </button>
          }
        />
      )
    }
    return (
      <EmptyState icon={Clock} title={t('livelink.sessions.noRecords')} description={t('livelink.sessions.autoDetected')} />
    )
  }

  return (
    <div className="space-y-4">
      {/* Session Count */}
      <div className="flex items-center justify-between text-sm text-text-mute">
        <span>{t('livelink.sessions.sessionCount', { count: sessions.total })}</span>
        {sessions.stationary_total > 0 && (
          <button
            type="button"
            onClick={() => setIncludeStationary((shown) => !shown)}
            className="text-sm font-medium text-primary hover:underline"
          >
            {includeStationary
              ? t('livelink.sessions.hideStationary')
              : t('livelink.sessions.showStationary')}
          </button>
        )}
      </div>

      {/* Session List */}
      {sessions.sessions.map((session) => (
        <SessionCard
          key={session.id}
          session={session}
          isExpanded={expandedSession === session.id}
          onToggle={() => toggleExpanded(session.id)}
          formatDuration={formatDuration}
          formatDistance={formatDistance}
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
  formatDistance,
  formatSpeed,
  formatTemp,
}: {
  session: DriveSession
  isExpanded: boolean
  onToggle: () => void
  formatDuration: (s: number | null | undefined) => string
  formatDistance: (value: number | null | undefined) => string
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
          {/* Says what a revealed row is. Version 0 means the drive was cut on
              device contact, so it may be a parked vehicle's check-in rather
              than a journey, and its distance may be an odometer step that
              accrued while it sat still. */}
          {session.boundary_algorithm_version === 0 && (
            <Chip tone="muted">{t('livelink.sessions.legacyBadge')}</Chip>
          )}
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
                <Mono size="sm">{formatDistance(session.distance_km)}</Mono>
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
            <Tile icon={MapPin} label={t('livelink.sessions.distance')} value={formatDistance(session.distance_km)} />
            <Tile icon={Gauge} label={t('livelink.sessions.avgMaxSpeed')} value={`${formatSpeed(session.avg_speed)} / ${formatSpeed(session.max_speed)}`} />
            {session.avg_rpm != null && (
              <Tile icon={Activity} label={t('livelink.sessions.avgMaxRPM')} value={`${formatRpm(session.avg_rpm)} / ${formatRpm(session.max_rpm)}`} />
            )}
            {session.avg_coolant_temp != null && (
              <Tile icon={Thermometer} label={t('livelink.sessions.avgMaxCoolant')} value={`${formatTemp(session.avg_coolant_temp)} / ${formatTemp(session.max_coolant_temp)}`} />
            )}
            {session.start_odometer != null && (
              <Tile icon={Gauge} label={t('livelink.sessions.odometerStartEnd')} value={`${formatDistance(session.start_odometer)} → ${formatDistance(session.end_odometer)}`} />
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
