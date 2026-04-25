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
 * - Distance: kilometers ↔ miles
 * - Fuel Economy: L/100km ↔ MPG
 * - Dimensions: meters ↔ feet
 * - Temperature: °C ↔ °F
 * - Pressure: kPa ↔ PSI (bar = kPa/100)
 * - Weight: kilograms ↔ pounds
 * - Torque: Nm ↔ lb-ft
 * - Electric: kWh, kW, voltage (no conversion needed, universal)
 */

export type UnitSystem = 'imperial' | 'metric';

type Numeric = number | null | undefined;

/**
 * Unit conversion between imperial and metric systems.
 *
 * These bidirectional helpers keep their imperial-named signatures
 * (gallonsToLiters, milesToKm, etc.) — they're utility functions used
 * in both directions, not tied to canonical storage.
 */
export class UnitConverter {
  // Conversion factors (imperial to metric)
  private static readonly GALLONS_TO_LITERS = 3.78541;
  private static readonly MILES_TO_KM = 1.60934;
  private static readonly FEET_TO_METERS = 0.3048;
  private static readonly PSI_TO_BAR = 0.0689476;
  private static readonly PSI_TO_KPA = 6.89476;
  private static readonly LBS_TO_KG = 0.453592;
  private static readonly LBFT_TO_NM = 1.35582;

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
   * Convert gallons to liters.
   */
  static gallonsToLiters(gallons: Numeric): number | null {
    if (gallons === null || gallons === undefined) {
      return null;
    }
    return this.roundResult(gallons * this.GALLONS_TO_LITERS);
  }

  /**
   * Convert liters to gallons.
   */
  static litersToGallons(liters: Numeric): number | null {
    if (liters === null || liters === undefined) {
      return null;
    }
    return this.roundResult(liters / this.GALLONS_TO_LITERS);
  }

  // ========== DISTANCE CONVERSIONS ==========

  /**
   * Convert miles to kilometers.
   */
  static milesToKm(miles: Numeric): number | null {
    if (miles === null || miles === undefined) {
      return null;
    }
    return this.roundResult(miles * this.MILES_TO_KM);
  }

  /**
   * Convert kilometers to miles.
   */
  static kmToMiles(km: Numeric): number | null {
    if (km === null || km === undefined) {
      return null;
    }
    return this.roundResult(km / this.MILES_TO_KM);
  }

  // ========== FUEL ECONOMY CONVERSIONS ==========

  /**
   * Convert MPG to L/100km.
   *
   * Formula: L/100km = 235.214 / MPG
   * (Uses exact conversion factor for gallon and mile)
   */
  static mpgToL100km(mpg: Numeric): number | null {
    if (mpg === null || mpg === undefined || mpg === 0) {
      return null;
    }
    const conversionFactor = 235.214;
    return this.roundResult(conversionFactor / mpg, 1);
  }

