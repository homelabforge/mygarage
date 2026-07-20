import { z } from 'zod'
import type { TFunction } from 'i18next'

import {
  makeDateSchema,
  makeNotesSchema,
  makeOptionalCurrencySchema,
  makeOptionalVolumeSchema,
  makeOptionalOdometerSchema,
  makeOptionalPricePerUnitSchema,
} from './shared'

/**
 * DEF record schema matching backend Pydantic validators.
 * See: backend/app/schemas/def_record.py
 *
 * Factory, not a constant — see the header of schemas/auth.ts for why.
 */

export const makeDefRecordSchema = (t: TFunction) =>
  z.object({
    date: makeDateSchema(t),
    odometer_km: makeOptionalOdometerSchema(t),
    liters: makeOptionalVolumeSchema(t),
    price_per_unit: makeOptionalPricePerUnitSchema(t),
    cost: makeOptionalCurrencySchema(t),
    fill_level: z
      .number()
      .min(0, t('common:validation.def.fillLevelNegative'))
      .max(100, t('common:validation.def.fillLevelTooLarge'))
      .or(z.nan())
      .transform(val => isNaN(val) ? undefined : val)
      .optional(),
    source: z.string().max(100).optional(),
    brand: z.string().max(100).optional(),
    notes: makeNotesSchema(t).optional(),
  })

export type DefRecordFormData = z.infer<ReturnType<typeof makeDefRecordSchema>>
