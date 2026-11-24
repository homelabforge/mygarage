import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, fireEvent, within } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import ServiceVisitForm from '../ServiceVisitForm'
import { useSupplies } from '../../hooks/queries/useSupplies'
import { toCanonical, toDisplay } from '../../utils/supplyUnits'
import { formatCurrency } from '../../utils/formatUtils'
import type { Supply } from '../../types/supplies'
import type { ServiceVisit } from '../../types/serviceVisit'
import { MONEY_MAX } from '../../schemas/shared'

const drawerForm = (): HTMLFormElement =>
  screen.getByRole('dialog').querySelector('form') as HTMLFormElement

const mockedApiGet = vi.fn().mockResolvedValue({ data: { items: [] } })
const mockedApiPost = vi.fn().mockResolvedValue({ data: {} })
const mockedApiPut = vi.fn().mockResolvedValue({ data: {} })

vi.mock('../../services/api', () => ({
  default: {
    get: (...args: unknown[]) => mockedApiGet(...args),
    post: (...args: unknown[]) => mockedApiPost(...args),
    put: (...args: unknown[]) => mockedApiPut(...args),
  },
}))

// Requires AuthProvider otherwise — same mock pattern as ServiceVisitForm.test.tsx.
// System is 'imperial' deliberately: the mock supply is unit_type 'volume', so a
// display-unit (quart) quantity only round-trips to a distinct canonical (liter)
// value under imperial — proving conversion actually ran, not just passed through.
vi.mock('../../hooks/useUnitPreference', async () => {
  const { IMPERIAL_UNITS } = await import('@/__tests__/factories')
  // UnitSession reads the account half too; same answer, nothing to pin here.
  const unitPreference = () => ({
    system: 'imperial',
    showBoth: false,
    units: IMPERIAL_UNITS,
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

const MOCK_SUPPLY: Supply = {
  id: 1,
  name: 'Motor Oil 5W-30',
  unit_type: 'volume',
  avg_unit_cost: '10.00',
  on_hand: '20',
  is_active: true,
  is_negative: false,
  created_at: '2026-01-01T00:00:00',
  category: null,
  notes: null,
  part_number: null,
  updated_at: null,
  vin: null,
}

// Shared across ServiceVisitForm's own lookup fetch (includeArchived=true) and
// SupplyUsedPicker's dropdown fetch (includeArchived=false) — a single supply
// list works for both since this suite has nothing archived.
vi.mock('../../hooks/queries/useSupplies', () => ({
  useSupplies: vi.fn(() => ({
    data: { supplies: [MOCK_SUPPLY], total: 1 },
    isSuccess: true,
    isLoading: false,
    isError: false,
  })),
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

const DEFAULT_PROPS = {
  vin: 'TEST123',
  onClose: vi.fn(),
  onSuccess: vi.fn(),
}

function fillRequiredDescription() {
  fireEvent.change(screen.getByPlaceholderText('lineItemEditor.misc.selectCategoryFirst'), {
    target: { value: 'Oil change' },
  })
}

describe('ServiceVisitForm — supplies used (Task 17)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Re-establish the happy-path supplies result before each test (clearAllMocks
    // keeps mockReturnValue, so a test that overrides it must not leak).
    vi.mocked(useSupplies).mockReturnValue({
      data: { supplies: [MOCK_SUPPLY], total: 1 },
      isSuccess: true,
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof useSupplies>)
  })

  it('adds a supply to a line item, sends a CANONICAL quantity on create, and shows the breakdown line', async () => {
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)

    fillRequiredDescription()

    // Add a supply usage row — the only fetched supply is auto-selected.
    fireEvent.click(screen.getByRole('button', { name: /suppliesAddRow/ }))

    const quantityInput = screen.getByRole('textbox', { name: 'service.suppliesQuantityOf' })
    fireEvent.change(quantityInput, { target: { value: '2' } })

    // The Total block now formats through the shared formatCurrency (SDQ-3), not a
    // hardcoded `$`+toFixed. USD/en-US (the mocked currency prefs) → "$18.93"; the
    // value is still derived from the canonical quantity, so it discriminates the
    // parts+supplies cost (a dropped canonical conversion or a wrong unit-cost fails).
    // MOCK_SUPPLY has no stored token, so under the imperial mock it falls back to US quarts.
    const expectedCanonicalQty = toCanonical(2, 'qt_us')
    const expectedPartsSuppliesCost = formatCurrency(10 * expectedCanonicalQty, { currencyCode: 'USD', locale: 'en-US' })
    const partsSuppliesRow = screen.getByText('service.suppliesTotal:').closest('div')
    expect(partsSuppliesRow).toHaveTextContent(expectedPartsSuppliesCost)

    fireEvent.submit(drawerForm())

    await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
    const body = mockedApiPost.mock.calls.at(-1)?.[1] as {
      line_items: { supplies_used: { supply_id: number; quantity: number }[] }[]
    }
    expect(body.line_items).toHaveLength(1)
    expect(body.line_items[0].supplies_used).toHaveLength(1)
    expect(body.line_items[0].supplies_used[0].supply_id).toBe(1)
    // CANONICAL, not the raw display-unit "2" that was typed.
    expect(body.line_items[0].supplies_used[0].quantity).toBeCloseTo(expectedCanonicalQty, 6)
    expect(body.line_items[0].supplies_used[0].quantity).not.toBeCloseTo(2, 3)
  })

  it('marks a new usage estimated: the server prices it as of the visit date (#307)', async () => {
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)
    fillRequiredDescription()
    fireEvent.click(screen.getByRole('button', { name: /suppliesAddRow/ }))
    fireEvent.change(screen.getByRole('textbox', { name: 'service.suppliesQuantityOf' }), { target: { value: '2' } })

    const partsSuppliesRow = screen.getByText('service.suppliesTotal:').closest('div') as HTMLElement
    expect(within(partsSuppliesRow).getByText('common:supplies.estimated')).toBeInTheDocument()
    expect(screen.getByText('service.partsEstimated')).toBeInTheDocument()
  })

  it('removes a supply usage row and sends an empty supplies_used array', async () => {
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)

    fillRequiredDescription()
    fireEvent.click(screen.getByRole('button', { name: /suppliesAddRow/ }))
    expect(screen.getByRole('textbox', { name: 'service.suppliesQuantityOf' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'service.suppliesRemoveNamed' }))
    expect(screen.queryByRole('textbox', { name: 'service.suppliesQuantityOf' })).not.toBeInTheDocument()
    expect(screen.queryByText('service.suppliesTotal:')).not.toBeInTheDocument()

    fireEvent.submit(drawerForm())

    await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
    const body = mockedApiPost.mock.calls.at(-1)?.[1] as {
      line_items: { supplies_used: unknown[] }[]
    }
    expect(body.line_items[0].supplies_used).toEqual([])
  })

  describe('edit — hydration is the correctness contract', () => {
    // Canonical usage from the server: 1 liter of the mock volume supply.
    const MOCK_VISIT: ServiceVisit = {
      id: 900,
      vin: 'TEST123',
      date: '2026-07-01',
      created_at: '2026-07-01T00:00:00',
      calculated_total_cost: '55.00',
      has_failed_inspections: false,
      line_item_count: 1,
      subtotal: '45.00',
      parts_supplies_cost: '10.00',
      vendor_id: null,
      odometer_km: null,
      notes: null,
      insurance_claim_number: null,
      tax_amount: null,
      shop_supplies: null,
      misc_fees: null,
      service_category: null,
      total_cost: '55.00',
      updated_at: null,
      vendor: null,
      line_items: [
        {
          id: 501,
          visit_id: 900,
          description: 'Oil change',
          category: 'Maintenance',
          cost: '45.00',
          created_at: '2026-07-01T00:00:00',
          is_failed_inspection: false,
          is_inspection: false,
          needs_followup: false,
          notes: null,
          triggered_by_inspection_id: null,
          is_recall: false,
          is_warranty: false,
          supply_usages: [
            {
              id: 1,
              supply_id: 1,
              supply_name: 'Motor Oil 5W-30',
              unit_type: 'volume',
              quantity: '1',
              created_at: '2026-07-01T00:00:00',
              service_line_item_id: 501,
              service_visit_id: 900,
              cost_snapshot: '10.00',
              unit_cost_snapshot: '10.00',
              cost_estimated: false,
              service_visit_date: '2026-07-01',
            },
          ],
        },
      ],
    }

    it('hydrates the picker from supply_usages in DISPLAY units', async () => {
      render(<ServiceVisitForm {...DEFAULT_PROPS} visit={MOCK_VISIT} />)

      const expectedDisplayQty = toDisplay(1, 'qt_us')
      await waitFor(() => {
        const quantityInput = screen.getByRole('textbox', {
          name: 'service.suppliesQuantityOf',
        }) as HTMLInputElement
        expect(Number(quantityInput.value)).toBeCloseTo(expectedDisplayQty, 6)
      })
    })

    it('resends the hydrated supplies_used (converted back to canonical) even when nothing else was touched — proves editing does not wipe usages', async () => {
      render(<ServiceVisitForm {...DEFAULT_PROPS} visit={MOCK_VISIT} />)

      // Wait for hydration before submitting, otherwise the still-empty [] would
      // race the effect and falsely appear to "work".
      await waitFor(() => {
        expect(screen.getByRole('textbox', { name: 'service.suppliesQuantityOf' })).toBeInTheDocument()
      })

      fireEvent.submit(drawerForm())

      await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
      const body = mockedApiPut.mock.calls.at(-1)?.[1] as {
        line_items: { id?: number; supplies_used: { supply_id: number; quantity: number }[] }[]
      }
      const lineItem = body.line_items.find((li) => li.id === 501)
      expect(lineItem?.supplies_used).toHaveLength(1)
      expect(lineItem?.supplies_used[0].supply_id).toBe(1)
      expect(lineItem?.supplies_used[0].quantity).toBeCloseTo(1, 6)
    })

    it('disables Save on edit until supplies load + hydrate (wipe-on-edit load-timing guard)', () => {
      vi.mocked(useSupplies).mockReturnValue({
        data: undefined,
        isSuccess: false,
        isLoading: true,
        isError: false,
      } as unknown as ReturnType<typeof useSupplies>)

      render(<ServiceVisitForm {...DEFAULT_PROPS} visit={MOCK_VISIT} />)

      // Until the supplies list loads + hydration runs, supplies_used is still [];
      // submitting would make the backend delete every logged usage on this visit.
      expect(screen.getByRole('button', { name: 'common:update' })).toBeDisabled()
    })

    it('resends a usage of a supply repinned to another vehicle (unfiltered resolution avoids a silent wipe)', async () => {
      // Supply 2 is pinned to a DIFFERENT vehicle — never OFFERED for a new row here,
      // but a past usage of it must still hydrate + resend. The form resolves usages
      // from an UNFILTERED supplies fetch precisely so this isn't dropped -> wiped.
      const repinned: Supply = { ...MOCK_SUPPLY, id: 2, name: 'Coolant', vin: 'OTHERVIN' }
      vi.mocked(useSupplies).mockReturnValue({
        data: { supplies: [MOCK_SUPPLY, repinned], total: 2 },
        isSuccess: true,
        isLoading: false,
        isError: false,
      } as unknown as ReturnType<typeof useSupplies>)

      const visit: ServiceVisit = {
        ...MOCK_VISIT,
        line_items: [
          {
            id: 501,
            visit_id: 900,
            description: 'Oil change',
            category: 'Maintenance',
            cost: '45.00',
            created_at: '2026-07-01T00:00:00',
            is_failed_inspection: false,
            is_inspection: false,
            needs_followup: false,
            notes: null,
            triggered_by_inspection_id: null,
            is_recall: false,
            is_warranty: false,
            supply_usages: [
              {
                id: 5,
                supply_id: 2,
                supply_name: 'Coolant',
                unit_type: 'volume',
                quantity: '1',
                created_at: '2026-07-01T00:00:00',
                service_line_item_id: 501,
                service_visit_id: 900,
                cost_snapshot: '10.00',
                unit_cost_snapshot: '10.00',
                cost_estimated: false,
                service_visit_date: '2026-07-01',
              },
            ],
          },
        ],
      }

      render(<ServiceVisitForm {...DEFAULT_PROPS} visit={visit} />)
      await waitFor(() => {
        expect(
          screen.getByRole('textbox', { name: 'service.suppliesQuantityOf' }),
        ).toBeInTheDocument()
      })
      fireEvent.submit(drawerForm())

      await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
      const body = mockedApiPut.mock.calls.at(-1)?.[1] as {
        line_items: { id?: number; supplies_used: { supply_id: number }[] }[]
      }
      const lineItem = body.line_items.find((li) => li.id === 501)
      expect(lineItem?.supplies_used.map((u) => u.supply_id)).toContain(2)
    })

    describe('says where supplies come from once per visit', () => {
      const line = MOCK_VISIT.line_items[0]
      const threeLines: ServiceVisit = {
        ...MOCK_VISIT,
        line_items: [501, 502, 503].map((id) => ({ ...line, id, supply_usages: [] })),
      }
      const hints = (): HTMLElement[] => screen.queryAllByText('service.suppliesOwnStockHint')
      const firstRemove = (): HTMLElement => screen.getAllByTitle('lineItemEditor.misc.removeLineItem')[0]
      const renderThree = async (): Promise<void> => {
        render(<ServiceVisitForm {...DEFAULT_PROPS} visit={threeLines} />)
        await waitFor(() => expect(screen.getAllByText('service.suppliesUsed')).toHaveLength(3))
      }

      it('not under every line item', async () => {
        await renderThree()
        expect(hints()).toHaveLength(1)
      })

      it('still there with the first line item collapsed', async () => {
        await renderThree()
        // The chevron is the first button in the item's header row.
        const collapse = firstRemove().parentElement!.querySelector('button')!
        fireEvent.click(collapse)
        await waitFor(() => expect(screen.getAllByText('service.suppliesUsed')).toHaveLength(2))
        // d0b0950c: 0, the hint rode inside item 1's body.
        expect(hints()).toHaveLength(1)
      })

      it('still there with the first line item deleted', async () => {
        await renderThree()
        fireEvent.click(firstRemove())
        await waitFor(() => expect(screen.getAllByText('service.suppliesUsed')).toHaveLength(2))
        expect(hints()).toHaveLength(1)
      })
    })

    // #301: the estimate is what the save will store, not today's average.
    const visitWithUsage = (usage: { quantity: string; cost_snapshot: string | null; unit_cost_snapshot: string | null; cost_estimated?: boolean }): ServiceVisit => ({
      ...MOCK_VISIT,
      line_items: [
        {
          ...MOCK_VISIT.line_items[0],
          supply_usages: [{ ...MOCK_VISIT.line_items[0].supply_usages![0], ...usage }],
        },
      ],
    })
    const partsRow = (): HTMLElement | null =>
      screen.queryByText('service.suppliesTotal:')?.closest('div') ?? null
    const usd = (n: number): string => formatCurrency(n, { currencyCode: 'USD', locale: 'en-US' })

    it('shows a saved usage at its stored cost even when the average has moved', async () => {
      // Stored at 7.00 a litre; the supply averages 10.00 now.
      render(<ServiceVisitForm {...DEFAULT_PROPS} visit={visitWithUsage({ quantity: '1', cost_snapshot: '7.00', unit_cost_snapshot: '7.0000' })} />)
      await waitFor(() => expect(partsRow()).toHaveTextContent(usd(7)))
      expect(partsRow()).not.toHaveTextContent(usd(10))
      expect(screen.queryByText('service.partsUnpriced')).not.toBeInTheDocument()
    })

    it('reprices an edited quantity at the frozen unit cost', async () => {
      render(<ServiceVisitForm {...DEFAULT_PROPS} visit={visitWithUsage({ quantity: '1', cost_snapshot: '7.00', unit_cost_snapshot: '7.0000' })} />)
      const quantityInput = await screen.findByRole('textbox', { name: 'service.suppliesQuantityOf' })
      fireEvent.change(quantityInput, { target: { value: '2' } })
      const litres = toCanonical(2, 'qt_us')
      await waitFor(() => expect(partsRow()).toHaveTextContent(usd(Math.round(7 * litres * 100) / 100)))
    })

    it('prices a usage saved with no cost at the average, which the save will store', async () => {
      render(<ServiceVisitForm {...DEFAULT_PROPS} visit={visitWithUsage({ quantity: '1', cost_snapshot: null, unit_cost_snapshot: null })} />)
      await waitFor(() => expect(partsRow()).toHaveTextContent(usd(10)))
    })

    it('leaves a backfill out when the server would, past the money column', async () => {
      // Labour 5.00 short of the cap: the usage's 10.00 would overflow, so the
      // save keeps the edit and leaves the usage unpriced.
      const nearCap = visitWithUsage({ quantity: '1', cost_snapshot: null, unit_cost_snapshot: null })
      nearCap.line_items[0].cost = String(MONEY_MAX - 5)
      render(<ServiceVisitForm {...DEFAULT_PROPS} visit={nearCap} />)
      expect(await screen.findByText('service.partsUnpriced')).toBeInTheDocument()
      expect(partsRow()).toBeNull()
    })

    // #307: the server prices as of the visit date, so the editor labels what it can't promise.
    const estimatedMark = (el: HTMLElement | null): boolean =>
      el != null && within(el).queryByText('common:supplies.estimated') != null
    const lineParts = (): HTMLElement | null =>
      screen.queryByText('lineItemEditor.suppliesCost')?.closest('p') ?? null
    const settled = { quantity: '1', cost_snapshot: '7.00', unit_cost_snapshot: '7.0000' }

    it('leaves a settled usage unmarked (regression control)', async () => {
      render(<ServiceVisitForm {...DEFAULT_PROPS} visit={visitWithUsage(settled)} />)
      await waitFor(() => expect(partsRow()).toHaveTextContent(usd(7)))
      expect(estimatedMark(partsRow())).toBe(false)
      expect(estimatedMark(lineParts())).toBe(false)
      expect(screen.queryByText('service.partsEstimated')).not.toBeInTheDocument()
    })

    it('marks a saved estimate estimated, in the total and on its line, and says why', async () => {
      render(<ServiceVisitForm {...DEFAULT_PROPS} visit={visitWithUsage({ ...settled, cost_estimated: true })} />)
      await waitFor(() => expect(partsRow()).toHaveTextContent(usd(7)))
      expect(estimatedMark(partsRow())).toBe(true)
      expect(estimatedMark(lineParts())).toBe(true)
      expect(screen.getByText('service.partsEstimated')).toBeInTheDocument()
    })

    it('marks every saved usage estimated while the date is changed, and drops it when changed back', async () => {
      render(<ServiceVisitForm {...DEFAULT_PROPS} visit={visitWithUsage(settled)} />)
      await waitFor(() => expect(partsRow()).toHaveTextContent(usd(7)))
      const date = screen.getByLabelText(/common:date/) as HTMLInputElement

      fireEvent.change(date, { target: { value: '2025-07-01' } })
      await waitFor(() => expect(estimatedMark(partsRow())).toBe(true))
      // Still the stored cost: the preview can't know the as-of price, only that it may move.
      expect(partsRow()).toHaveTextContent(usd(7))
      expect(screen.getByText('service.partsEstimated')).toBeInTheDocument()

      fireEvent.change(date, { target: { value: '2026-07-01' } })
      await waitFor(() => expect(estimatedMark(partsRow())).toBe(false))
      expect(screen.queryByText('service.partsEstimated')).not.toBeInTheDocument()
    })

    // Past the money column only the pricer's writes roll back, so a stored
    // estimate keeps the cost the edit left it; only new or unpriced usages drop (T5-C1).
    const withSecondUsage = (first: ServiceVisit, second: Record<string, unknown>, labour: number): ServiceVisit => {
      vi.mocked(useSupplies).mockReturnValue({
        data: { supplies: [MOCK_SUPPLY, { ...MOCK_SUPPLY, id: 2, name: 'Coolant' }], total: 2 },
        isSuccess: true,
        isLoading: false,
        isError: false,
      } as unknown as ReturnType<typeof useSupplies>)
      const [kept] = first.line_items[0].supply_usages!
      first.line_items[0].supply_usages = [kept, { ...kept, id: 2, supply_id: 2, supply_name: 'Coolant', ...second }]
      first.line_items[0].cost = String(labour)
      return first
    }
    const unpricedUsage = { cost_snapshot: null, unit_cost_snapshot: null, cost_estimated: false }

    it('keeps a saved estimate in the total past the money column, still estimated', async () => {
      // An estimated 10.00 and an unpriced usage (10.00 at the average), 5.00
      // short of the cap with the estimate in: the unpriced one drops, the estimate stays.
      const visit = withSecondUsage(
        visitWithUsage({ quantity: '1', cost_snapshot: '10.00', unit_cost_snapshot: '10.0000', cost_estimated: true }),
        unpricedUsage,
        MONEY_MAX - 15,
      )
      render(<ServiceVisitForm {...DEFAULT_PROPS} visit={visit} />)
      expect(await screen.findByText('service.partsUnpriced')).toBeInTheDocument()
      expect(partsRow()).toHaveTextContent(usd(10))
      expect(estimatedMark(partsRow())).toBe(true)
      expect(estimatedMark(lineParts())).toBe(true)
      expect(screen.getByText('service.partsEstimated')).toBeInTheDocument()
    })

    it('does not mark what stays in the total when the dropped backfill was the estimate (regression control)', async () => {
      // A settled 7.00 and an unpriced usage priced at the average (an estimate),
      // 8.00 short of the cap: the backfill drops, so the 7.00 left is no estimate.
      const visit = withSecondUsage(visitWithUsage(settled), unpricedUsage, MONEY_MAX - 8)
      render(<ServiceVisitForm {...DEFAULT_PROPS} visit={visit} />)
      expect(await screen.findByText('service.partsUnpriced')).toBeInTheDocument()
      expect(partsRow()).toHaveTextContent(usd(7))
      expect(estimatedMark(partsRow())).toBe(false)
      expect(estimatedMark(lineParts())).toBe(false)
      expect(screen.queryByText('service.partsEstimated')).not.toBeInTheDocument()
    })

    it('says so when a supply has nothing to price it with yet', async () => {
      vi.mocked(useSupplies).mockReturnValue({
        data: { supplies: [{ ...MOCK_SUPPLY, avg_unit_cost: null }], total: 1 },
        isSuccess: true,
        isLoading: false,
        isError: false,
      } as unknown as ReturnType<typeof useSupplies>)
      render(<ServiceVisitForm {...DEFAULT_PROPS} visit={visitWithUsage({ quantity: '1', cost_snapshot: null, unit_cost_snapshot: null })} />)
      expect(await screen.findByText('service.partsUnpriced')).toBeInTheDocument()
      expect(partsRow()).toBeNull()
    })
  })
})

describe('ServiceVisitForm: each supply converts in its own unit', () => {
  // One US fl oz is 3.785411784 / 128 L, so 12 fl oz is 0.35488235475 L.
  const FL_OZ: Supply = { ...MOCK_SUPPLY, id: 3, name: 'Gear Oil', volume_unit: 'fl_oz_us' }
  const LITRES: Supply = { ...MOCK_SUPPLY, id: 4, name: 'Coolant', volume_unit: 'L' }
  const MILLILITRES: Supply = { ...MOCK_SUPPLY, id: 5, name: 'Additive', volume_unit: 'mL' }

  const serveSupplies = (supplies: Supply[]) =>
    vi.mocked(useSupplies).mockReturnValue({
      data: { supplies, total: supplies.length },
      isSuccess: true,
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof useSupplies>)

  const visitUsing = (supply: Supply, quantity: string): ServiceVisit => ({
    id: 900,
    vin: 'TEST123',
    date: '2026-07-01',
    created_at: '2026-07-01T00:00:00',
    calculated_total_cost: '45.00',
    has_failed_inspections: false,
    line_item_count: 1,
    subtotal: '45.00',
    parts_supplies_cost: '0.00',
    vendor_id: null,
    odometer_km: null,
    notes: null,
    insurance_claim_number: null,
    tax_amount: null,
    shop_supplies: null,
    misc_fees: null,
    service_category: null,
    total_cost: '45.00',
    updated_at: null,
    vendor: null,
    line_items: [
      {
        id: 501,
        visit_id: 900,
        description: 'Oil change',
        category: 'Maintenance',
        cost: '45.00',
        created_at: '2026-07-01T00:00:00',
        is_failed_inspection: false,
        is_inspection: false,
        needs_followup: false,
        notes: null,
        triggered_by_inspection_id: null,
        is_recall: false,
        is_warranty: false,
        supply_usages: [
          {
            id: 1,
            supply_id: supply.id,
            supply_name: supply.name,
            unit_type: 'volume',
            volume_unit: supply.volume_unit,
            quantity,
            created_at: '2026-07-01T00:00:00',
            service_line_item_id: 501,
            service_visit_id: 900,
            cost_snapshot: '0.00',
            unit_cost_snapshot: '10.00',
            cost_estimated: false,
            service_visit_date: '2026-07-01',
          },
        ],
      },
    ],
  })

  const quantityInputs = (): HTMLInputElement[] =>
    screen.getAllByRole('textbox', { name: 'service.suppliesQuantityOf' }) as HTMLInputElement[]

  // The unit label sits beside its quantity input, in the same wrapper.
  const rowOf = (input: HTMLInputElement): HTMLElement => input.parentElement as HTMLElement

  const putLineItem = () => {
    const body = mockedApiPut.mock.calls.at(-1)?.[1] as {
      line_items: { id?: number; supplies_used: { supply_id: number; quantity: number }[] }[]
    }
    return body.line_items.find((li) => li.id === 501)
  }

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('labels a fl oz supply in fl oz and posts 12 fl oz as litres', async () => {
    serveSupplies([FL_OZ])
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)
    fillRequiredDescription()
    fireEvent.click(screen.getByRole('button', { name: /suppliesAddRow/ }))

    const [input] = quantityInputs()
    expect(within(rowOf(input)).getByText('fl oz')).toBeInTheDocument()
    fireEvent.change(input, { target: { value: '12' } })
    fireEvent.submit(drawerForm())

    await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
    const body = mockedApiPost.mock.calls.at(-1)?.[1] as {
      line_items: { supplies_used: { supply_id: number; quantity: number }[] }[]
    }
    expect(body.line_items[0].supplies_used).toHaveLength(1)
    expect(body.line_items[0].supplies_used[0].supply_id).toBe(3)
    expect(body.line_items[0].supplies_used[0].quantity).toBeCloseTo(0.35488235475, 9)
  })

  it('hydrates a canonical 0.355 L back to about 12 fl oz', async () => {
    serveSupplies([FL_OZ])
    render(<ServiceVisitForm {...DEFAULT_PROPS} visit={visitUsing(FL_OZ, '0.355')} />)

    await waitFor(() => {
      const [input] = quantityInputs()
      expect(Math.abs(Number(input.value) - 12)).toBeLessThan(0.01)
    })
    expect(within(rowOf(quantityInputs()[0])).getByText('fl oz')).toBeInTheDocument()
  })

  it('refuses 0.02 fl oz, which converts to less than 1 mL', async () => {
    serveSupplies([FL_OZ])
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)
    fillRequiredDescription()
    fireEvent.click(screen.getByRole('button', { name: /suppliesAddRow/ }))
    fireEvent.change(quantityInputs()[0], { target: { value: '0.02' } })

    fireEvent.submit(drawerForm())

    expect(await screen.findByText('service.supplyQuantityTooSmall')).toBeInTheDocument()
    await waitFor(() => expect(mockedApiPost).not.toHaveBeenCalled())
  })

  it('lets exactly 1 mL through', async () => {
    // The floor is the storable grain itself, so it has to be allowed.
    serveSupplies([MILLILITRES])
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)
    fillRequiredDescription()
    fireEvent.click(screen.getByRole('button', { name: /suppliesAddRow/ }))
    fireEvent.change(quantityInputs()[0], { target: { value: '1' } })

    fireEvent.submit(drawerForm())

    await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
    const body = mockedApiPost.mock.calls.at(-1)?.[1] as {
      line_items: { supplies_used: { quantity: number }[] }[]
    }
    expect(body.line_items[0].supplies_used[0].quantity).toBeCloseTo(0.001, 9)
    expect(screen.queryByText('service.supplyQuantityTooSmall')).not.toBeInTheDocument()
  })

  it('keeps the unit it hydrated with when the supply switches L to mL mid-edit', async () => {
    serveSupplies([LITRES])
    const visit = visitUsing(LITRES, '1')
    const { rerender } = render(<ServiceVisitForm {...DEFAULT_PROPS} visit={visit} />)
    await waitFor(() => expect(Number(quantityInputs()[0].value)).toBeCloseTo(1, 9))
    expect(within(rowOf(quantityInputs()[0])).getByText('L')).toBeInTheDocument()

    // Another tab changed the unit and the supplies query refetched under the open form.
    serveSupplies([{ ...LITRES, volume_unit: 'mL' }])
    rerender(<ServiceVisitForm {...DEFAULT_PROPS} visit={visit} />)

    const row = rowOf(quantityInputs()[0])
    expect(within(row).getByText('L')).toBeInTheDocument()
    expect(within(row).queryByText('mL')).not.toBeInTheDocument()

    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    const lineItem = putLineItem()
    expect(lineItem?.supplies_used).toHaveLength(1)
    expect(lineItem?.supplies_used[0].supply_id).toBe(4)
    expect(lineItem?.supplies_used[0].quantity).toBeCloseTo(1, 9)
  })

  it('admits a supply that shows up after hydration and posts it at the fl oz factor', async () => {
    serveSupplies([MOCK_SUPPLY])
    const visit = visitUsing(MOCK_SUPPLY, '1')
    const { rerender } = render(<ServiceVisitForm {...DEFAULT_PROPS} visit={visit} />)
    await waitFor(() => expect(quantityInputs()).toHaveLength(1))

    // Created in another tab; the refetch hands the open form a supply it has never seen.
    serveSupplies([MOCK_SUPPLY, FL_OZ])
    rerender(<ServiceVisitForm {...DEFAULT_PROPS} visit={visit} />)

    fireEvent.click(screen.getByRole('button', { name: /suppliesAddRow/ }))
    const added = quantityInputs()[1]
    expect(within(rowOf(added)).getByText('fl oz')).toBeInTheDocument()
    fireEvent.change(added, { target: { value: '12' } })

    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    const used = putLineItem()?.supplies_used ?? []
    expect(used.map((u) => u.supply_id)).toEqual([1, 3])
    expect(used[0].quantity).toBeCloseTo(1, 9)
    expect(used[1].quantity).toBeCloseTo(0.35488235475, 9)
  })
})

