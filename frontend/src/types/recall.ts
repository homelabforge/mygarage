// ============================================================================
// Section A: Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

export type Recall = components['schemas']['RecallResponse']
export type RecallCreate = components['schemas']['RecallCreate']
export type RecallUpdate = components['schemas']['RecallUpdate']
export type RecallListResponse = components['schemas']['RecallListResponse']
