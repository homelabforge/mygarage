import { z } from 'zod'
import { dateSchema, notesSchema } from './shared'

/**
 * Note schema matching backend Pydantic validators.
 * See: backend/app/schemas/note.py
 */

export const noteSchema = z.object({
  date: dateSchema,
  title: z
    .string()
    .max(100, 'Title too long (max 100 characters)')
    .optional(),
  content: z
    .string()
    .min(1, 'Content is required')
    .max(10000, 'Content too long (max 10,000 characters)'),
})

export type NoteFormData = z.infer<typeof noteSchema>
