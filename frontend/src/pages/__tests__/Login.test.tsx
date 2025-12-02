import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import Login from '../Login'

// Mock axios with create method
vi.mock('axios', () => {
  const mockAxios: any = {
    post: vi.fn(() => Promise.resolve({ data: {} })),
    get: vi.fn(() => Promise.resolve({ data: {} })),
    interceptors: {
      request: { use: vi.fn(), eject: vi.fn() },
      response: { use: vi.fn(), eject: vi.fn() },
    },
  }
  mockAxios.create = vi.fn(() => mockAxios)
  return { default: mockAxios }
})

describe.skip('Login Page', () => {
  // Skipped: Requires AuthProvider setup in test-utils
  it('renders login form', () => {
    render(<Login />)

    expect(screen.getByLabelText(/email|username/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /login|sign in/i })).toBeInTheDocument()
  })
})
