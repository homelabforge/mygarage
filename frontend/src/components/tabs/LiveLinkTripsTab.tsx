/**
 * LiveLink Trips Tab - GPS-tracked drive session list
 *
 * List (Task 14) + selected-trip route map (Task 15). Task 16 adds a
 * last-location card.
 */

import { useState, useEffect, useCallback, lazy, Suspense } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Clock, MapPin, Calendar, RefreshCw, Route, Map as MapIcon } from 'lucide-react'
import { livelinkService } from '@/services/livelinkService'
import vehicleService from '@/services/vehicleService'
import type { Trip, TripList, TripPoint } from '@/types/trips'
import { useTimeFormat } from '@/hooks/useTimeFormat'
import { formatAPITimestamp, formatTime } from '@/utils/parseAPITimestamp'
import { formatUnverifiedValue } from '@/utils/telemetryUnits'
import { Card, Toggle, Mono, EmptyState } from '../ui'

// Lazy-load map component — keeps Leaflet's ~150KB out of the main bundle
const TripRouteMap = lazy(() => import('@/components/maps/TripRouteMap'))

interface LiveLinkTripsTabProps {
  vin: string
}

export default function LiveLinkTripsTab({ vin }: LiveLinkTripsTabProps) {
  const { t } = useTranslation('vehicles')
  const [trips, setTrips] = useState<TripList | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedTripId, setSelectedTripId] = useState<number | null>(null)
  const [tripPoints, setTripPoints] = useState<TripPoint[]>([])
  const [pointsLoading, setPointsLoading] = useState(false)
  const [locationTrackingEnabled, setLocationTrackingEnabled] = useState<boolean | null>(null)
  const [trackingSaving, setTrackingSaving] = useState(false)

  const fetchTrips = useCallback(async () => {
    setLoading(true)
    try {
      const data = await livelinkService.getTrips(vin, { limit: 50 })
      setTrips(data)
    } catch (err) {
      console.error('Failed to fetch trips:', err)
      toast.error(t('livelink.trips.loadError'))
    } finally {
      setLoading(false)
    }
  }, [vin, t])

  const fetchLocationTrackingState = useCallback(async () => {
    try {
      const vehicle = await vehicleService.get(vin)
      setLocationTrackingEnabled(vehicle.location_tracking_enabled)
    } catch (err) {
      console.error('Failed to fetch location-tracking state:', err)
    }
  }, [vin])

  useEffect(() => {
    fetchTrips()
    fetchLocationTrackingState()
  }, [fetchTrips, fetchLocationTrackingState])

  const fetchTripPoints = useCallback(
    async (sessionId: number) => {
      setPointsLoading(true)
      try {
        const data = await livelinkService.getTripPoints(vin, sessionId)
        setTripPoints(data.points ?? [])
      } catch (err) {
        console.error('Failed to fetch trip points:', err)
        toast.error(t('livelink.trips.mapLoadError'))
        setTripPoints([])
      } finally {
        setPointsLoading(false)
      }
    },
    [vin, t],
  )

  useEffect(() => {
    if (selectedTripId != null) {
      fetchTripPoints(selectedTripId)
    } else {
      setTripPoints([])
    }
  }, [selectedTripId, fetchTripPoints])

  const handleToggleLocationTracking = async (): Promise<void> => {
    if (locationTrackingEnabled === null || trackingSaving) return
    const next = !locationTrackingEnabled
    setTrackingSaving(true)
    try {
      const result = await livelinkService.setLocationTracking(vin, next)
      setLocationTrackingEnabled(result.location_tracking_enabled)
      toast.success(
        result.location_tracking_enabled
          ? t('livelink.trips.locationTrackingEnabled')
          : t('livelink.trips.locationTrackingDisabled'),
      )
    } catch (err) {
      console.error('Failed to update location tracking:', err)
      toast.error(t('livelink.trips.locationTrackingError'))
    } finally {
      setTrackingSaving(false)
    }
  }

  const formatDuration = (seconds: number | null | undefined): string => {
    if (seconds == null) return '--'
    const hours = Math.floor(seconds / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    if (hours > 0) return `${hours}h ${minutes}m`
    return `${minutes}m`
  }

  // ★ `Trip.distance_km` is `DriveSession.distance_km` verbatim
  // (`location_service.py::get_trips` selects that column), so it carries the
  // custom-PID ambiguity `LiveLinkSessionsTab` documents: the odometer delta
  // wins over the GPS haversine whenever an odometer reading exists, and the
  // PIDs it is read from are the ones that "may already be in the user's
  // unit". Sending it through `UnitFormatter.formatDistance` treated it as
  // canonical kilometres and converted an already-mile delta a SECOND time for
  // an imperial client, while the Sessions tab merely relabelled the same
  // number. Three consumers of one column held three different beliefs about
  // it; this removes one rather than adding a fourth.
  const formatDistance = (km: number | null | undefined): string =>
    formatUnverifiedValue(km, t)

  const toggleSelected = (sessionId: number): void => {
    setSelectedTripId(selectedTripId === sessionId ? null : sessionId)
  }

  const header = (
    <div className="flex items-center justify-between gap-4">
      <span className="text-sm text-text-mute">
        {trips ? t('livelink.trips.tripCount', { count: trips.trips?.length ?? 0 }) : ''}
      </span>
      <Toggle
        label={t('livelink.trips.locationTracking')}
        checked={locationTrackingEnabled ?? false}
        onChange={handleToggleLocationTracking}
        disabled={locationTrackingEnabled === null || trackingSaving}
      />
    </div>
  )

  if (loading) {
    return (
      <div className="space-y-4">
        {header}
        <div className="flex items-center justify-center py-12">
          <RefreshCw aria-hidden="true" className="w-8 h-8 text-text-mute animate-spin" />
        </div>
      </div>
    )
  }

  const tripList = trips?.trips ?? []

  if (tripList.length === 0) {
    return (
      <div className="space-y-4">
        {header}
        <EmptyState icon={Route} title={t('livelink.trips.noRecords')} description={t('livelink.trips.autoDetected')} />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {header}

      {/* Trip List */}
      <div className="space-y-3">
        {tripList.map((trip) => (
          <TripCard
            key={trip.session_id}
            trip={trip}
            isSelected={selectedTripId === trip.session_id}
            onSelect={() => toggleSelected(trip.session_id)}
            formatDuration={formatDuration}
            formatDistance={formatDistance}
          />
        ))}
      </div>

      {/* Route map — selected trip's GPS polyline */}
      {selectedTripId != null && (
        <Card padding="sm">
          {pointsLoading ? (
            <div className="flex items-center justify-center py-12">
              <RefreshCw aria-hidden="true" className="w-8 h-8 text-text-mute animate-spin" />
            </div>
          ) : tripPoints.length === 0 ? (
            <EmptyState icon={MapIcon} size="sm" title={t('livelink.trips.mapEmpty')} />
          ) : (
            <Suspense fallback={<div className="h-[400px] bg-surface-2 rounded-card animate-pulse" />}>
              <TripRouteMap points={tripPoints} />
            </Suspense>
          )}
        </Card>
      )}
    </div>
  )
}

// Trip Card Component
function TripCard({
  trip,
  isSelected,
  onSelect,
  formatDuration,
  formatDistance,
}: {
  trip: Trip
  isSelected: boolean
  onSelect: () => void
  formatDuration: (s: number | null | undefined) => string
  formatDistance: (km: number | null | undefined) => string
}) {
  const { t } = useTranslation('vehicles')
  const { timeFormat } = useTimeFormat()

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={isSelected}
      className={`w-full text-left bg-surface rounded-card border p-4 ui-motion hover:bg-surface-2/50 ${
        isSelected ? 'border-(--accent-line)' : 'border-border'
      }`}
    >
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <Calendar aria-hidden="true" className="w-5 h-5 text-text-mute" />
          <div>
            <div className="text-text font-medium">
              {formatAPITimestamp(trip.started_at, (d) =>
                d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }),
              )}
            </div>
            <div className="text-xs text-text-mute">
              {formatTime(trip.started_at, timeFormat)}
              {trip.ended_at && (
                <>
                  {' → '}
                  {formatTime(trip.ended_at, timeFormat)}
                </>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-6 text-sm text-text-mute">
          <div className="flex items-center gap-1">
            <Clock aria-hidden="true" className="w-4 h-4" />
            <Mono size="sm">{formatDuration(trip.duration_seconds)}</Mono>
          </div>
          <div className="flex items-center gap-1">
            <MapPin aria-hidden="true" className="w-4 h-4" />
            <Mono size="sm">{formatDistance(trip.distance_km)}</Mono>
          </div>
          <div className="flex items-center gap-1">
            <Route aria-hidden="true" className="w-4 h-4" />
            <span>{t('livelink.trips.pointCount', { count: trip.point_count })}</span>
          </div>
        </div>
      </div>
    </button>
  )
}
