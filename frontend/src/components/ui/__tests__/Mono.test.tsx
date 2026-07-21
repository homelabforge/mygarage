import { describe, it, expect } from 'vitest'
import { render, screen } from '../../../__tests__/test-utils'
import Mono from '../Mono'

describe('Mono', () => {
  it('renders its children in the mono family', () => {
    render(<Mono>1HGCM82633A004352</Mono>)
    expect(screen.getByText('1HGCM82633A004352')).toHaveClass('font-mono')
  })

  it('applies tabular figures by default so columns align', () => {
    render(<Mono>1,234.56</Mono>)
    expect(screen.getByText('1,234.56')).toHaveClass('tabular-nums')
  })

  it('can opt out of tabular figures', () => {
    render(<Mono tabular={false}>abc</Mono>)
    expect(screen.getByText('abc')).not.toHaveClass('tabular-nums')
  })

  it('renders as a different element when asked', () => {
    const { container } = render(<Mono as="td">9</Mono>)
    expect(container.querySelector('td')).toBeInTheDocument()
  })

  it('widens tracking for the vin variant', () => {
    render(<Mono variant="vin">1HGCM82633A004352</Mono>)
    expect(screen.getByText('1HGCM82633A004352')).toHaveClass('tracking-[.02em]')
  })

  it('maps tone to a token class, never a raw palette colour', () => {
    render(<Mono tone="danger">overdue</Mono>)
    const el = screen.getByText('overdue')
    expect(el).toHaveClass('text-danger')
    expect(el.className).not.toMatch(/text-(red|green|blue|amber|yellow)-\d/)
  })

  it('emits no colour class of its own for the inherit tone, so an ambient colour cascades in', () => {
    render(<Mono tone="inherit">42</Mono>)
    const el = screen.getByText('42')
    expect(el).not.toHaveClass('text-text')
    expect(el).not.toHaveClass('text-text-mute')
    expect(el).not.toHaveClass('text-success')
    expect(el).not.toHaveClass('text-warning')
    expect(el).not.toHaveClass('text-danger')
    expect(el).not.toHaveClass('text-info')
    expect(el).not.toHaveClass('text-(--accent-fg)')
    // still gets everything else the primitive normally applies
    expect(el).toHaveClass('font-mono')
  })
})
