import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import type { BrakeCorner, BrakeOverview } from '../../../types/brake'

const updateMeasurementMock = vi.fn()
const updateJobMock = vi.fn()
const deleteMeasurementMock = vi.fn()
const deleteJobMock = vi.fn()

vi.mock('../../../hooks/queries/useBrakes', () => ({
  useUpdateBrakeMeasurement: () => ({ mutate: updateMeasurementMock, isPending: false }),
  useUpdateBrakeJob: () => ({ mutate: updateJobMock, isPending: false }),
  useDeleteBrakeMeasurement: () => ({ mutate: deleteMeasurementMock, isPending: false }),
  useDeleteBrakeJob: () => ({ mutate: deleteJobMock, isPending: false }),
}))
vi.mock('../../../hooks/queries/useOdometerRecords', () => ({
  useNearestOdometer: () => ({ data: undefined, isSuccess: false }),
}))
vi.mock('../../../hooks/queries/useHoursRecords', () => ({
  useNearestHours: () => ({ data: undefined, isSuccess: false }),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../../../hooks/useUnitPreference', () => {
  // UnitSession reads the account half too; same answer, nothing to pin here.
  const unitPreference = () => ({
    system: 'metric',
    showBoth: false,
    gallonStandard: 'us',
    units: {
      distance: 'km',
      speed: 'kmh',
      length: 'm',
      volume: 'L',
      consumption: 'l_100km',
      pressure: 'kpa',
      temperature: 'c',
      mass: 'kg',
      torque: 'nm',
      tread: 'mm',
      secondary_gallon: 'us',
    },
  })
  return {
    useUnitPreference: unitPreference,
    useAccountUnitPreference: unitPreference,
  }
})

import BrakeHistoryDrawer from '../BrakeHistoryDrawer'
import { JobEditor, MeasurementEditor } from '../BrakeEditors'
import { answerConfirm, escapeConfirm, withConfirm } from '../../../__tests__/confirmHelpers'

const VIN = '1HGCM82633A004352'

const JOB = {
  id: 7,
  position: 'FL' as const,
  brake_type: 'disc' as const,
  performed_on: '2026-09-10',
  odometer_km: '47000.00',
  friction_replaced: true,
  surface: 'resurfaced' as const,
}
const NEW_PADS = {
  id: 11,
  position: 'FL' as const,
  recorded_at: '2026-09-10',
  odometer_km: '47000.00',
  inner_pad_mm: '10.00',
  outer_pad_mm: '10.00',
  brake_job_id: 7,
}
const OLD_PADS = {
  id: 10,
  position: 'FL' as const,
  recorded_at: '2026-09-10',
  odometer_km: '47000.00',
  inner_pad_mm: '2.50',
}

const OVERVIEW: BrakeOverview = {
  usage_axis: 'distance',
  tracks_distance: true,
  tracks_hours: false,
  axles: [],
  corners: [],
  wheel_layout: 'four',
}

const CORNER: BrakeCorner = {
  position: 'FL',
  axle: 'front',
  brake_type: 'disc',
  condition: 'ok',
  wear_status: 'insufficient_measurements',
  surface_past_limit: false,
  on_layout: true,
  jobs: [JOB],
  measurements: [NEW_PADS, OLD_PADS],
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('BrakeHistoryDrawer', () => {
  it('lists the day of a brake job newest first: the new pads, the job, then the old pads', () => {
    render(
      <BrakeHistoryDrawer
        vin={VIN}
        overview={OVERVIEW}
        corner={CORNER}
        open
        onClose={vi.fn()}
        onEditMeasurement={vi.fn()}
        onEditJob={vi.fn()}
      />,
      { wrapper: withConfirm },
    )
    const text = document.body.textContent ?? ''
    const newPads = text.indexOf('brakes.newPartsBadge')
    const job = text.indexOf('brakes.padsReplaced')
    const oldPads = text.lastIndexOf('brakes.figureInner')
    expect(newPads).toBeGreaterThan(-1)
    expect(newPads).toBeLessThan(job)
    expect(job).toBeLessThan(oldPads)
  })

  it('deletes only after a confirm', async () => {
    render(
      <BrakeHistoryDrawer
        vin={VIN}
        overview={OVERVIEW}
        corner={CORNER}
        open
        onClose={vi.fn()}
        onEditMeasurement={vi.fn()}
        onEditJob={vi.fn()}
      />,
      { wrapper: withConfirm },
    )
    const deletes = screen.getAllByRole('button', { name: 'common:delete' })
    fireEvent.click(deletes[0])
    await answerConfirm('cancel', 'brakes.confirmDeleteMeasurement')
    expect(deleteMeasurementMock).not.toHaveBeenCalled()
    fireEvent.click(deletes[0])
    await answerConfirm('confirm', 'brakes.confirmDeleteMeasurement')
    expect(deleteMeasurementMock).toHaveBeenCalledWith(11, expect.anything())
  })

  // Regression pin: Escape on the confirm must not close the drawer under it.
  it('Escape closes the delete confirm and leaves the drawer open', async () => {
    const onClose = vi.fn()
    render(
      <BrakeHistoryDrawer
        vin={VIN}
        overview={OVERVIEW}
        corner={CORNER}
        open
        onClose={onClose}
        onEditMeasurement={vi.fn()}
        onEditJob={vi.fn()}
      />,
      { wrapper: withConfirm },
    )
    fireEvent.click(screen.getAllByRole('button', { name: 'common:delete' })[0])
    await escapeConfirm('brakes.confirmDeleteMeasurement')
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog', { name: 'brakes.historyTitle' })).toBeInTheDocument()
    expect(deleteMeasurementMock).not.toHaveBeenCalled()
  })
})

describe('MeasurementEditor', () => {
  it('a measurement a job wrote sends its figures only, never a date or odometer', () => {
    render(
      <MeasurementEditor vin={VIN} overview={OVERVIEW} measurement={NEW_PADS} brakeType="disc" open onClose={vi.fn()} />,
      { wrapper: withConfirm },
    )
    expect(document.getElementById('brake-measurement-edit-date')).toBeNull()
    fireEvent.change(document.getElementById('brake-measurement-edit-inner_pad_mm') as HTMLInputElement, {
      target: { value: '11' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'common:save' }))
    const payload = updateMeasurementMock.mock.calls[0][0]
    expect(payload).toMatchObject({ id: 11, inner_pad_mm: 11, outer_pad_mm: 10, rotor_mm: null })
    expect(payload).not.toHaveProperty('recorded_at')
    expect(payload).not.toHaveProperty('odometer_km')
  })

  it('an ordinary measurement sends its date and odometer back', () => {
    render(
      <MeasurementEditor vin={VIN} overview={OVERVIEW} measurement={OLD_PADS} brakeType="disc" open onClose={vi.fn()} />,
      { wrapper: withConfirm },
    )
    fireEvent.click(screen.getByRole('button', { name: 'common:save' }))
    expect(updateMeasurementMock.mock.calls[0][0]).toMatchObject({
      id: 10,
      recorded_at: '2026-09-10',
      odometer_km: 47000,
      inner_pad_mm: 2.5,
      outer_pad_mm: null,
    })
  })

  it('a blank wire figure seeds a blank field and saves as null, not 0', () => {
    render(
      <MeasurementEditor
        vin={VIN}
        overview={OVERVIEW}
        measurement={{ ...OLD_PADS, outer_pad_mm: '' }}
        brakeType="disc"
        open
        onClose={vi.fn()}
      />,
      { wrapper: withConfirm },
    )
    expect((document.getElementById('brake-measurement-edit-outer_pad_mm') as HTMLInputElement).value).toBe('')
    fireEvent.click(screen.getByRole('button', { name: 'common:save' }))
    expect(updateMeasurementMock.mock.calls[0][0]).toMatchObject({ id: 10, inner_pad_mm: 2.5, outer_pad_mm: null })
  })
})

describe('JobEditor', () => {
  it('refuses a job that does nothing', () => {
    render(<JobEditor vin={VIN} overview={OVERVIEW} job={JOB} open onClose={vi.fn()} />, { wrapper: withConfirm })
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: 'brakes.surfaceNone' }))
    fireEvent.click(screen.getByRole('button', { name: 'common:save' }))
    expect(updateJobMock).not.toHaveBeenCalled()
  })

  it('sends the corrected job', () => {
    render(<JobEditor vin={VIN} overview={OVERVIEW} job={JOB} open onClose={vi.fn()} />, { wrapper: withConfirm })
    fireEvent.click(screen.getByRole('button', { name: 'brakes.surfaceReplaced' }))
    fireEvent.click(screen.getByRole('button', { name: 'common:save' }))
    expect(updateJobMock.mock.calls[0][0]).toMatchObject({
      id: 7,
      performed_on: '2026-09-10',
      friction_replaced: true,
      surface: 'replaced',
      odometer_km: 47000,
    })
  })
})
