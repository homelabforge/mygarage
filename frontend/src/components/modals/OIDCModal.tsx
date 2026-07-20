import { useTranslation } from 'react-i18next'
import { useState } from 'react'
import { Shield, Info, CheckCircle, AlertCircle, Eye, EyeOff, Loader } from 'lucide-react'
import api from '@/services/api'
import { withBase } from '@/utils/basePath'
import FormModalWrapper from '../FormModalWrapper'

/** Identity providers known to work with MyGarage. Brand names — never translated. */
const SUPPORTED_PROVIDERS = [
  'Authentik',
  'Keycloak',
  'Auth0',
  'Okta',
  'Azure AD / Entra ID',
  'Google Workspace',
]

/** OIDC scope literals — protocol values, never translated. */
const DEFAULT_SCOPES = 'openid profile email'

/** Discovery path the backend appends to the issuer URL itself. */
const DISCOVERY_PATH = '/.well-known/openid-configuration'

/** Example issuer URL shown in the field placeholder and hint. */
const EXAMPLE_ISSUER_URL = 'https://rauthy.example.com/auth/v1'

interface OIDCFormData {
  oidc_provider_name: string
  oidc_issuer_url: string
  oidc_client_id: string
  oidc_client_secret: string
  oidc_scopes: string
  oidc_auto_create_users: string
  oidc_admin_group: string
  oidc_username_claim: string
  oidc_email_claim: string
  oidc_full_name_claim: string
}

interface OIDCModalProps {
  isOpen: boolean
  onClose: () => void
  formData: OIDCFormData
  onFormDataChange: (data: Partial<OIDCFormData>) => void
}

