import { useState, useEffect, useMemo } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { UserPlus, AlertCircle, CheckCircle, Loader, Crown, Eye, EyeOff } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { makeRegisterSchema, type RegisterFormData, getPasswordStrength } from '../schemas/auth'
import { FormError } from '../components/FormError'
import AuthPageLayout from '../components/AuthPageLayout'
import api from '../services/api'

export default function Register() {
  const { t } = useTranslation('common')
  // Zod bakes its messages in at construction, so the schema is rebuilt when
  // the language changes. Only the resolver depends on it — no fetch, no
  // reset() — so a rebuild can't discard what the user typed.
  const schema = useMemo(() => makeRegisterSchema(t), [t])
  const {
    register: registerField,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<RegisterFormData>({
    resolver: zodResolver(schema),
    mode: 'onBlur', // Validate on blur for better UX
  })
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)
  const [isFirstUser, setIsFirstUser] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  const { register: registerUser } = useAuth()
  const navigate = useNavigate()

  // Watch password for strength indicator
  const password = watch('password', '')

  // Check if this will be the first user
  useEffect(() => {
    api.get('/auth/users/count')
      .then(res => setIsFirstUser(res.data.count === 0))
      .catch(() => setIsFirstUser(false))
  }, [])

  // Calculate password strength using helper from schema. The level returned by
  // getPasswordStrength is a stable identifier ('weak' | 'medium' | 'strong') —
  // branch on it, never on the translated text.
  const passwordStrength = getPasswordStrength(password)
  const passwordStrengthLabel =
    passwordStrength.level === 'strong'
      ? t('registerPage.strength.strong')
      : passwordStrength.level === 'medium'
        ? t('registerPage.strength.medium')
        : t('registerPage.strength.weak')

  const onSubmit = async (data: RegisterFormData) => {
    setError('')

    try {
      await registerUser(data.username, data.email, data.password)
      setSuccess(true)
      setTimeout(() => {
        navigate('/login')
      }, 2000)
    } catch (err) {
      // Backend error text is rendered as-is; only the fallback is translated.
      setError(err instanceof Error ? err.message : t('registerPage.failed'))
    }
  }

  if (success) {
    return (
      <div className="min-h-screen bg-garage-bg flex items-center justify-center px-4">
        <div className="w-full max-w-md">
          <div className="bg-garage-surface rounded-lg border border-garage-border p-8 text-center">
            <div className="flex justify-center mb-4">
              <div className="p-4 bg-success-500/10 rounded-full">
                <CheckCircle className="w-12 h-12 text-success-500" />
              </div>
            </div>
            <h2 className="text-2xl font-bold text-garage-text mb-2">
              {t('registerPage.successTitle')}
            </h2>
            <p className="text-garage-text-muted mb-4">
              {isFirstUser
                ? t('registerPage.successAdminRedirect')
                : t('registerPage.successRedirect')}
            </p>
            <Loader className="w-6 h-6 animate-spin text-primary mx-auto" />
          </div>
        </div>
      </div>
    )
  }

  return (
    <AuthPageLayout
      subtitle={t('register.subtitle')}
      className="py-8"
      headerExtra={
        isFirstUser ? (
          <div className="mt-4 inline-flex items-center gap-2 px-4 py-2 bg-warning-500/10 border border-warning-500 rounded-full">
            <Crown className="w-5 h-5 text-warning-500" />
            <span className="text-sm font-medium text-warning-500">
              {t('registerPage.adminBadge')}
            </span>
          </div>
        ) : undefined
      }
      footerExtra={
        <div className="mt-6 text-center text-sm text-garage-text-muted">
          {t('register.hasAccount')}{' '}
          <Link to="/login" className="text-primary hover:underline font-medium">
            {t('register.loginLink')}
          </Link>
        </div>
      }
    >
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
        {/* Error Message */}
        {error && (
          <div className="p-4 bg-danger-500/10 border border-danger-500 rounded-lg flex items-start gap-2">
            <AlertCircle className="w-5 h-5 text-danger-500 flex-shrink-0 mt-0.5" />
            <div className="text-sm text-danger-500">{error}</div>
          </div>
        )}

        {/* Username Field */}
        <div>
          <label htmlFor="username" className="block text-sm font-medium text-garage-text mb-2">
            {t('register.username')}
          </label>
          <input
            id="username"
            type="text"
            {...registerField('username')}
            className={`w-full px-4 py-3 bg-garage-bg border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent ${
              errors.username ? 'border-red-500' : 'border-garage-border'
            }`}
            placeholder={t('registerPage.usernamePlaceholder')}
            autoComplete="username"
            disabled={isSubmitting}
          />
          <FormError error={errors.username} />
          {!errors.username && (
            <p className="mt-1 text-xs text-garage-text-muted">
              {t('registerPage.usernameHint')}
            </p>
          )}
        </div>

        {/* Email Field */}
        <div>
          <label htmlFor="email" className="block text-sm font-medium text-garage-text mb-2">
            {t('register.email')}
          </label>
          <input
            id="email"
            type="email"
            {...registerField('email')}
            className={`w-full px-4 py-3 bg-garage-bg border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent ${
              errors.email ? 'border-red-500' : 'border-garage-border'
            }`}
            placeholder="your.email@example.com"
            autoComplete="email"
            disabled={isSubmitting}
          />
          <FormError error={errors.email} />
        </div>

        {/* Password Field */}
        <div>
          <label htmlFor="password" className="block text-sm font-medium text-garage-text mb-2">
            {t('register.password')}
          </label>
          <div className="relative">
            <input
              id="password"
              type={showPassword ? 'text' : 'password'}
              {...registerField('password')}
              className={`w-full px-4 py-3 pr-12 bg-garage-bg border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent ${
                errors.password ? 'border-red-500' : 'border-garage-border'
              }`}
              placeholder={t('registerPage.passwordPlaceholder')}
              autoComplete="new-password"
              disabled={isSubmitting}
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-3 top-1/2 -translate-y-1/2 p-2 text-garage-text-muted hover:text-garage-text transition-colors"
              aria-label={
                showPassword ? t('registerPage.hidePassword') : t('registerPage.showPassword')
              }
              tabIndex={-1}
            >
              {showPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
            </button>
          </div>
          <FormError error={errors.password} />

          {/* Password Strength Indicator */}
          {password && !errors.password && (
            <div className="mt-2" aria-live="polite">
              <div className="flex items-center gap-2 mb-1">
                <div
                  className="flex-1 h-1.5 bg-garage-bg rounded-full overflow-hidden"
                  role="progressbar"
                  aria-valuenow={passwordStrength.score}
                  aria-valuemin={0}
                  aria-valuemax={6}
                  aria-label={t('registerPage.passwordStrength', {
                    strength: passwordStrengthLabel,
                  })}
                >
                  <div
                    className={`h-full transition-all duration-300 ${
                      passwordStrength.color.replace('text-', 'bg-')
                    }`}
                    style={{ width: `${(passwordStrength.score / 6) * 100}%` }}
                  />
                </div>
                <span className={`text-xs font-medium ${passwordStrength.color}`}>
                  {passwordStrengthLabel}
                </span>
              </div>
              <p className="text-xs text-garage-text-muted">
                {t('registerPage.passwordRequirements')}
              </p>
            </div>
          )}
        </div>

        {/* Confirm Password Field */}
        <div>
          <label htmlFor="confirmPassword" className="block text-sm font-medium text-garage-text mb-2">
            {t('registerPage.confirmPasswordLabel')}
          </label>
          <div className="relative">
            <input
              id="confirmPassword"
              type={showConfirmPassword ? 'text' : 'password'}
              {...registerField('confirmPassword')}
              className={`w-full px-4 py-3 pr-12 bg-garage-bg border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent ${
                errors.confirmPassword ? 'border-red-500' : 'border-garage-border'
              }`}
              placeholder={t('registerPage.confirmPasswordPlaceholder')}
              autoComplete="new-password"
              disabled={isSubmitting}
            />
            <button
              type="button"
              onClick={() => setShowConfirmPassword(!showConfirmPassword)}
              className="absolute right-3 top-1/2 -translate-y-1/2 p-2 text-garage-text-muted hover:text-garage-text transition-colors"
              aria-label={
                showConfirmPassword ? t('registerPage.hidePassword') : t('registerPage.showPassword')
              }
              tabIndex={-1}
            >
              {showConfirmPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
            </button>
          </div>
          <FormError error={errors.confirmPassword} />
        </div>

        {/* Submit Button */}
        <button
          type="submit"
          disabled={isSubmitting}
          className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-primary text-(--accent-on-solid) font-medium rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed mt-6"
        >
          {isSubmitting ? (
            <>
              <Loader className="w-5 h-5 animate-spin" />
              {t('registerPage.submitting')}
            </>
          ) : (
            <>
              <UserPlus className="w-5 h-5" />
              {t('register.submit')}
            </>
          )}
        </button>
      </form>
    </AuthPageLayout>
  )
}
