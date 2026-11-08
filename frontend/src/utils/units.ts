/**
 * Unit conversion utilities for imperial/metric conversion.
 *
 * Canonical: SI metric (km, L, kg, m, L/100km, °C, kPa, Nm)
 *
 * - All database values are stored in SI metric units (canonical).
 * - Conversion happens at render time for imperial-preferring users.
 * - UnitFormatter.formatX methods accept a METRIC value and convert to imperial for display.
 * - Form submissions convert user input back to canonical metric through the
 *   unit field protocol in `utils/unitFormat.ts` (prices through
 *   `utils/decimalSafe.ts`) before sending it to the API.
 *
 * ★ THERE ARE NO RAW CONVERTERS LEFT HERE. `UNIT_ADAPTERS` in
 * `utils/unitAdapters.ts` converts every quantity off the reader's own token.
 * This class keeps the factor table that adapter table is built from, plus
 * the volume token maps and `litersToVolumeUnit`.
 */

// TYPE-ONLY, and it has to stay that way. `utils/unitAdapters.ts` imports
// `UnitConverter` and builds its adapter table at module scope, so a runtime
// import back from here would form a cycle whose evaluation order decides
// whether that table reads `UnitConverter` before the class binding leaves its
// temporal dead zone. `import type` is erased, so no cycle exists at runtime.
import type { UnitSet } from '@/types/units';
import { cachedCurrencyFormat } from './numberFormatCache';

export type UnitSystem = 'imperial' | 'metric';
export type GallonStandard = 'us' | 'uk';

/**
 * ★ THE CONVERTER-GALLON SUBSCRIPTION IS GONE, AND SO IS WHAT IT SERVED.
 *
 * A `converterGallonListeners` set, `subscribeToConverterGallon`,
 * `getConverterGallon`, `getConverterGallonServerSnapshot`,
 * `hooks/useResolvedGallonSync.ts` and one `useSyncExternalStore` in
 * `useUnitPreference` used to sit here. They existed so a mounted component
 * repainted when the mutable gallon factors moved: every consumption and
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
 * that made a `gal_uk` user store 10 gal as 37.85 L. Phase 4 task 5 deleted its
 * last writer, so it sat frozen on the US gallon with six readers nobody
 * called. The statics, `setGallonStandard` and those six readers are gone now,
 * so there's no process-wide gallon left for anything to read: every gallon
 * comes off the reader's resolved set.
 */
type Numeric = number | null | undefined;

/**
 * The imperial/metric factor table and the resolved-set volume helpers.
 */
export class UnitConverter {
  // Conversion factors (imperial to metric).
  //
  // The `readonly` factors are PUBLIC so `utils/unitAdapters.ts` can build its
  // per-token table from them instead of declaring a second copy, exactly as
  // `backend/app/utils/unit_adapters.py` imports them from the backend's
  // `UnitConverter`. A duplicated factor table is the defect this workstream
  // keeps finding (`telemetryUnits.ts` has four of them); one more would be a
  // fifth.
  //
  // ★ THE ONLY PLACE IN THIS FILE THE RAW-CONSTANT RULE IS OFF, and it is these
  // lines rather than the whole module (plan 3b, task 2). Until now
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
  // Mirrors backend/app/utils/units.py: base factors are the legal
  // definitions, the rest are derived from them in the same order, and
  // __tests__/unitFactorCrossLayer.test.ts fails when the layers disagree.
  /* eslint-disable no-restricted-syntax -- this IS the factor table */
  static readonly MILES_TO_KM = 1.609344;
  static readonly FEET_TO_METERS = 0.3048;
  static readonly INCH_TO_METERS = 0.0254;
  static readonly US_GALLONS_TO_LITERS = 3.785411784;
  static readonly UK_GALLONS_TO_LITERS = 4.54609;
  static readonly LBS_TO_KG = 0.45359237;
  static readonly STANDARD_GRAVITY = 9.80665;
  static readonly LBF_TO_N = UnitConverter.LBS_TO_KG * UnitConverter.STANDARD_GRAVITY;
  static readonly PSI_TO_KPA =
    UnitConverter.LBF_TO_N / (UnitConverter.INCH_TO_METERS * UnitConverter.INCH_TO_METERS) / 1000;
  static readonly LBFT_TO_NM = UnitConverter.LBF_TO_N * UnitConverter.FEET_TO_METERS;
  static readonly US_MPG_TO_L100KM = (100 * UnitConverter.US_GALLONS_TO_LITERS) / UnitConverter.MILES_TO_KM;
  static readonly UK_MPG_TO_L100KM = (100 * UnitConverter.UK_GALLONS_TO_LITERS) / UnitConverter.MILES_TO_KM;
  /* eslint-enable no-restricted-syntax */

