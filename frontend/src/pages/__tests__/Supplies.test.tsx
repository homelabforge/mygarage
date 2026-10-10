import { StrictMode } from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, within, waitFor } from '../../__tests__/test-utils'
import type { Supply } from '../../types/supplies'
import { presetUnitsFor, type UnitSet } from '../../types/units'
import { setActiveLocale } from '../../constants/i18n'

// Mock the supplies query hooks so this stays a unit test — no real network
// calls needed. The api layer itself is already mocked globally (setup.ts
// mocks axios), so any hook we don't mock here still resolves harmlessly.
const useSuppliesMock = vi.fn()
const useDeleteSupplyMock = vi.fn()
// Stable across renders so the form tests can read back what got saved.
const createSupplyMock = vi.fn()
const updateSupplyMock = vi.fn()

const mutationStub = () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false, variables: undefined })

vi.mock('../../hooks/queries/useSupplies', () => ({
  useSupplies: () => useSuppliesMock(),
  useCreateSupply: () => ({ mutateAsync: createSupplyMock, mutate: vi.fn(), isPending: false }),
  useUpdateSupply: () => ({ mutateAsync: updateSupplyMock, mutate: vi.fn(), isPending: false }),
  useDeleteSupply: () => useDeleteSupplyMock(),
  // The quick-action tests mount the real SupplyHistoryModal, so its hooks
  // need inert stands-ins here too.
  useSupplyHistory: () => ({
    data: { entries: [], on_hand: '0.000', avg_unit_cost: null },
    isLoading: false,
    error: null,
  }),
  useAddPurchase: () => mutationStub(),
  useDeletePurchase: () => mutationStub(),
  useAddAdjustment: () => mutationStub(),
  useDeleteAdjustment: () => mutationStub(),
  useUploadReceipt: () => mutationStub(),
  useDeleteReceipt: () => mutationStub(),
}))

vi.mock('../../hooks/queries/useAddressBook', () => ({
  useAddressBookEntries: () => ({ data: [] }),
}))

vi.mock('../../hooks/queries/useQuickEntryVehicles', () => ({
  useQuickEntryVehicles: () => ({ data: [], isLoading: false }),
}))

