import { describe, it, expect, vi } from 'vitest'
import { Trash2 } from 'lucide-react'
import { render, screen, fireEvent } from '../../../__tests__/test-utils'
import IconButton from '../IconButton'
import type { IconType } from '../types'

describe('IconButton', () => {
  it('exposes an accessible name', () => {
    render(<IconButton icon={Trash2} label="Delete" />)
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument()
  })

  it('keeps title alongside aria-label', () => {
    // e2e pins button[title="Delete"] at records.spec.ts:50,79,147 and
    // a unit test pins getByTitle at VehicleDetail.test.tsx:378.
    render(<IconButton icon={Trash2} label="Delete" />)
    const button = screen.getByRole('button', { name: 'Delete' })
    expect(button).toHaveAttribute('title', 'Delete')
    expect(button).toHaveAttribute('aria-label', 'Delete')
  })

  it('allows title to differ from the accessible name', () => {
    render(<IconButton icon={Trash2} label="Delete" title="Delete this record" />)
    const button = screen.getByRole('button', { name: 'Delete' })
    expect(button).toHaveAttribute('title', 'Delete this record')
  })

  it('fires onClick', () => {
    const onClick = vi.fn()
    render(<IconButton icon={Trash2} label="Delete" onClick={onClick} />)
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(onClick).toHaveBeenCalledOnce()
  })

  // This only proves the icon renders — lucide-react sets aria-hidden="true"
  // on its own icons by default whenever no other a11y prop is passed (dist/
  // cjs/lucide-react.js: `...!children && !hasA11yProp(rest) && { 'aria-hidden':
  // 'true' }`), so this assertion passes whether or not IconButton sets the
  // attribute itself. The real contract — that IconButton itself sets
  // aria-hidden, not just that lucide defaults to it — is covered by the
  // bare-icon test below, which uses an icon with no default.
  it('renders the glyph hidden from the accessible name (lucide default, not a guard)', () => {
    const { container } = render(<IconButton icon={Trash2} label="Delete" />)
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  })

  it('marks the icon aria-hidden itself, not just relying on the icon default', () => {
    const BareIcon: IconType = (props) => <svg data-testid="bare-icon" {...props} />
    render(<IconButton icon={BareIcon} label="Delete" />)
    expect(screen.getByTestId('bare-icon')).toHaveAttribute('aria-hidden', 'true')
  })

  it('is unconditionally a real button element', () => {
    render(<IconButton icon={Trash2} label="Delete" />)
    expect(screen.getByRole('button', { name: 'Delete' }).tagName).toBe('BUTTON')
  })
})
