import { MapContainer, TileLayer, Marker, Popup, Circle } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

// Fix default icon issue with Leaflet + React
// eslint-disable-next-line @typescript-eslint/no-explicit-any
delete (L.Icon.Default.prototype as any)._getIconUrl
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
})

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
  searchRadius: number  // in miles
  onMarkerClick: (poi: POIResult) => void
}

export default function LeafletMap({ pois, userLocation, searchRadius, onMarkerClick }: Props) {
  const getCategoryColor = (category: string): string => {
    const colors: Record<string, string> = {
      auto_shop: '#3b82f6',     // blue
      rv_shop: '#a855f7',       // purple
      ev_charging: '#10b981',   // green
      fuel_station: '#f59e0b',  // orange
    }
    return colors[category] || '#6b7280'
  }

  const createMarkerIcon = (category: string) => {
    const color = getCategoryColor(category)
    return L.divIcon({
      className: 'custom-marker',
      html: `<div style="background-color: ${color}; width: 25px; height: 25px; border-radius: 50%; border: 2px solid white;"></div>`,
      iconSize: [25, 25],
    })
  }

  return (
    <MapContainer
      center={[userLocation.lat, userLocation.lng]}
      zoom={13}
      style={{ height: '400px', width: '100%', borderRadius: '8px' }}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />

      {/* User location marker */}
      <Marker position={[userLocation.lat, userLocation.lng]}>
        <Popup>Your location</Popup>
      </Marker>

      {/* Search radius circle */}
      <Circle
        center={[userLocation.lat, userLocation.lng]}
        radius={searchRadius * 1609.34}  // miles to meters
        pathOptions={{ fillColor: 'blue', fillOpacity: 0.1, color: 'blue' }}
      />

      {/* POI markers */}
      {pois.map((poi, index) => (
        <Marker
          key={poi.external_id || index}
          position={[poi.latitude, poi.longitude]}
          icon={createMarkerIcon(poi.poi_category)}
          eventHandlers={{
            click: () => onMarkerClick(poi),
          }}
        >
          <Popup>
            <div>
              <h3 className="font-semibold">{poi.business_name}</h3>
              <p className="text-sm">{poi.address}</p>
              {poi.rating && <p className="text-sm">★ {poi.rating}</p>}
            </div>
          </Popup>
        </Marker>
      ))}
    </MapContainer>
  )
}
