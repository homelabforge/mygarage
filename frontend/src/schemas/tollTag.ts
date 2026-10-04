import { z } from 'zod'
import type { TFunction } from 'i18next'
import { makeNotesSchema } from './shared'
import { TOLL_OTHER, canonicalTollSystem, findTollCountry } from '../utils/tollSystems'

/**
 * Toll tag schema matching backend Pydantic validators.
 * See: backend/app/schemas/toll.py
 *
 * Factory, not a constant. See the header of schemas/auth.ts for why.
 *
 * toll_country and toll_system are the two dropdowns and toll_system_other is
 * the typed name. Only selectedTollSystem() of the three goes to the API; the
 * country is just a filter.
 */

/** The API's max_length for toll_system. */
export const TOLL_SYSTEM_MAX = 50

export const makeTollTagSchema = (t: TFunction) =>
  z
    .object({
      toll_country: z.string(),
      toll_system: z.string(),
      toll_system_other: z.string(),
      tag_number: z
        .string()
        .min(1, t('common:validation.tollTag.tagNumberRequired'))
        .max(50, t('common:validation.tollTag.tagNumberTooLong')),
      status: z.enum(['active', 'inactive']),
      notes: makeNotesSchema(t).optional(),
    })
    .superRefine((data, ctx) => {
      const checkName = () => {
        const name = canonicalTollSystem(data.toll_system_other)
        if (name === '') {
          ctx.addIssue({ code: 'custom', path: ['toll_system_other'], message: t('common:validation.tollTag.systemNameRequired') })
        } else if (name.length > TOLL_SYSTEM_MAX) {
          ctx.addIssue({ code: 'custom', path: ['toll_system_other'], message: t('common:validation.tollTag.systemNameTooLong') })
        }
      }
      if (data.toll_country === TOLL_OTHER) return checkName()
      const country = findTollCountry(data.toll_country)
      if (!country) {
        ctx.addIssue({ code: 'custom', path: ['toll_country'], message: t('common:validation.tollTag.countryRequired') })
        return
      }
      if (data.toll_system === TOLL_OTHER) return checkName()
      if (!country.systems.includes(data.toll_system)) {
        ctx.addIssue({ code: 'custom', path: ['toll_system'], message: t('common:validation.tollTag.systemRequired') })
      }
    })

export type TollTagFormData = z.infer<ReturnType<typeof makeTollTagSchema>>
