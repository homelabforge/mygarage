/**
 * Task 3c: the fuel form's odometer and outside temperature, per quantity.
 *
 * Task 2 put this form's volume and price on the client's resolved `UnitSet`
 * and left the odometer and the outside temperature on the binary
 * `system === 'imperial'` path. `system` is D8-collapsed from VOLUME, so a
 * client resolving `{volume: 'L', distance: 'mi', temperature: 'f'}` read a
 * form whose volume and price honoured their units while the odometer beside
 * them was treated as kilometres and the temperature as Celsius. Those are
 * wrong numbers rather than merely inconsistent ones: the odometer's own round
 * trip stored a mileage reading verbatim into a kilometre column.
 *
 * Every case DRIVES the component and asserts RENDERED TEXT as well as the
 * posted body. A label naming the unit a value is not in is the same-screen
 * defect this slice exists to remove, and a payload assertion alone cannot see
 * it.
 *
 * Expected values are hand-written and derived in comments, never computed
 * through the code under test.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import { IMPERIAL_UNITS, METRIC_UNITS } from '../../__tests__/factories'
import { binarySystemFor, type UnitSet } from '../../types/units'
import { UNIT_ADAPTERS } from '../../utils/unitAdapters'
import FuelRecordForm from '../FuelRecordForm'
import type { Vehicle } from '../../types/vehicle'

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

// `system` is DERIVED from `units`, exactly as the real hook derives it
// (`binarySystemFor(units.volume)`). A mock that pinned `system` to a literal
// could make every case below pass for the wrong reason: the whole defect is
// that `system` disagrees with `units.distance` and `units.temperature`, and a
// hardcoded `system` cannot express the disagreement. Commit `e3f834f` fixed
// exactly this in two other suites.
let units: UnitSet = METRIC_UNITS
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: binarySystemFor(units.volume),
    showBoth: false,
    units,
    gallonStandard: units.secondary_gallon,
  }),
}))

vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ user: null }) }))
vi.mock('../../hooks/useTimeFormat', () => ({ useTimeFormat: () => ({ timeFormat: '24h' }) }))

// LOCAL i18n mock that RETAINS the interpolated unit. The global setup.ts mock
// is `t: (key) => key`, so a label assertion against it would render the same
// string whether the unit is right, wrong, or missing entirely.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { unit?: string }) =>
      options?.unit ? `${key} (${options.unit})` : key,
    i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}))

const VIN = 'TEST12345678901234'
const DEFAULT_PROPS = { vin: VIN, onClose: vi.fn(), onSuccess: vi.fn() }

const vehicle = {
  vin: VIN,
  nickname: 'Test Car',
  vehicle_type: 'Car',
  year: 2024,
  make: 'Toyota',
  model: 'Camry',
  created_at: '2024-01-15T00:00:00Z',
  archived_visible: true,
  fuel_type: 'gasoline',
} as Vehicle

const field = (id: string): HTMLInputElement => document.getElementById(id) as HTMLInputElement

/** The rendered `<label>` text for a field, unit suffix included. */
const labelText = (id: string): string =>
  document.querySelector(`label[for="${id}"]`)?.textContent ?? ''

const drawerForm = (): HTMLFormElement =>
  screen.getByRole('dialog').querySelector('form') as HTMLFormElement

/** The body of the CREATE call, found by URL rather than by index. */
function postedPayload(): Record<string, unknown> {
  const call = mockedApiPost.mock.calls.find(
    (c) => typeof c[0] === 'string' && c[0].endsWith('/fuel')
  )
  expect(call, 'no create POST was made').toBeDefined()
  return call![1] as Record<string, unknown>
}

/**
 * The body of the UPDATE call.
 *
 * The twin of `postedPayload`, and it exists for the same reason: every edit
 * case used to read `mockedApiPut.mock.calls[0][1]` inline, which throws an
 * unreadable "cannot read properties of undefined" when the submit did not fire
 * at all, where the named check says which call is missing.
 */
function putPayload(): Record<string, unknown> {
  const call = mockedApiPut.mock.calls[0]
  expect(call, 'no update PUT was made').toBeDefined()
  return call[1] as Record<string, unknown>
}

/** The suggestion preview line, as one string. */
const previewText = (): string =>
  document.getElementById('obc_suggestion_preview')?.textContent ?? ''

/**
 * A client whose VOLUME is metric but whose DISTANCE and TEMPERATURE are not.
 *
 * `binarySystemFor('L')` is `'metric'`, so every `system === 'imperial'` branch
 * answers "no" for two quantities this client chose in imperial units.
 */
