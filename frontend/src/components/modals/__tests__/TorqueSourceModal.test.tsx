/**
 * The Torque source drawer, read by name: the revealed URL and token, their
 * icon buttons, the two Done buttons and each source's revoke. Strings come
 * from the en bundle, so a name that only differs by interpolation shows up.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'

vi.mock('react-i18next', async () => (await import('@/__tests__/i18nEn')).reactI18nextEn())

const svc = vi.hoisted(() => ({
  getTorqueSources: vi.fn(),
  createTorqueSource: vi.fn(),
  deleteTorqueSource: vi.fn(),
}))
vi.mock('@/services/livelinkService', () => ({ livelinkService: svc }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import TorqueSourceModal from '../TorqueSourceModal'

const VIN = '1HGCM82633A004352'

beforeEach(() => {
  vi.clearAllMocks()
  svc.getTorqueSources.mockResolvedValue({
    sources: [
      { device_id: 'torque_a', label: 'Pixel', last_seen: null },
      { device_id: 'torque_b', label: 'Tablet', last_seen: null },
    ],
  })
  svc.createTorqueSource.mockResolvedValue({
    device_id: 'torque_c',
    label: 'New phone',
    token: 'tok-secret',
    upload_url: 'https://garage/api/v1/torque/tok-secret',
  })
})

async function createSource(): Promise<void> {
  fireEvent.click(await screen.findByRole('button', { name: 'Add source' }))
  fireEvent.change(screen.getByRole('textbox', { name: 'Label (optional)' }), { target: { value: 'New phone' } })
  fireEvent.click(screen.getByRole('button', { name: 'Create' }))
  await screen.findByRole('textbox', { name: 'Upload URL' })
}

describe('TorqueSourceModal names', () => {
  it('ties the add-source label to its box', async () => {
    render(<TorqueSourceModal vin={VIN} isOpen onClose={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Add source' }))
    expect(screen.getByRole('textbox', { name: 'Label (optional)' })).toHaveAttribute('maxLength', '100')
  })

  it('names the revealed fields and the buttons beside them', async () => {
    render(<TorqueSourceModal vin={VIN} isOpen onClose={vi.fn()} />)
    await createSource()

    expect(screen.getByRole('textbox', { name: 'Upload URL' })).toHaveValue('https://garage/api/v1/torque/tok-secret')
    // A password box has no role, so the label tie is checked by label.
    expect(screen.getByLabelText('Device Token')).toHaveValue('tok-secret')
    expect(screen.getByRole('button', { name: 'Copy Upload URL' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Copy Device Token' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Show Device Token' }))
    expect(screen.getByRole('textbox', { name: 'Device Token' })).toHaveValue('tok-secret')
    expect(screen.getByRole('button', { name: 'Hide Device Token' })).toBeInTheDocument()
  })

  it("tells the token's Done apart from the drawer's Done", async () => {
    const onClose = vi.fn()
    render(<TorqueSourceModal vin={VIN} isOpen onClose={onClose} />)
    await createSource()

    // Only the footer is plain "Done"; the reveal's starts with Done and says it's the token.
    const footerDone = screen.getByRole('button', { name: 'Done' })
    const revealDone = screen.getByRole('button', { name: /^Done, .*token/i })
    expect(revealDone).not.toBe(footerDone)
    expect(revealDone).toHaveTextContent('Done')

    fireEvent.click(revealDone)
    expect(screen.queryByRole('textbox', { name: 'Upload URL' })).toBeNull()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('names each revoke button after its source', async () => {
    render(<TorqueSourceModal vin={VIN} isOpen onClose={vi.fn()} />)
    const dialog = await screen.findByRole('dialog', { name: 'Torque Pro Sources' })
    expect(await within(dialog).findByRole('button', { name: 'Revoke Pixel' })).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Revoke Tablet' })).toBeInTheDocument()
  })
})
