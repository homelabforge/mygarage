/**
 * LiveLinkLiveTab's gauges, driven through the REAL telemetry unit layer.
 *
 * `LiveLinkLiveTab.test.tsx` stubs `@/utils/telemetryUnits` so it can assert
 * polling and status without arithmetic in the way. That stub also means it
 * cannot see whether the gauge renders what the layer returns, which is the
 * half that matters here: the unknown-unit marker is user-visible wording, and
 * a component that computed it correctly and painted something else would pass
 * every unit test in `utils/__tests__/telemetryUnits.test.ts`.
 *
 * Only `useUnitPreference` is stubbed, so `useUnitFormat`, the adapter table
 * and the classifier are all real.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { render, screen } from '../../../__tests__/test-utils'
import type { VehicleLiveLinkStatus } from '../../../types/livelink'
import { binarySystemFor, presetUnitsFor, type UnitSet } from '../../../types/units'
import vehiclesEn from '../../../locales/en/vehicles.json'

// Resolves ONLY the affordance key from the shipped English bundle, so the
// assertion below pins the wording a user actually reads. Every other key
// echoes, matching the global mock.
vi.mock('react-i18next', () => {
  const t = (key: string) =>
    key === 'vehicles:livelink.unknownUnit' ? vehiclesEn.livelink.unknownUnit : key
  return {
    useTranslation: () => ({
      t,
      i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
    }),
    Trans: ({ children }: { children: ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

const getVehicleStatus = vi.fn()
vi.mock('@/services/livelinkService', () => ({
  livelinkService: { getVehicleStatus: (vin: string) => getVehicleStatus(vin) },
}))
// `system` is DERIVED from `units`, as the real hook derives it: a literal here
// would make the custom-set case pass for the wrong reason.
let units: UnitSet = presetUnitsFor('imperial', 'us')
vi.mock('@/hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: binarySystemFor(units.volume),
    showBoth: false,
    units,
    gallonStandard: units.secondary_gallon,
  }),
}))
vi.mock('@/hooks/useTimeFormat', () => ({ useTimeFormat: () => ({ timeFormat: '12h' }) }))
vi.mock('@/utils/parseAPITimestamp', () => ({ formatTime: () => '12:00:00' }))

import LiveLinkLiveTab from '../LiveLinkLiveTab'

const status = (
  values: NonNullable<VehicleLiveLinkStatus['latest_values']>,
): VehicleLiveLinkStatus =>
  ({
    vin: 'V1',
    device_id: 'DEV1',
    device_status: 'online',
    ecu_status: 'online',
    rssi: -55,
    current_session_id: null,
    latest_values: values,
  }) satisfies VehicleLiveLinkStatus

beforeEach(() => {
  vi.clearAllMocks()
  units = presetUnitsFor('imperial', 'us')
})

describe('LiveLinkLiveTab gauges', () => {
  it('converts a standard hex-prefixed odometer, which SAE J1979 guarantees is km', async () => {
    getVehicleStatus.mockResolvedValue(
      status([
        {
          param_key: 'A6-Odometer',
          value: 1000,
          unit: null,
          display_name: 'Odometer',
          in_warning: false,
          timestamp: 'x',
        },
      ]),
    )
    render(<LiveLinkLiveTab vin="V1" />)
    // 1000 / 1.60934 = 621.37..., at the mi adapter's 0 dp.
    expect(await screen.findByText('621')).toBeInTheDocument()
    expect(screen.getByText('mi')).toBeInTheDocument()
  })

  it('marks a custom odometer with the unknown-unit wording instead of a mile label', async () => {
    getVehicleStatus.mockResolvedValue(
      status([
        {
          param_key: 'ODOMETER',
          value: 1000,
          unit: null,
          display_name: 'Odometer',
          in_warning: false,
          timestamp: 'x',
        },
      ]),
    )
    render(<LiveLinkLiveTab vin="V1" />)
    expect(await screen.findByText('1,000')).toBeInTheDocument()
    expect(screen.getByText('(unknown unit)')).toBeInTheDocument()
    expect(screen.queryByText('mi')).not.toBeInTheDocument()
  })

  it('answers per quantity for a custom set the binary system would call metric', async () => {
    // volume L collapses `system` to 'metric' (D8) while temperature is °F.
    units = { ...presetUnitsFor('metric', 'us'), temperature: 'f' }
    getVehicleStatus.mockResolvedValue(
      status([
        {
          param_key: 'COOLANT_TMP',
          value: 90,
          unit: 'C',
          display_name: 'Coolant',
          in_warning: false,
          timestamp: 'x',
        },
      ]),
    )
    render(<LiveLinkLiveTab vin="V1" />)
    expect(await screen.findByText('194.0')).toBeInTheDocument()
    expect(screen.getByText('°F')).toBeInTheDocument()
  })
})
