/**
 * A German gauge reading "0.346" in a /32 in field is read as 0.346 inches
 * (the blur makes it 11/32), but before the blur the box's own hint said
 * "Read as 346". The hint has to say what the field will do with it.
 * Strings come from the en bundle so the hint's number shows.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render } from '@testing-library/react'
import { useState, type ReactElement } from 'react'

import { IMPERIAL_UNITS } from '../../../__tests__/factories'
import { setActiveLocale } from '@/constants/i18n'

vi.mock('react-i18next', async () => (await import('@/__tests__/i18nEn')).reactI18nextEn())
vi.mock('../../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: 'imperial',
    showBoth: false,
    gallonStandard: IMPERIAL_UNITS.secondary_gallon,
    units: IMPERIAL_UNITS,
  }),
}))

import TreadField from '../TreadField'

function Harness(): ReactElement {
  const [value, setValue] = useState('')
  return <TreadField id="tread" label="Tread" value={value} onChange={setValue} onConverted={vi.fn()} />
}

const field = (): HTMLInputElement => document.getElementById('tread') as HTMLInputElement
const readAs = (): string | null => document.getElementById('tread-ambiguity')?.textContent ?? null

afterEach(() => setActiveLocale('en'))

describe('TreadField: the read-as hint agrees with the gauge reading', () => {
  it('de: 0.346 says it reads as 0,346, not 346', () => {
    setActiveLocale('de')
    render(<Harness />)
    fireEvent.change(field(), { target: { value: '0.346' } })
    expect(readAs()).toBe('Read as 0,346')
    expect(field()).toHaveAccessibleDescription(expect.stringContaining('Read as 0,346'))
  })

  it('en: 0.346 needs no hint, it already reads as inches', () => {
    // Guard: passes on main too. Show the gauge hint whenever the gauge rule matches and this fails.
    render(<Harness />)
    fireEvent.change(field(), { target: { value: '0.346' } })
    expect(readAs()).toBeNull()
  })

  it('de: 1.346 is not a gauge reading and keeps the box\'s own hint', () => {
    // Guard: passes on main too. Only text under 1 is a gauge's inches.
    setActiveLocale('de')
    render(<Harness />)
    fireEvent.change(field(), { target: { value: '1.346' } })
    // 1346, grouped the German way.
    expect(readAs()).toBe('Read as 1.346')
  })
})
