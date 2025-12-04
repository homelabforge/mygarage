import { z } from 'zod'
import { dateSchema, notesSchema } from './shared'

/**
 * Spot rental schema matching backend Pydantic validators.
 * See: backend/app/schemas/spot_rental.py
 *
 * CRITICAL: This schema fixes 8 missing isNaN validation bugs in SpotRentalForm
 */

// Currency validators specific to spot rental limits - use z.coerce to handle string inputs
const nightlyRateSchema = z.coerce
  .number()
  .min(0, 'Nightly rate cannot be negative')
  .max(9999.99, 'Nightly rate too large (max $9,999.99)')

const largeRateSchema = z.coerce
  .number()
  .min(0, 'Rate cannot be negative')
  .max(99999.99, 'Rate too large (max $99,999.99)')

const utilitySchema = z.coerce
  .number()
  .min(0, 'Utility cost cannot be negative')
  .max(9999.99, 'Utility cost too large (max $9,999.99)')

// Optional versions - use .optional() directly with z.coerce
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

// Use z.output for Zod v4 compatibility with z.coerce fields
export type SpotRentalInput = z.input<typeof spotRentalSchema>
export type SpotRentalFormData = z.output<typeof spotRentalSchema>