  /**
   * Convert L/100km to MPG.
   *
   * Formula: MPG = 235.214 / (L/100km)
   */
  static l100kmToMpg(l100km: Numeric): number | null {
    if (l100km === null || l100km === undefined || l100km === 0) {
      return null;
    }
    const conversionFactor = 235.214;
    return this.roundResult(conversionFactor / l100km, 1);
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

  /**
   * Convert Fahrenheit to Celsius.
   *
   * Formula: C = (F - 32) × 5/9
   */
  static fahrenheitToCelsius(fahrenheit: Numeric): number | null {
    if (fahrenheit === null || fahrenheit === undefined) {
      return null;
    }
    const celsius = (fahrenheit - 32) * 5 / 9;
    return this.roundResult(celsius, 1);
  }

  /**
   * Convert Celsius to Fahrenheit.
   *
   * Formula: F = C × 9/5 + 32
   */
  static celsiusToFahrenheit(celsius: Numeric): number | null {
    if (celsius === null || celsius === undefined) {
      return null;
    }
    const fahrenheit = celsius * 9 / 5 + 32;
    return this.roundResult(fahrenheit, 1);
  }

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
        result = num * UnitConverter.GALLONS_TO_LITERS;
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
        result = 235.214 / num;
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
 */
export class UnitFormatter {
  /**
   * Format volume with appropriate unit label.
   *
   * @param liters - Value in liters (canonical metric)
   * @param system - Target unit system
   * @param showBoth - Show both units (e.g., "94.6 L (25 gal)")
   */
  static formatVolume(liters: Numeric, system: UnitSystem, showBoth: boolean = false): string {
    if (liters === null || liters === undefined) {
      return 'N/A';
    }

    const litersNum = typeof liters === 'string' ? parseFloat(liters) : liters;
    if (isNaN(litersNum)) return 'N/A';

    if (system === 'metric') {
      const primary = `${litersNum.toFixed(2)} L`;
      if (showBoth) {
        const gallons = UnitConverter.litersToGallons(litersNum);
        return `${primary} (${gallons?.toFixed(2)} gal)`;
      }
      return primary;
    } else {
      const gallons = UnitConverter.litersToGallons(litersNum);
      const primary = `${gallons?.toFixed(2)} gal`;
      if (showBoth) {
        return `${primary} (${litersNum.toFixed(2)} L)`;
      }
      return primary;
    }
  }

  /**
   * Format distance with appropriate unit label.
   *
   * @param km - Value in kilometers (canonical metric)
   * @param system - Target unit system
   * @param showBoth - Show both units
   */
  static formatDistance(km: Numeric, system: UnitSystem, showBoth: boolean = false): string {
    if (km === null || km === undefined) {
      return 'N/A';
    }

    const kmNum = typeof km === 'string' ? parseFloat(km) : km;
    if (isNaN(kmNum)) return 'N/A';

    if (system === 'metric') {
      const primary = `${Math.round(kmNum).toLocaleString()} km`;
      if (showBoth) {
        const miles = UnitConverter.kmToMiles(kmNum);
        return `${primary} (${miles?.toLocaleString()} mi)`;
      }
      return primary;
    } else {
      const miles = UnitConverter.kmToMiles(kmNum);
      const primary = `${miles?.toLocaleString()} mi`;
      if (showBoth) {
        return `${primary} (${Math.round(kmNum).toLocaleString()} km)`;
      }
      return primary;
    }
  }

  /**
   * Format fuel economy with appropriate unit label.
   *
   * @param lPer100km - Value in L/100km (canonical metric)
   * @param system - Target unit system
   * @param showBoth - Show both units
   */
  static formatFuelEconomy(lPer100km: Numeric, system: UnitSystem, showBoth: boolean = false): string {
    if (lPer100km === null || lPer100km === undefined) {
      return 'N/A';
    }

    const lNum = typeof lPer100km === 'string' ? parseFloat(lPer100km) : lPer100km;
    if (isNaN(lNum) || lNum === 0) return 'N/A';

    if (system === 'metric') {
      const primary = `${lNum.toFixed(1)} L/100km`;
      if (showBoth) {
        const mpg = UnitConverter.l100kmToMpg(lNum);
        return `${primary} (${mpg?.toFixed(1)} MPG)`;
      }
      return primary;
    } else {
      const mpg = UnitConverter.l100kmToMpg(lNum);
      const primary = `${mpg?.toFixed(1)} MPG`;
      if (showBoth) {
        return `${primary} (${lNum.toFixed(1)} L/100km)`;
      }
      return primary;
    }
  }

  /**
   * Format temperature with appropriate unit label.
   *
   * @param celsius - Value in Celsius (canonical metric)
   * @param system - Target unit system
   * @param showBoth - Show both units
   */
  static formatTemperature(celsius: Numeric, system: UnitSystem, showBoth: boolean = false): string {
    if (celsius === null || celsius === undefined) {
      return 'N/A';
    }

    const cNum = typeof celsius === 'string' ? parseFloat(celsius) : celsius;
    if (isNaN(cNum)) return 'N/A';

    if (system === 'metric') {
      const primary = `${cNum.toFixed(1)}°C`;
      if (showBoth) {
        const fahrenheit = UnitConverter.celsiusToFahrenheit(cNum);
        return `${primary} (${fahrenheit?.toFixed(1)}°F)`;
      }
      return primary;
    } else {
      const fahrenheit = UnitConverter.celsiusToFahrenheit(cNum);
      const primary = `${fahrenheit?.toFixed(1)}°F`;
      if (showBoth) {
        return `${primary} (${cNum.toFixed(1)}°C)`;
      }
      return primary;
    }
  }

  /**
   * Format pressure with appropriate unit label.
   *
   * @param kPa - Value in kilopascals (canonical metric). Display in metric uses bar = kPa/100.
   * @param system - Target unit system
   * @param showBoth - Show both units
   */
  static formatPressure(kPa: Numeric, system: UnitSystem, showBoth: boolean = false): string {
    if (kPa === null || kPa === undefined) {
      return 'N/A';
    }

    const kPaNum = typeof kPa === 'string' ? parseFloat(kPa) : kPa;
    if (isNaN(kPaNum)) return 'N/A';

    const bar = kPaNum / 100;

    if (system === 'metric') {
      const primary = `${bar.toFixed(2)} bar`;
      if (showBoth) {
        const psi = UnitConverter.kPaToPsi(kPaNum);
        return `${primary} (${psi?.toFixed(1)} PSI)`;
      }
      return primary;
    } else {
      const psi = UnitConverter.kPaToPsi(kPaNum);
      const primary = `${psi?.toFixed(1)} PSI`;
      if (showBoth) {
        return `${primary} (${bar.toFixed(2)} bar)`;
      }
      return primary;
    }
  }

  /**
   * Format weight with appropriate unit label.
   *
   * @param kg - Value in kilograms (canonical metric)
   * @param system - Target unit system
   * @param showBoth - Show both units
   */
  static formatWeight(kg: Numeric, system: UnitSystem, showBoth: boolean = false): string {
    if (kg === null || kg === undefined) {
      return 'N/A';
    }

    const kgNum = typeof kg === 'string' ? parseFloat(kg) : kg;
    if (isNaN(kgNum)) return 'N/A';

    if (system === 'metric') {
      const primary = `${kgNum.toLocaleString()} kg`;
      if (showBoth) {
        const lbs = UnitConverter.kgToLbs(kgNum);
        return `${primary} (${lbs?.toLocaleString()} lbs)`;
      }
      return primary;
    } else {
      const lbs = UnitConverter.kgToLbs(kgNum);
      const primary = `${lbs?.toLocaleString()} lbs`;
      if (showBoth) {
        return `${primary} (${kgNum.toLocaleString()} kg)`;
      }
      return primary;
    }
  }

  /**
   * Format torque with appropriate unit label.
   *
   * @param nm - Value in Newton-meters (canonical metric)
   * @param system - Target unit system
   * @param showBoth - Show both units
   */
  static formatTorque(nm: Numeric, system: UnitSystem, showBoth: boolean = false): string {
    if (nm === null || nm === undefined) {
      return 'N/A';
    }

    const nmNum = typeof nm === 'string' ? parseFloat(nm) : nm;
    if (isNaN(nmNum)) return 'N/A';

    if (system === 'metric') {
      const primary = `${nmNum.toFixed(1)} Nm`;
      if (showBoth) {
        const lbft = UnitConverter.nmToLbft(nmNum);
        return `${primary} (${lbft?.toFixed(1)} lb-ft)`;
      }
      return primary;
    } else {
      const lbft = UnitConverter.nmToLbft(nmNum);
      const primary = `${lbft?.toFixed(1)} lb-ft`;
      if (showBoth) {
        return `${primary} (${nmNum.toFixed(1)} Nm)`;
      }
      return primary;
    }
  }

  /**
   * Get volume unit label for input placeholders.
   */
  static getVolumeUnit(system: UnitSystem): string {
    return system === 'imperial' ? 'gal' : 'L';
  }

  /**
   * Get distance unit label for input placeholders.
   */
  static getDistanceUnit(system: UnitSystem): string {
    return system === 'imperial' ? 'mi' : 'km';
  }

  /**
   * Get fuel economy unit label for input placeholders.
   */
  static getFuelEconomyUnit(system: UnitSystem): string {
    return system === 'imperial' ? 'MPG' : 'L/100km';
  }

  /**
   * Get temperature unit label for input placeholders.
   */
  static getTemperatureUnit(system: UnitSystem): string {
    return system === 'imperial' ? '°F' : '°C';
  }

  /**
   * Get pressure unit label for input placeholders.
   */
  static getPressureUnit(system: UnitSystem): string {
    return system === 'imperial' ? 'PSI' : 'bar';
  }

  /**
   * Get weight unit label for input placeholders.
   */
  static getWeightUnit(system: UnitSystem): string {
    return system === 'imperial' ? 'lbs' : 'kg';
  }

  /**
   * Get torque unit label for input placeholders.
   */
  static getTorqueUnit(system: UnitSystem): string {
    return system === 'imperial' ? 'lb-ft' : 'Nm';
  }

  // ========== SUMMARY CARD HELPERS ==========
  // All accept metric-base values and convert at render time.

  /**
   * Format a volume total for summary cards.
   * Input: liters (canonical metric). Output: "47.3 L total" or "12.5 gal total".
   */
  static formatVolumeTotal(liters: number, system: UnitSystem): string {
    if (system === 'imperial') {
      const gallons = UnitConverter.litersToGallons(liters);
      return `${(gallons ?? 0).toFixed(1)} gal total`;
    }
    return `${liters.toFixed(1)} L total`;
  }

  /**
   * Format cost per volume for summary cards.
   * Input: cost per liter (canonical metric $/L). Output: "$0.91" or "$3.45".
   */
  static formatCostPerVolume(
    costPerLiter: number,
    system: UnitSystem,
    currencyCode: string = 'USD',
    locale: string = 'en-US'
  ): string {
    const value = system === 'imperial'
      ? costPerLiter * 3.78541  // $/L → $/gal
      : costPerLiter;
    return new Intl.NumberFormat(locale, {
      style: 'currency',
      currency: currencyCode,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  }

  /**
   * Get the label for cost-per-volume cards.
   * Returns "Avg Cost/L" or "Avg Cost/gal".
   */
  static getCostPerVolumeLabel(system: UnitSystem): string {
    return `Avg Cost/${UnitFormatter.getVolumeUnit(system)}`;
  }

  /**
   * Format cost per distance for summary cards.
   * Input: cost per kilometer (canonical metric $/km).
   * Metric uses $/100 km (standard convention), imperial uses $/1,000 mi.
   */
  static formatCostPerDistance(
    costPerKm: number,
    system: UnitSystem,
    currencyCode: string = 'USD',
    locale: string = 'en-US'
  ): string {
    const value = system === 'imperial'
      ? costPerKm * 1.60934 * 1000  // $/km → $/1000 mi
      : costPerKm * 100;             // $/km → $/100 km
    return new Intl.NumberFormat(locale, {
      style: 'currency',
      currency: currencyCode,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  }

  /**
   * Get the label for cost-per-distance cards.
   * Returns "Cost/1k Miles" or "Cost/100 km".
   */
  static getCostPerDistanceLabel(system: UnitSystem): string {
    return system === 'imperial' ? 'Cost/1k Miles' : 'Cost/100 km';
  }

  /**
   * Format volume consumption per distance for summary cards.
   * Input: liters per 1,000 km (canonical metric L/1000km).
   * Output: "3.4" (L/1,000 km) or "2.1" (gal/1,000 mi).
   */
  static formatVolumePerDistance(litersPer1kKm: number, system: UnitSystem): string {
    if (system === 'imperial') {
      // L/1000km → gal/1000mi: (L / 3.78541) * 1.60934
      const galPer1kMi = (litersPer1kKm / 3.78541) * 1.60934;
      return `${galPer1kMi.toFixed(1)}`;
    }
    return `${litersPer1kKm.toFixed(1)}`;
  }

  /**
   * Get the sub-label for volume-per-distance cards.
   * Returns "gal/1,000 mi" or "L/1,000 km".
   */
  static getVolumePerDistanceLabel(system: UnitSystem): string {
    return system === 'imperial' ? 'gal/1,000 mi' : 'L/1,000 km';
  }
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
