import { z } from 'zod'
import type { TFunction } from 'i18next'

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
    max: 99999.99,
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

export const makePricePerUnitSchema = (t: TFunction) =>
  makeNumericField(t, {
    min: 0,
    max: 999.99,
    negativeKey: 'common:validation.price.negative',
    tooLargeKey: 'common:validation.price.tooLarge',
    invalidKey: 'common:validation.price.invalid',
    requiredKey: 'common:validation.price.required',
  })

// Date validators
export const makeDateSchema = (t: TFunction) =>
  z
    .string()
    .min(1, t('common:validation.date.required'))
    .regex(/^\d{4}-\d{2}-\d{2}$/, t('common:validation.date.invalidFormat'))

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
    max: 99999.99,
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

export const makeOptionalPricePerUnitSchema = (t: TFunction) =>
  makeNumericField(t, {
    min: 0,
    max: 999.99,
    negativeKey: 'common:validation.price.negative',
    tooLargeKey: 'common:validation.price.tooLarge',
    invalidKey: 'common:validation.price.invalid',
  })

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
