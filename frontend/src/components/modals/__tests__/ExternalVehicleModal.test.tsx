import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '../../../__tests__/test-utils'
import ExternalVehicleModal from '../ExternalVehicleModal'
import type { VINDecodeResponse } from '@/types/vin'

// VINInput stands in as two buttons: AutoRef's agreement (make only), then
// the version the person picked.
vi.mock('@/components/VINInput', () => ({
  default: ({ onDecode }: { onDecode?: (data: VINDecodeResponse) => void }) => (
    <div>
      <button type="button" onClick={() => onDecode?.({ vin: 'WVWZZZAUZFW806653', make: 'Volkswagen', model: null })}>
        agreement
      </button>
      <button type="button" onClick={() => onDecode?.({ vin: 'WVWZZZAUZFW806653', make: 'Volkswagen', model: 'Golf' })}>
        picked
      </button>
    </div>
  ),
}))

vi.mock('@/services/externalVehicleService', () => ({
  createExternalVehicle: vi.fn(),
  updateExternalVehicle: vi.fn(),
  deleteExternalVehicle: vi.fn(),
}))

describe('ExternalVehicleModal: the decoded nickname', () => {
  it('a later decode rewrites the nickname a decode wrote', () => {
    render(<ExternalVehicleModal isOpen onClose={vi.fn()} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'agreement' }))
    expect(screen.getByLabelText(/externalVehicles.nickname/)).toHaveValue('Volkswagen')
    fireEvent.click(screen.getByRole('button', { name: 'picked' }))
    expect(screen.getByLabelText(/externalVehicles.nickname/)).toHaveValue('Volkswagen Golf')
  })

  it('a nickname the person typed stays', () => {
    render(<ExternalVehicleModal isOpen onClose={vi.fn()} onSaved={vi.fn()} />)
    fireEvent.change(screen.getByLabelText(/externalVehicles.nickname/), { target: { value: "Dad's car" } })
    fireEvent.click(screen.getByRole('button', { name: 'picked' }))
    expect(screen.getByLabelText(/externalVehicles.nickname/)).toHaveValue("Dad's car")
  })
})
