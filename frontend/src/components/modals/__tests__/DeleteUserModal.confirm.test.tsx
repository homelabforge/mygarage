import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '../../../__tests__/test-utils'
import DeleteUserModal, { renderConfirmPrompt } from '../DeleteUserModal'
import type { User } from '../../../__tests__/factories'

/**
 * Guards the confirm affordance on an irreversible delete.
 *
 * i18n extraction turned the prompt into one interpolated sentence, which
 * dropped the red monospace DELETE badge. The badge tells the user what to type
 * verbatim, so it is behaviour rather than decoration — and the confirm button
 * must stay disabled until the token matches exactly.
 */

const user = { id: 1, username: 'someone', email: 'someone@example.com' } as User

function renderModal() {
  const onConfirm = vi.fn()
  render(<DeleteUserModal isOpen user={user} onClose={() => {}} onConfirm={onConfirm} />)
  // The vitest mock is `t: (key) => key`, so the accessible name is the key.
  const confirmButton = screen.getByRole('button', { name: 'modal.deleteUser' })
  const input = screen.getByPlaceholderText('DELETE')
  return { onConfirm, confirmButton, input }
}

describe('renderConfirmPrompt', () => {
  // Tested directly rather than through the component: the test t() returns the
  // raw key, which contains no token, so rendering the modal would only ever
  // exercise the fallback branch.
  it('keeps the token as its own <code> element', () => {
    render(<>{renderConfirmPrompt('Type DELETE to confirm:')}</>)
    expect(screen.getByText('DELETE', { selector: 'code' })).toBeInTheDocument()
  })

  it('preserves the translated word order around the token', () => {
    // Word order differs by language; the badge must not force English order.
    const { container } = render(<>{renderConfirmPrompt('Zum Bestätigen DELETE eingeben:')}</>)
    expect(container.textContent).toBe('Zum Bestätigen DELETE eingeben:')
  })

  it('degrades to plain text if a translation drops the placeholder', () => {
    const { container } = render(<>{renderConfirmPrompt('Bitte bestätigen:')}</>)
    expect(container.textContent).toBe('Bitte bestätigen:')
    expect(container.querySelector('code')).toBeNull()
  })
})

describe('DeleteUserModal confirmation', () => {
  it('stays disabled for a near-miss and enables only on an exact match', () => {
    const { confirmButton, input } = renderModal()

    expect(confirmButton).toBeDisabled()

    fireEvent.change(input, { target: { value: 'delete' } })
    expect(confirmButton).toBeDisabled()

    fireEvent.change(input, { target: { value: 'DELETE' } })
    expect(confirmButton).toBeEnabled()
  })
})

describe('DeleteUserModal drawer', () => {
  it('is a nested drawer with the delete button in its footer', () => {
    const { confirmButton } = renderModal()
    expect(screen.getByRole('dialog', { name: 'modal.deleteUser' })).toHaveClass('z-drawer-nested')
    expect(confirmButton.closest('footer')).not.toBeNull()
  })

  // Family nulls the user as it closes this, so the exit slide needs the last one.
  it('keeps showing the user while it slides out', () => {
    const { rerender } = render(<DeleteUserModal isOpen user={user} onClose={() => {}} onConfirm={() => {}} />)
    rerender(<DeleteUserModal isOpen={false} user={null} onClose={() => {}} onConfirm={() => {}} />)

    expect(screen.getByRole('dialog', { name: 'modal.deleteUser' })).toBeInTheDocument()
    expect(screen.getByText('someone@example.com', { exact: false })).toBeInTheDocument()
  })

  // The header X is a way out the old overlay never had, and Cancel has to clear it too.
  it.each(['common:close', 'deleteUserModal.cancel'])('%s clears the typed token', (closeName) => {
    const onClose = vi.fn()
    const { rerender } = render(<DeleteUserModal isOpen user={user} onClose={onClose} onConfirm={() => {}} />)
    fireEvent.change(screen.getByPlaceholderText('DELETE'), { target: { value: 'DELETE' } })

    fireEvent.click(screen.getByRole('button', { name: closeName }))
    expect(onClose).toHaveBeenCalledTimes(1)
    rerender(<DeleteUserModal isOpen user={user} onClose={onClose} onConfirm={() => {}} />)

    expect(screen.getByPlaceholderText('DELETE')).toHaveValue('')
    expect(screen.getByRole('button', { name: 'modal.deleteUser' })).toBeDisabled()
  })

  // Family keeps this mounted, so switching users while it's open must not carry the token over.
  it('a new user clears the typed token without a close', () => {
    const other = { id: 2, username: 'other', email: 'other@example.com' } as User
    const { rerender } = render(<DeleteUserModal isOpen user={user} onClose={() => {}} onConfirm={() => {}} />)
    fireEvent.change(screen.getByPlaceholderText('DELETE'), { target: { value: 'DELETE' } })

    rerender(<DeleteUserModal isOpen user={other} onClose={() => {}} onConfirm={() => {}} />)

    expect(screen.getByText('other@example.com', { exact: false })).toBeInTheDocument()
    expect(screen.getByPlaceholderText('DELETE')).toHaveValue('')
    expect(screen.getByRole('button', { name: 'modal.deleteUser' })).toBeDisabled()
  })
})
