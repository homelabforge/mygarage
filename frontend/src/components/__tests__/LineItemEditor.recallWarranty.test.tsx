import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, fireEvent, within } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import ServiceVisitForm from '../ServiceVisitForm'
import type { ServiceVisit } from '../../types/serviceVisit'
import type { Recall } from '../../types/recall'
import type { WarrantyRecord } from '../../types/warranty'

// The recall and warranty boxes on a line item. Which recalls a line can pick
// depends on the other lines, so these run through the whole form.

const mockedApiGet = vi.fn()
const mockedApiPost = vi.fn()
const mockedApiPut = vi.fn()

vi.mock('../../services/api', () => ({
  default: {
    get: (...args: unknown[]) => mockedApiGet(...args),
    post: (...args: unknown[]) => mockedApiPost(...args),
    put: (...args: unknown[]) => mockedApiPut(...args),
  },
}))
vi.mock('../../hooks/useUnitPreference', async () => {
  const { METRIC_UNITS } = await import('@/__tests__/factories')
  const unitPreference = () => ({ system: 'metric', showBoth: false, units: METRIC_UNITS, gallonStandard: 'us' })
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
}))
const useRecallRecordsMock = vi.fn()
const useWarrantyRecordsMock = vi.fn()
vi.mock('../../hooks/queries/useRecallRecords', () => ({
  useRecallRecords: (...args: unknown[]) => useRecallRecordsMock(...args),
}))
vi.mock('../../hooks/queries/useWarrantyRecords', () => ({
  useWarrantyRecords: (...args: unknown[]) => useWarrantyRecordsMock(...args),
}))
vi.mock('../VendorSearch', () => ({ default: () => <div data-testid="vendor-search" /> }))
vi.mock('../ServiceVisitAttachmentUpload', () => ({ default: () => <div /> }))
vi.mock('../ServiceVisitAttachmentList', () => ({ default: () => <div /> }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const VIN = 'TEST12345678901234'

const recall = (over: Partial<Recall> & { id: number }): Recall =>
  ({
    vin: VIN,
    nhtsa_campaign_number: null,
    external_id: null,
    component: null,
    summary: null,
    is_resolved: false,
    resolved_at: null,
    resolved_via: null,
    linked_visit: null,
    ...over,
  }) as unknown as Recall

const OPEN = recall({ id: 1, nhtsa_campaign_number: '26V059000', component: 'Air Bags' })
const BY_HAND = recall({ id: 2, nhtsa_campaign_number: '25V100000', component: 'Brakes', is_resolved: true, resolved_via: 'manual' })
// Fixed on some other visit: not this form's to give out.
const ELSEWHERE = recall({
  id: 3,
  nhtsa_campaign_number: '24V200000',
  component: 'Fuel Pump',
  is_resolved: true,
  resolved_via: 'service_visit',
  linked_visit: { visit_id: 77, line_item_id: 700, date: '2026-01-02', vendor_name: null },
})
// Fixed on THIS visit (900), by line 501.
const HERE = recall({
  id: 4,
  nhtsa_campaign_number: '23V300000',
  component: 'Seat Belts',
  is_resolved: true,
  resolved_via: 'service_visit',
  linked_visit: { visit_id: 900, line_item_id: 501, date: '2026-07-01', vendor_name: null },
})
const NAMELESS = recall({ id: 5 })

const WARRANTIES = [
  { id: 9, warranty_type: 'Powertrain', provider: 'Toyota' },
  { id: 10, warranty_type: 'Extended', provider: null },
] as unknown as WarrantyRecord[]

const lineItem = (over: Record<string, unknown>): Record<string, unknown> => ({
  visit_id: 900,
  category: 'Maintenance',
  cost: null,
  created_at: '2026-07-01T00:00:00',
  is_failed_inspection: false,
  is_inspection: false,
  needs_followup: false,
  notes: null,
  triggered_by_inspection_id: null,
  is_recall: false,
  recall_id: null,
  is_warranty: false,
  warranty_id: null,
  supply_usages: [],
  ...over,
})

const visit = {
  id: 900,
  vin: VIN,
  date: '2026-07-01',
  created_at: '2026-07-01T00:00:00',
  calculated_total_cost: '0.00',
  has_failed_inspections: false,
  line_item_count: 2,
  subtotal: '0.00',
  vendor_id: null,
  odometer_km: null,
  engine_hours: null,
  notes: null,
  insurance_claim_number: null,
  invoice_number: null,
  po_number: null,
  work_order_number: null,
  tax_amount: null,
  shop_supplies: null,
  misc_fees: null,
  service_category: null,
  total_cost: '0.00',
  updated_at: null,
  vendor: null,
  line_items: [
    lineItem({
      id: 501,
      description: 'Seat belt pretensioner',
      is_recall: true,
      recall_id: 4,
      recall_summary: { id: 4, campaign: '23V300000', component: 'Seat Belts' },
      is_warranty: true,
      warranty_id: 9,
      warranty_summary: { id: 9, warranty_type: 'Powertrain', provider: 'Toyota' },
    }),
    lineItem({ id: 502, description: 'Wipers' }),
  ],
} as unknown as ServiceVisit

const drawerForm = (): HTMLFormElement => screen.getByRole('dialog').querySelector('form') as HTMLFormElement
const recallBox = (i: number): HTMLInputElement => document.getElementById(`recall-${i}`) as HTMLInputElement
const warrantyBox = (i: number): HTMLInputElement => document.getElementById(`warranty-${i}`) as HTMLInputElement
const recallSelect = (i: number): HTMLSelectElement | null => document.getElementById(`recall-pick-${i}`) as HTMLSelectElement | null
const warrantySelect = (i: number): HTMLSelectElement | null => document.getElementById(`warranty-pick-${i}`) as HTMLSelectElement | null
const optionTexts = (select: HTMLSelectElement | null): string[] =>
  Array.from(select?.options ?? []).map((o) => o.textContent ?? '')

function typeDescription(i: number, text: string): void {
  const label = screen.getAllByText('lineItemEditor.misc.descriptionLabel')[i]
  const input = label.parentElement?.querySelector('input[type="text"]') as HTMLInputElement
  fireEvent.change(input, { target: { value: text } })
}

async function renderNew(): Promise<void> {
  render(<ServiceVisitForm vin={VIN} onClose={vi.fn()} onSuccess={vi.fn()} />)
  await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
  typeDescription(0, 'Air bag inflator')
}

async function renderEdit(): Promise<void> {
  render(<ServiceVisitForm vin={VIN} visit={visit} onClose={vi.fn()} onSuccess={vi.fn()} />)
  await waitFor(() => expect(screen.getByRole('button', { name: 'common:update' })).toBeEnabled())
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedApiGet.mockResolvedValue({ data: { usage_unit: 'distance', secondary_usage_enabled: false } })
  mockedApiPost.mockResolvedValue({ data: {} })
  mockedApiPut.mockResolvedValue({ data: {} })
  useRecallRecordsMock.mockReturnValue({
    data: { recalls: [OPEN, BY_HAND, ELSEWHERE, HERE, NAMELESS], total: 5, active_count: 2, resolved_count: 3 },
  })
  useWarrantyRecordsMock.mockReturnValue({ data: WARRANTIES })
})

describe('LineItemEditor: recall items', () => {
  it('ticking "This is a recall item" shows a recall select of the open and hand-resolved recalls, none another visit fixed', async () => {
    await renderNew()
    expect(recallSelect(0)).toBeNull()

    fireEvent.click(recallBox(0))

    expect(useRecallRecordsMock).toHaveBeenCalledWith(VIN)
    expect(screen.getByLabelText('lineItemEditor.misc.pickRecall')).toBe(recallSelect(0))
    expect(optionTexts(recallSelect(0))).toEqual([
      'lineItemEditor.misc.noSpecificRecall',
      '26V059000 · Air Bags',
      '25V100000 · Brakes',
      // Not 24V200000 or 23V300000: other visits fixed those.
      'vehicles:recallList.unnamed',
    ])
  })

  it('a recall one line picked is not offered to another line', async () => {
    await renderNew()
    fireEvent.click(recallBox(0))
    fireEvent.change(recallSelect(0) as HTMLSelectElement, { target: { value: '1' } })

    fireEvent.click(screen.getByRole('button', { name: 'service.addItem' }))
    fireEvent.click(recallBox(1))

    expect(optionTexts(recallSelect(1))).not.toContain('26V059000 · Air Bags')
    expect(optionTexts(recallSelect(1))).toContain('25V100000 · Brakes')
    // The first line still has its own pick.
    expect(recallSelect(0)?.value).toBe('1')
  })

  it('create sends the picked recall and warranty, and false/null for a plain line', async () => {
    await renderNew()
    fireEvent.click(recallBox(0))
    fireEvent.change(recallSelect(0) as HTMLSelectElement, { target: { value: '1' } })
    fireEvent.click(warrantyBox(0))
    fireEvent.change(warrantySelect(0) as HTMLSelectElement, { target: { value: '9' } })
    fireEvent.click(screen.getByRole('button', { name: 'service.addItem' }))
    typeDescription(1, 'Wipers')

    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())

    const items = (mockedApiPost.mock.calls.at(-1)?.[1] as { line_items: Record<string, unknown>[] }).line_items
    expect(items[0]).toMatchObject({ is_recall: true, recall_id: 1, is_warranty: true, warranty_id: 9 })
    expect(items[1]).toMatchObject({ is_recall: false, recall_id: null, is_warranty: false, warranty_id: null })
  })

  it("a 422 for a recall that isn't this vehicle's shows in the form's error banner", async () => {
    const detail = 'The linked recall is not on this vehicle'
    mockedApiPost.mockRejectedValueOnce({ isAxiosError: true, message: 'Request failed', response: { status: 422, data: { detail } } })
    await renderNew()
    fireEvent.click(recallBox(0))
    fireEvent.change(recallSelect(0) as HTMLSelectElement, { target: { value: '1' } })

    fireEvent.submit(drawerForm())

    expect(await within(screen.getByRole('dialog')).findByText(detail)).toBeInTheDocument()
  })
})

