import { describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'

import vehiclesEn from '../../../locales/en/vehicles.json'

// t reads the shipped English and fills {{name}} from the options by name, so a
// missing key throws instead of passing on the raw key. Same mock as useBrakeText.
vi.mock('react-i18next', () => {
  const t = (key: string, options?: Record<string, unknown>): string => {
    const found = key.split('.').reduce<unknown>(
      (node, part) => (node && typeof node === 'object' ? (node as Record<string, unknown>)[part] : undefined),
      vehiclesEn,
    )
    if (typeof found !== 'string') throw new Error(`no English string for ${key}`)
    return found.replace(/{{(\w+)}}/g, (whole, name: string) =>
      options && name in options ? String(options[name]) : whole,
    )
  }
  const i18n = { language: 'en', changeLanguage: () => Promise.resolve() }
  return { useTranslation: () => ({ t, i18n }) }
})

import { useWheelLayoutText, type WheelLayoutId } from '../useWheelLayoutText'

const EXPECTED: Record<WheelLayoutId, string> = {
  four: 'Four wheels',
  two: 'Two wheels (front and rear)',
  trike_2f1r: 'Trike, two front wheels',
  trike_1f2r: 'Trike, two rear wheels',
  dually: 'Dual rear wheels (dually)',
  none: 'No wheels',
}

const ALL = Object.keys(EXPECTED) as WheelLayoutId[]

describe('useWheelLayoutText', () => {
  it('gives every layout its English name, not a key', () => {
    const { result } = renderHook(() => useWheelLayoutText())
    for (const id of ALL) {
      expect(result.current.layoutLabel(id)).toBe(EXPECTED[id])
    }
  })

  it('wraps the layout name in the automatic option', () => {
    const { result } = renderHook(() => useWheelLayoutText())
    expect(result.current.autoLabel('two')).toBe('Automatic: Two wheels (front and rear)')
    expect(result.current.autoLabel('two')).toContain(result.current.layoutLabel('two'))
  })

  it('names the new tire positions', () => {
    const positions = vehiclesEn.tireList.positions as Record<string, string>
    expect(positions.F).toBe('Front')
    expect(positions.R).toBe('Rear')
    expect(positions.RLO).toBe('Rear Left Outer')
    expect(positions.RLI).toBe('Rear Left Inner')
    expect(positions.RRI).toBe('Rear Right Inner')
    expect(positions.RRO).toBe('Rear Right Outer')
  })
})
