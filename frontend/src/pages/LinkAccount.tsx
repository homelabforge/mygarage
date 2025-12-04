import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Car, Lock, AlertCircle, Loader } from 'lucide-react'
import api, { setCSRFToken } from '../services/api'
import { useAuth } from '../contexts/AuthContext'

export default function LinkAccount() {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { refreshUser } = useAuth()
  const token = searchParams.get('token')

  // Redirect to login if no token
  useEffect(() => {
    if (!token) {
      navigate('/login')
    }
  }, [token, navigate])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (!token) {
      setError('Link token is missing. Please restart the login process.')
      return
    }

    if (!password) {
      setError('Password is required')
      return
    }

    setIsLoading(true)

    try {
      const response = await api.post('/auth/oidc/link-account', {
        token,
        password,
      })

      // Set CSRF token from response
      if (response.data.csrf_token) {
        setCSRFToken(response.data.csrf_token)
      }

      // Refresh auth context to load user with JWT cookie
      // This ensures the user is authenticated before navigation
      await refreshUser()

      // JWT is already set as httpOnly cookie by backend
      // Navigate to redirect URL (default to dashboard)
      const redirectUrl = response.data.redirect_url || '/'
      navigate(redirectUrl)
    } catch (err) {
      // Display backend error message directly (contains specific errors)
      const error = err as { response?: { data?: { detail?: string } } }
      const errorMessage = error.response?.data?.detail || 'Failed to link account. Please try again.'
      setError(errorMessage)
    } finally {
      setIsLoading(false)
    }
  }

  const handleCancel = () => {
    navigate('/login')
  }

  if (!token) {
    return null // Will redirect via useEffect
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
            Link Your Account
          </h1>
          <p className="text-garage-text-muted">
            An existing account with this username was found. Please verify your password to link your SSO account.
          </p>
        </div>

        {/* Link Account Form */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-4 sm:p-6 md:p-8">
          <form onSubmit={handleSubmit} className="space-y-6">
            {/* Error Message */}
            {error && (
              <div className="p-4 bg-danger-500/10 border border-danger-500 rounded-lg flex items-start gap-2">
                <AlertCircle className="w-5 h-5 text-danger-500 flex-shrink-0 mt-0.5" />
                <div className="text-sm text-danger-500">{error}</div>
              </div>
            )}

            {/* Password Field */}
            <div>
              <label htmlFor="password" className="block text-sm font-medium text-garage-text mb-2">
                Password
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-garage-text-muted" />
                <input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full pl-10 pr-4 py-3 bg-garage-bg border border-garage-border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                  placeholder="Enter your password"
                  autoComplete="current-password"
                  autoFocus
                  disabled={isLoading}
                  required
                />
              </div>
            </div>

            {/* Buttons */}
            <div className="flex gap-3">
              <button
                type="button"
                onClick={handleCancel}
                className="flex-1 px-4 py-3 bg-garage-bg border border-garage-border text-garage-text font-medium rounded-lg hover:bg-garage-surface transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                disabled={isLoading}
              >
                Cancel
              </button>
              <button
                type="submit"
                className="flex-1 flex items-center justify-center gap-2 px-4 py-3 btn-primary font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                disabled={isLoading}
              >
                {isLoading ? (
                  <>
                    <Loader className="w-5 h-5 animate-spin" />
                    Linking...
                  </>
                ) : (
                  'Link Account'
                )}
              </button>
            </div>

            {/* Help Text */}
            <div className="text-center text-sm text-garage-text-muted">
              <p>
                Forgot your password?{' '}
                <a
                  href="/login"
                  className="text-primary hover:underline"
                >
                  Return to login
                </a>
              </p>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}
