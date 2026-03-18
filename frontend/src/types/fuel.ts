// ============================================================================
// Section A: Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

export type FuelRecord = components['schemas']['FuelRecordResponse']
export type FuelRecordCreate = components['schemas']['FuelRecordCreate']
export type FuelRecordUpdate = components['schemas']['FuelRecordUpdate']
export type FuelRecordListResponse = components['schemas']['FuelRecordListResponse']

// ============================================================================
// Section B: Hand-maintained frontend-only types
// ============================================================================
// (none)
