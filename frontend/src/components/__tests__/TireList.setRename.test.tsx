import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

// Mock the query hooks so this stays a unit test - no QueryClient/api wiring.
const useTiresMock = vi.fn()
const { WINTERS } = vi.hoisted(() => ({
  WINTERS: { id: 9, vin: '1HGCM82633A004352', name: 'Winters', notes: null, tire_ids: [], mounted_count: 0 },
}))
const useUpsertTireMock = vi.fn()
const useAddTireReadingMock = vi.fn()
const useDeleteTireMock = vi.fn()

// v3.3.0 split the single upsert into create-and-mount plus update, and added
// mount/dismount. The old `useUpsertTire` name is kept for the mock variable
// because every assertion below is about the payload a save produces, and that
// payload is now create-and-mount's.
vi.mock('../../hooks/queries/useTires', () => ({
  useTires: () => useTiresMock(),
  useCreateAndMountTire: () => useUpsertTireMock(),
  useCreateTire: () => useUpsertTireMock(),
  useUpdateTire: () => useUpsertTireMock(),
  useMountTire: () => useUpsertTireMock(),
  useDismountTire: () => useUpsertTireMock(),
  useRestoreTire: () => useUpsertTireMock(),
  useRetireTire: () => useUpsertTireMock(),
  useRotateTires: () => useUpsertTireMock(),
  useAddTireReading: () => useAddTireReadingMock(),
  useDeleteTire: () => useDeleteTireMock(),
  useDeleteTireReading: () => ({ mutate: vi.fn(), isPending: false }),
  // Sets are not this file's subject; it just has to render past them.
  useTireSets: () => ({ data: { sets: [WINTERS], total: 1 }, isLoading: false, error: null }),
  useCreateTireSet: () => useUpsertTireMock(),
  useUpdateTireSet: () => useUpsertTireMock(),
  useDeleteTireSet: () => useUpsertTireMock(),
  useMountTireSet: () => useUpsertTireMock(),
}))

vi.mock('../../hooks/queries/useOdometerRecords', () => ({
  useNearestOdometer: () => ({ data: undefined, isSuccess: false }),
}))

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))

// useUnitPreference calls useAuth, which throws outside an AuthProvider, and the
// shared renderer does not supply one. Imperial is what exercises conversion.
//
// The resolved set is written out here rather than imported from the factories,
// so this file states the units it is asserting against. `useUnitFormat` is NOT
// mocked: the conversions below are the real adapters running.
vi.mock('../../hooks/useUnitPreference', () => {
  // UnitSession reads the account half too; same answer, nothing to pin here.
  const unitPreference = () => ({
    system: 'imperial',
    showBoth: false,
    gallonStandard: 'us',
    units: {
      distance: 'mi',
      speed: 'mph',
      length: 'ft',
      volume: 'gal_us',
      consumption: 'mpg_us',
      pressure: 'psi',
      temperature: 'f',
      mass: 'lb',
      torque: 'lbft',
      tread: 'in32',
      secondary_gallon: 'us',
    },
  })
  return {
    useUnitPreference: unitPreference,
    useAccountUnitPreference: unitPreference,
  }
})

import TireList from '../TireList'

describe('TireList: renaming a tire set', () => {
  beforeEach(() => {
    useUpsertTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useAddTireReadingMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useDeleteTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useTiresMock.mockReturnValue({ data: { tires: [], total: 0 }, isLoading: false, error: null })
  })

  it('a blank name shows an inline error instead of doing nothing', () => {
    const mutate = vi.fn()
    useUpsertTireMock.mockReturnValue({ mutate, isPending: false })
    render(<TireList vin="1HGCM82633A004352" />)
    fireEvent.click(screen.getByRole('button', { name: 'tireList.sets' }))
    fireEvent.click(screen.getByRole('button', { name: 'tireList.setRename' }))
    fireEvent.change(document.getElementById('set-rename-9') as HTMLInputElement, { target: { value: '  ' } })
    fireEvent.click(screen.getByRole('button', { name: 'common:save' }))
    expect(screen.getByText('common:validation.tireSet.nameRequired')).toBeInTheDocument()
    expect(mutate).not.toHaveBeenCalled()
  })
})
