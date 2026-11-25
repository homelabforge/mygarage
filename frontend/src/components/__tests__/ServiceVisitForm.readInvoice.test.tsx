import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import ServiceVisitForm from '../ServiceVisitForm'

// "Read invoice" fills the new visit from the server's draft, and the file is
// attached to the visit once it's created. Nothing is saved by the read.

const mockedApiGet = vi.fn()
const mockedApiPost = vi.fn()

vi.mock('../../services/api', () => ({
  default: {
    get: (...args: unknown[]) => mockedApiGet(...args),
    post: (...args: unknown[]) => mockedApiPost(...args),
    put: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

// The draft's odometer is canonical km; a miles user must see and save it in miles.
const unitPrefMock = vi.hoisted(() => ({ imperial: false }))
vi.mock('../../hooks/useUnitPreference', async () => {
  const { METRIC_UNITS, IMPERIAL_UNITS } = await import('@/__tests__/factories')
  const unitPreference = () =>
    unitPrefMock.imperial
      ? { system: 'imperial', showBoth: false, units: IMPERIAL_UNITS, gallonStandard: 'us' }
      : { system: 'metric', showBoth: false, units: METRIC_UNITS, gallonStandard: 'us' }
  return { useUnitPreference: unitPreference, useAccountUnitPreference: unitPreference }
})
vi.mock('../../hooks/useReminders', () => ({
  useMaintenanceTypes: () => ({ data: [] }),
  invalidateMaintenanceQueries: () => {},
}))
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US', formatCurrency: () => '$0.00' }),
}))
vi.mock('../../hooks/queries/useSupplies', () => ({
  useSupplies: () => ({ data: { supplies: [], total: 0 }, isSuccess: true, isLoading: false, isError: false }),
  // the create hook's onSuccess calls it (#301); missing, mutateAsync rejects
  invalidateSupplyLedgers: vi.fn(),
}))
vi.mock('../../hooks/queries/useAiDocumentReading', () => ({
  useAiDocumentReading: () => ({ enabled: true, isLoading: false }),
}))
vi.mock('../VendorSearch', () => ({
  default: ({ value }: { value?: number }) => <div data-testid="vendor-search" data-value={value ?? ''} />,
}))
// The line items' recall and warranty pickers; nothing to offer here.
vi.mock('../../hooks/queries/useRecallRecords', () => ({ useRecallRecords: () => ({ data: { recalls: [] } }) }))
vi.mock('../../hooks/queries/useWarrantyRecords', () => ({ useWarrantyRecords: () => ({ data: [] }) }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const VIN = 'TEST12345678901234'

const READ = {
  source: 'text',
  model: 'qwen2.5:7b',
  warnings: [],
  draft: {
    date: '2025-11-19',
    odometer_km: '112625',
    vendor_name: 'Unlimited Auto ANGRi',
    vendor_id: 1,
    invoice_number: 'INV18499',
    currency: 'ZAR',
    tax_amount: '15.00',
    total: '115.00',
    notes: null,
    line_items: [
      { description: 'Water Pump', cost: '60.00', kind: 'part', notes: 'Part' },
      { description: 'Fit pump', cost: '40.00', kind: 'labour', notes: 'Labour' },
    ],
  },
}

const input = (id: string) => document.getElementById(id) as HTMLInputElement

describe('ServiceVisitForm: read invoice', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    unitPrefMock.imperial = false
    mockedApiGet.mockResolvedValue({ data: { usage_unit: 'distance', secondary_usage_enabled: false } })
    mockedApiPost.mockImplementation((url: string) => {
      if (url.endsWith('/read-invoice')) return Promise.resolve({ data: READ })
      if (url === `/vehicles/${VIN}/service-visits`) return Promise.resolve({ data: { id: 42 } })
      return Promise.resolve({ data: {} })
    })
  })

  it('fills the visit, then creates it and attaches the invoice', async () => {
    render(<ServiceVisitForm vin={VIN} onClose={vi.fn()} onSuccess={vi.fn()} />)
    const file = new File(['%PDF-1.4'], 'jeep.pdf', { type: 'application/pdf' })
    fireEvent.change(await screen.findByTestId('service-invoice-file'), { target: { files: [file] } })

    await waitFor(() => expect(screen.getByTestId('invoice-summary')).toBeInTheDocument())
    expect(input('service-date').value).toBe('2025-11-19')
    expect(input('service-odometer').value).toBe('112625')
    expect(input('tax-amount').value).toBe('15')
    expect(screen.getByTestId('vendor-search').dataset.value).toBe('1')
    expect(screen.getByDisplayValue('Water Pump')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Fit pump')).toBeInTheDocument()
    expect(input('invoice-number').value).toBe('INV18499')
    // Only the read: nothing created yet.
    expect(mockedApiPost).toHaveBeenCalledTimes(1)

    fireEvent.submit(screen.getByRole('dialog').querySelector('form') as HTMLFormElement)

    await waitFor(() =>
      expect(mockedApiPost).toHaveBeenCalledWith('/service-visits/42/attachments', expect.any(FormData), expect.anything())
    )
    const created = mockedApiPost.mock.calls.find(([url]) => url === `/vehicles/${VIN}/service-visits`)?.[1]
    expect(created).toMatchObject({
      date: '2025-11-19',
      vendor_id: 1,
      odometer_km: 112625,
      tax_amount: 15,
      invoice_number: 'INV18499',
    })
    // The blank starting line was replaced, not kept.
    expect(created.line_items.map((l: { description: string; cost?: number }) => [l.description, l.cost])).toEqual([
      ['Water Pump', 60],
      ['Fit pump', 40],
    ])
  })

  it('does not attach the invoice when unticked', async () => {
    render(<ServiceVisitForm vin={VIN} onClose={vi.fn()} onSuccess={vi.fn()} />)
    const file = new File(['%PDF-1.4'], 'jeep.pdf', { type: 'application/pdf' })
    fireEvent.change(await screen.findByTestId('service-invoice-file'), { target: { files: [file] } })
    await waitFor(() => expect(screen.getByTestId('invoice-summary')).toBeInTheDocument())

    fireEvent.click(document.getElementById('attach-invoice') as HTMLInputElement)
    fireEvent.submit(screen.getByRole('dialog').querySelector('form') as HTMLFormElement)

    await waitFor(() =>
      expect(mockedApiPost).toHaveBeenCalledWith(`/vehicles/${VIN}/service-visits`, expect.anything())
    )
    expect(mockedApiPost.mock.calls.some(([url]) => String(url).includes('/attachments'))).toBe(false)
  })

  it('shows a miles user the odometer in miles and saves it back as km', async () => {
    unitPrefMock.imperial = true
    render(<ServiceVisitForm vin={VIN} onClose={vi.fn()} onSuccess={vi.fn()} />)
    const file = new File(['%PDF-1.4'], 'jeep.pdf', { type: 'application/pdf' })
    fireEvent.change(await screen.findByTestId('service-invoice-file'), { target: { files: [file] } })
    await waitFor(() => expect(screen.getByTestId('invoice-summary')).toBeInTheDocument())

    // 112 625 km = 69 981.9 mi
    expect(Math.round(Number(input('service-odometer').value))).toBe(69982)

    fireEvent.submit(screen.getByRole('dialog').querySelector('form') as HTMLFormElement)
    await waitFor(() =>
      expect(mockedApiPost).toHaveBeenCalledWith(`/vehicles/${VIN}/service-visits`, expect.anything())
    )
    const created = mockedApiPost.mock.calls.find(([url]) => url === `/vehicles/${VIN}/service-visits`)?.[1]
    // Back to km within the displayed precision, not the mile figure sent as km.
    expect(Math.abs(created.odometer_km - 112625)).toBeLessThan(1.7)
  })
})
