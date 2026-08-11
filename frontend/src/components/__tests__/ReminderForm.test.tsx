import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '../../__tests__/test-utils'
import { fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Reminder } from '../../types/reminder'
import { toCanonicalKm } from '../../utils/decimalSafe'
import { UnitConverter } from '../../utils/units'

const createMock = vi.fn().mockResolvedValue({})
const updateMock = vi.fn().mockResolvedValue({})
vi.mock('../../hooks/useReminders', () => ({
  useCreateReminder: () => ({ mutateAsync: createMock }),
  useUpdateReminder: () => ({ mutateAsync: updateMock }),
}))
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({ system: 'imperial', showBoth: false }),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
// Task 15 — ReminderForm now fetches the vehicle for usage_unit/secondary_usage_enabled
// (mirrors FuelRecordForm/ServiceVisitForm). This suite is all date-type reminders on a
// distance-tracking (default) vehicle, so a resolved-but-empty response is enough — the
// ReminderForm.hours.test.tsx suite exercises the hours-specific behavior.
const mockedApiGet = vi.fn().mockResolvedValue({ data: { usage_unit: 'distance', secondary_usage_enabled: false } })
vi.mock('../../services/api', () => ({
  default: { get: (...args: unknown[]) => mockedApiGet(...args) },
}))

import ReminderForm from '../ReminderForm'

const reminder = {
  id: 3, vin: 'V1', title: 'Registration', reminder_type: 'date', status: 'pending',
  due_date: '2026-09-01', due_mileage_km: null, estimated_due_date: null, notes: null,
  line_item_id: null, last_notified_at: null,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
} as unknown as Reminder

/** Current odometer in canonical km corresponding to 149977 mi display. */
const CURRENT_MI = 149977
const CURRENT_KM = UnitConverter.milesToKm(CURRENT_MI)!

beforeEach(() => vi.clearAllMocks())

describe('ReminderForm — create vs update routing (SDQ-C)', () => {
  it('a valid date-type create fires the create mutation with the EXACT payload and NOT update (fails if create is unwired, misfields the payload, or routes to update)', async () => {
    const user = userEvent.setup()
    const onSuccess = vi.fn()
    render(<ReminderForm vin="V1" onClose={vi.fn()} onSuccess={onSuccess} />)
    await user.type(screen.getByLabelText('common:title *'), 'Oil change')  // type defaults to 'date' → due-date field shows
    fireEvent.change(screen.getByLabelText('reminder.dueDate *'), { target: { value: '2026-06-01' } })
    fireEvent.click(screen.getByRole('button', { name: 'common:create' }))
    await vi.waitFor(() => expect(createMock).toHaveBeenCalledTimes(1))
    // strict payload — a date-type reminder leaves due_mileage_km/due_hours/notes undefined (never objectContaining, LD6)
    expect(createMock.mock.calls[0][0]).toStrictEqual({
      title: 'Oil change', reminder_type: 'date', due_date: '2026-06-01', due_mileage_km: undefined, due_hours: undefined, notes: undefined,
    })
    expect(updateMock).not.toHaveBeenCalled()
    await vi.waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1))
  })

  it('editing a date-type reminder fires the update mutation with id + the EXACT payload and NOT create (fails if edit is unwired, drops id, or routes to create)', async () => {
    const onSuccess = vi.fn()
    render(<ReminderForm vin="V1" reminder={reminder} currentMileage={null} onClose={vi.fn()} onSuccess={onSuccess} />)
    fireEvent.click(screen.getByRole('button', { name: 'common:update' }))
    await vi.waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1))
    expect(updateMock.mock.calls[0][0]).toStrictEqual({
      id: 3, title: 'Registration', reminder_type: 'date', due_date: '2026-09-01', due_mileage_km: undefined, due_hours: undefined, notes: undefined,
    })
    expect(createMock).not.toHaveBeenCalled()
    await vi.waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1))
  })

  it('submitting with an empty title shows the title-required error and calls NEITHER mutation (fails if the required guard is dropped)', () => {
    render(<ReminderForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'common:create' }))
    expect(screen.getByText('reminder.titleRequired')).toBeInTheDocument()
    expect(createMock).not.toHaveBeenCalled()
    expect(updateMock).not.toHaveBeenCalled()
  })
})

