import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import ServiceVisitForm from '../ServiceVisitForm'
import type { ServiceVisit } from '../../types/serviceVisit'

// Clearing a field on edit has to reach the API as null. The update route
// drops keys that aren't sent (exclude_unset), so an undefined here kept the
// old vendor, notes, fees and readings no matter what the form showed.

const drawerForm = (): HTMLFormElement =>
  screen.getByRole('dialog').querySelector('form') as HTMLFormElement

const mockedApiGet = vi.fn()
const mockedApiPut = vi.fn().mockResolvedValue({ data: {} })

vi.mock('../../services/api', () => ({
  default: {
    get: (...args: unknown[]) => mockedApiGet(...args),
    post: vi.fn().mockResolvedValue({ data: {} }),
    put: (...args: unknown[]) => mockedApiPut(...args),
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

const visit = {
  id: 900,
  vin: VIN,
  date: '2026-07-01',
  created_at: '2026-07-01T00:00:00',
  calculated_total_cost: '0.00',
  has_failed_inspections: false,
  line_item_count: 1,
  subtotal: '0.00',
  vendor_id: 7,
  odometer_km: '72420.0',
  engine_hours: '640.5',
  notes: 'Old notes',
  insurance_claim_number: 'CLM-1',
  invoice_number: 'INV-1',
  po_number: 'PO-1',
  work_order_number: 'WO-1',
  tax_amount: '4.50',
  shop_supplies: '3.25',
  misc_fees: '2.00',
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

// An inspection (601) and the repair it triggered (602).
const inspectionVisit = {
  ...visit,
  line_item_count: 2,
  line_items: [
    {
      id: 601,
      visit_id: 900,
      description: 'Brake inspection',
      category: 'Inspection',
      cost: null,
      created_at: '2026-07-01T00:00:00',
      is_failed_inspection: true,
      is_inspection: true,
      inspection_result: 'failed',
      inspection_severity: 'red',
      needs_followup: true,
      notes: null,
      triggered_by_inspection_id: null,
      supply_usages: [],
    },
    {
      id: 602,
      visit_id: 900,
      description: 'Front pads',
      category: 'Maintenance',
      cost: '80.00',
      created_at: '2026-07-01T00:00:00',
      is_failed_inspection: false,
      is_inspection: false,
      needs_followup: false,
      notes: 'Old item notes',
      triggered_by_inspection_id: 601,
      supply_usages: [],
    },
  ],
} as unknown as ServiceVisit

const input = (id: string) => document.getElementById(id) as HTMLInputElement

const found = (el: Element | null | undefined): Element => {
  if (!el) throw new Error('control not found')
  return el
}

async function renderEdit(v: ServiceVisit = visit): Promise<void> {
  // Dual tracking, so both the odometer and the engine-hours inputs mount.
  mockedApiGet.mockResolvedValue({ data: { usage_unit: 'distance', secondary_usage_enabled: true } })
  render(<ServiceVisitForm vin={VIN} visit={v} onClose={vi.fn()} onSuccess={vi.fn()} />)
  await waitFor(() => expect(input('service-engine-hours')).toBeInTheDocument())
}

async function submittedBody(): Promise<Record<string, unknown>> {
  fireEvent.submit(drawerForm())
  await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
  return mockedApiPut.mock.calls.at(-1)?.[1] as Record<string, unknown>
}

describe('ServiceVisitForm: clearing a field on edit', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedApiPut.mockResolvedValue({ data: {} })
  })

  it('sends null for every optional field the user cleared', async () => {
    await renderEdit()

    fireEvent.click(screen.getByRole('button', { name: 'clear vendor' }))
    for (const id of ['service-odometer', 'service-engine-hours', 'insurance-claim', 'invoice-number', 'po-number', 'work-order-number', 'visit-notes', 'tax-amount', 'shop-supplies', 'misc-fees']) {
      fireEvent.change(input(id), { target: { value: '' } })
    }

    const body = await submittedBody()
    expect(body).toMatchObject({
      vendor_id: null,
      odometer_km: null,
      engine_hours: null,
      insurance_claim_number: null,
      invoice_number: null,
      po_number: null,
      work_order_number: null,
      notes: null,
      tax_amount: null,
      shop_supplies: null,
      misc_fees: null,
    })
  })

  it('still sends the stored values when nothing was touched', async () => {
    await renderEdit()

    const body = await submittedBody()
    expect(body).toMatchObject({
      vendor_id: 7,
      odometer_km: 72420,
      engine_hours: 640.5,
      insurance_claim_number: 'CLM-1',
      invoice_number: 'INV-1',
      po_number: 'PO-1',
      work_order_number: 'WO-1',
      notes: 'Old notes',
      tax_amount: 4.5,
      shop_supplies: 3.25,
      misc_fees: 2,
    })
  })

  // A ref with no stored value has its chip off and no input. Sending null for
  // it would be harmless here, but it's the same code path that would wipe a
  // value the form never showed, so the key stays out of the PUT entirely (D6).
  it('leaves out every ref whose chip it never showed', async () => {
    await renderEdit({
      ...visit,
      insurance_claim_number: null,
      invoice_number: null,
      po_number: null,
      work_order_number: null,
    } as unknown as ServiceVisit)

    const body = await submittedBody()
    for (const key of ['insurance_claim_number', 'invoice_number', 'po_number', 'work_order_number']) {
      expect(body).not.toHaveProperty(key)
    }
  })
})

// An existing line item keeps any field the update leaves out, so a field the
// user blanked has to go out as null too, or the old value comes back.
describe('ServiceVisitForm: clearing a line item field on edit', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedApiPut.mockResolvedValue({ data: {} })
  })

  const lineItems = (body: Record<string, unknown>): Record<string, unknown>[] =>
    body.line_items as Record<string, unknown>[]

  it('sends null for each line-item field the user cleared', async () => {
    await renderEdit(inspectionVisit)

    const cost = screen.getAllByLabelText('lineItemEditor.cost')[1]
    const notes = screen.getAllByPlaceholderText('lineItemEditor.misc.notesPlaceholder')[1]
    const category = found(screen.getAllByText('lineItemEditor.misc.categoryLabel')[1].parentElement?.querySelector('select'))
    const triggeredBy = found(screen.getByText('lineItemEditor.misc.triggeredByFailedInspection').parentElement?.querySelector('select'))
    fireEvent.change(cost, { target: { value: '' } })
    fireEvent.change(notes, { target: { value: '' } })
    fireEvent.change(category, { target: { value: '' } })
    fireEvent.change(triggeredBy, { target: { value: '' } })

    const repair = lineItems(await submittedBody())[1]
    expect(repair).toHaveProperty('id', 602)
    expect(repair).toHaveProperty('category', null)
    expect(repair).toHaveProperty('cost', null)
    expect(repair).toHaveProperty('notes', null)
    expect(repair).toHaveProperty('triggered_by_inspection_id', null)
  })

  it('sends null result and severity when the inspection box is unticked', async () => {
    await renderEdit(inspectionVisit)

    fireEvent.click(found(document.getElementById('inspection-0')))

    const inspection = lineItems(await submittedBody())[0]
    expect(inspection).toHaveProperty('id', 601)
    expect(inspection).toHaveProperty('is_inspection', false)
    expect(inspection).toHaveProperty('inspection_result', null)
    expect(inspection).toHaveProperty('inspection_severity', null)
  })

  it('still sends the stored line-item values when nothing was touched', async () => {
    await renderEdit(inspectionVisit)

    const [inspection, repair] = lineItems(await submittedBody())
    expect(repair).toMatchObject({
      id: 602,
      category: 'Maintenance',
      cost: 80,
      notes: 'Old item notes',
      triggered_by_inspection_id: 601,
    })
    expect(inspection).toMatchObject({
      id: 601,
      inspection_result: 'failed',
      inspection_severity: 'red',
    })
  })
})

