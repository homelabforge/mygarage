// ============================================================================
// Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

export type Supply = components['schemas']['SupplyResponse']
export type SupplyListResponse = components['schemas']['SupplyListResponse']
export type SupplyCreate = components['schemas']['SupplyCreate']
export type SupplyUpdate = components['schemas']['SupplyUpdate']
export type SupplyPurchase = components['schemas']['SupplyPurchaseResponse']
export type SupplyPurchaseCreate = components['schemas']['SupplyPurchaseCreate']
export type SupplyAdjustmentCreate = components['schemas']['SupplyAdjustmentCreate']
export type SupplyUsage = components['schemas']['SupplyUsageResponse']
export type SupplyHistory = components['schemas']['SupplyHistoryResponse']
export type VehicleSupplyUsages = components['schemas']['VehicleSupplyUsagesResponse']
