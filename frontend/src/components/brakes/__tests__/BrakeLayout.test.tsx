/**
 * The brake screens follow the vehicle's wheel layout (#272): a bike gets a
 * Front and a Rear corner, and a corner the layout doesn't have only shows up
 * when it still has history, flagged, and no drawer offers it.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'

import type { BrakeCorner, BrakeOverview } from '../../../types/brake'

const useBrakesMock = vi.fn()
const logMock = vi.fn()
const jobMock = vi.fn()

vi.mock('../../../hooks/queries/useBrakes', () => ({
  useBrakes: () => useBrakesMock(),
  useLogBrakeMeasurements: () => ({ mutate: logMock, isPending: false }),
  useCreateBrakeJob: () => ({ mutate: jobMock, isPending: false }),
  useUpdateBrakeAxle: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateBrakeMeasurement: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteBrakeMeasurement: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateBrakeJob: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteBrakeJob: () => ({ mutate: vi.fn(), isPending: false }),
}))
vi.mock('../../../hooks/queries/useOdometerRecords', () => ({
  useNearestOdometer: () => ({ data: undefined, isSuccess: false }),
}))
vi.mock('../../../hooks/queries/useHoursRecords', () => ({
  useNearestHours: () => ({ data: undefined, isSuccess: false }),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../../../hooks/useUnitPreference', async () => {
  const { METRIC_UNITS: units } = await import('../../../__tests__/factories')
  const unitPreference = () => ({ system: 'metric', showBoth: false, gallonStandard: 'us', units })
  return { useUnitPreference: unitPreference, useAccountUnitPreference: unitPreference }
})

import BrakeList from '../BrakeList'
import BrakeJobDrawer from '../BrakeJobDrawer'

const VIN = '1HGCM82633A004352'

function corner(position: BrakeCorner['position'], extra: Partial<BrakeCorner> = {}): BrakeCorner {
  const rear = position.startsWith('R')
  return {
    position,
    axle: rear ? 'rear' : 'front',
    brake_type: rear ? 'drum' : 'disc',
    condition: 'unknown',
    wear_status: 'no_measurements',
    surface_past_limit: false,
    on_layout: true,
    measurements: [],
    jobs: [],
    ...extra,
  }
}

/** A bike: F and R on the layout, plus any off-layout corners the server kept. */
function twoWheels(offLayout: BrakeCorner[] = []): BrakeOverview {
  return {
    usage_axis: 'distance',
    tracks_distance: true,
    tracks_hours: false,
    axles: [
      { axle: 'front', brake_type: 'disc', min_thickness_mm: '3.00', new_thickness_mm: '10.00', configured: false, due_soon_mm: '4.75' },
      { axle: 'rear', brake_type: 'drum', min_thickness_mm: '1.50', new_thickness_mm: '5.00', drum_max_mm: '230.00', configured: true, due_soon_mm: '2.38' },
    ],
    corners: [corner('F'), corner('R'), ...offLayout],
    wheel_layout: 'two',
  }
}

// It was a car once: FL kept its pads when the type went to Motorcycle.
const STALE_FL = corner('FL', {
  on_layout: false,
  condition: 'ok',
  wear_status: 'insufficient_measurements',
  inner_pad_mm: '8.00',
  thinnest_mm: '8.00',
})

