import { z } from 'zod'
import type { TFunction } from 'i18next'
import { makeDateSchema, makeOdometerSchema, makeNotesSchema } from './shared'

/**
 * Odometer record schema matching backend Pydantic validators.
 * See: backend/app/schemas/odometer.py
 *
 * Field `odometer_km` is the form-side name; values represent the user's
 * displayed unit (km for metric, mi for imperial). The form converts to
 * canonical km via `canonicalFromUnitField` against a seeded `UnitFieldOrigin`
 * on `u.distance` (see OdometerRecordForm.tsx). The binary `toCanonicalKm` this
 * path used to call was deleted in phase 3b task 5 (ruling R8), so there is no
 * longer a second way to write this field.
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
