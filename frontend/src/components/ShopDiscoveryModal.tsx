/**
 * ShopDiscoveryModal Component
 *
 * Three-step modal for discovering nearby auto repair shops:
 * 1. Permission: Request geolocation access
 * 2. Searching: Loading state while fetching shops
 * 3. Results: Display shops with Save/Select buttons
 *
 * Features:
 * - Geolocation permission flow
 * - Show previously used shops (recommendations)
 * - Display search results with distance calculation
 * - Save button → add to address book
 * - Select button → auto-populate ServiceRecordForm
 */

import { useState, useEffect } from 'react'
import { MapPin, Loader2, Navigation, Star, Phone, Save, Check, X, AlertTriangle } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/services/api'
import type { PlaceResult, ShopRecommendation, ShopSearchResponse, ShopRecommendationsResponse } from '@/types/shopDiscovery'

interface ShopDiscoveryModalProps {
  onClose: () => void
  onSelectShop: (shop: PlaceResult | ShopRecommendation) => void
}

type Step = 'permission' | 'searching' | 'results'

export default function ShopDiscoveryModal({ onClose, onSelectShop }: ShopDiscoveryModalProps) {
  const [step, setStep] = useState<Step>('permission')
  const [recommendations, setRecommendations] = useState<ShopRecommendation[]>([])
  const [searchResults, setSearchResults] = useState<PlaceResult[]>([])
  const [searchSource, setSearchSource] = useState<string>('')
  const [error, setError] = useState<string>('')
  const [savedShops, setSavedShops] = useState<Set<string>>(new Set())

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
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 0,
      }
    )
  }

  const searchNearbyShops = async (latitude: number, longitude: number) => {
    try {
      const response = await api.post<ShopSearchResponse>('/shop-discovery/search', {
        latitude,
        longitude,
        radius_meters: 8000, // ~5 miles
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
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
      toast.error(typeof detail === 'string' ? detail : 'Failed to save shop')
    }
  }

  const handleSelectShop = (shop: PlaceResult | ShopRecommendation) => {
    onSelectShop(shop)
    onClose()
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-garage-surface border border-garage-border rounded-lg max-w-3xl w-full max-h-[90vh] overflow-y-auto">
        <div className="p-6 space-y-4">
          {/* Header */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="p-3 bg-primary/10 rounded-full">
                <MapPin className="w-6 h-6 text-primary" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-garage-text">Find Nearby Shop</h2>
                <p className="text-sm text-garage-text-muted">
                  Discover auto repair shops near your location
                </p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-2 hover:bg-garage-bg rounded-lg transition-colors"
              aria-label="Close"
            >
              <X className="w-5 h-5 text-garage-text-muted" />
            </button>
          </div>

          {/* Step 1: Permission Request */}
          {step === 'permission' && (
            <>
              {/* Recommendations Section */}
              {recommendations.length > 0 && (
                <div className="space-y-3">
                  <h3 className="text-sm font-semibold text-garage-text">Previously Used Shops</h3>
                  <div className="space-y-2">
                    {recommendations.map((shop) => (
                      <div
                        key={shop.id}
                        className="p-4 bg-garage-bg border border-garage-border rounded-lg hover:border-primary/50 transition-colors"
                      >
                        <div className="flex items-start justify-between gap-4">
                          <div className="flex-1">
                            <h4 className="font-semibold text-garage-text">{shop.business_name}</h4>
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
                          <button
                            onClick={() => handleSelectShop(shop)}
                            className="px-3 py-1.5 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors text-sm whitespace-nowrap"
                          >
                            Select
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="border-t border-garage-border pt-4" />
                </div>
              )}

              {/* Geolocation Request */}
              <div className="text-center space-y-4 py-8">
                <div className="flex justify-center">
                  <div className="p-4 bg-primary/10 rounded-full">
                    <Navigation className="w-12 h-12 text-primary" />
                  </div>
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-garage-text">Enable Location Access</h3>
                  <p className="text-sm text-garage-text-muted mt-2">
                    We need your location to find nearby auto repair shops within 5 miles.
                  </p>
                </div>

                {error && (
                  <div className="p-3 bg-danger/10 border border-danger/30 rounded-lg flex items-start gap-2">
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
            </>
          )}

          {/* Step 2: Searching */}
          {step === 'searching' && (
            <div className="text-center space-y-4 py-12">
              <Loader2 className="w-12 h-12 text-primary animate-spin mx-auto" />
              <div>
                <h3 className="text-lg font-semibold text-garage-text">Searching for Shops...</h3>
                <p className="text-sm text-garage-text-muted mt-2">
                  Finding nearby auto repair shops within 5 miles
                </p>
              </div>
            </div>
          )}

          {/* Step 3: Results */}
          {step === 'results' && (
            <>
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-semibold text-garage-text">
                    Found {searchResults.length} shop{searchResults.length !== 1 ? 's' : ''}
                  </h3>
                  <p className="text-xs text-garage-text-muted mt-1">
                    Source: {searchSource === 'tomtom' ? 'TomTom Places' : 'OpenStreetMap'}
                  </p>
                </div>
                <button
                  onClick={() => setStep('permission')}
                  className="text-sm text-primary hover:underline"
                >
                  Search Again
                </button>
              </div>

              {searchResults.length === 0 ? (
                <div className="text-center py-12">
                  <MapPin className="w-12 h-12 text-garage-text-muted mx-auto mb-4" />
                  <h3 className="text-lg font-semibold text-garage-text">No Shops Found</h3>
                  <p className="text-sm text-garage-text-muted mt-2">
                    Try searching from a different location or expanding your search radius.
                  </p>
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-3 max-h-96 overflow-y-auto">
                  {searchResults.map((shop, index) => {
                    const shopKey = shop.external_id || shop.business_name
                    const isSaved = savedShops.has(shopKey)

                    return (
                      <div
                        key={index}
                        className="p-3 bg-garage-bg border border-garage-border rounded-lg hover:border-primary/50 transition-colors"
                      >
                        <div className="space-y-2">
                          <div className="flex items-start justify-between gap-2">
                            <div className="flex-1 min-w-0">
                              <h4 className="font-semibold text-sm text-garage-text truncate">{shop.business_name}</h4>
                              <p className="text-xs text-garage-text-muted">
                                {formatDistance(shop.distance_meters)} away
                              </p>
                            </div>
                            <button
                              onClick={() => handleSaveShop(shop)}
                              disabled={isSaved}
                              className={`p-1.5 rounded transition-colors flex-shrink-0 ${
                                isSaved
                                  ? 'bg-success/20 text-success cursor-not-allowed'
                                  : 'bg-garage-surface border border-garage-border hover:bg-primary/10 text-garage-text'
                              }`}
                              title={isSaved ? 'Saved' : 'Save to address book'}
                            >
                              {isSaved ? (
                                <Check className="w-3.5 h-3.5" />
                              ) : (
                                <Save className="w-3.5 h-3.5" />
                              )}
                            </button>
                          </div>

                          {shop.address && (
                            <p className="text-xs text-garage-text-muted line-clamp-2">
                              {shop.address}
                              {shop.city && `, ${shop.city}`}
                              {shop.state && `, ${shop.state}`}
                            </p>
                          )}

                          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-garage-text-muted">
                            {shop.phone && (
                              <span className="flex items-center gap-1">
                                <Phone className="w-3 h-3" />
                                <span className="truncate">{shop.phone}</span>
                              </span>
                            )}
                            {shop.rating && (
                              <span className="flex items-center gap-1">
                                <Star className="w-3 h-3 fill-yellow-500 text-yellow-500" />
                                {shop.rating}
                              </span>
                            )}
                          </div>

                          <button
                            onClick={() => handleSelectShop(shop)}
                            className="w-full px-3 py-1.5 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors text-sm"
                          >
                            Select
                          </button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </>
          )}

          {/* Cancel Button (always shown except during search) */}
          {step !== 'searching' && (
            <div className="flex justify-end pt-2 border-t border-garage-border">
              <button
                onClick={onClose}
                className="px-4 py-2 bg-garage-bg border border-garage-border text-garage-text rounded-lg hover:bg-garage-surface transition-colors"
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
