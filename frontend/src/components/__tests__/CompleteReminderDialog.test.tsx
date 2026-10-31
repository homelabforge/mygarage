/**
 * CompleteReminderDialog — the real date and reading go on the wire, in
 * canonical units, with the mode's own fields and nothing else.
 *
 * Imperial account: the odometer is typed in miles and stored in km. An
 * untouched field hands back the exact canonical value it was seeded from
 * (88,896 mi seeded from 143064.24 km returns 143064.24, not 143064.28).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '../../__tests__/test-utils'
import { fireEvent } from '@testing-library/react'
import type { Reminder } from '../../types/reminder'

const completeMock = vi.fn()
vi.mock('../../hooks/useReminders', () => ({
  useCompleteReminder: () => ({ mutateAsync: completeMock }),
}))
const fetchNextPage = vi.fn()
const pagesMock = vi.fn()
vi.mock('../../hooks/queries/useServiceVisits', () => ({
  useServiceVisitPages: (...args: unknown[]) => pagesMock(...args),
}))
const FIRST_PAGE = {
  visits: [{ id: 7, date: '2026-06-13', odometer_km: '143064.24', line_items: [{ description: 'Labor' }], vendor: { name: 'Mavis' } }],
  total: 101,
}
vi.mock('../VendorSearch', () => ({ default: () => <div>vendor-search</div> }))
vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => 'en-US' }))
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US', formatCurrency: (n: number) => `$${n}` }),
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
const toastSuccess = vi.fn()
vi.mock('sonner', () => ({ toast: { success: (...args: unknown[]) => toastSuccess(...args), error: vi.fn() } }))

import CompleteReminderDialog from '../CompleteReminderDialog'

const reminder = {
  id: 4, vin: 'V1', title: 'Oil Change', reminder_type: 'smart', status: 'pending',
  due_date: '2026-12-13', due_mileage_km: '151064.24', due_hours: null, notes: null,
  line_item_id: 60, last_notified_at: null, created_at: '2026-06-14T00:00:00Z', updated_at: '2026-06-14T00:00:00Z',
  rule_id: 1, rule: { id: 1, title: 'Oil Change', maintenance_type: 'engine_oil_filter', interval_km: '8000', interval_months: 6, interval_days: null, interval_hours: null, source: 'pack', source_pack_id: 'oil_and_filter', is_active: true },
} as unknown as Reminder

const SERVICE_KM = 143064.24 // 88,896 mi
const today = (() => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
})()

function renderDialog(overrides: Partial<React.ComponentProps<typeof CompleteReminderDialog>> = {}) {
  const onSuccess = vi.fn()
  render(
    <CompleteReminderDialog
      vin="V1"
      reminder={reminder}
      currentMileage={SERVICE_KM}
      currentHours={null}
      tracksDistance
      tracksHours={false}
      onClose={vi.fn()}
      onSuccess={onSuccess}
      {...overrides}
    />,
  )
  return { onSuccess }
}

const form = () => document.getElementById('complete-reminder-form') as HTMLFormElement

beforeEach(() => {
  vi.clearAllMocks()
  completeMock.mockResolvedValue({ reminder, next_reminder: null, service_visit_id: 9, line_item_id: 61 })
  pagesMock.mockReturnValue({ data: { pages: [FIRST_PAGE] }, hasNextPage: true, fetchNextPage, isFetchingNextPage: false })
})

describe('CompleteReminderDialog — payloads', () => {
  it('defaults to logging a visit today at the current reading, with the EXACT canonical odometer of an untouched field', async () => {
    const { onSuccess } = renderDialog()
    const odometer = screen.getByLabelText(/completeReminder\.odometer/) as HTMLInputElement
    expect(odometer.value).toBe('88896')
    fireEvent.submit(form())
    await waitFor(() => expect(completeMock).toHaveBeenCalledTimes(1))
    expect(completeMock.mock.calls[0][0]).toStrictEqual({
      id: 4,
      completed_date: today,
      odometer_km: SERVICE_KM,
      engine_hours: undefined,
      mode: 'create_visit',
      service_visit_id: undefined,
      vendor_id: undefined,
      cost: undefined,
      notes: undefined,
    })
    expect(onSuccess).toHaveBeenCalled()
  })

  it('a typed odometer in miles is stored in km (88,900 mi = 143070.6816 km) and the date is the typed one', async () => {
    renderDialog()
    fireEvent.change(screen.getByLabelText(/completeReminder\.completedDate/), { target: { value: '2026-06-13' } })
    fireEvent.change(screen.getByLabelText(/completeReminder\.odometer/), { target: { value: '88900' } })
    fireEvent.change(screen.getByLabelText(/completeReminder\.cost/), { target: { value: '45.5' } })
    fireEvent.submit(form())
    await waitFor(() => expect(completeMock).toHaveBeenCalledTimes(1))
    const payload = completeMock.mock.calls[0][0]
    expect(payload.completed_date).toBe('2026-06-13')
    expect(payload.odometer_km).toBeCloseTo(143070.6816, 4)
    expect(payload.cost).toBe(45.5)
  })

  it('"just mark it done" sends no vendor, cost or notes', async () => {
    renderDialog()
    fireEvent.click(screen.getByLabelText(/completeReminder\.modeMarkOnly/))
    fireEvent.submit(form())
    await waitFor(() => expect(completeMock).toHaveBeenCalledTimes(1))
    const payload = completeMock.mock.calls[0][0]
    expect(payload.mode).toBe('mark_only')
    expect(payload.vendor_id).toBeUndefined()
    expect(payload.cost).toBeUndefined()
    expect(payload.service_visit_id).toBeUndefined()
  })

  it('linking requires a visit, then sends its id', async () => {
    renderDialog()
    fireEvent.click(screen.getByLabelText(/completeReminder\.modeLink/))
    fireEvent.submit(form())
    expect(await screen.findByRole('alert')).toHaveTextContent('completeReminder.visitRequired')
    expect(completeMock).not.toHaveBeenCalled()
    fireEvent.change(screen.getByRole('combobox', { name: /completeReminder\.visit/ }), { target: { value: '7' } })
    fireEvent.submit(form())
    await waitFor(() => expect(completeMock).toHaveBeenCalledTimes(1))
    expect(completeMock.mock.calls[0][0].mode).toBe('link_visit')
    expect(completeMock.mock.calls[0][0].service_visit_id).toBe(7)
  })

  it('a linked visit supplies the date and reading: the date and odometer fields go away (codex BE R1-H3)', async () => {
    renderDialog()
    fireEvent.click(screen.getByLabelText(/completeReminder\.modeLink/))
    expect(screen.queryByLabelText(/completeReminder\.completedDate/)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/completeReminder\.odometer/)).not.toBeInTheDocument()
    fireEvent.change(screen.getByRole('combobox', { name: /completeReminder\.visit/ }), { target: { value: '7' } })
    fireEvent.submit(form())
    await waitFor(() => expect(completeMock).toHaveBeenCalledTimes(1))
    const payload = completeMock.mock.calls[0][0]
    expect(payload.completed_date).toBe('2026-06-13')
    expect(payload.odometer_km).toBeUndefined()
    expect(payload.engine_hours).toBeUndefined()
  })

  it('visits beyond the first page can be loaded, and only in link mode (codex FE R1-M2)', () => {
    renderDialog()
    expect(pagesMock.mock.calls.at(-1)?.[1]).toStrictEqual({ enabled: false })
    fireEvent.click(screen.getByLabelText(/completeReminder\.modeLink/))
    expect(pagesMock.mock.calls.at(-1)?.[1]).toStrictEqual({ enabled: true })
    fireEvent.click(screen.getByRole('button', { name: 'completeReminder.showOlderVisits' }))
    expect(fetchNextPage).toHaveBeenCalledTimes(1)
  })

  it('reports the next due date when the backend created a successor', async () => {
    completeMock.mockResolvedValue({
      reminder,
      next_reminder: { ...reminder, id: 5, due_date: '2026-12-13' },
      service_visit_id: 9,
      line_item_id: 61,
    })
    renderDialog()
    fireEvent.submit(form())
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledTimes(1))
    expect(toastSuccess.mock.calls[0][0]).toBe('completeReminder.doneNextDue')
  })

  it('an hours-tracked vehicle sends engine_hours and no odometer', async () => {
    renderDialog({ tracksDistance: false, tracksHours: true, currentMileage: null, currentHours: 812.4 })
    expect(screen.queryByLabelText(/completeReminder\.odometer/)).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText(/completeReminder\.hours/), { target: { value: '820' } })
    fireEvent.submit(form())
    await waitFor(() => expect(completeMock).toHaveBeenCalledTimes(1))
    expect(completeMock.mock.calls[0][0].engine_hours).toBe(820)
    expect(completeMock.mock.calls[0][0].odometer_km).toBeUndefined()
  })
})

// money-fits: the API takes 0 to MONEY_MAX (9,999,999,999.99) for the visit
// cost. The dialog used to drop unreadable text and post anything else.
describe('CompleteReminderDialog: the visit cost', () => {
  const cost = () => screen.getByLabelText(/completeReminder\.cost/)

  it.each([
    ['10000000000', 'common:validation.amount.tooLarge'],
    ['-5', 'common:validation.amount.negative'],
    ['abc', 'common:validation.amount.invalid'],
  ])('refuses %s on the field and sends nothing', async (typed, message) => {
    renderDialog()
    fireEvent.change(cost(), { target: { value: typed } })
    fireEvent.submit(form())
    expect(await screen.findByText(message)).toBeInTheDocument()
    expect(completeMock).not.toHaveBeenCalled()
  })

  it('takes MONEY_MAX itself', async () => {
    renderDialog()
    fireEvent.change(cost(), { target: { value: '9999999999.99' } })
    fireEvent.submit(form())
    await waitFor(() => expect(completeMock).toHaveBeenCalledTimes(1))
    expect(completeMock.mock.calls[0][0].cost).toBe(9999999999.99)
  })

  it('the cost error clears when the cost is edited', async () => {
    renderDialog()
    fireEvent.change(cost(), { target: { value: '-5' } })
    fireEvent.submit(form())
    expect(await screen.findByText('common:validation.amount.negative')).toBeInTheDocument()

    fireEvent.change(cost(), { target: { value: '45' } })
    expect(screen.queryByText('common:validation.amount.negative')).not.toBeInTheDocument()
    expect(cost()).not.toHaveAttribute('aria-invalid')
    expect(completeMock).not.toHaveBeenCalled()
  })

  it('a cost left behind in another mode does not block the save it is not part of', async () => {
    renderDialog()
    fireEvent.change(cost(), { target: { value: '10000000000' } })
    fireEvent.click(screen.getByLabelText(/completeReminder\.modeMarkOnly/))
    fireEvent.submit(form())
    await waitFor(() => expect(completeMock).toHaveBeenCalledTimes(1))
    expect(completeMock.mock.calls[0][0].cost).toBeUndefined()
  })
})