const field = (id: string): HTMLInputElement => {
  const el = document.getElementById(id)
  if (!(el instanceof HTMLInputElement)) throw new Error(`no input #${id}`)
  return el
}
const dialog = (): HTMLElement => screen.getByRole('dialog')
const save = (): void => {
  fireEvent.click(within(dialog()).getByRole('button', { name: 'common:save' }))
}
const section = (axleKey: string): HTMLElement => {
  const el = screen.getByText(axleKey).closest('section')
  if (!el) throw new Error(`no section for ${axleKey}`)
  return el
}
const cardOf = (label: string): HTMLElement => {
  const el = screen.getByText(label).closest('.relative')
  if (!(el instanceof HTMLElement)) throw new Error(`no card for ${label}`)
  return el
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('brake screens on a two-wheel layout', () => {
  it('shows one Front card and logs Front and Rear only', () => {
    useBrakesMock.mockReturnValue({ data: twoWheels(), isLoading: false, error: null })
    render(<BrakeList vin={VIN} />)

    const front = section('brakes.frontAxle')
    expect(within(front).getAllByRole('button', { name: 'brakes.historyOpen' })).toHaveLength(1)
    expect(within(front).getByText('tireList.positions.F')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'brakes.logMeasurements' }))
    expect(document.getElementById('brake-log-F-inner_pad_mm')).not.toBeNull()
    expect(document.getElementById('brake-log-R-shoe_mm')).not.toBeNull()
    for (const p of ['FL', 'FR']) expect(document.getElementById(`brake-log-${p}-inner_pad_mm`)).toBeNull()
    for (const p of ['RL', 'RR']) expect(document.getElementById(`brake-log-${p}-shoe_mm`)).toBeNull()

    fireEvent.change(field('brake-log-date'), { target: { value: '2026-10-01' } })
    fireEvent.change(field('brake-log-F-inner_pad_mm'), { target: { value: '6' } })
    save()
    expect(logMock).toHaveBeenCalledTimes(1)
    expect(logMock.mock.calls[0][0].corners).toEqual([{ position: 'F', inner_pad_mm: 6 }])
  })

  it('the Front axle button sends F, never FL and FR', () => {
    useBrakesMock.mockReturnValue({ data: twoWheels(), isLoading: false, error: null })
    render(<BrakeList vin={VIN} />)
    // The header's Brake job comes first, ahead of the cards'.
    fireEvent.click(screen.getAllByRole('button', { name: 'brakes.brakeJob' })[0])

    fireEvent.click(within(dialog()).getByRole('button', { name: 'brakes.frontAxle' }))
    save()
    expect(jobMock).toHaveBeenCalledTimes(1)
    expect(jobMock.mock.calls[0][0].corners).toEqual([{ position: 'F', new_thickness_mm: 10 }])
  })

  it('All corners ticks the layout’s corners', () => {
    useBrakesMock.mockReturnValue({ data: twoWheels(), isLoading: false, error: null })
    render(<BrakeList vin={VIN} />)
    fireEvent.click(screen.getAllByRole('button', { name: 'brakes.brakeJob' })[0])

    const chips = within(dialog())
    expect(chips.getByRole('button', { name: 'tireList.positions.F' })).toBeInTheDocument()
    expect(chips.getByRole('button', { name: 'tireList.positions.R' })).toBeInTheDocument()
    expect(chips.queryByRole('button', { name: 'tireList.positions.FL' })).toBeNull()

    fireEvent.click(chips.getByRole('button', { name: 'brakes.allCorners' }))
    save()
    expect(jobMock.mock.calls[0][0].corners).toEqual([
      { position: 'F', new_thickness_mm: 10 },
      { position: 'R', new_thickness_mm: 5 },
    ])
  })
})

describe('an off-layout corner with history', () => {
  it('shows flagged and the log drawer leaves it out', () => {
    useBrakesMock.mockReturnValue({ data: twoWheels([STALE_FL]), isLoading: false, error: null })
    render(<BrakeList vin={VIN} />)

    expect(within(cardOf('tireList.positions.FL')).getByText('tireList.offLayout')).toBeInTheDocument()
    expect(within(cardOf('tireList.positions.F')).queryByText('tireList.offLayout')).toBeNull()
    expect(screen.getAllByText('tireList.offLayout')).toHaveLength(1)

    fireEvent.click(screen.getByRole('button', { name: 'brakes.logMeasurements' }))
    expect(document.getElementById('brake-log-FL-inner_pad_mm')).toBeNull()
    expect(document.getElementById('brake-log-F-inner_pad_mm')).not.toBeNull()
  })

  it('the job drawer leaves it out too', () => {
    useBrakesMock.mockReturnValue({ data: twoWheels([STALE_FL]), isLoading: false, error: null })
    render(<BrakeList vin={VIN} />)

    fireEvent.click(screen.getAllByRole('button', { name: 'brakes.brakeJob' })[0])
    expect(within(dialog()).queryByRole('button', { name: 'tireList.positions.FL' })).toBeNull()
    fireEvent.click(within(dialog()).getByRole('button', { name: 'brakes.allCorners' }))
    save()
    expect(jobMock.mock.calls[0][0].corners.map((c: { position: string }) => c.position)).toEqual(['F', 'R'])
  })

  it('a brake job from the FL card pre-ticks F only', () => {
    useBrakesMock.mockReturnValue({ data: twoWheels([STALE_FL]), isLoading: false, error: null })
    render(<BrakeList vin={VIN} />)

    fireEvent.click(within(cardOf('tireList.positions.FL')).getByRole('button', { name: 'brakes.brakeJob' }))
    save()
    expect(jobMock).toHaveBeenCalledTimes(1)
    expect(jobMock.mock.calls[0][0].corners).toEqual([{ position: 'F', new_thickness_mm: 10 }])
  })

  it('the job drawer drops a stale caller’s off-layout corner', () => {
    render(
      <BrakeJobDrawer vin={VIN} overview={twoWheels([STALE_FL])} open onClose={vi.fn()} initialCorners={['FL', 'F']} />
    )
    save()
    expect(jobMock).toHaveBeenCalledTimes(1)
    expect(jobMock.mock.calls[0][0].corners).toEqual([{ position: 'F', new_thickness_mm: 10 }])
  })
})
