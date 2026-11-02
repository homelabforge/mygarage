/**
 * The Reminders-tab notice (#211): shown only while the vehicle's country has
 * a periodic inspection and the first registration date is blank.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { Vehicle } from '../../types/vehicle'

const state = vi.hoisted(() => ({ country: null as string | null, profile: null as unknown }))

vi.mock('@/hooks/useResolvedCountry', () => ({
  useResolvedCountry: () => state.country,
}))
vi.mock('@/hooks/queries/useCountryProfile', () => ({
  useCountryProfile: (country: string | null) => ({ data: country ? state.profile : undefined }),
}))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { name?: string }) => (options?.name ? `${key}:${options.name}` : key),
  }),
}))

import InspectionScheduleNotice from '../InspectionScheduleNotice'

const vehicle = (overrides: Partial<Vehicle> = {}): Vehicle =>
  ({ vin: 'V1', nickname: 'Car', vehicle_type: 'Car', first_registration_date: null, ...overrides }) as Vehicle

beforeEach(() => {
  state.country = 'FR'
  state.profile = { country: 'FR', inspection: { name: 'Contrôle technique' } }
})

describe('InspectionScheduleNotice', () => {
  it('asks for the first registration date when the country has an inspection', () => {
    render(<InspectionScheduleNotice vehicle={vehicle()} />)
    expect(screen.getByRole('note')).toHaveTextContent(
      'reminderList.inspectionNeedsDate:Contrôle technique'
    )
  })

  it('shows nothing once the date is set, or for an archived vehicle', () => {
    const { unmount } = render(
      <InspectionScheduleNotice vehicle={vehicle({ first_registration_date: '2023-03-12' })} />
    )
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
    unmount()
    render(<InspectionScheduleNotice vehicle={vehicle({ archived_at: '2026-01-01T00:00:00Z' })} />)
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
  })

  it('shows nothing without a country, or for a country without an inspection', () => {
    state.country = null
    const { unmount } = render(<InspectionScheduleNotice vehicle={vehicle()} />)
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
    unmount()
    state.country = 'US'
    state.profile = null
    render(<InspectionScheduleNotice vehicle={vehicle()} />)
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
  })
})
