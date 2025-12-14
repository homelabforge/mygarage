import { z } from 'zod'

export const propaneRecordSchema = z.object({
  date: z.string().min(1, 'Date is required'),
  propane_gallons: z.coerce
    .number()
    .positive('Propane must be greater than 0')
    .optional(),
  price_per_unit: z.coerce
    .number()
    .nonnegative('Price must be 0 or greater')
    .optional(),
  cost: z.coerce
    .number()
    .nonnegative('Cost must be 0 or greater')
    .optional(),
  vendor: z.string().max(100).optional(),
  notes: z.string().max(1000).optional(),
})

export type PropaneRecordFormData = z.infer<typeof propaneRecordSchema>
