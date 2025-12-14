import { z } from 'zod'

export const spotRentalBillingSchema = z.object({
  billing_date: z.string().min(1, 'Billing date is required'),
  monthly_rate: z.coerce
    .number()
    .nonnegative('Monthly rate must be 0 or greater')
    .optional()
    .nullable(),
  electric: z.coerce
    .number()
    .nonnegative('Electric cost must be 0 or greater')
    .optional()
    .nullable(),
  water: z.coerce
    .number()
    .nonnegative('Water cost must be 0 or greater')
    .optional()
    .nullable(),
  waste: z.coerce
    .number()
    .nonnegative('Waste cost must be 0 or greater')
    .optional()
    .nullable(),
  total: z.coerce
    .number()
    .nonnegative('Total must be 0 or greater')
    .optional()
    .nullable(),
  notes: z.string().max(1000, 'Notes must be 1000 characters or less').optional().nullable(),
})

export type SpotRentalBillingFormData = z.infer<typeof spotRentalBillingSchema>
