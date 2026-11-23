import { describe, it, vi } from 'vitest'

// The unit and currency hooks read useAuth, and the shared render has no AuthProvider.
vi.mock('../../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: null, isAuthenticated: false }),
}))
import { render, screen } from '../../../__tests__/test-utils'
import { expectSafeOverlay } from '../../../__tests__/safeOverlay'
import VINDecoderModal from '../VINDecoderModal'

describe('VINDecoderModal layout', () => {
  it('centres inside the iPhone safe area (#305)', () => {
    render(<VINDecoderModal isOpen onClose={vi.fn()} />)
    expectSafeOverlay(screen.getByRole('heading', { name: 'modal.vinDecoder' }))
  })
})
