import { describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'

import type { BrakeCorner, BrakeOverview } from '../../../types/brake'
import { formatDateForDisplay } from '../../../utils/dateUtils'

// A t that shows what it was handed, so a test can see the date go in. Kept
// at module scope: react-i18next hands out a stable t, and so must the mock.
vi.mock('react-i18next', () => {
  const t = (key: string, options?: Record<string, unknown>): string =>
    options ? `${key} (${Object.values(options).map(String).join(' | ')})` : key
  const i18n = { language: 'en', changeLanguage: () => Promise.resolve() }
  return { useTranslation: () => ({ t, i18n }) }
})

vi.mock('../../../hooks/useUnitFormat', () => ({
  useUnitFormat: () => ({ distance: { format: (v: number | null) => `${v} km` } }),
}))

import { useBrakeText } from '../useBrakeText'

function corner(extra: Partial<BrakeCorner>): BrakeCorner {
  return {
    position: 'FL',
    axle: 'front',
    brake_type: 'disc',
    condition: 'ok',
    wear_status: 'no_measurements',
    surface_past_limit: false,
    measurements: [],
    jobs: [],
    ...extra,
  }
}

function overview(axis: BrakeOverview['usage_axis']): BrakeOverview {
  return { usage_axis: axis, tracks_distance: axis === 'distance', tracks_hours: axis === 'hours', axles: [], corners: [] }
}

const summary = (c: BrakeCorner, axis: BrakeOverview['usage_axis'] = 'distance'): string => {
  const { result } = renderHook(() => useBrakeText())
  return result.current.wearSummary(c, overview(axis))
}

describe('useBrakeText wearSummary', () => {
  it('names the older measurement that needs the reading, by its date', () => {
    const april = corner({ wear_status: 'no_usage_figures', measured_on: '2026-06-01', measured_odometer_km: '30000.00', measured_hours: '120.0', reading_needed_on: '2026-04-01' })
    const date = formatDateForDisplay('2026-04-01')
    expect(summary(april)).toBe(`brakes.wear.needsOdometerOn (${date})`)
    expect(summary(april, 'hours')).toBe(`brakes.wear.needsHoursOn (${date})`)
  })

  it('says the latest only when the latest has no reading', () => {
    const latest = corner({ wear_status: 'no_usage_figures', measured_on: '2026-04-01', reading_needed_on: '2026-04-01' })
    expect(summary(latest)).toBe('brakes.wear.needsOdometer')
    expect(summary(latest, 'hours')).toBe('brakes.wear.needsHours')
  })

  it('names the date when a second check that day has the reading', () => {
    // Apr 1: an inner-only look with no odometer, then an outer-only one with it.
    const sameDay = corner({ wear_status: 'no_usage_figures', measured_on: '2026-04-01', measured_odometer_km: '20000.00', reading_needed_on: '2026-04-01' })
    expect(summary(sameDay)).toBe(`brakes.wear.needsOdometerOn (${formatDateForDisplay('2026-04-01')})`)
  })

  it("gives the other pad's date when the thinnest has no estimate", () => {
    const fast = corner({ condition: 'due_soon', wear_status: 'not_decreasing', worn_by: '2026-04-29' })
    expect(summary(fast)).toBe(`brakes.wear.notDecreasing · brakes.wear.otherPadBy (${formatDateForDisplay('2026-04-29')})`)
    expect(summary(corner({ wear_status: 'not_decreasing' }))).toBe('brakes.wear.notDecreasing')
  })

  it('leaves a projection to its own date', () => {
    const projected = corner({ wear_status: 'projected', projected_usage_remaining: '1333.3', projected_wear_date: '2026-05-06', worn_by: '2026-05-06' })
    expect(summary(projected)).toBe(`~1333.3 km · ${formatDateForDisplay('2026-05-06')}`)
  })
})
