export interface WarrantyRecord {
  id: number
  vin: string
  warranty_type: string
  provider: string | null
  start_date: string
  end_date: string | null
  mileage_limit: number | null
  coverage_details: string | null
  policy_number: string | null
  notes: string | null
  created_at: string
}

export interface WarrantyRecordCreate {
  warranty_type: string
  provider?: string | null
  start_date: string
  end_date?: string | null
  mileage_limit?: number | null
  coverage_details?: string | null
  policy_number?: string | null
  notes?: string | null
}

export interface WarrantyRecordUpdate {
  warranty_type?: string
  provider?: string | null
  start_date?: string
  end_date?: string | null
  mileage_limit?: number | null
  coverage_details?: string | null
  policy_number?: string | null
  notes?: string | null
}
