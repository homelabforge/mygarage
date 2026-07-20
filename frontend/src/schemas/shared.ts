import { z } from 'zod'
import type { TFunction } from 'i18next'

/**
 * Shared validation schemas for common field types across the application.
 * These ensure consistency with backend Pydantic validators.
 *
 * Every validator here is a FACTORY, not a module-level constant — see the
 * header of schemas/auth.ts for why. Consumers are themselves factories that
 * thread `t` straight through, so a language change rebuilds the whole tree.
 *
 * Keys are namespace-qualified (`common:…`) because this module never calls
 * useTranslation and its consumers are bound to several namespaces.
 */

// Numeric validators - required number fields
// Using direct number validation (forms use valueAsNumber: true)
// Odometer stored in km (Decimal) on backend; form accepts decimals. Imperial
// users enter miles (displayed via UnitConverter) and the submit path converts
// to km via toCanonicalKm.
export const makeOdometerSchema = (t: TFunction) =>
  z
    .number()
    .min(0, t('common:validation.odometer.negative'))
    .max(9999999, t('common:validation.odometer.tooLarge'))

export const makeCurrencySchema = (t: TFunction) =>
  z
    .number()
    .min(0, t('common:validation.amount.negative'))
    .max(99999.99, t('common:validation.amount.tooLarge'))

export const makeVolumeSchema = (t: TFunction) =>
  z
    .number()
    .min(0, t('common:validation.volume.negative'))
    .max(9999.999, t('common:validation.volume.tooLarge'))

export const makePricePerUnitSchema = (t: TFunction) =>
  z
    .number()
    .min(0, t('common:validation.price.negative'))
    .max(999.99, t('common:validation.price.tooLarge'))

// Date validators
export const makeDateSchema = (t: TFunction) =>
  z
    .string()
    .min(1, t('common:validation.date.required'))
    .regex(/^\d{4}-\d{2}-\d{2}$/, t('common:validation.date.invalidFormat'))

// Text validators
export const makeDescriptionSchema = (t: TFunction) =>
  z
    .string()
    .min(1, t('common:validation.description.required'))
    .max(500, t('common:validation.description.tooLong'))

export const makeNotesSchema = (t: TFunction) =>
  z.string().max(1000, t('common:validation.notes.tooLong'))

export const makeVendorNameSchema = (t: TFunction) =>
  z.string().max(100, t('common:validation.vendorName.tooLong'))

// VIN validator
export const makeVinSchema = (t: TFunction) =>
  z
    .string()
    .length(17, t('common:validation.vin.length'))
    .regex(/^[A-HJ-NPR-Z0-9]{17}$/, t('common:validation.vin.invalidFormat'))

// Optional numeric fields - define as base schema then make optional
// Forms use valueAsNumber: true, so empty fields become NaN
// Transform NaN to undefined for optional fields
export const makeOptionalOdometerSchema = (t: TFunction) =>
  z
    .number()
    .min(0, t('common:validation.odometer.negative'))
    .max(9999999, t('common:validation.odometer.tooLarge'))
    .or(z.nan())
    .transform(val => isNaN(val) ? undefined : val)
    .optional()

export const makeOptionalCurrencySchema = (t: TFunction) =>
  z
    .number()
    .min(0, t('common:validation.amount.negative'))
    .max(99999.99, t('common:validation.amount.tooLarge'))
    .or(z.nan())
    .transform(val => isNaN(val) ? undefined : val)
    .optional()

export const makeOptionalVolumeSchema = (t: TFunction) =>
  z
    .number()
    .min(0, t('common:validation.volume.negative'))
    .max(9999.999, t('common:validation.volume.tooLarge'))
    .or(z.nan())
    .transform(val => isNaN(val) ? undefined : val)
    .optional()

export const makeOptionalPricePerUnitSchema = (t: TFunction) =>
  z
    .number()
    .min(0, t('common:validation.price.negative'))
    .max(999.99, t('common:validation.price.tooLarge'))
    .or(z.nan())
    .transform(val => isNaN(val) ? undefined : val)
    .optional()

// kWh validator for electric vehicles
export const makeOptionalKwhSchema = (t: TFunction) =>
  z
    .number()
    .min(0, t('common:validation.kwh.negative'))
    .max(99999.999, t('common:validation.kwh.tooLarge'))
    .or(z.nan())
    .transform(val => isNaN(val) ? undefined : val)
    .optional()
