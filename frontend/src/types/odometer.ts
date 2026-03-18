// ============================================================================
// Section A: Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

export type OdometerRecord = components['schemas']['OdometerRecordResponse']
export type OdometerRecordCreate = components['schemas']['OdometerRecordCreate']
export type OdometerRecordUpdate = components['schemas']['OdometerRecordUpdate']
export type OdometerRecordListResponse = components['schemas']['OdometerRecordListResponse']

// ============================================================================
// Section B: Hand-maintained frontend-only types
// Backend uses str, not Literal[]. Keep manual.
// ============================================================================

export type OdometerSource = 'manual' | 'livelink' | 'import'
