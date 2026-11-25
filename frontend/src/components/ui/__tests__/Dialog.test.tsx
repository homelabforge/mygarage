import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '../../../__tests__/test-utils'
import Dialog from '../Dialog'

let root: HTMLElement
beforeEach(() => {
  root = document.createElement('div')
  root.id = 'root'
  document.body.appendChild(root)
})
afterEach(() => {
  root.remove()
})

describe('Dialog', () => {
  it('renders role=dialog with the title as its name, portaled outside #root', () => {
    render(
      <Dialog open onClose={() => {}} title="Remove vehicle"><p>Gone for good.</p></Dialog>,
      { container: root },
    )
    const dialog = screen.getByRole('dialog', { name: 'Remove vehicle' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(screen.getByRole('heading', { level: 2, name: 'Remove vehicle' })).toBeInTheDocument()
    expect(root.contains(dialog)).toBe(false)
    expect(dialog.closest('[inert]')).toBeNull()
    expect(root).toHaveAttribute('inert')
  })

  it('renders nothing when closed', () => {
    render(<Dialog open={false} onClose={() => {}} title="Remove vehicle">x</Dialog>, { container: root })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('alertdialog takes its name from labelledBy', () => {
    render(
      <Dialog open onClose={() => {}} role="alertdialog" labelledBy="confirm-msg" describedBy="confirm-detail">
        <p id="confirm-msg">Delete this fuel record?</p>
        <p id="confirm-detail">This can't be undone.</p>
      </Dialog>,
      { container: root },
    )
    const dialog = screen.getByRole('alertdialog', { name: 'Delete this fuel record?' })
    expect(dialog).toHaveAccessibleDescription("This can't be undone.")
  })

  it('shows a header X only with a title and a closeLabel', () => {
    const onClose = vi.fn()
    const { rerender } = render(
      <Dialog open onClose={onClose} title="Decode VIN" closeLabel="Close">x</Dialog>,
      { container: root },
    )
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledOnce()

    rerender(<Dialog open onClose={onClose} labelledBy="m" closeLabel="Close"><p id="m">x</p></Dialog>)
    expect(screen.queryByRole('button', { name: 'Close' })).not.toBeInTheDocument()
  })

  it('Tab wraps inside the dialog', () => {
    render(
      <Dialog open onClose={() => {}} labelledBy="m">
        <p id="m">Pick one</p>
        <button>First</button>
        <button>Last</button>
      </Dialog>,
      { container: root },
    )
    const first = screen.getByRole('button', { name: 'First' })
    const last = screen.getByRole('button', { name: 'Last' })
    last.focus()
    fireEvent.keyDown(last, { key: 'Tab' })
    expect(document.activeElement).toBe(first)
    fireEvent.keyDown(first, { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(last)
  })

  it('Shift+Tab and Tab from the panel itself stay inside', () => {
    render(
      <Dialog open onClose={() => {}} title="Notes" closeLabel="Close">
        <p>Just text.</p>
      </Dialog>,
      { container: root },
    )
    const panel = screen.getByRole('dialog', { name: 'Notes' })
    const close = screen.getByRole('button', { name: 'Close' })
    expect(document.activeElement).toBe(panel)
    expect(fireEvent.keyDown(panel, { key: 'Tab', shiftKey: true })).toBe(false)
    expect(document.activeElement).toBe(close)
    panel.focus()
    expect(fireEvent.keyDown(panel, { key: 'Tab' })).toBe(false)
    expect(document.activeElement).toBe(close)
  })

  it('wraps at the last control that is actually there', () => {
    // A hidden file input, a disabled fieldset and an inert box all match the
    // selector, and none of them can take focus.
    render(
      <Dialog open onClose={() => {}} title="Upload" closeLabel="Close">
        <button>Choose file</button>
        <input type="file" aria-label="File" style={{ display: 'none' }} />
        <div style={{ visibility: 'hidden' }}><button>Ghost</button></div>
        <fieldset disabled><input aria-label="Locked" /></fieldset>
        <div inert><button>Asleep</button></div>
      </Dialog>,
      { container: root },
    )
    const close = screen.getByRole('button', { name: 'Close' })
    const choose = screen.getByRole('button', { name: 'Choose file' })
    close.focus()
    fireEvent.keyDown(close, { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(choose)
    fireEvent.keyDown(choose, { key: 'Tab' })
    expect(document.activeElement).toBe(close)
  })

  it('Tab with nothing to land on keeps focus on the panel', () => {
    render(<Dialog open onClose={() => {}} labelledBy="m"><p id="m">Working on it</p></Dialog>, { container: root })
    const panel = screen.getByRole('dialog')
    expect(document.activeElement).toBe(panel)
    expect(fireEvent.keyDown(panel, { key: 'Tab' })).toBe(false)
    expect(fireEvent.keyDown(panel, { key: 'Tab', shiftKey: true })).toBe(false)
    expect(document.activeElement).toBe(panel)
  })

  it('initialFocus first-field focuses the first field, not a button before it', () => {
    render(
      <Dialog open onClose={() => {}} title="Upload">
        <button>Browse</button>
        <input aria-label="Description" />
      </Dialog>,
      { container: root },
    )
    expect(document.activeElement).toBe(screen.getByRole('textbox', { name: 'Description' }))
  })

  it('initialFocus cancel focuses the cancel button', () => {
    render(
      <Dialog
        open
        onClose={() => {}}
        title="Remove vehicle"
        initialFocus="cancel"
        footer={
          <>
            <button data-dialog-cancel>Cancel</button>
            <button>Remove</button>
          </>
        }
      >
        <input aria-label="Reason" />
      </Dialog>,
      { container: root },
    )
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Cancel' }))
  })

  it('backdrop click calls onClose, a click in the panel does not', () => {
    const onClose = vi.fn()
    render(
      <Dialog open onClose={onClose} title="Remove vehicle"><p>Body</p></Dialog>,
      { container: root },
    )
    fireEvent.pointerDown(screen.getByText('Body'))
    fireEvent.pointerUp(screen.getByText('Body'))
    fireEvent.click(screen.getByText('Body'))
    expect(onClose).not.toHaveBeenCalled()
    const backdrop = screen.getByTestId('dialog-backdrop')
    fireEvent.pointerDown(backdrop)
    fireEvent.pointerUp(backdrop)
    fireEvent.click(backdrop)
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('a drag from a field in the panel that lets go over the backdrop does not close', () => {
    // Chromium sends that click to the overlay, the common ancestor, so it looked
    // like a backdrop click and threw away whatever was typed.
    const onClose = vi.fn()
    render(
      <Dialog open onClose={onClose} title="Upload"><input aria-label="Title" /></Dialog>,
      { container: root },
    )
    fireEvent.pointerDown(screen.getByRole('textbox', { name: 'Title' }))
    fireEvent.pointerUp(screen.getByTestId('dialog-backdrop'))
    fireEvent.click(screen.getByTestId('dialog-backdrop'))
    expect(onClose).not.toHaveBeenCalled()
  })

  it('a press that starts on the backdrop and lets go in the panel does not close', () => {
    // The click still lands on the overlay (the common ancestor), so both ends count.
    const onClose = vi.fn()
    render(
      <Dialog open onClose={onClose} title="Upload"><input aria-label="Title" /></Dialog>,
      { container: root },
    )
    const backdrop = screen.getByTestId('dialog-backdrop')
    fireEvent.pointerDown(backdrop)
    fireEvent.pointerUp(screen.getByRole('textbox', { name: 'Title' }))
    fireEvent.click(backdrop)
    expect(onClose).not.toHaveBeenCalled()
  })

  it('forgets where the last press started once its click lands', () => {
    const onClose = vi.fn()
    render(
      <Dialog open onClose={onClose} title="Upload"><input aria-label="Title" /></Dialog>,
      { container: root },
    )
    const backdrop = screen.getByTestId('dialog-backdrop')
    fireEvent.pointerDown(backdrop)
    fireEvent.pointerUp(backdrop)
    fireEvent.click(backdrop)
    expect(onClose).toHaveBeenCalledOnce()
    // A bare click with no press of its own (a synthetic one) mustn't ride on the old press.
    fireEvent.click(backdrop)
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('Esc calls onClose', () => {
    const onClose = vi.fn()
    render(<Dialog open onClose={onClose} title="Remove vehicle"><button>OK</button></Dialog>, { container: root })
    fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledOnce()
  })
})
