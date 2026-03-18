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

