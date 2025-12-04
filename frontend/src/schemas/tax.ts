import { z } from 'zod'
import { dateSchema, currencySchema, notesSchema } from './shared'

/**
 * Tax record schema matching backend Pydantic validators.
 * See: backend/app/schemas/tax.py
 */

export const TAX_TYPES = ['Registration', 'Inspection', 'Property Tax', 'Tolls'] as const

export const taxRecordSchema = z.object({
  date: dateSchema,
  tax_type: z.enum(TAX_TYPES).optional(),
  amount: currencySchema,
  renewal_date: dateSchema.optional(),
  notes: notesSchema.optional(),
})

// Use z.output for Zod v4 compatibility with z.coerce fields
export type TaxRecordInput = z.input<typeof taxRecordSchema>
export type TaxRecordFormData = z.output<typeof taxRecordSchema>
