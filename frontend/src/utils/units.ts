/**
 * Unit conversion utilities for imperial/metric conversion.
 *
 * Canonical: SI metric (km, L, kg, m, L/100km, °C, bar, Nm)
 *
 * - All database values are stored in SI metric units (canonical).
 * - Conversion happens at render time for imperial-preferring users.
 * - UnitFormatter.formatX methods accept a METRIC value and convert to imperial for display.
 * - Form submissions should use UnitConverter.toCanonicalMetricString() to convert
 *   user input back to canonical metric before sending to the API.
 *
 * Supported conversions:
 * - Volume: liters ↔ gallons
 * - Fuel Economy: L/100km ↔ MPG
 * - Dimensions: meters ↔ feet
 * - Pressure: kPa ↔ PSI (bar = kPa/100)
 * - Weight: kilograms ↔ pounds
 * - Torque: Nm ↔ lb-ft
 * - Electric: kWh, kW, voltage (no conversion needed, universal)
 *
 * ★ DISTANCE IS NOT ON THAT LIST ANY MORE, and its absence is a statement.
 * `UNIT_ADAPTERS` in `utils/unitAdapters.ts` is where km ↔ mi happens now, off
 * the resolved `units.distance` token; plan 3b task 6 migrated the last call
 * site and deleted `formatDistance`, `getDistanceUnit`, `kmToMiles` and
 * `milesToKm`. The factor `MILES_TO_KM` stays here because that table is built
 * from it.
 */

// TYPE-ONLY, and it has to stay that way. `utils/unitAdapters.ts` imports
// `UnitConverter` and builds its adapter table at module scope, so a runtime
// import back from here would form a cycle whose evaluation order decides
// whether that table reads `UnitConverter` before the class binding leaves its
// temporal dead zone. `import type` is erased, so no cycle exists at runtime.
import type { UnitSet } from '@/types/units';

export type UnitSystem = 'imperial' | 'metric';
export type GallonStandard = 'us' | 'uk';

/**
 * ★ THE CONVERTER-GALLON SUBSCRIPTION IS GONE, AND SO IS WHAT IT SERVED.
 *
 * A `converterGallonListeners` set, `subscribeToConverterGallon`,
 * `getConverterGallon`, `getConverterGallonServerSnapshot`,
 * `hooks/useResolvedGallonSync.ts` and one `useSyncExternalStore` in
 * `useUnitPreference` used to sit here. They existed so a mounted component
 * repainted when the mutable gallon factors below moved: every consumption and
 * fuel-rate reader took the binary `system` and read those statics, so a
 * changed flavour changed the next conversion and repainted nothing.
 *
 * Plan 3b task 6b moved all thirty-one of those readers onto the resolved set,
 * and the adapter table is built from the `readonly` constants, so no screen
 * can observe the mutable statics at all. The sync ran on every load, wrote a
 * value nothing read, and notified a subscriber that discarded it: a closed
 * loop. Task 8 deleted it, since a clean-room gate that cannot see a dead unit
 * loop is claiming more than it checks, and neither units gate can see a
 * subscription.
 *
 * ★ That mutable gallon IS defect L1's mechanism, the instance-driven factor
 * that made a `gal_uk` user store 10 gal as 37.85 L. What survives here is the
 * INSTANCE setting's write path and the six methods that read the factors, all
 * six of which have zero production callers.
 * `utils/__tests__/unitsBinaryApiSurface.test.ts` enumerates them and holds the
 * loop deleted.
 *
 * ★ AND SINCE PHASE 4 TASK 5 THE WRITE PATH HAS NO CALLER EITHER.
 * `utils/gallonStandardStore.ts` was the one production module that called
 * `setGallonStandard`, and task 5 deleted it with the `imperial_gallon_standard`
 * control it served; the instance default is the whole `default_unit_prefs` set
 * now. So the two mutable fields below are frozen at their US initialisers for
 * the life of the process, and the only writer left is a test arranging a
 * flavour. That enumeration is `[]` now, and taking the statics and the six
 * methods out with it is the follow-up, held open because doing it rewrites nine
 * test files whose flavour lines are deliberate defect-L1 guards.
 */
type Numeric = number | null | undefined;

