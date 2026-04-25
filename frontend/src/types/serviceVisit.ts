// ============================================================================
// Section A: Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

export type ServiceLineItem = components['schemas']['ServiceLineItemResponse']
export type ServiceLineItemCreate = components['schemas']['ServiceLineItemCreate']
export type ServiceLineItemUpdate = components['schemas']['ServiceLineItemUpdate']
export type ServiceVisit = components['schemas']['ServiceVisitResponse']
export type ServiceVisitCreate = components['schemas']['ServiceVisitCreate']
export type ServiceVisitUpdate = components['schemas']['ServiceVisitUpdate']
export type ServiceVisitListResponse = components['schemas']['ServiceVisitListResponse']

// Derive union types from generated schema fields
export type ServiceCategory = NonNullable<ServiceLineItem['category']>
export type InspectionResult = NonNullable<ServiceLineItem['inspection_result']>
export type InspectionSeverity = NonNullable<ServiceLineItem['inspection_severity']>

// ============================================================================
// Section B: Hand-maintained frontend-only types
// These types exist only in the frontend for form/UI state management.
// ============================================================================

import type { ReminderDraft } from './reminder'

// Form data types for creating visits with inline line items
export interface ServiceVisitFormLineItem {
  id?: number
  tempId?: number
  description: string
  category: ServiceCategory | ''
  cost: number | undefined
  notes: string
  is_inspection: boolean
  inspection_result: InspectionResult | ''
  inspection_severity: InspectionSeverity | ''
  triggered_by_inspection_id: number | undefined
  reminderDraft?: ReminderDraft
}

export interface ServiceVisitFormData {
  vendor_id: number | undefined
  date: string
  odometer_km: number | undefined
  notes: string
  insurance_claim_number: string
  tax_amount: number | undefined
  shop_supplies: number | undefined
  misc_fees: number | undefined
  line_items: ServiceVisitFormLineItem[]
}
