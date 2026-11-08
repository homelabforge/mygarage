/**
 * Editing a user as an admin, SSO users included.
 *
 * Active is MyGarage's own kill switch: it's checked on every request, so
 * unticking it ends a live session at once, and the IdP never touches it. The
 * dialog used to lock it for SSO users and leave it out of the save, so an
 * admin couldn't disable one at all. The name belongs to the IdP, which sets it
 * on every sign-in. The email doesn't: nothing syncs it, so it's editable, and
 * sent only when changed.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { render, screen, fireEvent, waitFor } from '../../../__tests__/test-utils'
import { makeUser, type User } from '@/__tests__/factories'

const { put, post, t, i18n } = vi.hoisted(() => ({
  put: vi.fn(),
  post: vi.fn(),
  // Echoes the provider, so a test can see who the SSO description names.
  t: (key: string, opts?: { provider?: string }): string =>
    opts?.provider ? `${key} ${opts.provider}` : key,
  i18n: { language: 'en', changeLanguage: (): Promise<void> => Promise.resolve() },
}))
vi.mock('@/services/api', () => ({ default: { put, post } }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t, i18n }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}))

import AddEditUserModal from '../AddEditUserModal'

const account = (overrides: Partial<User> = {}): User => makeUser({
  id: 7,
  username: 'dana',
  email: 'dana@example.com',
  full_name: 'Dana',
  is_active: true,
  is_admin: false,
  auth_method: 'oidc',
  oidc_provider: 'Rauthy',
  oidc_relink_until: null,
  created_at: '2026-01-01T00:00:00',
  updated_at: '2026-01-01T00:00:00',
  last_login: null,
  relationship: null,
  relationship_custom: null,
  show_on_family_dashboard: true,
  family_dashboard_order: 0,
  ...overrides,
})

// activeAdminCount defaults to 1 so every test runs with a last admin in the
// house, and only the edited user's own flags decide whether it's them.
const renderEdit = (user: User, { currentUserId = 1, activeAdminCount = 1 } = {}): void => {
  render(
    <AddEditUserModal
      isOpen
      onClose={vi.fn()}
      onSave={vi.fn()}
      user={user}
      currentUserId={currentUserId}
      activeAdminCount={activeAdminCount}
    />,
  )
}

const activeBox = (): HTMLInputElement =>
  screen.getByRole('checkbox', { name: 'modal.activeUser' }) as HTMLInputElement

/** Saves the dialog and returns the body of the one PUT it made. */
const save = async (): Promise<Record<string, unknown>> => {
  fireEvent.click(screen.getByRole('button', { name: 'common:update' }))
  await waitFor(() => expect(put).toHaveBeenCalledTimes(1))
  const [url, body] = put.mock.calls[0] as [string, Record<string, unknown>]
  expect(url).toBe('/auth/users/7')
  return body
}

beforeEach(() => {
  vi.clearAllMocks()
  put.mockResolvedValue({ data: {} })
})

describe('AddEditUserModal active status', () => {
  it('unticking Active on an SSO user saves is_active false, and no name', async () => {
    renderEdit(account())

    expect(activeBox()).toBeEnabled()
    fireEvent.click(activeBox())
    const body = await save()

    expect(body).toHaveProperty('is_active', false)
    expect(body).not.toHaveProperty('full_name')
    expect(post).not.toHaveBeenCalled()
  })

  it.each([true, false])('an untouched SSO save sends is_active as it was (%s)', async (isActive) => {
    renderEdit(account({ is_active: isActive }))

    const body = await save()

    expect(body).toHaveProperty('is_active', isActive)
  })

  it('a local user still saves email and name with Active', async () => {
    renderEdit(account({ auth_method: 'local', oidc_provider: null }))

    fireEvent.click(activeBox())
    const body = await save()

    expect(body).toMatchObject({ is_active: false, email: 'dana@example.com', full_name: 'Dana' })
  })

  it('tells SSO users what Active does, not that the IdP manages it', () => {
    renderEdit(account())
    expect(screen.getByText('modal.inactiveUsersCannotLogin')).toBeInTheDocument()
  })

  it('names the provider and says active status can be edited', () => {
    renderEdit(account())
    expect(screen.getByText('modal.oidcUserDescriptionEditable Rauthy', { exact: false })).toBeInTheDocument()
  })
})

describe('AddEditUserModal SSO email and name', () => {
  it("lets an admin change an SSO user's email, and saves it", async () => {
    renderEdit(account())

    const email = screen.getByDisplayValue('dana@example.com')
    expect(email).toBeEnabled()
    fireEvent.change(email, { target: { value: 'dana@new.example' } })
    const body = await save()

    expect(body).toHaveProperty('email', 'dana@new.example')
    expect(body).not.toHaveProperty('full_name')
  })

  // The IdP's address can be one the server's email check refuses, so an
  // untouched save leaves it out rather than fail on it.
  it('an untouched SSO save leaves the email out', async () => {
    renderEdit(account({ email: 'admin@localhost' }))

    fireEvent.click(activeBox())
    const body = await save()

    expect(body).toHaveProperty('is_active', false)
    expect(body).not.toHaveProperty('email')
  })

  // The browser's own email check refuses addresses an IdP happily stores, and
  // a blocked submit would stop even an Active-only save.
  it("saves an SSO user whose IdP email the browser's email check refuses", async () => {
    renderEdit(account({ email: 'jörg@example.com' }))

    fireEvent.click(activeBox())
    const body = await save()

    expect(body).toHaveProperty('is_active', false)
    expect(body).not.toHaveProperty('email')
  })

  it("keeps an SSO user's name locked, with the only managed-by hint", () => {
    renderEdit(account())

    expect(screen.getByDisplayValue('Dana')).toBeDisabled()
    expect(screen.getAllByText('modal.managedByOidc')).toHaveLength(1)
  })
})

describe('AddEditUserModal last active admin', () => {
  // Someone else's card on purpose: the lock is for whoever is the last active
  // admin, not only when it's you.
  it.each(['local', 'oidc'] as const)('locks Active on the last active admin, with a hint (%s)', (authMethod) => {
    renderEdit(account({ auth_method: authMethod, is_admin: true }))

    expect(activeBox()).toBeDisabled()
    expect(screen.getByText('modal.lastActiveAdminDisableWarning')).toBeInTheDocument()
  })

  it('leaves Active open on an admin when another admin is active', () => {
    renderEdit(account({ is_admin: true }), { activeAdminCount: 2 })

    expect(activeBox()).toBeEnabled()
    expect(screen.queryByText('modal.lastActiveAdminDisableWarning')).not.toBeInTheDocument()
  })

  it('leaves Active open on a disabled admin, so it can be turned back on', () => {
    renderEdit(account({ is_admin: true, is_active: false }))

    expect(activeBox()).toBeEnabled()
    expect(screen.queryByText('modal.lastActiveAdminDisableWarning')).not.toBeInTheDocument()
  })
})