export default function OIDCModal({
  isOpen,
  onClose,
  formData,
  onFormDataChange,
}: OIDCModalProps) {
  const { t } = useTranslation('forms')
  const [oidcTestLoading, setOidcTestLoading] = useState(false)
  const [oidcTestResult, setOidcTestResult] = useState<{
    ok: boolean
    issuer?: string
    algorithms_supported?: string[]
    error?: string
    detail?: string
  } | null>(null)
  const [showClientSecret, setShowClientSecret] = useState(false)
  const [copiedCallback, setCopiedCallback] = useState(false)

  const callbackUrl = `${window.location.origin}${withBase('/api/auth/oidc/callback')}`

  // Handle OIDC test connection. Returns canonical {ok, error, detail, issuer, algorithms_supported}.
  const handleOIDCTest = async () => {
    setOidcTestLoading(true)
    setOidcTestResult(null)

    try {
      const response = await api.post('/auth/oidc/test', {
        issuer_url: formData.oidc_issuer_url,
        client_id: formData.oidc_client_id,
        client_secret: formData.oidc_client_secret,
      })
      const data = response.data as {
        ok: boolean
        issuer?: string
        algorithms_supported?: string[]
        error?: string
        detail?: string
      }
      setOidcTestResult(data)
    } catch (error) {
      const apiError = error as { response?: { data?: { detail?: string } } }
      setOidcTestResult({
        ok: false,
        error: 'request_failed',
        detail: apiError.response?.data?.detail || t('modal.oidc.testEndpointError'),
      })
    } finally {
      setOidcTestLoading(false)
    }
  }

  const handleCopyCallback = async () => {
    try {
      await navigator.clipboard.writeText(callbackUrl)
      setCopiedCallback(true)
      setTimeout(() => setCopiedCallback(false), 1500)
    } catch {
      // Clipboard unavailable — user can still copy manually.
    }
  }

  const handleClose = () => {
    setOidcTestResult(null)
    onClose()
  }

  return (
    <FormModalWrapper
      title={t('modal.oidcAuth')}
      onClose={handleClose}
      isOpen={isOpen}
      icon={<Shield className="w-6 h-6 text-primary" />}
      footer={
        <div className="flex justify-end">
          <button
            onClick={handleClose}
            className="px-4 py-2 text-sm font-medium text-garage-text bg-garage-bg border border-garage-border rounded-lg hover:bg-garage-surface-light transition-colors"
          >
            {t('modal.oidc.close')}
          </button>
        </div>
      }
    >
      <div className="p-6 space-y-4">
          {/* OIDC Info Box */}
          <div className="p-4 bg-primary/10 border border-primary/30 rounded-lg">
            <div className="flex items-start gap-3">
              <Info className="w-5 h-5 text-primary flex-shrink-0 mt-0.5" />
              <div className="flex-1">
                <strong className="text-sm font-semibold text-garage-text">{t('modal.oidc.infoTitle')}</strong>
                <div className="text-sm text-garage-text space-y-2 mt-2">
                  <p>{t('modal.oidc.infoDesc')}</p>
                  <ul className="list-disc list-inside ml-2 text-xs space-y-1 text-garage-text-muted">
                    {SUPPORTED_PROVIDERS.map((provider) => (
                      <li key={provider}>{provider}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          </div>

          {/* OIDC Configuration Form */}
          <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
            <div className="space-y-4">
              <h3 className="text-sm font-semibold text-garage-text">{t('modal.oidcConfiguration')}</h3>

              {/* Provider Name */}
              <div>
                <label htmlFor="oidc-provider-name" className="block text-xs font-medium text-garage-text mb-1.5">
                  {t('modal.oidc.providerName')}
                </label>
                <input
                  id="oidc-provider-name"
                  type="text"
                  value={formData.oidc_provider_name}
                  onChange={(e) => onFormDataChange({ oidc_provider_name: e.target.value })}
                  className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                  placeholder={t('modal.oidc.providerNamePlaceholder')}
                />
                <p className="text-xs text-garage-text-muted mt-1">{t('modal.providerNameHint')}</p>
              </div>

              {/* Issuer URL */}
              <div>
                <label htmlFor="oidc-issuer-url" className="block text-xs font-medium text-garage-text mb-1.5">
                  {t('modal.oidc.issuerUrl')} <span className="text-danger-500">*</span>
                </label>
                <input
                  id="oidc-issuer-url"
                  type="url"
                  value={formData.oidc_issuer_url}
                  onChange={(e) => onFormDataChange({ oidc_issuer_url: e.target.value })}
                  className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                  placeholder={EXAMPLE_ISSUER_URL}
                />
                <p className="text-xs text-garage-text-muted mt-1">
                  {t('modal.oidc.issuerUrlHint', {
                    example: EXAMPLE_ISSUER_URL,
                    discovery: DISCOVERY_PATH,
                  })}
                </p>
              </div>

              {/* Client ID */}
              <div>
                <label htmlFor="oidc-client-id" className="block text-xs font-medium text-garage-text mb-1.5">
                  {t('modal.oidc.clientId')} <span className="text-danger-500">*</span>
                </label>
                <input
                  id="oidc-client-id"
                  type="text"
                  value={formData.oidc_client_id}
                  onChange={(e) => onFormDataChange({ oidc_client_id: e.target.value })}
                  className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                  placeholder={t('modal.oidc.clientIdPlaceholder')}
                />
              </div>

              {/* Client Secret */}
              <div>
                <label htmlFor="oidc-client-secret" className="block text-xs font-medium text-garage-text mb-1.5">
                  {t('modal.oidc.clientSecret')} <span className="text-danger-500">*</span>
                </label>
                <div className="relative">
                  <input
                    id="oidc-client-secret"
                    type={showClientSecret ? 'text' : 'password'}
                    value={formData.oidc_client_secret}
                    onChange={(e) => onFormDataChange({ oidc_client_secret: e.target.value })}
                    className="w-full px-3 py-2 pr-10 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                    placeholder={t('modal.oidc.clientSecretPlaceholder')}
                  />
                  <button
                    type="button"
                    onClick={() => setShowClientSecret(!showClientSecret)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-garage-text-muted hover:text-garage-text transition-colors"
                    aria-label={showClientSecret ? t('modal.oidc.hideSecret') : t('modal.oidc.showSecret')}
                  >
                    {showClientSecret ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                <p className="text-xs text-garage-text-muted mt-1">{t('modal.oidc.clientSecretHint')}</p>
              </div>

              {/* Callback URL (Read-only, computed from window.location) */}
              <div>
                <label htmlFor="oidc-redirect-uri" className="block text-xs font-medium text-garage-text mb-1.5">
                  {t('modal.oidc.callbackUrl')}
                </label>
                <div className="flex gap-2">
                  <input
                    id="oidc-redirect-uri"
                    type="text"
                    value={callbackUrl}
                    readOnly
                    className="flex-1 px-3 py-2 bg-garage-surface/50 border border-garage-border rounded-lg text-sm text-garage-text-muted font-mono cursor-default"
                  />
                  <button
                    type="button"
                    onClick={handleCopyCallback}
                    className="px-3 py-2 bg-garage-surface border border-garage-border text-garage-text text-xs rounded-lg hover:bg-garage-bg transition-colors"
                  >
                    {copiedCallback ? t('modal.oidc.copied') : t('modal.oidc.copy')}
                  </button>
                </div>
                <p className="text-xs text-garage-text-muted mt-1">
                  {t('modal.oidc.callbackUrlHint')}
                </p>
              </div>

              {/* OIDC protocol constants */}
              <div className="grid grid-cols-2 gap-3 text-xs text-garage-text-muted bg-garage-surface/40 border border-garage-border rounded-lg p-3">
                <div>
                  <span className="font-medium text-garage-text">{t('modal.oidc.tokenAlgorithmsLabel')}:</span>{' '}
                  {t('modal.oidc.tokenAlgorithmsDesc')}
                </div>
                <div>
                  <span className="font-medium text-garage-text">{t('modal.oidc.pkceLabel')}:</span>{' '}
                  {t('modal.oidc.pkceDesc')}
                </div>
              </div>

              {/* Scopes */}
              <div>
                <label htmlFor="oidc-scopes" className="block text-xs font-medium text-garage-text mb-1.5">
                  {t('modal.oidc.scopes')}
                </label>
                <input
                  id="oidc-scopes"
                  type="text"
                  value={formData.oidc_scopes}
                  onChange={(e) => onFormDataChange({ oidc_scopes: e.target.value })}
                  className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                  placeholder={DEFAULT_SCOPES}
                />
                <p className="text-xs text-garage-text-muted mt-1">{t('modal.scopesHint')}</p>
              </div>

              {/* Auto-create Users */}
              <div className="flex items-start gap-3">
                <input
                  id="oidc-auto-create"
                  type="checkbox"
                  checked={formData.oidc_auto_create_users === 'true'}
                  onChange={(e) => onFormDataChange({ oidc_auto_create_users: e.target.checked ? 'true' : 'false' })}
                  className="mt-1 w-4 h-4 text-primary bg-garage-surface border-garage-border rounded focus:ring-2 focus:ring-primary"
                />
                <div className="flex-1">
                  <label htmlFor="oidc-auto-create" className="text-xs font-medium text-garage-text cursor-pointer">
                    {t('modal.oidc.autoCreateUsers')}
                  </label>
                  <p className="text-xs text-garage-text-muted mt-0.5">
                    {t('modal.oidc.autoCreateUsersDesc')}
                  </p>
                </div>
              </div>

              {/* Admin Group */}
              <div>
                <label htmlFor="oidc-admin-group" className="block text-xs font-medium text-garage-text mb-1.5">
                  {t('modal.oidc.adminGroup')}
                </label>
                <input
                  id="oidc-admin-group"
                  type="text"
                  value={formData.oidc_admin_group}
                  onChange={(e) => onFormDataChange({ oidc_admin_group: e.target.value })}
                  className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                  placeholder="mygarage-admins"
                />
                <p className="text-xs text-garage-text-muted mt-1">
                  {t('modal.oidc.adminGroupDesc')}
                </p>
              </div>

              {/* Claim Mappings */}
              <div className="space-y-3 pt-2 border-t border-garage-border">
                <h4 className="text-xs font-semibold text-garage-text">{t('modal.claimMappings')}</h4>

                {/* Username Claim */}
                <div>
                  <label htmlFor="oidc-username-claim" className="block text-xs font-medium text-garage-text mb-1.5">
                    {t('modal.oidc.usernameClaim')}
                  </label>
                  <select
                    id="oidc-username-claim"
                    value={formData.oidc_username_claim}
                    onChange={(e) => onFormDataChange({ oidc_username_claim: e.target.value })}
                    className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                  >
                    <option value="preferred_username">preferred_username</option>
                    <option value="email">email</option>
                    <option value="sub">sub</option>
                  </select>
                </div>

                {/* Email Claim */}
                <div>
                  <label htmlFor="oidc-email-claim" className="block text-xs font-medium text-garage-text mb-1.5">
                    {t('modal.oidc.emailClaim')}
                  </label>
                  <select
                    id="oidc-email-claim"
                    value={formData.oidc_email_claim}
                    onChange={(e) => onFormDataChange({ oidc_email_claim: e.target.value })}
                    className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                  >
                    <option value="email">email</option>
                    <option value="mail">mail</option>
                  </select>
                </div>

                {/* Full Name Claim */}
                <div>
                  <label htmlFor="oidc-full-name-claim" className="block text-xs font-medium text-garage-text mb-1.5">
                    {t('modal.oidc.fullNameClaim')}
                  </label>
                  <select
                    id="oidc-full-name-claim"
                    value={formData.oidc_full_name_claim}
                    onChange={(e) => onFormDataChange({ oidc_full_name_claim: e.target.value })}
                    className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                  >
                    <option value="name">name</option>
                    <option value="given_name">given_name + family_name</option>
                  </select>
                </div>
              </div>

              {/* Test Connection Result (canonical {ok, error, detail, issuer, algorithms_supported}) */}
              {oidcTestResult && (
                <div className={`p-3 rounded-lg border text-sm ${
                  oidcTestResult.ok
                    ? 'bg-success-500/10 border-success-500'
                    : 'bg-danger-500/10 border-danger-500'
                }`}>
                  <div className="flex items-start gap-2">
                    {oidcTestResult.ok ? (
                      <CheckCircle className="w-4 h-4 text-success-500 flex-shrink-0 mt-0.5" />
                    ) : (
                      <AlertCircle className="w-4 h-4 text-danger-500 flex-shrink-0 mt-0.5" />
                    )}
                    <div className="flex-1">
                      {oidcTestResult.ok ? (
                        <>
                          <div className="font-medium text-success-500">{t('modal.oidc.connectionSuccessful')}</div>
                          <div className="mt-1 text-xs text-garage-text-muted">
                            <div>{t('modal.oidc.issuerLabel')}: <span className="font-mono">{oidcTestResult.issuer}</span></div>
                            {oidcTestResult.algorithms_supported && oidcTestResult.algorithms_supported.length > 0 && (
                              <div>{t('modal.oidc.algorithmsLabel')}: <span className="font-mono">{oidcTestResult.algorithms_supported.join(', ')}</span></div>
                            )}
                          </div>
                        </>
                      ) : (
                        <>
                          <div className="font-medium text-danger-500 mb-1">{t('modal.connectionFailed')}</div>
                          <div className="text-xs text-danger-500">
                            <div>{t('modal.oidc.codeLabel')}: <span className="font-mono">{oidcTestResult.error}</span></div>
                            {oidcTestResult.detail && <div className="mt-0.5">{oidcTestResult.detail}</div>}
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* Test Connection Button */}
              <button
                type="button"
                onClick={handleOIDCTest}
                disabled={oidcTestLoading || !formData.oidc_issuer_url || !formData.oidc_client_id || !formData.oidc_client_secret}
                className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-garage-surface border border-garage-border text-garage-text text-sm font-medium rounded-lg hover:bg-garage-bg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {oidcTestLoading ? (
                  <>
                    <Loader className="w-4 h-4 animate-spin" />
                    {t('modal.testing')}
                  </>
                ) : (
                  <>
                    <CheckCircle className="w-4 h-4" />
                    {t('modal.oidc.testConnection')}
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Authentik Setup Instructions */}
          <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
            <div className="flex items-start gap-3">
              <Info className="w-5 h-5 text-primary flex-shrink-0 mt-0.5" />
              <div className="flex-1">
                <h4 className="text-sm font-semibold text-garage-text mb-2">{t('modal.authentikSetupGuide')}</h4>
                <ol className="list-decimal list-inside space-y-1.5 text-xs text-garage-text-muted">
                  <li>{t('modal.oidc.setupStep1')}</li>
                  <li>{t('modal.oidc.setupStep2')}</li>
                  <li>{t('modal.oidc.setupStep3')}</li>
                  <li>{t('modal.oidc.setupStep4')}</li>
                  <li>{t('modal.oidc.setupStep5')}</li>
                  <li>{t('modal.oidc.setupStep6')}</li>
                  <li>{t('modal.oidc.setupStep7')}</li>
                </ol>
              </div>
            </div>
          </div>
      </div>
    </FormModalWrapper>
  )
}
