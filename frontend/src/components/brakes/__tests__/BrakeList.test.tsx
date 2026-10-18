import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'

import type { BrakeCorner, BrakeOverview } from '../../../types/brake'

const useBrakesMock = vi.fn()
const logMock = vi.fn()
const jobMock = vi.fn()
const axleMock = vi.fn()

vi.mock('../../../hooks/queries/useBrakes', () => ({
  useBrakes: () => useBrakesMock(),
  useLogBrakeMeasurements: () => ({ mutate: logMock, isPending: false }),
  useCreateBrakeJob: () => ({ mutate: jobMock, isPending: false }),
  useUpdateBrakeAxle: () => ({ mutateAsync: axleMock, isPending: false }),
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

// Miles, so the odometer round trip below runs through a real conversion.
vi.mock('../../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: 'imperial',
    showBoth: false,
    gallonStandard: 'us',
    units: {
      distance: 'mi',
      speed: 'mph',
      length: 'ft',
      volume: 'gal_us',
      consumption: 'mpg_us',
      pressure: 'psi',
      temperature: 'f',
      mass: 'lb',
      torque: 'lbft',
      tread: 'in32',
      secondary_gallon: 'us',
    },
  }),
}))

import BrakeList from '../BrakeList'
import { formatDateForDisplay } from '../../../utils/dateUtils'

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
    measurements: [],
    jobs: [],
    ...extra,
  }
}

function overview(corners: Partial<Record<BrakeCorner['position'], Partial<BrakeCorner>>> = {}): BrakeOverview {
  return {
    usage_axis: 'distance',
    tracks_distance: true,
    tracks_hours: false,
    axles: [
      { axle: 'front', brake_type: 'disc', min_thickness_mm: '3.00', new_thickness_mm: '10.00', configured: false, due_soon_mm: '4.75' },
      { axle: 'rear', brake_type: 'drum', min_thickness_mm: '1.50', new_thickness_mm: '5.00', drum_max_mm: '230.00', configured: true, due_soon_mm: '2.38' },
    ],
    corners: (['FL', 'FR', 'RL', 'RR'] as const).map((p) => corner(p, corners[p])),
  }
}

