// ============================================================================
// Section A: Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

export type VehicleStatistics = components['schemas']['VehicleStatistics'] & {
  owner_relationship?: string | null
  owner_relationship_custom?: string | null
}
export type DashboardResponse = Omit<components['schemas']['DashboardResponse'], 'vehicles'> & {
  vehicles: VehicleStatistics[]
  multi_user_enabled?: boolean
}
export type FleetHealth = components['schemas']['FleetHealth']
export type FleetNextDue = components['schemas']['FleetNextDue']

// ============================================================================
// Section B: Hand-maintained frontend-only types
// ============================================================================
// (none)
