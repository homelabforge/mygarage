/**
 * Trip route map — draws a GPS breadcrumb polyline for a selected trip (Task 15).
 *
 * Shares the default-icon fix in leafletIcons.ts. Lazy-loaded by the
 * caller (React.lazy + Suspense) to keep Leaflet's ~150KB out of the main bundle.
 */
import { useEffect, type ReactElement } from 'react'
import { MapContainer, TileLayer, Marker, Polyline, Popup, useMap } from 'react-leaflet'
import type { LatLngBoundsExpression, LatLngTuple } from 'leaflet'
import 'leaflet/dist/leaflet.css'
import './leafletIcons'
import { useTranslation } from 'react-i18next'
import type { TripPoint } from '../../types/trips'

interface Props {
  points: TripPoint[]
}

const MAP_STYLE = { height: '400px', width: '100%', borderRadius: '8px' }

function FitBounds({ positions }: { positions: LatLngTuple[] }): null {
  const map = useMap()
  useEffect(() => {
    if (positions.length > 0) {
      map.fitBounds(positions as LatLngBoundsExpression, { padding: [24, 24] })
    }
  }, [map, positions])
  return null
}

export default function TripRouteMap({ points }: Props): ReactElement | null {
  const { t } = useTranslation('vehicles')

  if (points.length === 0) {
    return null
  }

  const positions: LatLngTuple[] = points.map((p) => [p.latitude, p.longitude])

  // Single point: no line to draw — render a centered marker only.
  if (points.length === 1) {
    return (
      <MapContainer center={positions[0]} zoom={15} style={MAP_STYLE}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <Marker position={positions[0]} />
      </MapContainer>
    )
  }

  const start = positions[0]
  const end = positions[positions.length - 1]

  return (
    <MapContainer center={start} zoom={13} style={MAP_STYLE}>
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <Polyline positions={positions} pathOptions={{ color: 'var(--accent)', weight: 4 }} />
      <Marker position={start}>
        <Popup>{t('livelink.trips.mapStart')}</Popup>
      </Marker>
      <Marker position={end}>
        <Popup>{t('livelink.trips.mapEnd')}</Popup>
      </Marker>
      <FitBounds positions={positions} />
    </MapContainer>
  )
}
