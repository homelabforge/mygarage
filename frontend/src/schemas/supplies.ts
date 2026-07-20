import { z } from 'zod'
import type { TFunction } from 'i18next'

import { makeVinSchema } from './shared'

/**
 * Supply validation schema.
 *
 * Factory, not a constant — see the header of schemas/auth.ts for why.
 */

export const SUPPLY_UNIT_TYPES = ['volume', 'count'] as const

export const makeSupplySchema = (t: TFunction) =>
  z.object({
    name: z
      .string()
      .min(1, t('common:validation.supply.nameRequired'))
      .max(120, t('common:validation.supply.nameTooLong')),
    unit_type: z.enum(SUPPLY_UNIT_TYPES, {
      message: t('common:validation.supply.unitTypeRequired'),
    }),
    part_number: z.string().max(60, t('common:validation.supply.partNumberTooLong')).optional(),
    category: z.string().max(40, t('common:validation.supply.categoryTooLong')).optional(),
    notes: z.string().max(5000, t('common:validation.supply.notesTooLong')).optional(),
    vin: makeVinSchema(t).or(z.literal('')).optional(),
  })

export type SupplyFormData = z.infer<ReturnType<typeof makeSupplySchema>>
