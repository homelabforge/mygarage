/**
 * The conversion layer, mirroring `backend/app/utils/unit_adapters.py` and
 * `unit_counterparts.py`.
 *
 * Every expected number below is hand-written from the factor and the input,
 * never produced by running the adapter. The factors are the ones
 * `UnitConverter` already declares, plus 25.4/32 for tread, which existed
 * nowhere in the frontend before this module.
 */
import { describe, it, expect } from 'vitest'
import {
  UNIT_ADAPTERS,
  adapterFor,
  counterpartFor,
  radiusToMeters,
  type UnitToken,
} from '../unitAdapters'
import { presetUnitsFor, type UnitQuantity } from '@/types/units'
import type { UnitSet } from '@/types/units'

/**
 * Every token's label and decimal precision, hand-written against
 * `unit_adapters.py`'s ADAPTERS table.
 *
 * Typed as `Record<UnitToken, ...>`, so a token added to the vocabulary that
 * this file forgets is a compile error rather than an untested adapter.
 *
 * The two temperature labels deliberately differ from the backend's bare `C`
 * and `F`: the UI has always rendered the degree sign, and dropping it here
 * would make a phase-3b call-site migration a visible regression for no gain.
 * Every other label matches the backend character for character. (The cite for
 * "has always rendered" used to be `UnitFormatter.getTemperatureUnit`; phase 3b
 * task 2 deleted it as an uncalled binary API, so these labels are now the only
 * place the degree sign is decided.)
 */
const EXPECTED: Record<UnitToken, { label: string; precision: number }> = {
  km: { label: 'km', precision: 0 },
  mi: { label: 'mi', precision: 0 },
  kmh: { label: 'km/h', precision: 0 },
  mph: { label: 'mph', precision: 0 },
  m: { label: 'm', precision: 2 },
  ft: { label: 'ft', precision: 2 },
  L: { label: 'L', precision: 2 },
  gal_us: { label: 'gal', precision: 2 },
  gal_uk: { label: 'gal', precision: 2 },
  l_100km: { label: 'L/100km', precision: 2 },
  km_l: { label: 'km/L', precision: 2 },
  mpg_us: { label: 'MPG', precision: 1 },
  mpg_uk: { label: 'MPG', precision: 1 },
  kpa: { label: 'kPa', precision: 0 },
  bar: { label: 'bar', precision: 2 },
  psi: { label: 'PSI', precision: 1 },
  c: { label: '°C', precision: 1 },
  f: { label: '°F', precision: 1 },
  kg: { label: 'kg', precision: 2 },
  lb: { label: 'lb', precision: 2 },
  nm: { label: 'Nm', precision: 1 },
  lbft: { label: 'lb-ft', precision: 1 },
  mm: { label: 'mm', precision: 2 },
  in32: { label: '/32 in', precision: 0 },
}

describe('UNIT_ADAPTERS', () => {
  it('carries one adapter per token, with the backend label and precision', () => {
    for (const [token, expected] of Object.entries(EXPECTED)) {
      const adapter = UNIT_ADAPTERS[token as UnitToken]
      expect(adapter.unit).toBe(token)
      expect(adapter.label).toBe(expected.label)
      expect(adapter.precision).toBe(expected.precision)
    }
  })

  it('has no token the expectation table above does not name', () => {
    expect(Object.keys(UNIT_ADAPTERS).sort()).toStrictEqual(Object.keys(EXPECTED).sort())
  })
})

