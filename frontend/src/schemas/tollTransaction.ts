import { z } from 'zod'

const amountSchema = z
  .number()
  .min(0, 'Amount must be 0 or greater')
  .or(z.nan())
  .transform(val => isNaN(val) ? undefined : val)
  .optional()
  .nullable()

const tollTagIdSchema = z
  .number()
  .or(z.nan())
  .transform(val => isNaN(val) ? undefined : val)
  .optional()
  .nullable()

export const tollTransactionSchema = z.object({
  transaction_date: z.string().min(1, 'Transaction date is required'),
  amount: amountSchema,
  location: z.string().min(1, 'Location is required'),
  toll_tag_id: tollTagIdSchema,
  notes: z.string().optional(),
})

export type TollTransactionInput = z.input<typeof tollTransactionSchema>
export type TollTransactionFormData = z.output<typeof tollTransactionSchema>
