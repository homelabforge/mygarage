import { z } from 'zod'
import type { TFunction } from 'i18next'
import { makeNotesSchema } from './shared'

/**
 * Toll tag schema matching backend Pydantic validators.
 * See: backend/app/schemas/toll.py
 *
 * Factory, not a constant — see the header of schemas/auth.ts for why.
 */

/**
 * Wire values. These are persisted and sent to the backend verbatim, so they
 * must never be translated — the dropdown renders the label looked up from
 * TOLL_SYSTEM_LABEL_KEYS instead.
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

export type TollSystemValue = (typeof TOLL_SYSTEMS)[number]

/**
 * Form options: API `value` plus the i18n `labelKey` resolved at render.
 *
 * Most of these are US brand names that stay as-is in every language, but they
 * still go through i18next so a locale that does transliterate (uk/ru) can, and
 * so 'Other' is actually translatable. Keys are namespace-qualified because
 * this module never calls useTranslation.
 */
export const TOLL_SYSTEM_OPTIONS = [
  { value: 'EZ TAG', labelKey: 'forms:tollSystems.ezTag' },
  { value: 'TxTag', labelKey: 'forms:tollSystems.txTag' },
  { value: 'E-ZPass', labelKey: 'forms:tollSystems.ezPass' },
  { value: 'SunPass', labelKey: 'forms:tollSystems.sunPass' },
  { value: 'NTTA TollTag', labelKey: 'forms:tollSystems.nttaTollTag' },
  { value: 'FasTrak', labelKey: 'forms:tollSystems.fasTrak' },
  { value: 'I-PASS', labelKey: 'forms:tollSystems.iPass' },
  { value: 'Other', labelKey: 'forms:tollSystems.other' },
] as const satisfies readonly { value: TollSystemValue; labelKey: string }[]

export const makeTollTagSchema = (t: TFunction) =>
  z.object({
    toll_system: z.enum(TOLL_SYSTEMS, {
      message: t('common:validation.tollTag.systemRequired'),
    }),
    tag_number: z
      .string()
      .min(1, t('common:validation.tollTag.tagNumberRequired'))
      .max(50, t('common:validation.tollTag.tagNumberTooLong')),
    status: z.enum(['active', 'inactive']),
    notes: makeNotesSchema(t).optional(),
  })

export type TollTagFormData = z.infer<ReturnType<typeof makeTollTagSchema>>
