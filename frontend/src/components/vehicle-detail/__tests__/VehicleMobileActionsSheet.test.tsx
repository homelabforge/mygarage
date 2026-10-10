import type { ComponentProps } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '../../../__tests__/test-utils'

const h = vi.hoisted(() => ({ authMode: 'local' }))

vi.mock('../../../contexts/AuthContext', () => ({
  useAuth: () => ({ authMode: h.authMode }),
}))

import VehicleMobileActionsSheet from '../VehicleMobileActionsSheet'

function setup(overrides: Partial<ComponentProps<typeof VehicleMobileActionsSheet>> = {}) {
  const props: ComponentProps<typeof VehicleMobileActionsSheet> = {
    vin: '1HGCM82633A004352', isAdmin: false, importing: false, exporting: false, isOnline: true,
    onImportClick: vi.fn(), onExport: vi.fn(), onOpenModal: vi.fn(), onClose: vi.fn(), onEdit: vi.fn(),
    ...overrides,
  }
  render(<VehicleMobileActionsSheet {...props} />)
  return props
}

beforeEach(() => {
  h.authMode = 'local'
})

describe('VehicleMobileActionsSheet', () => {
  // Phone twin of the toolbar check: no user to share as with sign-in off, and
  // isAdmin is false there, so Transfer stays gone too (A-12).
  it('hides Share and Transfer with sign-in off (A-12)', () => {
    h.authMode = 'none'
    setup()
    expect(screen.queryByRole('button', { name: 'detail.shareVehicle' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'detail.transferVehicle' })).not.toBeInTheDocument()
    // The rest of the sheet still renders, so the hide isn't the whole sheet vanishing.
    expect(screen.getByRole('button', { name: 'detail.editVehicle' })).toBeInTheDocument()
  })

  it.each(['local', 'oidc'])('shows Share with auth mode %s and opens the sharing modal', (mode) => {
    h.authMode = mode
    const props = setup()
    fireEvent.click(screen.getByRole('button', { name: 'detail.shareVehicle' }))
    expect(props.onClose).toHaveBeenCalledTimes(1)
    expect(props.onOpenModal).toHaveBeenCalledWith('sharing')
  })
})
