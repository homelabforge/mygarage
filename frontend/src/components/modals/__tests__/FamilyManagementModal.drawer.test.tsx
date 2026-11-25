/**
 * Family is a drawer now, and Add user, Delete user and Configure auth open as
 * nested drawers over it. Esc closes only the top one, and the delete token
 * never carries over from one user to the next.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '../../../__tests__/test-utils'

const { get } = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/services/api', () => ({ default: { get, put: vi.fn(), post: vi.fn(), delete: vi.fn() } }))
vi.mock('@/services/familyService', () => ({
  familyService: {
    getDashboardMembers: vi.fn().mockResolvedValue([]),
    updateDashboardMember: vi.fn(),
  },
}))
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 1, username: 'alice', is_admin: true } }),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import FamilyManagementModal from '../FamilyManagementModal'

const account = (id: number, username: string): Record<string, unknown> => ({
  id,
  username,
  email: `${username}@example.com`,
  full_name: null,
  is_admin: id === 1,
  is_active: true,
  auth_method: 'local',
  oidc_relink_until: null,
  show_on_family_dashboard: true,
  family_dashboard_order: id,
})

beforeEach(() => {
  vi.clearAllMocks()
  get.mockImplementation((url: string) => {
    if (url === '/settings') {
      return Promise.resolve({
        data: { settings: [{ key: 'auth_mode', value: 'local' }, { key: 'multi_user_enabled', value: 'true' }] },
      })
    }
    if (url === '/auth/users') return Promise.resolve({ data: [account(1, 'alice'), account(2, 'bob'), account(3, 'carol')] })
    return Promise.resolve({ data: {} })
  })
})

const renderFamily = async (): Promise<{ onClose: ReturnType<typeof vi.fn> }> => {
  const onClose = vi.fn()
  render(<FamilyManagementModal isOpen onClose={onClose} />)
  await screen.findByText('carol')
  return { onClose }
}

/** Opens Delete for the nth deletable card (alice is you, so 0 is bob, 1 is carol). */
const openDelete = async (index: number): Promise<{ input: HTMLInputElement; button: HTMLElement }> => {
  const deletes = await screen.findAllByTitle('familyCard.deleteUser')
  fireEvent.click(deletes[index])
  const input = (await screen.findByPlaceholderText('DELETE')) as HTMLInputElement
  return { input, button: screen.getByRole('button', { name: 'modal.deleteUser' }) }
}

describe('FamilyManagementModal on Drawer', () => {
  it('renders as a drawer with its title', async () => {
    await renderFamily()
    const drawer = screen.getByTestId('drawer')
    expect(drawer).toHaveAccessibleName('modal.familyManagement')
    expect(drawer).toHaveClass('z-drawer')
  })

  it('Add user opens a nested drawer over Family', async () => {
    await renderFamily()
    fireEvent.click(screen.getByRole('button', { name: 'familyManagementModal.addUser' }))
    const addUser = await screen.findByRole('dialog', { name: 'modal.addUser' })
    expect(addUser).toHaveClass('z-drawer-nested')
    expect(screen.getAllByTestId('drawer')).toHaveLength(2)
  })

  it('Configure auth opens a nested drawer over Family', async () => {
    await renderFamily()
    fireEvent.click(screen.getByRole('button', { name: 'modal.configureAuth' }))
    expect(await screen.findByRole('dialog', { name: 'modal.localAuth.title' })).toHaveClass('z-drawer-nested')
  })

  it('Delete user opens a nested drawer with both buttons in its footer', async () => {
    await renderFamily()
    const { button } = await openDelete(0)
    expect(screen.getByRole('dialog', { name: 'modal.deleteUser' })).toHaveClass('z-drawer-nested')
    expect(button.closest('footer')).not.toBeNull()
    expect(screen.getByRole('button', { name: 'deleteUserModal.cancel' }).closest('footer')).not.toBeNull()
  })

  // Regression pin: Family's own Esc juggling already did this before the drawers.
  it('Esc in Add user closes only Add user, not Family', async () => {
    const { onClose } = await renderFamily()
    fireEvent.click(screen.getByRole('button', { name: 'familyManagementModal.addUser' }))
    await screen.findByText('modal.addUser')

    fireEvent.keyDown(document, { key: 'Escape' })

    await waitFor(() => expect(screen.queryByText('modal.addUser')).not.toBeInTheDocument())
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByText('modal.familyManagement')).toBeInTheDocument()
  })

  // Regression pin: the button was already gated on the exact token.
  it('the delete button stays disabled until DELETE is typed', async () => {
    await renderFamily()
    const { input, button } = await openDelete(0)
    expect(button).toBeDisabled()
    fireEvent.change(input, { target: { value: 'DELET' } })
    expect(button).toBeDisabled()
    fireEvent.change(input, { target: { value: 'DELETE' } })
    expect(button).toBeEnabled()
  })

  it("the typed token doesn't survive a close", async () => {
    await renderFamily()
    const first = await openDelete(0)
    expect(document.body.textContent).toContain('modal.email: bob@example.com')
    fireEvent.change(first.input, { target: { value: 'DELETE' } })
    expect(first.button).toBeEnabled()

    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByPlaceholderText('DELETE')).not.toBeInTheDocument())

    const second = await openDelete(1)
    expect(document.body.textContent).toContain('modal.email: carol@example.com')
    expect(second.input).toHaveValue('')
    expect(second.button).toBeDisabled()
  })
})
