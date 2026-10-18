import { describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'

import type { BrakeCorner, BrakeOverview } from '../../../types/brake'
import { formatDateForDisplay } from '../../../utils/dateUtils'
import vehiclesEn from '../../../locales/en/vehicles.json'

// t reads the shipped English and fills {{name}} from the options by name, so a
// wrong option name leaves the placeholder showing. Kept at module scope:
// react-i18next hands out a stable t, and so must the mock.
vi.mock('react-i18next', () => {
  const t = (key: string, options?: Record<string, unknown>): string => {
    const found = key.split('.').reduce<unknown>(
      (node, part) => (node && typeof node === 'object' ? (node as Record<string, unknown>)[part] : undefined),
      vehiclesEn,
    )
    if (typeof found !== 'string') return key
    return found.replace(/{{(\w+)}}/g, (whole, name: string) =>
      options && name in options ? String(options[name]) : whole,
    )
  }
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
    expect(summary(april)).toBe(`Add an odometer reading to the ${date} measurement`)
    expect(summary(april, 'hours')).toBe(`Add an hour meter reading to the ${date} measurement`)
  })

  it('says the latest only when the latest has no reading', () => {
    const latest = corner({ wear_status: 'no_usage_figures', measured_on: '2026-04-01', reading_needed_on: '2026-04-01' })
    expect(summary(latest)).toBe('Add an odometer reading to the latest measurement')
    expect(summary(latest, 'hours')).toBe('Add an hour meter reading to the latest measurement')
  })

  it('names the date when a second check that day has the reading', () => {
    // Apr 1: an inner-only look with no odometer, then an outer-only one with it.
    const sameDay = corner({ wear_status: 'no_usage_figures', measured_on: '2026-04-01', measured_odometer_km: '20000.00', reading_needed_on: '2026-04-01' })
    expect(summary(sameDay)).toBe(`Add an odometer reading to the ${formatDateForDisplay('2026-04-01')} measurement`)
  })

  it("gives the other pad's date when the thinnest has no estimate", () => {
    const fast = corner({ condition: 'due_soon', wear_status: 'not_decreasing', worn_by: '2026-04-29' })
    expect(summary(fast)).toBe(`No wear measured yet · Other pad reaches the minimum around ${formatDateForDisplay('2026-04-29')}`)
    expect(summary(corner({ wear_status: 'not_decreasing' }))).toBe('No wear measured yet')
  })

  it('leaves a projection to its own date', () => {
    const projected = corner({ wear_status: 'projected', projected_usage_remaining: '1333.3', projected_wear_date: '2026-05-06', worn_by: '2026-05-06' })
    expect(summary(projected)).toBe(`~1333.3 km · ${formatDateForDisplay('2026-05-06')}`)
  })
})