// Task 10 addendum — the coordinator flagged that 10a's catch-block rewrite
// (parseApiError(err).fieldErrors -> fieldErrors map, else setError(...))
// gained real branching (the problems.length>0 test, the fieldErrors state,
// the render wiring) with zero test coverage. This is the same class of gap
// that hid a live bug in Task 7/9 — a non-422 failure showing NOTHING to the
// user — for two more tasks after a reviewer flagged it as Minor and it was
// deferred. Both branches are fenced here on the real create-mutation path.
describe('ReminderForm — server-side error wiring (Task 10 addendum)', () => {
  const fillMinimal = () => {
    fireEvent.change(screen.getByLabelText('common:title *'), { target: { value: 'Oil change' } })
    fireEvent.change(screen.getByLabelText('reminder.dueDate *'), { target: { value: '2026-06-01' } })
  }

  it('a 422 naming "notes" lands its message on the notes field (fails if the fieldErrors map is not wired to the Field)', async () => {
    createMock.mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed with status code 422',
      response: {
        status: 422,
        data: { detail: [{ type: 'string_too_long', loc: ['body', 'notes'], msg: 'Notes must be 2000 characters or fewer' }] },
      },
    })
    render(<ReminderForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    fillMinimal()
    fireEvent.click(screen.getByRole('button', { name: 'common:create' }))

    await vi.waitFor(() => expect(createMock).toHaveBeenCalledTimes(1))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Notes must be 2000 characters or fewer')
    expect(alert.id).toBe('reminder-notes-error')
  })

  it('a non-422 failure (network error) still shows the banner instead of staying silent (regression fence for the Task 7/9 silent-failure bug)', async () => {
    createMock.mockRejectedValueOnce(new Error('Network Error'))
    render(<ReminderForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    fillMinimal()
    fireEvent.click(screen.getByRole('button', { name: 'common:create' }))

    await vi.waitFor(() => expect(createMock).toHaveBeenCalledTimes(1))
    await vi.waitFor(() => expect(screen.getByText('Failed to {{action}}. {{message}}')).toBeInTheDocument())
  })

  // Final-review I4 regression fence: a 422 naming a field with NO render
  // target (reminder_type is a button group, not a Field) used to write to
  // fieldErrors state, render nothing for it, and — because the old gate was
  // `problems.length > 0 ? fieldErrors : setError(...)` — suppress the banner
  // too. The fix (applyControlledFieldErrors's attached/unhandled split) must
  // surface SOMETHING when a problem is left over even though another
  // problem DID attach.
  it('a 422 with one mapped field and one unmapped field still shows the banner for the unmapped one (fails if the silent-failure gate regresses)', async () => {
    createMock.mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed with status code 422',
      response: {
        status: 422,
        data: {
          detail: [
            { type: 'string_too_long', loc: ['body', 'notes'], msg: 'Notes must be 2000 characters or fewer' },
            { type: 'enum', loc: ['body', 'reminder_type'], msg: 'Invalid reminder type' },
          ],
        },
      },
    })
    render(<ReminderForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    fillMinimal()
    fireEvent.click(screen.getByRole('button', { name: 'common:create' }))

    await vi.waitFor(() => expect(createMock).toHaveBeenCalledTimes(1))
    // The mapped field still gets its own message...
    await vi.waitFor(() =>
      expect(screen.getByText('Notes must be 2000 characters or fewer')).toBeInTheDocument()
    )
    // ...AND the unmapped reminder_type problem must not vanish silently —
    // it has to surface via the generic action-failed banner.
    expect(screen.getByText('Failed to {{action}}. Please check your input.')).toBeInTheDocument()
  })

  it('a 422 naming ONLY an unmapped field shows the banner, not silence (fails if attached.length===0 check regresses)', async () => {
    createMock.mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed with status code 422',
      response: {
        status: 422,
        data: {
          detail: [{ type: 'enum', loc: ['body', 'reminder_type'], msg: 'Invalid reminder type' }],
        },
      },
    })
    render(<ReminderForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    fillMinimal()
    fireEvent.click(screen.getByRole('button', { name: 'common:create' }))

    await vi.waitFor(() => expect(createMock).toHaveBeenCalledTimes(1))
    expect(await screen.findByText('Failed to {{action}}. Please check your input.')).toBeInTheDocument()
  })
})

