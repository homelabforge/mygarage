import { z } from 'zod'
import type { TFunction } from 'i18next'
import { makeDateSchema } from './shared'

/**
 * Note schema matching backend Pydantic validators.
 * See: backend/app/schemas/note.py
 *
 * Factory, not a constant — see the header of schemas/auth.ts for why.
 */

export const makeNoteSchema = (t: TFunction) =>
  z.object({
    date: makeDateSchema(t),
    title: z
      .string()
      .max(100, t('common:validation.note.titleTooLong'))
      .optional(),
    content: z
      .string()
      .min(1, t('common:validation.note.contentRequired'))
      .max(10000, t('common:validation.note.contentTooLong')),
  })

export type NoteFormData = z.infer<ReturnType<typeof makeNoteSchema>>
