import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '../../../__tests__/test-utils'
import Drawer from '../Drawer'
import type { IconType } from '../types'

describe('Drawer', () => {
  it('renders nothing when closed', () => {
    render(<Drawer open={false} onClose={() => {}} title="Add Fuel">body</Drawer>)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('renders a labelled dialog when open', () => {
    render(<Drawer open onClose={() => {}} title="Add Fuel">body</Drawer>)
    expect(screen.getByRole('dialog', { name: 'Add Fuel' })).toBeInTheDocument()
  })

  it('is modal', () => {
    render(<Drawer open onClose={() => {}} title="Add Fuel">body</Drawer>)
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true')
  })

  it('closes on Escape', () => {
    const onClose = vi.fn()
    render(<Drawer open onClose={onClose} title="Add Fuel">body</Drawer>)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('closes on the X button', () => {
    const onClose = vi.fn()
    render(<Drawer open onClose={onClose} title="Add Fuel">body</Drawer>)
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('closes on backdrop click', () => {
    const onClose = vi.fn()
    render(<Drawer open onClose={onClose} title="Add Fuel">body</Drawer>)
    fireEvent.click(screen.getByTestId('drawer-backdrop'))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('renders a footer when given one', () => {
    render(
      <Drawer open onClose={() => {}} title="Add Fuel" footer={<button>Save</button>}>
        body
      </Drawer>,
    )
    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument()
  })

  it('carries a stable test id', () => {
    render(<Drawer open onClose={() => {}} title="Add Fuel">body</Drawer>)
    expect(screen.getByTestId('drawer')).toBeInTheDocument()
  })

  it('moves focus into the panel on open', () => {
    render(<Drawer open onClose={() => {}} title="Add Fuel"><input aria-label="Litres" /></Drawer>)
    expect(screen.getByRole('dialog')).toContainElement(document.activeElement as HTMLElement)
  })

  it('does not steal focus when the parent re-renders with a new onClose', () => {
    // Every consumer passes an inline arrow, so onClose has a new identity on
    // every parent render. If the focus effect depends on it, its cleanup and
    // body re-run per keystroke and focus jumps to the Close button in all 15
    // controlled record forms. Hold it in a ref and depend on [open] only.
    const { rerender } = render(
      <Drawer open onClose={() => {}} title="Add Fuel">
        <input aria-label="Litres" />
      </Drawer>,
    )
    const litres = screen.getByRole('textbox', { name: 'Litres' })
    litres.focus()
    expect(document.activeElement).toBe(litres)

    rerender(
      <Drawer open onClose={() => {}} title="Add Fuel">
        <input aria-label="Litres" />
      </Drawer>,
    )
    expect(document.activeElement).toBe(litres)
    expect(document.activeElement).not.toBe(screen.getByRole('button', { name: 'Close' }))
  })

  it('locks body scroll while open and restores it on close', () => {
    const { rerender } = render(
      <Drawer open onClose={() => {}} title="Add Fuel">body</Drawer>,
    )
    expect(document.body.style.overflow).toBe('hidden')

    rerender(<Drawer open={false} onClose={() => {}} title="Add Fuel">body</Drawer>)
    expect(document.body.style.overflow).not.toBe('hidden')
  })

  it('marks the header icon aria-hidden itself, not just relying on the icon default', () => {
    // Not in the brief's own test list. lucide-react icons default to
    // aria-hidden="true" whenever no other a11y prop is present, so a test
    // using a lucide icon here would pass whether or not Drawer sets the
    // attribute itself (see the standing instructions' lucide aria-hidden
    // trap — it already shipped into Badge, Chip and EmptyState this way).
    // BareIcon has no such default, so this only passes if Drawer's own JSX
    // sets aria-hidden="true".
    const BareIcon: IconType = (props) => <svg data-testid="bare-icon" {...props} />
    render(<Drawer open onClose={() => {}} title="Add Fuel" icon={BareIcon}>body</Drawer>)
    expect(screen.getByTestId('bare-icon')).toHaveAttribute('aria-hidden', 'true')
  })
})
