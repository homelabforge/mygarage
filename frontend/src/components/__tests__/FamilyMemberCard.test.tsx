/**
 * The admin actions on a family member card: the SSO relink, and disable,
 * delete and password reset for SSO users.
 *
 * An SSO user whose identity provider account was re-created can't sign in
 * until an admin allows a one-time relink. The card offers that to SSO users,
 * one tap, and badges the account while the window is open.
 *
 * oidc_relink_until is naive UTC. The file runs in a zone behind UTC, so a
 * plain `new Date()` read of it lands hours late and an expired window looks
 * open.
 */
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { render, screen, fireEvent, within } from '../../__tests__/test-utils'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import FamilyMemberCard from '../FamilyMemberCard'
import type { FamilyMemberData } from '@/types/family'
import type { User } from '@/types/user'
import { formatTime } from '@/utils/parseAPITimestamp'
import commonEn from '@/locales/en/common.json'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { time?: string; action?: string; name?: string }) => {
      // Same shape as the shipped "{{action}}: {{name}}", so names read "familyCard.editUser: Dana".
      if (key === 'familyCard.actionFor') return `${opts?.action}: ${opts?.name}`
      return opts?.time ? `${key} ${opts.time}` : key
    },
    i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}))
vi.mock('@/hooks/useTimeFormat', () => ({ useTimeFormat: () => ({ timeFormat: '24h' }) }))

beforeAll(() => {
  vi.stubEnv('TZ', 'America/Chicago')
})
afterAll(() => {
  vi.unstubAllEnvs()
})

const member: FamilyMemberData = {
  id: 7,
  username: 'dana',
  full_name: 'Dana',
  relationship: null,
  relationship_custom: null,
  vehicle_count: 0,
  vehicles: [],
  overdue_maintenance: 0,
  upcoming_maintenance: 0,
  show_on_family_dashboard: true,
  family_dashboard_order: 0,
}

