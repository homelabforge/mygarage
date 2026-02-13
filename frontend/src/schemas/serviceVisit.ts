import { z } from 'zod'
import {
  dateSchema,
  optionalMileageSchema,
  optionalCurrencySchema,
} from './shared'
// Service categories matching backend Literal type
export const SERVICE_CATEGORIES = ['Maintenance', 'Inspection', 'Collision', 'Upgrades', 'Detailing'] as const

/**
 * Service Visit validation schemas matching backend Pydantic validators.
 * See: backend/app/schemas/service_visit.py
 */

// Inspection result values
export const INSPECTION_RESULTS = ['passed', 'failed', 'needs_attention'] as const
export const INSPECTION_SEVERITIES = ['green', 'yellow', 'red'] as const

// Service line item schema
export const serviceLineItemSchema = z.object({
  description: z
    .string()
    .min(1, 'Description is required')
    .max(200, 'Description too long (max 200 characters)'),
  cost: optionalCurrencySchema,
  notes: z.string().max(1000, 'Notes too long (max 1000 characters)').optional(),
  is_inspection: z.boolean().default(false),
  inspection_result: z
    .enum(INSPECTION_RESULTS, { message: 'Invalid inspection result' })
    .optional()
    .or(z.literal('')),
  inspection_severity: z
    .enum(INSPECTION_SEVERITIES, { message: 'Invalid inspection severity' })
    .optional()
    .or(z.literal('')),
  schedule_item_id: z
    .number()
    .int()
    .positive()
    .optional()
    .or(z.nan())
    .transform(val => (typeof val === 'number' && isNaN(val) ? undefined : val)),
  triggered_by_inspection_id: z
    .number()
    .int()
    .positive()
    .optional()
    .or(z.nan())
    .transform(val => (typeof val === 'number' && isNaN(val) ? undefined : val)),
})

// Service visit schema
export const serviceVisitSchema = z.object({
  vendor_id: z
    .number()
    .int()
    .positive()
    .optional()
    .or(z.nan())
    .transform(val => (typeof val === 'number' && isNaN(val) ? undefined : val)),
  date: dateSchema,
  mileage: optionalMileageSchema,
  notes: z.string().max(5000, 'Notes too long (max 5000 characters)').optional(),
  service_category: z
    .enum(SERVICE_CATEGORIES, { message: 'Please select a valid service category' })
    .optional()
    .or(z.literal('')),
  insurance_claim_number: z
    .string()
    .max(50, 'Insurance claim number too long (max 50 characters)')
    .optional(),
  line_items: z
    .array(serviceLineItemSchema)
    .min(1, 'At least one line item is required'),
})

// Refine to validate inspection fields are set when is_inspection is true
export const serviceVisitSchemaRefined = serviceVisitSchema.refine(
  (data) => {
    for (const item of data.line_items) {
      if (item.is_inspection && !item.inspection_result) {
        return false
      }
    }
    return true
  },
  {
    message: 'Inspection result is required for inspection items',
    path: ['line_items'],
  }
)

export type ServiceLineItemInput = z.input<typeof serviceLineItemSchema>
export type ServiceLineItemFormData = z.output<typeof serviceLineItemSchema>
export type ServiceVisitInput = z.input<typeof serviceVisitSchema>
export type ServiceVisitFormData = z.output<typeof serviceVisitSchema>
