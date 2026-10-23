import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '../../__tests__/test-utils'
import { fireEvent } from '@testing-library/react'
import type { Reminder } from '../../types/reminder'
import { IMPERIAL_UNITS } from '../../__tests__/factories'
import api from '../../services/api'
import { NO_READING, makeReminder, makeVehicle, reminderHooks, reminderFormModule, unitPreference } from './helpers/reminderListHarness'

const useRemindersMock = vi.fn()
const markDoneMock = vi.fn().mockResolvedValue(undefined)
const dismissMock = vi.fn().mockResolvedValue(undefined)
const deleteMock = vi.fn().mockResolvedValue(undefined)
const useReminderDuplicatesMock = vi.fn()
const useReminderPacksMock = vi.fn()
vi.mock('../../hooks/useReminders', () => reminderHooks({
  useReminders: () => useRemindersMock(),
  useMarkReminderDone: () => ({ mutateAsync: markDoneMock }),
  useMarkReminderDismissed: () => ({ mutateAsync: dismissMock }),
  useDeleteReminder: () => ({ mutateAsync: deleteMock }),
  useReminderDuplicates: () => useReminderDuplicatesMock(),
  useReminderPacks: (vehicleType: string | null) => useReminderPacksMock(vehicleType),
}))
// The completion dialog is its own component with its own tests; here only
// the fact that Mark done OPENS it with the exact reminder matters.
const completeDialogProps = vi.hoisted(() => ({ reminder: 'UNSET' as unknown }))
vi.mock('../CompleteReminderDialog', () => ({
  default: (props: { reminder?: unknown }) => {
    completeDialogProps.reminder = props.reminder
    return <div>complete-dialog-open</div>
  },
}))
vi.mock('../../hooks/useLatestMileage', () => ({ useLatestMileage: () => NO_READING }))
vi.mock('../../hooks/useLatestHours', () => ({ useLatestHours: () => NO_READING }))
vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => 'en-US' }))
// The RESOLVED set, not just the collapsed system: this component reads its
// distance through `useUnitFormat()`, which closes over `units`.
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => unitPreference(IMPERIAL_UNITS, 'imperial'),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
// Capture the reminder prop the mounted ReminderForm receives (vi.hoisted so the holder is safe to
// reference inside the hoisted vi.mock factory — the house idiom). Sentinel 'UNSET' distinguishes
// "form never rendered" from "rendered with reminder === undefined".
const reminderFormProps = vi.hoisted(() => ({ reminder: 'UNSET' as unknown }))
vi.mock('../ReminderForm', (importOriginal) =>
  reminderFormModule(importOriginal, (props: { reminder?: Reminder }) => {
    reminderFormProps.reminder = props.reminder
    return <div>reminder-form-open</div>
  }),
)

import ReminderList from '../ReminderList'

const pending = makeReminder({ id: 8 })
const done = makeReminder({ id: 9, title: 'Old task', status: 'done' })
const vehicle = makeVehicle()

beforeEach(() => {
  vi.clearAllMocks()
  reminderFormProps.reminder = 'UNSET'
  completeDialogProps.reminder = 'UNSET'
  useRemindersMock.mockReturnValue({ data: [pending], isLoading: false })
  useReminderDuplicatesMock.mockReturnValue({ data: [] })
  useReminderPacksMock.mockReturnValue({ data: [] })
})

describe('ReminderList — rendering + row actions (pending)', () => {
  it('renders the reminder title and its type category chip (fails if a field is dropped or the list never renders the reminders)', () => {
    render(<ReminderList vehicle={vehicle} />)
    expect(screen.getByText('Oil change')).toBeInTheDocument()
    expect(screen.getByText('reminderForm.typeMileage')).toBeInTheDocument()   // the reminder_type <Chip>
  })

  it('clicking Mark-done opens the completion dialog with the EXACT reminder and never flips the status directly (v3.5.0: the real date and reading anchor the next cycle)', async () => {
    render(<ReminderList vehicle={vehicle} />)
    expect(screen.queryByText('complete-dialog-open')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'reminderList.markDone' }))
    await waitFor(() => expect(screen.getByText('complete-dialog-open')).toBeInTheDocument())
    expect(completeDialogProps.reminder).toBe(pending)
    expect(markDoneMock).not.toHaveBeenCalled()
  })

  it('clicking Dismiss calls the dismiss mutation with the reminder id (fails if dismiss is unwired)', async () => {
    render(<ReminderList vehicle={vehicle} />)
    fireEvent.click(screen.getByRole('button', { name: 'reminderList.dismiss' }))
    await waitFor(() => expect(dismissMock.mock.calls[0]).toStrictEqual([8]))
  })

  it('a RULE-BACKED reminder says Dismiss stops the repeat (v3.5.0: dismiss deactivates the rule, so the label may not read like a one-off dismiss)', () => {
    const recurring = { ...pending, rule_id: 1, rule: { id: 1, title: 'Oil change', is_active: true } } as unknown as Reminder
    useRemindersMock.mockReturnValue({ data: [recurring], isLoading: false })
    render(<ReminderList vehicle={vehicle} />)
    expect(screen.getByRole('button', { name: 'reminderList.dismissStopsRepeat' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'reminderList.dismiss' })).not.toBeInTheDocument()
  })

  it('clicking Delete calls the delete mutation DIRECTLY with the id and never opens a confirm dialog (fails if delete is unwired OR a confirm gate is added — ReminderList delete is direct, LD5)', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm')
    render(<ReminderList vehicle={vehicle} />)
    fireEvent.click(screen.getByRole('button', { name: 'common:delete' }))
    await waitFor(() => expect(deleteMock.mock.calls[0]).toStrictEqual([8]))
    expect(confirmSpy).not.toHaveBeenCalled()
  })

  it('the row Mark-done/Dismiss/Edit/Delete expose a real aria-label (IconButton), not a bare title (fails if any regresses to a title-only <button>)', () => {
    render(<ReminderList vehicle={vehicle} />)
    expect(screen.getByRole('button', { name: 'reminderList.markDone' })).toHaveAttribute('aria-label', 'reminderList.markDone')
    expect(screen.getByRole('button', { name: 'reminderList.dismiss' })).toHaveAttribute('aria-label', 'reminderList.dismiss')
    expect(screen.getByRole('button', { name: 'common:edit' })).toHaveAttribute('aria-label', 'common:edit')
    expect(screen.getByRole('button', { name: 'common:delete' })).toHaveAttribute('aria-label', 'common:delete')
  })

  it('clicking Edit opens the ReminderForm with the EXACT pending reminder (fails if edit is unwired OR opens a blank create form — e.g. handleEdit(reminder) replaced by setShowForm(true))', () => {
    render(<ReminderList vehicle={vehicle} />)
    expect(screen.queryByText('reminder-form-open')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'common:edit' }))
    expect(screen.getByText('reminder-form-open')).toBeInTheDocument()
    // the mounted ReminderForm received the exact clicked reminder object (identity) — not undefined, not a clone.
    // A blank-create regression (setShowForm(true) without setEditingReminder(reminder)) would pass reminder=undefined → this FAILS.
    expect(reminderFormProps.reminder).toBe(pending)
  })

  it('clicking Add opens the ReminderForm with NO reminder (create mode — fails if Add prefills a reminder instead of passing undefined)', () => {
    render(<ReminderList vehicle={vehicle} />)
    fireEvent.click(screen.getByRole('button', { name: 'reminderList.addReminder' }))
    expect(screen.getByText('reminder-form-open')).toBeInTheDocument()
    // open-create passes NO reminder — distinguishes the Add path from the Edit path above.
    expect(reminderFormProps.reminder).toBeUndefined()
  })
})