/**
 * Unit conversion between imperial and metric systems.
 *
 * These bidirectional helpers keep their imperial-named signatures
 * (gallonsToLiters, litersToGallons, etc.) — they're utility functions used
 * in both directions, not tied to canonical storage. The distance pair that
 * used to be named here is gone; see the DISTANCE CONVERSIONS marker below.
 */
export class UnitConverter {
  // Conversion factors (imperial to metric).
  //
  // The `readonly` factors are PUBLIC so `utils/unitAdapters.ts` can build its
  // per-token table from them instead of declaring a second copy, exactly as
  // `backend/app/utils/unit_adapters.py` imports them from the backend's
  // `UnitConverter`. A duplicated factor table is the defect this workstream
  // keeps finding (`telemetryUnits.ts` has four of them); one more would be a
  // fifth. The two MUTABLE fields below stay private on purpose: they are
  // process-global state driven by the instance gallon setting, and an adapter
  // resolved from a user's own `UnitSet` must never read them.
  //
  // ★ THE ONLY PLACE IN THIS FILE THE RAW-CONSTANT RULE IS OFF, and it is these
  // twelve lines rather than the whole module (plan 3b, task 2). Until now
  // `eslint.config.js` silenced `no-restricted-syntax` for `utils/units.ts`
  // outright, in a block meant for the i18n guards, and the entry in
  // `UNITS_CONSTANT_EXEMPT` beside `unitAdapters.ts` and `supplyUnits.ts` was
  // doing nothing: the later block won by ordering. Removing that whole-file
  // silence turns up twelve findings, and ten of them are right here. This is
  // the table the rule's own message tells every other file to move its
  // constants INTO, so it is exempt for a reason nothing else in this module
  // can borrow. The eleventh (a `c * 9 / 5 + 32` idiom) and the twelfth (a
  // fourteenth copy of `1.60934`) were not in this table at all, and both are
  // now gone rather than exempt.
  /* eslint-disable no-restricted-syntax -- this IS the factor table */
  static readonly US_GALLONS_TO_LITERS = 3.78541;
  static readonly UK_GALLONS_TO_LITERS = 4.54609;
  private static gallonsToLitersFactor = UnitConverter.US_GALLONS_TO_LITERS;
  static readonly MILES_TO_KM = 1.60934;
  static readonly FEET_TO_METERS = 0.3048;
  private static readonly PSI_TO_BAR = 0.0689476;
  static readonly PSI_TO_KPA = 6.89476;
  static readonly LBS_TO_KG = 0.453592;
  static readonly LBFT_TO_NM = 1.35582;
  static readonly US_MPG_TO_L100KM = 235.214;
  static readonly UK_MPG_TO_L100KM = 282.481;
  private static mpgToL100kmFactor = UnitConverter.US_MPG_TO_L100KM;
  /* eslint-enable no-restricted-syntax */

  // ── Resolved-set dispatch ────────────────────────────────────────────────
  //
  // The two mutable fields above follow the INSTANCE gallon setting, which is
  // not the same thing as the client's own units: phase 1 gave every account a
  // `resolved_units` set, so a user resolving `gal_uk` on a US-default instance
  // must get the imperial gallon regardless of what the instance holds. The
  // maps below are how a resolved token becomes a factor.
  //
  // They ARE a second dispatch of a decision `utils/unitAdapters.ts` also
  // makes, and duplicated unit knowledge is exactly what this workstream keeps
  // finding (defect L1 was a hardcoded `3.78541` under a comment claiming it
  // mirrored this class). Two things keep them honest: the `Record<...>` types
  // fail to compile if the API schema adds a token, and
  // `utils/__tests__/unitFactorParity.test.ts` asserts every entry equals what
  // `UNIT_ADAPTERS` converts. The duplication exists only because the import
  // cycle above forbids reading the adapter table directly; collapsing it is a
  // 3b job, once `unitAdapters` no longer depends on this module.

  /** Litres in one unit of each volume token a resolved set can name. */
  static readonly LITERS_PER_VOLUME_UNIT: Readonly<Record<UnitSet['volume'], number>> = {
    L: 1,
    gal_us: UnitConverter.US_GALLONS_TO_LITERS,
    gal_uk: UnitConverter.UK_GALLONS_TO_LITERS,
  };

