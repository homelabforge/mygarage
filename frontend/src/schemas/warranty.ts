import { z } from 'zod'

export const WARRANTY_TYPES = [
  'Manufacturer',
  'Powertrain',
  'Extended',
  'Bumper-to-Bumper',
  'Emissions',
  'Corrosion',
  'Other',
] as const

const mileageLimitSchema = z
  .number()
  .int('Mileage must be a whole number')
  .min(0, 'Mileage cannot be negative')
  .or(z.nan())
  .transform(val => isNaN(val) ? undefined : val)
  .optional()
  .nullable()

export const warrantySchema = z.object({
  warranty_type: z.string().min(1, 'Warranty type is required'),
  provider: z.string().optional(),
  start_date: z.string().min(1, 'Start date is required'),
  end_date: z.string().optional(),
  mileage_limit: mileageLimitSchema,
  coverage_details: z.string().optional(),
  policy_number: z.string().optional(),
  notes: z.string().optional(),
})

export type WarrantyInput = z.input<typeof warrantySchema>
export type WarrantyFormData = z.output<typeof warrantySchema>
