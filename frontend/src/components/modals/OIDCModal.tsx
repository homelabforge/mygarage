import { useState } from 'react'
import { X, Shield, Info, CheckCircle, AlertCircle, Eye, EyeOff, Loader } from 'lucide-react'
import api from '@/services/api'

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
  const [oidcTestLoading, setOidcTestLoading] = useState(false)
  const [oidcTestResult, setOidcTestResult] = useState<{
    success: boolean
    message?: string
    metadata?: object
    errors?: string[]
  } | null>(null)
  const [showClientSecret, setShowClientSecret] = useState(false)

  // Handle OIDC test connection
  const handleOIDCTest = async () => {
    setOidcTestLoading(true)
    setOidcTestResult(null)

    try {
      const response = await api.post('/auth/oidc/test', {
        issuer_url: formData.oidc_issuer_url,
        client_id: formData.oidc_client_id,
        client_secret: formData.oidc_client_secret,
      })

      setOidcTestResult({
        success: true,
        message: 'Connection successful! Provider metadata retrieved.',
        metadata: response.data.metadata || {},
      })
    } catch (error) {
      const apiError = error as { response?: { data?: { errors?: string[], detail?: string } } }
      setOidcTestResult({
        success: false,
        errors: apiError.response?.data?.errors || [apiError.response?.data?.detail || 'Failed to connect to OIDC provider'],
      })
    } finally {
      setOidcTestLoading(false)
    }
  }

  const handleClose = () => {
    setOidcTestResult(null)
    onClose()
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-garage-surface border border-garage-border rounded-lg max-w-2xl w-full max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="p-6 border-b border-garage-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Shield className="w-6 h-6 text-primary" />
            <h2 className="text-xl font-bold text-garage-text">OIDC Authentication</h2>
          </div>
          <button onClick={handleClose} className="p-2 hover:bg-garage-muted rounded-lg transition-colors">
            <X className="w-5 h-5 text-garage-text-muted" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {/* OIDC Info Box */}
          <div className="p-4 bg-primary/10 border border-primary/30 rounded-lg">
            <div className="flex items-start gap-3">
              <Info className="w-5 h-5 text-primary flex-shrink-0 mt-0.5" />
              <div className="flex-1">
                <strong className="text-sm font-semibold text-garage-text">OpenID Connect (OIDC) Authentication</strong>
                <div className="text-sm text-garage-text space-y-2 mt-2">
                  <p>
                    Configure single sign-on with your identity provider. Supported providers include:
                  </p>
                  <ul className="list-disc list-inside ml-2 text-xs space-y-1 text-garage-text-muted">
                    <li>Authentik</li>
                    <li>Keycloak</li>
                    <li>Auth0</li>
                    <li>Okta</li>
                    <li>Azure AD / Entra ID</li>
                    <li>Google Workspace</li>
                  </ul>
                </div>
              </div>
            </div>
          </div>

          {/* OIDC Configuration Form */}
          <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
            <div className="space-y-4">
              <h3 className="text-sm font-semibold text-garage-text">OIDC Configuration</h3>

              {/* Provider Name */}
              <div>
                <label htmlFor="oidc-provider-name" className="block text-xs font-medium text-garage-text mb-1.5">
                  Provider Name
                </label>
                <input
                  id="oidc-provider-name"
                  type="text"
                  value={formData.oidc_provider_name}
                  onChange={(e) => onFormDataChange({ oidc_provider_name: e.target.value })}
                  className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                  placeholder="e.g., Authentik, Keycloak"
                />
                <p className="text-xs text-garage-text-muted mt-1">Display name for the SSO provider</p>
              </div>

              {/* Issuer URL */}
              <div>
                <label htmlFor="oidc-issuer-url" className="block text-xs font-medium text-garage-text mb-1.5">
                  Issuer URL <span className="text-danger-500">*</span>
                </label>
                <input
                  id="oidc-issuer-url"
                  type="url"
                  value={formData.oidc_issuer_url}
                  onChange={(e) => onFormDataChange({ oidc_issuer_url: e.target.value })}
                  className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                  placeholder="https://auth.example.com/application/o/mygarage/"
                />
                <p className="text-xs text-garage-text-muted mt-1">
                  OIDC provider's issuer URL (must end with /.well-known/openid-configuration)
                </p>
              </div>

              {/* Client ID */}
              <div>
                <label htmlFor="oidc-client-id" className="block text-xs font-medium text-garage-text mb-1.5">
                  Client ID <span className="text-danger-500">*</span>
                </label>
                <input
                  id="oidc-client-id"
                  type="text"
                  value={formData.oidc_client_id}
                  onChange={(e) => onFormDataChange({ oidc_client_id: e.target.value })}
                  className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                  placeholder="client-id-from-provider"
                />
              </div>

              {/* Client Secret */}
              <div>
                <label htmlFor="oidc-client-secret" className="block text-xs font-medium text-garage-text mb-1.5">
                  Client Secret <span className="text-danger-500">*</span>
                </label>
                <div className="relative">
                  <input
                    id="oidc-client-secret"
                    type={showClientSecret ? 'text' : 'password'}
                    value={formData.oidc_client_secret}
                    onChange={(e) => onFormDataChange({ oidc_client_secret: e.target.value })}
                    className="w-full px-3 py-2 pr-10 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                    placeholder="client-secret-from-provider"
                  />
                  <button
                    type="button"
                    onClick={() => setShowClientSecret(!showClientSecret)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-garage-text-muted hover:text-garage-text transition-colors"
                    aria-label={showClientSecret ? 'Hide secret' : 'Show secret'}
                  >
                    {showClientSecret ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                <p className="text-xs text-garage-text-muted mt-1">Encrypted and stored securely</p>
              </div>

              {/* Redirect URI (Read-only) */}
              <div>
                <label htmlFor="oidc-redirect-uri" className="block text-xs font-medium text-garage-text mb-1.5">
                  Redirect URI (Configure in provider)
                </label>
                <div className="relative">
                  <input
                    id="oidc-redirect-uri"
                    type="text"
                    value={`${window.location.origin}/api/auth/oidc/callback`}
                    readOnly
                    className="w-full px-3 py-2 bg-garage-surface/50 border border-garage-border rounded-lg text-sm text-garage-text-muted font-mono cursor-default"
                  />
                </div>
                <p className="text-xs text-garage-text-muted mt-1">
                  Copy this URL to your OIDC provider's redirect URI configuration
                </p>
              </div>

              {/* Scopes */}
              <div>
                <label htmlFor="oidc-scopes" className="block text-xs font-medium text-garage-text mb-1.5">
                  Scopes
                </label>
                <input
                  id="oidc-scopes"
                  type="text"
                  value={formData.oidc_scopes}
                  onChange={(e) => onFormDataChange({ oidc_scopes: e.target.value })}
                  className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                  placeholder="openid profile email"
                />
                <p className="text-xs text-garage-text-muted mt-1">Space-separated list of OIDC scopes</p>
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
                    Auto-create users on first login
                  </label>
                  <p className="text-xs text-garage-text-muted mt-0.5">
                    Automatically create new users when they login via SSO for the first time
                  </p>
                </div>
              </div>

              {/* Admin Group */}
              <div>
                <label htmlFor="oidc-admin-group" className="block text-xs font-medium text-garage-text mb-1.5">
                  Admin Group (Optional)
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
                  Users in this group will be granted admin privileges
                </p>
              </div>

              {/* Claim Mappings */}
              <div className="space-y-3 pt-2 border-t border-garage-border">
                <h4 className="text-xs font-semibold text-garage-text">Claim Mappings</h4>

                {/* Username Claim */}
                <div>
                  <label htmlFor="oidc-username-claim" className="block text-xs font-medium text-garage-text mb-1.5">
                    Username Claim
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
                    Email Claim
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
                    Full Name Claim
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

              {/* Test Connection Result */}
              {oidcTestResult && (
                <div className={`p-3 rounded-lg border text-sm ${
                  oidcTestResult.success
                    ? 'bg-success-500/10 border-success-500'
                    : 'bg-danger-500/10 border-danger-500'
                }`}>
                  <div className="flex items-start gap-2">
                    {oidcTestResult.success ? (
                      <CheckCircle className="w-4 h-4 text-success-500 flex-shrink-0 mt-0.5" />
                    ) : (
                      <AlertCircle className="w-4 h-4 text-danger-500 flex-shrink-0 mt-0.5" />
                    )}
                    <div className="flex-1">
                      {oidcTestResult.success ? (
                        <>
                          <div className="font-medium text-success-500">{oidcTestResult.message}</div>
                          {oidcTestResult.metadata && (
                            <pre className="mt-2 text-xs bg-garage-bg p-2 rounded overflow-x-auto text-garage-text">
                              {JSON.stringify(oidcTestResult.metadata, null, 2)}
                            </pre>
                          )}
                        </>
                      ) : (
                        <>
                          <div className="font-medium text-danger-500 mb-1">Connection Failed</div>
                          <ul className="text-xs text-danger-500 space-y-1">
                            {oidcTestResult.errors?.map((err, idx) => (
                              <li key={idx}>• {err}</li>
                            ))}
                          </ul>
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
                    Testing...
                  </>
                ) : (
                  <>
                    <CheckCircle className="w-4 h-4" />
                    Test Connection
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
                <h4 className="text-sm font-semibold text-garage-text mb-2">Authentik Setup Guide</h4>
                <ol className="list-decimal list-inside space-y-1.5 text-xs text-garage-text-muted">
                  <li>In Authentik, create a new OAuth2/OIDC Provider</li>
                  <li>Set Client Type to "Confidential"</li>
                  <li>Copy the Redirect URI shown above to the provider's configuration</li>
                  <li>Configure Scopes: openid, profile, email</li>
                  <li>Copy the Client ID and Client Secret to the fields above</li>
                  <li>Click "Test Connection" to verify configuration</li>
                  <li>Save the settings to enable OIDC authentication</li>
                </ol>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-garage-border flex justify-end">
          <button
            onClick={handleClose}
            className="px-4 py-2 text-sm font-medium text-garage-text bg-garage-bg border border-garage-border rounded-lg hover:bg-garage-muted transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