  /** Kilograms in one unit of each mass token a resolved set can name. */
  static readonly KG_PER_MASS_UNIT: Readonly<Record<UnitSet['mass'], number>> = {
    kg: 1,
    lb: UnitConverter.LBS_TO_KG,
  };

  /**
   * Litres in the gallon a LITRE primary pairs with under show-both (spec D4b).
   *
   * `L` cannot state its own gallon flavour, so the set carries it separately.
   */
  static readonly LITERS_PER_SECONDARY_GALLON: Readonly<
    Record<UnitSet['secondary_gallon'], number>
  > = {
    us: UnitConverter.US_GALLONS_TO_LITERS,
    uk: UnitConverter.UK_GALLONS_TO_LITERS,
  };

  /**
   * Select US or UK imperial gallon (also updates MPG conversion).
   *
   * It used to notify a `subscribeToConverterGallon` listener set so a mounted
   * component could repaint. Nothing renders off these statics since plan 3b
   * task 6b, so there is nothing to repaint and task 8 deleted the whole loop;
   * see the note above `type Numeric`. Phase 4 task 5 then deleted
   * `gallonStandardStore`, the last production caller, so no production module
   * calls this or the six methods below.
   */
  static setGallonStandard(standard: GallonStandard): void {
    if (standard === 'uk') {
      this.gallonsToLitersFactor = this.UK_GALLONS_TO_LITERS;
      this.mpgToL100kmFactor = this.UK_MPG_TO_L100KM;
    } else {
      this.gallonsToLitersFactor = this.US_GALLONS_TO_LITERS;
      this.mpgToL100kmFactor = this.US_MPG_TO_L100KM;
    }
  }

  static getGallonStandard(): GallonStandard {
    return this.gallonsToLitersFactor === this.UK_GALLONS_TO_LITERS ? 'uk' : 'us';
  }

  /**
   * Round result to specified decimal places.
   */
  private static roundResult(value: number | null, decimals: number = 2): number | null {
    if (value === null || value === undefined) {
      return null;
    }
    return parseFloat(value.toFixed(decimals));
  }

  // ========== VOLUME CONVERSIONS ==========

  /**
   * Convert gallons to liters (uses active US/UK gallon standard).
   */
  static gallonsToLiters(gallons: Numeric): number | null {
    if (gallons === null || gallons === undefined) {
      return null;
    }
    return this.roundResult(gallons * this.gallonsToLitersFactor);
  }

  /**
   * Convert liters to gallons (uses active US/UK gallon standard).
   */
  static litersToGallons(liters: Numeric): number | null {
    if (liters === null || liters === undefined) {
      return null;
    }
    return this.roundResult(liters / this.gallonsToLitersFactor);
  }

  /**
   * Convert canonical litres into the volume unit a resolved set names.
   *
   * The resolved-set counterpart of `litersToGallons`, and the reason the
   * flavour is right for a `gal_uk` user on a US-default instance. A litre set
   * returns the value untouched rather than passing it through `roundResult`:
   * this feeds form fields, and re-rounding a stored value a metric user never
   * edited would rewrite it on save.
   *
   * @param liters Canonical litres.
   * @param units The client's resolved unit set.
   * @returns The value in `units.volume`, or null when there is none.
   */
  static litersToVolumeUnit(liters: Numeric, units: UnitSet): number | null {
    if (liters === null || liters === undefined) {
      return null;
    }
    // units-exempt(token-branch): volume dispatch inside a volume converter. The token read is the quantity being converted, not a proxy for a different one, which is the distinction the token-branch leg exists to draw and cannot draw for itself. Not deferred work.
    if (units.volume === 'L') {
      return liters;
    }
    return this.roundResult(liters / UnitConverter.LITERS_PER_VOLUME_UNIT[units.volume]);
  }

