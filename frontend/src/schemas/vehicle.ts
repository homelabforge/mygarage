import { z } from 'zod'
import type { TFunction } from 'i18next'
import { FUEL_TYPE_VALUES } from '../constants/fuel'
import { getActiveLocale } from '../constants/i18n'
import { INVALID_NUMBER } from './shared'

/**
 * Vehicle schema for VehicleEdit and VehicleWizard forms.
 * Matches backend Pydantic validators.
 * See: backend/app/schemas/vehicle.py
 *
 * Factory, not a constant — see the header of schemas/auth.ts for why.
 */

export const VEHICLE_TYPES = [
  'Car',
  'SUV',
  'Truck',
  'Motorcycle',
  'ATV',
  'RV',
  'Trailer',
  'FifthWheel',
  'TravelTrailer',
  'Electric',
  'Hybrid',
  'Boat',
  'UTV',
  'Snowmobile',
  'Bicycle',
  'EBike',
] as const

/**
 * Vehicle-type options for a <Select>, ordered alphabetically by the label the
 * user actually sees.
 *
 * Deliberately sorted here rather than by reordering VEHICLE_TYPES itself. The
 * constant holds raw values ("FifthWheel", "EBike", "UTV") while the dropdown
 * shows translated labels, so a constant sorted by value is wrong twice over:
 * it is only alphabetical in English, and even there "SUV" would sort before
 * "Snowmobile" because it compares S-U against S-n. localeCompare against the
 * active locale gets both right in all six languages.
 */
export function vehicleTypeOptions(
  translate: TFunction,
): { value: (typeof VEHICLE_TYPES)[number]; label: string }[] {
  return VEHICLE_TYPES.map((value) => ({
    value,
    label: translate(`vehicleTypeLabels.${value}`, { defaultValue: value }),
  })).sort((a, b) => a.label.localeCompare(b.label, getActiveLocale()))
}

/** Trailer-like types: no fuel / odometer as a primary motorized vehicle. */
export const NON_MOTORIZED_TYPES = ['Trailer', 'FifthWheel', 'TravelTrailer'] as const

/** Distance-tracked but typically no liquid/charge fuel log (EBike uses Electric fuel). */
export const NO_FUEL_TYPES = ['Bicycle'] as const

// Collapse a blank/missing value to an explicit `null` rather than
// `undefined`. The vehicle update endpoint uses Pydantic's
// `model_dump(exclude_unset=True)` — an omitted key means "leave
// unchanged" — so a blank/cleared field must submit `null` (not
// `undefined`, which JSON.stringify/axios would drop) for the backend to
// actually clear it. Every field schema below funnels its blank case
// through one of these two helpers so a cleared field actually persists.
// Safe on the create path too (VehicleWizard POST): that endpoint calls
// `.model_dump()` without `exclude_unset`, so every field is always present
// regardless — an explicit `null` there is identical to omitting it.

// Empty string / null / undefined -> null. For string & date fields.
const nullOnBlank = <T,>(val: T | '' | null | undefined): T | null => val || null

// NaN (react-hook-form's `valueAsNumber` on a blanked input) / null /
// undefined -> null, but a legitimate 0 survives. Still used by
// soldPriceSchema below, which stays on the pre-Task-8 shape (see its own
// comment) — every other numeric field in this file now goes through
// numericOrNullField instead.
const numberOrNull = (val: number | null | undefined): number | null =>
  val == null || Number.isNaN(val) ? null : val

interface NullableNumericFieldOptions {
  min: number
  max: number
  negativeKey: string
  tooLargeKey: string
  invalidKey: string
  integerKey?: string
}

/**
 * Like shared.ts's makeNumericField, but outputs `null` instead of
 * `undefined` for the empty case, and `.optional()` is the LAST call in the
 * chain (not the first, unlike makeNumericField) — empirically verified
 * (see propane/spotRental/etc. conversions' sibling commit) that this is
 * what makes an OMITTED key stay omitted from the parsed output, rather
 * than becoming an explicit `null` that force-clears the column. A vehicle
 * stored with NULL year/doors/cylinders/current_hours/purchase_price/
 * def_tank_capacity_liters seeds the form with raw `null`, which must still
 * parse (to `null`) — `.nullable()` mid-chain handles that; it does NOT
 * short-circuit the way a trailing `.optional()` does, so a genuine null
 * input still reaches superRefine/transform below.
 *
 * Task 8 moved these fields onto NumberInput/registerDecimal, which can
 * hand this the INVALID_NUMBER sentinel for unparseable text. The old
 * `.or(z.nan())` shape only recognized number/NaN, so a sentinel failed the
 * union and zod reported its raw "expected number, received symbol" instead
 * of a translated message — fixed here the same way as every other
 * converted schema, while keeping each field's exact original bound and
 * this file's omitted-key/explicit-null distinction.
 */
