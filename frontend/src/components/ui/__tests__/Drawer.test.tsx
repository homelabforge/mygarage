import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, act } from '../../../__tests__/test-utils'
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

  it('focuses the first body field on open, not the Close button', () => {
    // The header (with the Close button) always renders before the body
    // slot, so a document-order query over the whole panel is structurally
    // guaranteed to hit Close first. The test above can't catch this — it
    // only asserts focus lands *somewhere* inside the dialog, and Close is
    // inside the dialog too. This one names the actual target.
    render(<Drawer open onClose={() => {}} title="Add Fuel"><input aria-label="Litres" /></Drawer>)
    expect(document.activeElement).toBe(screen.getByRole('textbox', { name: 'Litres' }))
    expect(document.activeElement).not.toBe(screen.getByRole('button', { name: 'Close' }))
  })

  it('falls back to focusing the panel when the body has no focusable control', () => {
    // No input/button/link in the body slot at all (footer is absent too),
    // so the initial-focus query scoped to the body finds nothing. Focus
    // must land on the panel itself, never escape to <body>, and must not
    // fall through to the Close button either.
    render(<Drawer open onClose={() => {}} title="Add Fuel">body</Drawer>)
    expect(document.activeElement).toBe(screen.getByTestId('drawer'))
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

  it('traps Tab focus, wrapping from the last focusable element to the first', () => {
    // Not in the brief's own test list either, but "focus trap" is the
    // explicit point of this primitive (FormModalWrapper never had one) and
    // none of the brief's 11 tests exercise the Tab-wrapping code path at
    // all — without this, that whole branch could be deleted and every
    // required test would still pass.
    render(
      <Drawer open onClose={() => {}} title="Add Fuel" footer={<button>Save</button>}>
        <input aria-label="Litres" />
      </Drawer>,
    )
    const closeButton = screen.getByRole('button', { name: 'Close' })
    const saveButton = screen.getByRole('button', { name: 'Save' })
    saveButton.focus()
    expect(document.activeElement).toBe(saveButton)
    fireEvent.keyDown(document, { key: 'Tab' })
    expect(document.activeElement).toBe(closeButton)
  })

  it('traps Shift+Tab focus, wrapping from the first focusable element to the last', () => {
    render(
      <Drawer open onClose={() => {}} title="Add Fuel" footer={<button>Save</button>}>
        <input aria-label="Litres" />
      </Drawer>,
    )
    const closeButton = screen.getByRole('button', { name: 'Close' })
    const saveButton = screen.getByRole('button', { name: 'Save' })
    closeButton.focus()
    expect(document.activeElement).toBe(closeButton)
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(saveButton)
  })

  it('stays mounted through the closing transition, then unmounts once it ends', () => {
    // The component used to return null in the same render that flipped
    // `open` false, so React tore down the DOM synchronously and the exit
    // slide/fade never had a chance to play. It must now stay mounted until
    // the panel's own transitionend fires.
    const { rerender } = render(<Drawer open onClose={() => {}} title="Add Fuel">body</Drawer>)
    const panel = screen.getByTestId('drawer')

    rerender(<Drawer open={false} onClose={() => {}} title="Add Fuel">body</Drawer>)
    expect(screen.getByTestId('drawer')).toBeInTheDocument()

    fireEvent.transitionEnd(panel)
    expect(screen.queryByTestId('drawer')).not.toBeInTheDocument()
  })

  it('ignores a transitionend bubbling up from a descendant, and still unmounts on the panel\'s own', () => {
    // A hover/focus transition finishing on the Close button (or any other
    // interactive child) bubbles transitionend up through the panel. That
    // must not be mistaken for the panel's own exit transition ending.
    const { rerender } = render(<Drawer open onClose={() => {}} title="Add Fuel">body</Drawer>)
    const panel = screen.getByTestId('drawer')
    const closeButton = screen.getByRole('button', { name: 'Close' })

    rerender(<Drawer open={false} onClose={() => {}} title="Add Fuel">body</Drawer>)
    fireEvent.transitionEnd(closeButton)
    expect(screen.getByTestId('drawer')).toBeInTheDocument()

    fireEvent.transitionEnd(panel)
    expect(screen.queryByTestId('drawer')).not.toBeInTheDocument()
  })

  it('unmounts immediately under prefers-reduced-motion, without waiting on a transition', () => {
    // motion-reduce:transition-none means transition-property is `none` for
    // these users, so transitionend never fires. Waiting on it anyway would
    // strand the drawer mounted — full-screen invisible backdrop and all —
    // for someone who explicitly asked for no motion.
    // vi.spyOn(...).mockRestore() is unreliable here: window.matchMedia is
    // already a vi.fn() (see setup.ts), and restoring a spy over an
    // already-mocked function can leave it as undefined instead of putting
    // the original mock back — which then breaks every later test in this
    // file that reads window.matchMedia. Save and reassign the reference
    // directly instead.
    const originalMatchMedia = window.matchMedia
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: query.includes('prefers-reduced-motion'),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }))
    try {
      const { rerender } = render(<Drawer open onClose={() => {}} title="Add Fuel">body</Drawer>)
      rerender(<Drawer open={false} onClose={() => {}} title="Add Fuel">body</Drawer>)
      expect(screen.queryByTestId('drawer')).not.toBeInTheDocument()
    } finally {
      window.matchMedia = originalMatchMedia
    }
  })

  it('falls back to unmounting on a timeout if transitionend never fires', () => {
    // Belt-and-braces path: a mismatched property, a duration that reads as
    // 0, or any other reason transitionend fails to fire must not leave the
    // drawer's invisible, full-screen backdrop blocking the page forever.
    vi.useFakeTimers()
    try {
      const { rerender } = render(<Drawer open onClose={() => {}} title="Add Fuel">body</Drawer>)
      rerender(<Drawer open={false} onClose={() => {}} title="Add Fuel">body</Drawer>)
      expect(screen.getByTestId('drawer')).toBeInTheDocument()

      act(() => {
        vi.runOnlyPendingTimers()
      })
      expect(screen.queryByTestId('drawer')).not.toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })

  it('cancels a pending close and stays open if reopened mid-transition', () => {
    const { rerender } = render(<Drawer open onClose={() => {}} title="Add Fuel">body</Drawer>)
    rerender(<Drawer open={false} onClose={() => {}} title="Add Fuel">body</Drawer>)
    expect(screen.getByTestId('drawer')).toBeInTheDocument()

    rerender(<Drawer open onClose={() => {}} title="Add Fuel">body</Drawer>)
    const panel = screen.getByTestId('drawer')
    // A transitionend left over from the aborted close must not unmount a
    // drawer that has since reopened.
    fireEvent.transitionEnd(panel)
    expect(screen.getByTestId('drawer')).toBeInTheDocument()
  })
})
