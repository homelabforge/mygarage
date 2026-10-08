import { z } from 'zod'
import type { TFunction } from 'i18next'
import { makeOptionalCurrencySchema } from './shared'

/**
 * Insurance policy schema matching backend Pydantic validators.
 * See: backend/app/schemas/insurance.py
 */

/**
 * Option lists for the insurance form.
 *
 * `value` is the persisted/API value — it must never be translated or changed.
 * `labelKey` is the i18n key for the human-readable label, resolved at render.
 */
export const POLICY_TYPES = [
  { value: 'Liability', labelKey: 'forms:policyTypes.liability' },
  { value: 'Comprehensive', labelKey: 'forms:policyTypes.comprehensive' },
  { value: 'Collision', labelKey: 'forms:policyTypes.collision' },
  { value: 'Full Coverage', labelKey: 'forms:policyTypes.fullCoverage' },
  { value: 'Minimum', labelKey: 'forms:policyTypes.minimum' },
  { value: 'Other', labelKey: 'forms:policyTypes.other' },
  // The European formulas (#211): « au tiers », « tiers étendu ».
  { value: 'Third Party', labelKey: 'forms:policyTypes.thirdParty' },
  { value: 'Third Party Extended', labelKey: 'forms:policyTypes.thirdPartyExtended' },
] as const

export type PolicyTypeValue = (typeof POLICY_TYPES)[number]['value']

/** The translated name of a stored policy type; a value this version does
 *  not know (an older row, an import) is shown as stored. */
export function policyTypeLabel(value: string | null | undefined, t: TFunction): string {
  if (!value) return ''
  const option = POLICY_TYPES.find((item) => item.value === value)
  return option ? t(option.labelKey) : value
}

/**
 * The policy type options in the order a form offers them: the country
 * profile's formulas first, in its order, then the rest of the list. Without
 * a profile, the list as declared (#211).
 */
export function policyTypeOptions(
  t: TFunction,
  preferred: readonly string[] | null | undefined
): { value: PolicyTypeValue; label: string }[] {
  const first = (preferred ?? []).filter((value): value is PolicyTypeValue =>
    POLICY_TYPES.some((option) => option.value === value)
  )
  const rest = POLICY_TYPES.map((option) => option.value).filter((value) => !first.includes(value))
  return [...first, ...rest].map((value) => ({ value, label: policyTypeLabel(value, t) }))
}

/** `insurance_policy_vehicles.no_claims_class`: ten characters of plain text.
 *  The country profile's own pattern is a hint shown beside the field, never
 *  a rule, since the schemes differ per insurer. */
export const NO_CLAIMS_CLASS_PATTERN = /^[A-Za-z0-9 .,/%-]{1,10}$/

export const PREMIUM_FREQUENCIES = [
  { value: 'Monthly', labelKey: 'forms:premiumFrequencies.monthly' },
  { value: 'Quarterly', labelKey: 'forms:premiumFrequencies.quarterly' },
  { value: 'Semi-Annual', labelKey: 'forms:premiumFrequencies.semiAnnual' },
  { value: 'Annual', labelKey: 'forms:premiumFrequencies.annual' },
] as const

/** Labels offered as one-tap chips in the named-fields editor. Suggestions
 *  only: the stored label is whatever text the user keeps, so these are
 *  translated for display and never persisted as keys. */
export const SUGGESTED_POLICY_FIELDS = [
  'forms:insuranceFieldLabels.agentName',
  'forms:insuranceFieldLabels.agentPhone',
  'forms:insuranceFieldLabels.claimsPhone',
] as const

/** Deliberately none of the standard coverages: those have their own inputs
 *  in the coverage editor now, and offering them here as free text would give
 *  a vehicle two places to hold its collision deductible. */
export const SUGGESTED_VEHICLE_FIELDS = [
  'forms:insuranceFieldLabels.lienholder',
  'forms:insuranceFieldLabels.garagingAddress',
  'forms:insuranceFieldLabels.discounts',
] as const

const namedFieldSchema = (t: TFunction) =>
  z.object({
    label: z.string().trim().min(1, t('common:required')).max(60),
    value: z.string().trim().min(1, t('common:required')).max(255),
  })

