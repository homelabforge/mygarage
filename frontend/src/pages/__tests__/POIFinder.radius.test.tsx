/**
 * POIFinder's search radius, and the radius the MAP is asked to draw.
 *
 * Three defects met on this one screen. The radius list and default branched on
 * the binary `system`, which spec D8 collapses from VOLUME. The metres sent to
 * `/poi/search` branched on it too. And the map was handed the user's raw
 * number and multiplied it by a hardcoded `1609.34` UNCONDITIONALLY, so a
 * metric user searching 10 km was drawn a 16.1 km circle.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '../../__tests__/test-utils'
import { binarySystemFor, presetUnitsFor, type UnitSet } from '../../types/units'

const apiGet = vi.fn()
const apiPost = vi.fn()
vi.mock('@/services/api', () => ({
  default: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
  },
}))
// `system` is DERIVED from `units` as the real hook derives it, so the
// custom-set cases below cannot pass by a hardcoded literal agreeing with them.
let units: UnitSet = presetUnitsFor('imperial', 'us')
vi.mock('@/hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: binarySystemFor(units.volume),
    showBoth: false,
    units,
    gallonStandard: units.secondary_gallon,
  }),
}))
// The map is stubbed at the MapDisplay boundary so the metres crossing it are
// visible; LeafletMap's own arithmetic is pinned in its own test.
vi.mock('@/components/MapDisplay', () => ({
  default: ({ radiusMeters }: { radiusMeters: number }) => (
    <div data-testid="map" data-radius={String(radiusMeters)} />
  ),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import POIFinder from '../POIFinder'

const RESULT = {
  business_name: 'Shop',
  latitude: '10',
  longitude: '20',
  poi_category: 'auto_shop',
  distance_meters: 500,
}

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
  apiPost.mockResolvedValue({ data: { results: [RESULT], source: 'osm' } })
  grantLocation()
})

describe('POIFinder radius options', () => {
  it('offers mile radii for a mile client', async () => {
    render(<POIFinder />)
    const select = (await screen.findByLabelText('poiFinder.searchRadius')) as HTMLSelectElement
    expect([...select.options].map((o) => o.textContent)).toStrictEqual([
      '5 mi',
      '10 mi',
      '25 mi',
      '50 mi',
      '100 mi',
    ])
    expect(select.value).toBe('5')
  })

  it('offers kilometre radii for a kilometre client', async () => {
    units = presetUnitsFor('metric', 'us')
    render(<POIFinder />)
    const select = (await screen.findByLabelText('poiFinder.searchRadius')) as HTMLSelectElement
    expect([...select.options].map((o) => o.textContent)).toStrictEqual([
      '10 km',
      '25 km',
      '50 km',
      '100 km',
      '200 km',
    ])
    expect(select.value).toBe('10')
  })

  it('follows the DISTANCE token for a custom set whose volume reads metric', async () => {
    units = { ...presetUnitsFor('metric', 'us'), distance: 'mi' }
    render(<POIFinder />)
    const select = (await screen.findByLabelText('poiFinder.searchRadius')) as HTMLSelectElement
    expect([...select.options].map((o) => o.textContent)).toStrictEqual([
      '5 mi',
      '10 mi',
      '25 mi',
      '50 mi',
      '100 mi',
    ])
  })
})

describe('POIFinder search radius in metres', () => {
  it('sends the default mile radius as metres (5 x 1.60934 km = 8046.7 m)', async () => {
    render(<POIFinder />)
    ;(await screen.findByText('poiFinder.useMyLocation')).click()
    await waitFor(() => expect(apiPost).toHaveBeenCalled())
    expect(apiPost.mock.calls[0][1]).toStrictEqual({
      latitude: 10,
      longitude: 20,
      radius_meters: 8047,
      categories: ['auto_shop'],
    })
  })

  it('searches MILES for a custom set the binary system calls metric', async () => {
    units = { ...presetUnitsFor('metric', 'us'), distance: 'mi' }
    render(<POIFinder />)
    ;(await screen.findByText('poiFinder.useMyLocation')).click()
    await waitFor(() => expect(apiPost).toHaveBeenCalled())
    expect(apiPost.mock.calls[0][1]).toStrictEqual({
      latitude: 10,
      longitude: 20,
      radius_meters: 8047,
      categories: ['auto_shop'],
    })
  })
})

describe('POIFinder map radius', () => {
  it('hands the map the SAME metres it searched, never the raw number', async () => {
    units = presetUnitsFor('metric', 'us')
    render(<POIFinder />)
    ;(await screen.findByText('poiFinder.useMyLocation')).click()
    await waitFor(() => expect(apiPost).toHaveBeenCalled())
    // 10 km searched, so 10,000 m drawn. It used to draw 10 x 1609.34 = 16,093 m.
    expect(await screen.findByTestId('map')).toHaveAttribute('data-radius', '10000')
    expect(apiPost.mock.calls[0][1]).toMatchObject({ radius_meters: 10000 })
  })
})
