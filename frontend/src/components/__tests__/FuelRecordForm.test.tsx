import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import FuelRecordForm from '../FuelRecordForm'
import type { Vehicle } from '../../types/vehicle'

const mockedApiGet = vi.fn()

vi.mock('../../services/api', () => ({
  default: {
    get: (...args: unknown[]) => mockedApiGet(...args),
    post: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

// Requires AuthProvider otherwise — same mock pattern as ServiceVisitForm.test.tsx
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({ system: 'metric', showBoth: false }),
}))

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: null }),
}))

function mockVehicle(overrides: Partial<Vehicle> = {}): Vehicle {
  return {
    vin: 'TEST12345678901234',
    nickname: 'Test Car',
    vehicle_type: 'Car',
    year: 2024,
    make: 'Toyota',
    model: 'Camry',
    created_at: '2024-01-15T00:00:00Z',
    archived_visible: true,
    fuel_type: 'gasoline',
    ...overrides,
  } as Vehicle
}

const DEFAULT_PROPS = {
  vin: 'TEST12345678901234',
  onClose: vi.fn(),
  onSuccess: vi.fn(),
}

describe('FuelRecordForm — DEF tank level visibility (diesel-only gate)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows the DEF tank level section for a diesel vehicle', async () => {
    mockedApiGet.mockResolvedValue({ data: mockVehicle({ fuel_type: 'diesel' }) })

    render(<FuelRecordForm {...DEFAULT_PROPS} />)

    await waitFor(() => {
      expect(screen.getByText('fuel.defTankLevel')).toBeInTheDocument()
    })
  })

  it('hides the DEF tank level section for a non-diesel vehicle even with a legacy DEF tank capacity set', async () => {
    // Pre-hardening behavior showed this section whenever def_tank_capacity_liters > 0,
    // regardless of fuel type. That arm is now unreachable for new data (the
    // server 400s the write) and the UI shouldn't invite it either.
    mockedApiGet.mockResolvedValue({
      data: mockVehicle({ fuel_type: 'gasoline', def_tank_capacity_liters: '19.0' }),
    })

    render(<FuelRecordForm {...DEFAULT_PROPS} />)

    // Wait for the vehicle fetch effect to settle before asserting absence.
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    expect(screen.queryByText('fuel.defTankLevel')).not.toBeInTheDocument()
  })

  it('hides the DEF tank level section for a plain non-diesel vehicle', async () => {
    mockedApiGet.mockResolvedValue({ data: mockVehicle({ fuel_type: 'gasoline' }) })

    render(<FuelRecordForm {...DEFAULT_PROPS} />)

    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    expect(screen.queryByText('fuel.defTankLevel')).not.toBeInTheDocument()
  })
})
