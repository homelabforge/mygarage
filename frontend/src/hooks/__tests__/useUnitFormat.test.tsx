/**
 * `useUnitFormat()` is the component-facing half of the adapter: it closes over
 * whatever `useUnitPreference()` resolved for this client, so every rung of that
 * precedence (an account, an anonymous choice, the instance default, the
 * post-093 fallback) reaches a call site through one object.
 *
 * The set the mock supplies is deliberately one no preset can produce, so a
 * hook that rebuilt units from the binary `system` instead of reading the
 * resolved set cannot pass.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { METRIC_UNITS, makeUnitSet } from '@/__tests__/factories'
import type { UnitSet } from '@/types/units'

const h = vi.hoisted(() => ({
  units: undefined as unknown as UnitSet,
  showBoth: false,
}))

vi.mock('../useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: 'metric' as const,
    showBoth: h.showBoth,
    gallonStandard: 'us' as const,
    units: h.units,
  }),
}))

import { useUnitFormat } from '../useUnitFormat'

describe('useUnitFormat', () => {
  beforeEach(() => {
    h.units = METRIC_UNITS
    h.showBoth = false
  })

  it('reads the resolved set, not the binary system it collapses to', () => {
    // Metric everywhere except tread, which no preset does. `system` is
    // 'metric' in the mock, so a hook keyed on it would answer 'mm'.
    h.units = makeUnitSet({ tread: 'in32' })

    const { result } = renderHook(() => useUnitFormat())

    expect(result.current.tread.label).toBe('/32 in')
    expect(result.current.pressure.label).toBe('kPa')
  })

  it('converts through the set it closed over', () => {
    h.units = makeUnitSet({ tread: 'in32' })

    const { result } = renderHook(() => useUnitFormat())

    // 9/32 in x 0.79375 = 7.14375 mm
    expect(result.current.tread.toCanonical(9)).toBe(7.14375)
  })

  it('renders one representation when the client did not ask for both', () => {
    const { result } = renderHook(() => useUnitFormat())

    expect(result.current.tread.format(7.5)).toBe('7.50 mm')
  })

  it('renders the counterpart when the client asked for both', () => {
    h.showBoth = true

    const { result } = renderHook(() => useUnitFormat())

    // 7.5 mm / 0.79375 = 9.4488..., rendered at in32's zero decimals.
    expect(result.current.tread.format(7.5)).toBe('7.50 mm (9/32 in)')
  })

  it('keeps one identity across renders so a memo on it does not thrash', () => {
    const { result, rerender } = renderHook(() => useUnitFormat())
    const first = result.current

    rerender()

    expect(result.current).toBe(first)
  })

  it('rebuilds when the resolved set changes underneath it', () => {
    const { result, rerender } = renderHook(() => useUnitFormat())
    expect(result.current.tread.label).toBe('mm')

    h.units = makeUnitSet({ tread: 'in32' })
    rerender()

    expect(result.current.tread.label).toBe('/32 in')
  })
})
