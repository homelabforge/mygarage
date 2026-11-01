import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render } from '@testing-library/react'
import { useState, type ReactElement } from 'react'

import { IMPERIAL_UNITS, METRIC_UNITS, type UnitSet } from '../../../__tests__/factories'

/** Overridden per test; imperial unless a test says otherwise. */
let units: UnitSet = IMPERIAL_UNITS
vi.mock('../../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: units.distance === 'km' ? 'metric' : 'imperial',
    showBoth: false,
    gallonStandard: units.secondary_gallon,
    units,
  }),
}))

import TreadField from '../TreadField'

const onConverted = vi.fn()

/** The field holding its own text, the way every form holds it. */
function Harness({ gaugeHint }: { gaugeHint?: boolean }): ReactElement {
  const [value, setValue] = useState('')
  return (
    <TreadField
      id="tread"
      label="Tread"
      value={value}
      onChange={setValue}
      onConverted={onConverted}
      gaugeHint={gaugeHint}
    />
  )
}

const field = (): HTMLInputElement => document.getElementById('tread') as HTMLInputElement
const hint = (): string | null => document.getElementById('tread-hint')?.textContent ?? null

describe('TreadField', () => {
  beforeEach(() => {
    units = IMPERIAL_UNITS
    onConverted.mockReset()
  })

  it('reads a gauge decimal as inches on blur and says what it converted', () => {
    render(<Harness />)
    expect(hint()).toBe('tireList.treadDecimalHint')
    fireEvent.change(field(), { target: { value: '.346' } })
    expect(onConverted).not.toHaveBeenCalled()
    fireEvent.blur(field())
    expect(field()).toHaveValue('11')
    expect(hint()).toBe('tireList.treadConverted')
    // So the form drops the seeded origin: this 11 is a new measurement.
    expect(onConverted).toHaveBeenCalledTimes(1)
    // The next keystroke drops the note, so it never describes a value since replaced.
    fireEvent.change(field(), { target: { value: '10' } })
    expect(hint()).toBe('tireList.treadDecimalHint')
  })

  it('leaves zero, a whole 32nd and anything from an inch up as typed', () => {
    render(<Harness />)
    for (const typed of ['0', '1', '11', '12.5']) {
      fireEvent.change(field(), { target: { value: typed } })
      fireEvent.blur(field())
      expect(field().value).toBe(typed)
      expect(hint()).toBe('tireList.treadDecimalHint')
    }
    expect(onConverted).not.toHaveBeenCalled()
  })

  it('shows no gauge hint when asked not to, but still converts and says so', () => {
    render(<Harness gaugeHint={false} />)
    expect(hint()).toBeNull()
    fireEvent.change(field(), { target: { value: '0.0625' } })
    fireEvent.blur(field())
    expect(field()).toHaveValue('2')
    expect(hint()).toBe('tireList.treadConverted')
  })

  it('never touches a millimetre field, and says nothing about inches there', () => {
    units = METRIC_UNITS
    render(<Harness />)
    expect(hint()).toBeNull()
    fireEvent.change(field(), { target: { value: '0.346' } })
    fireEvent.blur(field())
    expect(field().value).toBe('0.346')
    expect(hint()).toBeNull()
    expect(onConverted).not.toHaveBeenCalled()
  })
})
