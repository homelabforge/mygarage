/**
 * #192: each pending row says where it stands. The server orders the list and
 * works out the status; these tests pin what the row does with them.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import type { Reminder } from '../../types/reminder'
import { IMPERIAL_UNITS } from '../../__tests__/factories'

// The remaining text carries its figure through interpolation, so this file
// swaps the global key-only mock for one that appends the options. Held at
// module scope: a fresh `t` per render re-fires every effect that lists it.
const i18nMock = vi.hoisted(() => ({
  t: (key: string, options?: Record<string, unknown>): string =>
    options ? [key, ...Object.values(options).map(String)].join('|') : key,
  i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
}))
vi.mock('react-i18next', () => ({
  useTranslation: () => i18nMock,
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}))

const useRemindersMock = vi.fn()
vi.mock('../../hooks/useReminders', () => ({
  useReminders: () => useRemindersMock(),
  useMarkReminderDone: () => ({ mutateAsync: vi.fn() }),
  useMarkReminderDismissed: () => ({ mutateAsync: vi.fn() }),
  useDeleteReminder: () => ({ mutateAsync: vi.fn() }),
  useReminderDuplicates: () => ({ data: [] }),
  useReminderPacks: () => ({ data: [] }),
  useDeletePack: () => ({ mutateAsync: vi.fn(), isPending: false }),
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

const row = (over: Partial<Reminder>): Reminder =>
  ({
    vin: 'V1', reminder_type: 'mileage', status: 'pending',
    due_date: null, due_mileage_km: null, due_hours: null,
    estimated_due_date: null, projected_usage_date: null, snoozed_until: null,
    notes: null, line_item_id: null, last_notified_at: null,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    due_status: null, progress: null, progress_basis: null,
    days_until_due: null, km_until_due: null, hours_until_due: null,
    ...over,
  }) as unknown as Reminder

// 1995.59 km is 1,240.00 mi and 482.80 km is 300.00 mi (/ 1.609344): whole
// numbers at the mile adapter's zero decimals.
const overdue = row({ id: 1, title: 'Brakes', due_status: 'overdue', progress: 1.1, progress_basis: 'distance', km_until_due: '-482.80' })
const dueSoon = row({ id: 2, title: 'Oil change', due_status: 'due_soon', progress: 0.9, progress_basis: 'distance', km_until_due: '1995.59' })
const onTrack = row({ id: 3, title: 'Coolant', reminder_type: 'date', due_status: 'on_track', progress: 0.4, progress_basis: 'date', days_until_due: 12 })
const snoozed = row({ id: 4, title: 'Wipers', reminder_type: 'date', due_status: 'snoozed', snoozed_until: '2999-01-01', progress: 0.5, progress_basis: 'date', days_until_due: 3 })

const card = (title: string): HTMLElement =>
  screen.getByText(title).closest('.rounded-card') as HTMLElement
const meter = (title: string): HTMLElement =>
  screen.getByRole('progressbar', { name: `reminderList.progressLabel|${title}` })
const show = (...rows: Reminder[]): void => {
  useRemindersMock.mockReturnValue({ data: rows, isLoading: false })
  render(<ReminderList vin="V1" />)
}

describe('ReminderList: where each reminder stands (#192)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('keeps the order the server sent', () => {
    show(overdue, dueSoon, onTrack, snoozed)
    const titles = screen.getAllByRole('heading', { level: 4 }).map((h) => h.textContent)
    expect(titles).toEqual(['Brakes', 'Oil change', 'Coolant', 'Wipers'])
  })

  it('an overdue row gets the danger chip, stripe and bar, and says how far over', () => {
    show(overdue)
    expect(screen.getByText('reminderList.statusOverdue')).toBeInTheDocument()
    expect(card('Brakes')).toHaveClass('border-l-danger')
    expect(meter('Brakes').firstElementChild).toHaveClass('bg-danger')
    expect(meter('Brakes')).toHaveAttribute('aria-valuenow', '100')
    expect(screen.getByText('reminderList.distanceOver|300 mi')).toBeInTheDocument()
  })

  it('a due-soon row gets the warning chip, stripe and bar, and says what is left in miles', () => {
    show(dueSoon)
    expect(screen.getByText('reminderList.statusDueSoon')).toBeInTheDocument()
    expect(card('Oil change')).toHaveClass('border-l-warning')
    expect(meter('Oil change').firstElementChild).toHaveClass('bg-warning')
    expect(meter('Oil change')).toHaveAttribute('aria-valuenow', '90')
    expect(meter('Oil change')).toHaveAttribute('aria-valuetext', 'reminderList.distanceLeft|1,240 mi')
    expect(screen.getByText('reminderList.distanceLeft|1,240 mi')).toBeInTheDocument()
  })

  it('an on-track row gets an accent bar and no chip or stripe', () => {
    show(onTrack)
    expect(screen.queryByText(/^reminderList\.status(Overdue|DueSoon)$/)).not.toBeInTheDocument()
    expect(card('Coolant').className).not.toMatch(/border-l-(danger|warning)/)
    expect(meter('Coolant').firstElementChild).toHaveClass('bg-(--accent-solid)')
    expect(screen.getByText('reminderList.daysLeft|12')).toBeInTheDocument()
  })

  it('a snoozed row keeps its snooze chip and gets a muted bar, no status chip or stripe', () => {
    show(snoozed)
    expect(screen.getByText(/^reminderList\.snoozedUntil\|/)).toBeInTheDocument()
    expect(screen.queryByText(/^reminderList\.status(Overdue|DueSoon)$/)).not.toBeInTheDocument()
    expect(card('Wipers').className).not.toMatch(/border-l-(danger|warning)/)
    expect(meter('Wipers').firstElementChild).toHaveClass('bg-text-mute')
  })

  it('a date reminder due today reads "due today", and one past due counts its days over', () => {
    show(
      row({ id: 5, title: 'Inspection', reminder_type: 'date', due_status: 'overdue', progress: 1, progress_basis: 'date', days_until_due: 0 }),
      row({ id: 6, title: 'Registration', reminder_type: 'date', due_status: 'overdue', progress: 1.1, progress_basis: 'date', days_until_due: -3 }),
    )
    expect(screen.getByText('reminderList.dueToday')).toBeInTheDocument()
    expect(screen.getByText('reminderList.daysOverdue|3')).toBeInTheDocument()
    expect(screen.queryByText('reminderList.daysLeft|0')).not.toBeInTheDocument()
  })

  it('hours read in hours, left and over', () => {
    show(
      row({ id: 9, title: 'Hydraulic oil', reminder_type: 'hours', due_status: 'on_track', progress: 0.5, progress_basis: 'hours', hours_until_due: '12.5' }),
      row({ id: 10, title: 'Grease', reminder_type: 'hours', due_status: 'overdue', progress: 1.04, progress_basis: 'hours', hours_until_due: '-4.0' }),
    )
    expect(screen.getByText('reminderList.hoursLeft|12.5')).toBeInTheDocument()
    expect(screen.getByText('reminderList.hoursOver|4.0')).toBeInTheDocument()
  })

  it('no progress, no bar, but the chip stays', () => {
    show(row({ id: 7, title: 'Hydraulics', reminder_type: 'hours', due_status: 'due_soon' }))
    expect(screen.getByText('reminderList.statusDueSoon')).toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })

  it('a closed row shows none of it, even carrying stale status fields', () => {
    show(row({ id: 8, title: 'Old task', reminder_type: 'date', status: 'done', due_status: 'overdue', progress: 1.2, progress_basis: 'date', days_until_due: -9 }))
    expect(screen.queryByText('reminderList.statusOverdue')).not.toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    expect(card('Old task').className).not.toMatch(/border-l-danger/)
  })
})
