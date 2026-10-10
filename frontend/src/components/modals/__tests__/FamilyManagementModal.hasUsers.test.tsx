/**
 * Outside multi-user mode the modal only lists accounts if anyone has
 * registered, and it asks /auth/users/count, which answers has_users.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '../../../__tests__/test-utils'

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

beforeEach(() => {
  vi.clearAllMocks()
})

describe('FamilyManagementModal outside multi-user mode', () => {
  it('loads the accounts once has_users says somebody exists', async () => {
    get.mockImplementation((url: string) => {
      if (url === '/settings') return Promise.resolve({ data: { settings: [{ key: 'auth_mode', value: 'none' }] } })
      if (url === '/auth/users/count') return Promise.resolve({ data: { has_users: true } })
      if (url === '/auth/users') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: {} })
    })

    render(<FamilyManagementModal isOpen onClose={vi.fn()} />)

    await waitFor(() => expect(get).toHaveBeenCalledWith('/auth/users/count'))
    await waitFor(() => expect(get).toHaveBeenCalledWith('/auth/users'))
  })
})
