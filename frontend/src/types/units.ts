/**
 * Unit preference types, re-exported from the generated OpenAPI schema.
 *
 * Nothing here is hand-maintained. `AuthContext` used to declare its own
 * `unit_preference?: 'imperial' | 'metric'`, which the API freshness gate
 * cannot see: regenerating the schema passed while that union went stale, and
 * migration 093 can now write a third value it never admitted.
 */

import type { components } from './api.generated'

export type UnitSet = components['schemas']['UnitSet']
export type UnitPreference = components['schemas']['UserResponse']['unit_preference']

export type VolumeUnit = UnitSet['volume']

/**
 * The accepted token for every quantity, mirroring `app/constants/units.py`.
 *
 * `satisfies` makes the compiler reject a missing quantity and an unknown
 * token; `UNIT_OPTIONS_ARE_COMPLETE` below rejects a missing token, which
 * `satisfies` alone cannot see.
 *
 * ★ This table used to live, unexported, inside `utils/publicUnitDefaults.ts`,
 * where the only reader was that module's own parser. Phase 4 gave it a second
 * reader (the browser preference store validates a stored set the same way) and
 * will give it a third (the eleven Custom controls need the options to offer),
 * so it moved to the module that owns the vocabulary rather than being copied.
 * A second copy of the unit vocabulary is how this workstream started.
 */
export const UNIT_OPTIONS = {
  distance: ['km', 'mi'],
  speed: ['kmh', 'mph'],
  length: ['m', 'ft'],
  volume: ['L', 'gal_us', 'gal_uk'],
  consumption: ['l_100km', 'km_l', 'mpg_us', 'mpg_uk'],
  pressure: ['kpa', 'bar', 'psi'],
  temperature: ['c', 'f'],
  mass: ['kg', 'lb'],
  torque: ['nm', 'lbft'],
  tread: ['mm', 'in32'],
  secondary_gallon: ['us', 'uk'],
} as const satisfies { readonly [K in keyof UnitSet]: readonly UnitSet[K][] }

/** Any token the generated `UnitSet` admits that the table above omits. */
type MissingUnitOption = {
  [K in keyof UnitSet]: Exclude<UnitSet[K], (typeof UNIT_OPTIONS)[K][number]>
}[keyof UnitSet]

/**
 * Compile-time proof that the table lists every token of every quantity.
 *
 * An omitted token would make a perfectly valid server default unparseable and
 * silently drop the client to the legacy localStorage keys, which is the exact
 * failure `publicUnitDefaults` exists to end. The declared type collapses to
 * `false` the moment a token goes missing, and this assignment stops compiling.
 */
export const UNIT_OPTIONS_ARE_COMPLETE: [MissingUnitOption] extends [never] ? true : false = true

/** Every field of a `UnitSet`, derived from the vocabulary rather than listed. */
export const UNIT_FIELD_NAMES = Object.keys(UNIT_OPTIONS) as Array<keyof UnitSet>

/**
 * The display layer over `UNIT_OPTIONS`: a heading key per quantity, and a
 * label key per OPTION.
 *
 * ★ EVERY OPTION CARRIES ITS OWN KEY, not just every quantity. Spec D10 says
 * unit SYMBOLS are literals and unit NAMES are translated, so a select has to
 * offer "Kilopascals (kPa)" and never the raw token `kpa`. `Select` renders
 * whatever label its caller hands it, verbatim, so a table with one key per
 * quantity and nothing per option would drop `kpa`, `l_100km` and `in32`
 * straight onto the screen and pass every other test in this file.
 *
 * ★ WHY THE KEYS ARE NAMESPACE-QUALIFIED. This module never calls
 * `useTranslation`, so a bare key here has no namespace to resolve against and
 * `scripts/validate-i18n-usage.ts` reports it. Writing `settings:` carries the
 * scope with the key, which is what lets that gate check all twenty-six.
 *
 * ★ WHY THE OPTIONS ARE A RECORD KEYED BY TOKEN, and not the array-plus-
 * `Exclude` proof `UNIT_OPTIONS` needs. An ARRAY of tokens says nothing about an
 * omitted one, which is why `UNIT_OPTIONS_ARE_COMPLETE` exists above. A mapped
 * type over `UnitSet[K]` makes every token a REQUIRED key, so `satisfies`
 * rejects an omission directly and rejects an unknown token by excess-property
 * check. That is the same two-sided guarantee in one mechanism rather than two,
 * and a separate `..._ARE_COMPLETE` companion here would be a guard nothing
 * could ever make fail.
 *
 * The tokens themselves are NOT re-listed: `unitOptionsFor` reads the order and
 * the membership from `UNIT_OPTIONS`, so this table cannot become a second
 * vocabulary that disagrees with the first.
 */
