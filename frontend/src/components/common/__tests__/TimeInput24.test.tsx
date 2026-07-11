import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '../../../__tests__/test-utils'
import TimeInput24, { normalizeTime, formatTimeForInput } from '../TimeInput24'

describe('normalizeTime (24h)', () => {
  it.each([
    ['22:00', '22:00'],
    ['2200', '22:00'],
    ['6:30', '06:30'],
    ['630', '06:30'],
    ['9', '09:00'],
    ['00:00', '00:00'],
    ['23:59', '23:59'],
    ['25:00', ''],
    ['12:60', ''],
    ['abc', ''],
    ['', ''],
    ['   ', ''],
  ])('normalizes %j -> %j', (input, expected) => {
    expect(normalizeTime(input)).toBe(expected)
  })
})

describe('normalizeTime (12h)', () => {
  it.each([
    ['2:30 PM', '14:30'],
    ['2:30 pm', '14:30'],
    ['2:30 AM', '02:30'],
    ['12:00 AM', '00:00'], // midnight
    ['12:00 PM', '12:00'], // noon
    ['12:30 AM', '00:30'],
    ['1230 PM', '12:30'],
    ['14:30', '14:30'], // unambiguous 24h form still accepted
    ['2:30', ''], //  bare 1-12 without AM/PM is ambiguous -> rejected
    ['12:00', ''], // 12 without meridiem is ambiguous
    ['13:00 PM', ''], // hour 13 invalid with a meridiem
    ['', ''],
  ])('normalizes %j -> %j', (input, expected) => {
    expect(normalizeTime(input, '12h')).toBe(expected)
  })
})

describe('formatTimeForInput', () => {
  it.each([
    ['14:30', '24h', '14:30'],
    ['14:30', '12h', '2:30 PM'],
    ['00:00', '12h', '12:00 AM'],
    ['12:00', '12h', '12:00 PM'],
    ['09:05', '12h', '9:05 AM'],
    ['', '12h', ''],
  ] as const)('formats %j (%s) -> %j', (canonical, fmt, expected) => {
    expect(formatTimeForInput(canonical, fmt)).toBe(expected)
  })
})

describe('TimeInput24 (24h mode)', () => {
  it('renders the provided value', () => {
    render(<TimeInput24 id="t" ariaLabel="Fill-up time" value="22:00" onChange={() => {}} timeFormat="24h" />)
    expect(screen.getByRole('textbox')).toHaveValue('22:00')
  })

  it('fires onChange with raw text on every keystroke (parent stays current without blur)', () => {
    const onChange = vi.fn()
    render(<TimeInput24 id="t" ariaLabel="Fill-up time" value="" onChange={onChange} timeFormat="24h" />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '2200' } })
    expect(onChange).toHaveBeenLastCalledWith('2200') // raw, not yet normalized
  })

  it('normalizes to 24h "HH:MM" on blur (no meridiem shift)', () => {
    const onChange = vi.fn()
    render(<TimeInput24 id="t" ariaLabel="Fill-up time" value="" onChange={onChange} timeFormat="24h" />)
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '2200' } })
    fireEvent.blur(input)
    expect(onChange).toHaveBeenLastCalledWith('22:00')
  })

  it('KEEPS an invalid non-empty value on blur (so submit can block, not silently clear)', () => {
    const onChange = vi.fn()
    render(<TimeInput24 id="t" ariaLabel="Fill-up time" value="" onChange={onChange} timeFormat="24h" />)
    const input = screen.getByRole('textbox') as HTMLInputElement
    fireEvent.change(input, { target: { value: '25:00' } })
    fireEvent.blur(input)
    expect(input.value).toBe('25:00')
    expect(onChange).not.toHaveBeenLastCalledWith('')
  })

  it('clears to "" on blur only when the field is empty', () => {
    const onChange = vi.fn()
    render(<TimeInput24 id="t" ariaLabel="Fill-up time" value="" onChange={onChange} timeFormat="24h" />)
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '' } })
    fireEvent.blur(input)
    expect(onChange).toHaveBeenLastCalledWith('')
  })

  it('sets no native pattern (a pattern would block raw "2200" on Enter-submit)', () => {
    render(<TimeInput24 id="t" ariaLabel="Fill-up time" value="" onChange={() => {}} timeFormat="24h" />)
    expect(screen.getByRole('textbox')).not.toHaveAttribute('pattern')
  })
})

describe('TimeInput24 (12h mode)', () => {
  it('shows the h:mm part and the active meridiem from the value', () => {
    render(<TimeInput24 id="t" ariaLabel="Fill-up time" value="2:30 PM" onChange={() => {}} timeFormat="12h" />)
    expect(screen.getByRole('textbox')).toHaveValue('2:30')
    expect(screen.getByRole('button', { name: 'PM' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'AM' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('emits "h:mm MERIDIEM" when the AM/PM toggle changes (never a silent guess)', () => {
    const onChange = vi.fn()
    render(<TimeInput24 id="t" ariaLabel="Fill-up time" value="2:30 PM" onChange={onChange} timeFormat="12h" />)
    fireEvent.click(screen.getByRole('button', { name: 'AM' }))
    expect(onChange).toHaveBeenLastCalledWith('2:30 AM')
  })

  it('emits "" when the time part is cleared', () => {
    const onChange = vi.fn()
    render(<TimeInput24 id="t" ariaLabel="Fill-up time" value="2:30 PM" onChange={onChange} timeFormat="12h" />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '' } })
    expect(onChange).toHaveBeenLastCalledWith('')
  })

  it('is reachable by its accessible name', () => {
    render(<TimeInput24 id="t" ariaLabel="Fill-up time" value="" onChange={() => {}} timeFormat="12h" />)
    expect(screen.getByLabelText('Fill-up time')).toBeInTheDocument()
  })
})
