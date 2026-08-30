import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import { fireEvent } from '@testing-library/react'
import type { Reminder } from '../../types/reminder'
import { METRIC_UNITS } from '../../__tests__/factories'

// Task 15 — ReminderList hours-based target rendering. Mirrors
// ServiceVisitList's Task 14 engine-hours reading coverage: an hours
// reminder renders its "due at N hr" target (fixed "hr" unit, no
// UnitFormatter conversion — dimensionless, same convention as the
// engine-hours reading elsewhere); a mileage reminder's existing rendering
// stays untouched. `estimated_due_date` (the backend-computed
// smart-reminder status) is already rendered unconditionally by
// ReminderList regardless of which metric backs it, so it needs no new
// branch here.
//
// Task 15 (revised) — hours reminders are interval-based (parity with
// mileage), so ReminderList must also source a currentHours baseline (via
// useLatestHours, mirroring useLatestMileage) and forward it into
// ReminderForm.

const useRemindersMock = vi.fn()
vi.mock('../../hooks/useReminders', () => ({
  useReminders: () => useRemindersMock(),
  useMarkReminderDone: () => ({ mutateAsync: vi.fn().mockResolvedValue(undefined) }),
  useMarkReminderDismissed: () => ({ mutateAsync: vi.fn().mockResolvedValue(undefined) }),
  useDeleteReminder: () => ({ mutateAsync: vi.fn().mockResolvedValue(undefined) }),
}))
vi.mock('../../hooks/useLatestMileage', () => ({ useLatestMileage: () => ({ data: null }) }))
const useLatestHoursMock = vi.fn(() => ({ data: null as number | null }))
vi.mock('../../hooks/useLatestHours', () => ({ useLatestHours: () => useLatestHoursMock() }))
vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => 'en-US' }))
// Metric — keeps the mileage-target assertion an exact, deterministic string
// (no mi/km conversion constant to derive).
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: 'metric',
    showBoth: false,
    gallonStandard: 'us',
    // The RESOLVED set, not just the collapsed system: this component reads
    // its distance through `useUnitFormat()`, which closes over `units`.
    units: METRIC_UNITS,
  }),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
// vi.hoisted so the holder is safe to reference inside the hoisted vi.mock
// factory (the house idiom, mirrors ReminderList.test.tsx's reminderFormProps).
const reminderFormProps = vi.hoisted(() => ({ currentHours: 'UNSET' as unknown }))
vi.mock('../ReminderForm', () => ({
  default: (props: { currentHours?: number | null }) => {
    reminderFormProps.currentHours = props.currentHours
    return <div>reminder-form-open</div>
  },
}))

import ReminderList from '../ReminderList'

const hoursReminder = {
  id: 21, vin: 'V1', title: 'Hydraulic fluid change', reminder_type: 'hours', status: 'pending',
  due_date: null, due_mileage_km: null, due_hours: '812.4', estimated_due_date: null, notes: null,
  line_item_id: null, last_notified_at: null,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
} as unknown as Reminder

const mileageReminder = {
  id: 22, vin: 'V1', title: 'Oil change', reminder_type: 'mileage', status: 'pending',
  due_date: null, due_mileage_km: '80467', due_hours: null, estimated_due_date: null, notes: null,
  line_item_id: null, last_notified_at: null,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
} as unknown as Reminder

beforeEach(() => {
  vi.clearAllMocks()
  useLatestHoursMock.mockReturnValue({ data: null })
  reminderFormProps.currentHours = 'UNSET'
  useRemindersMock.mockReturnValue({ data: [], isLoading: false })
})

describe('ReminderList — hours-based reminder target rendering (Task 15)', () => {
  it('renders an hours reminder\'s "due at N hr" target (fails if the due_hours branch is missing or mis-keyed)', () => {
    useRemindersMock.mockReturnValue({ data: [hoursReminder], isLoading: false })
    render(<ReminderList vin="V1" />)

    expect(screen.getByText('Hydraulic fluid change')).toBeInTheDocument()
    expect(screen.getByText('reminderList.dueAtHours')).toBeInTheDocument()
    // no mileage target attempted on an hours reminder (due_mileage_km is null)
    expect(screen.queryByText(/km$/)).not.toBeInTheDocument()
  })

  it('renders a mileage reminder\'s target UNCHANGED (fails if the new hours branch regresses the existing mileage rendering)', () => {
    useRemindersMock.mockReturnValue({ data: [mileageReminder], isLoading: false })
    render(<ReminderList vin="V1" />)

    expect(screen.getByText('Oil change')).toBeInTheDocument()
    expect(screen.getByText('80,467 km')).toBeInTheDocument()
    // no hours target attempted on a mileage reminder (due_hours is null)
    expect(screen.queryByText('reminderList.dueAtHours')).not.toBeInTheDocument()
  })

  it('an hours reminder renders the Timer type icon, distinct from a mileage reminder\'s Gauge icon (fails if TYPE_ICONS never gained an "hours" entry — both would silently fall back to the same default icon)', () => {
    useRemindersMock.mockReturnValue({ data: [hoursReminder, mileageReminder], isLoading: false })
    const { container } = render(<ReminderList vin="V1" />)

    // lucide-react stamps `lucide-<kebab-icon-name>` on every icon's <svg> —
    // the header's own Bell icon is unrelated and out of scope here.
    expect(container.querySelector('.lucide-timer')).toBeInTheDocument()
    expect(container.querySelector('.lucide-gauge')).toBeInTheDocument()
  })
})

describe('ReminderList — wires currentHours from useLatestHours into ReminderForm (Task 15 revised, parity with currentMileage)', () => {
  it('forwards the useLatestHours value as the currentHours prop when opening the form', () => {
    useLatestHoursMock.mockReturnValue({ data: 812.4 })
    render(<ReminderList vin="V1" />)

    fireEvent.click(screen.getByRole('button', { name: 'reminderList.addReminder' }))
    expect(reminderFormProps.currentHours).toBe(812.4)
  })

  it('forwards null when useLatestHours has no reading yet', () => {
    useLatestHoursMock.mockReturnValue({ data: null })
    render(<ReminderList vin="V1" />)

    fireEvent.click(screen.getByRole('button', { name: 'reminderList.addReminder' }))
    expect(reminderFormProps.currentHours).toBeNull()
  })
})