const field = (id: string): HTMLInputElement => {
  const el = document.getElementById(id)
  if (!(el instanceof HTMLInputElement)) throw new Error(`no input #${id}`)
  return el
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('BrakeList', () => {
  it('groups the four corners by axle and shows each condition', () => {
    useBrakesMock.mockReturnValue({
      data: overview({
        FL: {
          condition: 'due_soon',
          wear_status: 'projected',
          inner_pad_mm: '4.20',
          outer_pad_mm: '6.00',
          thinnest_mm: '4.20',
          projected_usage_remaining: '60000.0',
          measured_on: '2026-09-04',
          measured_odometer_km: '80467.20',
          inner_pad_measured_on: '2026-04-01',
          outer_pad_measured_on: '2026-09-04',
        },
        FR: { condition: 'ok', wear_status: 'insufficient_measurements', inner_pad_mm: '8.00', thinnest_mm: '8.00' },
        RL: { condition: 'replace_now', wear_status: 'at_or_below_minimum', shoe_mm: '1.20', thinnest_mm: '1.20' },
      }),
      isLoading: false,
      error: null,
    })
    render(<BrakeList vin={VIN} />)

    expect(screen.getByText('brakes.frontAxle')).toBeInTheDocument()
    expect(screen.getByText('brakes.rearAxle')).toBeInTheDocument()
    expect(screen.getByText('brakes.condition.dueSoon')).toBeInTheDocument()
    expect(screen.getByText('brakes.condition.oneMeasurement')).toBeInTheDocument()
    expect(screen.getByText('brakes.condition.replaceNow')).toBeInTheDocument()
    expect(screen.getByText('brakes.condition.unknown')).toBeInTheDocument()

    // Distances come through the reader's unit: 60,000 km left and the
    // 50,000 mi odometer, never kilometres beside a miles odometer field.
    expect(screen.getByText('~37,282 mi')).toBeInTheDocument()
    expect(screen.getByText(/@ 50,000 mi/)).toBeInTheDocument()

    // The inner pad's figure is April's, carried past an outer-only check: it says so.
    expect(screen.getByText('brakes.carriedPad')).toBeInTheDocument()

    // Pads read against the new thickness: 4.2 of 10 mm, in the band.
    const meters = screen.getAllByRole('progressbar')
    const inner = meters.find((m) => m.getAttribute('aria-valuenow') === '42')
    expect(inner).toBeDefined()
    // The shoe at 1.2 of 5 mm is at or below the 1.5 mm minimum.
    expect(meters.some((m) => m.getAttribute('aria-valuenow') === '24')).toBe(true)
  })

  it('logs every corner that has a figure, in canonical units, and skips blank ones', () => {
    useBrakesMock.mockReturnValue({ data: overview(), isLoading: false, error: null })
    render(<BrakeList vin={VIN} />)
    fireEvent.click(screen.getByRole('button', { name: 'brakes.logMeasurements' }))

    fireEvent.change(field('brake-log-date'), { target: { value: '2026-10-01' } })
    fireEvent.change(field('brake-log-odometer'), { target: { value: '30000' } })
    fireEvent.change(field('brake-log-FL-inner_pad_mm'), { target: { value: '6.5' } })
    fireEvent.change(field('brake-log-FL-outer_pad_mm'), { target: { value: '7' } })
    fireEvent.change(field('brake-log-RR-shoe_mm'), { target: { value: '3.1' } })
    // A drum corner has no pad fields at all.
    expect(document.getElementById('brake-log-RL-inner_pad_mm')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'common:save' }))

    expect(logMock).toHaveBeenCalledTimes(1)
    const payload = logMock.mock.calls[0][0]
    expect(payload.recorded_at).toBe('2026-10-01')
    expect(payload.odometer_km).toBeCloseTo(48280.32, 2)
    expect(payload.corners).toEqual([
      { position: 'FL', inner_pad_mm: 6.5, outer_pad_mm: 7 },
      { position: 'RR', shoe_mm: 3.1 },
    ])
  })

  it('does not send a batch with nothing in it', () => {
    useBrakesMock.mockReturnValue({ data: overview(), isLoading: false, error: null })
    render(<BrakeList vin={VIN} />)
    fireEvent.click(screen.getByRole('button', { name: 'brakes.logMeasurements' }))
    fireEvent.click(screen.getByRole('button', { name: 'common:save' }))
    expect(logMock).not.toHaveBeenCalled()
  })

  it('a brake job from a card covers its axle and carries the new pad thickness', () => {
    useBrakesMock.mockReturnValue({ data: overview(), isLoading: false, error: null })
    render(<BrakeList vin={VIN} />)
    const card = screen.getAllByRole('button', { name: 'brakes.historyOpen' })[0].closest('.relative') as HTMLElement
    fireEvent.click(within(card).getByRole('button', { name: 'brakes.brakeJob' }))

    fireEvent.change(field('brake-job-new-front'), { target: { value: '11' } })
    fireEvent.click(screen.getByRole('button', { name: 'brakes.surfaceResurfaced' }))
    fireEvent.click(screen.getByRole('button', { name: 'common:save' }))

    expect(jobMock).toHaveBeenCalledTimes(1)
    const payload = jobMock.mock.calls[0][0]
    expect(payload.friction_replaced).toBe(true)
    expect(payload.surface).toBe('resurfaced')
    expect(payload.corners).toEqual([
      { position: 'FL', new_thickness_mm: 11 },
      { position: 'FR', new_thickness_mm: 11 },
    ])
  })

  it('axle setup saves the axle that changed, starting from its new type’s defaults', async () => {
    axleMock.mockResolvedValue({})
    useBrakesMock.mockReturnValue({ data: overview(), isLoading: false, error: null })
    render(<BrakeList vin={VIN} />)
    fireEvent.click(screen.getByRole('button', { name: 'brakes.axleSetup' }))

    // Front axle: disc to drum.
    const drumChips = screen.getAllByRole('button', { name: 'brakes.drum' })
    fireEvent.click(drumChips[0])
    expect(field('brake-setup-front-min').value).toBe('1.5')
    expect(field('brake-setup-front-new').value).toBe('5')
    fireEvent.click(screen.getByRole('button', { name: 'common:save' }))

    await vi.waitFor(() => expect(axleMock).toHaveBeenCalledTimes(1))
    expect(axleMock.mock.calls[0][0]).toEqual({
      axle: 'front',
      brake_type: 'drum',
      min_thickness_mm: 1.5,
      new_thickness_mm: 5,
      rotor_min_mm: null,
      drum_max_mm: null,
    })
  })

  it('axle setup writes nothing when nothing changed', async () => {
    useBrakesMock.mockReturnValue({ data: overview(), isLoading: false, error: null })
    render(<BrakeList vin={VIN} />)
    fireEvent.click(screen.getByRole('button', { name: 'brakes.axleSetup' }))
    fireEvent.click(screen.getByRole('button', { name: 'common:save' }))
    await Promise.resolve()
    expect(axleMock).not.toHaveBeenCalled()
  })

  it('says which measurement needs an odometer', () => {
    useBrakesMock.mockReturnValue({
      data: overview({
        // The newest has one; the earlier ones don't.
        FL: { condition: 'ok', wear_status: 'no_usage_figures', inner_pad_mm: '8.00', thinnest_mm: '8.00', measured_on: '2026-09-04', measured_odometer_km: '1000.00' },
        // The newest has none.
        FR: { condition: 'ok', wear_status: 'no_usage_figures', inner_pad_mm: '8.00', thinnest_mm: '8.00', measured_on: '2026-09-04', reading_needed_on: '2026-09-04' },
      }),
      isLoading: false,
      error: null,
    })
    render(<BrakeList vin={VIN} />)
    expect(screen.getByText('brakes.wear.needsEarlierOdometer')).toBeInTheDocument()
    expect(screen.getByText('brakes.wear.needsOdometer')).toBeInTheDocument()
  })

  it('names an older measurement when that is the one without an odometer', () => {
    useBrakesMock.mockReturnValue({
      data: overview({
        // The thin inner pad was last read in April; June read the outer one.
        FL: { condition: 'ok', wear_status: 'no_usage_figures', inner_pad_mm: '5.00', outer_pad_mm: '6.00', thinnest_mm: '5.00', measured_on: '2026-06-01', measured_odometer_km: '30000.00', reading_needed_on: '2026-04-01' },
      }),
      isLoading: false,
      error: null,
    })
    render(<BrakeList vin={VIN} />)
    expect(screen.getByText('brakes.wear.needsOdometerOn')).toBeInTheDocument()
    expect(screen.queryByText('brakes.wear.needsOdometer')).not.toBeInTheDocument()
  })

  it('shows the date alone when the estimate has no distance', () => {
    useBrakesMock.mockReturnValue({
      data: overview({
        FL: { condition: 'due_soon', wear_status: 'projected', inner_pad_mm: '6.00', thinnest_mm: '6.00', projected_wear_date: '2026-06-07' },
      }),
      isLoading: false,
      error: null,
    })
    render(<BrakeList vin={VIN} />)
    expect(screen.getByText(formatDateForDisplay('2026-06-07'))).toBeInTheDocument()
  })

  it('opens Log measurements straight away when sent from the Tires page', () => {
    useBrakesMock.mockReturnValue({ data: overview(), isLoading: false, error: null })
    const opened = vi.fn()
    render(<BrakeList vin={VIN} logOnOpen onLogOpened={opened} />)
    expect(screen.getByText('brakes.logTitle')).toBeInTheDocument()
    expect(opened).toHaveBeenCalledTimes(1)
  })
})
