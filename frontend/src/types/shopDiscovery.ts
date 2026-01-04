/**
 * Shop discovery types for TomTom/OSM integration.
 */

export interface PlaceResult {
  business_name: string
  address?: string
  city?: string
  state?: string
  zip_code?: string
  phone?: string
  latitude: number
  longitude: number
  source: 'tomtom' | 'osm'
  external_id?: string
  rating?: number
  distance_meters?: number
  category: string
  website?: string
}

export interface ShopSearchRequest {
  latitude: number
  longitude: number
  radius_meters?: number
}

export interface ShopSearchResponse {
  results: PlaceResult[]
  count: number
  source: string
  latitude: number
  longitude: number
  radius_meters: number
}

export interface ShopRecommendation {
  id: number
  business_name: string
  address?: string
  city?: string
  state?: string
  phone?: string
  usage_count: number
  rating?: number
  user_rating?: number
}

export interface ShopRecommendationsResponse {
  recommendations: ShopRecommendation[]
  count: number
}
