import type { CoverageFormData } from '../schemas/insurance'
import type { Coverage, CoverageKey } from '../types/insurance'

/**
 * The standard coverage catalogue, mirroring
 * `backend/app/utils/insurance_coverages.py`.
 *
 * The backend owns the keys and what each coverage may store; this file owns
 * how they are LABELLED and laid out. `Record<CoverageKey, CoverageMeta>` is
 * what keeps the two in step: `CoverageKey` comes from the generated API
 * types, so a coverage added on the backend and forgotten here fails `tsc`,
 * and one removed there fails on the leftover entry.
 *
 * DECLARATION ORDER IS DISPLAY ORDER, on the card and in the form, and it is
 * the same order the API sorts its responses into. `insuranceCoverages.test.ts`
 * checks it against `openapi.json` so the two can never drift silently.
 */

/** One of a coverage's two limit inputs. `count` is a plain number (days). */
export interface CoverageSlot {
  labelKey: string
  kind: 'money' | 'count'
}

/** Where a coverage is sold, mirroring `Coverage.regions` on the backend (#211). */
export type CoverageRegion = 'US' | 'EU'

export interface CoverageMeta {
  labelKey: string
  /** Shown under the label when the coverage's name alone is not the whole story. */
  hintKey?: string
  primary?: CoverageSlot
  secondary?: CoverageSlot
  deductible?: boolean
  premium?: boolean
  regions: CoverageRegion[]
}

const EACH_PERSON: CoverageSlot = {
  labelKey: 'forms:insuranceCoverages.slots.eachPerson',
  kind: 'money',
}
const EACH_ACCIDENT: CoverageSlot = {
  labelKey: 'forms:insuranceCoverages.slots.eachAccident',
  kind: 'money',
}
const EACH_DAY: CoverageSlot = {
  labelKey: 'forms:insuranceCoverages.slots.eachDay',
  kind: 'money',
}
const MAXIMUM_DAYS: CoverageSlot = {
  labelKey: 'forms:insuranceCoverages.slots.maximumDays',
  kind: 'count',
}
const LIMIT: CoverageSlot = { labelKey: 'forms:insuranceCoverages.slots.limit', kind: 'money' }
/** Deductible and premium are slots like any other, matching the backend
 *  catalogue, so every surface renders all four amounts with one loop. */
export const DEDUCTIBLE: CoverageSlot = { labelKey: 'forms:insurance.deductible', kind: 'money' }
export const PREMIUM: CoverageSlot = {
  labelKey: 'forms:insuranceCoverages.slots.premium',
  kind: 'money',
}

export const COVERAGES: Record<CoverageKey, CoverageMeta> = {
  bodily_injury: {
    labelKey: 'forms:insuranceCoverages.bodilyInjury',
    primary: EACH_PERSON,
    secondary: EACH_ACCIDENT,
    premium: true,
    regions: ['US'],
  },
  property_damage: {
    labelKey: 'forms:insuranceCoverages.propertyDamage',
    primary: EACH_ACCIDENT,
    premium: true,
    regions: ['US'],
  },
  uninsured_bodily_injury: {
    labelKey: 'forms:insuranceCoverages.uninsuredBodilyInjury',
    primary: EACH_PERSON,
    secondary: EACH_ACCIDENT,
    premium: true,
    regions: ['US'],
  },
  uninsured_property_damage: {
    labelKey: 'forms:insuranceCoverages.uninsuredPropertyDamage',
    primary: EACH_ACCIDENT,
    deductible: true,
    premium: true,
    regions: ['US'],
  },
  personal_injury_protection: {
    labelKey: 'forms:insuranceCoverages.personalInjuryProtection',
    primary: EACH_PERSON,
    deductible: true,
    premium: true,
    regions: ['US'],
  },
  medical_payments: {
    labelKey: 'forms:insuranceCoverages.medicalPayments',
    primary: EACH_PERSON,
    premium: true,
    regions: ['US'],
  },
  comprehensive: {
    labelKey: 'forms:insuranceCoverages.comprehensive',
    hintKey: 'forms:insuranceCoverages.actualCashValue',
    deductible: true,
    premium: true,
    regions: ['US'],
  },
  collision: {
    labelKey: 'forms:insuranceCoverages.collision',
    hintKey: 'forms:insuranceCoverages.actualCashValue',
    deductible: true,
    premium: true,
    regions: ['US'],
  },
  glass: {
    labelKey: 'forms:insuranceCoverages.glass',
    deductible: true,
    premium: true,
    regions: ['US', 'EU'],
  },
  rental_reimbursement: {
    labelKey: 'forms:insuranceCoverages.rentalReimbursement',
    primary: EACH_DAY,
    secondary: MAXIMUM_DAYS,
    premium: true,
    regions: ['US'],
  },
  roadside_assistance: {
    labelKey: 'forms:insuranceCoverages.roadsideAssistance',
    premium: true,
    regions: ['US'],
  },
  loan_lease_gap: {
    labelKey: 'forms:insuranceCoverages.loanLeaseGap',
    premium: true,
    regions: ['US'],
  },
  custom_equipment: {
    labelKey: 'forms:insuranceCoverages.customEquipment',
    primary: LIMIT,
    deductible: true,
    premium: true,
    regions: ['US'],
  },
  // --- Europe (#211): the garanties a French, German, Italian or Spanish
  // policy prints, in the backend catalogue's order.
  third_party_liability: {
    labelKey: 'forms:insuranceCoverages.thirdPartyLiability',
    primary: LIMIT,
    premium: true,
    regions: ['EU'],
  },
  driver_protection: {
    labelKey: 'forms:insuranceCoverages.driverProtection',
    primary: LIMIT,
    premium: true,
    regions: ['EU'],
  },
  theft: {
    labelKey: 'forms:insuranceCoverages.theft',
    deductible: true,
    premium: true,
    regions: ['EU'],
  },
  fire: {
    labelKey: 'forms:insuranceCoverages.fire',
    deductible: true,
    premium: true,
    regions: ['EU'],
  },
  natural_disasters: {
    labelKey: 'forms:insuranceCoverages.naturalDisasters',
    deductible: true,
    premium: true,
    regions: ['EU'],
  },
  all_accidents_damage: {
    labelKey: 'forms:insuranceCoverages.allAccidentsDamage',
    hintKey: 'forms:insuranceCoverages.allAccidentsDamageHint',
    deductible: true,
    premium: true,
    regions: ['EU'],
  },
  legal_protection: {
    labelKey: 'forms:insuranceCoverages.legalProtection',
    primary: LIMIT,
    premium: true,
    regions: ['EU'],
  },
  assistance: {
    labelKey: 'forms:insuranceCoverages.assistance',
    premium: true,
    regions: ['EU'],
  },
  replacement_vehicle: {
    labelKey: 'forms:insuranceCoverages.replacementVehicle',
    primary: MAXIMUM_DAYS,
    premium: true,
    regions: ['EU'],
  },
}

