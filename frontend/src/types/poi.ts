/**
 * POI (Points of Interest) discovery types.
 */

export type POICategory = 'auto_shop' | 'rv_shop' | 'ev_charging' | 'gas_station' | 'propane'

export interface EVChargingMetadata {
  connector_types?: string[]
  charging_speeds?: string[]
  network?: string
  availability?: string
}

export interface POIResult {
  business_name: string
  address?: string
  city?: string
  state?: string
  zip_code?: string
  phone?: string
  latitude: number
  longitude: number
  source: string
  external_id?: string
  rating?: number
  distance_meters?: number
  website?: string
  poi_category: POICategory
  metadata?: EVChargingMetadata
}

export interface POISearchRequest {
  latitude: number
  longitude: number
  radius_meters?: number
  categories: POICategory[]
}

export interface POISearchResponse {
  results: POIResult[]
  count: number
  source: string
  latitude: number
  longitude: number
  radius_meters: number
}

export interface POIRecommendation {
  id: number
  business_name: string
  address?: string
  city?: string
  state?: string
  phone?: string
  usage_count: number
  rating?: number
  user_rating?: number
  poi_category?: POICategory
}

export interface POIRecommendationsResponse {
  recommendations: POIRecommendation[]
  count: number
}

// Backward compatibility: Re-export old types
export type PlaceResult = POIResult
export type ShopSearchRequest = POISearchRequest
export type ShopSearchResponse = POISearchResponse
export type ShopRecommendation = POIRecommendation
export type ShopRecommendationsResponse = POIRecommendationsResponse
