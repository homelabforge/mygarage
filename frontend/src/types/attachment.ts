// ============================================================================
// Section A: Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

export type Attachment = components['schemas']['AttachmentResponse']
export type AttachmentListResponse = components['schemas']['AttachmentListResponse']

// ============================================================================
// Section B: Hand-maintained frontend-only types
// ============================================================================

// Backend upload route returns the same schema as AttachmentResponse
export type AttachmentUploadResponse = Attachment
