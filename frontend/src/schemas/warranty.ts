import { z } from 'zod'
import { optionalStringToUndefined, coerceToNumber } from './shared'

export const WARRANTY_TYPES = [
  'Manufacturer',
  'Powertrain',
  'Extended',
  'Bumper-to-Bumper',
  'Emissions',
  'Corrosion',
  'Other',
] as const

export const warrantySchema = z.object({
  warranty_type: z.string().min(1, 'Warranty type is required'),
  provider: optionalStringToUndefined,
  start_date: z.string().min(1, 'Start date is required'),
  end_date: optionalStringToUndefined,
  mileage_limit: coerceToNumber.optional(),
  coverage_details: optionalStringToUndefined,
  policy_number: optionalStringToUndefined,
  notes: optionalStringToUndefined,
})

export type WarrantyFormData = z.infer<typeof warrantySchema>