const LITRES_MILES_FAHRENHEIT: UnitSet = {
  ...METRIC_UNITS,
  distance: 'mi',
  speed: 'mph',
  temperature: 'f',
}

/**
 * The mirror: gallons, but kilometres and Celsius.
 *
 * `binarySystemFor('gal_us')` is `'imperial'`, so the collapsed answer is wrong
 * in the OTHER direction here. Pinning both directions is what makes these
 * assertions statements about the distance and temperature tokens rather than
 * about the binary system under a different name.
 */
const GALLONS_KM_CELSIUS: UnitSet = {
  ...IMPERIAL_UNITS,
  distance: 'km',
  speed: 'kmh',
  temperature: 'c',
}

/**
 * A client whose VOLUME is metric but whose SPEED and CONSUMPTION are not.
 *
 * The two sets above already mix SPEED against the binary system, but each of
 * them leaves CONSUMPTION agreeing with it. The OBC pair needs one set where
 * both of its quantities disagree at once, or a fix that reached only one of
 * them would still pass.
 */
const LITRES_MPH_MPG: UnitSet = {
  ...METRIC_UNITS,
  speed: 'mph',
  consumption: 'mpg_us',
}

/** The mirror: gallons, but km/h and L/100km. */
const GALLONS_KMH_L100: UnitSet = {
  ...IMPERIAL_UNITS,
  speed: 'kmh',
  consumption: 'l_100km',
}

/**
 * The stored record every OBC edit case opens.
 *
 * 10 L/100km and 100 km/h are chosen because BOTH round trips are lossy at the
 * imperial tokens' display precision, which is what makes the origin visible:
 * 62 mph converts back to 99.77908 km/h and 23.5 MPG to 10.009106383 L/100km.
 */
const OBC_RECORD = {
  id: 21,
  vin: VIN,
  date: '2026-02-10',
  obc_l_per_100km: 10,
  obc_avg_speed_kmh: 100,
}

/** The receipt draft the backend hands back, or null to leave the panel off. */
const receipt = { draft: null as Record<string, unknown> | null }

/** The drive session `/fuel/obc-suggestion` matches, canonical on the wire. */
const obcSuggestion = { body: null as Record<string, unknown> | null }

beforeEach(() => {
  vi.clearAllMocks()
  mockedApiGet.mockImplementation((url: string) => {
    if (url.includes('/settings/public')) {
      return Promise.resolve({
        data: {
          settings: [
            { key: 'llm_receipt_parse_enabled', value: receipt.draft ? 'true' : 'false' },
          ],
        },
      })
    }
    if (url.includes('/fuel/obc-suggestion')) return Promise.resolve({ data: obcSuggestion.body })
    return Promise.resolve({ data: vehicle })
  })
  mockedApiPost.mockImplementation((url: string) =>
    url.includes('parse-receipt')
      ? Promise.resolve({ data: { draft: receipt.draft, source: 'llm' } })
      : Promise.resolve({ data: {} })
  )
  mockedApiPut.mockResolvedValue({ data: {} })
  receipt.draft = null
  obcSuggestion.body = null
  units = METRIC_UNITS
  // The outside-temp field lives inside the collapsed "More details" panel.
  localStorage.setItem('fuel_form:more_details_expanded', '1')
})

