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
  year: z.coerce.number().int().min(1900).max(2100).optional(),
  make: z.string().optional(),
  model: z.string().optional(),

  // VIN Decoded Information
  trim: z.string().optional(),
  body_class: z.string().optional(),
  drive_type: z.string().optional(),
  doors: z.coerce.number().int().min(0).optional(),
  gvwr_class: z.string().optional(),

  // Engine & Transmission
  displacement_l: z.string().optional(), // Backend expects string
  cylinders: z.coerce.number().int().min(0).optional(),
  fuel_type: z.string().optional(),
  transmission_type: z.string().optional(),
  transmission_speeds: z.string().optional(),

  // Purchase Information
  purchase_date: z.string().optional(),
  purchase_price: z.coerce.number().optional(),

  // Sale Information
  sold_date: z.string().optional(),
  sold_price: z.coerce.number().optional(),
})

export type VehicleEditFormData = z.infer<typeof vehicleEditSchema>
