/**
 * Defect L1 at the fuel form's write boundary.
 *
 * The form's volume and its price are ONE decision. `cost` is computed in
 * display units (`volume x price`), so the two conversions have to use the same
 * gallon or the stored row no longer reconciles to the receipt the user was
 * looking at. Before this change they did not: `toCanonicalLiters` went through
 * `UnitConverter`'s instance-wide factor while `priceToCanonical` used a
 * hardcoded US gallon.
 *
 * Every test here pins the INSTANCE gallon standard to a flavour DIFFERENT from
 * the user's resolved one. That is the whole point: phase 1 gave accounts a
 * per-user `resolved_units`, and swapping in "the dynamic converter" would have
 * left a `gal_uk` user on a US-default instance exactly as broken as before.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import { IMPERIAL_UNITS, UK_IMPERIAL_UNITS } from '../../__tests__/factories'
import { UnitConverter, UnitFormatter } from '../../utils/units'
import FuelRecordForm from '../FuelRecordForm'
import type { Vehicle } from '../../types/vehicle'

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

const unitPrefMock = vi.hoisted(() => ({
  system: 'imperial' as 'metric' | 'imperial',
  showBoth: false,
  units: null as null | import('@/types/units').UnitSet,
}))
vi.mock('../../hooks/useUnitPreference', async () => {
  const { IMPERIAL_UNITS: IMP, METRIC_UNITS } = await import('@/__tests__/factories')
  return {
    useUnitPreference: () => ({
      system: unitPrefMock.system,
      showBoth: unitPrefMock.showBoth,
      units: unitPrefMock.units ?? (unitPrefMock.system === 'imperial' ? IMP : METRIC_UNITS),
    }),
  }
})

vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ user: null }) }))
vi.mock('../../hooks/useTimeFormat', () => ({ useTimeFormat: () => ({ timeFormat: '24h' }) }))

// LOCAL i18n mock that RETAINS the interpolated unit. The global setup.ts mock
// is `t: (key) => key`, which discards it, so a label test against it renders
// the same string whether the unit is right, wrong, or missing entirely.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { unit?: string }) => (options?.unit ? `${key} (${options.unit})` : key),
    i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}))

const VIN = 'TEST12345678901234'
const DEFAULT_PROPS = { vin: VIN, onClose: vi.fn(), onSuccess: vi.fn() }

const vehicle = { vin: VIN, nickname: 'Test Car', vehicle_type: 'Car', year: 2024, make: 'Toyota', model: 'Camry', created_at: '2024-01-15T00:00:00Z', archived_visible: true, fuel_type: 'gasoline' } as Vehicle
/** The same vehicle on propane, which is what makes the `propane_liters` field render. */
const propaneVehicle = { ...vehicle, fuel_type: 'propane_lpg' } as Vehicle

const field = (id: string): HTMLInputElement => document.getElementById(id) as HTMLInputElement

/**
 * The body of the CREATE call, found by URL.
 *
 * Not `calls[0]`: the receipt flow posts to `parse-receipt` first, and indexing
 * blindly would assert against the wrong request.
 */
function postedPayload(): Record<string, unknown> {
  const call = mockedApiPost.mock.calls.find(
    (c) => typeof c[0] === 'string' && c[0].endsWith('/fuel')
  )
  expect(call, 'no create POST was made').toBeDefined()
  return call![1] as Record<string, unknown>
}

/** Enter a full-tank fill of `volume` at `price`, in the client's own units. */
function enterFill(volume: string, price: string): void {
  fireEvent.change(field('date'), { target: { value: '2026-02-10' } })
  fireEvent.change(field('price_basis'), { target: { value: 'per_volume' } })
  fireEvent.change(field('liters'), { target: { value: volume } })
  fireEvent.change(field('price_per_unit'), { target: { value: price } })
}

/** The receipt draft the backend hands back, or null to disable the panel. */
const receipt = { draft: null as Record<string, unknown> | null }

