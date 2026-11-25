import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '../../../__tests__/test-utils'
import ExternalVehicleModal from '../ExternalVehicleModal'
import type { VINDecodeResponse } from '@/types/vin'
import type { ExternalVehicle } from '@/types/externalVehicle'
import { deleteExternalVehicle } from '@/services/externalVehicleService'
import { answerConfirm, escapeConfirm } from '../../../__tests__/confirmHelpers'

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

describe('ExternalVehicleModal: delete', () => {
  beforeEach(() => vi.clearAllMocks())

  const VEHICLE: ExternalVehicle = {
    id: 5,
    nickname: 'Trailer',
    vin: null,
    year: null,
    make: null,
    model: null,
    vehicle_type: null,
    contact_name: null,
    contact_phone: null,
    notes: null,
    created_at: '2026-01-01T00:00:00',
    updated_at: null,
  }

  it('deletes once the confirm is accepted', async () => {
    vi.mocked(deleteExternalVehicle).mockResolvedValue(undefined as never)
    render(<ExternalVehicleModal isOpen vehicle={VEHICLE} onClose={vi.fn()} onSaved={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'externalVehicles.delete' }))
    await answerConfirm('confirm', 'externalVehicles.confirmDelete')

    await waitFor(() => expect(deleteExternalVehicle).toHaveBeenCalledWith(5))
  })

  // Regression pin: Escape on the confirm must not close the drawer under it.
  it('Escape closes the delete confirm and leaves the drawer open', async () => {
    const onClose = vi.fn()
    render(<ExternalVehicleModal isOpen vehicle={VEHICLE} onClose={onClose} onSaved={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'externalVehicles.delete' }))
    await escapeConfirm('externalVehicles.confirmDelete')

    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog', { name: 'externalVehicles.editTitle' })).toBeInTheDocument()
    expect(deleteExternalVehicle).not.toHaveBeenCalled()
  })
})