const numericOrNullField = (t: TFunction, opts: NullableNumericFieldOptions) =>
  z
    .unknown()
    .nullable()
    .superRefine((val, ctx) => {
      const isEmpty = val === undefined || val === null || val === ''
      if (isEmpty) return

      if (val === INVALID_NUMBER || typeof val !== 'number' || Number.isNaN(val)) {
        ctx.addIssue({ code: 'custom', message: t(opts.invalidKey) })
        return
      }
      if (opts.integerKey && !Number.isInteger(val)) {
        ctx.addIssue({ code: 'custom', message: t(opts.integerKey) })
      }
      if (val < opts.min) ctx.addIssue({ code: 'custom', message: t(opts.negativeKey) })
      if (val > opts.max) ctx.addIssue({ code: 'custom', message: t(opts.tooLargeKey) })
    })
    .transform(val => (typeof val === 'number' && !Number.isNaN(val) ? val : null))
    .optional()

const yearSchema = (t: TFunction) =>
  numericOrNullField(t, {
    min: 1900,
    max: 2100,
    negativeKey: 'common:validation.vehicle.yearTooEarly',
    tooLargeKey: 'common:validation.vehicle.yearTooLate',
    invalidKey: 'common:validation.vehicle.yearInvalid',
    integerKey: 'common:validation.vehicle.yearNotWhole',
  })

const doorsSchema = (t: TFunction) =>
  numericOrNullField(t, {
    min: 0,
    max: Infinity,
    negativeKey: 'common:validation.vehicle.doorsNegative',
    tooLargeKey: 'common:validation.vehicle.doorsTooLarge',
    invalidKey: 'common:validation.vehicle.doorsInvalid',
    integerKey: 'common:validation.vehicle.doorsNotWhole',
  })

const cylindersSchema = (t: TFunction) =>
  numericOrNullField(t, {
    min: 0,
    max: Infinity,
    negativeKey: 'common:validation.vehicle.cylindersNegative',
    tooLargeKey: 'common:validation.vehicle.cylindersTooLarge',
    invalidKey: 'common:validation.vehicle.cylindersInvalid',
    integerKey: 'common:validation.vehicle.cylindersNotWhole',
  })

// No bound at all before (not even non-negative) — negativeKey/tooLargeKey
// are structurally required but provably unreachable at min:-Infinity/
// max:Infinity, so they just point at the same message as invalidKey.
const purchasePriceSchema = (t: TFunction) =>
  numericOrNullField(t, {
    min: -Infinity,
    max: Infinity,
    negativeKey: 'common:validation.vehicle.purchasePriceInvalid',
    tooLargeKey: 'common:validation.vehicle.purchasePriceInvalid',
    invalidKey: 'common:validation.vehicle.purchasePriceInvalid',
  })

// sold_price is NOT wired through registerDecimal anywhere in the current
// UI (not one of Task 8's 46 sites), so it can never receive INVALID_NUMBER
// — left on the original bespoke shape.
const soldPriceSchema = z
  .number()
  .or(z.nan())
  .nullable()
  .transform(numberOrNull)
  .optional()

// Engine-hour reading for hour-metered vehicles. Float ≥ 0, no prior upper
// bound. Previously kept an inverted `.optional()`-before-`.transform()`
// order that the old comment flagged as fragile (see git history) —
// numericOrNullField's verified ordering fixes that for free while keeping
// current_hours's own exact bound.
const currentHoursSchema = (t: TFunction) =>
  numericOrNullField(t, {
    min: 0,
    max: Infinity,
    negativeKey: 'common:validation.engineHours.negative',
    tooLargeKey: 'common:validation.engineHours.tooLarge',
    invalidKey: 'common:validation.engineHours.invalid',
  })

