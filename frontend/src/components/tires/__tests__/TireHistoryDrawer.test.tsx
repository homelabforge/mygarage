import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'

const useDeleteReadingMock = vi.fn()
vi.mock('../../../hooks/queries/useTires', () => ({
  useDeleteTireReading: () => useDeleteReadingMock(),
}))

const getActionErrorMessageMock = vi.fn()
vi.mock('../../../utils/httpErrorHandler', () => ({
  getActionErrorMessage: (...args: unknown[]) => getActionErrorMessageMock(...args),
}))

const toastSuccess = vi.fn()
const toastError = vi.fn()
vi.mock('sonner', () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}))

vi.mock('../../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: 'metric',
    showBoth: false,
    gallonStandard: 'us',
    units: {
      consumption: 'l_100km',
      distance: 'km',
      length: 'm',
      mass: 'kg',
      pressure: 'kpa',
      secondary_gallon: 'us',
      speed: 'kmh',
      temperature: 'c',
      torque: 'nm',
      tread: 'mm',
      volume: 'L',
    },
  }),
}))

import TireHistoryDrawer, { needsFix, needsOdometer } from '../TireHistoryDrawer'

const VIN = '1HGCM82633A004352'
const labelFor = (p: string | null | undefined) => (p == null ? 'stored' : `pos-${p}`)

const ASSUMED = {
  id: 1,
  position: 'FL',
  mounted_on: null,
  dismounted_on: '2026-01-15',
  mounted_odometer_km: null,
  dismounted_odometer_km: '3000.00',
  is_assumed: true,
  observed_active_on: '2025-09-04',
  notes: null,
}
const OPEN = {
  id: 2,
  position: 'FL',
  mounted_on: '2026-01-15',
  dismounted_on: null,
  mounted_odometer_km: '3000.00',
  dismounted_odometer_km: null,
  is_assumed: false,
  observed_active_on: null,
  notes: 'winter set',
}
const tire = (overrides: Record<string, unknown> = {}) => ({
  id: 9,
  vin: VIN,
  position: 'FL',
  brand: 'Nokian',
  min_tread_mm: '2.0',
  below_threshold: false,
  installed_date: null,
  blocking_period_ids: [1],
  mount_periods: [ASSUMED, OPEN],
  readings: [],
  created_at: '2026-01-01T00:00:00',
  ...overrides,
})

const drawer = () => within(screen.getByRole('dialog'))

const mutate = vi.fn()
beforeEach(() => {
  mutate.mockReset()
  toastSuccess.mockReset()
  toastError.mockReset()
  useDeleteReadingMock.mockReturnValue({ mutate, isPending: false })
})
afterEach(() => {
  vi.restoreAllMocks()
})

