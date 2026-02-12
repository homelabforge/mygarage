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
  .nullable()
  .optional()
  .transform(val => (val === null || (typeof val === 'number' && isNaN(val))) ? undefined : val)

const soldPriceSchema = z
  .number()
  .or(z.nan())
  .nullable()
  .optional()
  .transform(val => (val === null || (typeof val === 'number' && isNaN(val))) ? undefined : val)

// Handle date fields that may be null, undefined, or empty string from the database
const optionalDateSchema = z
  .string()
  .nullable()
  .optional()
  .transform(val => (val === null || val === '') ? undefined : val)

// Handle optional string fields that may be null from the database
const optionalStringSchema = z
  .string()
  .nullable()
  .optional()
  .transform(val => (val === null || val === '') ? undefined : val)

export const vehicleEditSchema = z.object({
  // Basic Information
  nickname: optionalStringSchema,
  license_plate: optionalStringSchema,
  vehicle_type: optionalStringSchema,
  color: optionalStringSchema,

  // Vehicle Details
  year: yearSchema,
  make: optionalStringSchema,
  model: optionalStringSchema,

  // VIN Decoded Information
  trim: optionalStringSchema,
  body_class: optionalStringSchema,
  drive_type: optionalStringSchema,
  doors: doorsSchema,
  gvwr_class: optionalStringSchema,

  // Engine & Transmission
  displacement_l: optionalStringSchema, // Backend expects string
  cylinders: cylindersSchema,
  fuel_type: optionalStringSchema,
  transmission_type: optionalStringSchema,
  transmission_speeds: optionalStringSchema,

  // Purchase Information
  purchase_date: optionalDateSchema,
  purchase_price: purchasePriceSchema,

  // Sale Information
  sold_date: optionalDateSchema,
  sold_price: soldPriceSchema,

  // DEF Tracking
  def_tank_capacity_gallons: z
    .number()
    .min(0, 'Tank capacity cannot be negative')
    .max(999.99, 'Tank capacity too large')
    .or(z.nan())
    .nullable()
    .optional()
    .transform(val => (val === null || (typeof val === 'number' && isNaN(val))) ? undefined : val),
})

// Use z.output for Zod v4 compatibility with z.coerce fields
export type VehicleEditInput = z.input<typeof vehicleEditSchema>
export type VehicleEditFormData = z.output<typeof vehicleEditSchema>
