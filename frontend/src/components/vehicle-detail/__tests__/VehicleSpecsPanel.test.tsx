import type { ComponentProps } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent, waitFor, within } from '@testing-library/react'
import { render } from '../../../__tests__/test-utils'
import type { Vehicle } from '../../../types/vehicle'
import vehicleService from '../../../services/vehicleService'

vi.mock('../../../services/vehicleService', () => ({
  default: { update: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

/* A full resolved set, not just the binary flag: `useUnitFormat` reads
 * `units` per quantity, and the mixed sets below are the cases the flag
 * cannot express. Mutable so a test can switch sets in place. */
const IMPERIAL_UNITS = {
  distance: 'mi', speed: 'mph', length: 'ft', volume: 'gal_us',
  consumption: 'mpg_us', pressure: 'psi', temperature: 'f', mass: 'lb',
  torque: 'lbft', tread: 'in32', secondary_gallon: 'us',
} as const
const METRIC_UNITS = {
  distance: 'km', speed: 'kmh', length: 'm', volume: 'L',
  consumption: 'l_100km', pressure: 'kpa', temperature: 'c', mass: 'kg',
  torque: 'nm', tread: 'mm', secondary_gallon: 'us',
} as const

const unitPrefMock = vi.hoisted(() => ({
  system: 'metric' as 'metric' | 'imperial',
  showBoth: false,
  gallonStandard: 'us' as const,
  units: {
    distance: 'km', speed: 'kmh', length: 'm', volume: 'L',
    consumption: 'l_100km', pressure: 'kpa', temperature: 'c', mass: 'kg',
    torque: 'nm', tread: 'mm', secondary_gallon: 'us',
  } as Record<string, string>,
}))
vi.mock('../../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => unitPrefMock,
}))

/* The numeric controls here are NumberInput, which renders type="text", so the
 * raw value carries the reader's own decimal mark. */
const localeMock = vi.hoisted(() => ({ value: 'en-US' }))
vi.mock('@/constants/i18n', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/constants/i18n')>()
  return { ...actual, getActiveLocale: () => localeMock.value }
})

import VehicleSpecsPanel from '../VehicleSpecsPanel'
import { toast } from 'sonner'

const mockedUpdate = vi.mocked(vehicleService).update

const baseVehicle = {
  vin: 'TEST0000000000001',
  nickname: 'Test',
  vehicle_type: 'Car',
  usage_unit: 'distance',
  secondary_usage_enabled: false,
  oil_viscosity: '5W-30',
  oil_capacity_liters: '4.7',
  lug_nut_torque_nm: '135.0',
  oil_filter_part_number: null,
  fuel_filter_part_number: null,
  coolant_type: null,
  brake_fluid_type: null,
  transmission_fluid_type: null,
  maintenance_specs_notes: null,
} as unknown as Vehicle

function renderPanel(props: Partial<ComponentProps<typeof VehicleSpecsPanel>> = {}) {
  const onUpdated = vi.fn()
  render(
    <VehicleSpecsPanel
      vin="TEST0000000000001"
      vehicle={baseVehicle}
      onUpdated={onUpdated}
      {...props}
    />,
  )
  return { onUpdated }
}

describe('VehicleSpecsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    unitPrefMock.system = 'metric'
    unitPrefMock.units = { ...METRIC_UNITS }
    localeMock.value = 'en-US'
    mockedUpdate.mockResolvedValue(baseVehicle)
  })

  it('shows recorded oil viscosity and torque on the card', () => {
    renderPanel()
    expect(screen.getByText('detail.specs.title')).toBeInTheDocument()
    expect(screen.getByText('5W-30')).toBeInTheDocument()
  })

  it('opens the editor drawer from the card overlay', async () => {
    renderPanel()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'detail.specs.editAria' }))
    const drawer = await screen.findByRole('dialog')
    expect(drawer).toHaveAccessibleName('detail.specs.title')
    expect(within(drawer).getByLabelText('detail.specs.oilViscosity')).toHaveValue('5W-30')
  })

  it('opens when editRequestKey increments', async () => {
    const { rerender } = render(
      <VehicleSpecsPanel
        vin="TEST0000000000001"
        vehicle={baseVehicle}
        onUpdated={vi.fn()}
        editRequestKey={0}
      />,
    )
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    rerender(
      <VehicleSpecsPanel
        vin="TEST0000000000001"
        vehicle={baseVehicle}
        onUpdated={vi.fn()}
        editRequestKey={1}
      />,
    )
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })

  it('saves oil viscosity via partial PUT and closes', async () => {
    const { onUpdated } = renderPanel()
    fireEvent.click(screen.getByRole('button', { name: 'detail.specs.editAria' }))
    const drawer = await screen.findByRole('dialog')
    fireEvent.change(within(drawer).getByLabelText('detail.specs.oilViscosity'), {
      target: { value: '0W-20' },
    })
    fireEvent.click(within(drawer).getByRole('button', { name: 'common:save' }))

    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledTimes(1))
    const [, payload] = mockedUpdate.mock.calls[0]
    expect(payload.oil_viscosity).toBe('0W-20')
    /* EXACT, not toBeCloseTo. A round trip through gallons yields 4.693910612 L
     * and back through lb-ft yields 135.04 Nm, and `toBeCloseTo(4.7, 1)` /
     * `toBeCloseTo(135, 0)` accept both, so the looser form could not detect the
     * re-conversion these assertions exist to forbid. */
    expect(payload.oil_capacity_liters).toBe(4.7)
    expect(payload.lug_nut_torque_nm).toBe(135)
    await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(baseVehicle))
    expect(toast.success).toHaveBeenCalled()
  })

  it('records a fuel filter part number and shows it on the card', async () => {
    /* Added for diesels, where the filters are a scheduled item, but NOT gated
     * on fuel type: an older petrol vehicle's inline filter is a real service
     * part too, and a column that exists only for diesels cannot record one.
     * A vehicle with no fuel filter simply leaves it blank and the card omits
     * the row, which is how every other spec here behaves. */
    renderPanel()
    fireEvent.click(screen.getByRole('button', { name: 'detail.specs.editAria' }))
    const drawer = await screen.findByRole('dialog')
    fireEvent.change(within(drawer).getByLabelText('detail.specs.fuelFilter'), {
      target: { value: '68436631AA' },
    })
    fireEvent.click(within(drawer).getByRole('button', { name: 'common:save' }))

    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledTimes(1))
    const [, payload] = mockedUpdate.mock.calls[0]
    expect(payload.fuel_filter_part_number).toBe('68436631AA')
  })

  it('leaves an untouched fuel filter alone rather than clearing it', async () => {
    /* The registered-but-unseeded trap this codebase has hit before: a field
     * mounted without its current value submits an explicit null and wipes the
     * column on the next save of any OTHER field. */
    renderPanel({ vehicle: { ...baseVehicle, fuel_filter_part_number: '68436631AA' } })
    fireEvent.click(screen.getByRole('button', { name: 'detail.specs.editAria' }))
    const drawer = await screen.findByRole('dialog')
    fireEvent.change(within(drawer).getByLabelText('detail.specs.oilViscosity'), {
      target: { value: '5W-40' },
    })
    fireEvent.click(within(drawer).getByRole('button', { name: 'common:save' }))

    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledTimes(1))
    const [, payload] = mockedUpdate.mock.calls[0]
    expect(payload.fuel_filter_part_number).toBe('68436631AA')
  })

  describe('resolved units', () => {
    it('reads litres with lb-ft, the pair the binary flag cannot express', async () => {
      /* THE discriminator. `useUnitPreference().system` is collapsed out of
       * VOLUME, so litres answers 'metric' and the old binary branch rendered
       * torque as "135.0 Nm" for a reader who chose lb-ft. That is the
       * disagreement issue #152 was filed about. */
      unitPrefMock.units = { ...IMPERIAL_UNITS, volume: 'L' }
      renderPanel()

      // Litres for a litre reader, unchanged by the quart work: oil follows the
      // resolved VOLUME token, and only the gallon flavours become quarts.
      expect(screen.getByText('4.7 L')).toBeInTheDocument()
      expect(screen.getByText('99.6 lb-ft')).toBeInTheDocument()
      expect(screen.queryByText('135.0 Nm')).not.toBeInTheDocument()
    })

    it('reads oil in QUARTS for a gallon reader, never gallons', () => {
      /* Engine oil is quoted in quarts wherever fuel is quoted in gallons, and
       * this used to ride the fuel adapter: 4.7 L rendered "1.24 gal". Nobody
       * enters oil that way, so a reader typing "12" for a 6.7 Cummins stored
       * 45.42 L and the card read it straight back. The round trip is
       * symmetric, so only an assertion on the UNIT can catch it. */
      unitPrefMock.units = { ...IMPERIAL_UNITS }
      renderPanel()

      expect(screen.getByText('5.0 qt')).toBeInTheDocument()
      expect(screen.queryByText('1.24 gal')).not.toBeInTheDocument()
      expect(screen.getByText('99.6 lb-ft')).toBeInTheDocument()
    })

    it('stores twelve QUARTS when a gallon reader types 12, not twelve gallons', async () => {
      /* The corruption this fix exists for, as the number it produced. A 6.7
       * Cummins holds 12 US quarts. Typed into a field labelled "gal" it stored
       * 12 x 3.785411784 = 45.42 L, and the card read "12 gal" back, so nothing
       * in the UI could show it. Measured on a real instance before this
       * landed. The assertion has to be on the CANONICAL value: a display-level
       * check passes either way, which is why the bug survived. */
      unitPrefMock.units = { ...IMPERIAL_UNITS }
      renderPanel()
      fireEvent.click(screen.getByRole('button', { name: 'detail.specs.editAria' }))
      const drawer = await screen.findByRole('dialog')
      fireEvent.change(within(drawer).getByLabelText('detail.specs.oilCapacityWithUnit'), {
        target: { value: '12' },
      })
      fireEvent.click(within(drawer).getByRole('button', { name: 'common:save' }))

      await waitFor(() => expect(mockedUpdate).toHaveBeenCalledTimes(1))
      const [, payload] = mockedUpdate.mock.calls[0]
      expect(payload.oil_capacity_liters).toBeCloseTo(11.356, 3)
      expect(payload.oil_capacity_liters).not.toBeCloseTo(45.42, 1)
    })

    it('names the resolved unit in each editor label', async () => {
      unitPrefMock.units = { ...IMPERIAL_UNITS }
      renderPanel()
      fireEvent.click(screen.getByRole('button', { name: 'detail.specs.editAria' }))
      const drawer = await screen.findByRole('dialog')

      /* The mock `t` returns the key, so the presence of the interpolated key
       * is what pins that the label is composed from the resolved unit rather
       * than from a hardcoded 'gal' / 'L' pair. */
      expect(within(drawer).getByLabelText('detail.specs.oilCapacityWithUnit')).toHaveValue('5.0')
      expect(within(drawer).getByLabelText('detail.specs.lugTorqueWithUnit')).toHaveValue('99.6')
    })

    it('posts the seeded canonical value back when an imperial field is untouched', async () => {
      /* The frozen-gallon class of bug: the field displays 1.24 gal, and
       * re-converting that on save would store 4.693910612 L, moving the record
       * every time it is opened and saved. */
      unitPrefMock.units = { ...IMPERIAL_UNITS }
      renderPanel()
      fireEvent.click(screen.getByRole('button', { name: 'detail.specs.editAria' }))
      const drawer = await screen.findByRole('dialog')
      fireEvent.click(within(drawer).getByRole('button', { name: 'common:save' }))

      await waitFor(() => expect(mockedUpdate).toHaveBeenCalledTimes(1))
      const [, payload] = mockedUpdate.mock.calls[0]
      expect(payload.oil_capacity_liters).toBe(4.7)
      expect(payload.lug_nut_torque_nm).toBe(135)
    })

    it('converts an edited imperial field back to canonical', async () => {
      unitPrefMock.units = { ...IMPERIAL_UNITS }
      renderPanel()
      fireEvent.click(screen.getByRole('button', { name: 'detail.specs.editAria' }))
      const drawer = await screen.findByRole('dialog')
      fireEvent.change(within(drawer).getByLabelText('detail.specs.lugTorqueWithUnit'), {
        target: { value: '100' },
      })
      fireEvent.click(within(drawer).getByRole('button', { name: 'common:save' }))

      await waitFor(() => expect(mockedUpdate).toHaveBeenCalledTimes(1))
      const [, payload] = mockedUpdate.mock.calls[0]
      // 100 lb-ft x 1.35582 = 135.582 Nm
      expect(payload.lug_nut_torque_nm).toBeCloseTo(135.582, 3)
    })

    it('reads a comma decimal mark, which NumberInput can carry', async () => {
      /* NumberInput is type="text" inputMode="decimal", so a German reader's
       * raw value is "4,5". canonicalFromUnitField's Number() would read that
       * as NaN, which is why this form parses with parseDecimalInput first. */
      localeMock.value = 'de-DE'
      renderPanel()
      fireEvent.click(screen.getByRole('button', { name: 'detail.specs.editAria' }))
      const drawer = await screen.findByRole('dialog')
      fireEvent.change(within(drawer).getByLabelText('detail.specs.oilCapacityWithUnit'), {
        target: { value: '5,25' },
      })
      fireEvent.click(within(drawer).getByRole('button', { name: 'common:save' }))

      await waitFor(() => expect(mockedUpdate).toHaveBeenCalledTimes(1))
      const [, payload] = mockedUpdate.mock.calls[0]
      expect(payload.oil_capacity_liters).toBe(5.25)
    })
  })

  it('shows empty state when no specs are set', () => {
    renderPanel({
      vehicle: {
        ...baseVehicle,
        oil_viscosity: null,
        oil_capacity_liters: null,
        lug_nut_torque_nm: null,
      } as Vehicle,
    })
    expect(screen.getByText('detail.specs.empty')).toBeInTheDocument()
  })
})