describe('FuelRecordForm — odometer and temperature follow their own tokens', () => {
  it('★ EDIT: volume, price, odometer and temperature all render in the units the client resolved', async () => {
    // The whole-form proof. One record, four quantities, four different
    // decisions, all read from the resolved set at once.
    //
    //   72420.3 km / 1.60934 = 45000 mi exactly (45000 x 1.60934 = 72420.3)
    //   20 C x 9/5 + 32      = 68.0 F
    //   47.318 L is already litres; $1.234/L is already per litre
    units = LITRES_MILES_FAHRENHEIT

    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={{
          id: 7,
          vin: VIN,
          date: '2026-02-10',
          odometer_km: 72420.3,
          liters: 47.318,
          price_per_unit: 1.234,
          price_basis: 'per_volume',
          cost: 58.39,
          outside_temp_c: 20,
        } as never}
      />
    )
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())

    // Rendered VALUES, per quantity.
    expect(field('odometer_km').value).toBe('45000')
    expect(field('outside_temp_display').value).toBe('68.0')
    // Two decimals, which is what the `L` adapter carries and what every other
    // rendering of a volume in the app shows. The field used to be seeded with
    // the raw stored litres and disagreed with all of them; task 7 put it on
    // the same adapter, and the third decimal survives in STORAGE through the
    // seeded origin rather than on screen.
    expect(field('liters').value).toBe('47.32')
    expect(field('price_per_unit').value).toBe('1.234')

    // Rendered LABELS, per quantity. A right number under a wrong label is the
    // same-screen defect; both halves have to agree.
    expect(labelText('odometer_km')).toBe('common:mileage (mi)')
    expect(labelText('outside_temp_display')).toBe('fuel.outsideTemp (°F)')
    expect(labelText('liters')).toBe('fuel.volume (L)')
    expect(labelText('price_per_unit')).toBe('fuel.pricePer L')

    // And the binary answer really does disagree with two of them, so none of
    // the four above can be passing because the collapse happened to agree.
    expect(binarySystemFor(units.volume)).toBe('metric')
  })

  it('★ EDIT: the two seedUnitField fields survive an untouched save; volume and price are identity here', async () => {
    // A seed in one unit and a submit in another rewrites a record the user
    // only opened. `seedUnitField` records the canonical origin so an untouched
    // field returns the stored value rather than a re-conversion of a rounded
    // display: 45000 mi converts back to 72420.3 km, but 72420.3 is what was
    // stored and 72420.3 is what must be posted.
    //
    // ★ NAMED FOR WHAT IT EXERCISES. This test used to be called "changes none
    // of the four", which overclaimed: this unit set's volume is `L`, so
    // `litersToVolumeUnit` returns the value untouched and the volume and price
    // assertions below are identity by construction rather than evidence. The
    // two that are real are the odometer and the temperature, which is exactly
    // what `seedUnitField` exists for. The CONVERTING volume/price case lives in
    // FuelRecordForm.gallonUnits.test.tsx, where it is a fixed point only after
    // one cycle.
    units = LITRES_MILES_FAHRENHEIT

    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={{
          id: 7,
          vin: VIN,
          date: '2026-02-10',
          odometer_km: 72420.3,
          liters: 47.318,
          price_per_unit: 1.234,
          price_basis: 'per_volume',
          cost: 58.39,
          outside_temp_c: 20,
        } as never}
      />
    )
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    await waitFor(() => expect(field('odometer_km').value).toBe('45000'))
    // Stated rather than assumed: this is WHY the two below cannot fail here.
    expect(units.volume).toBe('L')

    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())

    const payload = putPayload()
    expect(payload.odometer_km).toBe(72420.3)
    expect(payload.outside_temp_c).toBe(20)
    expect(payload.liters).toBe(47.318)
    expect(payload.price_per_unit).toBe(1.234)
  })

  it('★ EDIT: an odometer BETWEEN two whole miles survives a save that never touched it', async () => {
    // The case above round-trips exactly, so it cannot tell an origin from a
    // re-conversion. This one can, and it is what makes `seedUnitField`
    // load-bearing rather than decorative:
    //
    //   72420.5 km / 1.60934 = 45000.1242745 mi, shown as 45000 (mi has no
    //                          decimals)
    //   45000 mi x 1.60934   = 72420.3 km, which is NOT what was stored
    //
    // Re-converting the display would quietly move the reading 0.2 km every
    // time the record was opened and saved.
    units = LITRES_MILES_FAHRENHEIT

    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={{ id: 11, vin: VIN, date: '2026-02-10', odometer_km: 72420.5 } as never}
      />
    )
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    expect(field('odometer_km').value).toBe('45000')

    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    const payload = putPayload()
    expect(payload.odometer_km).toBe(72420.5)
    expect(payload.odometer_km).not.toBe(72420.3)

    // ★ The displayed precision, pinned. This used to be the thing holding
    // the untouched-save mechanism together: `canonicalFromUnitField`
    // compared the field against `toInputValue`'s `toFixed(precision)` and the
    // odometer, a react-hook-form NUMBER, can only offer `String(number)`, so
    // the two spellings agreed only at zero decimals. Phase 3b task 3 met the
    // same gap on propane's two-decimal mass field and made the helper compare
    // the quantity, so this now pins what the user reads rather than what the
    // submit depends on. Folded into this case rather than standing alone,
    // because on its own it holds at t=0 and would assert nothing.
    expect(UNIT_ADAPTERS.mi.precision).toBe(0)
    expect(UNIT_ADAPTERS.km.precision).toBe(0)
  })

  it('★ EDIT: retyping the temperature exactly as shown does not shift the stored Celsius', async () => {
    // The temperature's own lossy round trip, and the only path on which its
    // origin can be observed: an untouched field never reaches `onChange` at
    // all, so the drift shows up when a user types the reading, changes their
    // mind, and types it back.
    //
    //   21.7 C x 9/5 + 32   = 71.06 F, shown as 71.1 (F carries one decimal)
    //   (71.1 - 32) x 5/9   = 21.7222222222 C, which is NOT what was stored
    units = LITRES_MILES_FAHRENHEIT

    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={{ id: 12, vin: VIN, date: '2026-02-10', outside_temp_c: 21.7 } as never}
      />
    )
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    expect(field('outside_temp_display').value).toBe('71.1')

    fireEvent.change(field('outside_temp_display'), { target: { value: '70' } })
    fireEvent.change(field('outside_temp_display'), { target: { value: '71.1' } })
    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())

    const payload = putPayload()
    expect(payload.outside_temp_c).toBe(21.7)
    expect(payload.outside_temp_c).not.toBe(21.7222222222)
  })

  it('CREATE: a typed mileage and a typed Fahrenheit temperature reach the API canonical', async () => {
    //   45000 mi x 1.60934 = 72420.3 km
    //   (68 - 32) x 5/9    = 20 C
    //   47.318 L and $1.234/L pass through: the client's volume IS the canonical
    units = LITRES_MILES_FAHRENHEIT

    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())

    fireEvent.change(field('date'), { target: { value: '2026-02-10' } })
    fireEvent.change(field('odometer_km'), { target: { value: '45000' } })
    fireEvent.change(field('price_basis'), { target: { value: 'per_volume' } })
    fireEvent.change(field('liters'), { target: { value: '47.318' } })
    fireEvent.change(field('price_per_unit'), { target: { value: '1.234' } })
    fireEvent.change(field('outside_temp_display'), { target: { value: '68' } })
    fireEvent.submit(drawerForm())

    await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
    const payload = postedPayload()
    expect(payload.odometer_km).toBe(72420.3)
    expect(payload.outside_temp_c).toBe(20)
    expect(payload.liters).toBe(47.318)
    expect(payload.price_per_unit).toBe(1.234)
  })

  it('the MIRROR client, gallons with kilometres and Celsius, reads and writes the other way', async () => {
    // Same form, `system === 'imperial'`, and both quantities must ignore it.
    // Without this case every assertion above could be satisfied by code that
    // simply inverted the binary branch.
    units = GALLONS_KM_CELSIUS

    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={{
          id: 8,
          vin: VIN,
          date: '2026-02-10',
          odometer_km: 72420,
          outside_temp_c: 20,
        } as never}
      />
    )
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())

    expect(field('odometer_km').value).toBe('72420')
    expect(field('outside_temp_display').value).toBe('20.0')
    expect(labelText('odometer_km')).toBe('common:mileage (km)')
    expect(labelText('outside_temp_display')).toBe('fuel.outsideTemp (°C)')
    expect(binarySystemFor(units.volume)).toBe('imperial')

    // Retyping the SAME displayed temperature is not an edit of the quantity,
    // so it must not re-convert into a different stored number.
    fireEvent.change(field('outside_temp_display'), { target: { value: '20.0' } })
    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())

    const payload = putPayload()
    expect(payload.odometer_km).toBe(72420)
    expect(payload.outside_temp_c).toBe(20)
  })

  it('the odometer placeholder is a mileage hint for a mileage field', async () => {
    // The placeholder was keyed on `system`, i.e. on VOLUME, so a litres-and-
    // miles client was shown a six-figure kilometre hint under a `mi` label.
    units = LITRES_MILES_FAHRENHEIT
    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    expect(field('odometer_km').placeholder).toBe('45000')

    // And the volume placeholder on the same screen still follows VOLUME, which
    // for this client is litres. One form, two independent answers.
    expect(field('liters').placeholder).toBe('47.318')
    expect(field('price_per_unit').placeholder).toBe('0.924')
  })

  it('★ the volume and price EXAMPLES name the reader\'s OWN gallon', async () => {
    // ★ The case the one above cannot make. It distinguishes litres from
    // gallons; this distinguishes the two GALLONS, which is what
    // `units.volume === 'L'` could not do: `gal_uk` took the else arm and read a
    // US-gallon example for a unit 20 percent larger. One physical fill, three
    // vocabularies: 47.318 L at $0.924/L is 12.500 US gallons at $3.498 and
    // 10.409 imperial ones at $4.200.
    units = { ...IMPERIAL_UNITS, volume: 'gal_uk', consumption: 'mpg_uk', secondary_gallon: 'uk' }
    const uk = render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    expect(field('liters').placeholder).toBe('10.409')
    expect(field('price_per_unit').placeholder).toBe('4.200')
    uk.unmount()

    units = IMPERIAL_UNITS
    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(field('liters').placeholder).toBe('12.500'))
    expect(field('price_per_unit').placeholder).toBe('3.498')
  })

  it('★ the RECEIPT path lands the odometer in the client\'s distance unit', async () => {
    // `acceptReceiptDraft` used to seed through its OWN calls rather than the
    // form's shared seed. That is the path the ledger says to look at first:
    // both of Task 2's only surviving mutants sat in exactly this function.
    // Phase 3b task 4 moved it onto the same `acceptUnitField` the OBC
    // suggestion uses; the case below is what that move added.
    //
    // The draft is canonical by contract (`receipt_parse_service.py:127` tells
    // the model to "Prefer metric: liters, odometer_km, price per liter").
    units = LITRES_MILES_FAHRENHEIT
    receipt.draft = { odometer_km: 72420.3, liters: 47.318 }

    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(field('receipt_text')).not.toBeNull())

    fireEvent.change(field('receipt_text'), { target: { value: '45000 mi' } })
    fireEvent.click(screen.getByRole('button', { name: 'fuel.parseReceipt' }))
    const accept = await screen.findByRole('button', { name: 'fuel.receiptDraftAccept' })
    fireEvent.click(accept)

    // 72420.3 km is 45000 mi. Seeding it raw would have put a kilometre reading
    // into a field labelled `mi`, and the submit would then have converted it
    // AGAIN into 116,564 km.
    await waitFor(() => expect(field('odometer_km').value).toBe('45000'))

    fireEvent.change(field('date'), { target: { value: '2026-02-10' } })
    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
    expect(postedPayload().odometer_km).toBe(72420.3)
  })

  it('★ the RECEIPT PREVIEW reads in the client\'s own volume unit, not canonical litres', async () => {
    // R7, and it is the one forced-unit site in this file rather than a
    // conversion branch: the preview rendered `` `${draft.liters} L` ``. The
    // draft is CANONICAL by contract, which is exactly why the accept path
    // converts it through `litersToVolumeUnit` before seeding the field, so a
    // gallons account read "47.318 L", accepted it, and watched the field it
    // landed in say 12.50 gal: one quantity under two units, one click apart.
    // 47.318 / 3.78541 = 12.4998... US gallons, at the gal adapter's 2 decimals.
    units = GALLONS_KM_CELSIUS
    receipt.draft = { odometer_km: 72420.3, liters: 47.318 }

    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(field('receipt_text')).not.toBeNull())

    fireEvent.change(field('receipt_text'), { target: { value: '12.5 gal' } })
    fireEvent.click(screen.getByRole('button', { name: 'fuel.parseReceipt' }))
    await screen.findByRole('button', { name: 'fuel.receiptDraftAccept' })

    expect(screen.getByText(/12\.50 gal/)).toBeInTheDocument()
    expect(screen.queryByText(/47\.318 L/)).not.toBeInTheDocument()
  })

  it('★ the RECEIPT path moves the ORIGIN too, so a draft between two whole miles is not rounded', async () => {
    // The case above cannot see the origin: 72420.3 km displays as 45000 mi and
    // 45000 mi converts back to 72420.3 km, so seeding the value alone gives the
    // right answer by luck of the rounding. This one breaks the tie.
    //
    //   72420.5 km / 1.60934 = 45000.1242745 mi, shown as 45000 (mi has no
    //                          decimals)
    //   45000 mi x 1.60934   = 72420.3 km, which is NOT what the receipt said
    //
    // Setting the field without recording where the value came from is the same
    // defect the OBC suggestion had, and it sat here unguarded until the two
    // paths were made one call.
    units = LITRES_MILES_FAHRENHEIT
    receipt.draft = { odometer_km: 72420.5 }

    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(field('receipt_text')).not.toBeNull())

    fireEvent.change(field('receipt_text'), { target: { value: '45000 mi' } })
    fireEvent.click(screen.getByRole('button', { name: 'fuel.parseReceipt' }))
    fireEvent.click(await screen.findByRole('button', { name: 'fuel.receiptDraftAccept' }))
    await waitFor(() => expect(field('odometer_km').value).toBe('45000'))

    fireEvent.change(field('date'), { target: { value: '2026-02-10' } })
    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
    expect(postedPayload().odometer_km).toBe(72420.5)
    expect(postedPayload().odometer_km).not.toBe(72420.3)
  })

  it('a blank odometer and a cleared temperature post nothing rather than zero', async () => {
    // The null branches of both boundaries. A blank unit-bearing field that
    // posts 0 poisons a derived km delta, which is the shape of Task 1's F2a.
    units = LITRES_MILES_FAHRENHEIT

    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={{
          id: 9,
          vin: VIN,
          date: '2026-02-10',
          odometer_km: 72420.3,
          outside_temp_c: 20,
        } as never}
      />
    )
    await waitFor(() => expect(field('odometer_km').value).toBe('45000'))

    fireEvent.change(field('odometer_km'), { target: { value: '' } })
    fireEvent.change(field('outside_temp_display'), { target: { value: '' } })
    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())

    const payload = putPayload()
    expect(payload.odometer_km).toBeUndefined()
    expect(payload.outside_temp_c).toBeUndefined()
  })
})

