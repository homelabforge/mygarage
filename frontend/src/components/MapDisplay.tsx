import { lazy, Suspense } from 'react'

// Lazy-load map component
const LeafletMap = lazy(() => import('./maps/LeafletMap'))

interface POIResult {
  business_name: string
  latitude: number
  longitude: number
  poi_category: string
  rating?: number
  address?: string
  external_id?: string
}

interface Props {
  pois: POIResult[]
  userLocation: { lat: number; lng: number }
  searchRadius: number
  onMarkerClick: (poi: POIResult) => void
}

export default function MapDisplay({ pois, userLocation, searchRadius, onMarkerClick }: Props) {
  return (
    <div className="mb-6">
      <Suspense fallback={<div className="h-[400px] bg-zinc-800 rounded-lg animate-pulse" />}>
        <LeafletMap
          pois={pois}
          userLocation={userLocation}
          searchRadius={searchRadius}
          onMarkerClick={onMarkerClick}
        />
      </Suspense>
    </div>
  )
}
