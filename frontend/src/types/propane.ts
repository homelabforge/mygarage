// Propane record types - simplified version of fuel records for fifth wheels
export interface PropaneRecord {
  id: number
  vin: string
  date: string
  propane_gallons: number
  cost?: number
  price_per_unit?: number
  notes?: string
  created_at: string
}

export interface PropaneRecordCreate {
  vin: string
  date: string
  propane_gallons: number
  cost?: number
  price_per_unit?: number
  notes?: string
}

export type PropaneRecordUpdate = Partial<PropaneRecordCreate>

export interface PropaneRecordListResponse {
  fuel_records: PropaneRecord[]
  total: number
  average_mpg?: number  // Not used for propane, but part of API response
}
