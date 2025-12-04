import { z } from 'zod'
import { dateSchema, notesSchema } from './shared'

/**
 * Spot rental schema matching backend Pydantic validators.
 * See: backend/app/schemas/spot_rental.py
 *
 * CRITICAL: This schema fixes 8 missing isNaN validation bugs in SpotRentalForm
 */

// Currency validators specific to spot rental limits
const nightlyRateSchema = z.coerce
  .number({
    message: 'Nightly rate must be a number',
  })
  .min(0, 'Nightly rate cannot be negative')
  .max(9999.99, 'Nightly rate too large (max $9,999.99)')

const largeRateSchema = z.coerce
  .number({
    message: 'Rate must be a number',
  })
  .min(0, 'Rate cannot be negative')
  .max(99999.99, 'Rate too large (max $99,999.99)')

const utilitySchema = z.coerce
  .number({
    message: 'Utility cost must be a number',
  })
  .min(0, 'Utility cost cannot be negative')
  .max(9999.99, 'Utility cost too large (max $9,999.99)')

// Optional versions - React Hook Form's zodResolver automatically converts empty strings to undefined
const optionalNightlyRateSchema = nightlyRateSchema.optional()

const optionalLargeRateSchema = largeRateSchema.optional()

const optionalUtilitySchema = utilitySchema.optional()

export const spotRentalSchema = z.object({
  location_name: z.string().max(100, 'Location name too long (max 100 characters)').optional(),
  location_address: z.string().optional(),
  check_in_date: dateSchema,
  check_out_date: z.string().optional(),
  nightly_rate: optionalNightlyRateSchema,
  weekly_rate: optionalLargeRateSchema,
  monthly_rate: optionalLargeRateSchema,
  electric: optionalUtilitySchema,
  water: optionalUtilitySchema,
  waste: optionalUtilitySchema,
  total_cost: optionalLargeRateSchema,
  amenities: z.string().optional(),
  notes: notesSchema.optional(),
})

export type SpotRentalFormData = z.infer<typeof spotRentalSchema>
