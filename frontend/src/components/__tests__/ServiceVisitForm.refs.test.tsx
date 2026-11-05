import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, fireEvent, within } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import ServiceVisitForm from '../ServiceVisitForm'
import type { ServiceVisit } from '../../types/serviceVisit'

// The four reference numbers hide behind chips. A chip that was never on must
// stay out of an edit's PUT, or a hidden stored value gets wiped (D6).

const drawerForm = (): HTMLFormElement =>
  screen.getByRole('dialog').querySelector('form') as HTMLFormElement

const mockedApiGet = vi.fn()
const mockedApiPost = vi.fn().mockResolvedValue({ data: {} })
const mockedApiPut = vi.fn().mockResolvedValue({ data: {} })

vi.mock('../../services/api', () => ({
  default: {
    get: (...args: unknown[]) => mockedApiGet(...args),
    post: (...args: unknown[]) => mockedApiPost(...args),
    put: (...args: unknown[]) => mockedApiPut(...args),
  },
}))

vi.mock('../../hooks/useUnitPreference', async () => {
  const { METRIC_UNITS } = await import('@/__tests__/factories')
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
// The line items' recall and warranty pickers; nothing to offer here.
vi.mock('../../hooks/queries/useRecallRecords', () => ({ useRecallRecords: () => ({ data: { recalls: [] } }) }))
vi.mock('../../hooks/queries/useWarrantyRecords', () => ({ useWarrantyRecords: () => ({ data: [] }) }))
vi.mock('../VendorSearch', () => ({
  default: () => <div data-testid="vendor-search" />,
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

const visit = {
  id: 900,
  vin: VIN,
  date: '2026-07-01',
  created_at: '2026-07-01T00:00:00',
  calculated_total_cost: '0.00',
  has_failed_inspections: false,
  line_item_count: 1,
  subtotal: '0.00',
  vendor_id: null,
  odometer_km: null,
  engine_hours: null,
  notes: null,
  insurance_claim_number: null,
  invoice_number: null,
  po_number: 'PO-77',
  work_order_number: null,
  tax_amount: null,
  shop_supplies: null,
  misc_fees: null,
  service_category: null,
  total_cost: '0.00',
  updated_at: null,
  vendor: null,
  line_items: [
    {
      id: 501,
      visit_id: 900,
      description: 'Oil change',
      category: 'Maintenance',
      cost: null,
      created_at: '2026-07-01T00:00:00',
      is_failed_inspection: false,
      is_inspection: false,
      needs_followup: false,
      notes: null,
      triggered_by_inspection_id: null,
      supply_usages: [],
    },
  ],
} as unknown as ServiceVisit

const REF_INPUTS = ['insurance-claim', 'invoice-number', 'po-number', 'work-order-number']

const chip = (name: string): HTMLElement => screen.getByRole('button', { name })
const input = (id: string): HTMLInputElement | null => document.getElementById(id) as HTMLInputElement | null

async function renderNew(): Promise<void> {
  mockedApiGet.mockResolvedValue({ data: { usage_unit: 'distance', secondary_usage_enabled: false } })
  render(<ServiceVisitForm vin={VIN} onClose={vi.fn()} onSuccess={vi.fn()} />)
  await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
  const description = screen
    .getAllByText('lineItemEditor.misc.descriptionLabel')[0]
    .parentElement?.querySelector('input[type="text"]') as HTMLInputElement
  fireEvent.change(description, { target: { value: 'Oil change' } })
}

async function renderEdit(v: ServiceVisit = visit): Promise<void> {
  mockedApiGet.mockResolvedValue({ data: { usage_unit: 'distance', secondary_usage_enabled: false } })
  render(<ServiceVisitForm vin={VIN} visit={v} onClose={vi.fn()} onSuccess={vi.fn()} />)
  await waitFor(() => expect(screen.getByRole('button', { name: 'common:update' })).toBeEnabled())
}

async function created(): Promise<Record<string, unknown>> {
  fireEvent.submit(drawerForm())
  await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
  return mockedApiPost.mock.calls.at(-1)?.[1] as Record<string, unknown>
}

async function updated(): Promise<Record<string, unknown>> {
  fireEvent.submit(drawerForm())
  await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
  return mockedApiPut.mock.calls.at(-1)?.[1] as Record<string, unknown>
}

describe('ServiceVisitForm: reference number chips', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedApiPost.mockResolvedValue({ data: {} })
    mockedApiPut.mockResolvedValue({ data: {} })
  })

  it('a new visit shows four chips, all off, and no ref inputs', async () => {
    await renderNew()

    const group = screen.getByRole('group', { name: 'service.refs.toggleLabel' })
    for (const name of ['service.refs.insuranceClaim', 'service.refs.invoice', 'service.refs.po', 'service.refs.workOrder']) {
      expect(within(group).getByRole('button', { name })).toHaveAttribute('aria-pressed', 'false')
    }
    for (const id of REF_INPUTS) expect(input(id)).toBeNull()
  })

  it('turning Invoice on shows its input; create sends it and null for the rest', async () => {
    await renderNew()

    fireEvent.click(chip('service.refs.invoice'))
    expect(chip('service.refs.invoice')).toHaveAttribute('aria-pressed', 'true')
    expect(input('invoice-number')).toHaveAttribute('placeholder', 'service.refs.invoicePlaceholder')
    fireEvent.change(input('invoice-number') as HTMLInputElement, { target: { value: '4CCS403925' } })

    const body = await created()
    expect(body).toHaveProperty('invoice_number', '4CCS403925')
    expect(body).toHaveProperty('insurance_claim_number', null)
    expect(body).toHaveProperty('po_number', null)
    expect(body).toHaveProperty('work_order_number', null)
  })

  it('edit: a stored PO turns its chip on; an untouched save omits the hidden refs', async () => {
    await renderEdit()

    expect(chip('service.refs.po')).toHaveAttribute('aria-pressed', 'true')
    expect(input('po-number')).toHaveValue('PO-77')
    expect(chip('service.refs.invoice')).toHaveAttribute('aria-pressed', 'false')
    expect(input('invoice-number')).toBeNull()

    const body = await updated()
    expect(body).toHaveProperty('po_number', 'PO-77')
    expect(body).not.toHaveProperty('invoice_number')
    expect(body).not.toHaveProperty('work_order_number')
    expect(body).not.toHaveProperty('insurance_claim_number')
  })

  it('edit: turning the PO chip off sends po_number null', async () => {
    await renderEdit()

    fireEvent.click(chip('service.refs.po'))
    expect(input('po-number')).toBeNull()

    const body = await updated()
    expect(body).toHaveProperty('po_number', null)
  })

  it('edit: a chip turned on and off again still sends null', async () => {
    await renderEdit()

    fireEvent.click(chip('service.refs.workOrder'))
    fireEvent.change(input('work-order-number') as HTMLInputElement, { target: { value: 'WO-1' } })
    fireEvent.click(chip('service.refs.workOrder'))

    const body = await updated()
    expect(body).toHaveProperty('work_order_number', null)
  })

  it.each([
    ['service.refs.insuranceClaim', 'insurance-claim', 'common:validation.serviceVisit.insuranceClaimNumberTooLong'],
    ['service.refs.invoice', 'invoice-number', 'common:validation.serviceVisit.invoiceNumberTooLong'],
    ['service.refs.po', 'po-number', 'common:validation.serviceVisit.poNumberTooLong'],
    ['service.refs.workOrder', 'work-order-number', 'common:validation.serviceVisit.workOrderNumberTooLong'],
  ])('%s refuses 51 characters with its own message', async (chipName, id, message) => {
    await renderNew()

    fireEvent.click(chip(chipName))
    fireEvent.change(input(id) as HTMLInputElement, { target: { value: 'x'.repeat(51) } })
    fireEvent.submit(drawerForm())

    expect(await screen.findByText(message)).toHaveAttribute('id', `${id}-error`)
    expect(mockedApiPost).not.toHaveBeenCalled()
  })

  it('50 characters is fine', async () => {
    await renderNew()

    fireEvent.click(chip('service.refs.po'))
    fireEvent.change(input('po-number') as HTMLInputElement, { target: { value: 'x'.repeat(50) } })

    const body = await created()
    expect(body).toHaveProperty('po_number', 'x'.repeat(50))
  })
})

describe('ServiceVisitForm: a server 422 on a ref', () => {
  const axios422 = (field: string, msg: string): unknown => ({
    isAxiosError: true,
    message: 'Request failed with status code 422',
    response: { status: 422, data: { detail: [{ type: 'string_too_long', loc: ['body', field], msg }] } },
  })

  beforeEach(() => {
    vi.clearAllMocks()
    mockedApiPut.mockResolvedValue({ data: {} })
  })

  it('lands on its input', async () => {
    mockedApiPut.mockRejectedValueOnce(axios422('po_number', 'PO number too long'))
    await renderEdit()

    fireEvent.submit(drawerForm())

    expect(await screen.findByText('PO number too long')).toHaveAttribute('id', 'po-number-error')
  })

  it('turns a hidden chip on so the message has somewhere to show', async () => {
    mockedApiPut.mockRejectedValueOnce(axios422('invoice_number', 'Invoice number too long'))
    await renderEdit()

    fireEvent.submit(drawerForm())

    expect(await screen.findByText('Invoice number too long')).toHaveAttribute('id', 'invoice-number-error')
    expect(chip('service.refs.invoice')).toHaveAttribute('aria-pressed', 'true')
  })
})
