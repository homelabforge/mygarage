// ============================================================================
// Section A: Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

export type TaxRecord = components['schemas']['TaxRecordResponse']
export type TaxRecordCreate = components['schemas']['TaxRecordCreate']
export type TaxRecordUpdate = components['schemas']['TaxRecordUpdate']
export type TaxRecordListResponse = components['schemas']['TaxRecordListResponse']

// ============================================================================
// Section B: Hand-maintained frontend-only types
// ============================================================================

// Backend uses Literal["Registration", "Inspection", "Property Tax", "Tolls"]
// which generates the correct union — re-export for backward compat
export type TaxType = NonNullable<TaxRecord['tax_type']>
