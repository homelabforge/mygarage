import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// The unit and currency hooks read useAuth, and the shared render has no AuthProvider.
vi.mock('../../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: null, isAuthenticated: false }),
}))
import { render, screen } from '../../../__tests__/test-utils'
import VINDecoderModal from '../VINDecoderModal'

describe('VINDecoderModal as a dialog', () => {
  let root: HTMLElement
  beforeEach(() => {
    root = document.body.appendChild(document.createElement('div'))
    root.id = 'root'
  })
  afterEach(() => root.remove())

  it('is a named dialog outside #root', () => {
    render(<VINDecoderModal isOpen onClose={vi.fn()} />, { container: root })
    const dialog = screen.getByRole('dialog', { name: 'modal.vinDecoder' })
    expect(root.contains(dialog)).toBe(false)
  })
})
