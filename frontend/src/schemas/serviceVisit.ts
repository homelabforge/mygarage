import { z } from 'zod'
import type { TFunction } from 'i18next'
import {
  makeDateSchema,
  makeOptionalOdometerSchema,
  makeOptionalCurrencySchema,
} from './shared'
// Service categories matching backend Literal type
export const SERVICE_CATEGORIES = ['Maintenance', 'Inspection', 'Collision', 'Upgrades', 'Detailing'] as const

/**
 * Service Visit validation schemas matching backend Pydantic validators.
 * See: backend/app/schemas/service_visit.py
 *
 * Factories, not constants — see the header of schemas/auth.ts for why.
 */

// Inspection result values
export const INSPECTION_RESULTS = ['passed', 'failed', 'needs_attention'] as const
export const INSPECTION_SEVERITIES = ['green', 'yellow', 'red'] as const

// Service line item schema
export const makeServiceLineItemSchema = (t: TFunction) =>
  z.object({
    description: z
      .string()
      .min(1, t('common:validation.serviceVisit.descriptionRequired'))
      .max(200, t('common:validation.serviceVisit.descriptionTooLong')),
    category: z.enum(SERVICE_CATEGORIES).optional().or(z.literal('')),
    cost: makeOptionalCurrencySchema(t),
    notes: z
      .string()
      .max(1000, t('common:validation.serviceVisit.lineItemNotesTooLong'))
      .optional(),
    is_inspection: z.boolean().default(false),
    inspection_result: z
      .enum(INSPECTION_RESULTS, {
        message: t('common:validation.serviceVisit.inspectionResultInvalid'),
      })
      .optional()
      .or(z.literal('')),
    inspection_severity: z
      .enum(INSPECTION_SEVERITIES, {
        message: t('common:validation.serviceVisit.inspectionSeverityInvalid'),
      })
      .optional()
      .or(z.literal('')),
    triggered_by_inspection_id: z
      .number()
      .int()
      .optional()
      .or(z.nan())
      .transform(val => (typeof val === 'number' && isNaN(val) ? undefined : val)),
  })

// Service visit schema
export const makeServiceVisitSchema = (t: TFunction) =>
  z.object({
    vendor_id: z
      .number()
      .int()
      .positive()
      .optional()
      .or(z.nan())
      .transform(val => (typeof val === 'number' && isNaN(val) ? undefined : val)),
    date: makeDateSchema(t),
    odometer_km: makeOptionalOdometerSchema(t),
    notes: z.string().max(5000, t('common:validation.serviceVisit.notesTooLong')).optional(),
    insurance_claim_number: z
      .string()
      .max(50, t('common:validation.serviceVisit.insuranceClaimNumberTooLong'))
      .optional(),
    line_items: z
      .array(makeServiceLineItemSchema(t))
      .min(1, t('common:validation.serviceVisit.lineItemsRequired')),
  })

// Refine to validate inspection fields are set when is_inspection is true
export const makeServiceVisitSchemaRefined = (t: TFunction) =>
  makeServiceVisitSchema(t).refine(
    (data) => {
      for (const item of data.line_items) {
        if (item.is_inspection && !item.inspection_result) {
          return false
        }
      }
      return true
    },
    {
      message: t('common:validation.serviceVisit.inspectionResultRequired'),
      path: ['line_items'],
    }
  )

export type ServiceLineItemInput = z.input<ReturnType<typeof makeServiceLineItemSchema>>
export type ServiceLineItemFormData = z.output<ReturnType<typeof makeServiceLineItemSchema>>
export type ServiceVisitInput = z.input<ReturnType<typeof makeServiceVisitSchema>>
export type ServiceVisitFormData = z.output<ReturnType<typeof makeServiceVisitSchema>>
