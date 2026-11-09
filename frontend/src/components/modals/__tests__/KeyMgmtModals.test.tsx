import { describe, it, expect, vi } from 'vitest'
import { screen, fireEvent } from '@testing-library/react'
import { render } from '../../../__tests__/test-utils'
import CreateWidgetKeyModal from '../CreateWidgetKeyModal'
import TorqueSourceModal from '../TorqueSourceModal'
import VehicleSharingModal from '../VehicleSharingModal'
import api from '../../../services/api'

// The two panels load their lists on open; keep the fetch benign so only the
// Drawer chrome (asserted below) matters. Shape to the component if a run
// surfaces a destructure error.
vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: { sources: [], shares: [], users: [], items: [] } }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

// TorqueSourceModal reads the time preference, which reads the account.
vi.mock('../../../contexts/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: false, user: null }),
}))

describe('key/management modals — Drawer conversion', () => {
  it('CreateWidgetKeyModal renders a labelled dialog with the footer submit', () => {
    render(<CreateWidgetKeyModal isOpen onClose={vi.fn()} />)
    expect(screen.getByRole('dialog', { name: 'widgetKeys.createTitle' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'widgetKeys.submit' })).toBeInTheDocument()
  })

  it('TorqueSourceModal renders a labelled dialog with the footer Done', () => {
    render(<TorqueSourceModal vin="TEST12345678901234" isOpen onClose={vi.fn()} />)
    expect(screen.getByRole('dialog', { name: 'modal.torque.title' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'modal.torque.done' })).toBeInTheDocument()
  })

  it('VehicleSharingModal renders a labelled dialog with the footer Done', () => {
    render(<VehicleSharingModal isOpen vin="TEST12345678901234" vehicleNickname="Test Car" onClose={vi.fn()} />)
    expect(screen.getByRole('dialog', { name: 'modal.shareVehicle' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'vehicleSharingModal.done' })).toBeInTheDocument()
  })
})

describe('CreateWidgetKeyModal create failure', () => {
  function submit(): void {
    render(<CreateWidgetKeyModal isOpen onClose={vi.fn()} />)
    fireEvent.change(screen.getByPlaceholderText('widgetKeys.namePlaceholder'), {
      target: { value: 'Homepage' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'widgetKeys.submit' }))
  }

  it("shows the server's reason for a refused key", async () => {
    vi.mocked(api.post).mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed with status code 403',
      response: { status: 403, data: { detail: 'Nope' } },
    })
    submit()
    expect(await screen.findByText('Nope')).toBeInTheDocument()
  })

  it('names the action through its own key when there is no reason', async () => {
    vi.mocked(api.post).mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed with status code 500',
      response: { status: 500, data: {} },
    })
    submit()
    expect(
      await screen.findByText('Failed to widgetKeys.createAction. An unexpected server error occurred.')
    ).toBeInTheDocument()
  })
})
