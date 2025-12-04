import { z } from 'zod'

const amountSchema = z.coerce
  .number()
  .min(0, 'Amount must be 0 or greater')
  .optional()

const tollTagIdSchema = z.coerce.number().optional()

export const tollTransactionSchema = z.object({
  transaction_date: z.string().min(1, 'Transaction date is required'),
  amount: amountSchema,
  location: z.string().min(1, 'Location is required'),
  toll_tag_id: tollTagIdSchema,
  notes: z.string().optional(),
})

// Use z.output for Zod v4 compatibility with z.coerce fields
export type TollTransactionInput = z.input<typeof tollTransactionSchema>
export type TollTransactionFormData = z.output<typeof tollTransactionSchema>
