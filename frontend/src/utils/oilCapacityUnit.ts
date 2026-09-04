/**
 * Engine oil capacity, read in the unit people actually use for it.
 *
 * It went through the shared `volume` adapter, which is correct for fuel and
 * wrong here: a reader on `gal_us` was asked for GALLONS of engine oil. The
 * failure was silent rather than ugly. Entering `12` for a 6.7 Cummins stored
 * `12 x 3.785411784 = 45.42 L` and the card read `12 gal` straight back, so the
 * round trip was symmetric and the UI could not show the error. It surfaces
 * only where something else reads the canonical litres: an Ask My Garage
 * answer, a PDF, an export. Measured on a real instance, two vehicles were
 * stored 3.785x over before anyone noticed.
 *
 * Entering it correctly would have meant typing `3.01` for twelve quarts, which
 * is why this is a unit bug and not a user error.
 *
 * WHY NOT A TOKEN IN `UnitSet`
 * ----------------------------
 * Because `UnitToken` is `UnitSet[UnitQuantity]`, so a quart token means
 * amending the vocabulary: the settings UI, the presets,
 * `unit_resolution.py`, and every exhaustive `Record` over the union. That is
 * the D8 amendment `utils/supplyUnits.ts` has been waiting on, and it is a spec
 * decision rather than a refactor. This is deliberately smaller: one derived
 * adapter for one quantity, no new vocabulary, nothing else re-interpreted.
 *
 * THE QUART IS DERIVED, NOT CONSTANTED
 * ------------------------------------
 * `supplyUnits.ts` hardcodes `L_PER_QUART = 0.946352946`, the US liquid quart,
 * and its own docstring records the 20.1% defect that leaves on UK instances
 * along with the fix: `LITERS_PER_VOLUME_UNIT[gal_x] / 4`, derivable today. So
 * that is what this does, and the UK reader is right on day one. Supplies is
 * deliberately NOT changed here: its factor re-interprets quantities already
 * stored, and no column records which quart a row was written in, which is a
 * data decision that belongs with the amendment.
 */

import { UnitConverter } from '@/utils/units'
import type { UnitSet } from '@/types/units'
import { type UnitAdapter } from './unitAdapters'
import { formatForAdapter, type QuantityFormat } from './unitFormat'

/** Quarts in one gallon, US or Imperial alike. */
const QUARTS_PER_GALLON = 4

/** Decimals an oil capacity is read at: 5.0 qt, 11.4 L. */
const OIL_CAPACITY_PRECISION = 1

/**
 * The sub-unit an oil capacity is read in, for each volume a reader can resolve to.
 *
 * A TABLE keyed by the resolved token rather than a branch on it, so the
 * vocabulary decides and every token must answer. A branch would let a volume
 * unit added later fall silently into whichever leg it did not match, which is
 * the shape of the bug this file exists to fix; `tsc` fails this Record instead
 * and asks what the new unit means for oil.
 *
 * Each quart is a quarter of the gallon the reader already resolved to, so the
 * UK reader gets the Imperial quart (1.1365 L) rather than the US one. That is
 * the 20.1% defect `utils/supplyUnits.ts` records against its hardcoded
 * `L_PER_QUART`, avoided here by the derivation its own docstring recommends.
 */
const OIL_UNIT_BY_VOLUME: Readonly<
  Record<UnitSet['volume'], { readonly label: string; readonly litres: number }>
> = {
  L: { label: 'L', litres: 1 },
  gal_us: { label: 'qt', litres: UnitConverter.US_GALLONS_TO_LITERS / QUARTS_PER_GALLON },
  gal_uk: { label: 'qt', litres: UnitConverter.UK_GALLONS_TO_LITERS / QUARTS_PER_GALLON },
}

/** Twelve significant digits, matching `unitAdapters.normalise`. */
function normalise(value: number | null | undefined): number | null {
  if (value === null || value === undefined || Number.isNaN(value)) return null
  return Number(value.toPrecision(12))
}

/**
 * The unit an oil capacity is read and entered in, for one resolved set.
 *
 * `unit` reports the volume token the reader resolved to: this adapter serves
 * the volume quantity expressed in the sub-unit the vocabulary cannot name, and
 * claiming a token that does not exist would neither type-check nor be true.
 */
function oilCapacityAdapter(units: UnitSet): UnitAdapter {
  const { label, litres } = OIL_UNIT_BY_VOLUME[units.volume]
  return {
    unit: units.volume,
    label,
    precision: OIL_CAPACITY_PRECISION,
    toCanonical(typed) {
      const value = normalise(typed)
      return value === null ? null : normalise(value * litres)
    },
    toDisplay(canonical) {
      const value = normalise(canonical)
      return value === null ? null : normalise(value / litres)
    },
  }
}

/**
 * Formatter for a vehicle's engine oil capacity.
 *
 * Same surface as every table-driven quantity, so callers use
 * `seedUnitField` / `readUnitField` and the untouched-field rule unchanged.
 * No counterpart: show-both pairs a unit with its opposite system's unit, and
 * the quart's opposite is the litre this already renders for that reader.
 *
 * @param units The client's resolved unit set.
 * @returns The formatter.
 */
export function oilCapacityFormat(units: UnitSet): QuantityFormat {
  return formatForAdapter(oilCapacityAdapter(units), null, false)
}
