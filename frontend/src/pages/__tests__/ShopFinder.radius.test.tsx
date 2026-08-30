/**
 * ShopFinder's search radius.
 *
 * The radius list, its default, the label on each option and the metres sent to
 * `/shop-discovery/search` all used to branch on the binary `system`, which spec
 * D8 collapses from VOLUME. A custom client with litres and miles therefore got
 * kilometre radii offered against a mile preference, and searched kilometres.
 * All four now follow the resolved DISTANCE token.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { render, screen, waitFor } from '../../__tests__/test-utils'
import { binarySystemFor, presetUnitsFor, type UnitSet } from '../../types/units'

// The result distance reaches the DOM through `t('shopFinder.distanceAway',
// { distance })`, and the global key-echo mock swallows interpolations, so the
// formatted string would be invisible to any assertion. This `t` appends the
// interpolated values instead of dropping them; keys without options still
// echo, so every other assertion in this file is unchanged.
vi.mock('react-i18next', () => {
  const t = (key: string, opts?: Record<string, unknown>) =>
    opts ? `${key}|${Object.values(opts).join('|')}` : key
  return {
    useTranslation: () => ({
      t,
      i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
    }),
    Trans: ({ children }: { children: ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

const apiGet = vi.fn()
const apiPost = vi.fn()
vi.mock('@/services/api', () => ({
  default: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
  },
}))
// `system` is DERIVED from `units`, exactly as the real hook derives it
// (`binarySystemFor(units.volume)`). Pinning it to a literal would make the
// custom-set cases below pass for the wrong reason: the whole defect is that
// `system` disagrees with `units.distance`, and a mock that hardcodes `system`
// cannot express the disagreement.
let units: UnitSet = presetUnitsFor('imperial', 'us')
vi.mock('@/hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: binarySystemFor(units.volume),
    showBoth: false,
    units,
    gallonStandard: units.secondary_gallon,
  }),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import ShopFinder from '../ShopFinder'

/** Drives the geolocation prompt straight to a fixed position. */
function grantLocation(): void {
  Object.defineProperty(navigator, 'geolocation', {
    configurable: true,
    value: {
      getCurrentPosition: (ok: PositionCallback) =>
        ok({ coords: { latitude: 10, longitude: 20 } } as GeolocationPosition),
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  units = presetUnitsFor('imperial', 'us')
  apiGet.mockResolvedValue({ data: { recommendations: [] } })
  apiPost.mockResolvedValue({ data: { results: [], source: 'osm' } })
  grantLocation()
})

describe('ShopFinder radius options', () => {
  it('offers mile radii labelled in miles for a mile client', async () => {
    render(<ShopFinder />)
    const select = (await screen.findByLabelText('shopFinder.searchRadius')) as HTMLSelectElement
    expect([...select.options].map((o) => o.textContent)).toStrictEqual([
      '5 mi',
      '10 mi',
      '25 mi',
      '50 mi',
      '100 mi',
    ])
    expect(select.value).toBe('5')
  })

  it('offers kilometre radii labelled in kilometres for a kilometre client', async () => {
    units = presetUnitsFor('metric', 'us')
    render(<ShopFinder />)
    const select = (await screen.findByLabelText('shopFinder.searchRadius')) as HTMLSelectElement
    expect([...select.options].map((o) => o.textContent)).toStrictEqual([
      '10 km',
      '25 km',
      '50 km',
      '100 km',
      '150 km',
    ])
    expect(select.value).toBe('25')
  })

  it('follows the DISTANCE token for a custom set whose volume reads metric', async () => {
    units = { ...presetUnitsFor('metric', 'us'), distance: 'mi' }
    render(<ShopFinder />)
    const select = (await screen.findByLabelText('shopFinder.searchRadius')) as HTMLSelectElement
    expect([...select.options].map((o) => o.textContent)).toStrictEqual([
      '5 mi',
      '10 mi',
      '25 mi',
      '50 mi',
      '100 mi',
    ])
  })
})

describe('ShopFinder search radius in metres', () => {
  it('sends the default mile radius as metres (5 x 1.60934 km = 8046.7 m)', async () => {
    render(<ShopFinder />)
    ;(await screen.findByText('shopFinder.enableLocationBtn')).click()
    await waitFor(() => expect(apiPost).toHaveBeenCalled())
    expect(apiPost.mock.calls[0][1]).toStrictEqual({
      latitude: 10,
      longitude: 20,
      radius_meters: 8047,
      shop_type: 'auto',
    })
  })

  it('sends a kilometre radius as its own metres', async () => {
    units = presetUnitsFor('metric', 'us')
    render(<ShopFinder />)
    ;(await screen.findByText('shopFinder.enableLocationBtn')).click()
    await waitFor(() => expect(apiPost).toHaveBeenCalled())
    expect(apiPost.mock.calls[0][1]).toStrictEqual({
      latitude: 10,
      longitude: 20,
      radius_meters: 25000,
      shop_type: 'auto',
    })
  })

  it('searches MILES for a custom set the binary system calls metric', async () => {
    // The whole point: this client used to be offered 25 km and to search
    // 25,000 m while having chosen miles. 5 mi is the mile default.
    units = { ...presetUnitsFor('metric', 'us'), distance: 'mi' }
    render(<ShopFinder />)
    ;(await screen.findByText('shopFinder.enableLocationBtn')).click()
    await waitFor(() => expect(apiPost).toHaveBeenCalled())
    expect(apiPost.mock.calls[0][1]).toStrictEqual({
      latitude: 10,
      longitude: 20,
      radius_meters: 8047,
      shop_type: 'auto',
    })
  })
})

describe('ShopFinder result distances', () => {
  /**
   * Equator coordinates, where the haversine is exactly `R x d(lon)`: with
   * dLat = 0 and cos(lat) = 1, `2 * asin(sin(dLon/2))` is dLon itself. So
   * 0.1 deg is 6371000 x 0.1 x PI/180 = 11119.4926... m, a figure that can be
   * written down rather than read off a run.
   */
  const AT_ZERO_ONE_DEGREE = { business_name: 'Shop', latitude: 0, longitude: 0.1 }

  function grantLocationAtOrigin(): void {
    Object.defineProperty(navigator, 'geolocation', {
      configurable: true,
      value: {
        getCurrentPosition: (ok: PositionCallback) =>
          ok({ coords: { latitude: 0, longitude: 0 } } as GeolocationPosition),
      },
    })
  }

  it('shows the result distance in kilometres for a kilometre client', async () => {
    units = presetUnitsFor('metric', 'us')
    grantLocationAtOrigin()
    apiPost.mockResolvedValue({ data: { results: [AT_ZERO_ONE_DEGREE], source: 'osm' } })
    render(<ShopFinder />)
    ;(await screen.findByText('shopFinder.enableLocationBtn')).click()
    // 11119.49 m = 11.119 km, at one decimal.
    expect(await screen.findByText('shopFinder.distanceAway|11.1 km')).toBeInTheDocument()
  })

  it('shows it in MILES for a custom set the binary system calls metric', async () => {
    units = { ...presetUnitsFor('metric', 'us'), distance: 'mi' }
    grantLocationAtOrigin()
    apiPost.mockResolvedValue({ data: { results: [AT_ZERO_ONE_DEGREE], source: 'osm' } })
    render(<ShopFinder />)
    ;(await screen.findByText('shopFinder.enableLocationBtn')).click()
    // 11.119492 km / 1.60934 = 6.9093..., at one decimal.
    expect(await screen.findByText('shopFinder.distanceAway|6.9 mi')).toBeInTheDocument()
  })
})
