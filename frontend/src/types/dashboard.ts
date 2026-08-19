// ============================================================================
// Section A: Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

export type VehicleStatistics = components['schemas']['VehicleStatistics']
export type DashboardResponse = components['schemas']['DashboardResponse']
export type FleetHealth = components['schemas']['FleetHealth']
export type FleetNextDue = components['schemas']['FleetNextDue']

// ============================================================================
// Section B: Hand-maintained frontend-only types
// ============================================================================
// (none)