describe('linear conversion', () => {
  it('converts miles to kilometres and back', () => {
    // 100 mi x 1.60934 = 160.934 km
    expect(UNIT_ADAPTERS.mi.toCanonical(100)).toBe(160.934)
    expect(UNIT_ADAPTERS.mi.toDisplay(160.934)).toBe(100)
  })

  it('converts thirty-seconds of an inch to millimetres and back', () => {
    // 25.4 / 32 = 0.79375 mm per 1/32 in, so 9/32 in is 7.14375 mm exactly.
    expect(UNIT_ADAPTERS.in32.toCanonical(9)).toBe(7.14375)
    // 2/32 in, the value an untouched imperial tire form would submit if the
    // canonical 2.0 mm default were read as a display value.
    expect(UNIT_ADAPTERS.in32.toCanonical(2)).toBe(1.5875)
    // 7.5 mm / 0.79375 = 9.448818897637795..., kept to 12 significant digits.
    expect(UNIT_ADAPTERS.in32.toDisplay(7.5)).toBe(9.44881889764)
  })

  it('treats zero as a real value, not an undefined one', () => {
    expect(UNIT_ADAPTERS.kpa.toCanonical(0)).toBe(0)
    expect(UNIT_ADAPTERS.mi.toDisplay(0)).toBe(0)
  })

  it('applies the Fahrenheit offset in both directions', () => {
    // (212 - 32) x 5/9 = 100
    expect(UNIT_ADAPTERS.f.toCanonical(212)).toBe(100)
    // 100 / (5/9) + 32 = 212
    expect(UNIT_ADAPTERS.f.toDisplay(100)).toBe(212)
    // Freezing point: the offset alone, with the factor contributing nothing.
    expect(UNIT_ADAPTERS.f.toCanonical(32)).toBe(0)
    expect(UNIT_ADAPTERS.f.toDisplay(0)).toBe(32)
  })

  it('converts both gallon flavours with their own factor', () => {
    expect(UNIT_ADAPTERS.gal_us.toCanonical(10)).toBe(37.8541)
    expect(UNIT_ADAPTERS.gal_uk.toCanonical(10)).toBe(45.4609)
  })

  it('converts bar by the SI definition, not through PSI', () => {
    // 1 bar = 100 kPa exactly.
    expect(UNIT_ADAPTERS.bar.toCanonical(2.5)).toBe(250)
    expect(UNIT_ADAPTERS.bar.toDisplay(250)).toBe(2.5)
  })

  it('converts pressure, mass, torque and length by their declared factors', () => {
    expect(UNIT_ADAPTERS.psi.toCanonical(35)).toBe(241.3166)
    expect(UNIT_ADAPTERS.lb.toCanonical(10)).toBe(4.53592)
    expect(UNIT_ADAPTERS.lbft.toCanonical(100)).toBe(135.582)
    expect(UNIT_ADAPTERS.ft.toCanonical(10)).toBe(3.048)
  })

  it('is an identity for a metric token whose typed unit is canonical', () => {
    expect(UNIT_ADAPTERS.km.toCanonical(1234.5)).toBe(1234.5)
    expect(UNIT_ADAPTERS.mm.toDisplay(7.5)).toBe(7.5)
    expect(UNIT_ADAPTERS.L.toCanonical(47.318)).toBe(47.318)
  })

  it('trims binary float noise to twelve significant digits', () => {
    // 34.8 x 6.89476 evaluates to 239.93764799999997 in IEEE 754. Sending that
    // through the API is how a stored value ends up one ulp off its own
    // conversion, so the boundary normalises it the way
    // `UnitConverter.toCanonicalMetricString` already does.
    expect(UNIT_ADAPTERS.psi.toCanonical(34.8)).toBe(239.937648)
  })

  it('passes null and undefined straight through', () => {
    expect(UNIT_ADAPTERS.psi.toCanonical(null)).toBeNull()
    expect(UNIT_ADAPTERS.psi.toDisplay(null)).toBeNull()
    expect(UNIT_ADAPTERS.psi.toCanonical(undefined)).toBeNull()
    expect(UNIT_ADAPTERS.in32.toDisplay(undefined)).toBeNull()
  })

  it('refuses a value that is not a number', () => {
    // `Number('')` is 0 and `Number('abc')` is NaN; both reach these adapters
    // from a form field, and 0 kPa is a real reading while NaN is not.
    expect(UNIT_ADAPTERS.psi.toCanonical(Number.NaN)).toBeNull()
    expect(UNIT_ADAPTERS.psi.toDisplay(Number.NaN)).toBeNull()
  })
})

describe('inverse conversion', () => {
  it('is its own inverse for MPG', () => {
    // 235.214 / 30 MPG = 7.84046666666... L/100km, to 12 significant digits.
    expect(UNIT_ADAPTERS.mpg_us.toCanonical(30)).toBe(7.84046666667)
    // 235.214 / 23.5214 = 10 MPG
    expect(UNIT_ADAPTERS.mpg_us.toDisplay(23.5214)).toBe(10)
  })

  it('uses the UK numerator for UK MPG', () => {
    // 282.481 / 40 = 7.062025
    expect(UNIT_ADAPTERS.mpg_uk.toCanonical(40)).toBe(7.062025)
  })

  it('converts km/L through the hundred that names L/100km', () => {
    expect(UNIT_ADAPTERS.km_l.toCanonical(20)).toBe(5)
    expect(UNIT_ADAPTERS.km_l.toDisplay(5)).toBe(20)
  })

  it('treats zero as undefined in both directions, unlike a linear adapter', () => {
    expect(UNIT_ADAPTERS.mpg_us.toCanonical(0)).toBeNull()
    expect(UNIT_ADAPTERS.mpg_us.toDisplay(0)).toBeNull()
    expect(UNIT_ADAPTERS.km_l.toCanonical(0)).toBeNull()
  })
})

describe('adapterFor', () => {
  it('resolves each quantity to the token the set names', () => {
    const imperial = presetUnitsFor('imperial', 'us')
    expect(adapterFor(imperial, 'tread').unit).toBe('in32')
    expect(adapterFor(imperial, 'pressure').unit).toBe('psi')
    expect(adapterFor(imperial, 'distance').unit).toBe('mi')

    const metric = presetUnitsFor('metric', 'us')
    expect(adapterFor(metric, 'tread').unit).toBe('mm')
    expect(adapterFor(metric, 'pressure').unit).toBe('kpa')
    expect(adapterFor(metric, 'distance').unit).toBe('km')
  })

  it('follows a per-quantity override rather than the preset it came from', () => {
    // The custom user D3 exists for: metric volume, imperial tread.
    const custom: UnitSet = { ...presetUnitsFor('metric', 'us'), tread: 'in32', pressure: 'bar' }
    expect(adapterFor(custom, 'tread').unit).toBe('in32')
    expect(adapterFor(custom, 'pressure').unit).toBe('bar')
    expect(adapterFor(custom, 'volume').unit).toBe('L')
  })

  it('answers for every quantity of every preset', () => {
    for (const system of ['imperial', 'metric'] as const) {
      for (const gallon of ['us', 'uk'] as const) {
        const units = presetUnitsFor(system, gallon)
        for (const quantity of ['distance', 'tread', 'pressure', 'volume'] as UnitQuantity[]) {
          expect(adapterFor(units, quantity).unit).toBe(units[quantity])
        }
      }
    }
  })
})

