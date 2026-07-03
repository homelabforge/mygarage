import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { DEFRecord } from '../../types/def'

// Mock the DEF query hooks so this stays a unit test — no QueryClient/api wiring.
const useDEFRecordsMock = vi.fn()
const useDEFAnalyticsMock = vi.fn()
const useDeleteDEFRecordMock = vi.fn()

vi.mock('../../hooks/queries/useDEFRecords', () => ({
  useDEFRecords: () => useDEFRecordsMock(),
  useDEFAnalytics: () => useDEFAnalyticsMock(),
  useDeleteDEFRecord: () => useDeleteDEFRecordMock(),
  useCreateDEFRecord: () => ({ mutateAsync: vi.fn() }),
  useUpdateDEFRecord: () => ({ mutateAsync: vi.fn() }),
}))

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))

// Same mock pattern as VehicleEdit.test.tsx — these hooks need AuthProvider
// otherwise, and it's not under test here.
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({ system: 'metric', showBoth: false }),
}))
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({
    currencyCode: 'USD',
    locale: 'en-US',
    formatCurrency: () => '$0.00',
  }),
}))

import DEFRecordList from '../DEFRecordList'

const mockRecord: DEFRecord = {
  id: 1,
  vin: 'TEST12345678901234',
  date: '2026-02-10',
  entry_type: 'purchase',
  liters: '20.820',
  odometer_km: '88514',
  fill_level: '1.00',
  cost: '24.75',
  price_per_unit: '1.189',
  source: 'Truck Stop / Station Nozzle',
  brand: 'BlueDEF',
  notes: null,
  origin_fuel_record_id: null,
  created_at: '2026-02-10T14:30:00',
} as DEFRecord

beforeEach(() => {
  vi.clearAllMocks()
  useDEFRecordsMock.mockReturnValue({
    data: { records: [mockRecord] },
    isLoading: false,
    error: null,
  })
  useDEFAnalyticsMock.mockReturnValue({ data: undefined })
  useDeleteDEFRecordMock.mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
    variables: undefined,
  })
})

describe('DEFRecordList — readOnly gating (non-diesel vehicles)', () => {
  it('shows the read-only notice and hides add/edit affordances when readOnly', () => {
    render(<DEFRecordList vin="TEST12345678901234" readOnly />)

    expect(screen.getByText('defList.readOnlyNotice')).toBeInTheDocument()
    expect(screen.queryByText('defList.addDEF')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('common:edit')).not.toBeInTheDocument()
    // Delete stays available so bad legacy data can still be removed.
    expect(screen.getByLabelText('common:delete')).toBeInTheDocument()
  })

  it('hides the "add first record" button in the empty state when readOnly', () => {
    useDEFRecordsMock.mockReturnValue({
      data: { records: [] },
      isLoading: false,
      error: null,
    })

    render(<DEFRecordList vin="TEST12345678901234" readOnly />)

    expect(screen.getByText('defList.readOnlyNotice')).toBeInTheDocument()
    expect(screen.queryByText('defList.addFirstRecord')).not.toBeInTheDocument()
  })

  it('shows add/edit affordances and no notice when not readOnly (diesel)', () => {
    render(<DEFRecordList vin="TEST12345678901234" />)

    expect(screen.queryByText('defList.readOnlyNotice')).not.toBeInTheDocument()
    expect(screen.getByText('defList.addDEF')).toBeInTheDocument()
    expect(screen.getByLabelText('common:edit')).toBeInTheDocument()
    expect(screen.getByLabelText('common:delete')).toBeInTheDocument()
  })
})
