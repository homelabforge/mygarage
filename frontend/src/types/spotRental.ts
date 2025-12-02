export interface SpotRental {
  id: number
  vin: string
  location_name: string | null
  location_address: string | null
  check_in_date: string
  check_out_date: string | null
  nightly_rate: number | null
  weekly_rate: number | null
  monthly_rate: number | null
  electric: number | null
  water: number | null
  waste: number | null
  total_cost: number | null
  amenities: string | null
  notes: string | null
  created_at: string
}

export interface SpotRentalCreate {
  location_name?: string | null
  location_address?: string | null
  check_in_date: string
  check_out_date?: string | null
  nightly_rate?: number | null
  weekly_rate?: number | null
  monthly_rate?: number | null
  electric?: number | null
  water?: number | null
  waste?: number | null
  total_cost?: number | null
  amenities?: string | null
  notes?: string | null
}

export interface SpotRentalUpdate {
  location_name?: string | null
  location_address?: string | null
  check_in_date?: string
  check_out_date?: string | null
  nightly_rate?: number | null
  weekly_rate?: number | null
  monthly_rate?: number | null
  electric?: number | null
  water?: number | null
  waste?: number | null
  total_cost?: number | null
  amenities?: string | null
  notes?: string | null
}
