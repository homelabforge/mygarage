import { z } from 'zod'
import {
  dateSchema,
  optionalMileageSchema,
  optionalGallonsSchema,
  optionalCurrencySchema,
  optionalPricePerUnitSchema,
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
  cost: optionalCurrencySchema,
  price_per_unit: optionalPricePerUnitSchema,
  fuel_type: z.string().max(50, 'Fuel type too long').optional(),
  is_full_tank: z.boolean().default(true).pipe(z.boolean()),
  missed_fillup: z.boolean().default(false).pipe(z.boolean()),
  is_hauling: z.boolean().default(false).pipe(z.boolean()),
  notes: notesSchema.optional(),
})

export type FuelRecordFormData = z.infer<typeof fuelRecordSchema>