/** Every coverage, in the one order every surface shows them in. */
export const COVERAGE_ORDER = Object.keys(COVERAGES) as CoverageKey[]

/**
 * How a form lays the catalogue out for one country (#211): the profile's
 * `insurance.coverage_keys` first, in the profile's order, and every other
 * coverage behind « more coverages ». Without a profile, everything is shown
 * in catalogue order and nothing is folded away.
 */
export function coverageLayout(preferred: readonly string[] | null | undefined): {
  shown: CoverageKey[]
  more: CoverageKey[]
} {
  const first = (preferred ?? []).filter((key): key is CoverageKey => key in COVERAGES)
  if (first.length === 0) return { shown: COVERAGE_ORDER, more: [] }
  return { shown: first, more: COVERAGE_ORDER.filter((key) => !first.includes(key)) }
}

export type SlotName = 'limit_primary' | 'limit_secondary' | 'deductible' | 'premium'

/**
 * A coverage's amounts, in the order a declarations page prints its columns.
 *
 * The single frontend definition, mirroring `Coverage.slots()` on the backend:
 * the form renders an input per entry, the card renders a line per entry and
 * the submit path sends exactly these. `insuranceCoverages.test.ts` compares
 * it against the shape the backend publishes in `openapi.json`, because a
 * mismatch is silent and destructive -- a slot only the backend has gets no
 * input, and saving the form would then clear the stored amount.
 */
export function coverageSlots(key: CoverageKey): [SlotName, CoverageSlot][] {
  const meta = COVERAGES[key]
  const slots: [SlotName, CoverageSlot][] = []
  if (meta.primary) slots.push(['limit_primary', meta.primary])
  if (meta.secondary) slots.push(['limit_secondary', meta.secondary])
  if (meta.deductible) slots.push(['deductible', DEDUCTIBLE])
  if (meta.premium) slots.push(['premium', PREMIUM])
  return slots
}

/** One checklist row as the form holds it: the schema's own output type, so
 *  the two cannot drift. */
export type CoverageRow = CoverageFormData

const toNumber = (value: string | number | null | undefined): number | undefined =>
  value == null || value === '' ? undefined : Number(value)

/**
 * The full checklist, with the coverages a vehicle already carries ticked.
 *
 * Every catalogue coverage is present whether carried or not, so the form's
 * array indices are stable and a row can never be at a different position for
 * one vehicle than for another.
 */
export function coverageRows(existing: Coverage[] = []): CoverageRow[] {
  const carried = new Map(existing.map((item) => [item.coverage_key, item]))
  return COVERAGE_ORDER.map((key) => {
    const item = carried.get(key)
    return {
      coverage_key: key,
      included: item != null,
      limit_primary: toNumber(item?.limit_primary),
      limit_secondary: toNumber(item?.limit_secondary),
      deductible: toNumber(item?.deductible),
      premium: toNumber(item?.premium),
    }
  })
}

/**
 * The ticked rows, as the API takes them.
 *
 * An amount typed into a slot and then ticked away with a different coverage
 * is dropped here rather than sent: the API rejects an amount a coverage has
 * no place to show, and the user has already said that coverage is not carried.
 */
export function coveragesToApi(rows: CoverageRow[]): Coverage[] {
  return rows
    .filter((row) => row.included && row.coverage_key in COVERAGES)
    .map((row) => {
      const key = row.coverage_key as CoverageKey
      const allowed = new Set(coverageSlots(key).map(([name]) => name))
      const pick = (slot: SlotName) =>
        allowed.has(slot) && row[slot] != null ? String(row[slot]) : null
      return {
        coverage_key: key,
        limit_primary: pick('limit_primary'),
        limit_secondary: pick('limit_secondary'),
        deductible: pick('deductible'),
        premium: pick('premium'),
      }
    })
}
