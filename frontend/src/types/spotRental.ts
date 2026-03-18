// ============================================================================
// Section A: Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

export type SpotRental = components['schemas']['SpotRentalResponse']
export type SpotRentalCreate = components['schemas']['SpotRentalCreate']
export type SpotRentalUpdate = components['schemas']['SpotRentalUpdate']
export type SpotRentalListResponse = components['schemas']['SpotRentalListResponse']

export type SpotRentalBilling = components['schemas']['SpotRentalBillingResponse']
export type SpotRentalBillingCreate = components['schemas']['SpotRentalBillingCreate']
export type SpotRentalBillingUpdate = components['schemas']['SpotRentalBillingUpdate']
export type SpotRentalBillingListResponse = components['schemas']['SpotRentalBillingListResponse']

// ============================================================================
// Section B: Hand-maintained frontend-only types
// ============================================================================
// (none)