  // ========== DISTANCE CONVERSIONS ==========
  //
  // ★ There are none left here, and the gap is deliberate rather than an
  // oversight. `milesToKm` and `kmToMiles` were the raw pair a call site
  // reached for when it wanted to make the imperial/metric decision itself,
  // and plan 3b task 6 migrated the last two such sites (Calendar's
  // remaining-distance badge and the DEF card's estimate) onto the resolved
  // `units.distance` adapter. Both then had zero callers. Deleting them makes
  // "convert this to miles regardless of what the reader chose" inexpressible,
  // which is the same call R8 made one module over for the three
  // `toCanonical*` helpers. `MILES_TO_KM` stays: `UNIT_ADAPTERS` builds the
  // `mi` and `mph` adapters from it, which is the one place the conversion
  // should happen.

  // ========== FUEL ECONOMY CONVERSIONS ==========

  /**
   * Convert MPG to L/100km (US 235.214 or UK 282.481 per active gallon standard).
   */
  static mpgToL100km(mpg: Numeric): number | null {
    if (mpg === null || mpg === undefined || mpg === 0) {
      return null;
    }
    return this.roundResult(this.mpgToL100kmFactor / mpg, 1);
  }

  /**
   * Convert L/100km to MPG (US 235.214 or UK 282.481 per active gallon standard).
   */
  static l100kmToMpg(l100km: Numeric): number | null {
    if (l100km === null || l100km === undefined || l100km === 0) {
      return null;
    }
    return this.roundResult(this.mpgToL100kmFactor / l100km, 1);
  }

  /**
   * Convert L/100km to MPG.
   *
   * Alias of l100kmToMpg, named for the new metric-canonical
   * convention so callers can read top-down: "L per 100km to MPG".
   */
  static lPer100kmToMpg(value: Numeric): number | null {
    return this.l100kmToMpg(value);
  }

  // ========== DIMENSION CONVERSIONS ==========

  /**
   * Convert feet to meters.
   */
  static feetToMeters(feet: Numeric): number | null {
    if (feet === null || feet === undefined) {
      return null;
    }
    return this.roundResult(feet * this.FEET_TO_METERS);
  }

  /**
   * Convert meters to feet.
   */
  static metersToFeet(meters: Numeric): number | null {
    if (meters === null || meters === undefined) {
      return null;
    }
    return this.roundResult(meters / this.FEET_TO_METERS);
  }

  // ========== TEMPERATURE CONVERSIONS ==========
  //
  // Gone, with `formatTemperature`, the only thing that called either of them.
  // `celsiusToFahrenheit` held the `c * 9 / 5 + 32` idiom the ESLint leg
  // matches STRUCTURALLY (there is no constant in it distinctive enough to
  // list), so it was one of the twelve findings the whole-file exemption was
  // covering. `UNIT_ADAPTERS.f` is the live implementation and always was the
  // one with the offset spelled out; a dead second copy of a conversion is the
  // shape defect L1 took.

  // ========== PRESSURE CONVERSIONS ==========

  /**
   * Convert PSI to bar.
   */
  static psiToBar(psi: Numeric): number | null {
    if (psi === null || psi === undefined) {
      return null;
    }
    return this.roundResult(psi * this.PSI_TO_BAR);
  }

  /**
   * Convert bar to PSI.
   */
  static barToPsi(bar: Numeric): number | null {
    if (bar === null || bar === undefined) {
      return null;
    }
    return this.roundResult(bar / this.PSI_TO_BAR);
  }

  /**
   * Convert PSI to kPa.
   */
  static psiToKPa(psi: Numeric): number | null {
    if (psi === null || psi === undefined) {
      return null;
    }
    return this.roundResult(psi * this.PSI_TO_KPA);
  }

  /**
   * Convert kPa to PSI.
   */
  static kPaToPsi(kPa: Numeric): number | null {
    if (kPa === null || kPa === undefined) {
      return null;
    }
    return this.roundResult(kPa / this.PSI_TO_KPA);
  }

  // ========== WEIGHT CONVERSIONS ==========

  /**
   * Convert pounds to kilograms.
   */
  static lbsToKg(lbs: Numeric): number | null {
    if (lbs === null || lbs === undefined) {
      return null;
    }
    return this.roundResult(lbs * this.LBS_TO_KG);
  }

  /**
   * Convert kilograms to pounds.
   */
  static kgToLbs(kg: Numeric): number | null {
    if (kg === null || kg === undefined) {
      return null;
    }
    return this.roundResult(kg / this.LBS_TO_KG);
  }

