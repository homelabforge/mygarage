/**
 * ShopFinder Page
 *
 * Standalone page for discovering nearby auto repair shops using geolocation.
 * Users can search for shops and save them directly to their address book.
 */

import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { MapPin, Loader2, Navigation, Star, Phone, Globe, Save, Check,  AlertTriangle } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/services/api'
import { useUnitPreference } from '@/hooks/useUnitPreference'
import { UnitConverter, UnitFormatter } from '@/utils/units'
import type { PlaceResult, ShopRecommendation, ShopSearchResponse, ShopRecommendationsResponse } from '@/types/shopDiscovery'

type Step = 'permission' | 'searching' | 'results'

export default function ShopFinder() {
  const { t } = useTranslation('common')
  const { system } = useUnitPreference()
  const [step, setStep] = useState<Step>('permission')
  const [recommendations, setRecommendations] = useState<ShopRecommendation[]>([])
  const [searchResults, setSearchResults] = useState<PlaceResult[]>([])
  const [searchSource, setSearchSource] = useState<string>('')
  const [error, setError] = useState<string>('')
  const [savedShops, setSavedShops] = useState<Set<string>>(new Set())

  // Search options
  // Radius is held in the user's own unit and converted at request time.
  // Imperial users pick miles, metric users pick kilometres — hardcoding miles
  // showed "5 miles" to metric users and searched an imperial radius.
  const radiusOptions = system === 'metric' ? [10, 25, 50, 100, 150] : [5, 10, 25, 50, 100]
  // Unit symbol always comes from UnitFormatter — never hardcoded into a
  // translation value, which is how metric users used to be told "miles".
  const distanceUnit = UnitFormatter.getDistanceUnit(system)
  const [searchRadius, setSearchRadius] = useState<number>(system === 'metric' ? 25 : 5)
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
    if (!meters) return t('shopFinder.distanceUnknown')
    const km = meters / 1000
    const value = system === 'metric' ? km : (UnitConverter.kmToMiles(km) ?? 0)
    // One decimal, not UnitFormatter.formatDistance — that rounds to whole
    // units, which collapses every nearby shop to "0 mi".
    return `${value.toFixed(1)} ${UnitFormatter.getDistanceUnit(system)}`
  }

  const handleRequestLocation = () => {
    setStep('searching')
    setError('')

    if (!navigator.geolocation) {
      setError(t('shopFinder.geolocationUnsupported'))
      setStep('permission')
      return
    }

    navigator.geolocation.getCurrentPosition(
      async (position) => {
        await searchNearbyShops(position.coords.latitude, position.coords.longitude)
      },
      (err) => {
        let errorMessage = t('shopFinder.locationFailed')
        switch (err.code) {
          case err.PERMISSION_DENIED:
            errorMessage = t('shopFinder.locationDenied')
            break
          case err.POSITION_UNAVAILABLE:
            errorMessage = t('shopFinder.locationUnavailable')
            break
          case err.TIMEOUT:
            errorMessage = t('shopFinder.locationTimeout')
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
      const radiusMeters =
        system === 'metric'
          ? Math.round(searchRadius * 1000)
          : Math.round(searchRadius * 1609.34)

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
      const errorMessage = typeof detail === 'string' ? detail : t('shopFinder.searchFailed')
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
      // ``name`` is the provider-supplied business name — interpolated, never
      // passed through t() as a key.
      toast.success(t('shopFinder.savedToast', { name: shop.business_name }))

      // Refresh recommendations after saving
      loadRecommendations()
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
      toast.error(typeof detail === 'string' ? detail : t('shopFinder.saveFailed'))
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
            <h1 className="text-3xl font-bold text-garage-text">{t('shopFinder.title')}</h1>
            <p className="text-garage-text-muted">
              {t('shopFinder.subtitle')}
            </p>
          </div>
        </div>
      </div>

      {/* Step 1: Permission Request */}
      {step === 'permission' && (
        <>
          {/* Search Options */}
          <div className="mb-8 bg-garage-surface border border-garage-border rounded-lg p-6">
            <h2 className="text-lg font-semibold text-garage-text mb-4">{t('shopFinder.searchOptions')}</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Search Radius */}
              <div>
                <label htmlFor="search_radius" className="block text-sm font-medium text-garage-text mb-2">
                  {t('shopFinder.searchRadius')}
                </label>
                <select
                  id="search_radius"
                  value={radiusOptions.includes(searchRadius) ? searchRadius : radiusOptions[0]}
                  onChange={(e) => setSearchRadius(Number(e.target.value))}
                  className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
                >
                  {radiusOptions.map((r) => (
                    <option key={r} value={r}>
                      {r} {UnitFormatter.getDistanceUnit(system)}
                    </option>
                  ))}
                </select>
              </div>

              {/* Shop Type */}
              <div>
                <label htmlFor="shop_type" className="block text-sm font-medium text-garage-text mb-2">
                  {t('shopFinder.shopType')}
                </label>
                <select
                  id="shop_type"
                  value={shopType}
                  onChange={(e) => setShopType(e.target.value as 'auto' | 'rv')}
                  className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
                >
                  <option value="auto">{t('shopFinder.autoRepair')}</option>
                  <option value="rv">{t('shopFinder.rvRepair')}</option>
                </select>
              </div>
            </div>
          </div>

          {/* Recommendations Section */}
          {recommendations.length > 0 && (
            <div className="mb-8">
              <h2 className="text-lg font-semibold text-garage-text mb-4">{t('shopFinder.previouslyUsed')}</h2>
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
                          {t('shopFinder.usedTimes', { count: shop.usage_count })}
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
                <h2 className="text-xl font-semibold text-garage-text">{t('shopFinder.enableLocation')}</h2>
                <p className="text-garage-text-muted mt-2 max-w-md mx-auto">
                  {shopType === 'auto'
                    ? t('shopFinder.locationPromptAuto', { radius: searchRadius, unit: distanceUnit })
                    : t('shopFinder.locationPromptRv', { radius: searchRadius, unit: distanceUnit })}
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
                className="px-6 py-3 bg-primary text-(--accent-on-solid) rounded-lg hover:bg-primary/90 transition-colors flex items-center gap-2 mx-auto"
              >
                <Navigation className="w-4 h-4" />
                {t('shopFinder.enableLocationBtn')}
              </button>

              <p className="text-xs text-garage-text-muted">
                {/* Provider brand names are not translatable — i18n-exempt */}
                {t('shopFinder.poweredBy')} TomTom Places & OpenStreetMap
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
              <h2 className="text-xl font-semibold text-garage-text">{t('shopFinder.searching')}</h2>
              <p className="text-garage-text-muted mt-2">
                {shopType === 'auto'
                  ? t('shopFinder.searchingHintAuto', { radius: searchRadius, unit: distanceUnit })
                  : t('shopFinder.searchingHintRv', { radius: searchRadius, unit: distanceUnit })}
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
                {t('shopFinder.foundShops', { count: searchResults.length })}
              </h2>
              <p className="text-sm text-garage-text-muted mt-1">
                {t('shopFinder.source')}:{' '}
                {/* Provider brand names are not translatable — i18n-exempt */}
                {searchSource === 'tomtom' ? 'TomTom Places' : 'OpenStreetMap'}
              </p>
            </div>
            <button
              onClick={() => setStep('permission')}
              className="px-4 py-2 bg-primary/10 text-primary rounded-lg hover:bg-primary/20 transition-colors"
            >
              {t('shopFinder.searchAgain')}
            </button>
          </div>

          {searchResults.length === 0 ? (
            <div className="bg-garage-surface border border-garage-border rounded-lg p-12">
              <div className="text-center">
                <MapPin className="w-16 h-16 text-garage-text-muted mx-auto mb-4" />
                <h3 className="text-xl font-semibold text-garage-text">{t('shopFinder.noShopsFound')}</h3>
                <p className="text-garage-text-muted mt-2">
                  {t('shopFinder.noShopsHint')}
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
                            {t('shopFinder.distanceAway', {
                              distance: formatDistance(shop.distance_meters),
                            })}
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
                              {t('shopFinder.website')}
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
                            : 'bg-primary text-(--accent-on-solid) hover:bg-primary/90'
                        }`}
                        title={isSaved ? t('shopFinder.savedToAddressBook') : t('shopFinder.saveToAddressBook')}
                      >
                        {isSaved ? (
                          <>
                            <Check className="w-4 h-4" />
                            {t('shopFinder.saved')}
                          </>
                        ) : (
                          <>
                            <Save className="w-4 h-4" />
                            {t('shopFinder.saveToAddressBook')}
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
