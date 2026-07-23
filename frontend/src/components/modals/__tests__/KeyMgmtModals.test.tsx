import { describe, it, expect, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { render } from '../../../__tests__/test-utils'
import CreateWidgetKeyModal from '../CreateWidgetKeyModal'
import TorqueSourceModal from '../TorqueSourceModal'
import VehicleSharingModal from '../VehicleSharingModal'

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
