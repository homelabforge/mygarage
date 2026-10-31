// ============================================================================
// Section A: Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

export type HoursRecord = components['schemas']['HoursRecordResponse']
export type HoursRecordCreate = components['schemas']['HoursRecordCreate']
export type HoursRecordUpdate = components['schemas']['HoursRecordUpdate']
export type HoursRecordListResponse = components['schemas']['HoursRecordListResponse']
export type NearestHours = components['schemas']['NearestHoursResponse']

// ============================================================================
// Section B: Hand-maintained frontend-only types
// Backend uses str, not Literal[] -- see models/hours.py's `source` column
// comment ("manual, fuel, service_visit"). Keep manual.
// Since #217 tire events publish hours rows too, under the tire sources.
// ============================================================================

export type HoursSource =
  | 'manual'
  | 'fuel'
  | 'service_visit'
  | 'tire'
  | 'tire_mount'
  | 'tire_dismount'
  | 'tire_retire'
  | 'tire_lone_dismount'
  | 'tire_rotation'
  | 'tire_set'