/** One row of the standard coverage checklist.
 *
 *  The form carries EVERY catalogue coverage, included or not, so the checklist
 *  maps one-to-one onto stable array indices; `PolicyForm` drops the unticked
 *  ones on submit. A coverage the catalogue gives no such slot keeps
 *  `undefined` there and is stripped the same way, because the API rejects an
 *  amount it has nowhere to show. */
const coverageSchema = (t: TFunction) =>
  z.object({
    coverage_key: z.string().min(1),
    included: z.boolean(),
    limit_primary: makeOptionalCurrencySchema(t),
    limit_secondary: makeOptionalCurrencySchema(t),
    deductible: makeOptionalCurrencySchema(t),
    premium: makeOptionalCurrencySchema(t),
  })

const policyVehicleSchema = (t: TFunction) =>
  z.object({
    vin: z.string().min(1),
    policy_type: z.string().min(1, t('common:validation.policyType.required')),
    premium_share: makeOptionalCurrencySchema(t),
    deductible: makeOptionalCurrencySchema(t),
    no_claims_class: z
      .string()
      .trim()
      .optional()
      .refine((value) => !value || NO_CLAIMS_CLASS_PATTERN.test(value), {
        message: t('forms:insurance.noClaimsClassInvalid'),
      }),
    notes: z.string().optional(),
    effective_to: z.string().optional(),
    coverages: z.array(coverageSchema(t)),
    fields: z.array(namedFieldSchema(t)),
  })

/**
 * Factory, not a module-level constant — see the header of schemas/auth.ts for
 * why. `premium_amount` and `deductible` are genuinely optional on the backend
 * (`Decimal | None`); the bug (#140) was that the form sent the raw string
 * `"528,25"` for a comma-decimal locale and `""` for an untouched optional
 * field, both of which the backend's 422 rejected with no per-field detail.
 * Routing them through the locale-aware `NumberInput`/`registerDecimal` fixes
 * both — it reports `common:validation.amount.invalid` instead of a bare
 * status code.
 *
 * Every amount here is the shared currency factory: floor 0 and the API's
 * MONEY_MAX, which covers a collector-car policy or a commercial umbrella
 * premium in any currency (money-fits).
 */
export const makeInsuranceSchema = (t: TFunction) =>
  z
    .object({
      provider: z.string().min(1, t('common:validation.provider.required')),
      policy_number: z.string().min(1, t('common:validation.policyNumber.required')),
      start_date: z.string().min(1, t('common:validation.date.required')),
      end_date: z.string().min(1, t('common:validation.date.required')),
      premium_amount: makeOptionalCurrencySchema(t),
      premium_frequency: z.string().optional(),
      notes: z.string().optional(),
      fields: z.array(namedFieldSchema(t)),
      vehicles: z.array(policyVehicleSchema(t)),
    })
    .refine((data) => !data.start_date || !data.end_date || data.end_date >= data.start_date, {
      path: ['end_date'],
      message: t('forms:insurance.endBeforeStart'),
    })

// Amounts are `unknown` going in (raw NumberInput text or a number from
// defaultValues) and `number | undefined` coming out: the resolver is cast to
// the output type at the call site, like the sibling record forms built on
// the same shared.ts factories.
export type InsuranceFormData = z.output<ReturnType<typeof makeInsuranceSchema>>
export type PolicyVehicleFormData = InsuranceFormData['vehicles'][number]
export type CoverageFormData = PolicyVehicleFormData['coverages'][number]

/** `currentEnd` is the term being renewed: the next one may not start before
 *  it ends, or both would be active at once and both premiums would accrue. */
export const makeRenewSchema = (t: TFunction, currentEnd: string) =>
  z
    .object({
      start_date: z.string().min(1, t('common:validation.date.required')),
      end_date: z.string().min(1, t('common:validation.date.required')),
      premium_amount: makeOptionalCurrencySchema(t),
    })
    .refine((data) => data.end_date >= data.start_date, {
      path: ['end_date'],
      message: t('forms:insurance.endBeforeStart'),
    })
    .refine((data) => !data.start_date || data.start_date >= currentEnd, {
      path: ['start_date'],
      message: t('forms:insurance.renewOverlaps'),
    })

export type RenewFormData = z.output<ReturnType<typeof makeRenewSchema>>
