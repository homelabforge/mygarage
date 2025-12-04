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

export const warrantySchema = z.object({
  warranty_type: z.string().min(1, 'Warranty type is required'),
  provider: z.string().optional(),
  start_date: z.string().min(1, 'Start date is required'),
  end_date: z.string().optional(),
  mileage_limit: z.number().optional(),
  coverage_details: z.string().optional(),
  policy_number: z.string().optional(),
  notes: z.string().optional(),
})

export type WarrantyFormData = z.infer<typeof warrantySchema>
