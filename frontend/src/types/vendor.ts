// ============================================================================
// Section A: Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

export type Vendor = components['schemas']['VendorResponse']
export type VendorCreate = components['schemas']['VendorCreate']
export type VendorUpdate = components['schemas']['VendorUpdate']
export type VendorListResponse = components['schemas']['VendorListResponse']
