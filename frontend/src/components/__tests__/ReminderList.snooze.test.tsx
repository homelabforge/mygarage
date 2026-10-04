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
import type { Reminder } from '../../types/reminder'
import { IMPERIAL_UNITS } from '../../__tests__/factories'
import { todayInHousehold } from '../../constants/i18n'
import { addDaysToIsoDate } from '../../utils/dateUtils'

const useRemindersMock = vi.fn()
const dismissMock = vi.fn().mockResolvedValue(undefined)
const snoozeMock = vi.fn().mockResolvedValue(undefined)
const unsnoozeMock = vi.fn().mockResolvedValue(undefined)
vi.mock('../../hooks/useReminders', () => ({
  useReminders: () => useRemindersMock(),
  useMarkReminderDone: () => ({ mutateAsync: vi.fn() }),
  useMarkReminderDismissed: () => ({ mutateAsync: dismissMock }),
  useDeleteReminder: () => ({ mutateAsync: vi.fn() }),
  useReminderDuplicates: () => ({ data: [] }),
  useReminderPacks: () => ({ data: [] }),
  useDeletePack: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSnoozeReminder: () => ({ mutateAsync: snoozeMock, isPending: false }),
  useUnsnoozeReminder: () => ({ mutateAsync: unsnoozeMock, isPending: false }),
}))
vi.mock('../CompleteReminderDialog', () => ({ default: () => <div>complete-dialog-open</div> }))
const reminderFormProps = vi.hoisted(() => ({ onSuccess: undefined as (() => void) | undefined }))
vi.mock('../ReminderForm', () => ({
  default: (props: { onSuccess?: () => void }) => {
    reminderFormProps.onSuccess = props.onSuccess
    return <div>reminder-form-open</div>
  },
}))
vi.mock('../../hooks/useLatestMileage', () => ({ useLatestMileage: () => ({ data: null }) }))
vi.mock('../../hooks/useLatestHours', () => ({ useLatestHours: () => ({ data: null }) }))
vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => 'en-US' }))
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: 'imperial',
    showBoth: false,
    gallonStandard: 'us',
    units: IMPERIAL_UNITS,
  }),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import ReminderList from '../ReminderList'

const base = {
  id: 8, vin: 'V1', title: 'Oil change', reminder_type: 'date', status: 'pending',
  due_date: '2026-09-01', due_mileage_km: null, estimated_due_date: null, notes: null,
  line_item_id: null, last_notified_at: null, snoozed_until: null,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
} as unknown as Reminder

const snoozedFuture = {
  ...base, snoozed_until: addDaysToIsoDate(todayInHousehold(), 5),
} as unknown as Reminder
// today == snoozed_until means the snooze has expired (strictly-before
// semantics, matching the backend's is_reminder_snoozed).
const snoozedExpired = { ...base, snoozed_until: todayInHousehold() } as unknown as Reminder

beforeEach(() => {
  vi.clearAllMocks()
  useRemindersMock.mockReturnValue({ data: [base], isLoading: false })
})

describe('ReminderList — snooze action + dialog', () => {
  it('the 1-week preset snoozes to household today + 7', async () => {
    render(<ReminderList vin="V1" />)
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
    render(<ReminderList vin="V1" />)
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
      data: [{ ...base, status: 'done' } as unknown as Reminder],
      isLoading: false,
    })
    render(<ReminderList vin="V1" />)
    expect(screen.queryByRole('button', { name: 'reminderList.snooze' })).not.toBeInTheDocument()
  })
})

describe('ReminderList — snoozed chip + unsnooze', () => {
  it('an active snooze shows the chip; an unsnoozed reminder does not', () => {
    useRemindersMock.mockReturnValue({ data: [snoozedFuture], isLoading: false })
    const { unmount } = render(<ReminderList vin="V1" />)
    expect(screen.getByText('reminderList.snoozedUntil')).toBeInTheDocument()
    unmount()
    useRemindersMock.mockReturnValue({ data: [base], isLoading: false })
    render(<ReminderList vin="V1" />)
    expect(screen.queryByText('reminderList.snoozedUntil')).not.toBeInTheDocument()
  })

  it('an expired snooze (today == snoozed_until) shows no chip', () => {
    useRemindersMock.mockReturnValue({ data: [snoozedExpired], isLoading: false })
    render(<ReminderList vin="V1" />)
    expect(screen.queryByText('reminderList.snoozedUntil')).not.toBeInTheDocument()
  })

  it('unsnoozing from the dialog calls the mutation', async () => {
    useRemindersMock.mockReturnValue({ data: [snoozedFuture], isLoading: false })
    render(<ReminderList vin="V1" />)
    fireEvent.click(screen.getByRole('button', { name: 'reminderList.editSnooze' }))
    await screen.findByText('reminderList.snoozeExplain')
    fireEvent.click(screen.getByRole('button', { name: 'reminderList.unsnooze' }))
    await waitFor(() => expect(unsnoozeMock).toHaveBeenCalledWith(8))
  })
})
