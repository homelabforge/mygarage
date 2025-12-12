/**
 * Unit conversion utilities for imperial/metric conversion.
 *
 * Canonical storage format: IMPERIAL
 * - All database values are stored in imperial units
 * - Conversion happens at API boundary (input → imperial, imperial → output)
 * - This ensures data consistency and simplifies queries/aggregations
 *
 * Supported conversions:
 * - Volume: gallons ↔ liters
 * - Distance: miles ↔ kilometers
 * - Fuel Economy: MPG ↔ L/100km
 * - Dimensions: feet ↔ meters
 * - Temperature: °F ↔ °C
 * - Pressure: PSI ↔ bar
 * - Weight: pounds ↔ kilograms
 * - Torque: lb-ft ↔ Nm
 * - Electric: kWh, kW, voltage (no conversion needed, universal)
 */

export type UnitSystem = 'imperial' | 'metric';

type Numeric = number | null | undefined;

/**
 * Unit conversion between imperial and metric systems.
 */
export class UnitConverter {
  // Conversion factors (imperial to metric)
  private static readonly GALLONS_TO_LITERS = 3.78541;
  private static readonly MILES_TO_KM = 1.60934;
  private static readonly FEET_TO_METERS = 0.3048;
  private static readonly PSI_TO_BAR = 0.0689476;
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
}

/**
 * Display formatting with unit labels.
 */
export class UnitFormatter {
  /**
   * Format volume with appropriate unit label.
   *
   * @param gallons - Value in gallons (canonical storage format)
   * @param system - Target unit system
   * @param showBoth - Show both units (e.g., "25 gal (94.6 L)")
   */
  static formatVolume(gallons: Numeric, system: UnitSystem, showBoth: boolean = false): string {
    if (gallons === null || gallons === undefined) {
      return 'N/A';
    }

    if (system === 'imperial') {
      const primary = `${gallons.toFixed(2)} gal`;
      if (showBoth) {
        const liters = UnitConverter.gallonsToLiters(gallons);
        return `${primary} (${liters?.toFixed(2)} L)`;
      }
      return primary;
    } else {
      const liters = UnitConverter.gallonsToLiters(gallons);
      const primary = `${liters?.toFixed(2)} L`;
      if (showBoth) {
        return `${primary} (${gallons.toFixed(2)} gal)`;
      }
      return primary;
    }
  }

  /**
   * Format distance with appropriate unit label.
   *
   * @param miles - Value in miles (canonical storage format)
   * @param system - Target unit system
   * @param showBoth - Show both units
   */
  static formatDistance(miles: Numeric, system: UnitSystem, showBoth: boolean = false): string {
    if (miles === null || miles === undefined) {
      return 'N/A';
    }

    if (system === 'imperial') {
      const primary = `${miles.toLocaleString()} mi`;
      if (showBoth) {
        const km = UnitConverter.milesToKm(miles);
        return `${primary} (${km?.toLocaleString()} km)`;
      }
      return primary;
    } else {
      const km = UnitConverter.milesToKm(miles);
      const primary = `${km?.toLocaleString()} km`;
      if (showBoth) {
        return `${primary} (${miles.toLocaleString()} mi)`;
      }
      return primary;
    }
  }

  /**
   * Format fuel economy with appropriate unit label.
   *
   * @param mpg - Value in MPG (canonical storage format)
   * @param system - Target unit system
   * @param showBoth - Show both units
   */
  static formatFuelEconomy(mpg: Numeric, system: UnitSystem, showBoth: boolean = false): string {
    if (mpg === null || mpg === undefined) {
      return 'N/A';
    }

    if (system === 'imperial') {
      const primary = `${mpg.toFixed(1)} MPG`;
      if (showBoth) {
        const l100km = UnitConverter.mpgToL100km(mpg);
        return `${primary} (${l100km?.toFixed(1)} L/100km)`;
      }
      return primary;
    } else {
      const l100km = UnitConverter.mpgToL100km(mpg);
      const primary = `${l100km?.toFixed(1)} L/100km`;
      if (showBoth) {
        return `${primary} (${mpg.toFixed(1)} MPG)`;
      }
      return primary;
    }
  }

