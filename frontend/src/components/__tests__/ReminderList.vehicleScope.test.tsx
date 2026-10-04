/**
 * #192's distance-left text on a mi vehicle under a km account (#172). Only
 * AuthContext is mocked, so the REAL useUnitPreference reads the vehicle scope.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import { METRIC_UNITS } from '../../__tests__/factories'
import { VehicleUnitScope } from '../../contexts/VehicleUnitScope'
import type { Reminder } from '../../types/reminder'

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
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { unit_preference: 'metric', show_both_units: false, resolved_units: METRIC_UNITS },
    isAuthenticated: true,
    defaultUnitPrefs: null,
  }),
}))
const DUE_SOON = {
  id: 2, vin: 'V1', title: 'Oil change', reminder_type: 'mileage', status: 'pending',
  due_date: null, due_mileage_km: null, due_hours: null, estimated_due_date: null,
  projected_usage_date: null, snoozed_until: null, notes: null, line_item_id: null,
  last_notified_at: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  due_status: 'due_soon', progress: 0.9, progress_basis: 'distance',
  days_until_due: null, km_until_due: '1995.59', hours_until_due: null,
} as unknown as Reminder
vi.mock('../../hooks/useReminders', () => ({
  useReminders: () => ({ data: [DUE_SOON], isLoading: false }),
  useMarkReminderDismissed: () => ({ mutateAsync: vi.fn() }),
  useDeleteReminder: () => ({ mutateAsync: vi.fn() }),
  useReminderDuplicates: () => ({ data: [] }),
  useReminderPacks: () => ({ data: [] }),
  useDeletePack: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))
vi.mock('../../hooks/useLatestMileage', () => ({ useLatestMileage: () => ({ data: null }) }))
vi.mock('../../hooks/useLatestHours', () => ({ useLatestHours: () => ({ data: null }) }))
vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => 'en-US' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import ReminderList from '../ReminderList'

describe('ReminderList inside a mi vehicle on a km account', () => {
  it('says what is left in the vehicle\'s miles, not the account\'s km', () => {
    render(
      <VehicleUnitScope distanceUnit="mi">
        <ReminderList vin="V1" />
      </VehicleUnitScope>,
    )
    expect(screen.getByText('reminderList.distanceLeft|1,240 mi')).toBeInTheDocument()
    expect(screen.queryByText('reminderList.distanceLeft|1,996 km')).not.toBeInTheDocument()
  })
})
