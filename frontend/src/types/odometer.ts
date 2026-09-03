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

// Every value the backend writes to `odometer_records.source`, derived by
// enumerating the writers rather than by memory -- there are three syntaxes and
// grepping only the obvious one is how this list went wrong the first time:
// the column default ('manual'), a direct `OdometerRecord(source=...)`
// (telemetry_service -> 'livelink', webhooks -> 'webhook'), and
// `sync_odometer_from_record`, whose source_type is passed by KEYWORD at some
// call sites ('fuel', 'def', 'service_visit') and POSITIONALLY at others
// ('tire', 'tire_rotation', 'tire_set'). 'service' is the pre-v2.27 spelling of
// 'service_visit' and still sits in old rows.
//
// This union previously read 'manual' | 'livelink' | 'import'. Nothing writes
// 'import' -- the CSV importer constructs the row without a source, so those
// rows are 'manual'.
export type OdometerSource =
  | 'manual'
  | 'livelink'
  | 'webhook'
  | 'fuel'
  | 'def'
  | 'service'
  | 'service_visit'
  | 'tire'
  | 'tire_rotation'
  | 'tire_set'
