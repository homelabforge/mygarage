import type { TFunction } from 'i18next'

/**
 * A vehicle's key vs. what identifies it (#226).
 *
 * `vin` is the key every route hangs off. For a vehicle with a VIN it IS the
 * VIN. A tractor, a mower or a boat with a HIN is keyed by a generated "Q" key
 * instead (Q can't appear in a VIN), and what people see is `identifier`: its
 * serial number, HIN, chassis number or asset tag. Never show the generated key.
 */

export type IdentifierType = 'vin' | 'serial' | 'hin' | 'chassis' | 'asset_tag' | 'none'

export const IDENTIFIER_TYPES: readonly IdentifierType[] = ['vin', 'serial', 'hin', 'chassis', 'asset_tag', 'none']

/** The identifier types a vehicle without a VIN can have, in the order the picker shows them. */
export const NON_VIN_IDENTIFIER_TYPES: readonly IdentifierType[] = ['serial', 'hin', 'chassis', 'asset_tag', 'none']

export interface IdentifiedVehicle {
  vin: string
  identifier_type?: string | null
  identifier?: string | null
  has_vin?: boolean
}

const SYNTHETIC_KEY = /^Q[A-HJ-NPR-Z0-9]{16}$/

/** Whether a key was generated for a vehicle without a VIN. */
export function isSyntheticKey(key: string | null | undefined): boolean {
  return !!key && SYNTHETIC_KEY.test(key)
}

/** Whether the vehicle has a real VIN (decode, NHTSA recalls, window sticker apply). */
export function hasVin(vehicle: IdentifiedVehicle): boolean {
  if (typeof vehicle.has_vin === 'boolean') return vehicle.has_vin
  return (vehicle.identifier_type ?? 'vin') === 'vin'
}

/** The identifier to show: the VIN, or the serial / HIN / ...; null when there is none. */
export function identifierValue(vehicle: IdentifiedVehicle): string | null {
  if (hasVin(vehicle)) return vehicle.vin
  return vehicle.identifier || null
}

/** The label for the identifier ("VIN", "Serial number", ...). */
export function identifierLabel(vehicle: IdentifiedVehicle, t: TFunction): string {
  const kind = hasVin(vehicle) ? 'vin' : (vehicle.identifier_type ?? 'none')
  return identifierTypeLabel(kind, t)
}

export function identifierTypeLabel(kind: string, t: TFunction): string {
  return t(`vehicles:identifier.types.${kind}`, { defaultValue: kind })
}

/**
 * Where only the key is at hand (a trailer link, a stats payload): the key when
 * it's a VIN, null when it's a generated key that must not be shown.
 */
export function vinForDisplay(key: string | null | undefined): string | null {
  if (!key || isSyntheticKey(key)) return null
  return key
}

/** The vehicle's part of a client-side download name: the VIN, or "vehicle". */
export function keyForFilename(key: string): string {
  return isSyntheticKey(key) ? 'vehicle' : key
}
