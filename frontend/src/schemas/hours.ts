import { z } from 'zod'
import type { TFunction } from 'i18next'
import { makeDateSchema, makeEngineHoursSchema, makeNotesSchema } from './shared'

/**
 * Hours record schema matching backend Pydantic validators.
 * See: backend/app/schemas/hours.py
 *
 * Engine-hours analog of schemas/odometer.ts (s/odometer_km/engine_hours/).
 * `engine_hours` is dimensionless -- no unit system and nothing to convert on
 * submit, unlike odometer_km, which seeds a `UnitFieldOrigin` on `u.distance`
 * and converts back through `canonicalFromUnitField`.
 *
 * Factory, not a constant — see the header of schemas/auth.ts for why.
 */

export const makeHoursRecordSchema = (t: TFunction) =>
  z.object({
    date: makeDateSchema(t),
    engine_hours: makeEngineHoursSchema(t), // Required - min 0, max 999,999,999.9
    notes: makeNotesSchema(t).optional(),
  })

// Export both input and output types for Zod v4 zodResolver compatibility
export type HoursRecordInput = z.input<ReturnType<typeof makeHoursRecordSchema>>
export type HoursRecordFormData = z.output<ReturnType<typeof makeHoursRecordSchema>>
