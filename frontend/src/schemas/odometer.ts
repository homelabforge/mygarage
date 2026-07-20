import { z } from 'zod'
import type { TFunction } from 'i18next'
import { makeDateSchema, makeOdometerSchema, makeNotesSchema } from './shared'

/**
 * Odometer record schema matching backend Pydantic validators.
 * See: backend/app/schemas/odometer.py
 *
 * Field `odometer_km` is the form-side name; values represent the user's
 * displayed unit (km for metric, mi for imperial). The form converts to
 * canonical km via toCanonicalKm before submission.
 *
 * Factory, not a constant — see the header of schemas/auth.ts for why.
 */

export const makeOdometerRecordSchema = (t: TFunction) =>
  z.object({
    date: makeDateSchema(t),
    odometer_km: makeOdometerSchema(t), // Required - min 0, max 9,999,999
    notes: makeNotesSchema(t).optional(),
  })

// Export both input and output types for Zod v4 zodResolver compatibility
export type OdometerRecordInput = z.input<ReturnType<typeof makeOdometerRecordSchema>>
export type OdometerRecordFormData = z.output<ReturnType<typeof makeOdometerRecordSchema>>