// Same mock pattern as DEFRecordList.test.tsx — these hooks need AuthProvider
// otherwise, and it's not under test here.
const unitMock = vi.hoisted(() => ({
  system: 'metric' as 'metric' | 'imperial',
  units: null as UnitSet | null,
  gallonStandard: 'us' as 'us' | 'uk',
}))
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: unitMock.system,
    units: unitMock.units,
    gallonStandard: unitMock.gallonStandard,
    showBoth: false,
  }),
}))
// Sets the whole account in one go so system, set and gallon flavour can't disagree.
const setAccount = (system: 'metric' | 'imperial', flavour: 'us' | 'uk' = 'us'): void => {
  unitMock.system = system
  unitMock.units = presetUnitsFor(system, flavour)
  unitMock.gallonStandard = flavour
}
// The REAL currency hook runs, so a rate option has to survive it. Only the
// signed-in user is faked, and the rate-digits test flips them to yen.
const currencyMock = vi.hoisted(() => ({ code: 'USD' }))
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { currency_code: currencyMock.code } }),
}))
// Local i18n mock: a `{ unit }` call shows its unit so the avg-cost label can
// tell qt from fl oz. Everything else is the bare key, and t stays one stable
// function for the same reason setup.ts hoists its own.
vi.mock('react-i18next', () => {
  const t = (key: string, options?: { unit?: string }): string =>
    options?.unit !== undefined ? `${key} (${options.unit})` : key
  const i18n = { language: 'en', changeLanguage: () => Promise.resolve() }
  return {
    useTranslation: () => ({ t, i18n }),
    Trans: ({ children }: { children: React.ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

import Supplies from '../Supplies'

const mockSupply: Supply = {
  id: 1,
  name: 'Motor Oil 5W-30',
  unit_type: 'volume',
  category: 'Fluids',
  part_number: 'MO-530',
  vin: null,
  notes: null,
  on_hand: '10.500',
  avg_unit_cost: '5.25',
  is_active: true,
  is_negative: false,
  created_at: '2026-01-01T00:00:00',
  updated_at: null,
} as Supply

beforeEach(() => {
  vi.clearAllMocks()
  // The view pick persists on purpose, so tests must not inherit each other's.
  localStorage.clear()
  currencyMock.code = 'USD'
  setAccount('metric')
  createSupplyMock.mockResolvedValue({})
  updateSupplyMock.mockResolvedValue({})
  useSuppliesMock.mockReturnValue({
    data: { supplies: [mockSupply], total: 1 },
    isLoading: false,
    error: null,
  })
  useDeleteSupplyMock.mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
    variables: undefined,
  })
})

describe('Supplies page', () => {
  it('renders the supply list from useSupplies', () => {
    render(<Supplies />)

    expect(screen.getByText('Motor Oil 5W-30')).toBeInTheDocument()
    // The category filter's <option> shares the text, so scope to the chip.
    expect(screen.getAllByText('Fluids').length).toBeGreaterThan(1)
    expect(screen.getByText('MO-530')).toBeInTheDocument()
  })

  it('shows the empty state when there are no supplies', () => {
    useSuppliesMock.mockReturnValue({ data: { supplies: [], total: 0 }, isLoading: false, error: null })
    render(<Supplies />)

    expect(screen.getByText('supplies.noSupplies')).toBeInTheDocument()
  })

  it('opens the form modal when "Add supply" is clicked', () => {
    render(<Supplies />)

    // Select by id, not label text — the global i18n test mock renders keys,
    // so the form isn't visible until the click; the name input only exists
    // once the modal has mounted.
    expect(document.getElementById('name')).not.toBeInTheDocument()

    fireEvent.click(screen.getByText('supplies.addSupply'))

    expect(document.getElementById('name')).toBeInTheDocument()
    expect(document.getElementById('unit_type')).toBeInTheDocument()
    // unit_type is only disabled in edit mode — create mode leaves it editable
    expect(document.getElementById('unit_type')).not.toBeDisabled()
  })

  it('disables unit_type when editing an existing supply', () => {
    render(<Supplies />)

    fireEvent.click(screen.getByLabelText('common:edit'))

    expect(document.getElementById('unit_type')).toBeDisabled()
    // is_active toggle only appears on edit
    expect(document.getElementById('is_active')).toBeInTheDocument()
  })
})

describe('Supplies page toolbar: search and filters', () => {
  const fluidsA = { ...mockSupply, id: 11, name: 'Oil A', category: 'fluids' } as Supply
  const fluidsB = { ...mockSupply, id: 12, name: 'Oil B', category: 'Fluids' } as Supply
  const fluidsC = { ...mockSupply, id: 13, name: 'Oil C', category: 'Fluids' } as Supply
  const pinnedOut = {
    ...mockSupply, id: 14, name: 'Truck Brake Pads', category: null,
    vin: '1HGCM82633A004352', on_hand: '0.000',
  } as Supply

  beforeEach(() => {
    useSuppliesMock.mockReturnValue({
      data: { supplies: [fluidsA, fluidsB, fluidsC, pinnedOut], total: 4 },
      isLoading: false,
      error: null,
    })
  })

  it('a search with no hits hides the cards and offers clear filters', () => {
    render(<Supplies />)

    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'nomatch' } })

    expect(screen.queryByText('Oil A')).not.toBeInTheDocument()
    expect(screen.getByText('supplies.showingResults')).toBeInTheDocument()
    expect(screen.getByText('supplies.noMatches')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'supplies.clearFilters' })).toBeInTheDocument()
  })

  it('clear filters restores the cards and drops the showing line', () => {
    render(<Supplies />)

    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'nomatch' } })
    fireEvent.click(screen.getByRole('button', { name: 'supplies.clearFilters' }))

    expect(screen.getByText('Oil A')).toBeInTheDocument()
    expect(screen.queryByText('supplies.showingResults')).not.toBeInTheDocument()
  })

  it('the category select lists each category once, most common spelling', () => {
    render(<Supplies />)

    const select = screen.getByRole('combobox', { name: 'supplies.filterByCategory' })
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'supplies.allCategories', 'Fluids',
    ])
  })

  it('the vehicle select offers all, shared, and the raw VIN when quick entry does not know it', () => {
    render(<Supplies />)

    const select = screen.getByRole('combobox', { name: 'supplies.filterByVehicle' })
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'supplies.allVehicles', 'supplies.sharedVehicle', '1HGCM82633A004352',
    ])
  })

  it('the out of stock chip keeps only zero and negative rows', () => {
    render(<Supplies />)

    fireEvent.click(screen.getByRole('button', { name: 'supplies.outOfStock' }))

    expect(screen.getByText('Truck Brake Pads')).toBeInTheDocument()
    expect(screen.queryByText('Oil A')).not.toBeInTheDocument()
  })
})

