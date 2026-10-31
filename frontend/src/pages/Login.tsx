import { useState, useEffect, useMemo } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { resolvePostLoginRoute } from '../utils/postLoginRedirect'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { LogIn, AlertCircle, Loader, Eye, EyeOff, Shield } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { makeLoginSchema, type LoginFormData } from '../schemas/auth'
import { FormError } from '../components/FormError'
import AuthPageLayout from '../components/AuthPageLayout'
import { withBase } from '../utils/basePath'
import { applyServerErrors } from '../hooks/useApiFormErrors'
import { getActionErrorMessage } from '../utils/httpErrorHandler'

// The backend's SSOError values (app/constants/oidc.py), which its SSO redirect
// sends back as ?sso_error=. Anything else is someone's hand-typed URL, so it
// gets the generic sentence and never reaches t().
const SSO_ERROR_CODE_LIST = [
  'account_disabled',
  'email_linked_elsewhere',
  'email_no_password',
  'username_linked_elsewhere',
  'username_no_password',
  'no_account',
  'cancelled',
  'expired',
  'failed',
  'rate_limited',
] as const
type SSOErrorCode = (typeof SSO_ERROR_CODE_LIST)[number]
const SSO_ERROR_CODES: ReadonlySet<string> = new Set(SSO_ERROR_CODE_LIST)

const isSSOErrorCode = (value: string): value is SSOErrorCode => SSO_ERROR_CODES.has(value)

/** The ?sso_error= param as a known code, `failed` for anything else, null when absent. */
function toSSOErrorCode(param: string | null): SSOErrorCode | null {
  if (param === null) return null
  return isSSOErrorCode(param) ? param : 'failed'
}

