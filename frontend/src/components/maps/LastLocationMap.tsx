/**
 * Last-known-location map — Overview "Last seen here" card mini-map showing
 * a single marker at the vehicle's most recent GPS point (Task 16).
 *
 * Shares the default-icon fix in leafletIcons.ts. Lazy-loaded by the
 * caller (React.lazy + Suspense) to keep Leaflet's ~150KB out of the main
 * bundle — same pattern as TripRouteMap.tsx (Task 15).
 */
import type { ReactElement } from 'react'
import { MapContainer, TileLayer, Marker } from 'react-leaflet'
import type { LatLngTuple } from 'leaflet'
import 'leaflet/dist/leaflet.css'
import './leafletIcons'

interface Props {
  latitude: number
  longitude: number
}

// Small fixed height — this is an Overview-tab mini-map (not the full-size
// trip route map), and it sits on the print/PDF surface where a fixed
// height + break-inside-avoid on the parent card keeps pagination sane.
const MAP_STYLE = { height: '220px', width: '100%', borderRadius: '8px' }

export default function LastLocationMap({ latitude, longitude }: Props): ReactElement {
  const position: LatLngTuple = [latitude, longitude]

  return (
    <MapContainer center={position} zoom={14} style={MAP_STYLE} scrollWheelZoom={false}>
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <Marker position={position} />
    </MapContainer>
  )
}
