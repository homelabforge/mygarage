import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '../../__tests__/test-utils'
import { fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Reminder } from '../../types/reminder'

// Task 15 — ReminderForm engine-hours usage tracking. Mirrors
// ServiceVisitForm.hours coverage (Task 14, commit 10993e6): an hours-tracking
// vehicle offers the `hours` reminder type (not mileage/both), a
// distance-tracking vehicle offers mileage (not hours), a dual vehicle offers
// both dimensions. `smart` targets the vehicle's PRIMARY dimension
// (getUsageTracking(...).primary) so the backend's exactly-one-of
// {due_mileage_km, due_hours} rule is never violated.
//
// Task 15 (revised, parity fix) — the hours field is interval-based, mirroring
// the mileage field exactly: with a currentHours baseline it's "engine-hours
// until due" (due_hours = currentHours + interval); with none, the entered
// value is the absolute target verbatim (same fallback as mileage without a
// currentMileage baseline).

const createMock = vi.fn().mockResolvedValue({})
const updateMock = vi.fn().mockResolvedValue({})
vi.mock('../../hooks/useReminders', () => ({
  useCreateReminder: () => ({ mutateAsync: createMock }),
  useUpdateReminder: () => ({ mutateAsync: updateMock }),
}))
// Metric throughout — the mileage-comparison tests below assert the raw
// entered value passes straight through un-converted (toCanonicalKm is a
// no-op under metric), keeping the numbers exact without deriving
// mi->km conversion constants.
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({ system: 'metric', showBoth: false }),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const mockedApiGet = vi.fn()
vi.mock('../../services/api', () => ({
  default: { get: (...args: unknown[]) => mockedApiGet(...args) },
}))

import ReminderForm from '../ReminderForm'

const DEFAULT_PROPS = { vin: 'V1', onClose: vi.fn(), onSuccess: vi.fn() }

const typeButton = (labelKey: string): HTMLElement =>
  screen.getByText(labelKey).closest('button') as HTMLElement

beforeEach(() => {
  vi.clearAllMocks()
  createMock.mockResolvedValue({})
  updateMock.mockResolvedValue({})
})

describe('ReminderForm — reminder-type options filtered by usage tracking (Task 15)', () => {
  it('an hours-only vehicle offers hours, but NOT mileage/both', async () => {
    mockedApiGet.mockResolvedValue({ data: { usage_unit: 'hours', secondary_usage_enabled: false } })
    render(<ReminderForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(screen.getByText('reminderForm.typeHours')).toBeInTheDocument())

    expect(screen.getByText('reminderForm.typeDate')).toBeInTheDocument()
    expect(screen.getByText('reminderForm.typeSmart')).toBeInTheDocument()
    expect(screen.queryByText('reminderForm.typeMileage')).not.toBeInTheDocument()
    expect(screen.queryByText('reminderForm.typeBoth')).not.toBeInTheDocument()
  })

  it('a distance-tracking vehicle offers mileage, but NOT hours', async () => {
    mockedApiGet.mockResolvedValue({ data: { usage_unit: 'distance', secondary_usage_enabled: false } })
    render(<ReminderForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())

    expect(screen.getByText('reminderForm.typeMileage')).toBeInTheDocument()
    expect(screen.getByText('reminderForm.typeBoth')).toBeInTheDocument()
    expect(screen.queryByText('reminderForm.typeHours')).not.toBeInTheDocument()
  })

  it('a dual-tracking vehicle offers mileage AND hours (plus date/both/smart)', async () => {
    mockedApiGet.mockResolvedValue({ data: { usage_unit: 'distance', secondary_usage_enabled: true } })
    render(<ReminderForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(screen.getByText('reminderForm.typeHours')).toBeInTheDocument())

    expect(screen.getByText('reminderForm.typeMileage')).toBeInTheDocument()
    expect(screen.getByText('reminderForm.typeBoth')).toBeInTheDocument()
    expect(screen.getByText('reminderForm.typeDate')).toBeInTheDocument()
    expect(screen.getByText('reminderForm.typeSmart')).toBeInTheDocument()
  })

  it('defaults to the distance-tracking option set before the vehicle fetch resolves (no flash of the wrong options)', () => {
    mockedApiGet.mockReturnValue(new Promise(() => {})) // never resolves
    render(<ReminderForm {...DEFAULT_PROPS} />)

    expect(screen.getByText('reminderForm.typeMileage')).toBeInTheDocument()
    expect(screen.queryByText('reminderForm.typeHours')).not.toBeInTheDocument()
  })
})

