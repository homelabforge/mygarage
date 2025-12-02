/**
 * Odometer Record type definitions
 */

export interface OdometerRecord {
  id: number
  vin: string
  date: string
  mileage: number
  notes?: string
  created_at: string
}

export interface OdometerRecordCreate {
  vin: string
  date: string
  mileage: number
  notes?: string
}

export interface OdometerRecordUpdate {
  date?: string
  mileage?: number
  notes?: string
}

export interface OdometerRecordListResponse {
  records: OdometerRecord[]
  total: number
  latest_mileage?: number
}
