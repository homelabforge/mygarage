/**
 * ReminderForm — the Repeat toggle turns the form into a maintenance rule.
 *
 * With Repeat on, the payload carries `recurrence` (canonical km, months,
 * hours) and an optional `anchor` ("from last service"), and NEVER the
 * absolute `due_*` fields: the backend derives those from the anchor and the
 * intervals. Editing a rule-backed reminder edits the rule; switching Repeat
 * off sends `recurrence: null`.
 *
 * Imperial account, so a 5,000 mi interval is stored as 8046.72 km.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '../../__tests__/test-utils'
import { fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Reminder } from '../../types/reminder'

const createMock = vi.fn().mockResolvedValue({})
const updateMock = vi.fn().mockResolvedValue({})
vi.mock('../../hooks/useReminders', () => ({
  useCreateReminder: () => ({ mutateAsync: createMock }),
  useUpdateReminder: () => ({ mutateAsync: updateMock }),
  useMaintenanceTypes: () => ({
    data: [{ code: 'engine_oil_filter', label: 'Engine oil and filter', category: 'engine' }],
  }),
}))
vi.mock('../../hooks/useUnitPreference', async () => {
  const { IMPERIAL_UNITS } = await import('@/__tests__/factories')
  // UnitSession reads the account half too; same answer, nothing to pin here.
  const unitPreference = () => ({ system: 'imperial', showBoth: false, units: IMPERIAL_UNITS, gallonStandard: 'us' })
  return {
    useUnitPreference: unitPreference,
    useAccountUnitPreference: unitPreference,
  }
})
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
const mockedApiGet = vi.fn().mockResolvedValue({ data: { usage_unit: 'distance', secondary_usage_enabled: false } })
vi.mock('../../services/api', () => ({
  default: { get: (...args: unknown[]) => mockedApiGet(...args) },
}))

import ReminderForm from '../ReminderForm'

const CURRENT_KM = 143064.24 // 88,896 mi

const ruleBacked = {
  id: 4, vin: 'V1', title: 'Oil Change', reminder_type: 'smart', status: 'pending',
  due_date: '2026-12-13', due_mileage_km: '151064.24', due_hours: null, notes: null,
  line_item_id: 60, last_notified_at: null, created_at: '2026-06-14T00:00:00Z', updated_at: '2026-06-14T00:00:00Z',
  maintenance_type: 'engine_oil_filter', rule_id: 1,
  rule: { id: 1, title: 'Oil Change', maintenance_type: 'engine_oil_filter', interval_km: '8000', interval_months: 6, interval_days: null, interval_hours: null, source: 'pack', source_pack_id: 'oil_and_filter', is_active: true },
} as unknown as Reminder

const form = () => document.getElementById('reminder-form') as HTMLFormElement

beforeEach(() => vi.clearAllMocks())

describe('ReminderForm — recurring create', () => {
  it('sends recurrence in canonical units and no due_* fields (5,000 mi = 8046.72 km, 6 months)', async () => {
    const user = userEvent.setup()
    render(<ReminderForm vin="V1" currentMileage={CURRENT_KM} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.type(screen.getByLabelText(/common:title/), 'Oil Change')
    await user.click(screen.getByLabelText('reminder.repeat'))
    // The one-off type picker is gone; the intervals are there.
    expect(screen.queryByText('reminder.reminderType')).not.toBeInTheDocument()
    await user.type(screen.getByLabelText(/recurrence\.everyDistance/), '5000')
    await user.type(screen.getByLabelText(/recurrence\.everyMonths/), '6')
    fireEvent.submit(form())
    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1))
    expect(createMock.mock.calls[0][0]).toStrictEqual({
      title: 'Oil Change',
      notes: undefined,
      maintenance_type: undefined,
      recurrence: { interval_km: 8046.72, interval_months: 6, interval_days: undefined, interval_hours: undefined },
      anchor: undefined,
    })
    expect(updateMock).not.toHaveBeenCalled()
  })

  it('"from last service" sends an anchor with the date and the canonical odometer (88,000 mi = 141622.272 km)', async () => {
    const user = userEvent.setup()
    render(<ReminderForm vin="V1" currentMileage={CURRENT_KM} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.type(screen.getByLabelText(/common:title/), 'Oil Change')
    await user.click(screen.getByLabelText('reminder.repeat'))
    await user.type(screen.getByLabelText(/recurrence\.everyMonths/), '6')
    await user.click(screen.getByRole('button', { name: 'reminderForm.modeFromLast' }))
    fireEvent.change(screen.getByLabelText(/reminder\.lastDoneDate/), { target: { value: '2026-06-13' } })
    await user.type(screen.getByLabelText(/reminder\.lastDoneMileage/), '88000')
    fireEvent.submit(form())
    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1))
    const payload = createMock.mock.calls[0][0]
    expect(payload.anchor.date).toBe('2026-06-13')
    expect(payload.anchor.odometer_km).toBeCloseTo(141622.272, 3)
    expect(payload.anchor.hours).toBeUndefined()
    expect(payload.recurrence).toStrictEqual({ interval_km: undefined, interval_months: 6, interval_days: undefined, interval_hours: undefined })
  })

  it('refuses a repeat with no interval and calls neither mutation', async () => {
    const user = userEvent.setup()
    render(<ReminderForm vin="V1" currentMileage={CURRENT_KM} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.type(screen.getByLabelText(/common:title/), 'Oil Change')
    await user.click(screen.getByLabelText('reminder.repeat'))
    fireEvent.submit(form())
    expect(await screen.findByText('reminder.recurrenceRequired')).toBeInTheDocument()
    expect(createMock).not.toHaveBeenCalled()
    expect(updateMock).not.toHaveBeenCalled()
  })

  it('a chosen maintenance type is sent', async () => {
    const user = userEvent.setup()
    render(<ReminderForm vin="V1" currentMileage={CURRENT_KM} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.type(screen.getByLabelText(/common:title/), 'Lube')
    await user.click(screen.getByLabelText('reminder.repeat'))
    await user.selectOptions(screen.getByLabelText(/reminder\.maintenanceType/), 'engine_oil_filter')
    await user.type(screen.getByLabelText(/recurrence\.everyMonths/), '12')
    fireEvent.submit(form())
    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1))
    expect(createMock.mock.calls[0][0].maintenance_type).toBe('engine_oil_filter')
  })
})

describe('ReminderForm — editing a rule-backed reminder', () => {
  it('opens with Repeat on and the rule intervals, and saves the rule (no due_* fields)', async () => {
    const user = userEvent.setup()
    render(<ReminderForm vin="V1" reminder={ruleBacked} currentMileage={CURRENT_KM} onClose={vi.fn()} onSuccess={vi.fn()} />)
    expect((screen.getByLabelText('reminder.repeat') as HTMLInputElement).checked).toBe(true)
    // 8000 km reads as 4971 mi on an imperial account.
    expect((screen.getByLabelText(/recurrence\.everyDistance/) as HTMLInputElement).value).toBe('4971')
    expect((screen.getByLabelText(/recurrence\.everyMonths/) as HTMLInputElement).value).toBe('6')
    await user.clear(screen.getByLabelText(/recurrence\.everyMonths/))
    await user.type(screen.getByLabelText(/recurrence\.everyMonths/), '3')
    fireEvent.submit(form())
    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1))
    const payload = updateMock.mock.calls[0][0]
    expect(payload.id).toBe(4)
    // Untouched distance returns the exact stored 8000, not a re-conversion of 4971.
    expect(payload.recurrence).toStrictEqual({ interval_km: 8000, interval_months: 3, interval_days: undefined, interval_hours: undefined })
    expect(payload.maintenance_type).toBe('engine_oil_filter')
    expect(payload).not.toHaveProperty('due_date')
    expect(payload).not.toHaveProperty('due_mileage_km')
    expect(createMock).not.toHaveBeenCalled()
  })

  it('clearing the notes posts null, and still no due_* fields', async () => {
    const user = userEvent.setup()
    const noted = { ...ruleBacked, notes: 'old note' } as unknown as Reminder
    render(<ReminderForm vin="V1" reminder={noted} currentMileage={CURRENT_KM} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.clear(document.getElementById('reminder-notes') as HTMLTextAreaElement)
    fireEvent.submit(form())
    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1))
    const payload = updateMock.mock.calls[0][0]
    expect(payload.notes).toBeNull()
    // An active rule 422s on any due_* key, null included.
    expect(payload).not.toHaveProperty('due_date')
    expect(payload).not.toHaveProperty('due_mileage_km')
    expect(payload).not.toHaveProperty('due_hours')
  })

  it('switching Repeat off sends recurrence: null with the one-off values the form shows', async () => {
    const user = userEvent.setup()
    render(<ReminderForm vin="V1" reminder={ruleBacked} currentMileage={CURRENT_KM} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.click(screen.getByLabelText('reminder.repeat'))
    fireEvent.submit(form())
    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1))
    const payload = updateMock.mock.calls[0][0]
    expect(payload.recurrence).toBeNull()
    expect(payload.reminder_type).toBe('smart')
    expect(payload.due_date).toBe('2026-12-13')
    // Untouched: the stored target comes back, not a re-conversion of 4971 mi.
    expect(payload.due_mileage_km).toBeCloseTo(151064.24, 2)
  })

  it('a due date edited after switching Repeat off is the one saved (codex FE R1-H4)', async () => {
    const user = userEvent.setup()
    render(<ReminderForm vin="V1" reminder={ruleBacked} currentMileage={CURRENT_KM} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.click(screen.getByLabelText('reminder.repeat'))
    fireEvent.change(screen.getByLabelText(/reminder\.dueDate/), { target: { value: '2027-01-31' } })
    fireEvent.submit(form())
    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1))
    expect(updateMock.mock.calls[0][0].due_date).toBe('2027-01-31')
    expect(updateMock.mock.calls[0][0].recurrence).toBeNull()
  })

  it('an unchanged day-only rule saves and keeps its day interval (codex FE R1-H1)', async () => {
    const dayOnly = {
      ...ruleBacked,
      due_mileage_km: null,
      reminder_type: 'date',
      rule: { ...ruleBacked.rule, interval_km: null, interval_months: null, interval_days: 30 },
    } as unknown as Reminder
    render(<ReminderForm vin="V1" reminder={dayOnly} currentMileage={CURRENT_KM} onClose={vi.fn()} onSuccess={vi.fn()} />)
    expect((screen.getByLabelText(/recurrence\.everyDays/) as HTMLInputElement).value).toBe('30')
    fireEvent.submit(form())
    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1))
    expect(updateMock.mock.calls[0][0].recurrence).toStrictEqual({
      interval_km: undefined, interval_months: undefined, interval_days: 30, interval_hours: undefined,
    })
  })
})

describe('ReminderForm — codex FE round 2: an overdue target survives an untouched save (R2-M1)', () => {
  it('Repeat off on an OVERDUE distance reminder saves the stored target, not a validation error', async () => {
    const overdue = { ...ruleBacked, due_mileage_km: '140000' } as unknown as Reminder
    const user = userEvent.setup()
    render(<ReminderForm vin="V1" reminder={overdue} currentMileage={CURRENT_KM} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.click(screen.getByLabelText('reminder.repeat'))
    fireEvent.submit(form())
    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1))
    expect(updateMock.mock.calls[0][0].due_mileage_km).toBe(140000)
    expect(updateMock.mock.calls[0][0].recurrence).toBeNull()
  })

  it('Repeat off on an OVERDUE hours reminder saves the stored hours target', async () => {
    mockedApiGet.mockResolvedValue({ data: { usage_unit: 'hours', secondary_usage_enabled: false } })
    const overdueHours = {
      ...ruleBacked,
      reminder_type: 'hours',
      due_date: null,
      due_mileage_km: null,
      due_hours: '800',
      rule: { ...ruleBacked.rule, interval_km: null, interval_months: null, interval_hours: '50' },
    } as unknown as Reminder
    const user = userEvent.setup()
    render(<ReminderForm vin="V1" reminder={overdueHours} currentMileage={null} currentHours={812} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.click(screen.getByLabelText('reminder.repeat'))
    fireEvent.submit(form())
    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1))
    expect(updateMock.mock.calls[0][0].due_hours).toBe(800)
    expect(updateMock.mock.calls[0][0].recurrence).toBeNull()
    mockedApiGet.mockResolvedValue({ data: { usage_unit: 'distance', secondary_usage_enabled: false } })
  })

  it('an untouched overdue ONE-OFF distance reminder also saves (the same path, before v3.5.0)', async () => {
    const oneOff = { ...ruleBacked, rule_id: null, rule: null, due_mileage_km: '140000' } as unknown as Reminder
    render(<ReminderForm vin="V1" reminder={oneOff} currentMileage={CURRENT_KM} onClose={vi.fn()} onSuccess={vi.fn()} />)
    fireEvent.submit(form())
    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1))
    expect(updateMock.mock.calls[0][0].due_mileage_km).toBe(140000)
    expect(updateMock.mock.calls[0][0]).not.toHaveProperty('recurrence')
  })
})

describe('ReminderForm — codex FE round 1', () => {
  it('a last-done DATE alone is sent as the anchor, even with no readings on the vehicle (R1-H2)', async () => {
    const user = userEvent.setup()
    render(<ReminderForm vin="V1" currentMileage={null} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.type(screen.getByLabelText(/common:title/), 'Coolant')
    await user.click(screen.getByLabelText('reminder.repeat'))
    await user.type(screen.getByLabelText(/recurrence\.everyMonths/), '6')
    await user.click(screen.getByRole('button', { name: 'reminderForm.modeFromLast' }))
    fireEvent.change(screen.getByLabelText(/reminder\.lastDoneDate/), { target: { value: '2026-06-13' } })
    fireEvent.submit(form())
    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1))
    expect(createMock.mock.calls[0][0].anchor).toStrictEqual({ date: '2026-06-13', odometer_km: undefined, hours: undefined })
  })

  it('"from last service" with nothing entered is refused, not silently ignored', async () => {
    const user = userEvent.setup()
    render(<ReminderForm vin="V1" currentMileage={CURRENT_KM} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.type(screen.getByLabelText(/common:title/), 'Coolant')
    await user.click(screen.getByLabelText('reminder.repeat'))
    await user.type(screen.getByLabelText(/recurrence\.everyMonths/), '6')
    await user.click(screen.getByRole('button', { name: 'reminderForm.modeFromLast' }))
    fireEvent.submit(form())
    expect(await screen.findByText('reminder.lastDoneRequired')).toBeInTheDocument()
    expect(createMock).not.toHaveBeenCalled()
  })

  it('distance and engine hours together are refused before the request (R1-F2)', async () => {
    mockedApiGet.mockResolvedValueOnce({ data: { usage_unit: 'distance', secondary_usage_enabled: true } })
    const user = userEvent.setup()
    render(<ReminderForm vin="V1" currentMileage={CURRENT_KM} currentHours={812} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.type(screen.getByLabelText(/common:title/), 'Service')
    await user.click(screen.getByLabelText('reminder.repeat'))
    await user.type(await screen.findByLabelText(/recurrence\.everyHours/), '50')
    await user.type(screen.getByLabelText(/recurrence\.everyDistance/), '5000')
    fireEvent.submit(form())
    expect(await screen.findByText('reminder.recurrenceDistanceOrHours')).toBeInTheDocument()
    expect(createMock).not.toHaveBeenCalled()
  })
})
