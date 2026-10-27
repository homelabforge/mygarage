import { z } from 'zod'
import type { TFunction } from 'i18next'
import { getActiveLocale } from '@/constants/i18n'
import type { UnitSet } from '@/types/units'
import { parseDecimalInput } from '@/utils/decimalInput'
import { priceOverCanonicalMax, type PriceBasis } from '@/utils/decimalSafe'

/**
 * Shared validation schemas for common field types across the application.
 * These ensure consistency with backend Pydantic validators.
 *
 * Every validator here is a FACTORY, not a module-level constant — see the
 * header of schemas/auth.ts for why. Consumers are themselves factories that
 * thread `t` straight through, so a language change rebuilds the whole tree.
 *
 * Keys are namespace-qualified (`common:…`) because this module never calls
 * useTranslation and its consumers are bound to several namespaces.
 */

/**
 * Emitted by NumberInput when the typed text is not a number at all.
 *
 * Exists to separate EMPTY from INVALID. The original shape —
 * `.or(z.nan()).transform(v => isNaN(v) ? undefined : v)` — mapped every NaN to
 * undefined, so typing "abc" into an optional field was indistinguishable from
 * leaving it blank and the value was silently dropped on save.
 */
export const INVALID_NUMBER: unique symbol = Symbol('INVALID_NUMBER')

/**
 * The API's money bounds, from backend `app/schemas/_money.py`.
 *
 * Records carry no currency, so one cap serves forint and dollars alike: it is
 * what the column holds. Every stored amount is Numeric(12,2) and every
 * `price_per_unit` Numeric(13,4). moneyBounds.test.ts checks both against the
 * maxima in openapi.json.
 */
export const MONEY_MAX = 9_999_999_999.99
export const UNIT_PRICE_MAX = 999_999_999.9999

interface NumericFieldOptions {
  min: number
  max: number
  negativeKey: string
  tooLargeKey: string
  invalidKey: string
  /** When set, an absent value is an error rather than a pass. */
  requiredKey?: string
  /**
   * Reject `val === min` too, not just `val < min` — for a field whose
   * constraint is strictly positive (backend `gt=0`), not merely
   * non-negative (`ge=0`). Uses `negativeKey` for the message either way.
   */
  exclusiveMin?: boolean
  /** When set, a non-integer value is rejected with this message. Checked
   *  alongside min/max, after the invalid-number guard. */
  integerKey?: string
}

/**
 * One builder for every numeric field.
 *
 * Exported so schema files whose bounds don't match one of the specific
 * factories below (odometer/currency/volume/…) can still get correct
 * INVALID_NUMBER/NaN handling and a translated message while keeping their
 * OWN exact min/max — pass `min: -Infinity` / `max: Infinity` for a side
 * that was never bounded, never a stand-in shared factory's numbers.
 *
 * ⚠️ Zod 4 notes, both verified by execution against 4.4.3:
 *
 *  1. A `z.union([...])` reports a generic `invalid_union` and SWALLOWS a
 *     message added by a branch's own transform, so a union cannot carry these
 *     translated keys. superRefine can.
 *  2. The base MUST be `z.unknown().optional()`. A bare `z.unknown()` used as an
 *     object property rejects an ABSENT key with
 *     `invalid_type: expected nonoptional`, while still accepting an explicitly
 *     `undefined` one — so the bug hides from a direct safeParse(undefined) test.
 */
export const makeNumericField = (t: TFunction, opts: NumericFieldOptions) =>
  z
    .unknown()
    .optional()
    .superRefine((val, ctx) => {
      // Task 8 finished migrating every numeric producer off valueAsNumber
      // onto registerDecimal, which never emits a raw NaN — empty input
      // becomes undefined and unparseable text becomes INVALID_NUMBER. So a
      // NaN reaching this point can only mean a control that failed to
      // parse, never an empty one, and belongs with the invalid guard below,
      // not the empty one.
      const isEmpty = val === undefined || val === null || val === ''

      if (isEmpty) {
        if (opts.requiredKey) {
          ctx.addIssue({ code: 'custom', message: t(opts.requiredKey) })
        }
        return
      }

      if (val === INVALID_NUMBER || typeof val !== 'number' || Number.isNaN(val)) {
        ctx.addIssue({ code: 'custom', message: t(opts.invalidKey) })
        return
      }
      if (opts.integerKey && !Number.isInteger(val)) {
        ctx.addIssue({ code: 'custom', message: t(opts.integerKey) })
      }
      const belowMin = opts.exclusiveMin ? val <= opts.min : val < opts.min
      if (belowMin) ctx.addIssue({ code: 'custom', message: t(opts.negativeKey) })
      if (val > opts.max) ctx.addIssue({ code: 'custom', message: t(opts.tooLargeKey) })
    })
    .transform(val => (typeof val === 'number' && !Number.isNaN(val) ? val : undefined))

