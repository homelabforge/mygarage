import { z } from 'zod'

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
  nickname: z.string().optional(),
  license_plate: z.string().optional(),
  vehicle_type: z.string().optional(),
  color: z.string().optional(),

  // Vehicle Details
  year: z
    .number({ invalid_type_error: 'Year must be a number' })
    .int('Year must be a whole number')
    .min(1900, 'Year must be 1900 or later')
    .max(2100, 'Year must be 2100 or earlier')
    .optional(),
  make: z.string().optional(),
  model: z.string().optional(),

  // VIN Decoded Information
  trim: z.string().optional(),
  body_class: z.string().optional(),
  drive_type: z.string().optional(),
  doors: z
    .number({ invalid_type_error: 'Doors must be a number' })
    .int('Doors must be a whole number')
    .min(0, 'Doors cannot be negative')
    .optional(),
  gvwr_class: z.string().optional(),

  // Engine & Transmission
  displacement_l: z.string().optional(), // Backend expects string
  cylinders: z
    .number({ invalid_type_error: 'Cylinders must be a number' })
    .int('Cylinders must be a whole number')
    .min(0, 'Cylinders cannot be negative')
    .optional(),
  fuel_type: z.string().optional(),
  transmission_type: z.string().optional(),
  transmission_speeds: z.string().optional(),

  // Purchase Information
  purchase_date: z.string().optional(),
  purchase_price: z
    .number({ invalid_type_error: 'Purchase price must be a number' })
    .optional(),

  // Sale Information
  sold_date: z.string().optional(),
  sold_price: z
    .number({ invalid_type_error: 'Sold price must be a number' })
    .optional(),
})

export type VehicleEditFormData = z.infer<typeof vehicleEditSchema>
