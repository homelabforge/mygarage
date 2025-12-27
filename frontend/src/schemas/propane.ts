import { z } from 'zod'

export const propaneRecordSchema = z.object({
  date: z.string().min(1, 'Date is required'),
  propane_gallons: z
    .number()
    .positive('Propane must be greater than 0')
    .or(z.nan())
    .transform(val => isNaN(val) ? undefined : val)
    .optional(),
  tank_size_lb: z
    .number()
    .positive('Tank size must be greater than 0')
    .or(z.nan())
    .transform(val => isNaN(val) ? undefined : val)
    .optional(),
  tank_quantity: z
    .number()
    .int('Tank quantity must be a whole number')
    .positive('Tank quantity must be greater than 0')
    .or(z.nan())
    .transform(val => isNaN(val) ? undefined : val)
    .optional(),
  price_per_unit: z
    .number()
    .nonnegative('Price must be 0 or greater')
    .or(z.nan())
    .transform(val => isNaN(val) ? undefined : val)
    .optional(),
  cost: z
    .number()
    .nonnegative('Cost must be 0 or greater')
    .or(z.nan())
    .transform(val => isNaN(val) ? undefined : val)
    .optional(),
  vendor: z.string().max(100).optional(),
  notes: z.string().max(1000).optional(),
})

export type PropaneRecordFormData = z.infer<typeof propaneRecordSchema>
