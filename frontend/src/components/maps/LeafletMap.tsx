import { MapContainer, TileLayer, Marker, Popup, Circle } from 'react-leaflet'
import { useTranslation } from 'react-i18next'
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
  /**
   * The search radius in METRES, which is what Leaflet's `Circle` takes.
   *
   * ★ This used to be the radius in MILES, multiplied here by a hardcoded
   * `1609.34` UNCONDITIONALLY, so a metric client who searched a 10 km radius
   * was drawn a 16.1 km circle. A map component cannot know which unit the
   * client chose, so the conversion belongs to the caller and this takes the
   * canonical map unit.
   */
  radiusMeters: number
  onMarkerClick: (poi: POIResult) => void
}

export default function LeafletMap({ pois, userLocation, radiusMeters, onMarkerClick }: Props) {
  const { t } = useTranslation('common')

  // POI-category colours (data-encoding, NOT UI semantics). Kept as a literal palette (G4(e) carve-out):
  // no POI-palette token exists in the P0 token layer, and the design forbids deriving category colours
  // from the status/accent tokens (§4.9) — mapping these distinct hues onto danger/warning/success/info
  // would collide (no purple token; propane vs gas both land on warning) and lose category legibility.
  const getCategoryColor = (category: string): string => {
    const colors: Record<string, string> = {
      auto_shop: '#3b82f6',     // blue
      rv_shop: '#a855f7',       // purple
      ev_charging: '#10b981',   // green
      gas_station: '#f59e0b',   // orange
      propane: '#eab308',       // yellow
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
        <Popup>{t('leafletMap.yourLocation')}</Popup>
      </Marker>

      {/* Search radius circle */}
      <Circle
        center={[userLocation.lat, userLocation.lng]}
        radius={radiusMeters}
        pathOptions={{ fillColor: 'var(--accent)', fillOpacity: 0.1, color: 'var(--accent)' }}
      />

      {/* POI markers */}
      {pois.map((poi, index) => (
        <Marker
          key={poi.external_id || index}
          position={[Number(poi.latitude), Number(poi.longitude)]}
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