describe('Supplies page toolbar: sort, group, view', () => {
  const alpha = { ...mockSupply, id: 21, name: 'Alpha Coolant', category: 'Fluids', on_hand: '5.000' } as Supply
  const zulu = { ...mockSupply, id: 22, name: 'Zulu Grease', category: null, on_hand: '0.000' } as Supply

  beforeEach(() => {
    localStorage.clear()
    useSuppliesMock.mockReturnValue({
      data: { supplies: [alpha, zulu], total: 2 },
      isLoading: false,
      error: null,
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  const cardNames = () =>
    screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)

  it('sorting by lowest stock reorders the cards', () => {
    render(<Supplies />)
    expect(cardNames()).toEqual(['Alpha Coolant', 'Zulu Grease'])

    fireEvent.click(screen.getByRole('button', { name: 'supplies.sortSupplies' }))
    fireEvent.click(screen.getByRole('menuitemradio', { name: 'supplies.sortByLowestStock' }))

    expect(cardNames()).toEqual(['Zulu Grease', 'Alpha Coolant'])
  })

  it('grouping by category renders group headings with the no-category bucket last', () => {
    render(<Supplies />)

    fireEvent.click(screen.getByRole('button', { name: 'supplies.groupSupplies' }))
    fireEvent.click(screen.getByRole('menuitemradio', { name: 'supplies.groupByCategory' }))

    const headings = screen.getAllByRole('heading', { level: 2 })
    expect(headings).toHaveLength(2)
    expect(headings[0]).toHaveTextContent('Fluids')
    expect(headings[1]).toHaveTextContent('supplies.noCategory')
  })

  it('the list view toggle renders a table with the fixture row', () => {
    render(<Supplies />)
    expect(screen.queryByRole('table')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'supplies.listView' }))

    const table = screen.getByRole('table')
    expect(within(table).getByText('Alpha Coolant')).toBeInTheDocument()
  })

  it('the view pick persists and a fresh render starts from it', () => {
    const first = render(<Supplies />)
    fireEvent.click(screen.getByRole('button', { name: 'supplies.listView' }))
    expect(JSON.parse(localStorage.getItem('mygarage:supplies:view')!).view).toBe('list')
    first.unmount()

    render(<Supplies />)
    expect(screen.getByRole('table')).toBeInTheDocument()
  })

  it('a throwing Storage still renders the grid default', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })

    render(<Supplies />)

    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.getByText('Alpha Coolant')).toBeInTheDocument()
  })
})

