/**
 * The fuel-economy and fuel-rate family, read off the resolved set.
 *
 * This file used to test `UnitFormatter.formatFuelRate(lPerHr, system)` and
 * `getFuelRateUnit(system)`. Plan 3b task 6b migrated their call sites and
 * deleted both, along with `formatFuelEconomy` and `getFuelEconomyUnit`; what
 * follows tests the replacements, and several assertions below are answers the
 * retired API could not give at all.
 *
 * Two quantities, two shapes, and the asymmetry is the spec rather than an
 * inconsistency:
 *
 * - **Consumption** is one of the ten `UnitSet` quantities, so it is a plain
 *   `QuantityFormat` off `makeUnitFormat`. Its imperial tokens are RECIPROCAL
 *   (`mpg_us` is 235.214 / (L/100km)), so a canonical zero has no finite MPG
 *   and renders `'N/A'`; `l_100km` is linear, so the same zero is a real
 *   `'0.00 L/100km'`.
 * - **Fuel rate** is DERIVED: litres per a dimensionless engine hour. It
 *   composes the volume adapter with a fixed `'/hr'` suffix, mirroring
 *   `backend/app/utils/unit_derived.py::format_fuel_rate`, so it is a module
 *   function rather than an eleventh quantity. Volume is linear, so zero is a
 *   real rate here and the binary API's `'N/A'` at zero is gone.
 *
 * Every expectation is hand-written from the factor and the input, never read
 * off a run. The active Intl locale is `en-US` in tests.
 */

import { describe, it, expect } from 'vitest'
import { formatFuelRate, fuelRateLabel, makeUnitFormat } from '../unitFormat'
import { presetUnitsFor, type UnitSet } from '@/types/units'

const IMPERIAL = presetUnitsFor('imperial', 'us')
const UK_IMPERIAL = presetUnitsFor('imperial', 'uk')
const METRIC = presetUnitsFor('metric', 'us')
/** A metric client whose show-both counterpart is the IMPERIAL gallon (D4b). */
const METRIC_UK_PAIR: UnitSet = { ...METRIC, secondary_gallon: 'uk' }
/** Litres for volume, MPG for consumption: inexpressible under a binary system. */
const LITRES_MPG: UnitSet = { ...METRIC, consumption: 'mpg_us' }
/** The mirror: US gallons for volume, L/100km for consumption. */
const GALLONS_L100KM: UnitSet = { ...IMPERIAL, consumption: 'l_100km' }

describe('fuelRateLabel', () => {
  it('names the reader\'s own volume unit per hour', () => {
    expect(fuelRateLabel(METRIC)).toBe('L/hr')
    expect(fuelRateLabel(IMPERIAL)).toBe('gal/hr')
  })

  it('★ says gal/hr for BOTH gallon flavours, where GPH named neither', () => {
    // The retired `getFuelRateUnit` answered the three characters 'GPH' to a
    // US-gallon and a UK-gallon account for two different numbers. 'gal' is
    // what the volume adapter labels every other gallon in the app with, and
    // what `unit_derived.format_fuel_rate` prints in a PDF.
    expect(fuelRateLabel(UK_IMPERIAL)).toBe('gal/hr')
    expect(fuelRateLabel(UK_IMPERIAL)).not.toBe('GPH')
  })
})

describe('formatFuelRate', () => {
  it('renders a litre set in litres per hour, at the volume adapter\'s precision', () => {
    expect(formatFuelRate(METRIC, 3.2)).toBe('3.20 L/hr')
  })

  it('renders a US-gallon set in US gallons per hour', () => {
    // 3.78541 L is one US gallon.
    expect(formatFuelRate(IMPERIAL, 3.78541)).toBe('1.00 gal/hr')
    expect(formatFuelRate(IMPERIAL, 12)).toBe('3.17 gal/hr')
  })

  it('★ takes the gallon from the reader\'s own token, not an instance static', () => {
    // Defect L1's fuel-rate half. `UnitFormatter.formatFuelRate` divided by
    // `LITERS_PER_SECONDARY_GALLON[getGallonStandard()]`, a MUTABLE static
    // following the INSTANCE setting, so a `gal_uk` account on a US-default
    // instance read 4.54609 L/hr as 1.20 GPH beside a volume column that had
    // already converted it as one imperial gallon.
    expect(formatFuelRate(UK_IMPERIAL, 4.54609)).toBe('1.00 gal/hr')
    expect(formatFuelRate(IMPERIAL, 4.54609)).toBe('1.20 gal/hr')
  })

  it('appends the counterpart under show-both, in the D4b gallon flavour', () => {
    expect(formatFuelRate(METRIC, 3.78541, true)).toBe('3.79 L/hr (1.00 gal/hr)')
    expect(formatFuelRate(METRIC_UK_PAIR, 4.54609, true)).toBe('4.55 L/hr (1.00 gal/hr)')
    expect(formatFuelRate(IMPERIAL, 3.78541, true)).toBe('1.00 gal/hr (3.79 L/hr)')
  })

  it('★ suffixes each representation, never the composed string', () => {
    // `unit_formatting.format_rate`'s rule: "3.79 L (1.00 gal)/hr" would state
    // neither rate correctly. Asserted as a shape, so a naive
    // `${format(...)}/hr` reimplementation fails here rather than passing the
    // equality above by luck.
    const both = formatFuelRate(METRIC, 3.78541, true)
    expect(both).not.toBe('3.79 L (1.00 gal)/hr')
    expect(both.split('/hr')).toHaveLength(3)
  })

  it('omits the counterpart when show-both is off, which is the default', () => {
    expect(formatFuelRate(METRIC, 3.78541)).toBe('3.79 L/hr')
    expect(formatFuelRate(METRIC, 3.78541, false)).toBe('3.79 L/hr')
  })

  it('returns N/A for an absent or unreadable value, with no suffix', () => {
    expect(formatFuelRate(METRIC, null)).toBe('N/A')
    expect(formatFuelRate(IMPERIAL, undefined)).toBe('N/A')
    expect(formatFuelRate(METRIC, Number.NaN)).toBe('N/A')
    // The short-circuit is BEFORE the counterpart, or an absent value would
    // render as "N/A (N/A)".
    expect(formatFuelRate(METRIC, null, true)).toBe('N/A')
  })

  it('★ renders zero as a real rate, where the binary API said N/A', () => {
    // Volume is linear: burning no fuel over an interval IS 0.00 L/hr, and
    // 'N/A' claimed the figure was unknown. Matches `format_rate`, which
    // short-circuits only on a conversion that is undefined.
    expect(formatFuelRate(METRIC, 0)).toBe('0.00 L/hr')
    expect(formatFuelRate(IMPERIAL, 0)).toBe('0.00 gal/hr')
  })
})

