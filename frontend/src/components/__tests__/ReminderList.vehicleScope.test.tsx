/**
 * #192's distance-left text on a mi vehicle under a km account (#172). Only
 * AuthContext is mocked, so the REAL useUnitPreference reads the vehicle scope.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import { METRIC_UNITS } from '../../__tests__/factories'
import { VehicleUnitScope } from '../../contexts/VehicleUnitScope'
import type { Reminder } from '../../types/reminder'
import { NO_READING, makeReminder, makeVehicle, reminderHooks } from './helpers/reminderListHarness'

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
const DUE_SOON = vi.hoisted((): Partial<Reminder> => ({
  id: 2, title: 'Oil change', due_status: 'due_soon', progress: 0.9, progress_basis: 'distance',
  km_until_due: '1995.59',
}))
vi.mock('../../hooks/useReminders', () => {
  const data = [makeReminder(DUE_SOON)]
  return reminderHooks({ useReminders: () => ({ data, isLoading: false }) })
})
vi.mock('../../hooks/useLatestMileage', () => ({ useLatestMileage: () => NO_READING }))
vi.mock('../../hooks/useLatestHours', () => ({ useLatestHours: () => NO_READING }))
vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => 'en-US' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import ReminderList from '../ReminderList'

describe('ReminderList inside a mi vehicle on a km account', () => {
  it('says what is left in the vehicle\'s miles, not the account\'s km', () => {
    render(
      <VehicleUnitScope distanceUnit="mi">
        <ReminderList vehicle={makeVehicle()} />
      </VehicleUnitScope>,
    )
    expect(screen.getByText('reminderList.distanceLeft|1,240 mi')).toBeInTheDocument()
    expect(screen.queryByText('reminderList.distanceLeft|1,996 km')).not.toBeInTheDocument()
  })
})
