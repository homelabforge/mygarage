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
  'RV',
  'Trailer',
  'FifthWheel',
  'TravelTrailer',
  'Electric',
  'Hybrid',
] as const

const yearSchema = z
  .number()
  .int('Year must be a whole number')
  .min(1900, 'Year must be 1900 or later')
  .max(2100, 'Year must be 2100 or earlier')
  .or(z.nan())
  .transform(val => isNaN(val) ? undefined : val)
  .optional()

const doorsSchema = z
  .number()
  .int('Doors must be a whole number')
  .min(0, 'Doors cannot be negative')
  .or(z.nan())
  .transform(val => isNaN(val) ? undefined : val)
  .optional()

const cylindersSchema = z
  .number()
  .int('Cylinders must be a whole number')
  .min(0, 'Cylinders cannot be negative')
  .or(z.nan())
  .transform(val => isNaN(val) ? undefined : val)
  .optional()

const purchasePriceSchema = z
  .number()
  .or(z.nan())
  .transform(val => isNaN(val) ? undefined : val)
  .optional()

const soldPriceSchema = z
  .number()
  .or(z.nan())
  .transform(val => isNaN(val) ? undefined : val)
  .optional()

export const vehicleEditSchema = z.object({
  // Basic Information
  nickname: z.string().optional(),
  license_plate: z.string().optional(),
  vehicle_type: z.string().optional(),
  color: z.string().optional(),

  // Vehicle Details
  year: yearSchema,
  make: z.string().optional(),
  model: z.string().optional(),

  // VIN Decoded Information
  trim: z.string().optional(),
  body_class: z.string().optional(),
  drive_type: z.string().optional(),
  doors: doorsSchema,
  gvwr_class: z.string().optional(),

  // Engine & Transmission
  displacement_l: z.string().optional(), // Backend expects string
  cylinders: cylindersSchema,
  fuel_type: z.string().optional(),
  transmission_type: z.string().optional(),
  transmission_speeds: z.string().optional(),

  // Purchase Information
  purchase_date: z.string().optional(),
  purchase_price: purchasePriceSchema,

  // Sale Information
  sold_date: z.string().optional(),
  sold_price: soldPriceSchema,
})

// Use z.output for Zod v4 compatibility with z.coerce fields
export type VehicleEditInput = z.input<typeof vehicleEditSchema>
export type VehicleEditFormData = z.output<typeof vehicleEditSchema>