describe('Supplies page: out of stock highlight and the vehicle line', () => {
  const zero = { ...mockSupply, id: 31, name: 'Zero Oil', on_hand: '0.000' } as Supply
  const neg = { ...mockSupply, id: 32, name: 'Neg Oil', on_hand: '-1.000', is_negative: true } as Supply
  const shared = { ...mockSupply, id: 33, name: 'Shared Oil', vin: null } as Supply
  const pinned = { ...mockSupply, id: 34, name: 'Pinned Oil', vin: 'VINUNKNOWN123' } as Supply

  beforeEach(() => {
    localStorage.clear()
  })

  it('a zero-stock supply shows the chip in grid view and in list view', () => {
    useSuppliesMock.mockReturnValue({ data: { supplies: [zero], total: 1 }, isLoading: false, error: null })
    render(<Supplies />)

    // One occurrence is the toolbar filter chip; the second is the card's.
    expect(screen.getAllByText('supplies.outOfStock')).toHaveLength(2)

    fireEvent.click(screen.getByRole('button', { name: 'supplies.listView' }))
    expect(within(screen.getByRole('table')).getByText('supplies.outOfStock')).toBeInTheDocument()
  })

  it('a negative supply keeps the warning line, goes danger, and the chip shows once', () => {
    useSuppliesMock.mockReturnValue({ data: { supplies: [neg], total: 1 }, isLoading: false, error: null })
    render(<Supplies />)

    expect(screen.getByText('supplies.negativeWarning')).toBeInTheDocument()
    const card = screen.getByText('Neg Oil').closest('div[class*="border-danger"]')
    expect(card).not.toBeNull()
    expect(screen.getAllByText('supplies.outOfStock')).toHaveLength(2)
  })

  it('cards carry a vehicle line: shared label or the raw VIN fallback', () => {
    useSuppliesMock.mockReturnValue({ data: { supplies: [shared, pinned], total: 2 }, isLoading: false, error: null })
    render(<Supplies />)

    const sharedCard = screen.getByText('Shared Oil').closest('div[class*="bg-garage-surface"]')
    expect(within(sharedCard as HTMLElement).getByText('supplies.sharedVehicle')).toBeInTheDocument()
    const pinnedCard = screen.getByText('Pinned Oil').closest('div[class*="bg-garage-surface"]')
    expect(within(pinnedCard as HTMLElement).getByText('VINUNKNOWN123')).toBeInTheDocument()
  })
})

describe('Supplies page: review findings stay fixed', () => {
  it('persisting the view pick writes storage once per change (pure updater)', () => {
    // StrictMode double-invokes setState updaters, so a write inside the
    // updater runs twice; the write belongs beside setPrefs, not in it.
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem')
    render(
      <StrictMode>
        <Supplies />
      </StrictMode>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'supplies.listView' }))

    expect(setItemSpy.mock.calls.filter(([key]) => key === 'mygarage:supplies:view')).toHaveLength(1)
    setItemSpy.mockRestore()
  })

  it('a category literally named __trailing__ does not collide with the no-category bucket', () => {
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    useSuppliesMock.mockReturnValue({
      data: {
        supplies: [
          { ...mockSupply, id: 51, name: 'Weird Part', category: '__trailing__' },
          { ...mockSupply, id: 52, name: 'Bare Part', category: null },
        ],
        total: 2,
      },
      isLoading: false,
      error: null,
    })
    render(<Supplies />)

    fireEvent.click(screen.getByRole('button', { name: 'supplies.groupSupplies' }))
    fireEvent.click(screen.getByRole('menuitemradio', { name: 'supplies.groupByCategory' }))

    const headings = screen.getAllByRole('heading', { level: 2 })
    expect(headings[0]).toHaveTextContent('__trailing__')
    expect(headings[1]).toHaveTextContent('supplies.noCategory')
    const keyWarnings = errSpy.mock.calls.filter((args) =>
      args.some((a) => typeof a === 'string' && a.includes('same key')),
    )
    expect(keyWarnings).toHaveLength(0)
    errSpy.mockRestore()
  })
})

describe('Supplies page quick actions', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('the card offers log purchase and adjustment, and purchase opens that form', () => {
    render(<Supplies />)

    expect(screen.getByRole('button', { name: 'supplies.history.logAdjustment' })).toBeInTheDocument()
    expect(document.getElementById('purchase-date')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'supplies.history.logPurchase' }))

    expect(document.getElementById('purchase-date')).toBeInTheDocument()
  })

  it('list rows carry the same quick actions', () => {
    render(<Supplies />)

    fireEvent.click(screen.getByRole('button', { name: 'supplies.listView' }))

    const table = screen.getByRole('table')
    expect(within(table).getByRole('button', { name: 'supplies.history.logPurchase' })).toBeInTheDocument()
    expect(within(table).getByRole('button', { name: 'supplies.history.logAdjustment' })).toBeInTheDocument()
  })
})