describe('ServiceVisitForm — footer lift (P3 Task 5)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(useSupplies).mockReturnValue({
      data: { supplies: [MOCK_SUPPLY], total: 1 },
      isSuccess: true,
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof useSupplies>)
  })

  it('submits via the footer button (form= association, outside the <form>)', async () => {
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)
    fillRequiredDescription()
    // Create lives in the sticky footer, a sibling of the <form>, wired via form="service-visit-form".
    fireEvent.click(screen.getByRole('button', { name: 'common:create' }))
    await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
  })
})

// S-frac: a visit saved with 2.5 of a counted supply (before the check existed)
// still saves when edited for something else, but no new fraction gets in.
describe('ServiceVisitForm: an old fractional count', () => {
  const FILTER: Supply = { ...MOCK_SUPPLY, id: 3, name: 'Oil filter', unit_type: 'count' }
  const WIPER: Supply = { ...MOCK_SUPPLY, id: 4, name: 'Wiper', unit_type: 'count' }
  const OLD_VISIT: ServiceVisit = {
    id: 910,
    vin: 'TEST123',
    date: '2026-07-01',
    created_at: '2026-07-01T00:00:00',
    calculated_total_cost: '25.00',
    has_failed_inspections: false,
    line_item_count: 1,
    subtotal: '0',
    parts_supplies_cost: '25.00',
    vendor_id: null,
    odometer_km: null,
    notes: null,
    insurance_claim_number: null,
    tax_amount: null,
    shop_supplies: null,
    misc_fees: null,
    service_category: null,
    total_cost: '25.00',
    updated_at: null,
    vendor: null,
    line_items: [
      {
        id: 601,
        visit_id: 910,
        description: 'Filters',
        category: 'Maintenance',
        cost: '0',
        created_at: '2026-07-01T00:00:00',
        is_failed_inspection: false,
        is_inspection: false,
        needs_followup: false,
        notes: null,
        triggered_by_inspection_id: null,
        is_recall: false,
        is_warranty: false,
        supply_usages: [
          {
            id: 7,
            supply_id: 3,
            supply_name: 'Oil filter',
            unit_type: 'count',
            quantity: '2.5000000000000',
            created_at: '2026-07-01T00:00:00',
            service_line_item_id: 601,
            service_visit_id: 910,
            cost_snapshot: '25.00',
            unit_cost_snapshot: '10.00',
            cost_estimated: false,
            service_visit_date: '2026-07-01',
          },
        ],
      },
    ],
  }

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(useSupplies).mockReturnValue({
      data: { supplies: [FILTER, WIPER], total: 2 },
      isSuccess: true,
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof useSupplies>)
  })

  const quantities = (): HTMLInputElement[] =>
    screen.getAllByRole('textbox', { name: 'service.suppliesQuantityOf' }) as HTMLInputElement[]

  async function renderHydrated(): Promise<void> {
    render(<ServiceVisitForm {...DEFAULT_PROPS} visit={OLD_VISIT} />)
    await waitFor(() => expect(quantities()[0].value).toBe('2.5'))
  }

  async function expectRefused(): Promise<void> {
    fireEvent.submit(drawerForm())
    expect(await screen.findByText(/supplyQuantityWholeNumber/)).toBeTruthy()
    expect(mockedApiPut).not.toHaveBeenCalled()
  }

  it("a saved fractional count doesn't block an unrelated edit", async () => {
    await renderHydrated()

    fireEvent.submit(drawerForm())

    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    // Sent back as saved, so the API sees no change at all.
    const body = mockedApiPut.mock.calls.at(-1)?.[1] as {
      line_items: { id?: number; supplies_used: { supply_id: number; quantity: number | string }[] }[]
    }
    expect(body.line_items.find((li) => li.id === 601)?.supplies_used).toEqual([
      { supply_id: 3, quantity: '2.5000000000000' },
    ])
  })

  it('an untouched count too precise for a JS number goes back exactly as saved', async () => {
    // Number('1234.1234567890123') prints as ...124, which the API would read
    // as a changed fraction and refuse.
    const usage = OLD_VISIT.line_items[0].supply_usages![0]
    const precise: ServiceVisit = {
      ...OLD_VISIT,
      line_items: [{ ...OLD_VISIT.line_items[0], supply_usages: [{ ...usage, quantity: '1234.1234567890123' }] }],
    }
    render(<ServiceVisitForm {...DEFAULT_PROPS} visit={precise} />)
    await waitFor(() => expect(quantities()[0].value).not.toBe(''))

    fireEvent.submit(drawerForm())

    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    const body = mockedApiPut.mock.calls.at(-1)?.[1] as {
      line_items: { id?: number; supplies_used: { supply_id: number; quantity: number | string }[] }[]
    }
    expect(body.line_items.find((li) => li.id === 601)?.supplies_used).toEqual([
      { supply_id: 3, quantity: '1234.1234567890123' },
    ])
  })

  it('changing a saved count to another fraction is still refused', async () => {
    await renderHydrated()
    fireEvent.change(quantities()[0], { target: { value: '3.5' } })

    await expectRefused()
  })

  it('the saved value on a new line item is still refused', async () => {
    await renderHydrated()
    fireEvent.click(screen.getByRole('button', { name: 'service.addItem' }))
    const description = screen.getAllByText('lineItemEditor.misc.descriptionLabel')[1]
      .parentElement?.querySelector('input[type="text"]') as HTMLInputElement
    fireEvent.change(description, { target: { value: 'More filters' } })
    fireEvent.click(screen.getAllByRole('button', { name: /suppliesAddRow/ })[1])
    fireEvent.change(quantities()[1], { target: { value: '2.5' } })

    await expectRefused()
  })

  it('the saved value on a switched supply is still refused', async () => {
    await renderHydrated()
    fireEvent.change(screen.getAllByRole('combobox', { name: 'service.suppliesUsed' })[0], {
      target: { value: '4' },
    })

    await expectRefused()
  })
})
