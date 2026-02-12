/**
 * DEF (Diesel Exhaust Fluid) type definitions
 */

export interface DEFRecord {
  id: number
  vin: string
  date: string
  mileage?: number
  gallons?: number | string
  cost?: number | string
  price_per_unit?: number | string
  fill_level?: number | string // 0.00-1.00
  source?: string
  brand?: string
  notes?: string
  created_at: string
}

export interface DEFRecordCreate {
  vin: string
  date: string
  mileage?: number
  gallons?: number
  cost?: number
  price_per_unit?: number
  fill_level?: number
  source?: string
  brand?: string
  notes?: string
}

export interface DEFRecordUpdate {
  date?: string
  mileage?: number
  gallons?: number
  cost?: number
  price_per_unit?: number
  fill_level?: number
  source?: string
  brand?: string
  notes?: string
}

export interface DEFRecordListResponse {
  records: DEFRecord[]
  total: number
}

export interface DEFAnalytics {
  total_gallons: number | string | null
  total_cost: number | string | null
  avg_cost_per_gallon: number | string | null
  gallons_per_1000_miles: number | string | null
  avg_purchase_frequency_days: number | null
  estimated_remaining_gallons: number | string | null
  estimated_miles_remaining: number | null
  estimated_days_remaining: number | null
  last_fill_level: number | string | null
  record_count: number
  data_confidence: 'high' | 'low' | 'insufficient'
}