describe('FuelRecordForm — the OBC pair follows the speed and consumption tokens', () => {
  /**
   * Task 4: the onboard-computer readings, per quantity.
   *
   * `obc_l_per_100km` and `obc_avg_speed_kmh` were hardcoded to their canonical
   * units at every boundary — seed, label, suggestion preview, suggestion
   * acceptance and submit — so an MPH client typed the 60 their trip computer
   * showed and the app stored 60 km/h, 37.3 mph, a 38% error. The surface
   * survived three phases because it reports to neither leg of the units gate:
   * it holds no numeric literal and calls no formatter.
   *
   * Expected values are hand-written and derived in comments, never computed
   * through the code under test:
   *
   *   100 km/h / 1.60934   = 62.137273665 mph, shown as 62 (mph has no decimals)
   *   62 mph x 1.60934     = 99.77908 km/h, which is NOT what was stored
   *   235.214 / 10         = 23.5214 MPG, shown as 23.5 (MPG carries one)
   *   235.214 / 23.5       = 10.009106383 L/100km, which is NOT what was stored
   *   60 mph x 1.60934     = 96.5604 km/h
   *   235.214 / 30         = 7.84046666667 L/100km
   */

  it('★ EDIT: an MPG/MPH client reads both OBC values, and their labels, in its own units', async () => {
    units = LITRES_MPH_MPG

    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={
          OBC_RECORD as never
        }
      />
    )
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())

    expect(field('obc_l_per_100km').value).toBe('23.5')
    expect(field('obc_avg_speed_kmh').value).toBe('62')

    // A right number under a wrong label is the same-screen defect, and here it
    // was worse than that: the label said km/h and the field MEANT km/h, so the
    // reader had no way to tell their own unit was being ignored.
    expect(labelText('obc_l_per_100km')).toBe('fuel.obcConsumption (MPG)')
    expect(labelText('obc_avg_speed_kmh')).toBe('fuel.obcAvgSpeed (mph)')

    // And the binary answer disagrees with both, so neither can be passing
    // because the D8 collapse happened to agree with the tokens.
    expect(binarySystemFor(units.volume)).toBe('metric')
  })

  it('★ EDIT: an untouched OBC pair posts the stored canonical values byte-identically', async () => {
    // Display precision is lossy in BOTH quantities, so re-converting what the
    // field reads would move a record every time a user opened it to fix the
    // notes: 62 mph is 99.77908 km/h and 23.5 MPG is 10.009106383 L/100km.
    units = LITRES_MPH_MPG

    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={
          OBC_RECORD as never
        }
      />
    )
    await waitFor(() => expect(field('obc_avg_speed_kmh').value).toBe('62'))

    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())

    const payload = putPayload()
    expect(payload.obc_avg_speed_kmh).toBe(100)
    expect(payload.obc_avg_speed_kmh).not.toBe(99.77908)
    expect(payload.obc_l_per_100km).toBe(10)
    expect(payload.obc_l_per_100km).not.toBe(10.009106383)
  })

  it('★ CREATE: the 60 mph an MPH client types is stored as 96.5604 km/h, not as 60', async () => {
    // The headline defect, driven end to end.
    units = LITRES_MPH_MPG

    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())

    fireEvent.change(field('date'), { target: { value: '2026-02-10' } })
    fireEvent.change(field('obc_avg_speed_kmh'), { target: { value: '60' } })
    fireEvent.change(field('obc_l_per_100km'), { target: { value: '30' } })
    fireEvent.submit(drawerForm())

    await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
    const payload = postedPayload()
    expect(payload.obc_avg_speed_kmh).toBe(96.5604)
    expect(payload.obc_avg_speed_kmh).not.toBe(60)
    expect(payload.obc_l_per_100km).toBe(7.84046666667)
    expect(payload.obc_l_per_100km).not.toBe(30)
  })

  it('the MIRROR client, gallons with km/h and L/100km, reads and writes the other way', async () => {
    // Same form, `system === 'imperial'`, and both quantities must ignore it.
    // Without this case every assertion above could be satisfied by code that
    // simply inverted the binary branch.
    //
    // ★ AND IT IS NOT A NO-OP FOR THIS CLIENT, which is the trap a mirror walks
    // into: "the same units the column is in" is not "no boundary". Both stored
    // values are chosen to prove it.
    //
    //   47.4 km/h is READ at the token's precision, which is zero decimals, so
    //   the field shows 47 where the raw canonical showed 47.4. The origin is
    //   what puts 47.4 back on the wire.
    //   8.4 L/100km seeds as '8.40' (two decimals) while a react-hook-form
    //   NUMBER field can only offer back '8.4'. On characters alone that reads
    //   as an edit, which is why the untouched check compares the QUANTITY.
    units = GALLONS_KMH_L100

    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={
          {
            id: 23,
            vin: VIN,
            date: '2026-02-10',
            obc_l_per_100km: 8.4,
            obc_avg_speed_kmh: 47.4,
          } as never
        }
      />
    )
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())

    expect(field('obc_l_per_100km').value).toBe('8.4')
    expect(field('obc_avg_speed_kmh').value).toBe('47')
    expect(labelText('obc_l_per_100km')).toBe('fuel.obcConsumption (L/100km)')
    expect(labelText('obc_avg_speed_kmh')).toBe('fuel.obcAvgSpeed (km/h)')
    expect(binarySystemFor(units.volume)).toBe('imperial')

    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    const payload = putPayload()
    expect(payload.obc_l_per_100km).toBe(8.4)
    expect(payload.obc_avg_speed_kmh).toBe(47.4)
    expect(payload.obc_avg_speed_kmh).not.toBe(47)
  })

  it('★ the SUGGESTION previews in the client\'s units and accepting it stores the canonical value exactly', async () => {
    // The suggestion is canonical on the wire (`routes/fuel.py` reads the drive
    // session's own L/100km and km/h). Previewing it raw put a metric number
    // under an "L/100km:" caption over two fields the user reads in MPG and
    // mph, and accepting it wrote that metric number straight into them.
    //
    // Accepting is a SEED, not an edit, so it must also move the origin: with
    // the load-time origin left in place the next submit reads 23.5 as a change
    // and converts it back to 10.009106383.
    units = LITRES_MPH_MPG
    obcSuggestion.body = {
      session_id: 4,
      ended_at: '2026-02-10T09:30:00',
      distance_km: 120,
      obc_l_per_100km: 10,
      obc_avg_speed_kmh: 100,
      obc_trip_duration_s: 3600,
    }

    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())

    // The auto-fill button is gated on a fill-up timestamp.
    fireEvent.change(field('date'), { target: { value: '2026-02-10' } })
    fireEvent.change(field('filled_at_time'), { target: { value: '09:45' } })
    fireEvent.click(screen.getByRole('button', { name: 'fuel.obcAutoFill' }))

    // RENDERED TEXT, in the reader's own units. The em-dash absent markers went
    // with it: `format` carries its own.
    await waitFor(() =>
      expect(previewText()).toBe(
        '23.5 MPG · 62 mph · s: 3600'
      )
    )

    fireEvent.click(screen.getByRole('button', { name: 'fuel.obcSuggestionAccept' }))
    await waitFor(() => expect(field('obc_l_per_100km').value).toBe('23.5'))
    expect(field('obc_avg_speed_kmh').value).toBe('62')

    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
    const payload = postedPayload()
    expect(payload.obc_l_per_100km).toBe(10)
    expect(payload.obc_l_per_100km).not.toBe(10.009106383)
    expect(payload.obc_avg_speed_kmh).toBe(100)
    expect(payload.obc_avg_speed_kmh).not.toBe(99.77908)
  })

  it('an absent suggestion value previews as N/A rather than as an em-dash', async () => {
    // `QuantityFormat.format` returns 'N/A' for an absent value, which is what
    // UnitFormatter has always rendered, so routing the preview through the
    // tokens retired two `?? '—'` markers as a side effect of doing the
    // conversion; the third, on the duration, was changed by hand because
    // seconds are not a quantity and have no formatter.
    //
    // ★ NOT a claim that these were the last em-dashes in the tree. They were
    // handed to me as such and they were not: `git grep "'—'"` finds 19
    // rendered literals across 8 files at 76c09bf, including one 157 lines
    // above them in this same component's `common:select` placeholder, and
    // three beside `u.tread.format(...)` / `u.pressure.format(...)` calls in
    // TireList. The 16 that remain are a vocabulary decision (six files say
    // '—', the formatter says 'N/A', DEFRecordList says both on one line),
    // not a units one, and they want doing in one pass.
    units = LITRES_MPH_MPG
    obcSuggestion.body = {
      session_id: 5,
      ended_at: '2026-02-10T09:30:00',
      distance_km: null,
      obc_l_per_100km: null,
      obc_avg_speed_kmh: null,
      obc_trip_duration_s: null,
    }

    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    fireEvent.change(field('date'), { target: { value: '2026-02-10' } })
    fireEvent.change(field('filled_at_time'), { target: { value: '09:45' } })
    fireEvent.click(screen.getByRole('button', { name: 'fuel.obcAutoFill' }))

    await waitFor(() =>
      expect(previewText()).toBe(
        'N/A · N/A · s: N/A'
      )
    )
    expect(previewText()).not.toContain('—')
  })

  it('clearing both OBC fields OMITS the keys, which on an UPDATE leaves the stored values in place', async () => {
    // ★ WHAT THIS PINS, AND WHAT IT DOES NOT BLESS. It was first written as
    // "posts nothing rather than a converted zero", which read as approval.
    // Read the assertions instead: they say the two keys are ABSENT from the
    // payload, and absence is not neutral on this route.
    // `fuel_service.update_fuel_record` does `model_dump(exclude_unset=True)`
    // (app/services/fuel_service.py:799), so an omitted key means KEEP THE OLD
    // VALUE. A user who clears an OBC reading and saves gets a success and
    // finds the reading still there on reopening. The clear cannot clear.
    //
    // The half that is genuinely right, and the reason the case exists: a
    // blank unit-bearing field must not post a CONVERTED ZERO. `Number('')` is
    // 0, so without `canonicalFromUnitField`'s blank arm an empty speed field
    // would post 0 km/h as a real reading. It posts nothing instead.
    //
    // The other half is a defect, pre-existing and NOT this task's: the same
    // `?? undefined` shape covers `odometer_km` and `outside_temp_c`, and an
    // earlier task's test ("a blank odometer and a cleared temperature post
    // nothing rather than zero") reads the same way. The fix is 30 lines above
    // in this same payload, on `station_address_book_id`: send `null`, not
    // `undefined`. Sweeping it across every nullable field in every form's
    // update payload is update semantics, not units, and is routed as its own
    // work. Until then this test's name is the disclosure.
    //
    // An MPG client typing `0` is a FACET of the same defect, not a separate
    // one: `mpg` is reciprocal, `toCanonical(0)` is null, the key is omitted,
    // and the previous consumption survives the save. The field keeps showing
    // the typed 0, so nothing on screen says the save did not take.
    units = LITRES_MPH_MPG

    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={
          OBC_RECORD as never
        }
      />
    )
    await waitFor(() => expect(field('obc_avg_speed_kmh').value).toBe('62'))

    fireEvent.change(field('obc_l_per_100km'), { target: { value: '' } })
    fireEvent.change(field('obc_avg_speed_kmh'), { target: { value: '' } })
    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())

    const payload = putPayload()
    expect(payload.obc_l_per_100km).toBeUndefined()
    expect(payload.obc_avg_speed_kmh).toBeUndefined()
  })
})

