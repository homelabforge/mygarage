/**
 * TypeScript types for VIN-related data structures
 */

export interface EngineInfo {
  displacement_l?: string | null
  cylinders?: number | null
  hp?: number | null
  kw?: number | null
  fuel_type?: string | null
}

export interface TransmissionInfo {
  type?: string | null
  speeds?: string | null
}

export interface VINDecodeResponse {
  vin: string
  year?: number | null
  make?: string | null
  model?: string | null
  trim?: string | null
  vehicle_type?: string | null
  body_class?: string | null
  engine?: EngineInfo | null
  transmission?: TransmissionInfo | null
  drive_type?: string | null
  manufacturer?: string | null
  plant_city?: string | null
  plant_country?: string | null
  doors?: number | null
  gvwr?: string | null
  series?: string | null
  steering_location?: string | null
  entertainment_system?: string | null
  error_code?: string | null
  error_text?: string | null
}

export interface VINValidationResponse {
  valid: boolean
  vin: string
  message?: string
  error?: string
}
