import { z } from 'zod'
import {
  dateSchema,
  optionalMileageSchema,
  optionalCurrencySchema,
  vendorNameSchema,
} from './shared'
import { SERVICE_TYPES_BY_CATEGORY } from '../types/service'

/**
 * Service record schema matching backend Pydantic validators.
 * See: backend/app/schemas/service.py
 */

// Valid service categories from backend validator
export const SERVICE_CATEGORIES = ['Maintenance', 'Inspection', 'Collision', 'Upgrades'] as const

// All valid service types (flat list from SERVICE_TYPES_BY_CATEGORY)
export const ALL_SERVICE_TYPES = Object.values(SERVICE_TYPES_BY_CATEGORY).flat()

// Export the grouped service types for use in forms
export { SERVICE_TYPES_BY_CATEGORY }

export const serviceRecordSchema = z.object({
  date: dateSchema,
  mileage: optionalMileageSchema,
  service_type: z
    .string()
    .min(1, 'Service type is required')
    .max(100, 'Service type too long (max 100 characters)'),
  cost: optionalCurrencySchema,
  notes: z.string().max(5000, 'Notes too long (max 5000 characters)').optional(),
  vendor_name: vendorNameSchema.optional(),
  vendor_location: z.string().max(100, 'Location too long (max 100 characters)').optional(),
  service_category: z.enum(SERVICE_CATEGORIES, {
    message: 'Please select a valid service category',
  }).optional(),
  insurance_claim: z.string().max(50, 'Insurance claim too long (max 50 characters)').optional(),
})

// Use z.output for Zod v4 compatibility with z.coerce fields
export type ServiceRecordInput = z.input<typeof serviceRecordSchema>
export type ServiceRecordFormData = z.output<typeof serviceRecordSchema>