describe('SupplyForm category suggestions', () => {
  it('the add form offers one datalist option per canonical category', () => {
    useSuppliesMock.mockReturnValue({
      data: {
        supplies: [
          { ...mockSupply, id: 41, category: 'fluids' },
          { ...mockSupply, id: 42, category: 'Fluids' },
          { ...mockSupply, id: 43, category: 'Fluids' },
        ],
        total: 3,
      },
      isLoading: false,
      error: null,
    })
    render(<Supplies />)

    fireEvent.click(screen.getByText('supplies.addSupply'))

    // The form modal portals, so query the document, not the container.
    const datalist = document.querySelector('datalist#supply-category-suggestions')
    expect(datalist).not.toBeNull()
    expect([...datalist!.querySelectorAll('option')].map((o) => o.value)).toEqual(['Fluids'])
    expect(document.getElementById('category')).toHaveAttribute('list', 'supply-category-suggestions')
  })
})

describe('Supplies page — the average unit cost is a rate', () => {
  it('shows a yen unit cost with its decimals', () => {
    currencyMock.code = 'JPY'
    useSuppliesMock.mockReturnValue({
      data: { supplies: [{ ...mockSupply, avg_unit_cost: '170.5' }], total: 1 },
      isLoading: false,
      error: null,
    })
    render(<Supplies />)

    expect(screen.getByText('¥170.50')).toBeInTheDocument()
    expect(screen.queryByText('¥171')).not.toBeInTheDocument()
  })

  it('leaves the dollar unit cost where it was', () => {
    render(<Supplies />)
    expect(screen.getByText('$5.25')).toBeInTheDocument()
  })
})

describe('Supplies page: the unit cost is per the unit the stock is shown in', () => {
  // 5 qt for $25 is stored as 4.732 L, so the API's average is $5.2832 per litre.
  const perLitre = { ...mockSupply, avg_unit_cost: String(25 / 4.732) }

  it('prices a quart for an imperial user', () => {
    setAccount('imperial')
    useSuppliesMock.mockReturnValue({ data: { supplies: [perLitre], total: 1 }, isLoading: false, error: null })
    render(<Supplies />)

    expect(screen.getByText('$5.00')).toBeInTheDocument()
    expect(screen.queryByText('$5.28')).not.toBeInTheDocument()
    expect(screen.getByText('supplies.avgCostPerUnit (qt)')).toBeInTheDocument()
  })

  it('prices a litre for a metric user', () => {
    useSuppliesMock.mockReturnValue({ data: { supplies: [perLitre], total: 1 }, isLoading: false, error: null })
    render(<Supplies />)

    expect(screen.getByText('$5.28')).toBeInTheDocument()
    expect(screen.getByText('supplies.avgCostPerUnit (L)')).toBeInTheDocument()
  })

  it('keeps the plain label for a counted supply', () => {
    setAccount('imperial')
    useSuppliesMock.mockReturnValue({
      data: { supplies: [{ ...perLitre, unit_type: 'count', on_hand: '4' }], total: 1 },
      isLoading: false,
      error: null,
    })
    render(<Supplies />)

    expect(screen.getByText('$5.28')).toBeInTheDocument()
    expect(screen.getByText('supplies.avgUnitCost')).toBeInTheDocument()
  })
})

