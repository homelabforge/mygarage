import { z } from 'zod'
import type { TFunction } from 'i18next'
import { makeDateSchema, makeCurrencySchema, makeNotesSchema } from './shared'

/**
 * Tax record schema matching backend Pydantic validators.
 * See: backend/app/schemas/tax.py
 *
 * Factory, not a constant — see the header of schemas/auth.ts for why.
 */

/**
 * Persisted tax_type values. Backend contract:
 * Literal["Registration", "Inspection", "Property Tax", "Tolls"] — never translate these.
 */
export const TAX_TYPE_VALUES = ['Registration', 'Inspection', 'Property Tax', 'Tolls'] as const

export type TaxTypeValue = (typeof TAX_TYPE_VALUES)[number]

/** Form options: API `value` plus the i18n `labelKey` resolved at render. */
export const TAX_TYPES = [
  { value: 'Registration', labelKey: 'forms:taxTypes.registration' },
  { value: 'Inspection', labelKey: 'forms:taxTypes.inspection' },
  { value: 'Property Tax', labelKey: 'forms:taxTypes.propertyTax' },
  { value: 'Tolls', labelKey: 'forms:taxTypes.tolls' },
] as const satisfies readonly { value: TaxTypeValue; labelKey: string }[]

export const makeTaxRecordSchema = (t: TFunction) =>
  z.object({
    date: makeDateSchema(t),
    tax_type: z.enum(TAX_TYPE_VALUES).optional(),
    amount: makeCurrencySchema(t),
    renewal_date: makeDateSchema(t).optional(),
    notes: makeNotesSchema(t).optional(),
  })

// Use z.output for Zod v4 compatibility with z.coerce fields
export type TaxRecordInput = z.input<ReturnType<typeof makeTaxRecordSchema>>
export type TaxRecordFormData = z.output<ReturnType<typeof makeTaxRecordSchema>>
