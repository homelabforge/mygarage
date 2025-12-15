import { z } from 'zod'

export const spotRentalBillingSchema = z.object({
  billing_date: z.string().min(1, 'Billing date is required'),
  monthly_rate: z
    .number()
    .nonnegative('Monthly rate must be 0 or greater')
    .or(z.nan())
    .transform(val => isNaN(val) ? undefined : val)
    .optional(),
  electric: z
    .number()
    .nonnegative('Electric cost must be 0 or greater')
    .or(z.nan())
    .transform(val => isNaN(val) ? undefined : val)
    .optional(),
  water: z
    .number()
    .nonnegative('Water cost must be 0 or greater')
    .or(z.nan())
    .transform(val => isNaN(val) ? undefined : val)
    .optional(),
  waste: z
    .number()
    .nonnegative('Waste cost must be 0 or greater')
    .or(z.nan())
    .transform(val => isNaN(val) ? undefined : val)
    .optional(),
  total: z
    .number()
    .nonnegative('Total must be 0 or greater')
    .or(z.nan())
    .transform(val => isNaN(val) ? undefined : val)
    .optional(),
  notes: z.string().max(1000, 'Notes must be 1000 characters or less').optional(),
})

export type SpotRentalBillingFormData = z.infer<typeof spotRentalBillingSchema>
