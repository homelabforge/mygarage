import { z } from 'zod'
import { optionalStringToUndefined } from './shared'

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
  premium_amount: z.preprocess(
    optionalStringToUndefined,
    z.coerce.number().min(0, 'Premium amount cannot be negative').optional()
  ),
  premium_frequency: z.preprocess(
    optionalStringToUndefined,
    z.string().optional()
  ),
  deductible: z.preprocess(
    optionalStringToUndefined,
    z.coerce.number().min(0, 'Deductible cannot be negative').optional()
  ),
  coverage_limits: z.preprocess(optionalStringToUndefined, z.string().optional()),
  notes: z.preprocess(optionalStringToUndefined, z.string().optional()),
})

export type InsuranceFormData = z.infer<typeof insuranceSchema>