type UnitLabelTable = {
  readonly [K in keyof UnitSet]: {
    readonly labelKey: string
    readonly options: { readonly [T in UnitSet[K]]: { readonly labelKey: string } }
  }
}

export const UNIT_OPTION_LABELS = {
  distance: {
    labelKey: 'settings:units.quantities.distance',
    options: {
      km: { labelKey: 'settings:units.options.distance.km' },
      mi: { labelKey: 'settings:units.options.distance.mi' },
    },
  },
  speed: {
    labelKey: 'settings:units.quantities.speed',
    options: {
      kmh: { labelKey: 'settings:units.options.speed.kmh' },
      mph: { labelKey: 'settings:units.options.speed.mph' },
    },
  },
  length: {
    labelKey: 'settings:units.quantities.length',
    options: {
      m: { labelKey: 'settings:units.options.length.m' },
      ft: { labelKey: 'settings:units.options.length.ft' },
    },
  },
  volume: {
    labelKey: 'settings:units.quantities.volume',
    options: {
      L: { labelKey: 'settings:units.options.volume.L' },
      gal_us: { labelKey: 'settings:units.options.volume.gal_us' },
      gal_uk: { labelKey: 'settings:units.options.volume.gal_uk' },
    },
  },
  consumption: {
    labelKey: 'settings:units.quantities.consumption',
    options: {
      l_100km: { labelKey: 'settings:units.options.consumption.l_100km' },
      km_l: { labelKey: 'settings:units.options.consumption.km_l' },
      mpg_us: { labelKey: 'settings:units.options.consumption.mpg_us' },
      mpg_uk: { labelKey: 'settings:units.options.consumption.mpg_uk' },
    },
  },
  pressure: {
    labelKey: 'settings:units.quantities.pressure',
    options: {
      kpa: { labelKey: 'settings:units.options.pressure.kpa' },
      bar: { labelKey: 'settings:units.options.pressure.bar' },
      psi: { labelKey: 'settings:units.options.pressure.psi' },
    },
  },
  temperature: {
    labelKey: 'settings:units.quantities.temperature',
    options: {
      c: { labelKey: 'settings:units.options.temperature.c' },
      f: { labelKey: 'settings:units.options.temperature.f' },
    },
  },
  mass: {
    labelKey: 'settings:units.quantities.mass',
    options: {
      kg: { labelKey: 'settings:units.options.mass.kg' },
      lb: { labelKey: 'settings:units.options.mass.lb' },
    },
  },
  torque: {
    labelKey: 'settings:units.quantities.torque',
    options: {
      nm: { labelKey: 'settings:units.options.torque.nm' },
      lbft: { labelKey: 'settings:units.options.torque.lbft' },
    },
  },
  tread: {
    labelKey: 'settings:units.quantities.tread',
    options: {
      mm: { labelKey: 'settings:units.options.tread.mm' },
      in32: { labelKey: 'settings:units.options.tread.in32' },
    },
  },
  secondary_gallon: {
    labelKey: 'settings:units.quantities.secondaryGallon',
    options: {
      us: { labelKey: 'settings:units.options.secondary_gallon.us' },
      uk: { labelKey: 'settings:units.options.secondary_gallon.uk' },
    },
  },
} as const satisfies UnitLabelTable

/** One choice a per-quantity control offers. */
export interface UnitOptionChoice {
  /** The stored token, which is what a write sends. */
  readonly value: string
  /** The translation key for its name, per D10. Never the token itself. */
  readonly labelKey: string
}

/**
 * The choices one quantity offers, in vocabulary order, each with its key.
 *
 * @param field The quantity to offer.
 * @returns Its tokens paired with their label keys.
 */
export function unitOptionsFor(field: keyof UnitSet): readonly UnitOptionChoice[] {
  const labels: Readonly<Record<string, { readonly labelKey: string }>> =
    UNIT_OPTION_LABELS[field].options
  const vocabulary: readonly string[] = UNIT_OPTIONS[field]
  return vocabulary.map((value) => ({ value, labelKey: labels[value].labelKey }))
}

/**
 * Replace one quantity's token, refusing anything outside its vocabulary.
 *
 * The single cast lives here, next to the table that justifies it, rather than
 * at each of the eleven controls: `{ ...units, [field]: token }` widens the
 * field to `string` and there is no way to spread into a mapped type without
 * one. Guarding it on membership means the cast is only reached for a token
 * `UnitSet` already admits.
 *
 * @param units The set to change.
 * @param field The quantity to change.
 * @param token The candidate token, straight off a `<select>`.
 * @returns The new set, or null when the token is not one this quantity takes.
 */
