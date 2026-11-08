import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '../../../__tests__/test-utils'
import ExternalVehicleModal from '../ExternalVehicleModal'
import type { VINDecodeResponse } from '@/types/vin'

// VINInput stands in as buttons: AutoRef's agreement (make only), the version
// the person picked, and a slow pick that answers with the onDecode it started with.
let slow: (() => void) | null = null
vi.mock('@/components/VINInput', () => ({
  default: ({ onDecode }: { onDecode?: (data: VINDecodeResponse) => void }) => (
    <div>
      <button type="button" onClick={() => { slow = () => onDecode?.({ vin: 'WVWZZZAUZFW806653', make: 'Volkswagen', model: 'Golf' }) }}>
        start slow
      </button>
      <button type="button" onClick={() => slow?.()}>
        finish slow
      </button>
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

  it('a nickname typed while the decode is out stays', () => {
    render(<ExternalVehicleModal isOpen onClose={vi.fn()} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'start slow' }))
    fireEvent.change(screen.getByLabelText(/externalVehicles.nickname/), { target: { value: "Dad's car" } })
    fireEvent.click(screen.getByRole('button', { name: 'finish slow' }))
    expect(screen.getByLabelText(/externalVehicles.nickname/)).toHaveValue("Dad's car")
  })
})
