import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import Dashboard from '../Dashboard'

// Mock axios with create method
vi.mock('axios', () => {
  interface MockAxios {
    get: ReturnType<typeof vi.fn>
    post: ReturnType<typeof vi.fn>
    interceptors: {
      request: { use: ReturnType<typeof vi.fn>; eject: ReturnType<typeof vi.fn> }
      response: { use: ReturnType<typeof vi.fn>; eject: ReturnType<typeof vi.fn> }
    }
    create: ReturnType<typeof vi.fn>
  }
  const mockAxios: MockAxios = {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    post: vi.fn(() => Promise.resolve({ data: {} })),
    interceptors: {
      request: { use: vi.fn(), eject: vi.fn() },
      response: { use: vi.fn(), eject: vi.fn() },
    },
    create: vi.fn(),
  }
  mockAxios.create = vi.fn(() => mockAxios)
  return { default: mockAxios }
})

describe('Dashboard Page', () => {
  it('renders dashboard header', () => {
    render(<Dashboard />)

    expect(screen.getByText(/my garage/i)).toBeInTheDocument()
  })

  it('has add vehicle button', () => {
    render(<Dashboard />)

    expect(screen.getByRole('button', { name: /add vehicle/i })).toBeInTheDocument()
  })
})