beforeEach(() => {
  vi.clearAllMocks()
  // Discriminated by URL: the form fetches the vehicle AND /settings/public
  // (which is what gates the receipt panel), and posts to two endpoints.
  mockedApiGet.mockImplementation((url: string) =>
    url.includes('/settings/public')
      ? Promise.resolve({
          data: {
            settings: [
              { key: 'llm_receipt_parse_enabled', value: receipt.draft ? 'true' : 'false' },
            ],
          },
        })
      : Promise.resolve({ data: vehicle })
  )
  mockedApiPost.mockImplementation((url: string) =>
    url.includes('parse-receipt')
      ? Promise.resolve({ data: { draft: receipt.draft, source: 'llm' } })
      : Promise.resolve({ data: {} })
  )
  receipt.draft = null
  mockedApiPut.mockResolvedValue({ data: {} })
  unitPrefMock.system = 'imperial'
  unitPrefMock.units = null
  localStorage.removeItem('fuel_form:more_details_expanded')
})

describe('FuelRecordForm — the gallon comes from the user, not the instance', () => {
  it('CREATE: a gal_uk user on a US-default instance stores BOTH halves on the imperial gallon', async () => {
    UnitConverter.setGallonStandard('us')
    unitPrefMock.units = UK_IMPERIAL_UNITS

    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    enterFill('10', '6')
    fireEvent.submit(drawerForm())

    await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
    const payload = postedPayload()
    // 10 x 4.54609 = 45.4609 -> 45.461 at the schema's three decimal places.
    expect(payload.liters).toBe(45.461)
    // 6 / 4.54609 = 1.31981548979. The shipped bug stored 6 / 3.78541 = 1.585,
    // 20.1 percent high, against a volume converted on the OTHER gallon.
    expect(payload.price_per_unit).toBe(1.31981548979)
    // The instance really is on US gallons; nothing above consulted it.
    expect(UnitConverter.getGallonStandard()).toBe('us')
  })

  it('CREATE: a gal_us user on a UK-default instance stores BOTH halves on the US gallon', async () => {
    UnitConverter.setGallonStandard('uk')
    unitPrefMock.units = IMPERIAL_UNITS

    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    enterFill('10', '6')
    fireEvent.submit(drawerForm())

    await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
    const payload = postedPayload()
    expect(payload.liters).toBe(37.854)
    expect(payload.price_per_unit).toBe(1.58503306115)
    expect(UnitConverter.getGallonStandard()).toBe('uk')
  })

  it('★ the payload RECONCILES: price x volume equals the gross cost the user saw', async () => {
    // This is what "atomically" buys, and what a half-migration destroys. The
    // form computes cost in DISPLAY units, so price x volume comes back to the
    // gross total only when both conversions used the same gallon. Convert one
    // half and not the other and this ratio lands on 4.54609 / 3.78541.
    UnitConverter.setGallonStandard('us')
    unitPrefMock.units = UK_IMPERIAL_UNITS

    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    enterFill('10', '6')
    await waitFor(() => expect(field('cost').value).toBe('60'))
    fireEvent.submit(drawerForm())

    await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
    const payload = postedPayload()
    expect(payload.cost).toBe(60)
    const ratio = (payload.price_per_unit as number) * (payload.liters as number) / (payload.cost as number)
    expect(ratio).toBeCloseTo(1, 4)
    // And explicitly NOT the mismatch signature, so a test that merely tolerates
    // a wide band cannot pass with the bug present.
    expect(Math.abs(ratio - 1.20095)).toBeGreaterThan(0.1)
  })

  /*
   * ★ THE OBLIGATION THESE TWO RECORDED IS NOW DISCHARGED, and the pair is kept
   * rather than collapsed because it is what says so.
   *
   * They replaced a single test called "saving it untouched changes neither
   * half", whose fixture was `liters: 45.461` and `price_per_unit:
   * 1.31981548979`. Those are `10 * 4.54609` and `6 / 4.54609`: hand-picked
   * values that are already exact round-trip fixed points, so the name claimed
   * a guarantee the body could not exercise. Re-fixtured to an ordinary stored
   * value, the old assertion failed with `expected 22.73 to be 22.712`, and the
   * case was renamed to assert the shift it had found:
   *
   *   volume  22.712 / 4.54609 = 4.9959... -> two display dp   -> 5.00
   *           5 * 4.54609      = 22.73045  -> 3 wire decimals  -> 22.73
   *   price   1.32 * 4.54609   = 6.00084   -> 3 display dp     -> 6.001
   *           6.001 / 4.54609  = 1.32003545904 at 12 significant digits
   *
   * Plan 3b task 7 put both fields on the origin-preserving protocol, so the
   * right-hand column is now what the form does NOT post. The first case
   * asserts that, and asserts the two shifted answers by name so it cannot pass
   * on a build where the conversion arithmetic quietly changed instead. The
   * second keeps a fixture that was ALREADY a fixed point, so the pair still
   * separates "the origin works" from "the arithmetic happens to agree".
   */
  it('★ EDIT: an ordinary gal_uk record no longer shifts onto the entry grid', async () => {
    UnitConverter.setGallonStandard('us')
    unitPrefMock.units = UK_IMPERIAL_UNITS
    // ★ Named so the assertions below can say "this MOVED". Without that, the
    // two tests in this pair are distinguished only by their fixtures, and
    // swapping the fixtures leaves both green while they describe the same
    // case: a survivor found by mutating the test rather than the code.
    const STORED_LITERS = 22.712
    const STORED_PRICE = 1.32

    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={{
          id: 9,
          vin: VIN,
          date: '2026-02-10',
          liters: STORED_LITERS,
          price_per_unit: STORED_PRICE,
          price_basis: 'per_volume',
          cost: 30.01,
        } as never}
      />
    )
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    // ★ The DISPLAY is still quantised onto the grid the input accepts, and
    // that is what makes the payload assertions below mean something: the
    // form is not posting the stored values because it never rounded them.
    expect(field('liters').value).toBe('5')
    expect(field('price_per_unit').value).toBe('6.001')

    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    const payload = mockedApiPut.mock.calls[0][1] as Record<string, unknown>
    // The fixture is deliberately NOT on the entry grid, and both values stay
    // put anyway: the origin hands back what the field was seeded from.
    expect(payload.liters).toBe(STORED_LITERS)
    expect(payload.price_per_unit).toBe(STORED_PRICE)
    // And explicitly not the two answers the shipped path gave, named so this
    // case cannot pass on a build where the arithmetic moved instead.
    expect(payload.liters).not.toBe(22.73)
    expect(payload.price_per_unit).not.toBe(1.32003545904)
    // Cost is PRESERVED verbatim on an untouched submit, not recomputed: the form
    // deliberately keeps a stored total because a receipt may include unrelated items.
    // Pinned so nobody "fixes" it into a recomputation.
    expect(payload.cost).toBe(30.01)
  })

  it('EDIT: a gal_uk record already on the entry grid is a fixed point too', async () => {
    // The negative control. This fixture is what the OLD save produced, so the
    // naive reconversion gets it right on its own: it is the case the origin
    // cannot be credited for, kept so the case above is not the only evidence.
    UnitConverter.setGallonStandard('us')
    unitPrefMock.units = UK_IMPERIAL_UNITS

    // ★ The other half of the pin: this fixture IS on the entry grid. Swapping
    // the two fixtures no longer flips either case, because both are now
    // preserved; what still separates them is the `not.toBe` pair above, which
    // names the answers only the OFF-grid fixture could have produced.
    const STORED_LITERS = 22.73
    const STORED_PRICE = 1.32003545904

    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={{
          id: 9,
          vin: VIN,
          date: '2026-02-10',
          liters: STORED_LITERS,
          price_per_unit: STORED_PRICE,
          price_basis: 'per_volume',
          cost: 30.01,
        } as never}
      />
    )
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    expect(field('liters').value).toBe('5')
    expect(field('price_per_unit').value).toBe('6.001')

    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    const payload = mockedApiPut.mock.calls[0][1] as Record<string, unknown>
    expect(payload.liters).toBe(STORED_LITERS)
    expect(payload.price_per_unit).toBe(STORED_PRICE)
    expect(payload.cost).toBe(30.01)
  })

  it('the price-basis labels name the units the conversion actually uses', async () => {
    // The `per_weight` denominator now reads `units.mass`, and `system` is
    // D8-collapsed from VOLUME, so a label keyed on it would say "kg" for a
    // user whose price converts to $/lb.
    UnitConverter.setGallonStandard('us')
    unitPrefMock.units = { ...UK_IMPERIAL_UNITS, mass: 'lb' }

    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    const options = Array.from(field('price_basis').querySelectorAll('option')).map((o) => o.textContent)
    expect(options).toContain('fuel.priceBasisPerVolume (gal)')
    expect(options).toContain('fuel.priceBasisPerWeight (lb)')
    // The same set with kilograms flips only the mass label, proving the two
    // denominators are read independently rather than from one collapsed answer.
    expect(UnitFormatter.getMassUnit({ ...UK_IMPERIAL_UNITS, mass: 'kg' })).toBe('kg')
    expect(UnitFormatter.getVolumeUnit({ ...UK_IMPERIAL_UNITS, mass: 'kg' })).toBe('gal')
  })

  it('the price field\'s own denominator follows the basis, not the volume unit', async () => {
    // A litre user who prices by weight in pounds: `priceToDisplay` scales by
    // `units.mass`, so a label that keeps naming the volume unit claims $/L
    // over a $/lb number. That was pre-existing for `system`, and reading the
    // mass token independently is what made it reachable.
    UnitConverter.setGallonStandard('us')
    unitPrefMock.system = 'metric'
    unitPrefMock.units = { ...UK_IMPERIAL_UNITS, volume: 'L', consumption: 'l_100km', mass: 'lb' }

    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    const label = () => document.querySelector('label[for="price_per_unit"]')?.textContent

    fireEvent.change(field('price_basis'), { target: { value: 'per_volume' } })
    await waitFor(() => expect(label()).toBe('fuel.pricePer L'))
    fireEvent.change(field('price_basis'), { target: { value: 'per_weight' } })
    await waitFor(() => expect(label()).toBe('fuel.pricePer lb'))
  })

  it('★ the RECEIPT path lands both halves in the client\'s gallon, and its payload reconciles', async () => {
    // ★ MEDIUM 2. `acceptReceiptDraft` seeds volume and price through its OWN
    // calls rather than the form's shared seed, which is the tell the ledger
    // names: the two mutations that revert one half of THIS path were the only
    // survivors of the reviewer's twenty. The code was right and the guard was
    // missing, so this drives the flow instead of unit-testing the helpers.
    //
    // The draft is canonical by contract: `receipt_parse_service.py:127` tells
    // the model to "Prefer metric: liters, odometer_km, price per liter".
    UnitConverter.setGallonStandard('us')
    unitPrefMock.units = UK_IMPERIAL_UNITS
    receipt.draft = { liters: 45.4609, price_per_unit: 1.31981548979, cost: 60 }

    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(field('receipt_text')).not.toBeNull())

    fireEvent.change(field('receipt_text'), { target: { value: '10.00 gal at 6.00' } })
    fireEvent.click(screen.getByRole('button', { name: 'fuel.parseReceipt' }))
    const accept = await screen.findByRole('button', { name: 'fuel.receiptDraftAccept' })
    fireEvent.click(accept)

    // 45.4609 L is 10.00 imperial gallons and 12.01 US ones; $1.31981548979/L
    // is $6.000 per imperial gallon and $4.996 per US one.
    await waitFor(() => expect(field('liters').value).toBe('10'))
    expect(field('price_per_unit').value).toBe('6')

    fireEvent.change(field('date'), { target: { value: '2026-02-10' } })
    fireEvent.change(field('price_basis'), { target: { value: 'per_volume' } })
    fireEvent.submit(drawerForm())

    await waitFor(() => expect(postedPayload().liters).toBeDefined())
    const payload = postedPayload()
    expect(payload.liters).toBe(45.461)
    expect(payload.price_per_unit).toBe(1.31981548979)
    const ratio =
      ((payload.price_per_unit as number) * (payload.liters as number)) / (payload.cost as number)
    expect(ratio).toBeCloseTo(1, 4)
    expect(UnitConverter.getGallonStandard()).toBe('us')
  })

  it('★ an accepted receipt draft carries its ORIGIN, so an untouched save keeps it', async () => {
    // ★ The case above cannot see this: its draft is `45.4609` L, ten imperial
    // gallons exactly, so the display reconverts to itself and an accepted
    // draft with NO origin would post the same number. This draft is off the
    // grid, so only a fresh origin gets it back out intact. `acceptUnitField`
    // and `acceptPriceField` are the two calls under test; setting a value
    // without moving its origin is the defect they exist to prevent.
    UnitConverter.setGallonStandard('us')
    unitPrefMock.units = UK_IMPERIAL_UNITS
    receipt.draft = { liters: 22.712, price_per_unit: 1.32, cost: 30.01 }

    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(field('receipt_text')).not.toBeNull())
    fireEvent.change(field('receipt_text'), { target: { value: '5.00 gal at 6.00' } })
    fireEvent.click(screen.getByRole('button', { name: 'fuel.parseReceipt' }))
    fireEvent.click(await screen.findByRole('button', { name: 'fuel.receiptDraftAccept' }))

    // 22.712 / 4.54609 = 4.9959... at two decimals is 5.00; 1.32 x 4.54609 =
    // 6.00084 at three is 6.001. Both are quantised, which is the point.
    await waitFor(() => expect(field('liters').value).toBe('5'))
    expect(field('price_per_unit').value).toBe('6.001')

    fireEvent.change(field('date'), { target: { value: '2026-02-10' } })
    fireEvent.change(field('price_basis'), { target: { value: 'per_volume' } })
    fireEvent.submit(drawerForm())

    await waitFor(() => expect(postedPayload().liters).toBeDefined())
    const payload = postedPayload()
    expect(payload.liters).toBe(22.712)
    expect(payload.price_per_unit).toBe(1.32)
    // The answers an origin-less accept would have posted.
    expect(payload.liters).not.toBe(22.73)
    expect(payload.price_per_unit).not.toBe(1.32003545904)
  })

  it('★ the PROPANE volume field on this form has an origin too', async () => {
    // ★ FOUND BY MUTATION, not by reading. Reverting `propane_liters` to a
    // straight reconversion killed NOTHING: `PropaneRecordForm` has its own
    // field of the same name and its own cases, and this form's second volume
    // field had no test at all. A fuel record on a propane vehicle renders it,
    // and its round trip is the same one `liters` has.
    UnitConverter.setGallonStandard('us')
    unitPrefMock.units = UK_IMPERIAL_UNITS
    mockedApiGet.mockImplementation((url: string) =>
      url.includes('/settings/public')
        ? Promise.resolve({ data: { settings: [] } })
        : Promise.resolve({ data: propaneVehicle })
    )

    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={{
          id: 22,
          vin: VIN,
          date: '2026-02-10',
          propane_liters: 22.712,
          price_per_unit: 1.32,
          price_basis: 'per_volume',
          cost: 30.01,
        } as never}
      />
    )
    await waitFor(() => expect(field('propane_liters')).not.toBeNull())
    // 22.712 / 4.54609 = 4.9959... at two decimals is 5.00.
    expect(field('propane_liters').value).toBe('5')

    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    const payload = mockedApiPut.mock.calls[0][1] as Record<string, unknown>
    expect(payload.propane_liters).toBe(22.712)
    expect(payload.propane_liters).not.toBe(22.73)
  })

  it('★ moving the price BASIS is an edit, even with the number untouched', async () => {
    // ★ The leg a quantity origin has no place for, driven through the control
    // that moves it. `price_basis` is a <select> on this form: switching
    // per_volume -> per_weight leaves 6.001 in the box and makes it $/lb.
    // Handing back the stored $/L would relabel a gallon price as a pound one.
    UnitConverter.setGallonStandard('us')
    unitPrefMock.units = UK_IMPERIAL_UNITS

    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={{
          id: 21,
          vin: VIN,
          date: '2026-02-10',
          liters: 22.712,
          price_per_unit: 1.32,
          price_basis: 'per_volume',
          cost: 30.01,
        } as never}
      />
    )
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    expect(field('price_per_unit').value).toBe('6.001')

    fireEvent.change(field('price_basis'), { target: { value: 'per_weight' } })
    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    const payload = mockedApiPut.mock.calls[0][1] as Record<string, unknown>
    // 6.001 / 0.453592 = 13.2299511455 $/kg at 12 significant digits.
    expect(payload.price_basis).toBe('per_weight')
    expect(payload.price_per_unit).toBe(13.2299511455)
    expect(payload.price_per_unit).not.toBe(1.32)
    // The volume beside it did NOT move: only the field whose denominator
    // changed is treated as edited.
    expect(payload.liters).toBe(22.712)
  })
})