  // ========== TORQUE CONVERSIONS ==========

  /**
   * Convert lb-ft to Newton-meters.
   */
  static lbftToNm(lbft: Numeric): number | null {
    if (lbft === null || lbft === undefined) {
      return null;
    }
    return this.roundResult(lbft * this.LBFT_TO_NM);
  }

  /**
   * Convert Newton-meters to lb-ft.
   */
  static nmToLbft(nm: Numeric): number | null {
    if (nm === null || nm === undefined) {
      return null;
    }
    return this.roundResult(nm / this.LBFT_TO_NM);
  }

  // ========== CANONICAL CONVERSION (FORM SUBMIT) ==========

  /**
   * Convert a user-entered value in `fromUnit` to its canonical SI metric
   * representation, returned as a string to preserve precision through the
   * API boundary (avoids parseFloat round-trip loss).
   *
   * Mirrors the backend's `to_canonical_decimal()` helper.
   *
   * Pass-through (returns the input as a string, untouched) when fromUnit
   * is already the canonical unit. For imperial units, performs an exact
   * conversion using string-friendly arithmetic and returns a string with
   * sufficient precision (12 significant digits) to round-trip cleanly.
   *
   * Supported `fromUnit` values:
   *   km, mi, L, gal, kg, lb, m, ft, C, F, kPa, PSI, Nm, lbft, L/100km, MPG
   */
  static toCanonicalMetricString(
    value: number | string | null | undefined,
    fromUnit:
      | 'km'
      | 'mi'
      | 'L'
      | 'gal'
      | 'kg'
      | 'lb'
      | 'm'
      | 'ft'
      | 'C'
      | 'F'
      | 'kPa'
      | 'PSI'
      | 'Nm'
      | 'lbft'
      | 'L/100km'
      | 'MPG'
  ): string | null {
    if (value === null || value === undefined || value === '') {
      return null;
    }

    const trimmed = typeof value === 'string' ? value.trim() : value;
    if (trimmed === '') return null;

    const num = typeof trimmed === 'string' ? parseFloat(trimmed) : trimmed;
    if (isNaN(num)) return null;

    // Canonical pass-through: preserve original string form (no parseFloat loss).
    const canonicalUnits = new Set(['km', 'L', 'kg', 'm', 'C', 'kPa', 'Nm', 'L/100km']);
    if (canonicalUnits.has(fromUnit)) {
      return typeof trimmed === 'string' ? trimmed : String(trimmed);
    }

    // Imperial → metric
    let result: number;
    switch (fromUnit) {
      case 'mi':
        result = num * UnitConverter.MILES_TO_KM;
        break;
      case 'gal':
        result = num * UnitConverter.gallonsToLitersFactor;
        break;
      case 'lb':
        result = num * UnitConverter.LBS_TO_KG;
        break;
      case 'ft':
        result = num * UnitConverter.FEET_TO_METERS;
        break;
      case 'F':
        result = (num - 32) * 5 / 9;
        break;
      case 'PSI':
        result = num * UnitConverter.PSI_TO_KPA;
        break;
      case 'lbft':
        result = num * UnitConverter.LBFT_TO_NM;
        break;
      case 'MPG':
        if (num === 0) return null;
        result = UnitConverter.mpgToL100kmFactor / num;
        break;
      default:
        return null;
    }

    // 12 significant digits is enough to losslessly round-trip the conversion
    // factors used here while still being a clean decimal string. Strip
    // trailing zeros after the decimal point (but keep integer trailing zeros).
    const precise = result.toPrecision(12);
    if (!precise.includes('.')) return precise;
    return precise.replace(/\.?0+$/, '');
  }
}

