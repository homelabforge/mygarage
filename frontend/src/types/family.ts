// ============================================================================
// Section A: Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

export type UserMinimal = components['schemas']['UserMinimal']
export type VehicleTransferRequest = components['schemas']['VehicleTransferRequest']
export type VehicleTransferResponse = components['schemas']['VehicleTransferResponse']
export type EligibleRecipient = components['schemas']['EligibleRecipient']
export type TransferHistoryResponse = components['schemas']['TransferHistoryResponse']
export type VehicleShareCreate = components['schemas']['VehicleShareCreate']
export type VehicleShareUpdate = components['schemas']['VehicleShareUpdate']
export type VehicleShareResponse = components['schemas']['VehicleShareResponse']
export type VehicleSharesListResponse = components['schemas']['VehicleSharesListResponse']
export type FamilyVehicleSummary = components['schemas']['FamilyVehicleSummary']
export type FamilyMemberData = components['schemas']['FamilyMemberData']
export type FamilyDashboardResponse = components['schemas']['FamilyDashboardResponse']
export type FamilyMemberUpdateRequest = components['schemas']['FamilyMemberUpdateRequest']

// Derive union types from generated schema fields
export type PermissionType = VehicleShareCreate['permission']

// ============================================================================
// Section B: Hand-maintained frontend-only types
// These types and runtime values exist only in the frontend.
// ============================================================================

// ShareableUser is not in the OpenAPI schema — it's a frontend-only UI type
export interface ShareableUser {
  id: number
  display_name: string
  relationship: string | null
}

// =============================================================================
// Relationship Types
// =============================================================================

/** Minimal shape of i18next's `t`, so this module needn't import react-i18next. */
export type TranslateFn = (key: string) => string

export const RELATIONSHIP_PRESETS = [
  { value: 'spouse', labelKey: 'common:relationships.spouse' },
  { value: 'child', labelKey: 'common:relationships.child' },
  { value: 'parent', labelKey: 'common:relationships.parent' },
  { value: 'sibling', labelKey: 'common:relationships.sibling' },
  { value: 'grandparent', labelKey: 'common:relationships.grandparent' },
  { value: 'grandchild', labelKey: 'common:relationships.grandchild' },
  { value: 'in_law', labelKey: 'common:relationships.inLaw' },
  { value: 'friend', labelKey: 'common:relationships.friend' },
  { value: 'other', labelKey: 'common:relationships.other' },
] as const

export type RelationshipType = (typeof RELATIONSHIP_PRESETS)[number]['value'] | null

// =============================================================================
// Helper Functions
// =============================================================================

/**
 * Get the display label for a relationship value.
 */
export function getRelationshipLabel(value: string | null, t: TranslateFn): string {
  if (!value) return ''
  const preset = RELATIONSHIP_PRESETS.find((p) => p.value === value)
  return preset ? t(preset.labelKey) : value
}

/**
 * Format a relationship for display (handles custom relationships).
 */
export function formatRelationship(
  relationship: string | null,
  relationshipCustom: string | null | undefined,
  t: TranslateFn,
): string {
  if (!relationship) return ''
  // A custom relationship is user-entered text — never run it through t().
  if (relationship === 'other' && relationshipCustom) {
    return relationshipCustom
  }
  return getRelationshipLabel(relationship, t)
}