// `.optional()` stays outside the transform (same reasoning as the numeric
// schemas above): a non-motorized vehicle (Trailer/FifthWheel/TravelTrailer)
// never registers trim/body_class/drive_type/gvwr_class/displacement_l/
// transmission_type/transmission_speeds in VehicleEdit, so those keys are
// absent from the submitted object entirely. If `.transform()` ran before
// `.optional()`, zod would still synthesize an explicit `null` for every
// schema-defined key on the output object — even one the input never had —
// and that stray `null` survives JSON.stringify, so the backend's
// `exclude_unset=True` partial update reads it as "clear this column"
// instead of "leave unchanged". Ordering `.optional()` last makes an
// omitted key short-circuit to `undefined`, which JSON.stringify drops.

// Handle date fields that may be null, undefined, or empty string from the database
const optionalDateSchema = z
  .string()
  .nullable()
  .transform(nullOnBlank)
  .optional()

// Handle optional string fields that may be null from the database.
const optionalStringSchema = z
  .string()
  .nullable()
  .transform(nullOnBlank)
  .optional()

// nickname and vehicle_type are NOT NULL columns in the DB
// (`mapped_column(..., nullable=False)`) and required on create — they must
// NOT get the nullOnBlank treatment. Submitting an explicit `null` for
// either raises an IntegrityError server-side (409 "Database constraint
// violation") and rolls back the WHOLE update, losing every other field the
// user edited. Required non-blank here surfaces the problem as a client-side
// field error instead.
const nicknameSchema = z
  .string('Nickname is required')
  .trim()
  .min(1, 'Nickname is required')

const vehicleTypeSchema = z.enum(VEHICLE_TYPES, 'Vehicle type is required')

// fuel_type gets the same null-on-clear treatment (see nullOnBlank above),
// but as its own schema because it's additionally validated against the
// canonical enum (the <select> only ever emits one of these values or "")
// so a stray non-canonical value fails fast in the form instead of
// round-tripping to a 422 from the API. `.optional()` stays outside the
// transform for the same omitted-key reason as optionalStringSchema/
// optionalDateSchema above.
const fuelTypeSchema = z
  .union([z.enum(FUEL_TYPE_VALUES), z.literal(''), z.null()])
  .transform(nullOnBlank)
  .optional()

export const makeVehicleEditSchema = (t: TFunction) =>
  z.object({
    // Basic Information
    nickname: nicknameSchema,
    license_plate: optionalStringSchema,
    vehicle_type: vehicleTypeSchema,
    // Usage tracking: distance (odometer) or hours (hour meter). Defaulted so a
    // payload that omits it (older forms / tests) is treated as distance; the edit
    // form always supplies the vehicle's real value via its <select>.
    usage_unit: z.enum(['distance', 'hours']).default('distance'),
    current_hours: currentHoursSchema(t),
    // Also-track-the-other-dimension toggle. Defaulted so a payload that omits
    // it (older forms / tests) is treated as distance/hours-only — mirrors the
    // usage_unit default above.
    secondary_usage_enabled: z.boolean().default(false),
    color: optionalStringSchema,

    // Vehicle Details
    year: yearSchema(t),
    make: optionalStringSchema,
    model: optionalStringSchema,

    // VIN Decoded Information
    trim: optionalStringSchema,
    body_class: optionalStringSchema,
    drive_type: optionalStringSchema,
    doors: doorsSchema(t),
    gvwr_class: optionalStringSchema,

    // Engine & Transmission
    displacement_l: optionalStringSchema, // Backend expects string
    cylinders: cylindersSchema(t),
    fuel_type: fuelTypeSchema,
    transmission_type: optionalStringSchema,
    transmission_speeds: optionalStringSchema,

    // Purchase Information
    purchase_date: optionalDateSchema,
    purchase_price: purchasePriceSchema(t),

    // Sale Information
    sold_date: optionalDateSchema,
    sold_price: soldPriceSchema,

    // DEF Tracking — canonical liters. Reuses the volume message-key family
    // (same reasoning as propane_liters/def_tank_capacity in def.ts): it's
    // liters, and the min/max here (0-9999.99) are this field's own,
    // preserved exactly rather than swapped for makeOptionalVolumeSchema's
    // slightly different 9999.999 ceiling.
    def_tank_capacity_liters: numericOrNullField(t, {
      min: 0,
      max: 9999.99,
      negativeKey: 'common:validation.volume.negative',
      tooLargeKey: 'common:validation.volume.tooLarge',
      invalidKey: 'common:validation.volume.invalid',
    }),
  })

// Use z.output for Zod v4 compatibility with z.coerce fields
export type VehicleEditInput = z.input<ReturnType<typeof makeVehicleEditSchema>>
export type VehicleEditFormData = z.output<ReturnType<typeof makeVehicleEditSchema>>
