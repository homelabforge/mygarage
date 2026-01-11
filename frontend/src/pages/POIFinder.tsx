/**
 * POIFinder Page
 *
 * Discover nearby Points of Interest using geolocation.
 * Supports multiple POI categories: Auto/RV Shops, EV Charging, Fuel Stations.
 */

import { useState, useEffect } from 'react'
import { MapPin, Loader2, Navigation, AlertTriangle } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/services/api'
import CategoryToggle from '@/components/CategoryToggle'
import POICard from '@/components/POICard'
import MapDisplay from '@/components/MapDisplay'
import type {
  POIResult,
  POIRecommendation,
  POISearchResponse,
  POIRecommendationsResponse,
  POICategory,
} from '@/types/poi'

type Step = 'permission' | 'searching' | 'results'

export default function POIFinder() {
  const [step, setStep] = useState<Step>('permission')
  const [recommendations, setRecommendations] = useState<POIRecommendation[]>([])
  const [searchResults, setSearchResults] = useState<POIResult[]>([])
  const [searchSource, setSearchSource] = useState<string>('')
  const [error, setError] = useState<string>('')
  const [savedPOIs, setSavedPOIs] = useState<Set<string>>(new Set())
  const [userLocation, setUserLocation] = useState<{ lat: number; lng: number } | null>(null)

  // Search options - category toggles
  const [searchRadius, setSearchRadius] = useState<number>(5) // miles
  const [categories, setCategories] = useState<Record<POICategory, boolean>>({
    auto_shop: true,
    rv_shop: false,
    ev_charging: false,
    gas_station: false,
    propane: false,
  })

  // Load recommendations on mount
  useEffect(() => {
    loadRecommendations()
  }, [])

  const loadRecommendations = async () => {
    try {
      const response = await api.get<POIRecommendationsResponse>('/poi/recommendations?limit=5')
      setRecommendations(response.data.recommendations)
    } catch (err) {
      console.error('Failed to load recommendations:', err)
    }
  }

  const handleCategoryToggle = (category: POICategory, enabled: boolean) => {
    setCategories((prev) => ({ ...prev, [category]: enabled }))
  }

  const getActiveCategories = (): POICategory[] => {
    return Object.entries(categories)
      .filter(([_, enabled]) => enabled)
      .map(([category]) => category as POICategory)
  }

  const calculateDistance = (lat1: number, lon1: number, lat2: number, lon2: number): number => {
    // Haversine formula for distance in meters
    const R = 6371e3
    const φ1 = (lat1 * Math.PI) / 180
    const φ2 = (lat2 * Math.PI) / 180
    const Δφ = ((lat2 - lat1) * Math.PI) / 180
    const Δλ = ((lon2 - lon1) * Math.PI) / 180

    const a =
      Math.sin(Δφ / 2) * Math.sin(Δφ / 2) +
      Math.cos(φ1) * Math.cos(φ2) * Math.sin(Δλ / 2) * Math.sin(Δλ / 2)
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))

    return R * c
  }

  const handleRequestLocation = () => {
    const activeCategories = getActiveCategories()
    if (activeCategories.length === 0) {
      toast.error('Please enable at least one category')
      return
    }

    setStep('searching')
    setError('')

    if (!navigator.geolocation) {
      setError('Geolocation is not supported by your browser')
      setStep('permission')
      return
    }

    navigator.geolocation.getCurrentPosition(
      async (position) => {
        await searchNearbyPOIs(position.coords.latitude, position.coords.longitude)
      },
      (err) => {
        let errorMessage = 'Failed to get your location'
        switch (err.code) {
          case err.PERMISSION_DENIED:
            errorMessage = 'Location permission denied. Please enable location access in your browser settings.'
            break
          case err.POSITION_UNAVAILABLE:
            errorMessage = 'Location information is unavailable.'
            break
          case err.TIMEOUT:
            errorMessage = 'Location request timed out.'
            break
        }
        setError(errorMessage)
        setStep('permission')
        toast.error(errorMessage)
      },
      {
        enableHighAccuracy: false,
        timeout: 30000,
        maximumAge: 300000,
      }
    )
  }

  const searchNearbyPOIs = async (latitude: number, longitude: number) => {
    // Save user location for map
    setUserLocation({ lat: latitude, lng: longitude })

    try {
      const radiusMeters = Math.round(searchRadius * 1609.34)
      const activeCategories = getActiveCategories()

      const response = await api.post<POISearchResponse>('/poi/search', {
        latitude,
        longitude,
        radius_meters: radiusMeters,
        categories: activeCategories,
      })

      // Calculate distances for results without distance_meters
      const resultsWithDistance = response.data.results.map((poi) => ({
        ...poi,
        distance_meters:
          poi.distance_meters || calculateDistance(latitude, longitude, poi.latitude, poi.longitude),
      }))

      resultsWithDistance.sort((a, b) => (a.distance_meters || 0) - (b.distance_meters || 0))

      setSearchResults(resultsWithDistance)
      setSearchSource(response.data.source)
      setStep('results')
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
      const errorMessage = typeof detail === 'string' ? detail : 'Failed to search for POIs'
      setError(errorMessage)
      toast.error(errorMessage)
      setStep('permission')
    }
  }

  const handleSavePOI = async (poi: POIResult) => {
    try {
      await api.post('/poi/save', {
        business_name: poi.business_name,
        address: poi.address,
        city: poi.city,
        state: poi.state,
        zip_code: poi.zip_code,
        phone: poi.phone,
        latitude: poi.latitude.toString(),
        longitude: poi.longitude.toString(),
        category: 'service',
        source: poi.source,
        external_id: poi.external_id,
        rating: poi.rating,
        website: poi.website,
        poi_category: poi.poi_category,
        poi_metadata: poi.metadata ? JSON.stringify(poi.metadata) : undefined,
      })

      setSavedPOIs((prev) => new Set(prev).add(poi.external_id || poi.business_name))
      toast.success(`${poi.business_name} saved to address book!`)

      loadRecommendations()
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
      toast.error(typeof detail === 'string' ? detail : 'Failed to save POI')
    }
  }

  return (
    <div className="max-w-6xl mx-auto p-6">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-2">
          <div className="p-3 bg-primary/10 rounded-full">
            <MapPin className="w-8 h-8 text-primary" />
          </div>
          <div>
            <h1 className="text-3xl font-bold text-garage-text">Find POI (Points of Interest)</h1>
            <p className="text-garage-text-muted">
              Discover nearby locations and save them to your address book
            </p>
          </div>
        </div>
      </div>

      {/* Step 1: Permission Request */}
      {step === 'permission' && (
        <>
          {/* Category Toggles */}
          <div className="mb-8 bg-garage-surface border border-garage-border rounded-lg p-6">
            <h2 className="text-lg font-semibold text-garage-text mb-4">POI Categories</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <CategoryToggle
                label="Auto Shops"
                category="auto_shop"
                enabled={categories.auto_shop}
                onToggle={(enabled) => handleCategoryToggle('auto_shop', enabled)}
              />
              <CategoryToggle
                label="EV Charging"
                category="ev_charging"
                enabled={categories.ev_charging}
                onToggle={(enabled) => handleCategoryToggle('ev_charging', enabled)}
              />
              <CategoryToggle
                label="Gas Stations"
                category="gas_station"
                enabled={categories.gas_station}
                onToggle={(enabled) => handleCategoryToggle('gas_station', enabled)}
              />
              <CategoryToggle
                label="Propane"
                category="propane"
                enabled={categories.propane}
                onToggle={(enabled) => handleCategoryToggle('propane', enabled)}
              />
              <CategoryToggle
                label="RV Shops"
                category="rv_shop"
                enabled={categories.rv_shop}
                onToggle={(enabled) => handleCategoryToggle('rv_shop', enabled)}
              />
            </div>

            {/* Search Radius */}
            <div className="mt-6">
              <label htmlFor="search_radius" className="block text-sm font-medium text-garage-text mb-2">
                Search Radius
              </label>
              <select
                id="search_radius"
                value={searchRadius}
                onChange={(e) => setSearchRadius(Number(e.target.value))}
                className="w-full md:w-64 px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
              >
                <option value={5}>5 miles</option>
                <option value={10}>10 miles</option>
                <option value={25}>25 miles</option>
                <option value={50}>50 miles</option>
                <option value={100}>100 miles</option>
              </select>
            </div>
          </div>

          {/* Recommendations */}
          {recommendations.length > 0 && (
            <div className="mb-8">
              <h2 className="text-lg font-semibold text-garage-text mb-4">Recently Used</h2>
              <div className="space-y-3">
                {recommendations.map((poi) => (
                  <div
                    key={poi.id}
                    className="p-4 bg-garage-surface border border-garage-border rounded-lg hover:border-primary/50 transition-colors"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1">
                        <h3 className="font-semibold text-garage-text">{poi.business_name}</h3>
                        {poi.address && (
                          <p className="text-sm text-garage-text-muted mt-1">
                            {poi.address}, {poi.city}, {poi.state}
                          </p>
                        )}
                      </div>
                      <span className="text-sm text-garage-text-muted whitespace-nowrap">
                        Used {poi.usage_count} {poi.usage_count === 1 ? 'time' : 'times'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Location Request Card */}
          <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
            <button
              type="button"
              onClick={handleRequestLocation}
              className="w-full px-6 py-3 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors flex items-center justify-center gap-2 font-medium"
            >
              <Navigation className="w-5 h-5" />
              Use My Location
            </button>
            {error && (
              <div className="mt-4 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg flex items-start gap-3">
                <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
                <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
              </div>
            )}
          </div>
        </>
      )}

      {/* Step 2: Searching */}
      {step === 'searching' && (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-12 text-center">
          <Loader2 className="w-12 h-12 text-primary animate-spin mx-auto mb-4" />
          <p className="text-lg text-garage-text">Searching for nearby POIs...</p>
          <p className="text-sm text-garage-text-muted mt-2">
            This may take a few seconds
          </p>
        </div>
      )}

      {/* Step 3: Results */}
      {step === 'results' && (
        <>
          {/* Results Header */}
          <div className="mb-6 flex items-center justify-between">
            <div>
              <h2 className="text-2xl font-bold text-garage-text">
                Found {searchResults.length} POI{searchResults.length !== 1 ? 's' : ''}
              </h2>
              <p className="text-sm text-garage-text-muted mt-1">
                Source: {searchSource === 'tomtom' ? 'TomTom' : searchSource === 'osm' ? 'OpenStreetMap' : searchSource}
              </p>
            </div>
            <button
              type="button"
              onClick={() => setStep('permission')}
              className="px-4 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text hover:bg-garage-surface transition-colors"
            >
              New Search
            </button>
          </div>

          {/* Map Display */}
          {userLocation && searchResults.length > 0 && (
            <MapDisplay
              pois={searchResults}
              userLocation={userLocation}
              searchRadius={searchRadius}
              onMarkerClick={(poi) => {
                const cardElement = document.getElementById(`poi-card-${poi.external_id || poi.business_name}`)
                if (cardElement) {
                  cardElement.scrollIntoView({ behavior: 'smooth', block: 'center' })
                  cardElement.classList.add('ring-2', 'ring-blue-500')
                  setTimeout(() => {
                    cardElement.classList.remove('ring-2', 'ring-blue-500')
                  }, 2000)
                }
              }}
            />
          )}

          {/* Results Grid (2 columns) */}
          {searchResults.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {searchResults.map((poi, index) => (
                <POICard
                  key={poi.external_id || `${poi.business_name}-${index}`}
                  poi={poi}
                  onSave={handleSavePOI}
                  isSaved={savedPOIs.has(poi.external_id || poi.business_name)}
                />
              ))}
            </div>
          ) : (
            <div className="bg-garage-surface border border-garage-border rounded-lg p-12 text-center">
              <MapPin className="w-12 h-12 text-garage-text-muted mx-auto mb-4" />
              <p className="text-lg text-garage-text">No POIs found in this area</p>
              <p className="text-sm text-garage-text-muted mt-2">
                Try increasing the search radius or selecting different categories
              </p>
            </div>
          )}
        </>
      )}
    </div>
  )
}
