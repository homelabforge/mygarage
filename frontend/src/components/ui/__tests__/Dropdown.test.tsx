import { describe, it, expect, vi } from 'vitest'
import type { SVGProps } from 'react'
import { render, screen, fireEvent } from '../../../__tests__/test-utils'
import Dropdown from '../Dropdown'

const items = (onSelect = vi.fn()) => [
  { id: 'csv', label: 'CSV', onSelect },
  { id: 'pdf', label: 'PDF', onSelect },
]

// Has no lucide default — carries aria-hidden only if Dropdown passes it.
// See standing instructions: lucide-react sets aria-hidden itself, so a test
// built on a lucide icon cannot discriminate whether the component does.
const BareIcon = (props: SVGProps<SVGSVGElement>) => <svg data-testid="bare-icon" {...props} />

describe('Dropdown', () => {
  it('is closed initially and reports that on the trigger', () => {
    render(<Dropdown label="Export" items={items()} />)
    expect(screen.getByRole('button', { name: 'Export' })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('opens on click', () => {
    render(<Dropdown label="Export" items={items()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Export' }))
    expect(screen.getByRole('menu')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Export' })).toHaveAttribute('aria-expanded', 'true')
  })

  it('invokes the item handler and closes', () => {
    const onSelect = vi.fn()
    render(<Dropdown label="Export" items={items(onSelect)} />)
    fireEvent.click(screen.getByRole('button', { name: 'Export' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'CSV' }))
    expect(onSelect).toHaveBeenCalledOnce()
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('closes on Escape', () => {
    render(<Dropdown label="Export" items={items()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Export' }))
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('marks a checked item for assistive tech', () => {
    render(
      <Dropdown
        label="Sort"
        items={[{ id: 'name', label: 'Name', onSelect: () => {}, checked: true }]}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Sort' }))
    expect(screen.getByRole('menuitem', { name: 'Name' })).toHaveAttribute('aria-checked', 'true')
  })

  // Beyond the brief: proves the icon contract from the "Consumes" interface
  // (IconType, rendered aria-hidden). A lucide icon would pass this whether
  // or not Dropdown sets the attribute (lucide sets its own default), so this
  // uses a bare, icon-less SVG per the standing instructions' guidance.
  it('renders an item icon with aria-hidden', () => {
    render(
      <Dropdown
        label="Export"
        items={[{ id: 'csv', label: 'CSV', icon: BareIcon, onSelect: () => {} }]}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Export' }))
    expect(screen.getByTestId('bare-icon')).toHaveAttribute('aria-hidden', 'true')
  })

  // Beyond the brief: the hard constraint that any listener added must be
  // removed on unmount. Balances every 'keydown' add against a matching
  // remove — see the report for the sabotage/restore proof.
  it('removes its keydown listener on unmount (no leak)', () => {
    const addSpy = vi.spyOn(document, 'addEventListener')
    const removeSpy = vi.spyOn(document, 'removeEventListener')
    const { unmount } = render(<Dropdown label="Export" items={items()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Export' }))

    const keydownAdds = addSpy.mock.calls.filter((call) => call[0] === 'keydown').length
    expect(keydownAdds).toBeGreaterThan(0)

    unmount()

    const keydownRemoves = removeSpy.mock.calls.filter((call) => call[0] === 'keydown').length
    expect(keydownRemoves).toBe(keydownAdds)

    addSpy.mockRestore()
    removeSpy.mockRestore()
  })

  // Beyond the brief: closing moves real DOM focus onto a menu item (the
  // arrow-key navigation target), so closing must hand focus back to the
  // trigger or it falls through to document.body — a regression the
  // original ExportMenu never had (it kept focus on the trigger throughout).
  it('returns focus to the trigger after closing on Escape', () => {
    render(<Dropdown label="Export" items={items()} />)
    const trigger = screen.getByRole('button', { name: 'Export' })
    fireEvent.click(trigger)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(trigger).toHaveFocus()
  })
})
