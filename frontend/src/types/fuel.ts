/**
 * Fuel Record type definitions
 */

export interface FuelRecord {
  id: number
  vin: string
  date: string
  mileage?: number
  gallons?: number | string  // Backend returns Decimal as string
  propane_gallons?: number | string  // Backend returns Decimal as string
  tank_size_lb?: number | string  // Backend returns Decimal as string
  tank_quantity?: number
  kwh?: number | string  // Backend returns Decimal as string
  price_per_unit?: number | string  // Backend returns Decimal as string
  cost?: number | string  // Backend returns Decimal as string
  fuel_type?: string
  is_full_tank: boolean
  missed_fillup: boolean
  is_hauling: boolean
  notes?: string
  mpg?: number | string  // Backend returns Decimal as string
  created_at: string
}

export interface FuelRecordCreate {
  vin: string
  date: string
  mileage?: number
  gallons?: number
  propane_gallons?: number
  tank_size_lb?: number
  tank_quantity?: number
  kwh?: number
  price_per_unit?: number
  cost?: number
  fuel_type?: string
  is_full_tank: boolean
  missed_fillup: boolean
  is_hauling: boolean
  notes?: string
  def_fill_level?: number
}

export interface FuelRecordUpdate {
  date?: string
  mileage?: number
  gallons?: number
  propane_gallons?: number
  tank_size_lb?: number
  tank_quantity?: number
  kwh?: number
  price_per_unit?: number
  cost?: number
  fuel_type?: string
  is_full_tank?: boolean
  missed_fillup?: boolean
  is_hauling?: boolean
  notes?: string
  def_fill_level?: number | null
}

export interface FuelRecordListResponse {
  records: FuelRecord[]
  total: number
  average_mpg?: number | string  // Backend returns Decimal as string
}
