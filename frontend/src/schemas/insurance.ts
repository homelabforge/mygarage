import { z } from 'zod'

/**
 * Insurance policy schema matching backend Pydantic validators.
 * See: backend/app/schemas/insurance.py
 */

export const POLICY_TYPES = [
  'Liability',
  'Comprehensive',
  'Collision',
  'Full Coverage',
  'Minimum',
  'Other',
] as const

export const PREMIUM_FREQUENCIES = [
  'Monthly',
  'Quarterly',
  'Semi-Annual',
  'Annual',
] as const

export const insuranceSchema = z.object({
  provider: z.string().min(1, 'Provider is required'),
  policy_number: z.string().min(1, 'Policy number is required'),
  policy_type: z.string().min(1, 'Policy type is required'),
  start_date: z.string().min(1, 'Start date is required'),
  end_date: z.string().min(1, 'End date is required'),
  premium_amount: z.string().optional(),
  premium_frequency: z.string().optional(),
  deductible: z.string().optional(),
  coverage_limits: z.string().optional(),
  notes: z.string().optional(),
})

export type InsuranceFormData = z.infer<typeof insuranceSchema>
