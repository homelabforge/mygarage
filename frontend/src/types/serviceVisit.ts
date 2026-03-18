/**
 * Service Visit type definitions
 */

import type { Vendor } from './vendor'
import type { ReminderCreate, ReminderDraft } from './reminder'

// Service categories matching backend Literal type
export type ServiceCategory = 'Maintenance' | 'Inspection' | 'Collision' | 'Upgrades' | 'Detailing'

// Inspection result types
export type InspectionResult = 'passed' | 'failed' | 'needs_attention'
export type InspectionSeverity = 'green' | 'yellow' | 'red'

// Service line item within a visit
export interface ServiceLineItem {
  id: number
  visit_id: number
  description: string
  category?: ServiceCategory
  cost?: number
  notes?: string
  is_inspection: boolean
  inspection_result?: InspectionResult
  inspection_severity?: InspectionSeverity
  schedule_item_id?: number
  triggered_by_inspection_id?: number
  created_at: string
  is_failed_inspection: boolean
  needs_followup: boolean
}

export interface ServiceLineItemCreate {
  description: string
  category?: ServiceCategory
  cost?: number
  notes?: string
  is_inspection?: boolean
  inspection_result?: InspectionResult
  inspection_severity?: InspectionSeverity
  schedule_item_id?: number
  triggered_by_inspection_id?: number
  reminder?: ReminderCreate
  temp_id?: number
}

// Diff-based line item for visit updates (id present = existing, absent = new)
export interface ServiceLineItemUpdate {
  id?: number
  temp_id?: number
  description: string
  category?: ServiceCategory
  cost?: number
  notes?: string
  is_inspection?: boolean
  inspection_result?: InspectionResult
  inspection_severity?: InspectionSeverity
  triggered_by_inspection_id?: number
  schedule_item_id?: number
  reminder?: ReminderCreate
}

// Service visit (container for line items)
export interface ServiceVisit {
  id: number
  vin: string
  vendor_id?: number
  vendor?: Vendor
  date: string
  mileage?: number
  total_cost?: number
  tax_amount?: number
  shop_supplies?: number
  misc_fees?: number
  notes?: string
  service_category?: ServiceCategory
  insurance_claim_number?: string
  created_at: string
  updated_at?: string
  line_items: ServiceLineItem[]
  subtotal: number
  calculated_total_cost: number
  has_failed_inspections: boolean
}

export interface ServiceVisitCreate {
  vendor_id?: number
  date: string
  mileage?: number
  total_cost?: number
  tax_amount?: number
  shop_supplies?: number
  misc_fees?: number
  notes?: string
  service_category?: ServiceCategory
  insurance_claim_number?: string
  line_items: ServiceLineItemCreate[]
}

export interface ServiceVisitUpdate {
  vendor_id?: number
  date?: string
  mileage?: number
  total_cost?: number
  tax_amount?: number
  shop_supplies?: number
  misc_fees?: number
  notes?: string
  service_category?: ServiceCategory
  insurance_claim_number?: string
  line_items?: ServiceLineItemUpdate[]
}

export interface ServiceVisitListResponse {
  visits: ServiceVisit[]
  total: number
}

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
  schedule_item_id: number | undefined
  triggered_by_inspection_id: number | undefined
  reminderDraft?: ReminderDraft
}

export interface ServiceVisitFormData {
  vendor_id: number | undefined
  date: string
  mileage: number | undefined
  notes: string
  insurance_claim_number: string
  tax_amount: number | undefined
  shop_supplies: number | undefined
  misc_fees: number | undefined
  line_items: ServiceVisitFormLineItem[]
}
