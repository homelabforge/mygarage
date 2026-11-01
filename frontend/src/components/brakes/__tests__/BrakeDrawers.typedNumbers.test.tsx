/**
 * Brake figures are typed text read in the user's language (G1b-21). They
 * were native number boxes read with Number(), so a German "6,5" mm pad read
 * as blank and the corner was skipped.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'

import type { BrakeAxle, BrakeOverview } from '../../../types/brake'
import { setActiveLocale } from '@/constants/i18n'

const logMock = vi.fn()
const axleMock = vi.fn()
vi.mock('../../../hooks/queries/useBrakes', () => ({
  useLogBrakeMeasurements: () => ({ mutate: logMock, isPending: false }),
  useUpdateBrakeAxle: () => ({ mutateAsync: axleMock, isPending: false }),
}))
vi.mock('../../../hooks/queries/useOdometerRecords', () => ({
  useNearestOdometer: () => ({ data: undefined, isSuccess: false }),
}))
vi.mock('../../../hooks/queries/useHoursRecords', () => ({
  useNearestHours: () => ({ data: undefined, isSuccess: false }),
}))
const toastError = vi.fn()
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: (...args: unknown[]) => toastError(...args) },
}))
vi.mock('../../../hooks/useUnitPreference', async () => {
  const { METRIC_UNITS: units } = await import('../../../__tests__/factories')
  const unitPreference = () => ({ system: 'metric', showBoth: false, gallonStandard: 'us', units })
  return { useUnitPreference: unitPreference, useAccountUnitPreference: unitPreference }
})

import LogBrakeMeasurementsDrawer from '../LogBrakeMeasurementsDrawer'
import AxleSetupDrawer from '../AxleSetupDrawer'

const VIN = '1HGCM82633A004352'
const AXLES: BrakeAxle[] = [
  { axle: 'front', brake_type: 'disc', min_thickness_mm: '3.00', new_thickness_mm: '10.00', configured: true, due_soon_mm: '4.75' },
  { axle: 'rear', brake_type: 'drum', min_thickness_mm: '1.50', new_thickness_mm: '5.00', drum_max_mm: '230.00', configured: true, due_soon_mm: '2.38' },
] as BrakeAxle[]
const OVERVIEW = {
  usage_axis: 'distance',
  tracks_distance: true,
  tracks_hours: false,
  axles: AXLES,
  corners: [],
} as unknown as BrakeOverview

const input = (id: string) => document.getElementById(id) as HTMLInputElement
const save = () => fireEvent.click(within(screen.getByRole('dialog')).getByText('common:save'))

beforeEach(() => {
  logMock.mockReset()
  axleMock.mockReset()
  toastError.mockReset()
})
afterEach(() => setActiveLocale('en'))

describe('brake drawers: numbers read in the user language', () => {
  it('de: a 6,5 mm pad saves as 6.5', () => {
    setActiveLocale('de')
    render(<LogBrakeMeasurementsDrawer vin={VIN} overview={OVERVIEW} open onClose={vi.fn()} />)
    fireEvent.change(input('brake-log-date'), { target: { value: '2026-10-01' } })
    fireEvent.change(input('brake-log-FL-inner_pad_mm'), { target: { value: '6,5' } })
    save()

    expect(logMock).toHaveBeenCalledTimes(1)
    expect(logMock.mock.calls[0][0].corners).toEqual([{ position: 'FL', inner_pad_mm: 6.5 }])
  })

  it('refuses a figure that is not a number instead of skipping it', () => {
    render(<LogBrakeMeasurementsDrawer vin={VIN} overview={OVERVIEW} open onClose={vi.fn()} />)
    fireEvent.change(input('brake-log-date'), { target: { value: '2026-10-01' } })
    fireEvent.change(input('brake-log-FL-inner_pad_mm'), { target: { value: '6.5' } })
    fireEvent.change(input('brake-log-FR-inner_pad_mm'), { target: { value: 'abc' } })
    save()

    expect(logMock).not.toHaveBeenCalled()
    expect(toastError).toHaveBeenCalledWith('numberInput.invalidField')
  })

  it('de: an axle limit of 25,4 mm saves as 25.4', async () => {
    setActiveLocale('de')
    render(<AxleSetupDrawer vin={VIN} axles={AXLES} open onClose={vi.fn()} />)
    fireEvent.change(input('brake-setup-front-limit'), { target: { value: '25,4' } })
    save()

    await vi.waitFor(() => expect(axleMock).toHaveBeenCalledTimes(1))
    expect(axleMock.mock.calls[0][0]).toMatchObject({ axle: 'front', rotor_min_mm: 25.4 })
  })
})
