// ============================================================================
// Section A: Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

export type InsurancePolicy = components['schemas']['InsurancePolicy']
export type InsurancePolicyCreate = components['schemas']['InsurancePolicyCreate']
export type InsurancePolicyUpdate = components['schemas']['InsurancePolicyUpdate']

// ============================================================================
// Section B: Hand-maintained frontend-only types
// Backend returns custom dict from insurance route, no schema.
// ============================================================================

export interface InsurancePDFParseResponse {
  success: boolean
  data: {
    provider: string | null
    policy_number: string | null
    policy_type: string | null
    start_date: string | null
    end_date: string | null
    premium_amount: string | null
    premium_frequency: string | null
    deductible: string | null
    coverage_limits: string | null
    notes: string | null
  }
  confidence: {
    [key: string]: 'high' | 'medium' | 'low'
  }
  vehicles_found: string[]
  warnings: string[]
}
