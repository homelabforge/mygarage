import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '../../__tests__/test-utils'
import { fireEvent } from '@testing-library/react'
import type { Reminder } from '../../types/reminder'
import { IMPERIAL_UNITS } from '../../__tests__/factories'

const useRemindersMock = vi.fn()
const markDoneMock = vi.fn().mockResolvedValue(undefined)
const dismissMock = vi.fn().mockResolvedValue(undefined)
const deleteMock = vi.fn().mockResolvedValue(undefined)
vi.mock('../../hooks/useReminders', () => ({
  useReminders: () => useRemindersMock(),
  useMarkReminderDone: () => ({ mutateAsync: markDoneMock }),
  useMarkReminderDismissed: () => ({ mutateAsync: dismissMock }),
  useDeleteReminder: () => ({ mutateAsync: deleteMock }),
}))
vi.mock('../../hooks/useLatestMileage', () => ({ useLatestMileage: () => ({ data: null }) }))
vi.mock('../../hooks/useLatestHours', () => ({ useLatestHours: () => ({ data: null }) }))
vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => 'en-US' }))
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: 'imperial',
    showBoth: false,
    gallonStandard: 'us',
    // The RESOLVED set, not just the collapsed system: this component reads
    // its distance through `useUnitFormat()`, which closes over `units`.
    units: IMPERIAL_UNITS,
  }),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
// Capture the reminder prop the mounted ReminderForm receives (vi.hoisted so the holder is safe to
// reference inside the hoisted vi.mock factory — the house idiom). Sentinel 'UNSET' distinguishes
// "form never rendered" from "rendered with reminder === undefined".
const reminderFormProps = vi.hoisted(() => ({ reminder: 'UNSET' as unknown }))
vi.mock('../ReminderForm', () => ({
  default: (props: { reminder?: Reminder }) => {
    reminderFormProps.reminder = props.reminder
    return <div>reminder-form-open</div>
  },
}))

import ReminderList from '../ReminderList'

const pending = {
  id: 8, vin: 'V1', title: 'Oil change', reminder_type: 'mileage', status: 'pending',
  due_date: null, due_mileage_km: null, estimated_due_date: null, notes: null,
  line_item_id: null, last_notified_at: null,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
} as unknown as Reminder
const done = { ...pending, id: 9, title: 'Old task', status: 'done' } as unknown as Reminder

beforeEach(() => {
  vi.clearAllMocks()
  reminderFormProps.reminder = 'UNSET'
  useRemindersMock.mockReturnValue({ data: [pending], isLoading: false })
})

describe('ReminderList — rendering + row actions (pending)', () => {
  it('renders the reminder title and its type category chip (fails if a field is dropped or the list never renders the reminders)', () => {
    render(<ReminderList vin="V1" />)
    expect(screen.getByText('Oil change')).toBeInTheDocument()
    expect(screen.getByText('mileage')).toBeInTheDocument()   // the reminder_type <Chip>
  })

  it('clicking Mark-done calls the markDone mutation with the reminder id (fails if mark-done is unwired)', async () => {
    render(<ReminderList vin="V1" />)
    fireEvent.click(screen.getByRole('button', { name: 'reminderList.markDone' }))
    await waitFor(() => expect(markDoneMock.mock.calls[0]).toStrictEqual([8]))
  })

  it('clicking Dismiss calls the dismiss mutation with the reminder id (fails if dismiss is unwired)', async () => {
    render(<ReminderList vin="V1" />)
    fireEvent.click(screen.getByRole('button', { name: 'reminderList.dismiss' }))
    await waitFor(() => expect(dismissMock.mock.calls[0]).toStrictEqual([8]))
  })

  it('clicking Delete calls the delete mutation DIRECTLY with the id and never opens a confirm dialog (fails if delete is unwired OR a confirm gate is added — ReminderList delete is direct, LD5)', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm')
    render(<ReminderList vin="V1" />)
    fireEvent.click(screen.getByRole('button', { name: 'common:delete' }))
    await waitFor(() => expect(deleteMock.mock.calls[0]).toStrictEqual([8]))
    expect(confirmSpy).not.toHaveBeenCalled()
  })

  it('the row Mark-done/Dismiss/Edit/Delete expose a real aria-label (IconButton), not a bare title (fails if any regresses to a title-only <button>)', () => {
    render(<ReminderList vin="V1" />)
    expect(screen.getByRole('button', { name: 'reminderList.markDone' })).toHaveAttribute('aria-label', 'reminderList.markDone')
    expect(screen.getByRole('button', { name: 'reminderList.dismiss' })).toHaveAttribute('aria-label', 'reminderList.dismiss')
    expect(screen.getByRole('button', { name: 'common:edit' })).toHaveAttribute('aria-label', 'common:edit')
    expect(screen.getByRole('button', { name: 'common:delete' })).toHaveAttribute('aria-label', 'common:delete')
  })

  it('clicking Edit opens the ReminderForm with the EXACT pending reminder (fails if edit is unwired OR opens a blank create form — e.g. handleEdit(reminder) replaced by setShowForm(true))', () => {
    render(<ReminderList vin="V1" />)
    expect(screen.queryByText('reminder-form-open')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'common:edit' }))
    expect(screen.getByText('reminder-form-open')).toBeInTheDocument()
    // the mounted ReminderForm received the exact clicked reminder object (identity) — not undefined, not a clone.
    // A blank-create regression (setShowForm(true) without setEditingReminder(reminder)) would pass reminder=undefined → this FAILS.
    expect(reminderFormProps.reminder).toBe(pending)
  })

  it('clicking Add opens the ReminderForm with NO reminder (create mode — fails if Add prefills a reminder instead of passing undefined)', () => {
    render(<ReminderList vin="V1" />)
    fireEvent.click(screen.getByRole('button', { name: 'reminderList.addReminder' }))
    expect(screen.getByText('reminder-form-open')).toBeInTheDocument()
    // open-create passes NO reminder — distinguishes the Add path from the Edit path above.
    expect(reminderFormProps.reminder).toBeUndefined()
  })
})

describe('ReminderList — status both ways', () => {
  it('a DONE reminder shows NO mark-done and NO dismiss action (fails if the pending-only guard is dropped or inverted)', () => {
    useRemindersMock.mockReturnValue({ data: [done], isLoading: false })
    render(<ReminderList vin="V1" />)
    expect(screen.queryByRole('button', { name: 'reminderList.markDone' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'reminderList.dismiss' })).not.toBeInTheDocument()
    // edit + delete remain available for a done reminder
    expect(screen.getByRole('button', { name: 'common:edit' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'common:delete' })).toBeInTheDocument()
  })

  it('with zero reminders, the empty state renders (fails if the empty branch is dropped)', () => {
    useRemindersMock.mockReturnValue({ data: [], isLoading: false })
    render(<ReminderList vin="V1" />)
    expect(screen.getByText('reminderList.noReminders')).toBeInTheDocument()
  })
})
