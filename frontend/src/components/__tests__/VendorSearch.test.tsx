import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, fireEvent, act, within } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import type { Vendor } from '../../types/vendor'

// Timers, fetches and ARIA only, so jsdom covers it.

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../services/api', () => ({ default: { get, post } }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
// The lender call site's own hooks; VendorSearch itself stays real here.
vi.mock('../../hooks/queries/useFinancingRecords', () => ({
  useCreateFinancingRecord: () => ({ mutateAsync: vi.fn() }),
  useUpdateFinancingRecord: () => ({ mutateAsync: vi.fn() }),
}))
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US', formatCurrency: vi.fn() }),
}))

import VendorSearch from '../VendorSearch'
import FinancingRecordForm from '../FinancingRecordForm'

const vendor = (id: number, name: string): Vendor => ({ id, name }) as Vendor
const MAVIS = vendor(1, 'Mavis')
const MAACO = vendor(2, 'Maaco')

type SearchResponse = { data: { vendors: Vendor[] } }
const found = (...vendors: Vendor[]): SearchResponse => ({ data: { vendors } })

interface Deferred<T> {
  promise: Promise<T>
  resolve: (value: T) => void
}

const deferred = <T,>(): Deferred<T> => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

// By placeholder, not role or id: the stale-guard cases have to fail on their own assertion
// on the old component, whose box was a plain textbox that took no id.
const box = (): HTMLInputElement => screen.getByPlaceholderText('vendorSearch.placeholder')
const type = (text: string): void => {
  fireEvent.change(box(), { target: { value: text } })
}
const wait = async (ms: number): Promise<void> => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}
const noResults = (): HTMLElement | null => screen.queryByText('vendorSearch.noResults')

beforeEach(() => {
  vi.useFakeTimers()
  get.mockReset()
  post.mockReset()
  get.mockResolvedValue(found(MAVIS, MAACO))
})

afterEach(() => {
  vi.useRealTimers()
})

describe('VendorSearch as a combobox (G-4)', () => {
  it('ArrowDown moves aria-activedescendant and Enter picks the highlighted vendor', async () => {
    // No roles and no keys at all: the list was mouse-only.
    const onSelect = vi.fn()
    render(<VendorSearch id="vendor" onSelect={onSelect} />)
    box().focus()
    type('Ma')
    await wait(300)
    const combo = screen.getByRole('combobox')
    expect(combo).toHaveAttribute('aria-expanded', 'true')
    expect(combo).toHaveAttribute('aria-autocomplete', 'list')
    const list = screen.getByRole('listbox')
    expect(combo).toHaveAttribute('aria-controls', list.id)
    const [mavis, maaco] = within(list).getAllByRole('option')
    fireEvent.keyDown(combo, { key: 'ArrowDown' })
    expect(combo).toHaveAttribute('aria-activedescendant', mavis.id)
    fireEvent.keyDown(combo, { key: 'ArrowDown' })
    expect(combo).toHaveAttribute('aria-activedescendant', maaco.id)
    expect(maaco).toHaveAttribute('aria-selected', 'true')
    expect(combo).toHaveFocus()
    fireEvent.keyDown(combo, { key: 'Enter' })
    expect(onSelect).toHaveBeenCalledWith(MAACO)
  })

  it('"Create as new" is the last option, and its name box is labelled', async () => {
    // The create row was a button past the list, out of the arrow keys' reach, and its
    // name box had only a placeholder.
    render(<VendorSearch id="vendor" onSelect={vi.fn()} />)
    type('Ma')
    await wait(300)
    const options = within(screen.getByRole('listbox')).getAllByRole('option')
    expect(options).toHaveLength(3)
    expect(options[2]).toHaveTextContent('vendorSearch.createAsNew')
    for (let i = 0; i < 3; i++) fireEvent.keyDown(box(), { key: 'ArrowDown' })
    expect(box()).toHaveAttribute('aria-activedescendant', options[2].id)
    fireEvent.keyDown(box(), { key: 'Enter' })
    expect(screen.getByRole('textbox', { name: 'vendorSearch.newVendorName' })).toHaveValue('Ma')
  })

  it('Escape closes the list', async () => {
    render(<VendorSearch id="vendor" onSelect={vi.fn()} />)
    type('Ma')
    await wait(300)
    expect(screen.getByText('Mavis')).toBeInTheDocument()
    fireEvent.keyDown(box(), { key: 'Escape' })
    expect(screen.queryByText('Mavis')).not.toBeInTheDocument()
  })

  it('a keyboard pick leaves focus on the clear button, not the page', async () => {
    // The pick unmounted the focused search box and nothing caught focus, so it fell to <body>.
    render(<VendorSearch id="vendor" onSelect={vi.fn()} />)
    box().focus()
    type('Ma')
    await wait(300)
    fireEvent.keyDown(box(), { key: 'ArrowDown' })
    fireEvent.keyDown(box(), { key: 'Enter' })
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'vendorSearch.clear' }))
  })

  it('creating a vendor leaves focus on the clear button', async () => {
    // Same drop as a pick: the new-vendor box unmounted under focus.
    post.mockResolvedValue({ data: vendor(3, 'Ma Garage') })
    render(<VendorSearch id="vendor" onSelect={vi.fn()} />)
    type('Ma')
    await wait(300)
    for (let i = 0; i < 3; i++) fireEvent.keyDown(box(), { key: 'ArrowDown' })
    fireEvent.keyDown(box(), { key: 'Enter' })
    const name = screen.getByRole('textbox', { name: 'vendorSearch.newVendorName' })
    name.focus()
    await act(async () => {
      fireEvent.keyDown(name, { key: 'Enter' })
    })
    expect(post).toHaveBeenCalledTimes(1)
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'vendorSearch.clear' }))
  })

  it('a vendor loaded from the saved value does not take focus', async () => {
    // Guard, passes before the fix: only a pick moves focus. Killed by the mutant that
    // focuses the clear button whenever a vendor is set.
    get.mockResolvedValueOnce({ data: MAVIS })
    render(
      <>
        <input aria-label="elsewhere" />
        <VendorSearch id="vendor" value={1} onSelect={vi.fn()} />
      </>
    )
    const elsewhere = screen.getByRole('textbox', { name: 'elsewhere' })
    elsewhere.focus()
    await wait(0)
    expect(screen.getByRole('button', { name: 'vendorSearch.clear' })).toBeInTheDocument()
    expect(document.activeElement).toBe(elsewhere)
  })

  it('the clear button has a name', async () => {
    // An X icon with no aria-label or title, read as an unnamed button.
    render(<VendorSearch id="vendor" onSelect={vi.fn()} />)
    type('Ma')
    await wait(300)
    fireEvent.click(screen.getByText('Mavis'))
    expect(screen.getByRole('button', { name: 'vendorSearch.clear' })).toBeInTheDocument()
  })
})

