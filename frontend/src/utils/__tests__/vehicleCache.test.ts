import { afterEach, describe, expect, it } from 'vitest'
import { forgetCachedVehicle, readCachedVehicle, rememberVehicle } from '../vehicleCache'
import type { Vehicle } from '../../types/vehicle'

const VIN = 'CACHE1234567890AB'

const vehicle = {
  vin: VIN,
  nickname: 'Cached',
  vehicle_type: 'Motorcycle',
  wheel_layout: null,
  effective_wheel_layout: 'two',
  default_wheel_layout: 'two',
} as unknown as Vehicle

afterEach(() => {
  localStorage.clear()
})

describe('vehicleCache', () => {
  it('hands back what it remembered', () => {
    rememberVehicle(VIN, vehicle)
    expect(readCachedVehicle(VIN)?.effective_wheel_layout).toBe('two')
  })

  it('does not serve a copy written before wheel layouts', () => {
    // What a pre-#272 build wrote: no version and no layout fields, so the
    // Details drawer would render "Automatic: " off it.
    localStorage.setItem(
      `vehicle-cache-${VIN}`,
      JSON.stringify({ timestamp: Date.now(), data: { vin: VIN, nickname: 'Old', vehicle_type: 'Car' } }),
    )
    expect(readCachedVehicle(VIN)).toBeNull()
  })

  it('forgets a copy', () => {
    rememberVehicle(VIN, vehicle)
    forgetCachedVehicle(VIN)
    expect(readCachedVehicle(VIN)).toBeNull()
  })
})
