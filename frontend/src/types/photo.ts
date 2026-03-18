// ============================================================================
// Section A: Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

export type PhotoUpdate = components['schemas']['PhotoUpdate']

// ============================================================================
// Section B: Hand-maintained frontend-only types
// Photo routes have no response_model; they return custom dict payloads
// from PhotoService.build_photo_payload(). These match the frontend shape,
// not a generated schema.
// ============================================================================

export interface Photo {
  id: number
  filename: string
  path: string
  thumbnail_url?: string | null
  size: number
  is_main: boolean
  caption?: string | null
  uploaded_at?: string
}

export interface PhotoListResponse {
  photos: Photo[]
  total: number
}
