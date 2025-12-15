import { z } from 'zod'

export const spotRentalBillingSchema = z.object({
  billing_date: z.string().min(1, 'Billing date is required'),
  monthly_rate: z
    .number()
    .nonnegative('Monthly rate must be 0 or greater')
    .or(z.nan())
    .transform(val => isNaN(val) ? undefined : val)
    .optional()
    .nullable(),
  electric: z
    .number()
    .nonnegative('Electric cost must be 0 or greater')
    .or(z.nan())
    .transform(val => isNaN(val) ? undefined : val)
    .optional()
    .nullable(),
  water: z
    .number()
    .nonnegative('Water cost must be 0 or greater')
    .or(z.nan())
    .transform(val => isNaN(val) ? undefined : val)
    .optional()
    .nullable(),
  waste: z
    .number()
    .nonnegative('Waste cost must be 0 or greater')
    .or(z.nan())
    .transform(val => isNaN(val) ? undefined : val)
    .optional()
    .nullable(),
  total: z
    .number()
    .nonnegative('Total must be 0 or greater')
    .or(z.nan())
    .transform(val => isNaN(val) ? undefined : val)
    .optional()
    .nullable(),
  notes: z.string().max(1000, 'Notes must be 1000 characters or less').optional().nullable(),
})

export type SpotRentalBillingFormData = z.infer<typeof spotRentalBillingSchema>