describe('TireHistoryDrawer', () => {
  it('lists periods oldest first with the badges each one earns', () => {
    render(<TireHistoryDrawer tire={tire() as never} open onClose={vi.fn()} onEditPeriod={vi.fn()} onEditReading={vi.fn()} onAddPeriod={vi.fn()} labelFor={labelFor} vin={VIN} />)
    expect(drawer().getByText('tireList.firstInstalledUnknown')).toBeInTheDocument()
    const rows = drawer().getAllByTestId(/^period-/)
    expect(rows.map((r) => r.getAttribute('data-testid'))).toEqual(['period-1', 'period-2'])
    const first = within(rows[0])
    expect(first.getByText('tireList.periodRange')).toBeInTheDocument()
    expect(first.getByText('tireList.periodAssumed')).toBeInTheDocument()
    expect(first.getByText('tireList.periodNeedsOdometer')).toBeInTheDocument()
    const second = within(rows[1])
    expect(second.getByText('tireList.periodSince')).toBeInTheDocument()
    expect(second.queryByText('tireList.periodAssumed')).toBeNull()
    expect(second.queryByText(/tireList\.period(NeedsOdometer|Check)/)).toBeNull()
    expect(second.getByText('winter set')).toBeInTheDocument()
  })

  it('a fully bounded blocking period is a fault, not a gap', () => {
    const faulted = { ...OPEN, id: 3, dismounted_on: '2026-02-01', dismounted_odometer_km: '2500.00' }
    render(<TireHistoryDrawer tire={tire({ mount_periods: [faulted], blocking_period_ids: [3] }) as never} open onClose={vi.fn()} onEditPeriod={vi.fn()} onEditReading={vi.fn()} onAddPeriod={vi.fn()} labelFor={labelFor} vin={VIN} />)
    expect(drawer().getByText('tireList.periodCheck')).toBeInTheDocument()
    expect(needsOdometer(faulted as never)).toBe(false)
    expect(needsOdometer(ASSUMED as never)).toBe(true)
  })

  it('an open, blocking period with a known mount odometer needs no odometer', () => {
    // Pins the guard's actual job: a currently-mounted tire has no dismount
    // odometer yet by definition (it hasn't come off), and must never be
    // told to supply one just because some other property makes it a
    // blocker. `dismounted_on == null` short-circuits the guard before
    // `dismounted_odometer_km` is ever inspected.
    const openBlocking = { ...OPEN, id: 4 }
    expect(needsOdometer(openBlocking as never)).toBe(false)
  })

  it('a closed period missing its closing odometer needs one', () => {
    // Pins the branch's true outcome directly: a period that closed but
    // never recorded the odometer at that moment genuinely needs one.
    const closedMissingDismountOdometer = {
      ...OPEN,
      id: 5,
      dismounted_on: '2026-02-01',
      dismounted_odometer_km: null,
    }
    expect(needsOdometer(closedMissingDismountOdometer as never)).toBe(true)
  })

  it('names the first installation when it is known', () => {
    render(<TireHistoryDrawer tire={tire({ installed_date: '2024-11-02', mount_periods: [{ ...OPEN, mounted_on: '2024-11-02' }] }) as never} open onClose={vi.fn()} onEditPeriod={vi.fn()} onEditReading={vi.fn()} onAddPeriod={vi.fn()} labelFor={labelFor} vin={VIN} />)
    expect(drawer().getByText('tireList.firstInstalled')).toBeInTheDocument()
  })

  it('Edit hands the row\'s period to the caller', () => {
    const onEditPeriod = vi.fn()
    render(<TireHistoryDrawer tire={tire() as never} open onClose={vi.fn()} onEditPeriod={onEditPeriod} onEditReading={vi.fn()} onAddPeriod={vi.fn()} labelFor={labelFor} vin={VIN} />)
    fireEvent.click(within(drawer().getByTestId('period-2')).getByText('tireList.periodEdit'))
    expect(onEditPeriod).toHaveBeenCalledWith(expect.objectContaining({ id: 2 }))
  })

  it('Add past period calls the caller', () => {
    const onAddPeriod = vi.fn()
    render(<TireHistoryDrawer tire={tire() as never} open onClose={vi.fn()} onEditPeriod={vi.fn()} onEditReading={vi.fn()} onAddPeriod={onAddPeriod} labelFor={labelFor} vin={VIN} />)
    fireEvent.click(drawer().getByText('tireList.addPastPeriod'))
    expect(onAddPeriod).toHaveBeenCalledTimes(1)
  })

  describe('deleting a reading', () => {
    /* Newest first, as the server sends them. */
    const READINGS = [
      { id: 31, tire_id: 9, recorded_at: '2026-03-01', odometer_km: '150000.00', tread_depth_mm: '7.00', pressure_kpa: null, notes: null },
      { id: 30, tire_id: 9, recorded_at: '2026-01-10', odometer_km: '10500.00', tread_depth_mm: '8.00', pressure_kpa: null, notes: null },
    ]
    const renderWithReadings = () =>
      render(<TireHistoryDrawer tire={tire({ readings: READINGS }) as never} open onClose={vi.fn()} onEditPeriod={vi.fn()} onEditReading={vi.fn()} onAddPeriod={vi.fn()} labelFor={labelFor} vin={VIN} />)
    const deleteIn = (readingId: number) =>
      within(drawer().getByTestId(`reading-${readingId}`)).getByRole('button', { name: 'tireList.readingDeleteLabel' })

    it('sends the row\'s tire and reading ids once the confirm is accepted', () => {
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
      renderWithReadings()
      fireEvent.click(deleteIn(30))
      expect(confirmSpy).toHaveBeenCalledWith('tireList.readingConfirmDelete')
      expect(mutate).toHaveBeenCalledTimes(1)
      expect(mutate.mock.calls[0][0]).toEqual({ tireId: 9, readingId: 30 })
    })

    it('sends nothing when the confirm is declined', () => {
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
      renderWithReadings()
      fireEvent.click(deleteIn(31))
      expect(confirmSpy).toHaveBeenCalledTimes(1)
      expect(mutate).not.toHaveBeenCalled()
    })

    it('reads Delete and is disabled while a delete is in flight', () => {
      useDeleteReadingMock.mockReturnValue({ mutate, isPending: true })
      renderWithReadings()
      const button = deleteIn(31)
      expect(button).toHaveTextContent('common:delete')
      expect(button).toBeDisabled()
    })

    it("disables the row's Edit while a delete is in flight", () => {
      useDeleteReadingMock.mockReturnValue({ mutate, isPending: true })
      renderWithReadings()
      const edit = within(drawer().getByTestId('reading-31')).getByRole('button', { name: 'tireList.readingEditLabel' })
      expect(edit).toHaveTextContent('common:edit')
      expect(edit).toBeDisabled()
    })

    it('reports the outcome through the reading keys', () => {
      vi.spyOn(window, 'confirm').mockReturnValue(true)
      renderWithReadings()
      fireEvent.click(deleteIn(31))
      const callbacks = mutate.mock.calls[0][1]
      callbacks.onSuccess()
      expect(toastSuccess).toHaveBeenCalledWith('tireList.readingDeleted')
      const failure = new Error('boom')
      getActionErrorMessageMock.mockReturnValue('the sentence the user reads')
      callbacks.onError(failure)
      expect(getActionErrorMessageMock).toHaveBeenCalledWith(failure, 'tireList.readingDeleteAction')
      expect(toastError).toHaveBeenCalledWith('the sentence the user reads')
    })
  })

  it("hands the row's own reading to onEditReading, and sends no delete", () => {
    const onEditReading = vi.fn()
    const readings = [
      { id: 31, tire_id: 9, recorded_at: '2026-03-01', odometer_km: null, tread_depth_mm: '7.00', pressure_kpa: null, notes: null },
      { id: 30, tire_id: 9, recorded_at: '2026-01-10', odometer_km: null, tread_depth_mm: '8.00', pressure_kpa: null, notes: null },
    ]
    render(<TireHistoryDrawer tire={tire({ readings }) as never} open onClose={vi.fn()} onEditPeriod={vi.fn()} onEditReading={onEditReading} onAddPeriod={vi.fn()} labelFor={labelFor} vin={VIN} />)
    const edit = within(drawer().getByTestId('reading-30')).getByRole('button', { name: 'tireList.readingEditLabel' })
    expect(edit).toHaveTextContent('common:edit')
    expect(onEditReading).not.toHaveBeenCalled()
    fireEvent.click(edit)
    expect(onEditReading).toHaveBeenCalledTimes(1)
    expect(onEditReading.mock.calls[0][0]).toMatchObject({ id: 30, recorded_at: '2026-01-10' })
    expect(mutate).not.toHaveBeenCalled()
  })

  it('badges both periods of a contradiction and shows the reason beneath each', () => {
    const fault = { period_id: 1, code: 'overlapping_dates', counterpart_id: 2, message: 'M' }
    render(
      <TireHistoryDrawer
        tire={tire({ blocking_period_ids: [], history_faults: [fault] }) as never}
        open
        onClose={vi.fn()}
        onEditPeriod={vi.fn()}
        onEditReading={vi.fn()}
        onAddPeriod={vi.fn()}
        labelFor={labelFor}
        vin={VIN}
      />
    )
    const first = within(drawer().getByTestId('period-1'))
    const second = within(drawer().getByTestId('period-2'))
    expect(first.getByText('tireList.periodCheck')).toBeInTheDocument()
    expect(second.getByText('tireList.periodCheck')).toBeInTheDocument()
    expect(first.getByTestId('period-1-fault')).toHaveTextContent('M')
    expect(second.getByTestId('period-2-fault')).toHaveTextContent('M')
  })

  it('asks for an odometer only when a blocking period lacks one; a contradiction alone asks for a check', () => {
    // Period 1 has no mount odometer either way. Flagged only by a
    // contradiction, adding an odometer is not the repair, so it reads "check".
    const fault = { period_id: 1, code: 'overlapping_dates', counterpart_id: 2, message: 'M' }
    const { unmount } = render(
      <TireHistoryDrawer
        tire={tire({ blocking_period_ids: [], history_faults: [fault] }) as never}
        open
        onClose={vi.fn()}
        onEditPeriod={vi.fn()}
        onEditReading={vi.fn()}
        onAddPeriod={vi.fn()}
        labelFor={labelFor}
        vin={VIN}
      />
    )
    const faultOnly = within(drawer().getByTestId('period-1'))
    expect(faultOnly.getByText('tireList.periodCheck')).toBeInTheDocument()
    expect(faultOnly.queryByText('tireList.periodNeedsOdometer')).toBeNull()
    unmount()

    render(
      <TireHistoryDrawer
        tire={tire({ blocking_period_ids: [1], history_faults: [fault] }) as never}
        open
        onClose={vi.fn()}
        onEditPeriod={vi.fn()}
        onEditReading={vi.fn()}
        onAddPeriod={vi.fn()}
        labelFor={labelFor}
        vin={VIN}
      />
    )
    const blocking = within(drawer().getByTestId('period-1'))
    expect(blocking.getByText('tireList.periodNeedsOdometer')).toBeInTheDocument()
    expect(blocking.queryByText('tireList.periodCheck')).toBeNull()
  })

  it('shows only the first reason when several contradictions name one period', () => {
    const faults = [
      { period_id: 2, code: 'overlapping_dates', counterpart_id: 1, message: 'first reason' },
      { period_id: 2, code: 'contradicts_reading', counterpart_id: null, message: 'second reason' },
    ]
    render(
      <TireHistoryDrawer
        tire={tire({ blocking_period_ids: [], history_faults: faults }) as never}
        open
        onClose={vi.fn()}
        onEditPeriod={vi.fn()}
        onEditReading={vi.fn()}
        onAddPeriod={vi.fn()}
        labelFor={labelFor}
        vin={VIN}
      />
    )
    expect(drawer().getByTestId('period-2-fault')).toHaveTextContent(/^first reason$/)
    expect(drawer().getByTestId('period-1-fault')).toHaveTextContent(/^first reason$/)
  })

  it('needsFix is true from history_faults alone, true from blocking alone, false from neither', () => {
    expect(
      needsFix(
        tire({
          blocking_period_ids: [],
          history_faults: [{ period_id: 1, code: 'x', counterpart_id: null, message: 'M' }],
        }) as never
      )
    ).toBe(true)
    expect(needsFix(tire({ blocking_period_ids: [1], history_faults: [] }) as never)).toBe(true)
    expect(needsFix(tire({ blocking_period_ids: [], history_faults: [] }) as never)).toBe(false)
  })

  it('still shows the mount history section, with Add past period, when there is nothing recorded yet', () => {
    // A tire never mounted in MyGarage is the feature's main user: no periods
    // and no readings must not hide the one control that can add either.
    render(<TireHistoryDrawer tire={tire({ mount_periods: [], readings: [], blocking_period_ids: [] }) as never} open onClose={vi.fn()} onEditPeriod={vi.fn()} onEditReading={vi.fn()} onAddPeriod={vi.fn()} labelFor={labelFor} vin={VIN} />)
    expect(drawer().getByText('tireList.addPastPeriod')).toBeInTheDocument()
    expect(drawer().getByText('tireList.historyNoPeriods')).toBeInTheDocument()
    expect(drawer().getByText('tireList.historyEmpty')).toBeInTheDocument()
  })

  it('Add past period is reachable even with no history at all', () => {
    const onAddPeriod = vi.fn()
    render(<TireHistoryDrawer tire={tire({ mount_periods: [], readings: [], blocking_period_ids: [] }) as never} open onClose={vi.fn()} onEditPeriod={vi.fn()} onEditReading={vi.fn()} onAddPeriod={onAddPeriod} labelFor={labelFor} vin={VIN} />)
    fireEvent.click(drawer().getByText('tireList.addPastPeriod'))
    expect(onAddPeriod).toHaveBeenCalledTimes(1)
  })
})
