import type { ComponentProps } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent, waitFor, within } from '@testing-library/react'
import { render } from '../../../__tests__/test-utils'
import { withBase } from '@/utils/basePath'
import formsEn from '../../../locales/en/forms.json'
import OIDCModal from '../OIDCModal'

type OIDCFormData = ComponentProps<typeof OIDCModal>['formData']

const FORM: OIDCFormData = {
  oidc_provider_name: 'Rauthy',
  oidc_issuer_url: 'https://auth.example.com',
  oidc_client_id: 'client-id',
  oidc_client_secret: '********',
  oidc_redirect_uri: '',
  oidc_scopes: 'openid profile email',
  oidc_auto_create_users: 'true',
  oidc_admin_group: '',
  oidc_username_claim: 'preferred_username',
  oidc_email_claim: 'email',
  oidc_full_name_claim: 'name',
}

const PINNED = 'https://garage.example.com/api/auth/oidc/callback'
// What the modal builds from this page's address when nothing is pinned.
const COMPUTED = `${window.location.origin}${withBase('/api/auth/oidc/callback')}`

const writeText = vi.fn()
const onFormDataChange = vi.fn()

function renderModal(formData: Partial<OIDCFormData> = {}): void {
  render(
    <OIDCModal
      isOpen
      onClose={vi.fn()}
      formData={{ ...FORM, ...formData }}
      onFormDataChange={onFormDataChange}
    />,
  )
}

const callbackInput = (): HTMLInputElement =>
  screen.getByLabelText('modal.oidc.callbackUrl') as HTMLInputElement

describe('OIDCModal: the Callback URL pins oidc_redirect_uri', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    writeText.mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
  })

  it('is an editable field that reports what is typed', () => {
    renderModal()

    expect(callbackInput()).not.toHaveAttribute('readonly')
    fireEvent.change(callbackInput(), { target: { value: PINNED } })
    expect(onFormDataChange).toHaveBeenCalledWith({ oidc_redirect_uri: PINNED })
  })

  it('shows the pinned value, with the computed callback as its placeholder', () => {
    renderModal({ oidc_redirect_uri: PINNED })

    expect(callbackInput().value).toBe(PINNED)
    expect(callbackInput().placeholder).toBe(COMPUTED)
  })

  it('Copy copies the pinned URL when one is set', async () => {
    renderModal({ oidc_redirect_uri: `  ${PINNED}  ` })

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
