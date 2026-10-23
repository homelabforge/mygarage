/**
 * Reminder snooze (v3.5.0, hide-until-date): the pending-row Snooze action,
 * the SnoozeReminderDialog presets and the "snoozed until" chip. The hero's
 * counts refresh through the snooze hooks' invalidation (#192), tested in
 * hooks/queries/__tests__/writesRefreshReminderViews.test.ts.
 *
 * The dialog is mounted REAL (only its mutation hooks are mocked) so the
 * preset date arithmetic is exercised, not stubbed.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '../../__tests__/test-utils'
import { fireEvent } from '@testing-library/react'
import { IMPERIAL_UNITS } from '../../__tests__/factories'
import { NO_READING, makeReminder, makeVehicle, reminderHooks, reminderFormModule, unitPreference } from './helpers/reminderListHarness'
import { todayInHousehold } from '../../constants/i18n'
import { addDaysToIsoDate } from '../../utils/dateUtils'

const useRemindersMock = vi.fn()
const dismissMock = vi.fn().mockResolvedValue(undefined)
const snoozeMock = vi.fn().mockResolvedValue(undefined)
const unsnoozeMock = vi.fn().mockResolvedValue(undefined)
vi.mock('../../hooks/useReminders', () => reminderHooks({
  useReminders: () => useRemindersMock(),
  useMarkReminderDismissed: () => ({ mutateAsync: dismissMock }),
  useSnoozeReminder: () => ({ mutateAsync: snoozeMock, isPending: false }),
  useUnsnoozeReminder: () => ({ mutateAsync: unsnoozeMock, isPending: false }),
}))
vi.mock('../CompleteReminderDialog', () => ({ default: () => <div>complete-dialog-open</div> }))
const reminderFormProps = vi.hoisted(() => ({ onSuccess: undefined as (() => void) | undefined }))
vi.mock('../ReminderForm', (importOriginal) =>
  reminderFormModule(importOriginal, (props: { onSuccess?: () => void }) => {
    reminderFormProps.onSuccess = props.onSuccess
    return <div>reminder-form-open</div>
  }),
)
vi.mock('../../hooks/useLatestMileage', () => ({ useLatestMileage: () => NO_READING }))
vi.mock('../../hooks/useLatestHours', () => ({ useLatestHours: () => NO_READING }))
vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => 'en-US' }))
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => unitPreference(IMPERIAL_UNITS, 'imperial'),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import ReminderList from '../ReminderList'

const base = makeReminder({ id: 8, reminder_type: 'date', due_date: '2026-09-01' })
const vehicle = makeVehicle()

const snoozedFuture = { ...base, snoozed_until: addDaysToIsoDate(todayInHousehold(), 5) }
// today == snoozed_until means the snooze has expired (strictly-before
// semantics, matching the backend's is_reminder_snoozed).
const snoozedExpired = { ...base, snoozed_until: todayInHousehold() }

beforeEach(() => {
  vi.clearAllMocks()
  useRemindersMock.mockReturnValue({ data: [base], isLoading: false })
})

describe('ReminderList — snooze action + dialog', () => {
  it('the 1-week preset snoozes to household today + 7', async () => {
    render(<ReminderList vehicle={vehicle} />)
    fireEvent.click(screen.getByRole('button', { name: 'reminderList.snooze' }))
    await screen.findByText('reminderList.snoozeExplain')
    fireEvent.click(screen.getByRole('button', { name: 'reminderList.snoozeWeek' }))
    await waitFor(() =>
      expect(snoozeMock).toHaveBeenCalledWith({
        id: 8,
        until: addDaysToIsoDate(todayInHousehold(), 7),
      }),
    )
  })

  it('a custom date snoozes to exactly that date', async () => {
    render(<ReminderList vehicle={vehicle} />)
    fireEvent.click(screen.getByRole('button', { name: 'reminderList.snooze' }))
    await screen.findByText('reminderList.snoozeExplain')
    const until = addDaysToIsoDate(todayInHousehold(), 42)
    fireEvent.change(screen.getByLabelText('reminderList.snoozeCustomLabel'), {
      target: { value: until },
    })
    fireEvent.click(screen.getByRole('button', { name: 'reminderList.snoozeConfirm' }))
    await waitFor(() => expect(snoozeMock).toHaveBeenCalledWith({ id: 8, until }))
  })

  it('a done reminder gets no snooze action (pending-only, like mark-done and dismiss)', () => {
    useRemindersMock.mockReturnValue({
      data: [{ ...base, status: 'done' }],
      isLoading: false,
    })
    render(<ReminderList vehicle={vehicle} />)
    expect(screen.queryByRole('button', { name: 'reminderList.snooze' })).not.toBeInTheDocument()
  })
})

describe('ReminderList — snoozed chip + unsnooze', () => {
  it('an active snooze shows the chip; an unsnoozed reminder does not', () => {
    useRemindersMock.mockReturnValue({ data: [snoozedFuture], isLoading: false })
    const { unmount } = render(<ReminderList vehicle={vehicle} />)
    expect(screen.getByText('reminderList.snoozedUntil')).toBeInTheDocument()
    unmount()
    useRemindersMock.mockReturnValue({ data: [base], isLoading: false })
    render(<ReminderList vehicle={vehicle} />)
    expect(screen.queryByText('reminderList.snoozedUntil')).not.toBeInTheDocument()
  })

  it('an expired snooze (today == snoozed_until) shows no chip', () => {
    useRemindersMock.mockReturnValue({ data: [snoozedExpired], isLoading: false })
    render(<ReminderList vehicle={vehicle} />)
    expect(screen.queryByText('reminderList.snoozedUntil')).not.toBeInTheDocument()
  })

  it('unsnoozing from the dialog calls the mutation', async () => {
    useRemindersMock.mockReturnValue({ data: [snoozedFuture], isLoading: false })
    render(<ReminderList vehicle={vehicle} />)
    fireEvent.click(screen.getByRole('button', { name: 'reminderList.editSnooze' }))
    await screen.findByText('reminderList.snoozeExplain')
    fireEvent.click(screen.getByRole('button', { name: 'reminderList.unsnooze' }))
    await waitFor(() => expect(unsnoozeMock).toHaveBeenCalledWith(8))
  })
})
