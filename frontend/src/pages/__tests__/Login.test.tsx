import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '../../__tests__/test-utils'
import Login from '../Login'

// Mock axios
vi.mock('axios', () => ({
  default: {
    post: vi.fn(),
    get: vi.fn(),
  },
}))

describe('Login Page', () => {
  it('renders login form', () => {
    render(<Login />)

    expect(screen.getByLabelText(/email|username/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /login|sign in/i })).toBeInTheDocument()
  })

  it('validates required fields', async () => {
    render(<Login />)

    const submitButton = screen.getByRole('button', { name: /login|sign in/i })
    fireEvent.click(submitButton)

    await waitFor(() => {
      // Should show validation errors
      expect(screen.getByText(/required/i) || screen.getByText(/cannot be empty/i)).toBeInTheDocument()
    })
  })

  it('validates email format', async () => {
    render(<Login />)

    const emailInput = screen.getByLabelText(/email|username/i)
    fireEvent.change(emailInput, { target: { value: 'invalid-email' } })

    const submitButton = screen.getByRole('button', { name: /login|sign in/i })
    fireEvent.click(submitButton)

    await waitFor(() => {
      expect(screen.getByText(/invalid email|valid email/i)).toBeInTheDocument()
    })
  })

  it('submits form with valid credentials', async () => {
    const { axios } = await import('axios')
    vi.mocked(axios.post).mockResolvedValue({
      data: { access_token: 'fake-token', user: { id: 1, email: 'test@example.com' } },
    })

    render(<Login />)

    fireEvent.change(screen.getByLabelText(/email|username/i), {
      target: { value: 'test@example.com' },
    })
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: 'password123' },
    })

    fireEvent.click(screen.getByRole('button', { name: /login|sign in/i }))

    await waitFor(() => {
      expect(axios.post).toHaveBeenCalledWith(
        expect.stringContaining('/auth/login'),
        expect.objectContaining({ email: 'test@example.com' })
      )
    })
  })

  it('displays error on login failure', async () => {
    const { axios } = await import('axios')
    vi.mocked(axios.post).mockRejectedValue({
      response: { data: { detail: 'Invalid credentials' } },
    })

    render(<Login />)

    fireEvent.change(screen.getByLabelText(/email|username/i), {
      target: { value: 'test@example.com' },
    })
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: 'wrongpassword' },
    })

    fireEvent.click(screen.getByRole('button', { name: /login|sign in/i }))

    await waitFor(() => {
      expect(screen.getByText(/invalid credentials|incorrect/i)).toBeInTheDocument()
    })
  })
})