export default function Login() {
  const { t } = useTranslation('common')
  // Zod bakes its messages in at construction, so the schema is rebuilt when
  // the language changes. Only the resolver depends on it — no fetch, no
  // reset() — so a rebuild can't discard what the user typed.
  const schema = useMemo(() => makeLoginSchema(t), [t])
  const {
    register: registerField,
    handleSubmit,
    formState: { errors, isSubmitting },
    setError: setFieldError,
  } = useForm<LoginFormData>({
    resolver: zodResolver(schema),
  })
  const [error, setError] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [oidcEnabled, setOidcEnabled] = useState(false)
  const [oidcProviderName, setOidcProviderName] = useState('')
  const [oidcLoading, setOidcLoading] = useState(true)
  // When OIDC is enabled, default the password form hidden behind a toggle —
  // SSO is primary. When OIDC is disabled (or the check fails) show the
  // password form immediately since it's the only option.
  const [showPasswordForm, setShowPasswordForm] = useState(false)
  const { login } = useAuth()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  // Read once on mount, since the param is dropped from the URL right after.
  const [ssoError, setSsoError] = useState<SSOErrorCode | null>(() =>
    toSSOErrorCode(searchParams.get('sso_error')),
  )

  // Drop sso_error so a reload doesn't show the same reason again.
  useEffect(() => {
    if (!searchParams.has('sso_error')) return
    const next = new URLSearchParams(searchParams)
    next.delete('sso_error')
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])

  // Spelled out rather than t(`login.ssoError.${code}`): the i18n usage gate
  // only sees literal keys.
  const ssoErrorMessage = (code: SSOErrorCode): string => {
    switch (code) {
      case 'account_disabled':
        return t('login.ssoError.account_disabled')
      case 'email_linked_elsewhere':
        return t('login.ssoError.email_linked_elsewhere')
      case 'email_no_password':
        return t('login.ssoError.email_no_password')
      case 'username_linked_elsewhere':
        return t('login.ssoError.username_linked_elsewhere')
      case 'username_no_password':
        return t('login.ssoError.username_no_password')
      case 'no_account':
        return t('login.ssoError.no_account')
      case 'cancelled':
        return t('login.ssoError.cancelled')
      case 'expired':
        return t('login.ssoError.expired')
      case 'failed':
        return t('login.ssoError.failed')
      case 'rate_limited':
        return t('login.ssoError.rate_limited')
    }
  }
  const bannerError = error || (ssoError ? ssoErrorMessage(ssoError) : '')

  // Check if OIDC is enabled
  useEffect(() => {
    const checkOIDC = async () => {
      try {
        const response = await fetch(withBase('/api/auth/oidc/config'))
        const data = await response.json()
        const enabled = Boolean(data.enabled)
        setOidcEnabled(enabled)
        setOidcProviderName(data.provider_name || 'SSO')
        if (!enabled) setShowPasswordForm(true)
      } catch {
        // OIDC not available, just use regular login
        setOidcEnabled(false)
        setShowPasswordForm(true)
      } finally {
        setOidcLoading(false)
      }
    }
    checkOIDC()
  }, [])

  const onSubmit = async (data: LoginFormData) => {
    setError('')
    setSsoError(null)

    try {
      const user = await login(data.username, data.password)
      navigate(resolvePostLoginRoute(user), { replace: true })
    } catch (err) {
      // attached.length === 0 catches a non-422 failure (network drop, 500):
      // it carries no field problems at all, so `unhandled` alone would stay
      // empty and this banner would never show.
      const { attached, unhandled } = applyServerErrors<LoginFormData>(setFieldError, err, ['username', 'password'])
      if (attached.length === 0 || unhandled.length > 0) {
        setError(getActionErrorMessage(err, t('login.signInAction')))
      }
    }
  }

  const handleSSOLogin = () => {
    window.location.href = withBase('/api/auth/oidc/login')
  }

  return (
    <AuthPageLayout
      subtitle={t('login.subtitle')}
      footerExtra={
        <div className="mt-6 text-center text-sm text-garage-text-muted">
          {t('login.noAccount')}{' '}
          <Link to="/register" className="text-primary hover:underline font-medium">
            {t('login.registerLink')}
          </Link>
        </div>
      }
    >
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
        {/* Error Message */}
        {bannerError && (
          <div role="alert" className="p-4 bg-danger-500/10 border border-danger-500 rounded-lg flex items-start gap-2">
            <AlertCircle className="w-5 h-5 text-danger-500 flex-shrink-0 mt-0.5" />
            <div className="text-sm text-danger-500">{bannerError}</div>
          </div>
        )}

        {/* SSO Button + optional toggle to reveal the password form */}
        {!oidcLoading && oidcEnabled && (
          <>
            <button
              type="button"
              onClick={handleSSOLogin}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 btn-primary-auth font-medium rounded-lg transition-colors"
            >
              <Shield className="w-5 h-5" />
              {t('login.oidcSignIn', { provider: oidcProviderName })}
            </button>

            {!showPasswordForm && (
              <button
                type="button"
                onClick={() => setShowPasswordForm(true)}
                className="relative w-full text-center text-sm text-garage-text-muted hover:text-garage-text transition-colors py-2"
              >
                <span className="absolute inset-0 flex items-center" aria-hidden="true">
                  <div className="w-full border-t border-garage-border"></div>
                </span>
                <span className="relative px-2 bg-garage-surface">
                  {t('login.continueWithPassword')}
                </span>
              </button>
            )}
          </>
        )}

        {showPasswordForm && (
          <>
            {/* Username Field */}
            <div>
              <label htmlFor="username" className="block text-sm font-medium text-garage-text mb-2">
                {t('login.usernameOrEmail')}
              </label>
              <input
                id="username"
                type="text"
                {...registerField('username')}
                className={`w-full px-4 py-3 bg-garage-bg border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent ${
                  errors.username ? 'border-red-500' : 'border-garage-border'
                }`}
                placeholder={t('loginPage.usernamePlaceholder')}
                autoComplete="username"
                disabled={isSubmitting}
              />
              <FormError error={errors.username} />
            </div>

            {/* Password Field */}
            <div>
              <label htmlFor="password" className="block text-sm font-medium text-garage-text mb-2">
                {t('login.password')}
              </label>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  {...registerField('password')}
                  className={`w-full px-4 py-3 pr-12 bg-garage-bg border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent ${
                    errors.password ? 'border-red-500' : 'border-garage-border'
                  }`}
                  placeholder={t('loginPage.passwordPlaceholder')}
                  autoComplete="current-password"
                  disabled={isSubmitting}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 p-2 text-garage-text-muted hover:text-garage-text transition-colors"
                  aria-label={showPassword ? t('loginPage.hidePassword') : t('loginPage.showPassword')}
                  tabIndex={-1}
                >
                  {showPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                </button>
              </div>
              <FormError error={errors.password} />
            </div>

            {/* Submit Button */}
            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 btn-primary-auth font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSubmitting ? (
                <>
                  <Loader className="w-5 h-5 animate-spin" />
                  {t('loginPage.submitting')}
                </>
              ) : (
                <>
                  <LogIn className="w-5 h-5" />
                  {t('login.submit')}
                </>
              )}
            </button>
          </>
        )}
      </form>
    </AuthPageLayout>
  )
}
