/**
 * Vehicle type definitions
 *
 * Section A: Generated aliases from openapi-typescript
 * Section B: Manual types (no response_model or backend uses str)
 */

import type { components } from './api.generated'

// =============================================================================
// Section A — Generated aliases
// =============================================================================

export type Vehicle = components['schemas']['VehicleResponse']
export type VehicleCreate = components['schemas']['VehicleCreate']
export type VehicleUpdate = components['schemas']['VehicleUpdate']
export type VehicleListResponse = components['schemas']['VehicleListResponse']
export type TrailerDetails = components['schemas']['TrailerDetailsResponse']
export type TrailerDetailsCreate = components['schemas']['TrailerDetailsCreate']
export type TrailerDetailsUpdate = components['schemas']['TrailerDetailsUpdate']

/** Derived from the generated VehicleResponse vehicle_type enum */
export type VehicleType = NonNullable<Vehicle['vehicle_type']>

// =============================================================================
// Section B — Manual types (photo routes have no response_model; hitch/brake use str)
// =============================================================================

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

export type HitchType = 'Ball' | 'Pintle' | 'Fifth Wheel' | 'Gooseneck'
export type BrakeType = 'None' | 'Electric' | 'Hydraulic'