export function withUnitField(units: UnitSet, field: keyof UnitSet, token: string): UnitSet | null {
  const vocabulary: readonly string[] = UNIT_OPTIONS[field]
  if (!vocabulary.includes(token)) return null
  return { ...units, [field]: token } as UnitSet
}

/**
 * Read an untrusted value as a complete, in-vocabulary `UnitSet`.
 *
 * Degrades WHOLE, mirroring `app/utils/default_unit_prefs.py`: a partial or
 * out-of-vocabulary set yields `null` rather than being patched field by field,
 * because filling the gaps from an imperial default would hand a metric client
 * imperial pressure. `null` means "there is nothing trustworthy here", and the
 * caller drops to whatever it has next.
 *
 * @param value A parsed candidate, from a settings row or from browser storage.
 * @returns The resolved set, or null when it is not a complete, valid one.
 */
export function coerceUnitSet(value: unknown): UnitSet | null {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return null

  const candidate = value as Record<string, unknown>
  // Arity first: this plus the per-field check below is the frontend's
  // equivalent of the model's `extra="forbid"` with every field required. An
  // unknown key means the writer and the reader disagree about the shape.
  if (Object.keys(candidate).length !== UNIT_FIELD_NAMES.length) return null

  for (const field of UNIT_FIELD_NAMES) {
    const token = candidate[field]
    const vocabulary: readonly string[] = UNIT_OPTIONS[field]
    if (typeof token !== 'string' || !vocabulary.includes(token)) return null
  }

  return candidate as UnitSet
}

/**
 * Collapse a resolved volume unit to the binary system the older helpers expect.
 *
 * Spec D8: a `custom` user still has to give `supplyUnits` and every other
 * binary consumer a defined answer, and the resolved volume unit is what
 * supplies it. Any gallon is imperial; litres are metric.
 */
export function binarySystemFor(volume: VolumeUnit): 'metric' | 'imperial' {
  // units-exempt(token-branch): D8's single admitted collapse, and the token read IS the quantity being asked about rather than a proxy for another one. Not deferred work: while any binary consumer survives, one of them has to be given a defined answer, and concentrating the collapse in one exported function is what makes the population countable. Kind-scoped, so a comparison of a DIFFERENT quantity added to this line would still be reported.
  return volume === 'L' ? 'metric' : 'imperial'
}

/**
 * The ten convertible quantities, in the order `UnitSet` declares them.
 *
 * `secondary_gallon` is deliberately absent: it is D4b's flavour hint for a
 * primary that cannot state its own gallon, not a quantity anything converts.
 * Asking for an adapter for it would be a bug, so the type forbids it.
 */
export type UnitQuantity = Exclude<keyof UnitSet, 'secondary_gallon'>

/**
 * The quantity names, as a value.
 *
 * `satisfies` rejects a name that is not a quantity; `UNIT_QUANTITIES_ARE_COMPLETE`
 * below rejects a quantity this list forgets, which `satisfies` alone cannot
 * see. Same two-sided proof `publicUnitDefaults.ts` uses for the vocabulary.
 */
export const UNIT_QUANTITIES = [
  'distance',
  'speed',
  'length',
  'volume',
  'consumption',
  'pressure',
  'temperature',
  'mass',
  'torque',
  'tread',
] as const satisfies readonly UnitQuantity[]

/** Any quantity the list above omits. */
type MissingQuantity = Exclude<UnitQuantity, (typeof UNIT_QUANTITIES)[number]>

/**
 * Compile-time proof that the list names every quantity.
 *
 * A forgotten quantity would give `makeUnitFormat` a hole rather than an error:
 * the returned record's type would still claim the key exists, and the call site
 * would read `undefined.label` at runtime. The declared type collapses to
 * `false` the moment one goes missing, and this assignment stops compiling.
 */
export const UNIT_QUANTITIES_ARE_COMPLETE: [MissingQuantity] extends [never] ? true : false = true

/** The gallon flavour a browser holds, as `UnitSet` spells it. */
type GallonFlavour = UnitSet['secondary_gallon']

/**
 * The four preset unit sets, mirroring `app/constants/units.py`'s
 * `METRIC_PRESET` / `IMPERIAL_PRESET` and `app/utils/default_unit_prefs.py`'s
 * `UK_IMPERIAL_PRESET` (the imperial preset with volume, consumption and
 * secondary_gallon replaced).
 *
 * Frozen module constants rather than objects built per call, so a hook that
 * memoizes on the resolved set does not recompute on every render.
 */