  // ── Resolved-set dispatch ────────────────────────────────────────────────
  //
  // Phase 1 gave every account a `resolved_units` set, so a user resolving
  // `gal_uk` on a US-default instance must get the imperial gallon regardless
  // of what the instance holds. The maps below are how a resolved token
  // becomes a factor.
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

  /**
   * The label each volume token prints. The adapter table builds its volume
   * labels from this, so `getVolumeUnit` and the adapters can't disagree. It
   * lives here because the import cycle above won't let this file read them.
   */
  static readonly VOLUME_UNIT_LABELS: Readonly<Record<UnitSet['volume'], string>> = {
    L: 'L',
    gal_us: 'gal',
    gal_uk: 'gal (UK)',
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
   * Round result to specified decimal places.
   */
  private static roundResult(value: number | null, decimals: number = 2): number | null {
    if (value === null || value === undefined) {
      return null;
    }
    return parseFloat(value.toFixed(decimals));
  }

  /**
   * Convert canonical litres into the volume unit a resolved set names.
   *
   * It reads the flavour off the resolved set, which is why it's right for a
   * `gal_uk` user on a US-default instance. A litre set returns the value
   * untouched rather than passing it through `roundResult`: this feeds form
   * fields, and re-rounding a stored value a metric user never edited would
   * rewrite it on save.
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
   * instance.
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
        // The counterpart names its gallon too, so a UK secondary reads 'gal (UK)'.
        const gallonLabel = UnitConverter.VOLUME_UNIT_LABELS[`gal_${units.secondary_gallon}` as const];
        return `${primary} (${gallons.toFixed(2)} ${gallonLabel})`;
      }
      return primary;
    } else {
      const gallons = UnitConverter.litersToVolumeUnit(litersNum, units);
      const primary = `${gallons?.toFixed(2)} ${UnitConverter.VOLUME_UNIT_LABELS[units.volume]}`;
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
    // Same table the adapters read, so a UK gallon says 'gal (UK)' here too.
    return UnitConverter.VOLUME_UNIT_LABELS[units.volume];
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
    // No token branch any more: litres come back untouched and the label comes
    // off the shared table, so the UK gallon reads 'gal (UK)'.
    const value = UnitConverter.litersToVolumeUnit(liters, units) ?? 0;
    return `${value.toFixed(1)} ${UnitConverter.VOLUME_UNIT_LABELS[units.volume]}`;
  }

  /**
   * Format cost per volume for summary cards.
   * Input: cost per liter (canonical metric $/L). Output: "$0.91" or "$3.45".
   */
  static formatCostPerVolume(
    costPerLiter: number,
    units: UnitSet,
    currencyCode: string,
    locale: string = 'en-US'
  ): string {
    // Defect L1's second half: this line multiplied by a hardcoded 3.78541, so
    // a UK user's card read about 20 percent low while the volume column beside
    // it converted through the dynamic factor. $/L x litres-per-unit = $/unit,
    // and a litre set's factor is 1, so the metric pass-through is the same
    // expression rather than a branch.
    const value = costPerLiter * UnitConverter.LITERS_PER_VOLUME_UNIT[units.volume];
    // The VOLUME unit is deliberately absent from the cache key: it is
    // multiplied into `value` above and the formatter never sees it.
    return cachedCurrencyFormat(locale, currencyCode, 2).format(value);
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