describe('counterpartFor', () => {
  it('is asymmetric where the spec says it is', () => {
    // bar and kpa both counterpart to psi, but psi counterparts to kpa, never bar.
    const bar: UnitSet = { ...presetUnitsFor('metric', 'us'), pressure: 'bar' }
    expect(counterpartFor(bar, 'pressure')?.unit).toBe('psi')
    expect(counterpartFor(presetUnitsFor('metric', 'us'), 'pressure')?.unit).toBe('psi')
    expect(counterpartFor(presetUnitsFor('imperial', 'us'), 'pressure')?.unit).toBe('kpa')
  })

  it("takes a litre primary's gallon flavour from secondary_gallon", () => {
    expect(counterpartFor(presetUnitsFor('metric', 'us'), 'volume')?.unit).toBe('gal_us')
    expect(counterpartFor(presetUnitsFor('metric', 'uk'), 'volume')?.unit).toBe('gal_uk')
  })

  it('ignores secondary_gallon when the primary states its own flavour', () => {
    const conflicted: UnitSet = { ...presetUnitsFor('imperial', 'us'), secondary_gallon: 'uk' }
    expect(counterpartFor(conflicted, 'volume')?.unit).toBe('L')
    expect(counterpartFor(conflicted, 'consumption')?.unit).toBe('l_100km')
  })

  it('takes a metric consumption counterpart from secondary_gallon', () => {
    expect(counterpartFor(presetUnitsFor('metric', 'us'), 'consumption')?.unit).toBe('mpg_us')
    expect(counterpartFor(presetUnitsFor('metric', 'uk'), 'consumption')?.unit).toBe('mpg_uk')
    const kmL: UnitSet = { ...presetUnitsFor('metric', 'uk'), consumption: 'km_l' }
    expect(counterpartFor(kmL, 'consumption')?.unit).toBe('mpg_uk')
  })

  it('pairs tread both ways', () => {
    expect(counterpartFor(presetUnitsFor('imperial', 'us'), 'tread')?.unit).toBe('mm')
    expect(counterpartFor(presetUnitsFor('metric', 'us'), 'tread')?.unit).toBe('in32')
  })

  it('never points a token at itself, for any token of any quantity', () => {
    // A self-referencing entry renders the same number twice under show-both
    // and looks correct while being useless.
    for (const token of Object.keys(EXPECTED) as UnitToken[]) {
      // Placed on whichever quantity legitimately accepts this token.
      const owner = QUANTITY_OF[token]
      const units = { ...presetUnitsFor('metric', 'us'), [owner]: token } as UnitSet
      const resolved = counterpartFor(units, owner)
      expect(resolved).not.toBeNull()
      expect(resolved?.unit).not.toBe(token)
    }
  })
})

/** Which quantity each token belongs to, hand-written from the vocabulary. */
const QUANTITY_OF: Record<UnitToken, UnitQuantity> = {
  km: 'distance',
  mi: 'distance',
  kmh: 'speed',
  mph: 'speed',
  m: 'length',
  ft: 'length',
  L: 'volume',
  gal_us: 'volume',
  gal_uk: 'volume',
  l_100km: 'consumption',
  km_l: 'consumption',
  mpg_us: 'consumption',
  mpg_uk: 'consumption',
  kpa: 'pressure',
  bar: 'pressure',
  psi: 'pressure',
  c: 'temperature',
  f: 'temperature',
  kg: 'mass',
  lb: 'mass',
  nm: 'torque',
  lbft: 'torque',
  mm: 'tread',
  in32: 'tread',
}

describe('radiusToMeters', () => {
  it('reads the radius in the set own distance unit, not in a binary system', () => {
    // 5 mi x 1.60934 = 8.0467 km = 8046.7 m.
    expect(radiusToMeters(presetUnitsFor('imperial', 'us'), 5)).toBe(8047)
    expect(radiusToMeters(presetUnitsFor('metric', 'us'), 10)).toBe(10000)
  })

  it('follows the DISTANCE token for a custom set whose volume says otherwise', () => {
    // D8 collapses `system` from volume, so this set reads 'metric' and used to
    // get kilometre radii while the user had chosen miles.
    const custom: UnitSet = { ...presetUnitsFor('metric', 'us'), distance: 'mi' }
    expect(radiusToMeters(custom, 25)).toBe(40234)
  })

  it('returns null for a radius that is not a number', () => {
    expect(radiusToMeters(presetUnitsFor('metric', 'us'), Number.NaN)).toBeNull()
  })
})
