import { z } from 'zod'
import type { TFunction } from 'i18next'
import { makeDateSchema, makeNotesSchema } from './shared'

/**
 * Spot rental schema matching backend Pydantic validators.
 * See: backend/app/schemas/spot_rental.py
 *
 * CRITICAL: This schema fixes 8 missing isNaN validation bugs in SpotRentalForm
 *
 * Factory, not a constant — see the header of schemas/auth.ts for why.
 */

// Currency validators specific to spot rental limits - forms use valueAsNumber: true
const makeNightlyRateSchema = (t: TFunction) =>
  z
    .number()
    .min(0, t('common:validation.spotRental.nightlyRateNegative'))
    .max(9999.99, t('common:validation.spotRental.nightlyRateTooLarge'))

const makeLargeRateSchema = (t: TFunction) =>
  z
    .number()
    .min(0, t('common:validation.spotRental.rateNegative'))
    .max(99999.99, t('common:validation.spotRental.rateTooLarge'))

const makeUtilitySchema = (t: TFunction) =>
  z
    .number()
    .min(0, t('common:validation.spotRental.utilityNegative'))
    .max(9999.99, t('common:validation.spotRental.utilityTooLarge'))

// Optional versions - handle NaN from empty inputs
const makeOptionalNightlyRateSchema = (t: TFunction) =>
  makeNightlyRateSchema(t)
    .or(z.nan())
    .transform(val => isNaN(val) ? undefined : val)
    .optional()

const makeOptionalLargeRateSchema = (t: TFunction) =>
  makeLargeRateSchema(t)
    .or(z.nan())
    .transform(val => isNaN(val) ? undefined : val)
    .optional()

const makeOptionalUtilitySchema = (t: TFunction) =>
  makeUtilitySchema(t)
    .or(z.nan())
    .transform(val => isNaN(val) ? undefined : val)
    .optional()

export const makeSpotRentalSchema = (t: TFunction) =>
  z.object({
    location_name: z
      .string()
      .max(100, t('common:validation.spotRental.locationNameTooLong'))
      .optional(),
    location_address: z.string().optional(),
    check_in_date: makeDateSchema(t),
    check_out_date: z.string().optional(),
    nightly_rate: makeOptionalNightlyRateSchema(t),
    weekly_rate: makeOptionalLargeRateSchema(t),
    monthly_rate: makeOptionalLargeRateSchema(t),
    electric: makeOptionalUtilitySchema(t),
    water: makeOptionalUtilitySchema(t),
    waste: makeOptionalUtilitySchema(t),
    total_cost: makeOptionalLargeRateSchema(t),
    amenities: z.string().optional(),
    notes: makeNotesSchema(t).optional(),
  })

// Use z.output for Zod v4 compatibility with z.coerce fields
export type SpotRentalInput = z.input<ReturnType<typeof makeSpotRentalSchema>>
export type SpotRentalFormData = z.output<ReturnType<typeof makeSpotRentalSchema>>
