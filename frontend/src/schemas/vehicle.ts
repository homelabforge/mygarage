import { z } from 'zod'
import { optionalStringToUndefined, coerceToNumber } from './shared'

/**
 * Vehicle schema for VehicleEdit and VehicleWizard forms.
 * Matches backend Pydantic validators.
 * See: backend/app/schemas/vehicle.py
 */

export const VEHICLE_TYPES = [
  'Car',
  'SUV',
  'Truck',
  'Motorcycle',
  'Trailer',
  'FifthWheel',
] as const

export const vehicleEditSchema = z.object({
  // Basic Information
  nickname: optionalStringToUndefined,
  license_plate: optionalStringToUndefined,
  vehicle_type: optionalStringToUndefined,
  color: optionalStringToUndefined,

  // Vehicle Details
  year: z.preprocess(
    (val) => (val === '' || val === undefined ? undefined : val),
    z.coerce.number().int().min(1900).max(2100).optional()
  ),
  make: optionalStringToUndefined,
  model: optionalStringToUndefined,

  // VIN Decoded Information
  trim: optionalStringToUndefined,
  body_class: optionalStringToUndefined,
  drive_type: optionalStringToUndefined,
  doors: z.preprocess(
    (val) => (val === '' || val === undefined ? undefined : val),
    z.coerce.number().int().min(0).optional()
  ),
  gvwr_class: optionalStringToUndefined,

  // Engine & Transmission - backend expects string, not number
  displacement_l: z.preprocess(
    (val) => {
      if (val === '' || val === undefined || val === null) return undefined
      // Convert to string for backend compatibility
      return String(val)
    },
    z.string().optional()
  ),
  cylinders: z.preprocess(
    (val) => (val === '' || val === undefined ? undefined : val),
    z.coerce.number().int().min(0).optional()
  ),
  fuel_type: optionalStringToUndefined,
  transmission_type: optionalStringToUndefined,
  transmission_speeds: optionalStringToUndefined,

  // Purchase Information
  purchase_date: optionalStringToUndefined,
  purchase_price: coerceToNumber,

  // Sale Information
  sold_date: optionalStringToUndefined,
  sold_price: coerceToNumber,
})

export type VehicleEditFormData = z.infer<typeof vehicleEditSchema>