const UNIT_PRESETS: Readonly<Record<'imperial' | 'metric', Readonly<Record<GallonFlavour, UnitSet>>>> =
  {
    imperial: {
      us: {
        distance: 'mi',
        speed: 'mph',
        length: 'ft',
        volume: 'gal_us',
        consumption: 'mpg_us',
        pressure: 'psi',
        temperature: 'f',
        mass: 'lb',
        torque: 'lbft',
        tread: 'in32',
        secondary_gallon: 'us',
      },
      uk: {
        distance: 'mi',
        speed: 'mph',
        length: 'ft',
        volume: 'gal_uk',
        consumption: 'mpg_uk',
        pressure: 'psi',
        temperature: 'f',
        mass: 'lb',
        torque: 'lbft',
        tread: 'in32',
        secondary_gallon: 'uk',
      },
    },
    metric: {
      us: {
        distance: 'km',
        speed: 'kmh',
        length: 'm',
        volume: 'L',
        consumption: 'l_100km',
        pressure: 'kpa',
        temperature: 'c',
        mass: 'kg',
        torque: 'nm',
        tread: 'mm',
        secondary_gallon: 'us',
      },
      uk: {
        distance: 'km',
        speed: 'kmh',
        length: 'm',
        volume: 'L',
        consumption: 'l_100km',
        pressure: 'kpa',
        temperature: 'c',
        mass: 'kg',
        torque: 'nm',
        tread: 'mm',
        secondary_gallon: 'uk',
      },
    },
  }

/**
 * Expand a binary system plus a gallon flavour into a full resolved set.
 *
 * Two rungs of `useUnitPreference` hold exactly that pair and no resolved set:
 * an explicit anonymous choice (the `unit_preference` key plus the browser's
 * cached gallon standard) and the post-093 fallback. Both still have to hand
 * `useUnitFormat` a complete `UnitSet`, and inventing one at the call site is
 * how a fourth copy of the preset table would appear.
 *
 * @param system The binary unit system the client resolved to.
 * @param gallonStandard The gallon flavour the browser holds.
 * @returns The matching preset. The same object every time, per pair.
 */
export function presetUnitsFor(
  system: 'metric' | 'imperial',
  gallonStandard: GallonFlavour
): UnitSet {
  return UNIT_PRESETS[system][gallonStandard]
}

/**
 * The gallon flavour the two canonical presets are written in.
 *
 * `METRIC_PRESET` and `IMPERIAL_PRESET` in `app/constants/units.py` both carry
 * `secondary_gallon='us'`, so a set expanded with the UK flavour is NOT the
 * preset its binary system names and `presetTagFor` has to say so.
 */
const PRESET_GALLON_FLAVOUR: GallonFlavour = 'us'

/**
 * Whether two resolved sets agree on every quantity.
 *
 * @param a One set.
 * @param b The other.
 * @returns True when every field matches.
 */
function sameUnitSet(a: UnitSet, b: UnitSet): boolean {
  return UNIT_FIELD_NAMES.every((field) => a[field] === b[field])
}

/**
 * Name a resolved set the way a control has to label it.
 *
 * A preset tag is a CLAIM THAT THE SET IS THAT PRESET. Anything else is
 * `custom`, which is the rule migration 093 applies when it retags a UK-gallon
 * imperial account (`093_add_unit_preferences.py`,
 * `_materialise_uk_imperial_users`).
 *
 * ★ IT LIVES HERE BECAUSE TWO CALLERS NEED THE SAME ANSWER. `unitPrefsStore`
 * derives the browser's tag with it so a stored tag can never contradict its
 * stored set, and `UnitPreferencesCard` asks it whether a write that names a
 * preset would CLEAR override columns that are currently carrying the account:
 * `PUT /auth/me/units` writes eleven nulls for any preset, so sending the
 * account's stored tag while its resolved set is not that preset would destroy
 * the set as a side effect of toggling something else. Two copies of that rule
 * is how this workstream started; one copy is why it is in the module that owns
 * the presets.
 *
 * @param units A resolved set.
 * @returns The preset it matches exactly, or 'custom'.
 */
export function presetTagFor(units: UnitSet): UnitPreference {
  const system = binarySystemFor(units.volume)
  return sameUnitSet(units, presetUnitsFor(system, PRESET_GALLON_FLAVOUR)) ? system : 'custom'
}

/**
 * The set a PRESET resolves to once every override column is cleared.
 *
 * Mirrors `app/constants/units.py::base_preset_for`. Both canonical presets are
 * written with `secondary_gallon='us'`, so choosing Imperial lands a UK-gallon
 * client on US gallons: a 20 percent move in every volume and every MPG, from a
 * button labelled with the system it is already on (R4). The card warns about
 * that before it writes, and the browser-store writer expands a preset through
 * THIS function so the same button means the same thing with and without an
 * account.
 *
 * @param preference The preset chosen.
 * @returns The set the route would resolve that preset to.
 */
export function basePresetFor(preference: 'imperial' | 'metric'): UnitSet {
  return presetUnitsFor(preference, PRESET_GALLON_FLAVOUR)
}