const user = (overrides: Partial<User> = {}): User => ({
  id: 7,
  username: 'dana',
  email: 'dana@example.com',
  full_name: 'Dana',
  is_active: true,
  is_admin: false,
  auth_method: 'oidc',
  oidc_provider: null,
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

/** The wire form: naive UTC, no offset, as the backend sends it. */
const naiveUtc = (d: Date): string => d.toISOString().replace('Z', '')

const minutesFromNow = (minutes: number): Date => new Date(Date.now() + minutes * 60_000)

const renderCard = (u: User, onToggleRelink = vi.fn()): ReturnType<typeof vi.fn> => {
  render(
    <FamilyMemberCard
      member={member}
      user={u}
      currentUserId={1}
      activeAdminCount={2}
      showActions
      onToggleRelink={onToggleRelink}
    />,
  )
  return onToggleRelink
}

describe('FamilyMemberCard SSO relink', () => {
  it('offers the relink to an SSO user', () => {
    renderCard(user())
    expect(screen.getByTitle('familyCard.allowSsoRelink')).toBeInTheDocument()
  })

  it('does not offer it to a local user', () => {
    renderCard(user({ auth_method: 'local' }))
    expect(screen.queryByTitle('familyCard.allowSsoRelink')).not.toBeInTheDocument()
    expect(screen.queryByTitle('familyCard.cancelSsoRelink')).not.toBeInTheDocument()
  })

  it('does not offer it without admin actions', () => {
    render(<FamilyMemberCard member={member} user={user()} onToggleRelink={vi.fn()} />)
    expect(screen.queryByTitle('familyCard.allowSsoRelink')).not.toBeInTheDocument()
  })

  it('a tap on an unarmed account asks to arm it', () => {
    const onToggleRelink = renderCard(user())
    fireEvent.click(screen.getByTitle('familyCard.allowSsoRelink'))
    expect(onToggleRelink).toHaveBeenCalledTimes(1)
    expect(onToggleRelink).toHaveBeenCalledWith(true)
  })

  it('badges an open relink with its closing time, and a tap cancels it', () => {
    const until = minutesFromNow(20)
    const onToggleRelink = renderCard(user({ oidc_relink_until: naiveUtc(until) }))

    expect(screen.getByText(`familyCard.relinkOpenUntil ${formatTime(until, '24h')}`)).toBeInTheDocument()
    fireEvent.click(screen.getByTitle('familyCard.cancelSsoRelink'))
    expect(onToggleRelink).toHaveBeenCalledWith(false)
  })

  it('an expired relink is not open', () => {
    renderCard(user({ oidc_relink_until: naiveUtc(minutesFromNow(-1)) }))
    expect(screen.queryByText(/familyCard\.relinkOpenUntil/)).not.toBeInTheDocument()
    expect(screen.getByTitle('familyCard.allowSsoRelink')).toBeInTheDocument()
  })

  it('an open relink on a local account still shows, and can be cancelled', () => {
    renderCard(user({ auth_method: 'local', oidc_relink_until: naiveUtc(minutesFromNow(20)) }))
    expect(screen.getByText(/familyCard\.relinkOpenUntil/)).toBeInTheDocument()
    expect(screen.getByTitle('familyCard.cancelSsoRelink')).toBeInTheDocument()
  })

  // Both sign-in steps refuse a disabled account before they read the relink,
  // so arming one would only advertise a window nobody can use.
  it('does not offer it to a disabled SSO user', () => {
    renderCard(user({ is_active: false }))
    expect(screen.queryByTitle('familyCard.allowSsoRelink')).not.toBeInTheDocument()
    expect(screen.queryByTitle('familyCard.cancelSsoRelink')).not.toBeInTheDocument()
  })

  it('still lets you cancel one left open on a disabled user', () => {
    const onToggleRelink = renderCard(user({ is_active: false, oidc_relink_until: naiveUtc(minutesFromNow(20)) }))
    fireEvent.click(screen.getByTitle('familyCard.cancelSsoRelink'))
    expect(onToggleRelink).toHaveBeenCalledWith(false)
  })
})

/** A card with every admin action wired, for the actions that aren't the relink. */
const renderActions = (u: User, { currentUserId = 1, activeAdminCount = 2 } = {}): void => {
  render(
    <FamilyMemberCard
      member={member}
      user={u}
      currentUserId={currentUserId}
      activeAdminCount={activeAdminCount}
      showActions
      onToggleActive={vi.fn()}
      onDelete={vi.fn()}
      onResetPassword={vi.fn()}
    />,
  )
}

// Disabling is MyGarage's own kill switch and ends a live session at once.
// The IdP never sets it, so SSO users get it like everyone else.
describe('FamilyMemberCard disable and delete', () => {
  it('offers disable for an active SSO user who is not the last admin', () => {
    renderActions(user())
    expect(screen.getByTitle('familyCard.disableUser')).toBeInTheDocument()
  })

  it('offers enable for a disabled SSO user', () => {
    renderActions(user({ is_active: false }))
    expect(screen.getByTitle('familyCard.enableUser')).toBeInTheDocument()
  })

  it.each(['local', 'oidc'] as const)('offers no disable for the last active admin (%s)', (authMethod) => {
    renderActions(user({ auth_method: authMethod, is_admin: true }), { activeAdminCount: 1 })
    expect(screen.queryByTitle('familyCard.disableUser')).not.toBeInTheDocument()
  })

  // One tap would lock you out mid-session. Edit User still lets you do it on purpose.
  it.each(['local', 'oidc'] as const)('offers no disable on your own card (%s)', (authMethod) => {
    renderActions(user({ auth_method: authMethod, is_admin: true }), { currentUserId: 7 })
    expect(screen.queryByTitle('familyCard.disableUser')).not.toBeInTheDocument()
  })

  it("offers disable on another admin's card", () => {
    renderActions(user({ is_admin: true }), { currentUserId: 1 })
    expect(screen.getByTitle('familyCard.disableUser')).toBeInTheDocument()
  })

  it('offers delete for an SSO user who is not you', () => {
    renderActions(user())
    expect(screen.getByTitle('familyCard.deleteUser')).toBeInTheDocument()
  })

  it.each(['local', 'oidc'] as const)('offers no delete on your own card (%s)', (authMethod) => {
    renderActions(user({ auth_method: authMethod }), { currentUserId: 7 })
    expect(screen.queryByTitle('familyCard.deleteUser')).not.toBeInTheDocument()
  })

  it('offers a password reset to a local user', () => {
    renderActions(user({ auth_method: 'local' }))
    expect(screen.getByTitle('familyCard.resetPassword')).toBeInTheDocument()
  })

  // The backend refuses a password reset for SSO users, so the card doesn't offer one.
  it('offers no password reset to an SSO user', () => {
    renderActions(user())
    expect(screen.queryByTitle('familyCard.resetPassword')).not.toBeInTheDocument()
  })
})

/**
 * A click anywhere on the header toggles, but only the chevron is a button,
 * so the admin actions aren't nested inside one (issue #179, P2E1). jsdom pins
 * the handlers only: a click that ends a text selection doesn't toggle, and a
 * click or key on an action belongs to that action. Whether the name is
 * selectable on a phone is the E2E half.
 */
describe('FamilyMemberCard header', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  const renderWithEdit = (): ReturnType<typeof vi.fn> => {
    const onEdit = vi.fn()
    render(
      <FamilyMemberCard
        member={member}
        user={user({ auth_method: 'local' })}
        currentUserId={1}
        activeAdminCount={2}
        showActions
        onEdit={onEdit}
      />,
    )
    return onEdit
  }

  // The expanded panel is the only place this text shows (no vehicles).
  const panelIsOpen = (): boolean => screen.queryByText('familyCard.noVehicles') !== null

  it('ending a selection in the header does not toggle the panel', () => {
    // The click that lets go of a selection mustn't toggle.
    renderWithEdit()
    vi.spyOn(window, 'getSelection').mockReturnValue({
      isCollapsed: false,
      toString: () => 'dana',
    } as unknown as Selection)

    fireEvent.click(screen.getByText('@dana'))
    expect(panelIsOpen()).toBe(false)

    // Selection gone, a plain click still toggles.
    vi.mocked(window.getSelection).mockRestore()
    fireEvent.click(screen.getByText('@dana'))
    expect(panelIsOpen()).toBe(true)
  })

  it('Enter on a header action button (Edit) runs it and does not toggle the panel', async () => {
    // The old role=button header caught the bubbled Enter, ate it and toggled.
    const userEv = userEvent.setup()
    const onEdit = renderWithEdit()

    screen.getByTitle('familyCard.editUser').focus()
    await userEv.keyboard('{Enter}')

    expect(onEdit).toHaveBeenCalledTimes(1)
    expect(panelIsOpen()).toBe(false)
  })

  it('Space on a header action button (Edit) runs it and does not toggle the panel', async () => {
    // Same for Space: the click it makes on keyup is the button's own.
    const userEv = userEvent.setup()
    const onEdit = renderWithEdit()

    screen.getByTitle('familyCard.editUser').focus()
    await userEv.keyboard(' ')

    expect(onEdit).toHaveBeenCalledTimes(1)
    expect(panelIsOpen()).toBe(false)
  })

  // The chevron is the disclosure button now, named by the member (P2E1).
  const chevron = (): HTMLElement => screen.getByRole('button', { name: 'Dana' })

  it('Enter and Space on the chevron toggle the panel and say so', async () => {
    const userEv = userEvent.setup()
    renderWithEdit()
    expect(chevron()).toHaveAttribute('aria-expanded', 'false')

    chevron().focus()
    await userEv.keyboard('{Enter}')
    expect(panelIsOpen()).toBe(true)
    expect(chevron()).toHaveAttribute('aria-expanded', 'true')
    await userEv.keyboard(' ')
    expect(panelIsOpen()).toBe(false)
    expect(chevron()).toHaveAttribute('aria-expanded', 'false')
  })

  it('a click on an action button does not toggle the panel', () => {
    const onEdit = renderWithEdit()
    fireEvent.click(screen.getByRole('button', { name: 'familyCard.editUser: Dana' }))
    expect(onEdit).toHaveBeenCalledTimes(1)
    expect(panelIsOpen()).toBe(false)
  })

  it('no button sits inside another button', () => {
    // axe nested-interactive: the header was a role=button around up to 8 real ones.
    renderWithEdit()
    for (const button of screen.getAllByRole('button')) {
      expect(within(button).queryAllByRole('button')).toHaveLength(0)
    }
  })
})

describe('FamilyMemberCard action names say whose card it is', () => {
  it('every admin action names the member', () => {
    render(
      <FamilyMemberCard
        member={member}
        user={user({ auth_method: 'local' })}
        currentUserId={1}
        activeAdminCount={2}
        showActions
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onToggleActive={vi.fn()}
        onToggleDashboard={vi.fn()}
        onResetPassword={vi.fn()}
        onMoveUp={vi.fn()}
        onMoveDown={vi.fn()}
        canMoveDown
      />,
    )
    for (const action of [
      'familyCard.hideFromDashboard',
      'familyCard.editUser',
      'familyCard.resetPassword',
      'familyCard.disableUser',
      'familyCard.deleteUser',
      'familyCard.moveUp',
      'familyCard.moveDown',
    ]) {
      expect(screen.getByRole('button', { name: `${action}: Dana` })).toBeInTheDocument()
    }
  })

  it('the relink button names the member too', () => {
    renderCard(user())
    expect(screen.getByRole('button', { name: 'familyCard.allowSsoRelink: Dana' })).toBeInTheDocument()
  })

  it('the shipped English starts with the action, so the tooltip text is in the name', () => {
    expect(commonEn.familyCard.actionFor.startsWith('{{action}}')).toBe(true)
  })
})