/**
 * Display formatting with unit labels.
 *
 * All format* methods accept the value in canonical SI metric form.
 * For imperial-preferring users, the metric value is converted at render time.
 *
 * ★ THERE ARE NO `UnitSystem` METHODS LEFT ON THIS CLASS, AND NO
 * `// units-exempt:` PRAGMAS, and the scheme that got it here is written down
 * once, here, because it is what a reader adding a method next needs (plan 3b,
 * ruling R2).
 *
 * Each of the retired methods carried exactly one `system === '...'`
 * comparison, which is why the units gate derived the same names from this
 * class that its comparison leg counted in this file. The comparison was never
 * the defect: the parameter IS the decision, already made by the caller. The
 * defect is that `system` is collapsed from VOLUME (spec D8,
 * `useUnitPreference.ts:98`), so a `{volume:'L', distance:'mi'}` user reached
 * `formatDistance` as `'metric'` and read kilometres. That is a call-site
 * decision, and the gate reported every one of those call sites under its
 * `formatter-binary` leg.
 *
 * So each comparison carried `// units-exempt:` naming who owned its call
 * sites, and the exemption expired when they were migrated rather than when
 * somebody remembered. A reason-bearing pragma silences anything
 * (`EXEMPT_PRAGMA` in `validate-units.ts`), so the exemptions never rested on
 * that prose: `utils/__tests__/unitsBinaryApiSurface.test.ts` derives this
 * surface from the file and fails when a method outlives its last production
 * caller. Seven methods failed it at t=0 and are gone; `getWeightUnit` followed
 * the moment task 3 moved `PropaneRecordForm` onto the mass adapter;
 * `formatDistance` and `getDistanceUnit` followed task 6's migration of their
 * twenty-seven call sites; the fuel-economy and fuel-rate family followed task
 * 6b's thirty-one; and `formatCostPerDistance` / `getCostPerDistanceLabel`
 * followed task 7's five. Each time the test failed first, exactly as designed.
 *
 * ★ THE SET BEING EMPTY IS NOW THE THING THAT NEEDS GUARDING. A derivation that
 * finds nothing looks identical to a derivation that has stopped looking, so
 * `validate-units.ts` no longer refuses on an empty binary-formatter set: it
 * refuses on an empty set of STATIC METHODS, which is the walk's own receipt,
 * exactly as it already did for the conversion leg one module over. A method
 * added below with a `UnitSystem` parameter is picked up by both derivations on
 * the next run, and its call sites become findings; nothing about that rests on
 * anybody reading this paragraph.
 *
 * The resolved-set replacement already exists for all ten quantities:
 * `useUnitFormat()` in a component, `makeUnitFormat(units)` outside one.
 */
export class UnitFormatter {
  /**
   * Format volume with appropriate unit label.
   *
   * Takes the client's resolved `UnitSet` rather than a binary system: the
   * gallon flavour belongs to the user (`resolved_units.volume`), not to the
   * instance-wide setting `UnitConverter`'s mutable factor follows.
   *
   * @param liters - Value in liters (canonical metric)
   * @param units - The client's resolved unit set
   * @param showBoth - Show both units (e.g., "94.6 L (25 gal)")
   */
  static formatVolume(liters: Numeric, units: UnitSet, showBoth: boolean = false): string {
    if (liters === null || liters === undefined) {
      return 'N/A';
    }

    const litersNum = typeof liters === 'string' ? parseFloat(liters) : liters;
    if (isNaN(litersNum)) return 'N/A';

    // units-exempt(token-branch): volume dispatch inside a volume formatter, same rule as `litersToVolumeUnit`. Not deferred work.
    if (units.volume === 'L') {
      const primary = `${litersNum.toFixed(2)} L`;
      if (showBoth) {
        // D4b: a litre primary's counterpart gallon comes from the set, since
        // 'L' cannot state a flavour of its own.
        const gallons = litersNum / UnitConverter.LITERS_PER_SECONDARY_GALLON[units.secondary_gallon];
        return `${primary} (${gallons.toFixed(2)} gal)`;
      }
      return primary;
    } else {
      const gallons = UnitConverter.litersToVolumeUnit(litersNum, units);
      const primary = `${gallons?.toFixed(2)} gal`;
      if (showBoth) {
        return `${primary} (${litersNum.toFixed(2)} L)`;
      }
      return primary;
    }
  }

