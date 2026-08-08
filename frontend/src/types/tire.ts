/** Hand-maintained tire types (regenerate OpenAPI later to switch to api.generated). */

export type TirePosition = 'FL' | 'FR' | 'RL' | 'RR' | 'SPARE'

export interface TireReading {
  id: number
  tire_id: number
  vin: string
  position: string
  recorded_at: string
  odometer_km: number | string | null
  tread_depth_mm: number | string
  pressure_kpa: number | string | null
  notes: string | null
  created_at: string
}

export interface Tire {
  id: number
  vin: string
  position: TirePosition
  brand: string | null
  model_name: string | null
  size: string | null
  dot_code: string | null
  installed_date: string | null
  tread_depth_mm: number | string | null
  pressure_kpa: number | string | null
  min_tread_mm: number | string | null
  notes: string | null
  created_at: string
  updated_at: string | null
  projected_km_remaining: number | string | null
  projected_wear_date: string | null
  below_threshold: boolean
  readings: TireReading[]
}

export interface TireListResponse {
  tires: Tire[]
  total: number
}

export interface TireCreate {
  vin: string
  position: TirePosition
  brand?: string | null
  model_name?: string | null
  size?: string | null
  dot_code?: string | null
  installed_date?: string | null
  tread_depth_mm?: number | null
  pressure_kpa?: number | null
  min_tread_mm?: number | null
  notes?: string | null
}

export interface TireReadingCreate {
  recorded_at: string
  odometer_km?: number | null
  tread_depth_mm: number
  pressure_kpa?: number | null
  notes?: string | null
}
