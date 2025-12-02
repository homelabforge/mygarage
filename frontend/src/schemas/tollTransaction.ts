import { z } from 'zod'
import { optionalStringToUndefined, coerceToNumber } from './shared'

export const tollTransactionSchema = z.object({
  transaction_date: z.string().min(1, 'Transaction date is required'),
  amount: coerceToNumber.refine(val => val !== undefined && val >= 0, {
    message: 'Amount must be 0 or greater',
  }),
  location: z.string().min(1, 'Location is required'),
  toll_tag_id: coerceToNumber.optional(),
  notes: optionalStringToUndefined,
})

export type TollTransactionFormData = z.infer<typeof tollTransactionSchema>
