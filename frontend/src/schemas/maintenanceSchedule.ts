import { z } from 'zod'
import { dateSchema, optionalMileageSchema } from './shared'

/**
 * Maintenance Schedule validation schemas matching backend Pydantic validators.
 * See: backend/app/schemas/maintenance_schedule.py
 */

// Component categories
export const COMPONENT_CATEGORIES = [
  'Engine',
  'Transmission',
  'Brakes',
  'Tires',
  'Electrical',
  'HVAC',
  'Fluids',
  'Suspension',
  'Body/Exterior',
  'Interior',
  'Exhaust',
  'Fuel System',
  'Other',
] as const

// Schedule item types
export const SCHEDULE_ITEM_TYPES = ['service', 'inspection'] as const

// Schedule item sources
export const SCHEDULE_ITEM_SOURCES = ['template', 'custom'] as const

// Create schedule item schema
export const maintenanceScheduleItemSchema = z.object({
  name: z
    .string()
    .min(1, 'Item name is required')
    .max(100, 'Item name too long (max 100 characters)'),
  component_category: z.enum(COMPONENT_CATEGORIES, {
    message: 'Please select a component category',
  }),
  item_type: z.enum(SCHEDULE_ITEM_TYPES, {
    message: 'Please select an item type',
  }),
  interval_months: z
    .number()
    .int('Interval must be a whole number')
    .min(1, 'Interval must be at least 1 month')
    .max(120, 'Interval cannot exceed 120 months')
    .optional()
    .or(z.nan())
    .transform(val => (typeof val === 'number' && isNaN(val) ? undefined : val)),
  interval_miles: z
    .number()
    .int('Interval must be a whole number')
    .min(100, 'Interval must be at least 100 miles')
    .max(200000, 'Interval cannot exceed 200,000 miles')
    .optional()
    .or(z.nan())
    .transform(val => (typeof val === 'number' && isNaN(val) ? undefined : val)),
  source: z.enum(SCHEDULE_ITEM_SOURCES).default('custom'),
  template_item_id: z.string().max(100).optional(),
})

// Require at least one interval
export const maintenanceScheduleItemSchemaRefined = maintenanceScheduleItemSchema.refine(
  (data) => {
    return data.interval_months !== undefined || data.interval_miles !== undefined
  },
  {
    message: 'At least one interval (months or miles) is required',
    path: ['interval_months'],
  }
)

// Update schedule item schema (all fields optional)
export const maintenanceScheduleItemUpdateSchema = z.object({
  name: z.string().min(1).max(100).optional(),
  component_category: z.enum(COMPONENT_CATEGORIES).optional(),
  item_type: z.enum(SCHEDULE_ITEM_TYPES).optional(),
  interval_months: z
    .number()
    .int()
    .min(1)
    .max(120)
    .optional()
    .or(z.nan())
    .transform(val => (typeof val === 'number' && isNaN(val) ? undefined : val)),
  interval_miles: z
    .number()
    .int()
    .min(100)
    .max(200000)
    .optional()
    .or(z.nan())
    .transform(val => (typeof val === 'number' && isNaN(val) ? undefined : val)),
  last_performed_date: dateSchema.optional(),
  last_performed_mileage: optionalMileageSchema,
})

// Apply template schema
export const applyTemplateSchema = z.object({
  template_source: z
    .string()
    .min(1, 'Template source is required')
    .max(50, 'Template source too long'),
  initial_date: dateSchema.optional(),
  initial_mileage: optionalMileageSchema,
})

export type MaintenanceScheduleItemInput = z.input<typeof maintenanceScheduleItemSchema>
export type MaintenanceScheduleItemFormData = z.output<typeof maintenanceScheduleItemSchema>
export type MaintenanceScheduleItemUpdateInput = z.input<typeof maintenanceScheduleItemUpdateSchema>
export type MaintenanceScheduleItemUpdateFormData = z.output<typeof maintenanceScheduleItemUpdateSchema>
export type ApplyTemplateInput = z.input<typeof applyTemplateSchema>
export type ApplyTemplateFormData = z.output<typeof applyTemplateSchema>
