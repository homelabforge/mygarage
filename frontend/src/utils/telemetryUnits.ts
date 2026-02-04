/**
 * Telemetry unit conversion utilities for LiveLink OBD2 data.
 *
 * OBD2 data is received in SI/metric units. This utility converts
 * values to the user's preferred unit system (imperial/metric).
 *
 * Native OBD2 units:
 * - Speed: km/h
 * - Temperature: °C
 * - Distance: km
 * - Pressure: kPa or bar
 * - Percentage: % (no conversion)
 * - RPM: rpm (no conversion)
 * - Voltage: V (no conversion)
 * - Time: seconds (no conversion)
 */

import type { UnitSystem } from './units'

interface ConvertedTelemetry {
  value: number
  unit: string
}

// Conversion factors
const KM_TO_MILES = 0.621371
const KPA_TO_PSI = 0.145038

/**
 * Detect the type of parameter from its key and unit.
 */
function detectParamType(
  paramKey: string,
  unit: string | null
): 'speed' | 'temperature' | 'distance' | 'pressure' | 'none' {
  const key = paramKey.toLowerCase()
  const unitLower = (unit || '').toLowerCase()

  // Speed detection
  if (
    key.includes('speed') ||
    key.includes('vehiclespeed') ||
    unitLower === 'km/h' ||
    unitLower === 'kmh'
  ) {
    return 'speed'
  }

  // Temperature detection
  if (
    key.includes('temp') ||
    key.includes('coolant') ||
    key.includes('ambient') ||
    key.includes('intake') ||
    unitLower === '°c' ||
    unitLower === 'c' ||
    unitLower === 'celsius'
  ) {
    return 'temperature'
  }

  // Distance detection
  if (
    key.includes('distance') ||
    key.includes('odometer') ||
    key.includes('mileage') ||
    unitLower === 'km' ||
    unitLower === 'kilometers'
  ) {
    return 'distance'
  }

  // Pressure detection
  if (
    key.includes('press') ||
    key.includes('baro') ||
    key.includes('manifold') ||
    unitLower === 'kpa' ||
    unitLower === 'bar'
  ) {
    return 'pressure'
  }

  return 'none'
}

/**
 * Convert temperature from Celsius to Fahrenheit.
 */
function celsiusToFahrenheit(celsius: number): number {
  return (celsius * 9) / 5 + 32
}

/**
 * Convert speed from km/h to mph.
 */
function kmhToMph(kmh: number): number {
  return kmh * KM_TO_MILES
}

/**
 * Convert distance from km to miles.
 */
function kmToMiles(km: number): number {
  return km * KM_TO_MILES
}

/**
 * Convert pressure from kPa to PSI.
 */
function kpaToPsi(kpa: number): number {
  return kpa * KPA_TO_PSI
}

/**
 * Convert bar to PSI.
 */
function barToPsi(bar: number): number {
  return bar * 14.5038
}

/**
 * Convert a telemetry value based on user's unit preference.
 *
 * @param value - Raw value from OBD2 (in SI/metric units)
 * @param paramKey - Parameter key (e.g., "SPEED", "COOLANT_TEMP")
 * @param unit - Original unit string from telemetry
 * @param system - User's preferred unit system
 * @returns Converted value and unit label
 */
export function convertTelemetryValue(
  value: number,
  paramKey: string,
  unit: string | null,
  system: UnitSystem
): ConvertedTelemetry {
  // If metric, return as-is (OBD2 data is already in SI units)
  if (system === 'metric') {
    return { value, unit: unit || '' }
  }

  // Imperial conversions
  const paramType = detectParamType(paramKey, unit)

  switch (paramType) {
    case 'speed':
      return {
        value: kmhToMph(value),
        unit: 'mph',
      }

    case 'temperature':
      return {
        value: celsiusToFahrenheit(value),
        unit: '°F',
      }

    case 'distance':
      return {
        value: kmToMiles(value),
        unit: 'mi',
      }

    case 'pressure': {
      const unitLower = (unit || '').toLowerCase()
      if (unitLower === 'bar') {
        return {
          value: barToPsi(value),
          unit: 'PSI',
        }
      }
      // Default: kPa
      return {
        value: kpaToPsi(value),
        unit: 'PSI',
      }
    }

    default:
      // No conversion needed (RPM, %, V, seconds, etc.)
      return { value, unit: unit || '' }
  }
}

/**
 * Format a telemetry value with appropriate decimal places.
 *
 * @param value - Numeric value to format
 * @param paramKey - Parameter key for context
 * @returns Formatted string
 */
export function formatTelemetryValue(value: number, paramKey: string): string {
  const key = paramKey.toLowerCase()

  // Integers for these values
  if (
    key.includes('rpm') ||
    key.includes('speed') ||
    key.includes('odometer') ||
    key.includes('distance')
  ) {
    return Math.round(value).toLocaleString()
  }

  // One decimal for temperatures and percentages
  if (key.includes('temp') || key.includes('%') || key.includes('throttle') || key.includes('load')) {
    return value.toFixed(1)
  }

  // Two decimals for voltage
  if (key.includes('volt') || key.includes('battery')) {
    return value.toFixed(2)
  }

  // Default: one decimal
  return value.toFixed(1)
}

/**
 * Get display name for a parameter with unit-aware formatting.
 */
export function getParamDisplayName(paramKey: string, displayName: string | null): string {
  if (displayName) return displayName

  // Clean up common OBD2 parameter keys
  const key = paramKey
    .replace(/^[0-9A-F]{2}-/i, '') // Remove hex prefix like "0D-"
    .replace(/([a-z])([A-Z])/g, '$1 $2') // Add spaces between camelCase
    .replace(/_/g, ' ') // Replace underscores with spaces

  // Capitalize first letter of each word
  return key
    .split(' ')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ')
}