describe('ReminderForm — hours reminder type (Task 15)', () => {
  beforeEach(() => {
    mockedApiGet.mockResolvedValue({ data: { usage_unit: 'hours', secondary_usage_enabled: false } })
  })

  it('selecting hours shows the hours-target input', async () => {
    render(<ReminderForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(screen.getByText('reminderForm.typeHours')).toBeInTheDocument())

    fireEvent.click(typeButton('reminderForm.typeHours'))
    expect(screen.getByLabelText('reminder.dueHours * (hr)')).toBeInTheDocument()
  })

  it('with no currentHours baseline, the entered value is submitted verbatim as the absolute due_hours target (fails if either field is mis-wired)', async () => {
    const user = userEvent.setup()
    render(<ReminderForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(screen.getByText('reminderForm.typeHours')).toBeInTheDocument())

    await user.type(screen.getByLabelText('common:title *'), 'Hydraulic service')
    fireEvent.click(typeButton('reminderForm.typeHours'))
    fireEvent.change(screen.getByLabelText('reminder.dueHours * (hr)'), { target: { value: '850' } })
    fireEvent.click(screen.getByRole('button', { name: 'common:create' }))

    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1))
    expect(createMock.mock.calls[0][0]).toStrictEqual({
      title: 'Hydraulic service', reminder_type: 'hours', due_date: undefined,
      due_mileage_km: undefined, due_hours: 850, notes: undefined,
    })
  })

  it('with a currentHours baseline, the entered value is an INTERVAL added to currentHours to produce due_hours (mirrors the mileage currentMileage + interval math, Task 15 parity fix)', async () => {
    const user = userEvent.setup()
    render(<ReminderForm {...DEFAULT_PROPS} currentHours={100} />)
    await waitFor(() => expect(screen.getByText('reminderForm.typeHours')).toBeInTheDocument())

    await user.type(screen.getByLabelText('common:title *'), 'Hydraulic service')
    fireEvent.click(typeButton('reminderForm.typeHours'))
    // label switches to the "until due" interval wording once a baseline exists
    expect(screen.getByLabelText('reminder.hoursUntilDue * (hr)')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('reminder.hoursUntilDue * (hr)'), { target: { value: '50' } })
    fireEvent.click(screen.getByRole('button', { name: 'common:create' }))

    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1))
    expect(createMock.mock.calls[0][0]).toStrictEqual({
      title: 'Hydraulic service', reminder_type: 'hours', due_date: undefined,
      due_mileage_km: undefined, due_hours: 150, notes: undefined,
    })
  })

  it('validation: hours type with no target blocks submit (fails if the required guard is dropped)', async () => {
    const user = userEvent.setup()
    render(<ReminderForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(screen.getByText('reminderForm.typeHours')).toBeInTheDocument())

    await user.type(screen.getByLabelText('common:title *'), 'Hydraulic service')
    fireEvent.click(typeButton('reminderForm.typeHours'))
    fireEvent.click(screen.getByRole('button', { name: 'common:create' }))

    expect(screen.getByText('reminder.hoursRequired')).toBeInTheDocument()
    expect(createMock).not.toHaveBeenCalled()
  })

  it('with no currentHours baseline, edit prefills due_hours verbatim (absolute target === the field value)', async () => {
    const reminder = {
      id: 5, vin: 'V1', title: 'Hydraulic service', reminder_type: 'hours', status: 'pending',
      due_date: null, due_mileage_km: null, due_hours: '640.5', estimated_due_date: null, notes: null,
      line_item_id: null, last_notified_at: null,
      created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    } as unknown as Reminder
    render(<ReminderForm {...DEFAULT_PROPS} reminder={reminder} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())

    expect((screen.getByLabelText('reminder.dueHours * (hr)') as HTMLInputElement).value).toBe('640.5')
  })

  it('with a currentHours baseline, edit prefills the REMAINING interval — not the absolute due_hours target (mirrors the mileage edit-prefill reverse computation, Task 15 parity fix)', async () => {
    const reminder = {
      id: 5, vin: 'V1', title: 'Hydraulic service', reminder_type: 'hours', status: 'pending',
      due_date: null, due_mileage_km: null, due_hours: '150', estimated_due_date: null, notes: null,
      line_item_id: null, last_notified_at: null,
      created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    } as unknown as Reminder
    render(<ReminderForm {...DEFAULT_PROPS} reminder={reminder} currentHours={100} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())

    // remaining interval = due_hours(150) - currentHours(100) = 50, NOT the absolute 150
    expect((screen.getByLabelText('reminder.hoursUntilDue * (hr)') as HTMLInputElement).value).toBe('50')
  })
})

