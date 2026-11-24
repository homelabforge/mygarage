import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useState, type ReactElement } from 'react'
import { render, screen, fireEvent, within } from '../../../__tests__/test-utils'
import Drawer from '../Drawer'
import Dialog from '../Dialog'
import Dropdown from '../Dropdown'
import SuggestInput from '../../SuggestInput'

// A real #root, so inert has something to land on and portals have somewhere
// to escape from. test-utils' default container isn't #root.
let root: HTMLElement
beforeEach(() => {
  root = document.createElement('div')
  root.id = 'root'
  document.body.appendChild(root)
})
afterEach(() => {
  root.remove()
})

function pressEscape(): void {
  fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' })
}

describe('modal stack', () => {
  it('Esc closes only the top layer', () => {
    const drawerClose = vi.fn()
    const nestedClose = vi.fn()
    const dialogClose = vi.fn()
    const ui = (nestedOpen: boolean, dialogOpen: boolean): ReactElement => (
      <>
        <Drawer open onClose={drawerClose} title="Parent"><input aria-label="Parent field" /></Drawer>
        <Drawer open={nestedOpen} nested onClose={nestedClose} title="Child"><input aria-label="Child field" /></Drawer>
        <Dialog open={dialogOpen} onClose={dialogClose} title="Confirm"><button>OK</button></Dialog>
      </>
    )
    const { rerender } = render(ui(false, false), { container: root })
    rerender(ui(true, false))
    rerender(ui(true, true))

    pressEscape()
    expect(dialogClose).toHaveBeenCalledOnce()
    expect(nestedClose).not.toHaveBeenCalled()
    expect(drawerClose).not.toHaveBeenCalled()
  })

  it('Esc closes only the top of two Dialogs, then the lower one', () => {
    const lowerClose = vi.fn()
    const upperClose = vi.fn()
    const ui = (upperOpen: boolean): ReactElement => (
      <>
        <Dialog open onClose={lowerClose} title="Lower"><button>Lower OK</button></Dialog>
        <Dialog open={upperOpen} onClose={upperClose} title="Upper"><button>Upper OK</button></Dialog>
      </>
    )
    const { rerender } = render(ui(false), { container: root })
    rerender(ui(true))
    expect(screen.getByRole('dialog', { name: 'Lower' }).closest('[inert]')).not.toBeNull()

    pressEscape()
    expect(upperClose).toHaveBeenCalledOnce()
    expect(lowerClose).not.toHaveBeenCalled()

    rerender(ui(false))
    expect(screen.getByRole('dialog', { name: 'Lower' }).closest('[inert]')).toBeNull()
    pressEscape()
    expect(lowerClose).toHaveBeenCalledOnce()
    expect(upperClose).toHaveBeenCalledOnce()
  })

  it('a drawer closing under an open Dialog keeps the lock', () => {
    // Not '' on purpose: restoring a hard-coded '' would pass a blank start.
    document.body.style.overflow = 'clip'
    try {
      const ui = (drawerOpen: boolean, dialogOpen: boolean): ReactElement => (
        <>
          <Drawer open={drawerOpen} onClose={() => {}} title="Parent">p</Drawer>
          <Dialog open={dialogOpen} onClose={() => {}} title="Confirm">d</Dialog>
        </>
      )
      const { rerender } = render(ui(true, false), { container: root })
      rerender(ui(true, true))
      rerender(ui(false, true))
      expect(root).toHaveAttribute('inert')
      expect(root).toHaveAttribute('aria-hidden', 'true')
      expect(document.body.style.overflow).toBe('hidden')

      rerender(ui(false, false))
      expect(document.body.style.overflow).toBe('clip')
      expect(root).not.toHaveAttribute('inert')
      expect(root).not.toHaveAttribute('aria-hidden')
    } finally {
      document.body.style.overflow = ''
    }
  })

  it('layers below the top are inert', () => {
    const ui = (nestedOpen: boolean): ReactElement => (
      <>
        <Drawer open onClose={() => {}} title="Parent">p</Drawer>
        <Drawer open={nestedOpen} nested onClose={() => {}} title="Child">c</Drawer>
      </>
    )
    const { rerender } = render(ui(false), { container: root })
    const parent = screen.getByRole('dialog', { name: 'Parent' })
    const parentBackdrop = screen.getAllByTestId('drawer-backdrop')[0]
    expect(parent).not.toHaveAttribute('inert')

    rerender(ui(true))
    const child = screen.getByRole('dialog', { name: 'Child' })
    expect(parent).toHaveAttribute('inert')
    expect(parentBackdrop).toHaveAttribute('inert')
    expect(child).not.toHaveAttribute('inert')

    rerender(ui(false))
    expect(parent).not.toHaveAttribute('inert')
    expect(parentBackdrop).not.toHaveAttribute('inert')
    // The backdrop's static aria-hidden survives the round trip.
    expect(parentBackdrop).toHaveAttribute('aria-hidden', 'true')
  })

  it('a stay-mounted drawer opening under a Dialog goes inert once its nodes exist', () => {
    // The drawer renders null on the render that flips open, so its nodes
    // show up after its push. Without a second sync they'd stay live.
    const ui = (drawerOpen: boolean): ReactElement => (
      <>
        <Dialog open onClose={() => {}} title="Confirm"><button>OK</button></Dialog>
        <Drawer open={drawerOpen} onClose={() => {}} title="Parent"><input aria-label="Parent field" /></Drawer>
      </>
    )
    const { rerender } = render(ui(false), { container: root })
    rerender(ui(true))
    expect(screen.getByRole('dialog', { name: 'Parent' })).toHaveAttribute('inert')
    expect(screen.getByTestId('drawer-backdrop')).toHaveAttribute('inert')
    expect(screen.getByRole('dialog', { name: 'Confirm' })).toContainElement(document.activeElement as HTMLElement)
  })

  it('top is by rank, not push order: a nested drawer mounting with its parent', () => {
    // Both mount in one commit, and React runs the child's effect first, so
    // the nested drawer pushes before its parent.
    const parentClose = vi.fn()
    const childClose = vi.fn()
    render(
      <Drawer open onClose={parentClose} title="Parent">
        <input aria-label="Parent field" />
        <Drawer open nested onClose={childClose} title="Child">
          <input aria-label="Child field" />
        </Drawer>
      </Drawer>,
      { container: root },
    )
    const child = screen.getByRole('dialog', { name: 'Child' })
    expect(child).not.toHaveAttribute('inert')
    expect(screen.getByRole('dialog', { name: 'Parent' })).toHaveAttribute('inert')
    expect(child).toContainElement(document.activeElement as HTMLElement)

    pressEscape()
    expect(childClose).toHaveBeenCalledOnce()
    expect(parentClose).not.toHaveBeenCalled()
  })

  it('top is by rank, not push order: a Dialog ahead of a Drawer in one commit', () => {
    const dialogClose = vi.fn()
    const drawerClose = vi.fn()
    render(
      <>
        <Dialog open onClose={dialogClose} title="Confirm"><button>OK</button></Dialog>
        <Drawer open onClose={drawerClose} title="Parent"><input aria-label="Parent field" /></Drawer>
      </>,
      { container: root },
    )
    expect(screen.getByRole('dialog', { name: 'Confirm' })).toContainElement(document.activeElement as HTMLElement)
    pressEscape()
    expect(dialogClose).toHaveBeenCalledOnce()
    expect(drawerClose).not.toHaveBeenCalled()
  })

  it('a combobox inside a nested drawer keeps its Esc', () => {
    const onClose = vi.fn()
    function Field(): ReactElement {
      const [value, setValue] = useState('')
      return <SuggestInput id="brand" value={value} onChange={setValue} suggest={() => [{ label: 'Shell' }]} />
    }
    render(
      <Drawer open nested onClose={onClose} title="Child"><Field /></Drawer>,
      { container: root },
    )
    const input = screen.getByRole('combobox')
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    expect(screen.getByRole('listbox')).toBeInTheDocument()

    fireEvent.keyDown(input, { key: 'Escape' })
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('a Dropdown inside a drawer keeps its Esc', () => {
    const onClose = vi.fn()
    render(
      <Drawer open onClose={onClose} title="Parent">
        <Dropdown label="Export" items={[{ id: 'csv', label: 'CSV', onSelect: () => {} }]} />
      </Drawer>,
      { container: root },
    )
    fireEvent.click(screen.getByRole('button', { name: 'Export' }))
    expect(screen.getByRole('menu')).toBeInTheDocument()

    pressEscape()
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('focus goes back to a live trigger, or to the new top layer', () => {
    const ui = (dialogOpen: boolean, showTrigger: boolean): ReactElement => (
      <>
        <Drawer open onClose={() => {}} title="Parent">
          {showTrigger ? <button>Open confirm</button> : null}
          <input aria-label="Name" />
        </Drawer>
        <Dialog open={dialogOpen} onClose={() => {}} title="Confirm"><button>OK</button></Dialog>
      </>
    )
    const { rerender } = render(ui(false, true), { container: root })
    const trigger = screen.getByRole('button', { name: 'Open confirm' })
    trigger.focus()
    rerender(ui(true, true))
    expect(screen.getByRole('dialog', { name: 'Confirm' })).toContainElement(document.activeElement as HTMLElement)
    rerender(ui(false, true))
    expect(document.activeElement).toBe(trigger)

    // Now the trigger goes away while the Dialog is up.
    rerender(ui(true, true))
    expect(() => {
      rerender(ui(true, false))
      rerender(ui(false, false))
    }).not.toThrow()
    const drawer = screen.getByRole('dialog', { name: 'Parent' })
    expect(document.activeElement).toBe(within(drawer).getByRole('button', { name: 'Close' }))
  })

  it('a layer released from under the top moves no focus', () => {
    // The parent pushes second here, so its restoreTo is the child's field.
    // Closing it under the nested drawer must leave focus where the user put it.
    const ui = (parentOpen: boolean): ReactElement => (
      <Drawer open={parentOpen} onClose={() => {}} title="Parent">
        <Drawer open nested onClose={() => {}} title="Child">
          <input aria-label="Child field" />
          <button>Child action</button>
        </Drawer>
      </Drawer>
    )
    const { rerender } = render(ui(true), { container: root })
    expect(document.activeElement).toBe(screen.getByRole('textbox', { name: 'Child field' }))
    const action = screen.getByRole('button', { name: 'Child action' })
    action.focus()
    rerender(ui(false))
    expect(document.activeElement).toBe(action)
  })

  it('the toaster is never inert', () => {
    const section = document.createElement('section')
    section.setAttribute('aria-label', 'Notifications')
    const toaster = document.createElement('ol')
    toaster.setAttribute('data-sonner-toaster', '')
    section.appendChild(toaster)
    document.body.appendChild(section)
    const clean = (): void => {
      for (const el of [section, toaster]) {
        expect(el).not.toHaveAttribute('inert')
        expect(el).not.toHaveAttribute('aria-hidden')
      }
    }
    try {
      const ui = (drawerOpen: boolean, dialogOpen: boolean): ReactElement => (
        <>
          <Drawer open={drawerOpen} onClose={() => {}} title="Parent">p</Drawer>
          <Dialog open={dialogOpen} onClose={() => {}} title="Confirm">d</Dialog>
        </>
      )
      const { rerender } = render(ui(true, false), { container: root })
      expect(root).toHaveAttribute('inert')
      clean()
      rerender(ui(true, true))
      clean()
      rerender(ui(false, false))
      clean()
    } finally {
      section.remove()
    }
  })
})
