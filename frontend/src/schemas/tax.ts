import { z } from 'zod'
import type { TFunction } from 'i18next'
import { makeDateSchema, makeCurrencySchema, makeNotesSchema, makeOptionalDateSchema } from './shared'

/**
 * Tax record schema matching backend Pydantic validators.
 * See: backend/app/schemas/tax.py
 *
 * Factory, not a constant — see the header of schemas/auth.ts for why.
 */

/**
 * Persisted tax_type codes (#211). Backend contract: `app.constants.tax.TAX_TYPE_VALUES`
 * — never translate these. The four display strings stored before migration 146 are
 * read as their codes (`LEGACY_TAX_TYPES`); the API accepts them too.
 */
export const TAX_TYPE_VALUES = [
  'registration',
  'registration_tax',
  'co2_malus',
  'weight_malus',
  'circulation_tax',
  'company_vehicle_tax',
  'inspection',
  'property_tax',
  'tolls',
  'vignette',
  'lez_sticker',
  'parking_permit',
  'other',
] as const

export type TaxTypeValue = (typeof TAX_TYPE_VALUES)[number]

const LABEL_KEYS: Record<TaxTypeValue, string> = {
  registration: 'forms:taxTypes.registration',
  registration_tax: 'forms:taxTypes.registrationTax',
  co2_malus: 'forms:taxTypes.co2Malus',
  weight_malus: 'forms:taxTypes.weightMalus',
  circulation_tax: 'forms:taxTypes.circulationTax',
  company_vehicle_tax: 'forms:taxTypes.companyVehicleTax',
  inspection: 'forms:taxTypes.inspection',
  property_tax: 'forms:taxTypes.propertyTax',
  tolls: 'forms:taxTypes.tolls',
  vignette: 'forms:taxTypes.vignette',
  lez_sticker: 'forms:taxTypes.lezSticker',
  parking_permit: 'forms:taxTypes.parkingPermit',
  other: 'forms:taxTypes.other',
}

/** Form options: API `value` plus the i18n `labelKey` resolved at render. */
export const TAX_TYPES: readonly { value: TaxTypeValue; labelKey: string }[] = TAX_TYPE_VALUES.map(
  (value) => ({ value, labelKey: LABEL_KEYS[value] })
)

/** What the column held before migration 146, by code. */
export const LEGACY_TAX_TYPES: Readonly<Record<string, TaxTypeValue>> = {
  Registration: 'registration',
  Inspection: 'inspection',
  'Property Tax': 'property_tax',
  Tolls: 'tolls',
}

/** The code a stored value means: itself, or the legacy string's code; null otherwise. */
export function asTaxType(value: string | null | undefined): TaxTypeValue | null {
  if (!value) return null
  if ((TAX_TYPE_VALUES as readonly string[]).includes(value)) return value as TaxTypeValue
  return LEGACY_TAX_TYPES[value] ?? null
}

/**
 * The label a stored value shows: its translated name, with the country's own
 * name beside it when the profile gives one (« Malus écologique (Y.3) »). A
 * value this build does not know shows as it is stored.
 */
export function taxTypeLabel(
  value: string | null | undefined,
  t: TFunction,
  names?: Record<string, string> | null
): string {
  if (!value) return ''
  const code = asTaxType(value)
  if (!code) return value
  const label = t(LABEL_KEYS[code])
  const national = names?.[code]
  return national ? `${label} (${national})` : label
}

/**
 * The select's options: the country's types first, in the profile's order and
 * with its names, then every other code. Without a profile, the plain list.
 */
export function taxTypeOptions(
  t: TFunction,
  profileTypes?: readonly string[] | null,
  names?: Record<string, string> | null
): { value: TaxTypeValue; label: string }[] {
  const first: TaxTypeValue[] = []
  for (const raw of profileTypes ?? []) {
    const code = asTaxType(raw)
    if (code && !first.includes(code)) first.push(code)
  }
  const rest = TAX_TYPE_VALUES.filter((code) => !first.includes(code))
  return [...first, ...rest].map((value) => ({ value, label: taxTypeLabel(value, t, names) }))
}

export const makeTaxRecordSchema = (t: TFunction) =>
  z.object({
    date: makeDateSchema(t),
    // '' is the select's empty option: no type.
    tax_type: z.enum(TAX_TYPE_VALUES).or(z.literal('')).optional(),
    amount: makeCurrencySchema(t),
    renewal_date: makeOptionalDateSchema(t),
    notes: makeNotesSchema(t).optional(),
  })

// Use z.output for Zod v4 compatibility with z.coerce fields
export type TaxRecordInput = z.input<ReturnType<typeof makeTaxRecordSchema>>
export type TaxRecordFormData = z.output<ReturnType<typeof makeTaxRecordSchema>>
