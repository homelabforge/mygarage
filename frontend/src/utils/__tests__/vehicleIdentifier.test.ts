import { describe, expect, it } from 'vitest'
import type { TFunction } from 'i18next'
import {
  hasVin,
  identifierLabel,
  identifierValue,
  isSyntheticKey,
  keyForFilename,
  vinForDisplay,
} from '../vehicleIdentifier'

const t = ((key: string) => key) as unknown as TFunction
const Q = 'QABCDEFGH12345678'
const VIN = '1HGCM82633A004352'

describe('vehicleIdentifier (#226)', () => {
  it('tells a generated key from a VIN', () => {
    expect(isSyntheticKey(Q)).toBe(true)
    expect(isSyntheticKey(VIN)).toBe(false)
    expect(isSyntheticKey('QABC')).toBe(false)
  })

  it('shows the VIN for a VIN vehicle', () => {
    const v = { vin: VIN, identifier_type: 'vin', identifier: null, has_vin: true }
    expect(hasVin(v)).toBe(true)
    expect(identifierValue(v)).toBe(VIN)
    expect(identifierLabel(v, t)).toBe('vehicles:identifier.types.vin')
  })

  it('shows the serial, never the generated key', () => {
    const v = { vin: Q, identifier_type: 'serial', identifier: 'BX23S-10234', has_vin: false }
    expect(identifierValue(v)).toBe('BX23S-10234')
    expect(identifierLabel(v, t)).toBe('vehicles:identifier.types.serial')
    expect(identifierValue({ vin: Q, identifier_type: 'none', identifier: null, has_vin: false })).toBeNull()
  })

  it('shows the serial on a vehicle that went in with a generated VIN', () => {
    const v = { vin: VIN, identifier_type: 'serial', identifier: 'BX23S-1', has_vin: false }
    expect(identifierValue(v)).toBe('BX23S-1')
  })

  it('hides a bare generated key', () => {
    expect(vinForDisplay(Q)).toBeNull()
    expect(vinForDisplay(VIN)).toBe(VIN)
    expect(keyForFilename(Q)).toBe('vehicle')
    expect(keyForFilename(VIN)).toBe(VIN)
  })
})
