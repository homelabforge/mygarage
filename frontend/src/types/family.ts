/**
 * Family Multi-User System type definitions.
 *
 * Includes types for:
 * - Relationship presets
 * - Vehicle transfers
 * - Vehicle sharing
 * - Family dashboard
 */

// =============================================================================
// Relationship Types
// =============================================================================

export const RELATIONSHIP_PRESETS = [
  { value: 'spouse', label: 'Spouse/Partner' },
  { value: 'child', label: 'Child' },
  { value: 'parent', label: 'Parent' },
  { value: 'sibling', label: 'Sibling' },
  { value: 'grandparent', label: 'Grandparent' },
  { value: 'grandchild', label: 'Grandchild' },
  { value: 'in_law', label: 'In-Law' },
  { value: 'friend', label: 'Friend' },
  { value: 'other', label: 'Other' },
] as const

export type RelationshipType = (typeof RELATIONSHIP_PRESETS)[number]['value'] | null

// =============================================================================
// User Types (Extended)
// =============================================================================

export interface UserMinimal {
  id: number
  username: string
  full_name: string | null
  relationship: string | null
}

export interface ShareableUser {
  id: number
  display_name: string
  relationship: string | null
}

// =============================================================================
// Vehicle Transfer Types
// =============================================================================

export interface VehicleTransferRequest {
  to_user_id: number
  transfer_notes?: string | null
  data_included?: Record<string, boolean>
}

export interface VehicleTransferResponse {
  id: number
  vehicle_vin: string
  from_user: UserMinimal
  to_user: UserMinimal
  transferred_at: string
  transferred_by: UserMinimal
  transfer_notes: string | null
  data_included: Record<string, boolean> | null
}

export interface EligibleRecipient {
  id: number
  username: string
  full_name: string | null
  relationship: string | null
}

export interface TransferHistoryResponse {
  transfers: VehicleTransferResponse[]
  total: number
}

// =============================================================================
// Vehicle Sharing Types
// =============================================================================

export type PermissionType = 'read' | 'write'

export interface VehicleShareCreate {
  user_id: number
  permission: PermissionType
}

export interface VehicleShareUpdate {
  permission: PermissionType
}

export interface VehicleShareResponse {
  id: number
  vehicle_vin: string
  user: UserMinimal
  permission: string
  shared_by: UserMinimal
  shared_at: string
}

export interface VehicleSharesListResponse {
  shares: VehicleShareResponse[]
  total: number
}

// =============================================================================
// Family Dashboard Types
// =============================================================================

export interface FamilyVehicleSummary {
  vin: string
  nickname: string
  year: number | null
  make: string | null
  model: string | null
  main_photo: string | null
  last_service_date: string | null
  last_service_description: string | null
  next_reminder_description: string | null
  next_reminder_due: string | null
  overdue_reminders: number
}

export interface FamilyMemberData {
  id: number
  username: string
  full_name: string | null
  relationship: string | null
  relationship_custom: string | null
  vehicle_count: number
  vehicles: FamilyVehicleSummary[]
  overdue_reminders: number
  upcoming_reminders: number
  // Dashboard management fields
  show_on_family_dashboard: boolean
  family_dashboard_order: number
}

export interface FamilyDashboardResponse {
  members: FamilyMemberData[]
  total_members: number
  total_vehicles: number
  total_overdue_reminders: number
  total_upcoming_reminders: number
}

export interface FamilyMemberUpdateRequest {
  show_on_family_dashboard: boolean
  family_dashboard_order?: number | null
}

// =============================================================================
// Helper Functions
// =============================================================================

/**
 * Get the display label for a relationship value.
 */
export function getRelationshipLabel(value: string | null): string {
  if (!value) return ''
  const preset = RELATIONSHIP_PRESETS.find(p => p.value === value)
  return preset ? preset.label : value
}

/**
 * Format a relationship for display (handles custom relationships).
 */
export function formatRelationship(relationship: string | null, relationshipCustom?: string | null): string {
  if (!relationship) return ''
  if (relationship === 'other' && relationshipCustom) {
    return relationshipCustom
  }
  return getRelationshipLabel(relationship)
}