describe('VendorSearch stale results (G-3)', () => {
  it('no "No vendors found" for text whose search has not answered yet', async () => {
    // The empty row read the current text against the last search's results.
    get.mockResolvedValueOnce(found())
    render(<VendorSearch id="vendor" onSelect={vi.fn()} />)
    type('Zq')
    await wait(300)
    expect(noResults()).toBeInTheDocument()
    const late = deferred<SearchResponse>()
    get.mockReturnValueOnce(late.promise)
    type('Zqx')
    expect(noResults()).not.toBeInTheDocument()
    await wait(300)
    expect(get).toHaveBeenCalledTimes(2)
    expect(noResults()).not.toBeInTheDocument()
    await act(async () => {
      late.resolve(found())
    })
    expect(noResults()).toBeInTheDocument()
  })

  it('a slow answer for old text does not replace the newer one', async () => {
    // No request guard: whichever answer landed last won, even for text long gone.
    const slow = deferred<SearchResponse>()
    get.mockReturnValueOnce(slow.promise)
    render(<VendorSearch id="vendor" onSelect={vi.fn()} />)
    type('Ma')
    await wait(300)
    get.mockResolvedValueOnce(found(MAACO))
    type('Maa')
    await wait(300)
    expect(screen.getByText('Maaco')).toBeInTheDocument()
    await act(async () => {
      slow.resolve(found(MAVIS))
    })
    expect(screen.queryByText('Mavis')).not.toBeInTheDocument()
    expect(screen.getByText('Maaco')).toBeInTheDocument()
  })

  it('a failed search says so instead of "No vendors found"', async () => {
    // The catch emptied the list, which read as no vendors.
    get.mockRejectedValueOnce(new Error('network down'))
    render(<VendorSearch id="vendor" onSelect={vi.fn()} />)
    type('Ma')
    await wait(300)
    expect(noResults()).not.toBeInTheDocument()
    expect(screen.getByText('vendorSearch.searchFailed')).toBeInTheDocument()
  })
})

describe('VendorSearch at a call site', () => {
  it("the lender box is found by the form's label", () => {
    // The label had no htmlFor and VendorSearch took no id, so the box had no name.
    vi.useRealTimers()
    render(<FinancingRecordForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    expect(screen.getByLabelText('financing.lender')).toHaveAttribute('role', 'combobox')
  })
})