describe('ReminderForm — smart reminders target the vehicle PRIMARY dimension (Task 15)', () => {
  it('smart on an hours-primary vehicle collects date + hours and submits due_date + due_hours (no mileage)', async () => {
    mockedApiGet.mockResolvedValue({ data: { usage_unit: 'hours', secondary_usage_enabled: false } })
    const user = userEvent.setup()
    render(<ReminderForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(screen.getByText('reminderForm.typeSmart')).toBeInTheDocument())

    await user.type(screen.getByLabelText('common:title *'), 'Hydraulic service')
    fireEvent.click(typeButton('reminderForm.typeSmart'))
    fireEvent.change(screen.getByLabelText('reminder.dueDate *'), { target: { value: '2026-12-01' } })
    expect(screen.getByLabelText('reminder.dueHours * (hr)')).toBeInTheDocument()
    expect(screen.queryByLabelText(/reminder\.dueMileage|reminder\.milesUntilDue/)).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('reminder.dueHours * (hr)'), { target: { value: '900' } })
    fireEvent.click(screen.getByRole('button', { name: 'common:create' }))

    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1))
    expect(createMock.mock.calls[0][0]).toStrictEqual({
      title: 'Hydraulic service', reminder_type: 'smart', due_date: '2026-12-01',
      due_mileage_km: undefined, due_hours: 900, notes: undefined,
    })
  })

  it('smart on a distance-only vehicle is unchanged: date + mileage, due_hours stays undefined', async () => {
    mockedApiGet.mockResolvedValue({ data: { usage_unit: 'distance', secondary_usage_enabled: false } })
    const user = userEvent.setup()
    render(<ReminderForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())

    await user.type(screen.getByLabelText('common:title *'), 'Oil change')
    fireEvent.click(typeButton('reminderForm.typeSmart'))
    fireEvent.change(screen.getByLabelText('reminder.dueDate *'), { target: { value: '2026-12-01' } })
    expect(screen.queryByLabelText('reminder.dueHours * (hr)')).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('reminder.dueMileage * (km)'), { target: { value: '5000' } })
    fireEvent.click(screen.getByRole('button', { name: 'common:create' }))

    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1))
    expect(createMock.mock.calls[0][0]).toStrictEqual({
      title: 'Oil change', reminder_type: 'smart', due_date: '2026-12-01',
      due_mileage_km: 5000, due_hours: undefined, notes: undefined,
    })
  })

  it('a dual vehicle defaults smart to mileage when usage_unit is distance (distance-primary)', async () => {
    mockedApiGet.mockResolvedValue({ data: { usage_unit: 'distance', secondary_usage_enabled: true } })
    render(<ReminderForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(screen.getByText('reminderForm.typeSmart')).toBeInTheDocument())

    fireEvent.click(typeButton('reminderForm.typeSmart'))
    expect(screen.getByLabelText('reminder.dueMileage * (km)')).toBeInTheDocument()
    expect(screen.queryByLabelText('reminder.dueHours * (hr)')).not.toBeInTheDocument()
  })

  it('a dual vehicle defaults smart to hours when usage_unit is hours (hours-primary)', async () => {
    mockedApiGet.mockResolvedValue({ data: { usage_unit: 'hours', secondary_usage_enabled: true } })
    render(<ReminderForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(screen.getByText('reminderForm.typeSmart')).toBeInTheDocument())

    fireEvent.click(typeButton('reminderForm.typeSmart'))
    expect(screen.getByLabelText('reminder.dueHours * (hr)')).toBeInTheDocument()
    expect(screen.queryByLabelText('reminder.dueMileage * (km)')).not.toBeInTheDocument()
  })
})

describe('ReminderForm — from last service hours baseline', () => {
  beforeEach(() => {
    mockedApiGet.mockResolvedValue({ data: { usage_unit: 'hours', secondary_usage_enabled: false } })
  })

  it('From last service: last 800 hr + 50 → due_hours 850 (creates even when already overdue)', async () => {
    const user = userEvent.setup()
    render(<ReminderForm {...DEFAULT_PROPS} currentHours={900} />)
    await waitFor(() => expect(screen.getByText('reminderForm.typeHours')).toBeInTheDocument())

    await user.type(screen.getByLabelText('common:title *'), 'Hydraulic service')
    fireEvent.click(typeButton('reminderForm.typeHours'))
    fireEvent.click(screen.getByRole('button', { name: 'reminderForm.modeFromLast' }))
    fireEvent.change(screen.getByLabelText('reminder.lastDoneHours * (hr)'), { target: { value: '800' } })
    fireEvent.change(screen.getByLabelText('reminder.hoursInterval * (hr)'), { target: { value: '50' } })
    expect(screen.getByText(/reminderForm\.hoursLastOverdueNote/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'common:create' }))

    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1))
    expect(createMock.mock.calls[0][0]).toStrictEqual({
      title: 'Hydraulic service', reminder_type: 'hours', due_date: undefined,
      due_mileage_km: undefined, due_hours: 850, notes: undefined,
    })
  })

  it('rejects last done hours greater than current engine hours', async () => {
    const user = userEvent.setup()
    render(<ReminderForm {...DEFAULT_PROPS} currentHours={100} />)
    await waitFor(() => expect(screen.getByText('reminderForm.typeHours')).toBeInTheDocument())

    await user.type(screen.getByLabelText('common:title *'), 'Hydraulic service')
    fireEvent.click(typeButton('reminderForm.typeHours'))
    fireEvent.click(screen.getByRole('button', { name: 'reminderForm.modeFromLast' }))
    fireEvent.change(screen.getByLabelText('reminder.lastDoneHours * (hr)'), { target: { value: '150' } })
    fireEvent.change(screen.getByLabelText('reminder.hoursInterval * (hr)'), { target: { value: '50' } })
    fireEvent.click(screen.getByRole('button', { name: 'common:create' }))

    expect(screen.getByText('reminder.lastDoneExceedsCurrentHours')).toBeInTheDocument()
    expect(createMock).not.toHaveBeenCalled()
  })
})
