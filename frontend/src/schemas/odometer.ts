import { z } from 'zod'
import { dateSchema, odometerSchema, notesSchema } from './shared'

/**
 * Odometer record schema matching backend Pydantic validators.
 * See: backend/app/schemas/odometer.py
 *
 * Field `odometer_km` is the form-side name; values represent the user's
 * displayed unit (km for metric, mi for imperial). The form converts to
 * canonical km via toCanonicalKm before submission.
 */

export const odometerRecordSchema = z.object({
  date: dateSchema,
  odometer_km: odometerSchema, // Required - min 0, max 9,999,999
  notes: notesSchema.optional(),
})

// Export both input and output types for Zod v4 zodResolver compatibility
export type OdometerRecordInput = z.input<typeof odometerRecordSchema>
export type OdometerRecordFormData = z.output<typeof odometerRecordSchema>
