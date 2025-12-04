import { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Car, LogIn, AlertCircle, Loader, Eye, EyeOff, Shield } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useAppVersion } from '../hooks/useAppVersion'
import { loginSchema, type LoginFormData } from '../schemas/auth'
import { FormError } from '../components/FormError'

export default function Login() {
  const {
    register: registerField,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormData>({
    resolver: zodResolver(loginSchema),
  })
  const [error, setError] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [oidcEnabled, setOidcEnabled] = useState(false)
  const [oidcProviderName, setOidcProviderName] = useState('')
  const [oidcLoading, setOidcLoading] = useState(true)
  const { login } = useAuth()
  const navigate = useNavigate()
  const version = useAppVersion()

  // Check if OIDC is enabled
  useEffect(() => {
    const checkOIDC = async () => {
      try {
        const response = await fetch('/api/auth/oidc/config')
        const data = await response.json()
        setOidcEnabled(data.enabled || false)
        setOidcProviderName(data.provider_name || 'SSO')
      } catch {
        // OIDC not available, just use regular login
        setOidcEnabled(false)
      } finally {
        setOidcLoading(false)
      }
    }
    checkOIDC()
  }, [])

  const onSubmit = async (data: LoginFormData) => {
    setError('')

    try {
      await login(data.username, data.password)
      navigate('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed. Please try again.')
    }
  }

  const handleSSOLogin = () => {
    window.location.href = '/api/auth/oidc/login'
  }

  return (
    <div className="min-h-screen bg-garage-bg flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        {/* Logo and Header */}
        <div className="text-center mb-8">
          <div className="flex justify-center mb-4">
            <div className="p-4 bg-primary/10 rounded-full">
              <Car className="w-12 h-12 text-primary" />
            </div>
          </div>
          <h1 className="text-3xl font-bold text-garage-text mb-2">
            My<span className="text-primary">Garage</span>
          </h1>
          <p className="text-garage-text-muted">Sign in to your account</p>
        </div>

        {/* Login Form */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-4 sm:p-6 md:p-8">
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
            {/* Error Message */}
            {error && (
              <div className="p-4 bg-danger-500/10 border border-danger-500 rounded-lg flex items-start gap-2">
                <AlertCircle className="w-5 h-5 text-danger-500 flex-shrink-0 mt-0.5" />
                <div className="text-sm text-danger-500">{error}</div>
              </div>
            )}

            {/* SSO Button */}
            {!oidcLoading && oidcEnabled && (
              <>
                <button
                  type="button"
                  onClick={handleSSOLogin}
                  className="w-full flex items-center justify-center gap-2 px-4 py-3 btn-primary-auth font-medium rounded-lg transition-colors"
                >
                  <Shield className="w-5 h-5" />
                  Sign in with {oidcProviderName}
                </button>

                {/* Divider */}
                <div className="relative">
                  <div className="absolute inset-0 flex items-center">
                    <div className="w-full border-t border-garage-border"></div>
                  </div>
                  <div className="relative flex justify-center text-sm">
                    <span className="px-2 bg-garage-surface text-garage-text-muted">Or continue with password</span>
                  </div>
                </div>
              </>
            )}

            {/* Username Field */}
            <div>
              <label htmlFor="username" className="block text-sm font-medium text-garage-text mb-2">
                Username or Email
              </label>
              <input
                id="username"
                type="text"
                {...registerField('username')}
                className={`w-full px-4 py-3 bg-garage-bg border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent ${
                  errors.username ? 'border-red-500' : 'border-garage-border'
                }`}
                placeholder="Enter your username or email"
                autoComplete="username"
                disabled={isSubmitting}
              />
              <FormError error={errors.username} />
            </div>

            {/* Password Field */}
            <div>
              <label htmlFor="password" className="block text-sm font-medium text-garage-text mb-2">
                Password
              </label>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  {...registerField('password')}
                  className={`w-full px-4 py-3 pr-12 bg-garage-bg border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent ${
                    errors.password ? 'border-red-500' : 'border-garage-border'
                  }`}
                  placeholder="Enter your password"
                  autoComplete="current-password"
                  disabled={isSubmitting}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 p-2 text-garage-text-muted hover:text-garage-text transition-colors"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
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
                  Signing in...
                </>
              ) : (
                <>
                  <LogIn className="w-5 h-5" />
                  Sign In
                </>
              )}
            </button>
          </form>

          {/* Register Link */}
          <div className="mt-6 text-center text-sm text-garage-text-muted">
            Don't have an account?{' '}
            <Link to="/register" className="text-primary hover:underline font-medium">
              Create one here
            </Link>
          </div>
        </div>

        {/* Footer */}
        <div className="mt-8 text-center text-xs text-garage-text-muted">
          MyGarage v{version} • Self-hosted vehicle maintenance tracking
        </div>
      </div>
    </div>
  )
}
