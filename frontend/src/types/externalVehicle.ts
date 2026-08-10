export type ExternalVehicleKind = 'customer' | 'reference'

export interface ExternalVehicle {
  id: number
  kind: ExternalVehicleKind
  nickname: string
  year: number | null
  make: string | null
  model: string | null
  vehicle_type: string | null
  contact_name: string | null
  contact_phone: string | null
  notes: string | null
  last_service_note: string | null
  created_at: string
  updated_at: string | null
}

export interface ExternalVehicleListResponse {
  vehicles: ExternalVehicle[]
  total: number
}

export type ExternalVehicleInput = {
  kind: ExternalVehicleKind
  nickname: string
  year?: number | null
  make?: string | null
  model?: string | null
  vehicle_type?: string | null
  contact_name?: string | null
  contact_phone?: string | null
  notes?: string | null
  last_service_note?: string | null
}
