import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '../../__tests__/test-utils'
import Dashboard from '../Dashboard'

// Mock axios
vi.mock('axios', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

describe('Dashboard Page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders dashboard header', () => {
    render(<Dashboard />)

    expect(screen.getByText(/my vehicles|dashboard/i)).toBeInTheDocument()
  })

  it('displays loading state', () => {
    const { axios } = require('axios')
    vi.mocked(axios.get).mockImplementation(() => new Promise(() => {}))

    render(<Dashboard />)

    expect(screen.getByText(/loading/i) || screen.getByRole('status')).toBeInTheDocument()
  })

  it('displays vehicle list when loaded', async () => {
    const { axios } = require('axios')
    vi.mocked(axios.get).mockResolvedValue({
      data: [
        {
          id: 1,
          vin: '1HGBH41JXMN109186',
          year: 2018,
          make: 'Honda',
          model: 'Accord',
          nickname: 'Test Vehicle',
        },
      ],
    })

    render(<Dashboard />)

    await waitFor(() => {
      expect(screen.getByText(/Test Vehicle/i)).toBeInTheDocument()
    })
  })

  it('displays empty state when no vehicles', async () => {
    const { axios } = require('axios')
    vi.mocked(axios.get).mockResolvedValue({ data: [] })

    render(<Dashboard />)

    await waitFor(() => {
      expect(screen.getByText(/no vehicles|add your first vehicle/i)).toBeInTheDocument()
    })
  })

  it('has add vehicle button', () => {
    render(<Dashboard />)

    expect(screen.getByRole('button', { name: /add vehicle/i })).toBeInTheDocument()
  })

  it('displays error message on API failure', async () => {
    const { axios } = require('axios')
    vi.mocked(axios.get).mockRejectedValue(new Error('API Error'))

    render(<Dashboard />)

    await waitFor(() => {
      expect(screen.getByText(/error|failed to load/i)).toBeInTheDocument()
    })
  })
})
