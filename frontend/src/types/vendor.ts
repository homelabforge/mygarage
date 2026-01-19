/**
 * Vendor type definitions
 */

export interface Vendor {
  id: number
  name: string
  address?: string
  city?: string
  state?: string
  zip_code?: string
  phone?: string
  created_at: string
  updated_at?: string
  full_address?: string
}

export interface VendorCreate {
  name: string
  address?: string
  city?: string
  state?: string
  zip_code?: string
  phone?: string
}

export interface VendorUpdate {
  name?: string
  address?: string
  city?: string
  state?: string
  zip_code?: string
  phone?: string
}

export interface VendorListResponse {
  vendors: Vendor[]
  total: number
}

export interface VendorPriceEntry {
  date: string
  cost: number
  service_line_item_id: number
}

export interface VendorPriceHistoryResponse {
  vendor_id: number
  vendor_name: string
  schedule_item_id?: number
  schedule_item_name?: string
  entries: VendorPriceEntry[]
  average_cost?: number
  min_cost?: number
  max_cost?: number
}
