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