describe('ReminderForm — from last service mileage baseline', () => {
  const typeMileage = () =>
    fireEvent.click(screen.getByText('reminderForm.typeMileage').closest('button') as HTMLElement)

  it('From now (default) still submits current + interval as absolute due_mileage_km', async () => {
    const user = userEvent.setup()
    render(
      <ReminderForm
        vin="V1"
        currentMileage={CURRENT_KM}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />,
    )
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())

    await user.type(screen.getByLabelText('common:title *'), 'Oil change')
    typeMileage()
    expect(screen.getByRole('button', { name: 'reminderForm.modeFromNow' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('reminder.milesUntilDue * (mi)'), { target: { value: '5000' } })
    fireEvent.click(screen.getByRole('button', { name: 'common:create' }))

    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1))
    expect(createMock.mock.calls[0][0]).toStrictEqual({
      title: 'Oil change',
      reminder_type: 'mileage',
      due_date: undefined,
      due_mileage_km: CURRENT_KM + toCanonicalKm(5000, 'imperial')!,
      due_hours: undefined,
      notes: undefined,
    })
  })

  it('From last service: last 142965 mi + 5000 → due_mileage_km of 147965 mi (may already be overdue)', async () => {
    const user = userEvent.setup()
    render(
      <ReminderForm
        vin="V1"
        currentMileage={CURRENT_KM}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />,
    )
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())

    await user.type(screen.getByLabelText('common:title *'), 'Oil change')
    typeMileage()
    fireEvent.click(screen.getByRole('button', { name: 'reminderForm.modeFromLast' }))
    fireEvent.change(screen.getByLabelText('reminder.lastDoneMileage * (mi)'), { target: { value: '142965' } })
    fireEvent.change(screen.getByLabelText('reminder.mileageInterval * (mi)'), { target: { value: '5000' } })
    expect(screen.getByText(/reminderForm\.mileageLastOverdueNote/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'common:create' }))

    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1))
    const expectedDue =
      toCanonicalKm(142965, 'imperial')! + toCanonicalKm(5000, 'imperial')!
    expect(createMock.mock.calls[0][0]).toStrictEqual({
      title: 'Oil change',
      reminder_type: 'mileage',
      due_date: undefined,
      due_mileage_km: expectedDue,
      due_hours: undefined,
      notes: undefined,
    })
  })

  it('rejects last done mileage greater than current odometer', async () => {
    const user = userEvent.setup()
    render(
      <ReminderForm
        vin="V1"
        currentMileage={CURRENT_KM}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />,
    )
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())

    await user.type(screen.getByLabelText('common:title *'), 'Oil change')
    typeMileage()
    fireEvent.click(screen.getByRole('button', { name: 'reminderForm.modeFromLast' }))
    fireEvent.change(screen.getByLabelText('reminder.lastDoneMileage * (mi)'), { target: { value: '160000' } })
    fireEvent.change(screen.getByLabelText('reminder.mileageInterval * (mi)'), { target: { value: '5000' } })
    fireEvent.click(screen.getByRole('button', { name: 'common:create' }))

    expect(screen.getByText('reminder.lastDoneExceedsCurrentMileage')).toBeInTheDocument()
    expect(createMock).not.toHaveBeenCalled()
  })
})
