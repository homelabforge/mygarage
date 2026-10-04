// ============================================================================
// Section A: Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

export type TollTag = components['schemas']['TollTagResponse']
export type TollTagCreate = components['schemas']['TollTagCreate']
export type TollTagUpdate = components['schemas']['TollTagUpdate']
export type TollTagListResponse = components['schemas']['TollTagListResponse']

export type TollTransaction = components['schemas']['TollTransactionResponse']
export type TollTransactionCreate = components['schemas']['TollTransactionCreate']
export type TollTransactionUpdate = components['schemas']['TollTransactionUpdate']
export type TollTransactionListResponse = components['schemas']['TollTransactionListResponse']
export type TollTransactionSummary = components['schemas']['TollTransactionSummary']

// ============================================================================
// Section B: Hand-maintained frontend-only types
// ============================================================================

/** Frontend-only type for monthly aggregation in summary views */
export interface MonthlyTotal {
  month: string
  count: number
  amount: number
}
