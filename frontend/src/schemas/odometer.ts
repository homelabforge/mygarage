import { z } from 'zod'
import { dateSchema, mileageSchema, notesSchema } from './shared'

/**
 * Odometer record schema matching backend Pydantic validators.
 * See: backend/app/schemas/odometer.py
 */

export const odometerRecordSchema = z.object({
  date: dateSchema,
  mileage: mileageSchema, // Required - integer, min 0, max 9,999,999
  notes: notesSchema.optional(),
})

// Export both input and output types for Zod v4 zodResolver compatibility
export type OdometerRecordInput = z.input<typeof odometerRecordSchema>
export type OdometerRecordFormData = z.output<typeof odometerRecordSchema>
