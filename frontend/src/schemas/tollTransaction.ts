import { z } from 'zod'

export const tollTransactionSchema = z.object({
  transaction_date: z.string().min(1, 'Transaction date is required'),
  amount: z.coerce.number().min(0, 'Amount must be 0 or greater').optional(),
  location: z.string().min(1, 'Location is required'),
  toll_tag_id: z.coerce.number().optional(),
  notes: z.string().optional(),
})

export type TollTransactionFormData = z.infer<typeof tollTransactionSchema>