// Numeric validators - required number fields
// Odometer stored in km (Decimal) on backend; form accepts decimals. Imperial
// users enter miles (displayed via `u.distance`, the resolved-set formatter)
// and the submit path converts to km via `canonicalFromUnitField`. The binary
// `toCanonicalKm` this path used to call was deleted in phase 3b task 5 (R8).
export const makeOdometerSchema = (t: TFunction) =>
  makeNumericField(t, {
    min: 0,
    max: 9999999,
    negativeKey: 'common:validation.odometer.negative',
    tooLargeKey: 'common:validation.odometer.tooLarge',
    invalidKey: 'common:validation.odometer.invalid',
    requiredKey: 'common:validation.odometer.required',
  })

export const makeCurrencySchema = (t: TFunction) =>
  makeNumericField(t, {
    min: 0,
    max: MONEY_MAX,
    negativeKey: 'common:validation.amount.negative',
    tooLargeKey: 'common:validation.amount.tooLarge',
    invalidKey: 'common:validation.amount.invalid',
    requiredKey: 'common:validation.amount.required',
  })

export const makeVolumeSchema = (t: TFunction) =>
  makeNumericField(t, {
    min: 0,
    max: 9999.999,
    negativeKey: 'common:validation.volume.negative',
    tooLargeKey: 'common:validation.volume.tooLarge',
    invalidKey: 'common:validation.volume.invalid',
    requiredKey: 'common:validation.volume.required',
  })

// Date validators
export const makeDateSchema = (t: TFunction) =>
  z
    .string()
    .min(1, t('common:validation.date.required'))
    .regex(/^\d{4}-\d{2}-\d{2}$/, t('common:validation.date.invalidFormat'))

/**
 * An optional date an edit can clear. A date input reports an empty field as
 * '', which `makeDateSchema(t).optional()` rejects as "date required", so a
 * record without the date could be neither created nor re-saved. A refine,
 * not a union with z.literal(''), so the format message isn't swallowed.
 */
export const makeOptionalDateSchema = (t: TFunction) =>
  z
    .string()
    .refine((value) => value === '' || /^\d{4}-\d{2}-\d{2}$/.test(value), {
      message: t('common:validation.date.invalidFormat'),
    })
    .optional()

// Text validators
export const makeDescriptionSchema = (t: TFunction) =>
  z
    .string()
    .min(1, t('common:validation.description.required'))
    .max(500, t('common:validation.description.tooLong'))

export const makeNotesSchema = (t: TFunction) =>
  z.string().max(1000, t('common:validation.notes.tooLong'))

export const makeVendorNameSchema = (t: TFunction) =>
  z.string().max(100, t('common:validation.vendorName.tooLong'))

// VIN validator
export const makeVinSchema = (t: TFunction) =>
  z
    .string()
    .length(17, t('common:validation.vin.length'))
    .regex(/^[A-HJ-NPR-Z0-9]{17}$/, t('common:validation.vin.invalidFormat'))

// Optional numeric fields
// Forms use valueAsNumber: true, so empty fields become NaN; NumberInput can
// also emit INVALID_NUMBER for genuinely unparseable text.
export const makeOptionalOdometerSchema = (t: TFunction) =>
  makeNumericField(t, {
    min: 0,
    max: 9999999,
    negativeKey: 'common:validation.odometer.negative',
    tooLargeKey: 'common:validation.odometer.tooLarge',
    invalidKey: 'common:validation.odometer.invalid',
  })

export const makeOptionalCurrencySchema = (t: TFunction) =>
  makeNumericField(t, {
    min: 0,
    max: MONEY_MAX,
    negativeKey: 'common:validation.amount.negative',
    tooLargeKey: 'common:validation.amount.tooLarge',
    invalidKey: 'common:validation.amount.invalid',
  })

