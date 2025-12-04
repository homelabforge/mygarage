import { z } from 'zod'

/**
 * Shared validation schemas for common field types across the application.
 * These ensure consistency with backend Pydantic validators.
 */

// Numeric validators
export const mileageSchema = z.coerce
  .number()
  .int('Mileage must be a whole number')
  .min(0, 'Mileage cannot be negative')
  .max(9999999, 'Mileage too large')

export const currencySchema = z.coerce
  .number()
  .min(0, 'Amount cannot be negative')
  .max(99999.99, 'Amount too large')

export const gallonsSchema = z.coerce
  .number()
  .min(0, 'Gallons cannot be negative')
  .max(999.999, 'Gallons too large')

export const pricePerUnitSchema = z.coerce
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

// Optional numeric fields - React Hook Form's zodResolver automatically converts empty strings to undefined
export const optionalMileageSchema = mileageSchema.optional()

export const optionalCurrencySchema = currencySchema.optional()

export const optionalGallonsSchema = gallonsSchema.optional()

export const optionalPricePerUnitSchema = pricePerUnitSchema.optional()