  // ★ THE FUEL-ECONOMY AND FUEL-RATE FAMILY USED TO BE HERE, and the gap is
  // deliberate rather than an oversight. `formatFuelEconomy`,
  // `getFuelEconomyUnit`, `formatFuelRate` and `getFuelRateUnit` all decided on
  // a binary `UnitSystem`, which is collapsed from VOLUME (spec D8), so a
  // `{volume:'L', consumption:'mpg_us'}` account read L/100km and a
  // `{volume:'gal_us', consumption:'l_100km'}` account read MPG: in both cases
  // the app ignored the very quantity the user had chosen. Plan 3b task 6b
  // migrated the last of their 31 call sites onto `units.consumption` and
  // `units.volume`, `unitsBinaryApiSurface.test.ts` reported all four as dead,
  // and they went.
  //
  // The replacements are `useUnitFormat().consumption` (a `QuantityFormat`,
  // whose `format`/`formatPrimary` split keeps show-both a per-site choice) and
  // `unitFormat.ts`'s `formatFuelRate(units, lPerHr, showBoth)` /
  // `fuelRateLabel(units)`. The rate pair lives there rather than here for the
  // reason `formatVolumePerDistance` gives at length: it composes two adapters,
  // and this module cannot import `adapterFor` without forming a cycle.

  /**
   * Get volume unit label for input placeholders.
   *
   * @param units - The client's resolved unit set
   */
  static getVolumeUnit(units: UnitSet): string {
    // units-exempt(token-branch): a volume LABEL chosen by the volume token. Not deferred work, though the label is D4b-incomplete: both gallons answer 'gal', which `units.manifest.json` records against SettingsSystemTab and phase 4 owns.
    return units.volume === 'L' ? 'L' : 'gal';
  }

  /**
   * Get the mass unit label a resolved set names.
   *
   * It replaced a binary `getWeightUnit(system)`, deleted by plan 3b task 3
   * when `PropaneRecordForm` moved onto the mass adapter and left it with no
   * production caller. That method also answered `'lbs'` where this one, the
   * `lb` adapter and the backend's table all answer `'lb'`. It exists because
   * `priceToDisplay`'s `per_weight` denominator reads `units.mass`: the label
   * beside that field has to name the same unit. `system` cannot, being
   * D8-collapsed from VOLUME, so it answers "kg" for a user who chose pounds.
   *
   * @param units - The client's resolved unit set
   */
  static getMassUnit(units: UnitSet): string {
    // units-exempt(token-branch): a mass LABEL chosen by the mass token, and the docstring above says why reading `units.mass` rather than `system` is the whole point of it. Not deferred work.
    return units.mass === 'kg' ? 'kg' : 'lb';
  }

  // ========== SUMMARY CARD HELPERS ==========
  // All accept metric-base values and convert at render time.

  /**
   * Volume at total-precision (1 decimal), number and unit only.
   *
   * ★ IT IS THE WHOLE OF WHAT IS LEFT, and `formatVolumeTotal` is gone. That
   * method appended the English word "total" and rendered in two summary cards;
   * `getCostPerVolumeLabel` appended the English words "Avg Cost/" and rendered
   * in four. Neither went through `t()`, so a German reader's fuel-stats row
   * read `Kosten/100 km` beside `Avg Cost/gal` and `45,5 L total`: task 7
   * translated the cost-per-distance caption one card to the RIGHT of an
   * untranslated one, which is the same half-migrated pair, on the same row,
   * that the caption's own migration existed to close.
   *
   * Both prose halves are now translated keys at the call site
   * (`avgCostPerVolume`, `volumeTotal`) and this method supplies the half that
   * is a symbol rather than prose, which is the split every other label on this
   * surface uses. The comment this replaces already warned that the trailing
   * word "breaks silently the moment this file is localized"; it did.
   */
  static formatVolumeShort(liters: number, units: UnitSet): string {
    // units-exempt(token-branch): volume dispatch inside a volume formatter, same rule as `formatVolume`. Not deferred work.
    if (units.volume === 'L') {
      return `${liters.toFixed(1)} L`;
    }
    const gallons = UnitConverter.litersToVolumeUnit(liters, units);
    return `${(gallons ?? 0).toFixed(1)} gal`;
  }

