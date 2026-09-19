// ============================================================================
// Section A: Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

export type InsurancePolicy = components['schemas']['InsurancePolicyResponse']
export type InsurancePolicyCreate = components['schemas']['InsurancePolicyCreate']
export type InsurancePolicyUpdate = components['schemas']['InsurancePolicyUpdate']
export type InsurancePolicyRenew = components['schemas']['InsurancePolicyRenew']
export type InsurancePolicyReplace = components['schemas']['InsurancePolicyReplace']
export type PolicyVehicle = components['schemas']['PolicyVehicleResponse']
export type PolicyVehicleCreate = components['schemas']['PolicyVehicleCreate']
export type PolicyVehicleUpsert = components['schemas']['PolicyVehicleUpsert']
export type PolicyHistoryEntry = components['schemas']['PolicyHistoryEntry']
export type NamedField = components['schemas']['NamedField']
export type PolicyStatusFilter = 'current' | 'active' | 'upcoming' | 'expired' | 'all'

// ============================================================================
// Section B: Hand-maintained frontend-only types
// Backend returns a plain dict from the parse route, no schema.
// ============================================================================

export interface ParsedPolicyVehicle {
  vin: string
  /** A vehicle in this garage the caller can put on a policy. */
  matched: boolean
  vehicle_name: string | null
  premium_share: string | null
  deductible: string | null
}

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
  /** Every VIN on the document, with its own figures where the parser finds them. */
  vehicles: ParsedPolicyVehicle[]
  confidence: {
    [key: string]: 'high' | 'medium' | 'low'
  }
  confidence_score: number
  parser_used: string | null
  warnings: string[]
}
