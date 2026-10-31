/**
 * An open odometer form keeps the vehicle's odometer unit it opened with (R4).
 *
 * A vehicle save or a list refetch can change the scope's unit while the form
 * holds a typed reading. The REAL `useUnitPreference` runs; only `AuthContext`
 * is mocked (a km account). On main the label flips to km and 50000 typed as
 * miles goes out as 50000 km.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactElement } from 'react'
import { screen, fireEvent, waitFor } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import { METRIC_UNITS } from '../../__tests__/factories'
import { VehicleUnitScope, type VehicleDistanceUnit } from '../../contexts/VehicleUnitScope'

const createMutateAsync = vi.fn().mockResolvedValue({})
vi.mock('../../hooks/queries/useOdometerRecords', () => ({
  useCreateOdometerRecord: () => ({ mutateAsync: createMutateAsync }),
  useUpdateOdometerRecord: () => ({ mutateAsync: vi.fn() }),
}))
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { unit_preference: 'metric', show_both_units: false, resolved_units: METRIC_UNITS },
    isAuthenticated: true,
    defaultUnitPrefs: null,
  }),
}))

import OdometerRecordForm from '../OdometerRecordForm'

beforeEach(() => vi.clearAllMocks())

const unitLabel = (): string =>
  document.querySelector('label[for="odometer_km"]')?.textContent ?? ''

const scoped = (unit: VehicleDistanceUnit, open = true): ReactElement => (
  <VehicleUnitScope distanceUnit={unit}>
    {open && <OdometerRecordForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />}
  </VehicleUnitScope>
)

describe('OdometerRecordForm holds the vehicle unit while open', () => {
  it('a vehicle switch from mi to km mid-form keeps miles and stores the typed miles', async () => {
    const { rerender } = render(scoped('mi'))
    expect(unitLabel()).toMatch(/\(mi\)/)

    rerender(scoped('km'))

    expect(unitLabel()).toMatch(/\(mi\)/)
    fireEvent.change(document.getElementById('date')!, { target: { value: '2026-03-01' } })
    fireEvent.change(document.getElementById('odometer_km')!, { target: { value: '50000' } })
    fireEvent.click(screen.getByRole('button', { name: 'common:create' }))
    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    // 50000 mi x 1.609344 = 80467.2 km.
    expect(createMutateAsync.mock.calls[0][0].odometer_km).toBe(80467.2)
  })

  it('guard: closing and reopening takes the new unit', () => {
    const { rerender } = render(scoped('mi'))
    rerender(scoped('km'))
    rerender(scoped('km', false))
    rerender(scoped('km'))
    expect(unitLabel()).toMatch(/\(km\)/)
    expect(unitLabel()).not.toMatch(/\(mi\)/)
  })
})
