import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, fireEvent, within } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import ServiceVisitForm from '../ServiceVisitForm'
import { useSupplies } from '../../hooks/queries/useSupplies'
import { toCanonical, toDisplay } from '../../utils/supplyUnits'
import { formatCurrency } from '../../utils/formatUtils'
import type { Supply } from '../../types/supplies'
import type { ServiceVisit } from '../../types/serviceVisit'

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
  return {
    useUnitPreference: () => ({
      system: 'imperial',
      showBoth: false,
      units: IMPERIAL_UNITS,
      gallonStandard: 'us',
    }),
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

    const quantityInput = screen.getByRole('spinbutton', { name: 'service.suppliesQuantity' })
    fireEvent.change(quantityInput, { target: { value: '2' } })

    // The Total block now formats through the shared formatCurrency (SDQ-3), not a
    // hardcoded `$`+toFixed. USD/en-US (the mocked currency prefs) → "$18.93"; the
    // value is still derived from the canonical quantity, so it discriminates the
    // parts+supplies cost (a dropped canonical conversion or a wrong unit-cost fails).
    // MOCK_SUPPLY has no stored token, so under the imperial mock it falls back to US quarts.
    const expectedCanonicalQty = toCanonical(2, 'qt_us')
    const expectedPartsSuppliesCost = formatCurrency(10 * expectedCanonicalQty, { currencyCode: 'USD', locale: 'en-US' })
    const partsSuppliesRow = screen.getByText('service.partsSupplies:').closest('div')
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

  it('removes a supply usage row and sends an empty supplies_used array', async () => {
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)

    fillRequiredDescription()
    fireEvent.click(screen.getByRole('button', { name: /suppliesAddRow/ }))
    expect(screen.getByRole('spinbutton', { name: 'service.suppliesQuantity' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'service.suppliesRemoveRow' }))
    expect(screen.queryByRole('spinbutton', { name: 'service.suppliesQuantity' })).not.toBeInTheDocument()
    expect(screen.queryByText('service.partsSupplies:')).not.toBeInTheDocument()

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
        const quantityInput = screen.getByRole('spinbutton', {
          name: 'service.suppliesQuantity',
        }) as HTMLInputElement
        expect(Number(quantityInput.value)).toBeCloseTo(expectedDisplayQty, 6)
      })
    })

    it('resends the hydrated supplies_used (converted back to canonical) even when nothing else was touched — proves editing does not wipe usages', async () => {
      render(<ServiceVisitForm {...DEFAULT_PROPS} visit={MOCK_VISIT} />)

      // Wait for hydration before submitting, otherwise the still-empty [] would
      // race the effect and falsely appear to "work".
      await waitFor(() => {
        expect(screen.getByRole('spinbutton', { name: 'service.suppliesQuantity' })).toBeInTheDocument()
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
                service_visit_date: '2026-07-01',
              },
            ],
          },
        ],
      }

      render(<ServiceVisitForm {...DEFAULT_PROPS} visit={visit} />)
      await waitFor(() => {
        expect(
          screen.getByRole('spinbutton', { name: 'service.suppliesQuantity' }),
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
            service_visit_date: '2026-07-01',
          },
        ],
      },
    ],
  })

  const quantityInputs = (): HTMLInputElement[] =>
    screen.getAllByRole('spinbutton', { name: 'service.suppliesQuantity' }) as HTMLInputElement[]

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
