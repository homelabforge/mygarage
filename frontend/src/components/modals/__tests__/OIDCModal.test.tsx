import type { ComponentProps } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent, waitFor, within } from '@testing-library/react'
import { render } from '../../../__tests__/test-utils'
import { withBase } from '@/utils/basePath'
import api from '@/services/api'
import { toast } from 'sonner'
import formsEn from '../../../locales/en/forms.json'
import OIDCModal from '../OIDCModal'

vi.mock('@/services/api', () => ({ default: { put: vi.fn(), post: vi.fn(), get: vi.fn() } }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

type OIDCAdminConfig = ComponentProps<typeof OIDCModal>['config']

const CONFIG: OIDCAdminConfig = {
  enabled: false,
  provider_name: 'Rauthy',
  issuer_url: 'https://auth.example.com',
  client_id: 'client-id',
  client_secret: '********',
  redirect_uri: '',
  scopes: 'openid profile email',
  auto_create_users: true,
  admin_group: '',
  username_claim: 'preferred_username',
  email_claim: 'email',
  full_name_claim: 'name',
}

const PINNED = 'https://garage.example.com/api/auth/oidc/callback'
// What the modal builds from this page's address when nothing is pinned.
const COMPUTED = `${window.location.origin}${withBase('/api/auth/oidc/callback')}`

const writeText = vi.fn()
const onSaved = vi.fn()
const onClose = vi.fn()
const mockedPut = vi.mocked(api.put)

function renderModal(config: Partial<OIDCAdminConfig> = {}): void {
  render(<OIDCModal isOpen onClose={onClose} config={{ ...CONFIG, ...config }} onSaved={onSaved} />)
}

const callbackInput = (): HTMLInputElement =>
  screen.getByLabelText('modal.oidc.callbackUrl') as HTMLInputElement

describe('OIDCModal: the Callback URL pins oidc_redirect_uri', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    writeText.mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
  })

  it('is an editable field that holds what is typed, and writes nothing on its own', () => {
    renderModal()

    expect(callbackInput()).not.toHaveAttribute('readonly')
    fireEvent.change(callbackInput(), { target: { value: PINNED } })
    expect(callbackInput().value).toBe(PINNED)
    expect(mockedPut).not.toHaveBeenCalled()
  })

  it('shows the pinned value, with the computed callback as its placeholder', () => {
    renderModal({ redirect_uri: PINNED })

    expect(callbackInput().value).toBe(PINNED)
    expect(callbackInput().placeholder).toBe(COMPUTED)
  })

  it('Copy copies the pinned URL when one is set', async () => {
    renderModal({ redirect_uri: `  ${PINNED}  ` })

    fireEvent.click(screen.getByRole('button', { name: 'modal.oidc.copy' }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(PINNED))
  })

  // Control: blank was the only case before, and it still copies the computed one.
  it('Copy copies the computed URL when the field is blank', async () => {
    renderModal()

    fireEvent.click(screen.getByRole('button', { name: 'modal.oidc.copy' }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(COMPUTED))
  })
})

describe('OIDCModal: Save writes the draft once', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('PUTs the edited config, then reports and closes', async () => {
    mockedPut.mockResolvedValue({ data: {} })
    renderModal()
    fireEvent.change(callbackInput(), { target: { value: PINNED } })

    fireEvent.click(screen.getByRole('button', { name: 'modal.oidc.save' }))

    await waitFor(() =>
      expect(mockedPut).toHaveBeenCalledWith('/auth/oidc/config/admin', { ...CONFIG, redirect_uri: PINNED }),
    )
    expect(onSaved).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(toast.success).toHaveBeenCalledWith('modal.oidc.saved')
  })

  it('keeps the draft and shows the field error when the Callback URL is refused', async () => {
    mockedPut.mockRejectedValue({
      isAxiosError: true,
      response: { status: 422, data: { detail: 'redirect_uri must be an absolute http(s) URL with no #fragment' } },
    })
    renderModal()
    fireEvent.change(callbackInput(), { target: { value: 'https:/half' } })

    fireEvent.click(screen.getByRole('button', { name: 'modal.oidc.save' }))

    expect(await screen.findByText('modal.oidc.redirectUriInvalid')).toBeInTheDocument()
    expect(callbackInput().value).toBe('https:/half')
    expect(onSaved).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('Cancel throws the draft away', () => {
    renderModal()
    fireEvent.change(callbackInput(), { target: { value: PINNED } })

    fireEvent.click(screen.getByRole('button', { name: 'modal.oidc.cancel' }))

    expect(mockedPut).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})

describe('OIDCModal: the setup guide names no provider', () => {
  it('heads the guide generically, with the new step 1 and step 3 keys', () => {
    renderModal()

    expect(screen.queryByText('modal.authentikSetupGuide')).not.toBeInTheDocument()
    const heading = screen.getByRole('heading', { name: 'modal.oidcSetupGuide' })
    const steps = within(heading.parentElement as HTMLElement)
      .getAllByRole('listitem')
      .map((step) => step.textContent)
    expect(steps).toEqual([
      'modal.oidc.setupCreateClient',
      'modal.oidc.setupStep2',
      'modal.oidc.setupRegisterCallback',
      'modal.oidc.setupStep4',
      'modal.oidc.setupStep5',
      'modal.oidc.setupStep6',
      'modal.oidc.setupStep7',
    ])
  })

  it('lists Rauthy as a supported provider, next to Keycloak', () => {
    renderModal()

    const providers = within(screen.getByText('Keycloak').closest('ul') as HTMLElement)
      .getAllByRole('listitem')
      .map((provider) => provider.textContent)
    expect(providers).toEqual([
      'Authentik',
      'Keycloak',
      'Rauthy',
      'Auth0',
      'Okta',
      'Azure AD / Entra ID',
      'Google Workspace',
    ])
  })

  // The mock renders keys, so only the en bundle can show what users actually read.
  it('ships no Authentik wording in the English guide copy', () => {
    const modal: { oidc: Record<string, string>; oidcSetupGuide?: string } = formsEn.modal
    const copy: Record<string, string | undefined> = {
      ...modal.oidc,
      oidcSetupGuide: modal.oidcSetupGuide,
    }

    // The placeholder is an example list, and Authentik is still supported.
    const named = Object.keys(copy).filter(
      (key) => key !== 'providerNamePlaceholder' && /authentik/i.test(copy[key] ?? ''),
    )
    expect(named).toEqual([])

    // The mock renders a key whether en has it or not, so check the new ones are really there.
    const newKeys = ['oidcSetupGuide', 'setupCreateClient', 'setupRegisterCallback']
    const missing = newKeys.filter((key) => !copy[key]?.trim())
    expect(missing).toEqual([])
  })
})
