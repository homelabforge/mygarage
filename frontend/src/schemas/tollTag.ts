import { z } from 'zod'
import { notesSchema } from './shared'

/**
 * Toll tag schema matching backend Pydantic validators.
 * See: backend/app/schemas/toll.py
 */

export const TOLL_SYSTEMS = [
  'EZ TAG',
  'TxTag',
  'E-ZPass',
  'SunPass',
  'NTTA TollTag',
  'FasTrak',
  'I-PASS',
  'Other',
] as const

export const tollTagSchema = z.object({
  toll_system: z.enum(TOLL_SYSTEMS, {
    message: 'Toll system is required',
  }),
  tag_number: z
    .string()
    .min(1, 'Tag number is required')
    .max(50, 'Tag number too long (max 50 characters)'),
  status: z.enum(['active', 'inactive']).default('active'),
  notes: notesSchema.optional(),
})

export type TollTagFormData = z.infer<typeof tollTagSchema>
