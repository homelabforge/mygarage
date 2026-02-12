import { z } from 'zod'

import {
  dateSchema,
  notesSchema,
  optionalCurrencySchema,
  optionalGallonsSchema,
  optionalMileageSchema,
  optionalPricePerUnitSchema,
} from './shared'

export const defRecordSchema = z.object({
  date: dateSchema,
  mileage: optionalMileageSchema,
  gallons: optionalGallonsSchema,
  price_per_unit: optionalPricePerUnitSchema,
  cost: optionalCurrencySchema,
  fill_level: z
    .number()
    .min(0, 'Fill level cannot be negative')
    .max(100, 'Fill level cannot exceed 100%')
    .or(z.nan())
    .transform(val => isNaN(val) ? undefined : val)
    .optional(),
  source: z.string().max(100).optional(),
  brand: z.string().max(100).optional(),
  notes: notesSchema.optional(),
})

export type DefRecordFormData = z.infer<typeof defRecordSchema>