describe('FuelRecordForm — the fuel-economy tip names the reader\'s own unit', () => {
  /**
   * Task 6b: `fuel.mpgTip` read "MPG is only calculated for full tank fill-ups"
   * to everybody, in a form whose economy figures a litre account reads in
   * L/100km. The local `t` mock above appends the interpolated `{{unit}}` in
   * parentheses, so the assertions below can tell a right unit from a wrong one
   * and from a dropped interpolation, which the global `t: (key) => key` mock
   * cannot.
   */

  it('★ says L/100km to a litre-and-L/100km account', async () => {
    units = METRIC_UNITS

    render(<FuelRecordForm {...DEFAULT_PROPS} />)

    expect(await screen.findByText('fuel.mpgTip (L/100km)')).toBeInTheDocument()
    expect(screen.queryByText('fuel.mpgTip (MPG)')).not.toBeInTheDocument()
    // A dropped interpolation renders the bare key, which is neither.
    expect(screen.queryByText('fuel.mpgTip')).not.toBeInTheDocument()
  })

  it('says MPG to an MPG account, so the fix is not a blanket rename', async () => {
    units = IMPERIAL_UNITS

    render(<FuelRecordForm {...DEFAULT_PROPS} />)

    expect(await screen.findByText('fuel.mpgTip (MPG)')).toBeInTheDocument()
  })

  it('★ follows CONSUMPTION, not the volume the binary system is collapsed from', async () => {
    // Litres for volume, MPG for economy: `binarySystemFor('L')` is 'metric',
    // so nothing derived from the volume token can reach this answer.
    units = LITRES_MPH_MPG

    render(<FuelRecordForm {...DEFAULT_PROPS} />)

    expect(await screen.findByText('fuel.mpgTip (MPG)')).toBeInTheDocument()
  })
})
