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
export type Coverage = components['schemas']['CoverageEntryResponse']
/** The standard coverage catalogue's keys, straight from the backend's
 *  `Literal`. `constants/insuranceCoverages.ts` is typed against this, so a
 *  coverage added there and not here (or the reverse) fails the build. */
export type CoverageKey = Coverage['coverage_key']
export type PolicyStatusFilter = 'current' | 'active' | 'upcoming' | 'expired' | 'all'

// ============================================================================
// Section B: Hand-maintained frontend-only types
// Backend returns a plain dict from the parse route, no schema.
// ============================================================================

export interface ParsedPolicyVehicle {
  /** Null for a plate the garage does not know (#211). */
  vin: string | null
  /** The registration plate the document printed, when it named one instead of a VIN. */
  plate?: string | null
  /** A vehicle in this garage the caller can put on a policy. */
  matched: boolean
  /** How the document named the vehicle: by VIN, or by plate (a French avis d'échéance). */
  matched_by?: 'vin' | 'plate'
  vehicle_name: string | null
  premium_share: string | null
  deductible: string | null
  /** The bonus-malus coefficient or class printed, for this vehicle's link. */
  no_claims_class?: string | null
  /** The standard coverages read off this vehicle's section, or off the
   *  document as a whole when it has no section of its own. */
  coverages: Coverage[]
}

export interface InsurancePDFParseResponse {
  success: boolean
  /** `text`: a PDF read on the server; `llm`: a photo read by the vision model (#211). */
  source?: 'text' | 'llm'
  data: {
    provider: string | null
    policy_number: string | null
    policy_type: string | null
    start_date: string | null
    end_date: string | null
    premium_amount: string | null
    premium_frequency: string | null
    deductible: string | null
    no_claims_class?: string | null
    notes: string | null
  }
  /** Every VIN on the document, with its own figures where the parser finds
   *  them, then every plate the document printed when it named no VIN. */
  vehicles: ParsedPolicyVehicle[]
  /** The plates printed on the document. */
  plates?: string[]
  /** The document-wide coverages, for a vehicle the form already holds when
   *  the document names none the garage knows. */
  coverages?: Coverage[]
  confidence: {
    [key: string]: 'high' | 'medium' | 'low' | 'rejected'
  }
  confidence_score: number
  parser_used: string | null
  warnings: string[]
}
