import { z } from 'zod'
import {
  dateSchema,
  optionalMileageSchema,
  optionalGallonsSchema,
  optionalCurrencySchema,
  optionalPricePerUnitSchema,
  optionalKwhSchema,
  notesSchema,
} from './shared'

/**
 * Fuel record schema matching backend Pydantic validators.
 * See: backend/app/schemas/fuel.py
 */

export const fuelRecordSchema = z.object({
  date: dateSchema,
  mileage: optionalMileageSchema,
  gallons: optionalGallonsSchema,
  propane_gallons: optionalGallonsSchema,
  kwh: optionalKwhSchema,
  cost: optionalCurrencySchema,
  price_per_unit: optionalPricePerUnitSchema,
  fuel_type: z.string().max(50, 'Fuel type too long').optional(),
  is_full_tank: z.boolean(),
  missed_fillup: z.boolean(),
  is_hauling: z.boolean(),
  notes: notesSchema.optional(),
})

// Export both input and output types for Zod v4 zodResolver compatibility
// z.input = what the form supplies (unknown for coerce fields)
// z.output = coerced result after validation (numbers)
export type FuelRecordInput = z.input<typeof fuelRecordSchema>
export type FuelRecordFormData = z.output<typeof fuelRecordSchema>
