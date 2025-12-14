/**
 * Vehicle type definitions
 */

export type VehicleType = 'Car' | 'Truck' | 'SUV' | 'Motorcycle' | 'RV' | 'Trailer' | 'FifthWheel' | 'Electric' | 'Hybrid'

export interface Vehicle {
  vin: string
  nickname: string
  vehicle_type: VehicleType
  year?: number
  make?: string
  model?: string
  license_plate?: string
  color?: string
  purchase_date?: string
  purchase_price?: number
  sold_date?: string
  sold_price?: number
  main_photo?: string
  // VIN decoded fields
  trim?: string
  body_class?: string
  drive_type?: string
  doors?: number
  gvwr_class?: string
  displacement_l?: string
  cylinders?: number
  fuel_type?: string
  transmission_type?: string
  transmission_speeds?: string
  // Window sticker fields
  window_sticker_file_path?: string
  window_sticker_uploaded_at?: string
  msrp_base?: number
  msrp_options?: number
  msrp_total?: number
  fuel_economy_city?: number
  fuel_economy_highway?: number
  fuel_economy_combined?: number
  standard_equipment?: Record<string, unknown>
  optional_equipment?: Record<string, unknown>
  assembly_location?: string
  // Enhanced window sticker fields
  destination_charge?: number
  window_sticker_options_detail?: Record<string, string>
  window_sticker_packages?: Record<string, string>
  exterior_color?: string
  interior_color?: string
  sticker_engine_description?: string
  sticker_transmission_description?: string
  sticker_drivetrain?: string
  wheel_specs?: string
  tire_specs?: string
  warranty_powertrain?: string
  warranty_basic?: string
  environmental_rating_ghg?: string
  environmental_rating_smog?: string
  window_sticker_parser_used?: string
  window_sticker_confidence_score?: number
  window_sticker_extracted_vin?: string
  created_at: string
  updated_at?: string
  // Archive fields
  archived_at?: string | null
  archive_reason?: string | null
  archive_sale_price?: number | null
  archive_sale_date?: string | null
  archive_notes?: string | null
  archived_visible?: boolean
}

export interface VehicleCreate {
  vin: string
  nickname: string
  vehicle_type: VehicleType
  year?: number
  make?: string
  model?: string
  license_plate?: string
  color?: string
  purchase_date?: string
  purchase_price?: number
  sold_date?: string
  sold_price?: number
  // VIN decoded fields
  trim?: string
  body_class?: string
  drive_type?: string
  doors?: number
  gvwr_class?: string
  displacement_l?: string
  cylinders?: number
  fuel_type?: string
  transmission_type?: string
  transmission_speeds?: string
}

export interface VehicleUpdate {
  nickname?: string
  vehicle_type?: VehicleType
  year?: number
  make?: string
  model?: string
  license_plate?: string
  color?: string
  purchase_date?: string
  purchase_price?: number
  sold_date?: string
  sold_price?: number
  // VIN decoded fields
  trim?: string
  body_class?: string
  drive_type?: string
  doors?: number
  gvwr_class?: string
  displacement_l?: string
  cylinders?: number
  fuel_type?: string
  transmission_type?: string
  transmission_speeds?: string
}

export interface VehicleListResponse {
  vehicles: Vehicle[]
  total: number
}

export interface VehiclePhoto {
  id: number
  filename: string
  path: string
  thumbnail_url?: string | null
  size: number
  is_main: boolean
  caption?: string | null
  uploaded_at?: string
}

export interface VehiclePhotoListResponse {
  photos: VehiclePhoto[]
  total: number
}

export interface VehiclePhotoUploadResponse {
  id: number
  filename: string
  path: string
  thumbnail_url?: string | null
  size: number
  is_main: boolean
  caption?: string | null
  uploaded_at?: string
}

// Trailer Details Types

export type HitchType = 'Ball' | 'Pintle' | 'Fifth Wheel' | 'Gooseneck'
export type BrakeType = 'None' | 'Electric' | 'Hydraulic'

export interface TrailerDetails {
  vin: string
  gvwr?: number
  hitch_type?: HitchType
  axle_count?: number
  brake_type?: BrakeType
  length_ft?: number
  width_ft?: number
  height_ft?: number
  tow_vehicle_vin?: string
}

export interface TrailerDetailsCreate {
  vin: string
  gvwr?: number
  hitch_type?: HitchType
  axle_count?: number
  brake_type?: BrakeType
  length_ft?: number
  width_ft?: number
  height_ft?: number
  tow_vehicle_vin?: string
}

export interface TrailerDetailsUpdate {
  gvwr?: number
  hitch_type?: HitchType
  axle_count?: number
  brake_type?: BrakeType
  length_ft?: number
  width_ft?: number
  height_ft?: number
  tow_vehicle_vin?: string
}
