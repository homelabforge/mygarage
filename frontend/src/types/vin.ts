// ============================================================================
// Section A: Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

export type EngineInfo = components['schemas']['EngineInfo']
export type TransmissionInfo = components['schemas']['TransmissionInfo']
export type VINDecodeResponse = components['schemas']['VINDecodeResponse']

// ============================================================================
// Section B: Hand-maintained frontend-only types
// Backend validates inline, no dedicated schema.
// ============================================================================

export interface VINValidationResponse {
  valid: boolean
  vin: string
  message?: string
  error?: string
}
