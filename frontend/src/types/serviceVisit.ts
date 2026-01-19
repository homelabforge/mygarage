/**
 * Service Visit type definitions
 */

import type { ServiceCategory } from './service'
import type { Vendor } from './vendor'

// Inspection result types
export type InspectionResult = 'passed' | 'failed' | 'needs_attention'
export type InspectionSeverity = 'green' | 'yellow' | 'red'

// Service line item within a visit
export interface ServiceLineItem {
  id: number
  visit_id: number
  description: string
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
  cost?: number
  notes?: string
  is_inspection?: boolean
  inspection_result?: InspectionResult
  inspection_severity?: InspectionSeverity
  schedule_item_id?: number
  triggered_by_inspection_id?: number
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
}

export interface ServiceVisitListResponse {
  visits: ServiceVisit[]
  total: number
}

// Form data types for creating visits with inline line items
export interface ServiceVisitFormLineItem {
  description: string
  cost: number | undefined
  notes: string
  is_inspection: boolean
  inspection_result: InspectionResult | ''
  inspection_severity: InspectionSeverity | ''
  schedule_item_id: number | undefined
  triggered_by_inspection_id: number | undefined
}

export interface ServiceVisitFormData {
  vendor_id: number | undefined
  date: string
  mileage: number | undefined
  notes: string
  service_category: ServiceCategory | ''
  insurance_claim_number: string
  tax_amount: number | undefined
  shop_supplies: number | undefined
  misc_fees: number | undefined
  line_items: ServiceVisitFormLineItem[]
}
