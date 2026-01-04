/**
 * ShopFinder Page
 *
 * Standalone page for discovering nearby auto repair shops using geolocation.
 * Users can search for shops and save them directly to their address book.
 */

import { useState, useEffect } from 'react'
import { MapPin, Loader2, Navigation, Star, Phone, Globe, Save, Check,  AlertTriangle } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/services/api'
import type { PlaceResult, ShopRecommendation, ShopSearchResponse, ShopRecommendationsResponse } from '@/types/shopDiscovery'

type Step = 'permission' | 'searching' | 'results'

export default function ShopFinder() {
  const [step, setStep] = useState<Step>('permission')
  const [recommendations, setRecommendations] = useState<ShopRecommendation[]>([])
  const [searchResults, setSearchResults] = useState<PlaceResult[]>([])
  const [searchSource, setSearchSource] = useState<string>('')
  const [error, setError] = useState<string>('')
  const [savedShops, setSavedShops] = useState<Set<string>>(new Set())

  // Search options
  const [searchRadius, setSearchRadius] = useState<number>(5) // miles
  const [shopType, setShopType] = useState<'auto' | 'rv'>('auto')

  // Load recommendations on mount
  useEffect(() => {
    loadRecommendations()
  }, [])

  const loadRecommendations = async () => {
    try {
      const response = await api.get<ShopRecommendationsResponse>('/shop-discovery/recommendations?limit=5')
      setRecommendations(response.data.recommendations)
    } catch (err) {
      console.error('Failed to load recommendations:', err)
      // Don't show error toast - recommendations are optional
    }
  }

  const calculateDistance = (lat1: number, lon1: number, lat2: number, lon2: number): number => {
    // Haversine formula for distance in meters
    const R = 6371e3 // Earth radius in meters
    const φ1 = (lat1 * Math.PI) / 180
    const φ2 = (lat2 * Math.PI) / 180
    const Δφ = ((lat2 - lat1) * Math.PI) / 180
    const Δλ = ((lon2 - lon1) * Math.PI) / 180

    const a = Math.sin(Δφ / 2) * Math.sin(Δφ / 2) +
              Math.cos(φ1) * Math.cos(φ2) *
              Math.sin(Δλ / 2) * Math.sin(Δλ / 2)
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))

    return R * c
  }

  const formatDistance = (meters?: number): string => {
    if (!meters) return 'Distance unknown'
    const miles = meters * 0.000621371
    return `${miles.toFixed(1)} mi`
  }

  const handleRequestLocation = () => {
    setStep('searching')
    setError('')

    if (!navigator.geolocation) {
      setError('Geolocation is not supported by your browser')
      setStep('permission')
      return
    }

    navigator.geolocation.getCurrentPosition(
      async (position) => {
        await searchNearbyShops(position.coords.latitude, position.coords.longitude)
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

  const searchNearbyShops = async (latitude: number, longitude: number) => {
    try {
      // Convert miles to meters
      const radiusMeters = Math.round(searchRadius * 1609.34)

      const response = await api.post<ShopSearchResponse>('/shop-discovery/search', {
        latitude,
        longitude,
        radius_meters: radiusMeters,
        shop_type: shopType,
      })

      // Calculate distances for all results
      const resultsWithDistance = response.data.results.map((shop) => ({
        ...shop,
        distance_meters: calculateDistance(latitude, longitude, shop.latitude, shop.longitude),
      }))

      // Sort by distance
      resultsWithDistance.sort((a, b) => (a.distance_meters || 0) - (b.distance_meters || 0))

      setSearchResults(resultsWithDistance)
      setSearchSource(response.data.source)
      setStep('results')
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
      const errorMessage = typeof detail === 'string' ? detail : 'Failed to search for shops'
      setError(errorMessage)
      toast.error(errorMessage)
      setStep('permission')
    }
  }

  const handleSaveShop = async (shop: PlaceResult) => {
    try {
      await api.post('/shop-discovery/save', {
        business_name: shop.business_name,
        address: shop.address,
        city: shop.city,
        state: shop.state,
        zip_code: shop.zip_code,
        phone: shop.phone,
        latitude: shop.latitude.toString(),
        longitude: shop.longitude.toString(),
        category: 'service',
        source: shop.source,
        external_id: shop.external_id,
        rating: shop.rating,
        website: shop.website,
      })

      setSavedShops((prev) => new Set(prev).add(shop.external_id || shop.business_name))
      toast.success(`${shop.business_name} saved to address book!`)

      // Refresh recommendations after saving
      loadRecommendations()
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
      toast.error(typeof detail === 'string' ? detail : 'Failed to save shop')
    }
  }

  return (
    <div className="max-w-4xl mx-auto p-6">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-2">
          <div className="p-3 bg-primary/10 rounded-full">
            <MapPin className="w-8 h-8 text-primary" />
          </div>
          <div>
            <h1 className="text-3xl font-bold text-garage-text">Find Nearby Shops</h1>
            <p className="text-garage-text-muted">
              Discover auto repair shops near your location and save them to your address book
            </p>
          </div>
        </div>
      </div>

      {/* Step 1: Permission Request */}
      {step === 'permission' && (
        <>
          {/* Search Options */}
          <div className="mb-8 bg-garage-surface border border-garage-border rounded-lg p-6">
            <h2 className="text-lg font-semibold text-garage-text mb-4">Search Options</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Search Radius */}
              <div>
                <label htmlFor="search_radius" className="block text-sm font-medium text-garage-text mb-2">
                  Search Radius
                </label>
                <select
                  id="search_radius"
                  value={searchRadius}
                  onChange={(e) => setSearchRadius(Number(e.target.value))}
                  className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
                >
                  <option value={5}>5 miles</option>
                  <option value={10}>10 miles</option>
                  <option value={25}>25 miles</option>
                  <option value={50}>50 miles</option>
                  <option value={100}>100 miles</option>
                </select>
              </div>

              {/* Shop Type */}
              <div>
                <label htmlFor="shop_type" className="block text-sm font-medium text-garage-text mb-2">
                  Shop Type
                </label>
                <select
                  id="shop_type"
                  value={shopType}
                  onChange={(e) => setShopType(e.target.value as 'auto' | 'rv')}
                  className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
                >
                  <option value="auto">Auto Repair</option>
                  <option value="rv">RV Repair</option>
                </select>
              </div>
            </div>
          </div>

          {/* Recommendations Section */}
          {recommendations.length > 0 && (
            <div className="mb-8">
              <h2 className="text-lg font-semibold text-garage-text mb-4">Previously Used Shops</h2>
              <div className="space-y-3">
                {recommendations.map((shop) => (
                  <div
                    key={shop.id}
                    className="p-4 bg-garage-surface border border-garage-border rounded-lg hover:border-primary/50 transition-colors"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1">
                        <h3 className="font-semibold text-garage-text">{shop.business_name}</h3>
                        {shop.address && (
                          <p className="text-sm text-garage-text-muted mt-1">
                            {shop.address}, {shop.city}, {shop.state}
                          </p>
                        )}
                        {shop.phone && (
                          <p className="text-sm text-garage-text-muted flex items-center gap-1 mt-1">
                            <Phone className="w-3 h-3" />
                            {shop.phone}
                          </p>
                        )}
                        <p className="text-xs text-garage-text-muted mt-2">
                          Used {shop.usage_count} time{shop.usage_count !== 1 ? 's' : ''}
                        </p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <div className="border-t border-garage-border mt-6 mb-6" />
            </div>
          )}

          {/* Geolocation Request */}
          <div className="bg-garage-surface border border-garage-border rounded-lg p-8">
            <div className="text-center space-y-6">
              <div className="flex justify-center">
                <div className="p-4 bg-primary/10 rounded-full">
                  <Navigation className="w-16 h-16 text-primary" />
                </div>
              </div>
              <div>
                <h2 className="text-xl font-semibold text-garage-text">Enable Location Access</h2>
                <p className="text-garage-text-muted mt-2 max-w-md mx-auto">
                  We need your location to find nearby {shopType === 'auto' ? 'auto repair' : 'RV repair'} shops within {searchRadius} mile{searchRadius !== 1 ? 's' : ''}.
                </p>
              </div>

              {error && (
                <div className="p-4 bg-danger/10 border border-danger/30 rounded-lg flex items-start gap-2 max-w-md mx-auto">
                  <AlertTriangle className="w-5 h-5 text-danger mt-0.5 flex-shrink-0" />
                  <p className="text-sm text-danger text-left">{error}</p>
                </div>
              )}

              <button
                onClick={handleRequestLocation}
                className="px-6 py-3 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors flex items-center gap-2 mx-auto"
              >
                <Navigation className="w-4 h-4" />
                Enable Location
              </button>

              <p className="text-xs text-garage-text-muted">
                Powered by TomTom Places & OpenStreetMap
              </p>
            </div>
          </div>
        </>
      )}

      {/* Step 2: Searching */}
      {step === 'searching' && (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-12">
          <div className="text-center space-y-4">
            <Loader2 className="w-16 h-16 text-primary animate-spin mx-auto" />
            <div>
              <h2 className="text-xl font-semibold text-garage-text">Searching for Shops...</h2>
              <p className="text-garage-text-muted mt-2">
                Finding nearby {shopType === 'auto' ? 'auto repair' : 'RV repair'} shops within {searchRadius} mile{searchRadius !== 1 ? 's' : ''}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Step 3: Results */}
      {step === 'results' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-xl font-semibold text-garage-text">
                Found {searchResults.length} shop{searchResults.length !== 1 ? 's' : ''}
              </h2>
              <p className="text-sm text-garage-text-muted mt-1">
                Source: {searchSource === 'tomtom' ? 'TomTom Places' : 'OpenStreetMap'}
              </p>
            </div>
            <button
              onClick={() => setStep('permission')}
              className="px-4 py-2 bg-primary/10 text-primary rounded-lg hover:bg-primary/20 transition-colors"
            >
              Search Again
            </button>
          </div>

          {searchResults.length === 0 ? (
            <div className="bg-garage-surface border border-garage-border rounded-lg p-12">
              <div className="text-center">
                <MapPin className="w-16 h-16 text-garage-text-muted mx-auto mb-4" />
                <h3 className="text-xl font-semibold text-garage-text">No Shops Found</h3>
                <p className="text-garage-text-muted mt-2">
                  Try searching from a different location or expanding your search radius.
                </p>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              {searchResults.map((shop, index) => {
                const shopKey = shop.external_id || shop.business_name
                const isSaved = savedShops.has(shopKey)

                return (
                  <div
                    key={index}
                    className="p-6 bg-garage-surface border border-garage-border rounded-lg hover:border-primary/50 transition-colors"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 space-y-3">
                        <div>
                          <h3 className="text-lg font-semibold text-garage-text">{shop.business_name}</h3>
                          <p className="text-sm text-garage-text-muted">
                            {formatDistance(shop.distance_meters)} away
                          </p>
                        </div>

                        {shop.address && (
                          <p className="text-sm text-garage-text-muted">
                            {shop.address}
                            {shop.city && `, ${shop.city}`}
                            {shop.state && `, ${shop.state}`}
                            {shop.zip_code && ` ${shop.zip_code}`}
                          </p>
                        )}

                        <div className="flex items-center gap-4 text-sm text-garage-text-muted">
                          {shop.phone && (
                            <span className="flex items-center gap-1">
                              <Phone className="w-4 h-4" />
                              {shop.phone}
                            </span>
                          )}
                          {shop.rating && (
                            <span className="flex items-center gap-1">
                              <Star className="w-4 h-4 fill-yellow-500 text-yellow-500" />
                              {shop.rating}
                            </span>
                          )}
                          {shop.website && (
                            <a
                              href={shop.website}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="flex items-center gap-1 text-primary hover:underline"
                            >
                              <Globe className="w-4 h-4" />
                              Website
                            </a>
                          )}
                        </div>
                      </div>

                      <button
                        onClick={() => handleSaveShop(shop)}
                        disabled={isSaved}
                        className={`px-4 py-2 rounded-lg transition-colors flex items-center gap-2 ${
                          isSaved
                            ? 'bg-success/20 text-success cursor-not-allowed'
                            : 'bg-primary text-white hover:bg-primary/90'
                        }`}
                        title={isSaved ? 'Saved to address book' : 'Save to address book'}
                      >
                        {isSaved ? (
                          <>
                            <Check className="w-4 h-4" />
                            Saved
                          </>
                        ) : (
                          <>
                            <Save className="w-4 h-4" />
                            Save to Address Book
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
