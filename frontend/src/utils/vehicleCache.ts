/**
 * The offline copy of a vehicle that VehicleDetail reads when the network is
 * down. Written on every load AND on every save (#172): a save that changed
 * the vehicle's odometer unit must not leave an offline visit, or the
 * analytics page's fallback, reading entry fields in the old unit.
 */
import type { Vehicle } from '../types/vehicle'

const keyFor = (vin: string): string => `vehicle-cache-${vin}`

// Bump this when Vehicle gains a field the page can't do without. An older
// copy then reads as missing instead of half a vehicle (#272: a pre-upgrade
// copy has no wheel layout).
const CACHE_VERSION = 2

interface CachedVehicle {
  version?: number
  timestamp?: number
  data?: Vehicle
}

/**
 * Store the vehicle as the offline copy for `vin`.
 *
 * @param vin The VIN as the route spells it (the key VehicleDetail reads).
 * @param vehicle The vehicle to remember.
 */
export function rememberVehicle(vin: string, vehicle: Vehicle): void {
  try {
    localStorage.setItem(keyFor(vin), JSON.stringify({ version: CACHE_VERSION, timestamp: Date.now(), data: vehicle }))
  } catch {
    // Storage full or blocked: the cache is a convenience, never required.
  }
}

/**
 * The offline copy for `vin`, or null when there is none, it is unreadable,
 * or an older build wrote it.
 *
 * @param vin The VIN as the route spells it.
 * @returns The cached vehicle, or null.
 */
export function readCachedVehicle(vin: string): Vehicle | null {
  try {
    const raw = localStorage.getItem(keyFor(vin))
    if (!raw) return null
    const cached = JSON.parse(raw) as CachedVehicle
    return cached.version === CACHE_VERSION ? (cached.data ?? null) : null
  } catch {
    return null
  }
}

/**
 * Drop the offline copy for `vin`.
 *
 * @param vin The VIN as the route spells it.
 */
export function forgetCachedVehicle(vin: string): void {
  try {
    localStorage.removeItem(keyFor(vin))
  } catch {
    // Nothing to do.
  }
}
