// ============================================================================
// Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

/** Barcode not yet in generated OpenAPI types — extend until `bun run generate:api`. */
type SupplyBarcodeFields = { barcode?: string | null }

export type Supply = components['schemas']['SupplyResponse'] & SupplyBarcodeFields
export type SupplyListResponse = Omit<components['schemas']['SupplyListResponse'], 'supplies'> & {
  supplies: Supply[]
}
export type SupplyCreate = components['schemas']['SupplyCreate'] & SupplyBarcodeFields
export type SupplyUpdate = components['schemas']['SupplyUpdate'] & SupplyBarcodeFields
export type SupplyPurchase = components['schemas']['SupplyPurchaseResponse']
export type SupplyPurchaseCreate = components['schemas']['SupplyPurchaseCreate']
export type SupplyAdjustmentCreate = components['schemas']['SupplyAdjustmentCreate']
export type SupplyUsage = components['schemas']['SupplyUsageResponse']
export type SupplyHistory = components['schemas']['SupplyHistoryResponse']
export type VehicleSupplyUsages = components['schemas']['VehicleSupplyUsagesResponse']