describe('consumption, through the resolved token', () => {
  it('renders each preset in the unit that preset names', () => {
    expect(makeUnitFormat(METRIC).consumption.formatPrimary(9.4160546)).toBe('9.42 L/100km')
    // 235.214 / 9.4160546 = 24.9800..., one decimal.
    expect(makeUnitFormat(IMPERIAL).consumption.formatPrimary(9.4160546)).toBe('25.0 MPG')
  })

  it('★ takes the MPG flavour from the token, so a UK account reads UK MPG', () => {
    // 282.481 / 9.4160546 = 29.9999..., one decimal. The retired
    // `formatFuelEconomy` read the same instance-wide static the fuel rate
    // did, so this account saw 25.0 beside a 10.00 gal volume column: a figure
    // that did not divide into its own row.
    expect(makeUnitFormat(UK_IMPERIAL).consumption.formatPrimary(9.4160546)).toBe('30.0 MPG')
  })

  it('★ a litres-and-MPG set reads MPG, which no binary system could express', () => {
    // `system` is collapsed from VOLUME (spec D8), so this account resolved
    // 'metric' and was shown L/100km however it had set `consumption`.
    expect(makeUnitFormat(LITRES_MPG).consumption.formatPrimary(9.4160546)).toBe('25.0 MPG')
    expect(makeUnitFormat(LITRES_MPG).consumption.formatPrimary(9.4160546)).not.toBe(
      '9.42 L/100km',
    )
  })

  it('★ a gallons-and-L/100km set reads L/100km, the mirror of the above', () => {
    // The mirror, so the assertion above cannot be satisfied by an inverted
    // branch that simply always answers MPG.
    expect(makeUnitFormat(GALLONS_L100KM).consumption.formatPrimary(9.4160546)).toBe(
      '9.42 L/100km',
    )
    expect(makeUnitFormat(GALLONS_L100KM).consumption.formatPrimary(9.4160546)).not.toBe(
      '25.0 MPG',
    )
  })

  it('pairs a metric primary with the D4b gallon\'s MPG under show-both', () => {
    expect(makeUnitFormat(METRIC, true).consumption.format(9.4160546)).toBe(
      '9.42 L/100km (25.0 MPG)',
    )
    expect(makeUnitFormat(METRIC_UK_PAIR, true).consumption.format(9.4160546)).toBe(
      '9.42 L/100km (30.0 MPG)',
    )
  })

  it('★ has no finite MPG for a canonical zero, and a real zero in L/100km', () => {
    // MPG is reciprocal (235.214 / x), so zero is undefined in both directions
    // by construction and there is no sentinel to invent. L/100km is linear,
    // so the same canonical value is a real reading.
    expect(makeUnitFormat(IMPERIAL).consumption.formatPrimary(0)).toBe('N/A')
    expect(makeUnitFormat(IMPERIAL, true).consumption.format(0)).toBe('N/A')
    expect(makeUnitFormat(METRIC).consumption.formatPrimary(0)).toBe('0.00 L/100km')
  })

  it('★ composes a HALF-ABSENT pair at zero, and that is the honest reading', () => {
    // The asymmetry above meets show-both here and the result is
    // '0.00 L/100km (N/A)': the primary is a real value, so the null
    // short-circuit correctly declines to fire, and the counterpart genuinely
    // has none. Task 6b's changelog note said consumption keeps `N/A` at zero
    // "by construction", which is true of the RECIPROCAL tokens only; a metric
    // reader with show-both on sees this string, and it was neither documented
    // nor asserted until fix round 1.
    //
    // Reachable rather than theoretical: the backend's `calculate_l_per_100km`
    // guards `liters > 0` and `distance_km > 0` and then rounds to two places,
    // so a bad odometer entry can round to 0.00.
    expect(makeUnitFormat(METRIC, true).consumption.format(0)).toBe('0.00 L/100km (N/A)')
    // And one ulp away it is a normal pair, so the line above is the boundary
    // case rather than a broken counterpart.
    expect(makeUnitFormat(METRIC, true).consumption.format(0.001)).toBe(
      '0.00 L/100km (235,214.0 MPG)',
    )
  })

  it('returns N/A for an absent or unreadable value', () => {
    expect(makeUnitFormat(METRIC).consumption.formatPrimary(null)).toBe('N/A')
    expect(makeUnitFormat(IMPERIAL).consumption.formatPrimary(undefined)).toBe('N/A')
    expect(makeUnitFormat(METRIC).consumption.formatPrimary(Number.NaN)).toBe('N/A')
  })
})