  /**
   * Format temperature with appropriate unit label.
   *
   * @param fahrenheit - Value in Fahrenheit (canonical storage format)
   * @param system - Target unit system
   * @param showBoth - Show both units
   */
  static formatTemperature(fahrenheit: Numeric, system: UnitSystem, showBoth: boolean = false): string {
    if (fahrenheit === null || fahrenheit === undefined) {
      return 'N/A';
    }

    if (system === 'imperial') {
      const primary = `${fahrenheit.toFixed(1)}°F`;
      if (showBoth) {
        const celsius = UnitConverter.fahrenheitToCelsius(fahrenheit);
        return `${primary} (${celsius?.toFixed(1)}°C)`;
      }
      return primary;
    } else {
      const celsius = UnitConverter.fahrenheitToCelsius(fahrenheit);
      const primary = `${celsius?.toFixed(1)}°C`;
      if (showBoth) {
        return `${primary} (${fahrenheit.toFixed(1)}°F)`;
      }
      return primary;
    }
  }

  /**
   * Format pressure with appropriate unit label.
   *
   * @param psi - Value in PSI (canonical storage format)
   * @param system - Target unit system
   * @param showBoth - Show both units
   */
  static formatPressure(psi: Numeric, system: UnitSystem, showBoth: boolean = false): string {
    if (psi === null || psi === undefined) {
      return 'N/A';
    }

    if (system === 'imperial') {
      const primary = `${psi.toFixed(1)} PSI`;
      if (showBoth) {
        const bar = UnitConverter.psiToBar(psi);
        return `${primary} (${bar?.toFixed(2)} bar)`;
      }
      return primary;
    } else {
      const bar = UnitConverter.psiToBar(psi);
      const primary = `${bar?.toFixed(2)} bar`;
      if (showBoth) {
        return `${primary} (${psi.toFixed(1)} PSI)`;
      }
      return primary;
    }
  }

  /**
   * Format weight with appropriate unit label.
   *
   * @param lbs - Value in pounds (canonical storage format)
   * @param system - Target unit system
   * @param showBoth - Show both units
   */
  static formatWeight(lbs: Numeric, system: UnitSystem, showBoth: boolean = false): string {
    if (lbs === null || lbs === undefined) {
      return 'N/A';
    }

    if (system === 'imperial') {
      const primary = `${lbs.toLocaleString()} lbs`;
      if (showBoth) {
        const kg = UnitConverter.lbsToKg(lbs);
        return `${primary} (${kg?.toLocaleString()} kg)`;
      }
      return primary;
    } else {
      const kg = UnitConverter.lbsToKg(lbs);
      const primary = `${kg?.toLocaleString()} kg`;
      if (showBoth) {
        return `${primary} (${lbs.toLocaleString()} lbs)`;
      }
      return primary;
    }
  }

  /**
   * Format torque with appropriate unit label.
   *
   * @param lbft - Value in lb-ft (canonical storage format)
   * @param system - Target unit system
   * @param showBoth - Show both units
   */
  static formatTorque(lbft: Numeric, system: UnitSystem, showBoth: boolean = false): string {
    if (lbft === null || lbft === undefined) {
      return 'N/A';
    }

    if (system === 'imperial') {
      const primary = `${lbft.toFixed(1)} lb-ft`;
      if (showBoth) {
        const nm = UnitConverter.lbftToNm(lbft);
        return `${primary} (${nm?.toFixed(1)} Nm)`;
      }
      return primary;
    } else {
      const nm = UnitConverter.lbftToNm(lbft);
      const primary = `${nm?.toFixed(1)} Nm`;
      if (showBoth) {
        return `${primary} (${lbft.toFixed(1)} lb-ft)`;
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