export const makeOptionalVolumeSchema = (t: TFunction) =>
  makeNumericField(t, {
    min: 0,
    max: 9999.999,
    negativeKey: 'common:validation.volume.negative',
    tooLargeKey: 'common:validation.volume.tooLarge',
    invalidKey: 'common:validation.volume.invalid',
  })

/**
 * A price per unit, with no ceiling of its own.
 *
 * The API caps it in canonical units ($/L, $/kg), and the unit the typed
 * number is per depends on the price basis, which on the fuel form is a
 * select in the same form. So the cap is `checkUnitPriceCap`, run from the
 * record schema where the basis can be read. Capping the typed number here
 * would refuse a gallon price that converts under the API's max.
 */
export const makeOptionalPricePerUnitSchema = (t: TFunction) =>
  makeNumericField(t, {
    min: 0,
    max: Infinity,
    negativeKey: 'common:validation.price.negative',
    tooLargeKey: 'common:validation.price.tooLarge',
    invalidKey: 'common:validation.price.invalid',
  })

/**
 * The unit-price cap, checked where the API checks it: in canonical units.
 *
 * Call it from a record schema's `superRefine` with the basis the form will
 * post. Only a number can be over the cap, so a price that failed its own
 * field check (negative, unreadable) keeps that one message.
 */
export const checkUnitPriceCap = (
  t: TFunction,
  ctx: z.RefinementCtx,
  price: unknown,
  units: UnitSet,
  basis: PriceBasis | string | null | undefined,
): void => {
  if (typeof price !== 'number') return
  if (!priceOverCanonicalMax(price, UNIT_PRICE_MAX, units, basis)) return
  ctx.addIssue({
    code: 'custom',
    path: ['price_per_unit'],
    message: t('common:validation.price.tooLarge'),
  })
}

/**
 * The first thing `makeOptionalCurrencySchema` says about `value`, or
 * undefined when it would pass. For forms that check amounts by hand, so they
 * get the same cap and the same messages as the zod forms.
 */
export const moneyError = (t: TFunction, value: unknown): string | undefined => {
  const result = makeOptionalCurrencySchema(t).safeParse(value)
  return result.success ? undefined : result.error.issues[0]?.message
}

/**
 * `moneyError` for an amount still held as typed text, read the way
 * NumberInput's `registerDecimal` reads it: blank is no amount, and text that
 * isn't a number is invalid rather than dropped.
 */
export const moneyTextError = (t: TFunction, raw: string): string | undefined => {
  const parsed = parseDecimalInput(raw, getActiveLocale())
  if (parsed.kind === 'empty') return undefined
  return moneyError(t, parsed.kind === 'value' ? parsed.value : INVALID_NUMBER)
}

// kWh validator for electric vehicles
export const makeOptionalKwhSchema = (t: TFunction) =>
  makeNumericField(t, {
    min: 0,
    max: 99999.999,
    negativeKey: 'common:validation.kwh.negative',
    tooLargeKey: 'common:validation.kwh.tooLarge',
    invalidKey: 'common:validation.kwh.invalid',
  })

// Engine-hours validator — dimensionless (no unit conversion), required for
// standalone hours-record entry. Bounds mirror the backend's
// HoursRecordBase/Update `engine_hours` field (ge=0, le=999999999.9) — wider
// than the optional fuel/service co-field sidecar below, which mirrors
// FuelRecordBase/Update's narrower bound instead.
export const makeEngineHoursSchema = (t: TFunction) =>
  makeNumericField(t, {
    min: 0,
    max: 999999999.9,
    negativeKey: 'common:validation.engineHours.negative',
    tooLargeKey: 'common:validation.engineHours.tooLarge',
    invalidKey: 'common:validation.engineHours.invalid',
    requiredKey: 'common:validation.engineHours.required',
  })

// Engine-hours validator — dimensionless (no unit conversion), for
// hour-metered vehicles. Bounds mirror the backend's FuelRecordBase/Update
// `engine_hours` field (ge=0, le=9999999.9).
export const makeOptionalEngineHoursSchema = (t: TFunction) =>
  makeNumericField(t, {
    min: 0,
    max: 9999999.9,
    negativeKey: 'common:validation.engineHours.negative',
    tooLargeKey: 'common:validation.engineHours.tooLarge',
    invalidKey: 'common:validation.engineHours.invalid',
  })
