export interface ExternalVehicle {
  id: number
  nickname: string
  vin: string | null
  year: number | null
  make: string | null
  model: string | null
  vehicle_type: string | null
  contact_name: string | null
  contact_phone: string | null
  notes: string | null
  created_at: string
  updated_at: string | null
}

export interface ExternalVehicleListResponse {
  vehicles: ExternalVehicle[]
  total: number
}

export type ExternalVehicleInput = {
  nickname: string
  vin?: string | null
  year?: number | null
  make?: string | null
  model?: string | null
  vehicle_type?: string | null
  contact_name?: string | null
  contact_phone?: string | null
  notes?: string | null
}
