import { lazy, Suspense } from 'react'

// Lazy-load map component
const LeafletMap = lazy(() => import('./maps/LeafletMap'))

interface POIResult {
  business_name: string
  latitude: number | string
  longitude: number | string
  poi_category: string
  rating?: number | string | null
  address?: string | null
  external_id?: string | null
}

interface Props {
  pois: POIResult[]
  userLocation: { lat: number; lng: number }
  /** The search radius in METRES. See LeafletMap for why it is not the user's own unit. */
  radiusMeters: number
  onMarkerClick: (poi: POIResult) => void
}

export default function MapDisplay({ pois, userLocation, radiusMeters, onMarkerClick }: Props) {
  return (
    <div className="mb-6">
      <Suspense fallback={<div className="h-[400px] bg-zinc-800 rounded-lg animate-pulse" />}>
        <LeafletMap
          pois={pois}
          userLocation={userLocation}
          radiusMeters={radiusMeters}
          onMarkerClick={onMarkerClick}
        />
      </Suspense>
    </div>
  )
}