describe('ReminderList — status both ways', () => {
  it('a DONE reminder shows NO mark-done and NO dismiss action (fails if the pending-only guard is dropped or inverted)', () => {
    useRemindersMock.mockReturnValue({ data: [done], isLoading: false })
    render(<ReminderList vehicle={vehicle} />)
    expect(screen.queryByRole('button', { name: 'reminderList.markDone' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'reminderList.dismiss' })).not.toBeInTheDocument()
    // edit + delete remain available for a done reminder
    expect(screen.getByRole('button', { name: 'common:edit' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'common:delete' })).toBeInTheDocument()
  })

  it('with zero reminders, the empty state renders (fails if the empty branch is dropped)', () => {
    useRemindersMock.mockReturnValue({ data: [], isLoading: false })
    render(<ReminderList vehicle={vehicle} />)
    expect(screen.getByText('reminderList.noReminders')).toBeInTheDocument()
  })
})

describe('ReminderList: possible duplicates (G5a-11)', () => {
  const group = {
    maintenance_type: 'engine_oil_filter', label: 'Oil & Filter', reminder_ids: [8, 12], suggested_keep_id: 12,
  }

  it('flags a pending row the duplicate groups name, with no duplicate_of on the row', () => {
    useReminderDuplicatesMock.mockReturnValue({ data: [group] })
    render(<ReminderList vehicle={vehicle} />)
    expect(screen.getByText('reminderList.possibleDuplicate')).toBeInTheDocument()
  })

  // Control: passes on main too; it pins that membership, not any group, sets the chip.
  it('leaves a row out of every group unflagged', () => {
    useReminderDuplicatesMock.mockReturnValue({ data: [{ ...group, reminder_ids: [11, 12] }] })
    render(<ReminderList vehicle={vehicle} />)
    expect(screen.queryByText('reminderList.possibleDuplicate')).not.toBeInTheDocument()
  })
})

describe('ReminderList: the type chip (D6a)', () => {
  it('a smart row shows the form\'s translated label, not the stored token', () => {
    useRemindersMock.mockReturnValue({ data: [makeReminder({ reminder_type: 'smart' })], isLoading: false })
    render(<ReminderList vehicle={vehicle} />)
    expect(screen.getByText('reminderForm.typeSmart')).toBeInTheDocument()
    expect(screen.queryByText('smart')).not.toBeInTheDocument()
  })

  it('a type the form does not know renders no chip', () => {
    useRemindersMock.mockReturnValue({ data: [makeReminder({ reminder_type: 'legacy' })], isLoading: false })
    render(<ReminderList vehicle={vehicle} />)
    expect(screen.getByText('Oil change')).toBeInTheDocument()
    expect(screen.queryByText('legacy')).not.toBeInTheDocument()
    expect(screen.queryByText(/^reminderForm\.type/)).not.toBeInTheDocument()
  })
})

describe('ReminderList: the vehicle comes from its parent (G5a-10)', () => {
  it('renders from the vehicle prop without fetching the vehicle', () => {
    render(<ReminderList vehicle={makeVehicle({ vehicle_type: 'Motorcycle' })} />)
    expect(screen.getByText('Oil change')).toBeInTheDocument()
    const fetched = vi.mocked(api.get).mock.calls.map(([url]) => url)
    expect(fetched.filter((url) => url.startsWith('/vehicles/'))).toEqual([])
    // The packs are the prop's vehicle type's from the first render.
    expect(useReminderPacksMock).toHaveBeenCalledWith('Motorcycle')
    expect(useReminderPacksMock).not.toHaveBeenCalledWith(null)
  })
})
