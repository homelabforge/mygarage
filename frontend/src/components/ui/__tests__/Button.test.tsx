import { describe, it, expect, vi } from 'vitest'
import { Plus } from 'lucide-react'
import { render, screen, fireEvent } from '../../../__tests__/test-utils'
import Button from '../Button'
import type { IconType } from '../types'

describe('Button', () => {
  it('renders a real button and fires onClick', () => {
    const onClick = vi.fn()
    render(<Button onClick={onClick}>Add Vehicle</Button>)
    fireEvent.click(screen.getByRole('button', { name: 'Add Vehicle' }))
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('defaults to type=button so it never submits a form by accident', () => {
    render(<Button>Cancel</Button>)
    expect(screen.getByRole('button')).toHaveAttribute('type', 'button')
  })

  it('honours an explicit type', () => {
    render(<Button type="submit">Save</Button>)
    expect(screen.getByRole('button')).toHaveAttribute('type', 'submit')
  })

  it('uses the accent foreground on the solid variant, never text-white', () => {
    render(<Button variant="primary">Save</Button>)
    // text-white under amber is ~2:1. The accent carries its own readable
    // foreground for exactly this reason (design §4.3).
    expect(screen.getByRole('button').className).not.toMatch(/\btext-white\b/)
    expect(screen.getByRole('button').className).toContain('--accent-on-solid')
  })

  it('is disabled and inert while loading', () => {
    const onClick = vi.fn()
    render(<Button loading onClick={onClick}>Save</Button>)
    const button = screen.getByRole('button')
    expect(button).toBeDisabled()
    fireEvent.click(button)
    expect(onClick).not.toHaveBeenCalled()
  })

  it('keeps its accessible name while loading', () => {
    render(<Button loading>Save</Button>)
    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument()
  })

  // This only proves the icon renders next to the label — lucide-react sets
  // aria-hidden="true" on its own icons by default whenever no other a11y
  // prop is passed (dist/cjs/lucide-react.js:
  // `...!children && !hasA11yProp(rest) && { 'aria-hidden': 'true' }`), and an
  // <svg> with no text content contributes nothing to accessible-name
  // computation either way — so this test passes whether or not Button sets
  // aria-hidden itself. The real contract is covered by the bare-icon test
  // below, which uses an icon with no default and asserts the attribute
  // directly.
  it('renders a decorative icon alongside the label (lucide default, not a guard)', () => {
    render(<Button icon={Plus}>Add</Button>)
    expect(screen.getByRole('button', { name: 'Add' })).toBeInTheDocument()
  })

  it('marks the icon aria-hidden itself, not just relying on the icon default', () => {
    const BareIcon: IconType = (props) => <svg data-testid="bare-icon" {...props} />
    render(<Button icon={BareIcon}>Add</Button>)
    expect(screen.getByTestId('bare-icon')).toHaveAttribute('aria-hidden', 'true')
  })
})
