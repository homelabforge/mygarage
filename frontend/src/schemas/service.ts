import { z } from 'zod'
import {
  dateSchema,
  optionalMileageSchema,
  optionalCurrencySchema,
  vendorNameSchema,
  notesSchema,
} from './shared'

/**
 * Service record schema matching backend Pydantic validators.
 * See: backend/app/schemas/service.py
 */

// Valid service types from backend validator
export const SERVICE_TYPES = ['Maintenance', 'Inspection', 'Collision', 'Upgrades'] as const

export const serviceRecordSchema = z.object({
  date: dateSchema,
  mileage: optionalMileageSchema,
  description: z
    .string()
    .min(1, 'Description is required')
    .max(200, 'Description too long (max 200 characters)'),
  cost: optionalCurrencySchema,
  notes: z.string().max(5000, 'Notes too long (max 5000 characters)').optional(),
  vendor_name: vendorNameSchema.optional(),
  vendor_location: z.string().max(100, 'Location too long (max 100 characters)').optional(),
  service_type: z.enum(SERVICE_TYPES, {
    errorMap: () => ({ message: 'Please select a valid service type' }),
  }).optional(),
  insurance_claim: z.string().max(50, 'Insurance claim too long (max 50 characters)').optional(),
})

export type ServiceRecordFormData = z.infer<typeof serviceRecordSchema>
