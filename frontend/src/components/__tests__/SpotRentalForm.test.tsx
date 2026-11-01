import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { render } from '../../__tests__/test-utils'
import { registeredFieldNames, submitAndSettle, validationError, whereA422Lands } from '../../__tests__/serverErrors'
import type { SpotRental } from '../../types/spotRental'

const createMutateAsync = vi.fn().mockResolvedValue({})
const updateMutateAsync = vi.fn().mockResolvedValue({})
vi.mock('../../hooks/queries/useSpotRentals', () => ({
  useCreateSpotRental: () => ({ mutateAsync: createMutateAsync }),
  useUpdateSpotRental: () => ({ mutateAsync: updateMutateAsync }),
}))
// B1: SpotRentalForm renders 5 CurrencyInputPrefix → useCurrencySymbol → useCurrencyPreference → useAuth
// (hooks/useCurrencyPreference.ts). test-utils provides NO AuthProvider, so mock useCurrencyPreference — the SAME
// deterministic mock the shipped P6c-2 form tests use — or the suite throws `useAuth must be used within an
// AuthProvider` before reaching any assertion.
vi.mock('../../hooks/useCurrencyPreference', () => ({ useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US', formatCurrency: vi.fn(), symbol: '$' }) }))
// B4: mock the shared axios instance so (1) the Save-path test can assert the exact address-book POST
// (handleSaveToAddressBook posts `/address-book`), and (2) AddressBookAutocomplete's debounced api.get resolves to
// an empty result set instead of a real network request. Both the form and AddressBookAutocomplete import the SAME
// `../services/api`, so this one mock covers both.
const apiPost = vi.fn().mockResolvedValue({ data: {} })
vi.mock('../../services/api', () => ({
  default: {
    post: (...a: unknown[]) => apiPost(...a),
    get: vi.fn().mockResolvedValue({ data: { entries: [] } }),
  },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import SpotRentalForm from '../SpotRentalForm'

beforeEach(() => vi.clearAllMocks())

// M1: fill via the LABEL→control association (getByLabelText) with the i18n mock echoing keys, so Field renders
// these exact accessible names (label + ' *' on the one required field, check_in_date). The current raw
// <label htmlFor>+<input id> render the SAME names Field will, so these characterize behavior that must SURVIVE
// the restyle — every case is GREEN pre- and post-restyle and is SABOTAGE-proven (never a fake RED).
describe('SpotRentalForm — routing + exact payload (SDQ-C)', () => {
  it('create submits the COMPLETE payload and routes to create, never update (fails if a field is dropped/mistyped or it misroutes)', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn(); const onSuccess = vi.fn()
    render(<SpotRentalForm vin="V1" onClose={onClose} onSuccess={onSuccess} />)
    // Fill ONLY the required check_in_date (leave location_name + all rates empty) so the auto-calc `> 0` guard
    // never fires and total_cost stays undefined — a fully deterministic payload with no auto-calc timing.
    fireEvent.change(screen.getByLabelText('spotRental.checkInDate *'), { target: { value: '2026-03-01' } })
    await user.click(screen.getByRole('button', { name: 'common:create' }))
    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    // The onSubmit object sets ALL 13 keys explicitly (undefined for the untouched ones) — toStrictEqual keeps
    // undefined-valued keys, so a dropped key fails. No `vin` (the hook closes over it).
    expect(createMutateAsync.mock.calls[0][0]).toStrictEqual({
      location_name: undefined,
      location_address: undefined,
      check_in_date: '2026-03-01',
      check_out_date: undefined,
      nightly_rate: undefined,
      weekly_rate: undefined,
      monthly_rate: undefined,
      electric: undefined,
      water: undefined,
      waste: undefined,
      total_cost: undefined,
      amenities: undefined,
      notes: undefined,
    })
    expect(updateMutateAsync).not.toHaveBeenCalled()
    // No new location_name ⇒ the nested prompt does NOT open; the straight path calls onSuccess + onClose.
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('edit submits the UPDATE payload — routing id + edited note — and never calls create (fails if it misroutes, drops the id, or drops a seeded field)', async () => {
    const rental = {
      id: 7, vin: 'V1', location_name: 'Lakeside', location_address: '123 Rd',
      check_in_date: '2026-03-01', check_out_date: null,
      nightly_rate: '45', weekly_rate: null, monthly_rate: null,
      electric: null, water: null, waste: null, total_cost: '45',
      amenities: 'wifi', notes: 'nice', billings: [], created_at: '2026-03-01T00:00:00',
    } as unknown as SpotRental
    const user = userEvent.setup()
    const onClose = vi.fn(); const onSuccess = vi.fn()
    render(<SpotRentalForm vin="V1" rental={rental} onClose={onClose} onSuccess={onSuccess} />)
    await user.clear(screen.getByLabelText('common:notes'))
    await user.type(screen.getByLabelText('common:notes'), 'updated')
    await user.click(screen.getByRole('button', { name: 'common:update' }))
    await waitFor(() => expect(updateMutateAsync).toHaveBeenCalledTimes(1))
    // rateType resolves to 'nightly' (no weekly/monthly seeded) ⇒ nightly_rate=45, and the stored total goes back
    // as is. A field stored empty posts null on edit, which is what's stored.
    expect(updateMutateAsync.mock.calls[0][0]).toStrictEqual({
      id: 7,
      location_name: 'Lakeside',
      location_address: '123 Rd',
      check_in_date: '2026-03-01',
      check_out_date: null,
      nightly_rate: 45,
      weekly_rate: null,
      monthly_rate: null,
      electric: null,
      water: null,
      waste: null,
      total_cost: 45,
      amenities: 'wifi',
      notes: 'updated',
    })
    expect(createMutateAsync).not.toHaveBeenCalled()
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})

describe('SpotRentalForm — nested Save-to-Address-Book confirm (LD8 wiring net + B4 Save/close paths)', () => {
  // Shared setup: fill the required date, type a NEW location name (not from the address book), create → the
  // nested "Save to Address Book" prompt opens (the create already succeeded; onClose is deferred until the
  // prompt resolves).
  const reachPrompt = async (user: ReturnType<typeof userEvent.setup>) => {
    fireEvent.change(screen.getByLabelText('spotRental.checkInDate *'), { target: { value: '2026-03-01' } })
    // AddressBookAutocomplete (id="location_name"); the mocked api.get returns {data:{entries:[]}}, so the search
    // yields no entries and selectedAddressEntry stays null ⇒ the new-location branch runs.
    await user.type(screen.getByLabelText('spotRental.locationName'), 'Lakeside RV')
    await user.click(screen.getByRole('button', { name: 'common:create' }))
    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    expect(await screen.findByText('spotRental.saveToAddressBookPrompt')).toBeInTheDocument()
  }

  it('after creating a NEW location the nested prompt appears and the form is NOT yet closed; clicking No/Skip routes to skipSaveToAddressBook → onSuccess + onClose (fails if the nested-confirm open/skip wiring is disturbed)', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn(); const onSuccess = vi.fn()
    render(<SpotRentalForm vin="V1" onClose={onClose} onSuccess={onSuccess} />)
    await reachPrompt(user)
    // The nested <Drawer open> mounts its prompt body; onClose has NOT fired (the save-succeeded path is waiting).
    expect(onClose).not.toHaveBeenCalled()
    // The footer "No/Skip" <Button> routes to skipSaveToAddressBook → onSuccess + onClose; no address-book POST.
    await user.click(screen.getByRole('button', { name: 'spotRental.noSkip' }))
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
    expect(onSuccess).toHaveBeenCalledTimes(1)
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('B4(a) — clicking Save (Yes) POSTs the exact address-book payload to the real endpoint, then completes via onSuccess + onClose (fails if handleSaveToAddressBook is unwired or the endpoint/payload changes)', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn(); const onSuccess = vi.fn()
    render(<SpotRentalForm vin="V1" onClose={onClose} onSuccess={onSuccess} />)
    await reachPrompt(user)
    await user.click(screen.getByRole('button', { name: 'spotRental.yesSave' }))
    // The REAL handleSaveToAddressBook (SpotRentalForm.tsx:122-140) POSTs api.post('/address-book',
    // {business_name, address, category: 'RV Park'}). location_address was never filled ⇒ address ''.
    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1))
    expect(apiPost).toHaveBeenCalledWith('/address-book', {
      business_name: 'Lakeside RV',
      address: '',
      category: 'RV Park',
    })
    // The finally block completes the flow regardless of POST outcome.
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
    expect(onSuccess).toHaveBeenCalledTimes(1)
  })

  it('B4(b) — the nested Drawer close mechanism (Escape) routes onClose={skipSaveToAddressBook} → onSuccess + onClose, and does NOT POST (fails if the nested Drawer onClose wiring is disturbed)', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn(); const onSuccess = vi.fn()
    render(<SpotRentalForm vin="V1" onClose={onClose} onSuccess={onSuccess} />)
    await reachPrompt(user)
    // Escape on the NESTED dialog (scoped by its accessible name so it never resolves the outer form Drawer). The
    // nested Drawer's capture-phase keydown listener stopImmediatePropagation()s, so ONLY its onClose
    // (skipSaveToAddressBook) runs — proving the Drawer close mechanism itself, not just the footer button.
    const nestedDialog = screen.getByRole('dialog', { name: 'spotRental.saveToAddressBook' })
    fireEvent.keyDown(nestedDialog, { key: 'Escape' })
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
    expect(onSuccess).toHaveBeenCalledTimes(1)
    expect(apiPost).not.toHaveBeenCalled()
  })
})

describe('SpotRentalForm: a rejected save', () => {
  const rentalForm = (): HTMLFormElement => document.getElementById('spot-rental-form') as HTMLFormElement
  const banner = (): HTMLElement | null => screen.queryByText(/^Failed to spotRental\.saveAction\./)
  const openFilled = (): void => {
    render(<SpotRentalForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    fireEvent.change(document.getElementById('check_in_date')!, { target: { value: '2026-03-01' } })
  }

  it('a non-422 failure shows the banner and no field error', async () => {
    createMutateAsync.mockRejectedValueOnce(new Error('Network Error'))
    openFilled()
    await submitAndSettle(rentalForm())

    expect(screen.getByText('Failed to spotRental.saveAction. Network Error')).toBeInTheDocument()
    expect(document.getElementById('check_in_date-error')).toBeNull()
  })

  it('a 422 on the check-in date shows under it and no banner', async () => {
    createMutateAsync.mockRejectedValueOnce(validationError({ check_in_date: 'Input should be a valid date' }))
    openFilled()
    await submitAndSettle(rentalForm())

    expect(document.getElementById('check_in_date-error')).toHaveTextContent('Input should be a valid date')
    expect(banner()).toBeNull()
  })

  // Named controls that aren't payload fields go here. None today: the rate
  // type picker is controlled and carries no name.
  const UI_ONLY: string[] = []
  // In knownFields but nameless: the location box is controlled, and its error
  // shows under that box.
  const CONTROLLED = ['location_name']

  // Guard for knownFields drift and silent fields: a 422 on any field the form
  // registers has to show under that field. Only one rate field is on screen
  // at a time, so it walks the three rate types. Mutant: drop a name from
  // knownFields and it banners.
  it('guard: a 422 on each field shows under it', async () => {
    openFilled()
    const checked = new Set<string>()
    const wrong: string[] = []
    for (const rateType of ['nightly', 'weekly', 'monthly']) {
      fireEvent.change(document.getElementById('rate_type')!, { target: { value: rateType } })
      const names = [...registeredFieldNames(rentalForm(), UI_ONLY), ...CONTROLLED].filter((n) => !checked.has(n))
      for (const name of names) {
        checked.add(name)
        const got = await whereA422Lands(rentalForm(), createMutateAsync, name, `bad ${name}`, banner)
        if (got !== 'field') wrong.push(`${name}: ${got}`)
      }
    }
    expect(wrong).toEqual([])
    // An empty sweep would pass, so pin the names it must contain.
    expect([...checked]).toEqual(
      expect.arrayContaining(['nightly_rate', 'weekly_rate', 'monthly_rate', 'total_cost', 'check_in_date', ...CONTROLLED])
    )
  })
})
