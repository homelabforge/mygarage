import { z } from 'zod'

/**
 * Shared validation schemas for common field types across the application.
 * These ensure consistency with backend Pydantic validators.
 */

// Numeric validators - required number fields
// Using direct number validation (forms use valueAsNumber: true)
export const mileageSchema = z
  .number()
  .int('Mileage must be a whole number')
  .min(0, 'Mileage cannot be negative')
  .max(9999999, 'Mileage too large')

export const currencySchema = z
  .number()
  .min(0, 'Amount cannot be negative')
  .max(99999.99, 'Amount too large')

export const gallonsSchema = z
  .number()
  .min(0, 'Gallons cannot be negative')
  .max(999.999, 'Gallons too large')

export const pricePerUnitSchema = z
  .number()
  .min(0, 'Price cannot be negative')
  .max(999.99, 'Price too large')

// Date validators
export const dateSchema = z
  .string()
  .min(1, 'Date is required')
  .regex(/^\d{4}-\d{2}-\d{2}$/, 'Invalid date format')

// Text validators
export const descriptionSchema = z
  .string()
  .min(1, 'Description is required')
  .max(500, 'Description too long (max 500 characters)')

export const notesSchema = z.string().max(1000, 'Notes too long (max 1000 characters)')

export const vendorNameSchema = z.string().max(100, 'Vendor name too long (max 100 characters)')

// VIN validator
export const vinSchema = z
  .string()
  .length(17, 'VIN must be exactly 17 characters')
  .regex(/^[A-HJ-NPR-Z0-9]{17}$/, 'Invalid VIN format')

// Optional numeric fields - define as base schema then make optional
// Forms use valueAsNumber: true, so empty fields become NaN
// Transform NaN to undefined for optional fields
export const optionalMileageSchema = z
  .number()
  .int('Mileage must be a whole number')
  .min(0, 'Mileage cannot be negative')
  .max(9999999, 'Mileage too large')
  .or(z.nan())
  .transform(val => isNaN(val) ? undefined : val)
  .optional()
  .nullable()

export const optionalCurrencySchema = z
  .number()
  .min(0, 'Amount cannot be negative')
  .max(99999.99, 'Amount too large')
  .or(z.nan())
  .transform(val => isNaN(val) ? undefined : val)
  .optional()
  .nullable()

export const optionalGallonsSchema = z
  .number()
  .min(0, 'Gallons cannot be negative')
  .max(999.999, 'Gallons too large')
  .or(z.nan())
  .transform(val => isNaN(val) ? undefined : val)
  .optional()
  .nullable()

export const optionalPricePerUnitSchema = z
  .number()
  .min(0, 'Price cannot be negative')
  .max(999.99, 'Price too large')
  .or(z.nan())
  .transform(val => isNaN(val) ? undefined : val)
  .optional()
  .nullable()

// kWh validator for electric vehicles
export const optionalKwhSchema = z
  .number()
  .min(0, 'kWh cannot be negative')
  .max(99999.999, 'kWh too large')
  .or(z.nan())
  .transform(val => isNaN(val) ? undefined : val)
  .optional()
  .nullable()
