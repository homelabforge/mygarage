import { z } from 'zod'
import { FUEL_TYPE_VALUES } from '../constants/fuel'

/**
 * Vehicle schema for VehicleEdit and VehicleWizard forms.
 * Matches backend Pydantic validators.
 * See: backend/app/schemas/vehicle.py
 */

export const VEHICLE_TYPES = [
  'Car',
  'SUV',
  'Truck',
  'Motorcycle',
  'RV',
  'Trailer',
  'FifthWheel',
  'TravelTrailer',
  'Electric',
  'Hybrid',
] as const

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
// undefined -> null, but a legitimate 0 survives (the backend has no
// lower-bound constraint on prices, doors, or cylinders — the min(0)
// checks below are frontend-only). Distinguishing 0 from blank is why
// numeric fields can't reuse the falsy `nullOnBlank`.
const numberOrNull = (val: number | null | undefined): number | null =>
  val == null || Number.isNaN(val) ? null : val

// The `.nullable()` before the transform matters: a vehicle stored with
// NULL year/doors/cylinders seeds the form with raw `null`, which must
// parse (to null) — otherwise zod hard-fails and NO edit of that vehicle
// can be saved until the user touches the numeric field. `.optional()`
// stays outside the transform so an omitted key (e.g. doors on a
// non-motorized vehicle, where the field isn't registered) passes through
// as `undefined` and gets dropped from the payload instead of
// force-clearing the column.
const yearSchema = z
  .number()
  .int('Year must be a whole number')
  .min(1900, 'Year must be 1900 or later')
  .max(2100, 'Year must be 2100 or earlier')
  .or(z.nan())
  .nullable()
  .transform(numberOrNull)
  .optional()

const doorsSchema = z
  .number()
  .int('Doors must be a whole number')
  .min(0, 'Doors cannot be negative')
  .or(z.nan())
  .nullable()
  .transform(numberOrNull)
  .optional()

const cylindersSchema = z
  .number()
  .int('Cylinders must be a whole number')
  .min(0, 'Cylinders cannot be negative')
  .or(z.nan())
  .nullable()
  .transform(numberOrNull)
  .optional()

const purchasePriceSchema = z
  .number()
  .or(z.nan())
  .nullable()
  .optional()
  .transform(numberOrNull)

const soldPriceSchema = z
  .number()
  .or(z.nan())
  .nullable()
  .optional()
  .transform(numberOrNull)

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

export const vehicleEditSchema = z.object({
  // Basic Information
  nickname: nicknameSchema,
  license_plate: optionalStringSchema,
  vehicle_type: vehicleTypeSchema,
  color: optionalStringSchema,

  // Vehicle Details
  year: yearSchema,
  make: optionalStringSchema,
  model: optionalStringSchema,

  // VIN Decoded Information
  trim: optionalStringSchema,
  body_class: optionalStringSchema,
  drive_type: optionalStringSchema,
  doors: doorsSchema,
  gvwr_class: optionalStringSchema,

  // Engine & Transmission
  displacement_l: optionalStringSchema, // Backend expects string
  cylinders: cylindersSchema,
  fuel_type: fuelTypeSchema,
  transmission_type: optionalStringSchema,
  transmission_speeds: optionalStringSchema,

  // Purchase Information
  purchase_date: optionalDateSchema,
  purchase_price: purchasePriceSchema,

  // Sale Information
  sold_date: optionalDateSchema,
  sold_price: soldPriceSchema,

  // DEF Tracking — canonical liters
  def_tank_capacity_liters: z
    .number()
    .min(0, 'Tank capacity cannot be negative')
    .max(9999.99, 'Tank capacity too large')
    .or(z.nan())
    .nullable()
    .optional()
    .transform(val => (typeof val === 'number' && isNaN(val)) ? null : val),
})

// Use z.output for Zod v4 compatibility with z.coerce fields
export type VehicleEditInput = z.input<typeof vehicleEditSchema>
export type VehicleEditFormData = z.output<typeof vehicleEditSchema>
