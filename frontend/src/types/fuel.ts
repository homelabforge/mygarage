/**
 * Fuel Record type definitions
 */

export interface FuelRecord {
  id: number
  vin: string
  date: string
  mileage?: number
  gallons?: number
  propane_gallons?: number
  price_per_unit?: number
  cost?: number
  fuel_type?: string
  is_full_tank: boolean
  missed_fillup: boolean
  is_hauling: boolean
  notes?: string
  mpg?: number
  created_at: string
}

export interface FuelRecordCreate {
  vin: string
  date: string
  mileage?: number
  gallons?: number
  propane_gallons?: number
  price_per_unit?: number
  cost?: number
  fuel_type?: string
  is_full_tank: boolean
  missed_fillup: boolean
  is_hauling: boolean
  notes?: string
}

export interface FuelRecordUpdate {
  date?: string
  mileage?: number
  gallons?: number
  propane_gallons?: number
  price_per_unit?: number
  cost?: number
  fuel_type?: string
  is_full_tank?: boolean
  missed_fillup?: boolean
  is_hauling?: boolean
  notes?: string
}

export interface FuelRecordListResponse {
  records: FuelRecord[]
  total: number
  average_mpg?: number
}