  /**
   * Format cost per volume for summary cards.
   * Input: cost per liter (canonical metric $/L). Output: "$0.91" or "$3.45".
   */
  static formatCostPerVolume(
    costPerLiter: number,
    units: UnitSet,
    currencyCode: string = 'USD',
    locale: string = 'en-US'
  ): string {
    // Defect L1's second half: this line multiplied by a hardcoded 3.78541, so
    // a UK user's card read about 20 percent low while the volume column beside
    // it converted through the dynamic factor. $/L x litres-per-unit = $/unit,
    // and a litre set's factor is 1, so the metric pass-through is the same
    // expression rather than a branch.
    const value = costPerLiter * UnitConverter.LITERS_PER_VOLUME_UNIT[units.volume];
    return new Intl.NumberFormat(locale, {
      style: 'currency',
      currency: currencyCode,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  }

  // ★ `formatCostPerDistance` and `getCostPerDistanceLabel` USED TO BE HERE,
  // and they are the LAST pair to leave, which is why this class no longer
  // declares a single method taking a `UnitSystem`. Both decided on that binary
  // system, which spec D8 collapses from VOLUME, so a
  // `{volume:'L', distance:'mi'}` account read "Cost/100 km" under a figure
  // quoted per 100 km, beside an odometer column task 6 had already migrated to
  // miles. The two DISAGREED ON SCREEN in the meantime: before task 6 they were
  // wrong together, which is less visible and no more correct.
  //
  // Plan 3b task 7 moved them to `utils/unitFormat.ts` as
  // `formatCostPerDistance(units, ...)` and `costPerDistanceUnitLabel(units)`,
  // for the same reason the volume-per-distance pair moved in task 6: this
  // module cannot import the adapter table (see the `import type` note at the
  // top), so the distance half would have needed a second dispatch beside
  // `LITERS_PER_VOLUME_UNIT`. The denominators did NOT change: 100 km and
  // 1,000 mi are what shipped, and what the label named in prose. What changed
  // is which of the two an account gets, and that the label is now translated
  // rather than two hardcoded English strings every language received.
  //
  // ★ `formatCostPerVolume` stays, and the split is the rule rather than an
  // accident: it needs the litres-per-unit factor this class already holds and
  // no adapter at all. `getCostPerVolumeLabel` did NOT stay, and for a
  // different reason: it was two English words glued to a symbol, so its prose
  // half is a translated key at the call site and its symbol half is
  // `getVolumeUnit`. Every method left on this class returns a number, a
  // currency string or a bare unit symbol; none returns prose.

  // ★ `formatVolumePerDistance` and `getVolumePerDistanceLabel` USED TO BE HERE,
  // and where they went is the point rather than a filing detail. Both derived
  // BOTH halves of a compound unit from `units.volume`, so a
  // `{volume:'L', distance:'mi'}` account read a per-kilometre rate beside an
  // odometer column reading miles. The first one's comment promised "Distance
  // migrates in 3b, per file, with its neighbours"; plan 3b task 6 kept that
  // promise, and they now live in `utils/unitFormat.ts` where `adapterFor` can
  // supply BOTH halves from the resolved set. They could not stay here: this
  // module cannot import the adapter table (see the `import type` note at the
  // top), so the distance half would have needed a second dispatch beside
  // `LITERS_PER_VOLUME_UNIT`, and a second copy of a unit decision is the
  // defect this workstream keeps unpicking.
}

/**
 * Detect user's preferred unit system from timezone.
 *
 * Smart default: US timezones → imperial, others → metric
 */
export function detectUnitSystemFromTimezone(): UnitSystem {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;

  // US timezones (partial list, can be extended)
  const usTimezones = [
    'America/New_York',
    'America/Chicago',
    'America/Denver',
    'America/Phoenix',
    'America/Los_Angeles',
    'America/Anchorage',
    'America/Adak',
    'Pacific/Honolulu',
    'America/Detroit',
    'America/Indiana/Indianapolis',
    'America/Kentucky/Louisville',
    'America/Boise',
  ];

  // Check if timezone starts with 'America/' (broader US/Americas detection)
  const isAmericas = timezone.startsWith('America/');
  const isUSTimezone = usTimezones.includes(timezone);

  // US timezones default to imperial, all others default to metric
  return (isUSTimezone || isAmericas) ? 'imperial' : 'metric';
}