describe('LineItemEditor: warranty items', () => {
  it('ticking "This is a warranty item" shows a warranty select with "No specific warranty"', async () => {
    await renderNew()
    expect(warrantySelect(0)).toBeNull()

    fireEvent.click(warrantyBox(0))

    expect(useWarrantyRecordsMock).toHaveBeenCalledWith(VIN)
    expect(screen.getByLabelText('lineItemEditor.misc.pickWarranty')).toBe(warrantySelect(0))
    expect(optionTexts(warrantySelect(0))).toEqual([
      'lineItemEditor.misc.noSpecificWarranty',
      'Powertrain (Toyota)',
      'Extended',
    ])
  })
})

describe('LineItemEditor: editing a visit', () => {
  it('shows the stored links, and only this visit\'s line holds its recall', async () => {
    await renderEdit()

    expect(recallBox(0)).toBeChecked()
    expect(recallSelect(0)?.value).toBe('4')
    expect(warrantyBox(0)).toBeChecked()
    expect(warrantySelect(0)?.value).toBe('9')

    fireEvent.click(recallBox(1))
    expect(optionTexts(recallSelect(1))).not.toContain('23V300000 · Seat Belts')
    expect(optionTexts(recallSelect(1))).not.toContain('24V200000 · Fuel Pump')
  })

  it('moving a recall from one line to another inside the form is allowed', async () => {
    await renderEdit()
    fireEvent.click(recallBox(0))
    fireEvent.click(recallBox(1))

    expect(optionTexts(recallSelect(1))).toContain('23V300000 · Seat Belts')
  })

  it('unticking clears the link in the PUT', async () => {
    await renderEdit()
    fireEvent.click(recallBox(0))
    fireEvent.click(warrantyBox(0))
    expect(recallSelect(0)).toBeNull()
    expect(warrantySelect(0)).toBeNull()

    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())

    const items = (mockedApiPut.mock.calls.at(-1)?.[1] as { line_items: Record<string, unknown>[] }).line_items
    expect(items[0]).toMatchObject({ id: 501, is_recall: false, recall_id: null, is_warranty: false, warranty_id: null })
  })

  it('picking "No specific recall" keeps the flag and drops the link', async () => {
    await renderEdit()
    fireEvent.change(recallSelect(0) as HTMLSelectElement, { target: { value: '' } })

    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())

    const items = (mockedApiPut.mock.calls.at(-1)?.[1] as { line_items: Record<string, unknown>[] }).line_items
    expect(items[0]).toMatchObject({ id: 501, is_recall: true, recall_id: null, is_warranty: true, warranty_id: 9 })
  })
})

describe('LineItemEditor: before the recall and warranty lists arrive', () => {
  it.each([
    ['loading', { data: undefined, isLoading: true, isError: false }],
    ['failed', { data: undefined, isLoading: false, isError: true }],
  ])('while the lists are %s, the stored links still show, named from the visit', async (_case, state) => {
    useRecallRecordsMock.mockReturnValue(state)
    useWarrantyRecordsMock.mockReturnValue(state)
    await renderEdit()

    expect(recallSelect(0)?.value).toBe('4')
    expect(recallSelect(0)?.selectedOptions[0]?.textContent).toBe('23V300000 · Seat Belts')
    expect(warrantySelect(0)?.value).toBe('9')
    expect(warrantySelect(0)?.selectedOptions[0]?.textContent).toBe('Powertrain (Toyota)')
  })

  it('once the list arrives the stored recall is listed once, not twice', async () => {
    await renderEdit()

    expect(optionTexts(recallSelect(0)).filter((label) => label === '23V300000 · Seat Belts')).toHaveLength(1)
    expect(optionTexts(warrantySelect(0)).filter((label) => label === 'Powertrain (Toyota)')).toHaveLength(1)
  })
})