describe('Supplies page: each supply shows its own unit', () => {
  // US fl oz is a gallon over 128, so this is $0.50 per fl oz and $16.91 per litre.
  const perFlOz = String(0.5 / (3.785411784 / 128))

  it('a fl oz supply shows stock and price in fl oz, even for a metric user', () => {
    useSuppliesMock.mockReturnValue({
      data: {
        supplies: [{ ...mockSupply, volume_unit: 'fl_oz_us', on_hand: '0.355', avg_unit_cost: perFlOz }],
        total: 1,
      },
      isLoading: false,
      error: null,
    })
    render(<Supplies />)

    expect(screen.getByText('12.00 fl oz')).toBeInTheDocument()
    expect(screen.getByText('supplies.avgCostPerUnit (fl oz)')).toBeInTheDocument()
    expect(screen.getByText('$0.50')).toBeInTheDocument()
    expect(screen.queryByText('$16.91')).not.toBeInTheDocument()
  })

  it('a 3 mL on-hand reads 0.003 L, not 0.00 L', () => {
    useSuppliesMock.mockReturnValue({
      data: { supplies: [{ ...mockSupply, on_hand: '0.003' }], total: 1 },
      isLoading: false,
      error: null,
    })
    render(<Supplies />)

    expect(screen.getByText('0.003 L')).toBeInTheDocument()
    expect(screen.queryByText('0.00 L')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'supplies.listView' }))
    expect(within(screen.getByRole('table')).getByText('0.003 L')).toBeInTheDocument()
  })

  it('on-hand follows the picked language, not toFixed', () => {
    setActiveLocale('de')
    try {
      render(<Supplies />)
      expect(screen.getByText('10,50 L')).toBeInTheDocument()
    } finally {
      setActiveLocale('en')
    }
  })

  it('a mL supply shows whole millilitres', () => {
    useSuppliesMock.mockReturnValue({
      data: { supplies: [{ ...mockSupply, volume_unit: 'mL', on_hand: '0.250' }], total: 1 },
      isLoading: false,
      error: null,
    })
    render(<Supplies />)

    expect(screen.getByText('250 mL')).toBeInTheDocument()
  })

  it('a mL supply prices per mL to four places, card and list', () => {
    // $5.25/L is $0.00525/mL; two places would round it to $0.01.
    useSuppliesMock.mockReturnValue({
      data: { supplies: [{ ...mockSupply, volume_unit: 'mL', avg_unit_cost: '5.25' }], total: 1 },
      isLoading: false,
      error: null,
    })
    render(<Supplies />)

    expect(screen.getByText('$0.0053')).toBeInTheDocument()
    expect(screen.queryByText('$0.01')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'supplies.listView' }))
    expect(within(screen.getByRole('table')).getByText('$0.0053')).toBeInTheDocument()
  })

  it('a legacy supply with no unit still follows the imperial pick to qt', () => {
    setAccount('imperial')
    useSuppliesMock.mockReturnValue({
      data: { supplies: [{ ...mockSupply, volume_unit: null }], total: 1 },
      isLoading: false,
      error: null,
    })
    render(<Supplies />)

    // 10.5 L is 11.095 US qt.
    expect(screen.getByText('11.10 qt')).toBeInTheDocument()
    expect(screen.getByText('supplies.avgCostPerUnit (qt)')).toBeInTheDocument()
  })
})

