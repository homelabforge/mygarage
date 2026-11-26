import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import ServiceVisitForm from '../ServiceVisitForm'

// A new visit's items carry temp ids so a repair can name the inspection that
// triggered it before either is saved. The first item and the next one added
// must never share one, or the repair links to the wrong row (or itself).

const drawerForm = (): HTMLFormElement =>
  screen.getByRole('dialog').querySelector('form') as HTMLFormElement

const mockedApiGet = vi.fn()
const mockedApiPost = vi.fn().mockResolvedValue({ data: {} })

vi.mock('../../services/api', () => ({
  default: {
    get: (...args: unknown[]) => mockedApiGet(...args),
    post: (...args: unknown[]) => mockedApiPost(...args),
    put: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

vi.mock('../../hooks/useUnitPreference', async () => {
  const { METRIC_UNITS } = await import('@/__tests__/factories')
  // UnitSession reads the account half too; same answer, nothing to pin here.
  const unitPreference = () => ({
    system: 'metric',
    showBoth: false,
    units: METRIC_UNITS,
    gallonStandard: 'us',
  })
  return {
    useUnitPreference: unitPreference,
    useAccountUnitPreference: unitPreference,
  }
})
vi.mock('../../hooks/useReminders', () => ({
  useMaintenanceTypes: () => ({ data: [] }),
  invalidateMaintenanceQueries: () => {},
}))
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({
    currencyCode: 'USD',
    locale: 'en-US',
    formatCurrency: () => '$0.00',
  }),
}))
vi.mock('../../hooks/queries/useSupplies', () => ({
  useSupplies: () => ({
    data: { supplies: [], total: 0 },
    isSuccess: true,
    isLoading: false,
    isError: false,
  }),
}))
// The real VendorSearch clears through onSelect(null); this stand-in does the same.
// The line items' recall and warranty pickers; nothing to offer here.
vi.mock('../../hooks/queries/useRecallRecords', () => ({ useRecallRecords: () => ({ data: { recalls: [] } }) }))
vi.mock('../../hooks/queries/useWarrantyRecords', () => ({ useWarrantyRecords: () => ({ data: [] }) }))
vi.mock('../VendorSearch', () => ({
  default: ({ value, onSelect }: { value?: number; onSelect: (v: null) => void }) => (
    <div data-testid="vendor-search" data-value={value ?? ''}>
      <button type="button" onClick={() => onSelect(null)}>clear vendor</button>
    </div>
  ),
}))
vi.mock('../ServiceVisitAttachmentUpload', () => ({
  default: () => <div data-testid="attachment-upload" />,
}))
vi.mock('../ServiceVisitAttachmentList', () => ({
  default: () => <div data-testid="attachment-list" />,
}))
vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}))

const VIN = 'TEST12345678901234'

const found = (el: Element | null | undefined): Element => {
  if (!el) throw new Error('control not found')
  return el
}

describe('ServiceVisitForm: temp ids on a new visit', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedApiPost.mockResolvedValue({ data: {} })
    mockedApiGet.mockResolvedValue({ data: { usage_unit: 'distance', secondary_usage_enabled: false } })
  })

  // Mutation: start nextTempIdRef at -1 for a new visit too, and the repair
  // takes the inspection's -1, so both ids below come out equal.
  it('gives a repair its own temp id and links it to the first item', async () => {
    render(<ServiceVisitForm vin={VIN} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await waitFor(() => expect(screen.getAllByText('lineItemEditor.misc.descriptionLabel')).toHaveLength(1))

    const description = found(screen.getAllByText('lineItemEditor.misc.descriptionLabel')[0].parentElement?.querySelector('input[type="text"]'))
    fireEvent.change(description, { target: { value: 'Brake inspection' } })
    fireEvent.click(document.getElementById('inspection-0') as HTMLInputElement)
    fireEvent.click(screen.getByRole('button', { name: 'inspectionResult.resultFailed' }))
    fireEvent.click(screen.getByRole('button', { name: 'service.addRepairForInspection' }))
    expect(screen.getByDisplayValue('Repair: Brake inspection')).toBeInTheDocument()

    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
    const items = (mockedApiPost.mock.calls.at(-1)?.[1] as { line_items: Record<string, unknown>[] }).line_items

    expect(items.map((li) => li.description)).toEqual(['Brake inspection', 'Repair: Brake inspection'])
    expect(items[0].temp_id).toBe(-1)
    expect(items[1].temp_id).toBe(-2)
    expect(items[1].triggered_by_inspection_id).toBe(-1)
  })
})
