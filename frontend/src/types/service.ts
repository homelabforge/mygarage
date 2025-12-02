/**
 * Service Record type definitions
 */

export type ServiceType = 'Maintenance' | 'Inspection' | 'Collision' | 'Upgrades'

export interface ServiceRecord {
  id: number
  vin: string
  date: string
  mileage?: number
  description: string
  cost?: number
  notes?: string
  vendor_name?: string
  vendor_location?: string
  service_type?: ServiceType
  insurance_claim?: string
  created_at: string
  attachment_count?: number
}

export interface ServiceRecordCreate {
  vin: string
  date: string
  mileage?: number
  description: string
  cost?: number
  notes?: string
  vendor_name?: string
  vendor_location?: string
  service_type?: ServiceType
  insurance_claim?: string
}

export interface ServiceRecordUpdate {
  date?: string
  mileage?: number
  description?: string
  cost?: number
  notes?: string
  vendor_name?: string
  vendor_location?: string
  service_type?: ServiceType
  insurance_claim?: string
}

export interface ServiceRecordListResponse {
  records: ServiceRecord[]
  total: number
}