describe('SupplyForm: the volume unit picker', () => {
  const US = ['mL', 'L', 'fl_oz_us', 'qt_us', 'gal_us']
  const UK = ['mL', 'L', 'fl_oz_uk', 'qt_uk', 'gal_uk']

  // The modal portals, so these read the document, not the render container.
  const unitSelect = () => document.getElementById('volume_unit') as HTMLSelectElement | null
  const offered = () => [...unitSelect()!.options].map((o) => o.value)
  const submit = () => fireEvent.submit(document.getElementById('supply-form') as HTMLFormElement)
  const lastPayload = (spy: typeof createSupplyMock) => spy.mock.calls.at(-1)?.[0] as Record<string, unknown>

  const openAdd = () => {
    render(<Supplies />)
    fireEvent.click(screen.getByText('supplies.addSupply'))
  }
  const openEdit = (supply: Supply) => {
    useSuppliesMock.mockReturnValue({ data: { supplies: [supply], total: 1 }, isLoading: false, error: null })
    render(<Supplies />)
    fireEvent.click(screen.getByLabelText('common:edit'))
  }

  it('a US account starts a new supply in US quarts and offers only US flavours', () => {
    setAccount('imperial', 'us')
    openAdd()

    expect(unitSelect()?.value).toBe('qt_us')
    expect(offered()).toEqual(US)
    // Litres and gallons reuse the Settings labels; the rest are supply keys.
    expect([...unitSelect()!.options].map((o) => o.textContent)).toEqual([
      'common:supplies.volumeUnits.mL',
      'settings:units.options.volume.L',
      'common:supplies.volumeUnits.fl_oz_us',
      'common:supplies.volumeUnits.qt_us',
      'settings:units.options.volume.gal_us',
    ])
    expect(screen.getByText('supplies.volumeUnit')).toBeInTheDocument()
    expect(document.getElementById('volume_unit-hint')).toHaveTextContent('supplies.volumeUnitHint')
  })

  it('a UK account starts in UK quarts and the create payload saves them', async () => {
    setAccount('imperial', 'uk')
    openAdd()

    expect(unitSelect()?.value).toBe('qt_uk')
    expect(offered()).toEqual(UK)

    fireEvent.change(document.getElementById('name')!, { target: { value: 'Gear Oil' } })
    submit()

    await waitFor(() => expect(createSupplyMock).toHaveBeenCalled())
    expect(lastPayload(createSupplyMock)).toMatchObject({ unit_type: 'volume', volume_unit: 'qt_uk' })
  })

  it('a metric account starts in litres', () => {
    openAdd()

    expect(unitSelect()?.value).toBe('L')
    expect(offered()).toEqual(US)
  })

  it('the create payload carries the unit picked', async () => {
    setAccount('imperial', 'us')
    openAdd()

    fireEvent.change(document.getElementById('name')!, { target: { value: 'Brake Fluid' } })
    fireEvent.change(unitSelect()!, { target: { value: 'mL' } })
    submit()

    await waitFor(() => expect(createSupplyMock).toHaveBeenCalled())
    expect(lastPayload(createSupplyMock).volume_unit).toBe('mL')
  })

  it('switching a new supply to count drops the picker and the payload leaves volume_unit out', async () => {
    setAccount('imperial', 'us')
    openAdd()
    expect(unitSelect()).not.toBeNull()

    fireEvent.change(document.getElementById('unit_type')!, { target: { value: 'count' } })
    expect(unitSelect()).toBeNull()

    // The form still holds qt_us for the hidden field, so the payload has to drop it.
    fireEvent.change(document.getElementById('name')!, { target: { value: 'Oil Filter' } })
    submit()

    await waitFor(() => expect(createSupplyMock).toHaveBeenCalled())
    const payload = lastPayload(createSupplyMock)
    expect(payload.unit_type).toBe('count')
    expect('volume_unit' in payload).toBe(false)
  })

  it('editing a legacy supply on an imperial account preselects US quarts and an untouched save writes them', async () => {
    setAccount('imperial', 'us')
    openEdit({ ...mockSupply, volume_unit: null })

    expect(unitSelect()?.value).toBe('qt_us')

    submit()

    await waitFor(() => expect(updateSupplyMock).toHaveBeenCalled())
    expect(lastPayload(updateSupplyMock)).toMatchObject({ id: 1, volume_unit: 'qt_us' })
  })

  it('a legacy supply on a UK account keeps the US quart it is shown in', () => {
    setAccount('imperial', 'uk')
    openEdit({ ...mockSupply, volume_unit: null })

    expect(unitSelect()?.value).toBe('qt_us')
    expect(offered()).toEqual([...UK, 'qt_us'])
  })

  it('editing a UK-quart supply on a US account keeps qt_uk on offer', () => {
    setAccount('imperial', 'us')
    openEdit({ ...mockSupply, volume_unit: 'qt_uk' })

    expect(unitSelect()?.value).toBe('qt_uk')
    expect(offered()).toEqual([...US, 'qt_uk'])
  })

  it('guard: editing a count supply shows no picker and the PATCH leaves volume_unit out (mutant: update always sends it)', async () => {
    setAccount('imperial', 'us')
    openEdit({ ...mockSupply, unit_type: 'count', on_hand: '4.000', volume_unit: null })

    expect(document.getElementById('name')).toBeInTheDocument()
    expect(unitSelect()).toBeNull()

    submit()

    await waitFor(() => expect(updateSupplyMock).toHaveBeenCalled())
    expect('volume_unit' in lastPayload(updateSupplyMock)).toBe(false)
  })
})
