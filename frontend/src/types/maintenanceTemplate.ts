// ============================================================================
// Section A: Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

export type MaintenanceTemplate = components['schemas']['MaintenanceTemplateResponse']
export type MaintenanceTemplateListResponse = components['schemas']['MaintenanceTemplateListResponse']
export type TemplateSearchResponse = components['schemas']['TemplateSearchResponse']
export type TemplateApplyRequest = components['schemas']['TemplateApplyRequest']
export type TemplateApplyResponse = components['schemas']['TemplateApplyResponse']

// ============================================================================
// Section B: Hand-maintained frontend-only types
// ============================================================================

/** Structured template data — backend uses untyped dict */
export interface MaintenanceTemplateData {
  metadata: {
    make: string
    model: string
    year_start: number
    year_end: number
    duty_type: string
    source?: string
    contributor?: string
    version?: string
  }
  maintenance_items: MaintenanceItem[]
}

/** Individual maintenance schedule item within a template */
export interface MaintenanceItem {
  description: string
  interval_months?: number
  interval_miles?: number
  category: string
  severity: string
  notes?: string
}
