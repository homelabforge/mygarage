import { z } from 'zod'
import { dateSchema, notesSchema } from './shared'

/**
 * Recall schema matching backend Pydantic validators.
 * See: backend/app/schemas/recall.py
 */

export const recallSchema = z.object({
  nhtsa_campaign_number: z
    .string()
    .max(50, 'Campaign number too long (max 50 characters)')
    .optional(),
  component: z
    .string()
    .min(1, 'Component is required')
    .max(200, 'Component description too long (max 200 characters)'),
  summary: z
    .string()
    .min(1, 'Summary is required')
    .max(2000, 'Summary too long (max 2,000 characters)'),
  consequence: z
    .string()
    .max(2000, 'Consequence description too long (max 2,000 characters)')
    .optional(),
  remedy: z
    .string()
    .max(2000, 'Remedy description too long (max 2,000 characters)')
    .optional(),
  date_announced: dateSchema.optional(),
  is_resolved: z.boolean(),
  notes: notesSchema.optional(),
})

export type RecallFormData = z.infer<typeof recallSchema>