// A repair can only point at an inspection (S1d-04). The form drops the link
// when its inspection stops being one, or goes away, so a save never carries
// a link the backend would drop or a temp id it would refuse.
describe('ServiceVisitForm: a repair link follows its inspection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedApiPut.mockResolvedValue({ data: {} })
  })

  const lineItems = (body: Record<string, unknown>): Record<string, unknown>[] =>
    body.line_items as Record<string, unknown>[]

  it('clears the repair link when its inspection is unticked', async () => {
    await renderEdit(inspectionVisit)

    fireEvent.click(document.getElementById('inspection-0') as HTMLInputElement)

    const [inspection, repair] = lineItems(await submittedBody())
    expect(inspection).toHaveProperty('is_inspection', false)
    expect(repair).toHaveProperty('id', 602)
    // main: still 601
    expect(repair).toHaveProperty('triggered_by_inspection_id', null)
  })

  it('carries no dangling temp id after an unsaved inspection is removed', async () => {
    await renderEdit()

    fireEvent.click(screen.getByRole('button', { name: 'service.addItem' }))
    // The added row is index 1; its description is the text input under that row's label.
    const description = found(screen.getAllByText('lineItemEditor.misc.descriptionLabel')[1].parentElement?.querySelector('input[type="text"]'))
    fireEvent.change(description, { target: { value: 'Tire inspection' } })
    fireEvent.click(document.getElementById('inspection-1') as HTMLInputElement)
    fireEvent.click(screen.getByRole('button', { name: 'inspectionResult.resultFailed' }))
    fireEvent.click(screen.getByRole('button', { name: 'service.addRepairForInspection' }))
    expect(screen.getByDisplayValue('Repair: Tire inspection')).toBeInTheDocument()

    fireEvent.click(screen.getAllByTitle('lineItemEditor.misc.removeLineItem')[1])

    const items = lineItems(await submittedBody())
    expect(items.map((li) => li.description)).toEqual(['Oil change', 'Repair: Tire inspection'])
    // main: the repair still names the removed inspection's temp id
    expect(items[1]).toHaveProperty('triggered_by_inspection_id', null)
  })

  // Coverage for the saved-id side of withoutLinksTo. Mutation: pass only
  // `removed.tempId` in handleRemoveLineItem and this goes red (602 keeps 601).
  it('clears the repair link when its saved inspection is removed', async () => {
    await renderEdit(inspectionVisit)

    fireEvent.click(screen.getAllByTitle('lineItemEditor.misc.removeLineItem')[0])

    const items = lineItems(await submittedBody())
    expect(items).toHaveLength(1)
    expect(items[0]).toHaveProperty('id', 602)
    expect(items[0]).toHaveProperty('triggered_by_inspection_id', null)
  })
})

// The editor has no recall or warranty controls yet, so an edit has to hand
// the stored flags and links back untouched instead of dropping or zeroing them.
describe('ServiceVisitForm: recall and warranty links on edit', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedApiPut.mockResolvedValue({ data: {} })
  })

  it('sends back the stored flags and links of every item', async () => {
    const linked = {
      ...visit,
      line_items: [
        { ...visit.line_items[0], is_recall: true, recall_id: 41, is_warranty: true, warranty_id: 9 },
      ],
    } as unknown as ServiceVisit
    await renderEdit(linked)

    const body = await submittedBody()
    expect((body.line_items as Record<string, unknown>[])[0]).toMatchObject({
      id: 501,
      is_recall: true,
      recall_id: 41,
      is_warranty: true,
      warranty_id: 9,
    })
  })
})
