import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import POICard from '../POICard'
import type { POIResult } from '../../types/poi'
import { binarySystemFor, presetUnitsFor, type UnitSet } from '../../types/units'

/**
 * POICard formatted every distance in miles regardless of the unit preference,
 * and then fell back to metres under one mile, so a metric user saw "1.4 mi"
 * and an imperial user saw "340 m". Both halves then followed the binary
 * `system`, which spec D8 collapses from VOLUME: a custom client with litres
 * and miles read kilometres on a screen whose radius selector offered miles.
 * Both halves now follow the resolved DISTANCE token.
 */

let units: UnitSet = presetUnitsFor('metric', 'us')

// `system` is DERIVED from `units` as the real hook derives it, so the custom
// case below cannot pass by a hardcoded literal happening to agree with it.
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: binarySystemFor(units.volume),
    showBoth: false,
    units,
    gallonStandard: units.secondary_gallon,
  }),
}))

const poi = {
  business_name: 'Test Shop',
  poi_category: 'auto_shop',
  distance_meters: 2300,
} as POIResult

function renderAt(meters: number, set: UnitSet) {
  units = set
  const { unmount } = render(
    <POICard poi={{ ...poi, distance_meters: meters }} onSave={() => {}} isSaved={false} />,
  )
  return unmount
}

const METRIC = presetUnitsFor('metric', 'us')
const IMPERIAL = presetUnitsFor('imperial', 'us')
/** Litres and miles: `system` reads 'metric' while the distance unit is 'mi'. */
const CUSTOM: UnitSet = { ...METRIC, distance: 'mi' }

describe('POICard distance follows the resolved distance unit', () => {
  it('shows kilometres for a kilometre client', () => {
    const unmount = renderAt(2300, METRIC)
    expect(screen.getByText('2.3 km')).toBeInTheDocument()
    unmount()
  })

  it('shows miles for a mile client', () => {
    // 2.3 km / 1.60934 = 1.4291..., at one decimal.
    const unmount = renderAt(2300, IMPERIAL)
    expect(screen.getByText('1.4 mi')).toBeInTheDocument()
    unmount()
  })

  it('shows metres, not feet, for a short kilometre distance', () => {
    const unmount = renderAt(340, METRIC)
    expect(screen.getByText('340 m')).toBeInTheDocument()
    unmount()
  })

  it('shows feet, not metres, for a short mile distance', () => {
    // 340 m / 0.3048 = 1115.48..., rounded and grouped.
    const unmount = renderAt(340, IMPERIAL)
    expect(screen.getByText('1,115 ft')).toBeInTheDocument()
    unmount()
  })

  it('follows the DISTANCE token for a custom set whose volume reads metric', () => {
    const unmount = renderAt(2300, CUSTOM)
    expect(screen.getByText('1.4 mi')).toBeInTheDocument()
    unmount()
  })

  it('falls back to feet for that same custom client under a mile', () => {
    const unmount = renderAt(340, CUSTOM)
    expect(screen.getByText('1,115 ft')).toBeInTheDocument()
    unmount()
  })
})
