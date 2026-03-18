// ============================================================================
// Section A: Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

export type Document = components['schemas']['DocumentResponse']
export type DocumentListResponse = components['schemas']['DocumentListResponse']
export type DocumentUpdate = components['schemas']['DocumentUpdate']

// ============================================================================
// Section B: Hand-maintained frontend-only types
// ============================================================================

// Backend uses str, not Literal[]. Keep manual.
export type DocumentType = 'Insurance' | 'Registration' | 'Manual' | 'Receipt' | 'Inspection' | 'Other'

// Document creation is via multipart file upload, not JSON body — no generated schema
export interface DocumentCreate {
  vin: string
  title: string
  document_type?: string
  description?: string
}
