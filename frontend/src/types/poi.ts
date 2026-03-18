// ============================================================================
// Section A: Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

export type POIResult = components['schemas']['POIResult']
export type POISearchRequest = components['schemas']['POISearchRequest']
export type POISearchResponse = components['schemas']['POISearchResponse']
export type POIRecommendation = components['schemas']['POIRecommendation']
export type POIRecommendationsResponse = components['schemas']['POIRecommendationsResponse']
export type EVChargingMetadata = components['schemas']['EVChargingMetadata']

// ============================================================================
// Section B: Hand-maintained frontend-only types
// ============================================================================

// Derive POICategory from generated schema (POISearchRequest.categories element type)
export type POICategory = POISearchRequest['categories'][number]

// Backward compatibility: Re-export old types
export type PlaceResult = components['schemas']['PlaceResult']
export type ShopSearchRequest = components['schemas']['ShopSearchRequest']
export type ShopSearchResponse = components['schemas']['ShopSearchResponse']
export type ShopRecommendation = components['schemas']['ShopRecommendation']
export type ShopRecommendationsResponse = components['schemas']['ShopRecommendationsResponse']
