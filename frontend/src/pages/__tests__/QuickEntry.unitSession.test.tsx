/**
 * A Quick Entry form keeps the odometer unit it opened with (#172).
 *
 * The vehicle list refetches in the background (30 s stale, on focus), so a
 * unit changed on another device can arrive while a form holds typed text; a
 * form that re-read it would convert typed miles as kilometres. The REAL
 * `useUnitPreference` runs here (only `AuthContext` is mocked), and the
 * odometer form is replaced by a probe that records the unit on EVERY render,
 * so a capture that flips after the first frame is caught too.
 *
 * The real forms pin themselves now (R4), so the probe wraps itself the same
 * way and Quick Entry only hands down a live, keyed scope.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, useNavigate } from 'react-router-dom'
import { METRIC_UNITS } from '../../__tests__/factories'

const h = vi.hoisted(() => ({
  vehicles: [] as Array<Record<string, unknown>>,
  seen: [] as string[],
}))

vi.mock('../../hooks/queries/useQuickEntryVehicles', () => ({
  useQuickEntryVehicles: () => ({
    data: h.vehicles,
    isLoading: false,
    isError: false,
    isFetching: false,
    refetch: vi.fn(),
  }),
}))
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 1, unit_preference: 'metric', show_both_units: false, resolved_units: METRIC_UNITS },
    isAuthenticated: true,
    defaultUnitPrefs: null,
  }),
}))
vi.mock('../../components/OdometerRecordForm', async () => {
  const { useUnitPreference } = await import('../../hooks/useUnitPreference')
  const { withUnitSession } = await import('../../contexts/UnitSession')
  return {
    default: withUnitSession(function OdometerProbe({ onClose }: { onClose: () => void }) {
      const unit = useUnitPreference().units.distance
      h.seen.push(unit)
      return (
        <div>
          <span>{`form:odometer:${unit}`}</span>
          <button onClick={onClose}>close-form</button>
        </div>
      )
    }),
  }
})
vi.mock('../../components/FuelRecordForm', () => ({ default: () => <div>form:fuel</div> }))
vi.mock('../../components/PropaneRecordForm', () => ({ default: () => <div>form:propane</div> }))
vi.mock('../../components/DEFRecordForm', () => ({ default: () => <div>form:def</div> }))
vi.mock('../../components/ServiceVisitForm', () => ({ default: () => <div>form:service</div> }))
vi.mock('../../components/HoursRecordForm', () => ({ default: () => <div>form:hours</div> }))

import QuickEntry from '../QuickEntry'

const VIN = 'VIN00000000000001'
const VIN2 = 'VIN00000000000002'
const vehicle = (distance_unit: 'km' | 'mi' | null, vin = VIN) => ({
  vin,
  nickname: 'Test',
  year: 2023,
  make: 'Make',
  model: 'Model',
  vehicle_type: 'Car',
  usage_unit: 'distance',
  secondary_usage_enabled: false,
  fuel_type: 'gasoline',
  fuel_type_secondary: null,
  thumbnail_url: null,
  distance_unit,
})

/** A button that follows a deep link, the way a PWA shortcut would. */
function GoTo({ to }: { to: string }) {
  const navigate = useNavigate()
  return <button onClick={() => navigate(to)}>go</button>
}

const page = (url: string, next?: string) => (
  <MemoryRouter initialEntries={[url]}>
    <QuickEntry />
    {next && <GoTo to={next} />}
  </MemoryRouter>
)

beforeEach(() => {
  h.vehicles = []
  h.seen = []
})

describe('a Quick Entry form keeps the unit it opened with', () => {
  it("a deep link opens straight into the vehicle's unit, never a frame in the account's", () => {
    h.vehicles = [vehicle('mi')]
    render(page(`/quick-entry?action=odometer&vin=${VIN}`))

    expect(screen.getByText('form:odometer:mi')).toBeInTheDocument()
    expect(h.seen.length).toBeGreaterThan(0)
    expect(h.seen.every((unit) => unit === 'mi')).toBe(true)
  })

  it('a refetch that changes the unit leaves the open form alone; the next form takes it', () => {
    h.vehicles = [vehicle('mi')]
    const { rerender } = render(page(`/quick-entry?action=odometer&vin=${VIN}`))
    expect(screen.getByText('form:odometer:mi')).toBeInTheDocument()

    // Another device switched the vehicle to km, and the list refetched.
    h.vehicles = [vehicle('km')]
    rerender(page(`/quick-entry?action=odometer&vin=${VIN}`))
    expect(screen.getByText('form:odometer:mi')).toBeInTheDocument()

    // Close it and open the odometer entry again: now in km.
    fireEvent.click(screen.getByText('close-form'))
    fireEvent.click(screen.getByText('quickEntry.mileage'))
    expect(screen.getByText('form:odometer:km')).toBeInTheDocument()
  })

  it('guard: a deep link that swaps the vehicle under an open form remounts it in the new unit', () => {
    // The key on Quick Entry's scope is what does this. The probe pins itself,
    // so without the key it would keep the first vehicle's miles.
    h.vehicles = [vehicle('mi'), vehicle('km', VIN2)]
    render(page(`/quick-entry?action=odometer&vin=${VIN}`, `/quick-entry?action=odometer&vin=${VIN2}`))
    expect(screen.getByText('form:odometer:mi')).toBeInTheDocument()

    fireEvent.click(screen.getByText('go'))
    expect(screen.getByText('form:odometer:km')).toBeInTheDocument()
  })
})
